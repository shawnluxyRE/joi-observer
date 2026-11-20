"""Real session outcomes stay intact across UI and transport-close races."""

import asyncio
from io import StringIO
import signal
import struct

import pytest

from joi_observer.cli import CommandDependencies, run_command
from joi_observer.ipc.client import ConnectionFailure, ConnectionState, SnapshotClient, UnixConnector
from joi_observer.tui.session import TuiClientSession
from test_client_session import MemoryTerminal
from test_ipc_client import MemoryStream, frame


DIAGNOSTIC = "Cannot connect to collector service. Run joi-observer again to retry."


class OfflineSession:
    """Replace OS/terminal boundaries; CLI, client, codec, app and session stay real."""

    def __init__(self, tmp_path, monkeypatch, *, cause=None, delayed=False, stale=False,
                 local_close_error=False):
        self.reader = MemoryStream(frame(stale=stale))
        self.closing = asyncio.Event()
        self.release_close = asyncio.Event()
        self.opens = []
        self.q_states = []
        self.close_states = []
        self.live_after_run = []
        self.close_hook = None
        owner = self

        class Writer:
            closed = False
            aborted = False

            def __init__(self):
                self.transport = self

            def close(self):
                self.closed = True
                owner.close_states.append(owner.client.state)
                owner.closing.set()

            async def wait_closed(self):
                if owner.close_hook is not None:
                    await owner.close_hook()
                if local_close_error:
                    raise OSError("PRIVATE-local-close-diagnostic")
                if delayed:
                    await owner.release_close.wait()

            def abort(self):
                self.closed = self.aborted = True
                owner.release_close.set()

        self.writer = Writer()

        async def open_stream(endpoint, **kwargs):
            self.opens.append((endpoint, kwargs))
            return self.reader, self.writer

        monkeypatch.setattr(asyncio, "open_unix_connection", open_stream)
        self.client = SnapshotClient(connector=UnixConnector(), timeout=0.08 if cause == "timeout" else 0.5)

        class Terminal(MemoryTerminal):
            def render(self, value):
                super().render(value)
                if len(self.frames) == 1:
                    if cause == "eof":
                        owner.reader.pending.put_nowait(None)
                    elif cause == "malformed":
                        owner.reader.pending.put_nowait(struct.pack(">Q", 1) + b"{")

            async def read_key(self, timeout):
                if cause is not None:
                    try:
                        async with asyncio.timeout(timeout):
                            await owner.closing.wait()
                    except TimeoutError:
                        return None
                    # The input is deliberately later than failure detection,
                    # independent of when the watcher receives its notification.
                    assert owner.client.state is ConnectionState.FAILED
                else:
                    await asyncio.sleep(0)
                owner.q_states.append(owner.client.state)
                return "q"

            def restore(self):
                super().restore()
                owner.release_close.set()

        self.terminal = Terminal()

        class TracedSession(TuiClientSession):
            async def run(self):
                try:
                    return await super().run()
                finally:
                    # Observe before asyncio.run can perform any global final
                    # cleanup. This wrapper never replaces a session result.
                    current = asyncio.current_task()
                    owner.live_after_run.append([
                        task.get_name() for task in asyncio.all_tasks()
                        if task is not current and not task.done()
                    ])

        self.session = TracedSession(self.client, self.terminal)

        class ErrorOutput(StringIO):
            def write(self, value):
                if value.strip():
                    assert owner.terminal.events[-1:] == ["restore"]
                return super().write(value)

        self.stdout, self.stderr = StringIO(), ErrorOutput()
        self.dependencies = CommandDependencies(
            tmp_path, tmp_path, True, True, "xterm-256color", self.stdout, self.stderr,
            lambda endpoint: self.session,
            lambda *args: pytest.fail("A client outcome must never construct a collector service"),
        )

    def run(self):
        return run_command([], dependencies=self.dependencies)

    def assert_closed(self):
        assert self.writer.closed and self.client.state is ConnectionState.CLOSED
        assert self.terminal.frames and self.terminal.events == ["enter", "restore"]
        assert len(self.opens) == 1
        assert self.live_after_run == [[]], "owned work must settle before the session returns"
        assert self.stdout.getvalue() == ""
        with pytest.raises(ConnectionFailure):
            self.client.snapshot()

    def assert_failed(self, result):
        self.assert_closed()
        assert result == 4
        assert self.q_states == [ConnectionState.FAILED]
        assert ConnectionState.FAILED in self.close_states
        assert self.stderr.getvalue().strip() == DIAGNOSTIC


