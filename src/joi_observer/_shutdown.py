"""Private shared shutdown timing and ownership; no resource or process IO."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine, Iterable
from contextlib import suppress
from typing import Any


class ShutdownBudget:
    """One lazy absolute deadline, shared only by one collector lifetime."""

    def __init__(self) -> None:
        self.deadline: float | None = None

    def begin(self) -> float:
        if self.deadline is None:
            self.deadline = asyncio.get_running_loop().time() + 1.0
        return self.deadline

    def remaining(self) -> float:
        return max(0.0, self.begin() - asyncio.get_running_loop().time())


class _InlineCompletion:
    """Allocation-failure fallback that never owns an asyncio Task or Future."""

    def __init__(self) -> None:
        self._done = False
        self._callbacks = []

    def done(self) -> bool:
        return self._done

    def result(self) -> None:
        if not self._done:
            raise asyncio.InvalidStateError

    def cancelled(self) -> bool:
        return False

    def exception(self) -> None:
        return self.result()

    def add_done_callback(self, callback) -> None:
        if self._done:
            callback(self)
        else:
            self._callbacks.append(callback)

    def set_result(self, value: None) -> None:
        self._done = True
        callbacks, self._callbacks = self._callbacks, []
        for callback in callbacks:
            with suppress(BaseException):
                callback(self)


def cancel_once(task: asyncio.Task) -> None:
    """Do not interrupt a cooperative task a second time inside its finally."""
    if not task.done() and not task.cancelling():
        task.cancel()


def spawn(coroutine: Coroutine, *, name: str | None = None) -> asyncio.Task:
    """Register a Task through the ordinary allocator, closing rejected input.

    Closing a never-started coroutine does not release resources held elsewhere;
    its caller still owns those resources and must complete their cleanup.
    """
    try:
        return asyncio.create_task(coroutine, name=name)
    except BaseException:
        with suppress(BaseException):
            coroutine.close()
        raise


async def await_owner(task: asyncio.Future | _InlineCompletion) -> Any:
    """A cancelled waiter still joins the cleanup owner before propagating.

    The owner bounds its actual resource work. Cancelling only this wait cannot
    detach that work or allow an instance lock to be released prematurely.
    """
    cancelled = False
    allocation_error: BaseException | None = None
    polling = isinstance(task, _InlineCompletion)
    while not task.done():
        try:
            if polling:
                await asyncio.sleep(0)
            else:
                await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
        except BaseException as caught:
            if task.done():
                break
            # shield allocates its own bookkeeping Future. If that allocation
            # is refused, the resource owner still exists and must be joined.
            allocation_error = caught
            polling = True
    if allocation_error is not None:
        with suppress(BaseException):
            task.result()
        raise allocation_error
    if cancelled:
        with suppress(BaseException):
            task.result()
        raise asyncio.CancelledError
    return task.result()


async def join_tasks(tasks: Iterable[asyncio.Future]) -> list[Any]:
    """Join already registered work, including when gather cannot allocate.

    This accepts Tasks/Futures, never raw coroutines. The fallback does not
    allocate replacement Tasks and keeps the original gather failure visible.
    """
    registered = tuple(tasks)
    if not registered:
        return []
    if any(isinstance(task, _InlineCompletion) for task in registered):
        # Do not let gather turn a no-Future completion into an implicit Task.
        # All actual work was already started; serial joining keeps it owned.
        results = []
        error: BaseException | None = None
        for task in registered:
            try:
                results.append(await await_owner(task))
            except BaseException as caught:
                if task.cancelled():
                    results.append(caught)
                    continue
                try:
                    result = task.result()
                except BaseException as child_error:
                    results.append(child_error)
                    if child_error is not caught and error is None:
                        error = caught
                else:
                    results.append(result)
                    if error is None:
                        error = caught
        if error is not None:
            raise error
        return results
    try:
        group = asyncio.gather(*registered, return_exceptions=True)
    except BaseException:
        for task in registered:
            with suppress(BaseException):
                await await_owner(task)
        raise
    return await await_owner(group)


async def run_cleanup(factory: Callable[[], Coroutine], *, name: str | None = None,
                      publish: Callable[[asyncio.Future | _InlineCompletion], None]) -> None:
    """Publish cleanup ownership before allocating its optional Task.

    A refused owner Task falls back to a fresh coroutine in this caller. Other
    close callers join the published completion Future. It represents resource
    settlement only, so retrying close does not repeat a transient allocation
    failure. The allocating caller receives that original failure after cleanup.
    """
    try:
        completion = asyncio.get_running_loop().create_future()
    except BaseException:
        # Do not move a failed Task allocation into another mandatory owner
        # allocation. This plain completion also lets concurrent close waiters
        # join inline cleanup without waiting on the caller's entire run Task.
        completion = _InlineCompletion()
        try:
            with suppress(BaseException):
                publish(completion)
            with suppress(BaseException):
                await factory()
        finally:
            completion.set_result(None)
        raise
    try:
        publish(completion)
    except BaseException:
        try:
            with suppress(BaseException):
                await factory()
        finally:
            if not completion.done():
                completion.set_result(None)
        raise
    try:
        task = spawn(factory(), name=name)
    except BaseException:
        try:
            with suppress(BaseException):
                await factory()
        finally:
            if not completion.done():
                completion.set_result(None)
        raise
    def settled(owner: asyncio.Future) -> None:
        if not completion.done():
            completion.set_result(None)

    try:
        publish(task)
        task.add_done_callback(settled)
    except BaseException:
        # The resource owner already exists. A failed callback/registration
        # allocation cannot make it safe to return before that owner settles.
        try:
            with suppress(BaseException):
                await await_owner(task)
        finally:
            if not completion.done():
                completion.set_result(None)
        raise
    await await_owner(task)


async def cleanup_inline(factory: Callable[[], Coroutine], deadline: float,
                         *, reserve: float = 0.25) -> None:
    """Run an unallocated resource close within the existing shutdown budget."""
    timeout = max(0.0, deadline - asyncio.get_running_loop().time() - reserve)
    async with asyncio.timeout(timeout):
        await factory()


async def settle(tasks: set[asyncio.Task], deadline: float, *, reserve: float = 0.25) -> None:
    """Bound resource work, then cancel and join its actual finally blocks.

    Reserve up to the existing 250ms source cleanup allowance inside the total
    deadline. Outer lifecycle owners join this operation rather than imposing a
    second timeout on a shielded waiter. Ports must honor their cancel contract.
    """
    if not tasks:
        return
    try:
        # Let newly registered close operations acquire their resources before
        # a failed wait allocation could request cancellation of those Tasks.
        await asyncio.sleep(0)
        await asyncio.wait(tasks, timeout=max(
            0.0, deadline - asyncio.get_running_loop().time() - reserve))
    finally:
        for task in tasks:
            cancel_once(task)
        await join_tasks(tasks)