@pytest.mark.parametrize("cause", ["eof", "malformed", "timeout"])
@pytest.mark.parametrize("delayed", [False, True], ids=["immediate-close", "delayed-close"])
def test_later_q_cannot_replace_any_latched_receive_failure(tmp_path, monkeypatch, cause, delayed):
    case = OfflineSession(tmp_path, monkeypatch, cause=cause, delayed=delayed)
    case.assert_failed(case.run())


def test_same_turn_completed_real_ui_and_watcher_preserve_failure(tmp_path, monkeypatch):
    case = OfflineSession(tmp_path, monkeypatch, cause="eof")
    original_wait = asyncio.wait
    completions = []

    async def wait_for_real_completions(tasks, *args, **kwargs):
        registered = tuple(tasks)
        names = {task.get_coro().__qualname__ for task in registered}
        if names == {"ObserverApp.run", "SnapshotClient.wait_failed"}:
            # Delay only the scheduler boundary. Both real tasks must finish;
            # their actual success/error results are returned unchanged.
            await original_wait(registered, *args, **kwargs)
            done, pending = await original_wait(registered, return_when=asyncio.ALL_COMPLETED, timeout=0.5)
            assert len(done) == 2 and not pending
            completions.append(done)
            return done, pending
        return await original_wait(registered, *args, **kwargs)

    monkeypatch.setattr(asyncio, "wait", wait_for_real_completions)
    case.assert_failed(case.run())
    assert len(completions) == 1


def test_real_eof_during_session_cleanup_join_is_not_erased_by_client_close(tmp_path, monkeypatch):
    import joi_observer.tui.session as session_module

    case = OfflineSession(tmp_path, monkeypatch)
    original_join = session_module.join_tasks
    injected = []

    async def join_then_deliver_eof(tasks):
        result = await original_join(tasks)
        assert case.q_states == [ConnectionState.CONNECTED]
        assert case.terminal.events == ["enter", "restore"]
        assert case.client.state is ConnectionState.CONNECTED
        # An external EOF reaches a still-connected receiver while the session
        # is awaiting its real cleanup join, before local client.close starts.
        case.reader.pending.put_nowait(None)
        await asyncio.wait_for(case.closing.wait(), 0.5)
        assert case.client.state is ConnectionState.FAILED
        injected.append(True)
        return result

    monkeypatch.setattr(session_module, "join_tasks", join_then_deliver_eof)
    result = case.run()
    case.assert_closed()
    assert injected == [True] and result == 4
    assert case.stderr.getvalue().strip() == DIAGNOSTIC


@pytest.mark.parametrize("owner", ["TuiClientSession._cleanup", "SnapshotClient._cleanup"])
def test_known_failure_keeps_its_outcome_when_cleanup_owner_allocation_is_rejected(
        tmp_path, monkeypatch, owner):
    case = OfflineSession(tmp_path, monkeypatch, cause="eof", delayed=True)
    original_create = asyncio.create_task
    rejected = []

    def create(coroutine, *args, **kwargs):
        if coroutine.cr_code.co_qualname == owner and not rejected:
            rejected.append(owner)
            raise MemoryError("PRIVATE-secondary-cleanup-allocation")
        return original_create(coroutine, *args, **kwargs)

    monkeypatch.setattr(asyncio, "create_task", create)
    case.assert_failed(case.run())
    assert rejected == [owner]


@pytest.mark.parametrize("stale,close_error", [(False, False), (True, False), (False, True)],
                         ids=["healthy", "source-stale", "local-close-error"])
def test_normal_q_in_a_connected_session_still_exits_zero(tmp_path, monkeypatch, stale, close_error):
    case = OfflineSession(tmp_path, monkeypatch, stale=stale, local_close_error=close_error)
    assert case.run() == 0
    case.assert_closed()
    assert case.q_states == [ConnectionState.CONNECTED]
    assert case.close_states == [ConnectionState.CLOSED]
    assert case.writer.aborted is close_error
    assert case.stderr.getvalue() == ""


def test_handled_caller_exception_does_not_hide_this_sessions_latched_failure(tmp_path, monkeypatch):
    case = OfflineSession(tmp_path, monkeypatch, cause="eof", delayed=True)

    async def scenario():
        try:
            raise ValueError("already handled by the caller")
        except ValueError:
            # An enclosing except block is not an error raised by this session.
            with pytest.raises(ConnectionFailure):
                await case.session.run()

    asyncio.run(scenario())
    case.assert_closed()
    assert case.q_states == [ConnectionState.FAILED]
    assert case.stderr.getvalue() == ""


@pytest.mark.parametrize("signum", [signal.SIGINT, signal.SIGTERM])
def test_signal_during_healthy_q_cleanup_keeps_signal_exit_after_resources_settle(
        tmp_path, monkeypatch, signum):
    case = OfflineSession(tmp_path, monkeypatch)
    originals = {selected: signal.getsignal(selected) for selected in (signal.SIGINT, signal.SIGTERM)}
    installed = dict(originals)
    delivered = []
    settled = []

    def install(selected, handler):
        previous = installed[selected]
        installed[selected] = handler
        return previous

    monkeypatch.setattr(signal, "signal", install)
    # asyncio.Runner also reads the currently installed handler while restoring
    # SIGINT. Keep both sides of this offline OS boundary consistent.
    monkeypatch.setattr(signal, "getsignal", lambda selected: installed[selected])

    async def close_with_signal():
        assert case.terminal.events == ["enter", "restore"]
        assert case.client.state is ConnectionState.CLOSED
        delivered.append(signum)
        installed[signum](signum, None)
        await asyncio.sleep(0.01)
        settled.append(True)

    case.close_hook = close_with_signal
    assert case.run() == 128 + signum
    case.assert_closed()
    assert delivered == [signum] and settled == [True]
    assert installed == originals and case.q_states == [ConnectionState.CONNECTED]
    assert case.stderr.getvalue() == ""


@pytest.mark.parametrize("stage", ["enter", "render", "read_key", "restore"])
def test_one_terminal_failure_cannot_stop_another_sessions_receive_or_render(stage):
    """AC-103 includes abnormal UI exit at each terminal lifecycle boundary."""
    from test_ipc_client import MemoryConnector

    async def scenario():
        original = RuntimeError("PRIVATE-terminal-" + stage)

        class FailingTerminal(MemoryTerminal):
            def enter(self):
                super().enter()
                if stage == "enter":
                    raise original

            def render(self, value):
                super().render(value)
                if stage == "render":
                    raise original

            async def read_key(self, timeout):
                if stage == "read_key":
                    raise original
                return "q"

            def restore(self):
                super().restore()
                if stage == "restore":
                    raise original

        left_stream, right_stream = MemoryStream(frame()), MemoryStream(frame())
        left_port, right_port = MemoryConnector(left_stream), MemoryConnector(right_stream)
        left_client = SnapshotClient(connector=left_port)
        right_client = SnapshotClient(connector=right_port)
        left_terminal, right_terminal = FailingTerminal(), MemoryTerminal()
        left_session = TuiClientSession(left_client, left_terminal)
        right_session = TuiClientSession(right_client, right_terminal)
        left = asyncio.create_task(left_session.run())
        right = asyncio.create_task(right_session.run())
        try:
            with pytest.raises(RuntimeError) as caught:
                await asyncio.wait_for(left, 2)
            assert caught.value is original
            assert left_stream.closed and left_client.state is ConnectionState.CLOSED
            assert left_terminal.events == ["enter", "restore"]
            assert not right.done() and not right_stream.closed

            # Supply a real subsequent wire frame only after the failed session
            # is fully closed. The surviving session must still decode and draw.
            right_stream.pending.put_nowait(frame(sequence=2, revision=1, stale=True))
            async with asyncio.timeout(2):
                while (right_client.state is not ConnectionState.CONNECTED
                       or right_client.envelope().sequence != 2
                       or not any("STALE" in cell.text
                                  for value in right_terminal.frames for cell in value.cells)):
                    await asyncio.sleep(0.005)
            assert right_client.snapshot().revision == 1
            assert right_client.snapshot().objects[0].stale
            assert not right.done() and not right_stream.closed
            right_terminal.keys.append("q")
            await asyncio.wait_for(right, 2)
        finally:
            for task in (left, right):
                if not task.done():
                    task.cancel()
            await asyncio.gather(left, right, return_exceptions=True)
        assert right_stream.closed and right_client.state is ConnectionState.CLOSED
        assert right_terminal.events == ["enter", "restore"]
        assert len(left_port.calls) == len(right_port.calls) == 1
        assert [task for task in asyncio.all_tasks()
                if task is not asyncio.current_task() and not task.done()] == []

    asyncio.run(scenario())


@pytest.mark.parametrize("initial_bytes,outcome", [
    pytest.param(size, outcome, id=f"{stage}-{outcome}")
    for size, stage in ((0, "no-frame"), (4, "partial-header"), (12, "partial-body"))
    for outcome in ("timeout", "sigint", "sigterm")
] + [pytest.param(None, "complete", id="complete-frame-normal-q")])
def test_first_frame_wait_has_safe_cli_outcome_without_entering_terminal(
        tmp_path, monkeypatch, initial_bytes, outcome):
    """Signals and an incomplete first frame must settle before CLI returns."""
    from test_ipc_client import MemoryConnector

    originals = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    installed = dict(originals)
    delivered, blocked_reads, live_after_run = [], [], []

    def install(number, handler):
        previous = installed[number]
        installed[number] = handler
        return previous

    monkeypatch.setattr(signal, "signal", install)
    monkeypatch.setattr(signal, "getsignal", lambda number: installed[number])
    signum = {"sigint": signal.SIGINT, "sigterm": signal.SIGTERM}.get(outcome)

    class PartialStream(MemoryStream):
        async def readexactly(self, count):
            if len(self.buffer) < count:
                blocked_reads.append(count)
                if signum is not None and not delivered:
                    delivered.append(signum)
                    # Only the OS signal-delivery boundary is substituted.
                    # _session's installed handler still cancels the real
                    # session and its first-frame receive task.
                    asyncio.get_running_loop().call_soon(installed[signum], signum, None)
            return await super().readexactly(count)

    payload = frame()
    stream = PartialStream()
    stream.buffer = payload if initial_bytes is None else payload[:initial_bytes]
    connector = MemoryConnector(stream)
    client = SnapshotClient(connector=connector, timeout=0.5 if initial_bytes is None else 0.03)
    terminal = MemoryTerminal(("q",))

    class ObservedSession(TuiClientSession):
        async def run(self):
            try:
                return await super().run()
            finally:
                live_after_run.append([
                    task.get_name() for task in asyncio.all_tasks()
                    if task is not asyncio.current_task() and not task.done()
                ])

    session = ObservedSession(client, terminal)
    stdout, stderr = StringIO(), StringIO()
    dependencies = CommandDependencies(
        tmp_path, tmp_path, True, True, "xterm-256color", stdout, stderr,
        lambda endpoint: session,
        lambda *args: pytest.fail("First-frame failure cannot start a collector"),
    )
    result = run_command([], dependencies=dependencies)
    expected = 0 if initial_bytes is None else (4 if signum is None else 128 + signum)
    assert result == expected
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == (DIAGNOSTIC + "\n" if outcome == "timeout" else "")
    assert len(connector.calls) == 1 and stream.closed
    assert client.state is ConnectionState.CLOSED and live_after_run == [[]]
    assert installed == originals
    with pytest.raises(ConnectionFailure):
        client.snapshot()
    if initial_bytes is None:
        assert terminal.events == ["enter", "restore"] and terminal.frames
        assert delivered == []
    else:
        assert terminal.events == [] and terminal.frames == []
        assert blocked_reads and delivered == ([] if signum is None else [signum])
