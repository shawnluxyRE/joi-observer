"""Writer allocation failures reject one event without poisoning later samples."""

import asyncio
import json
import threading

import pytest

from joi_observer.config import LogConfig
from joi_observer.error_log import ErrorLog
from test_error_log import GatedIO, MemoryIO, record, records


@pytest.mark.parametrize("stage", ["construct", "start"])
@pytest.mark.parametrize("error_type", [RuntimeError, OSError, MemoryError])
def test_writer_resource_failure_leaves_no_pending_or_throttle_and_can_retry(
        tmp_path, monkeypatch, capsys, stage, error_type):
    unavailable = [True]
    attempts = []
    threads = []
    real_thread = threading.Thread
    real_start = real_thread.start

    def construct(*args, **kwargs):
        if kwargs.get("name") == "joi-observer-error-log":
            if stage == "construct":
                attempts.append(None)
                if unavailable[0]:
                    raise error_type("injected unavailable writer resource")
            thread = real_thread(*args, **kwargs)
            threads.append(thread)
            return thread
        return real_thread(*args, **kwargs)

    def start(thread):
        if thread.name == "joi-observer-error-log" and stage == "start":
            attempts.append(None)
            if unavailable[0]:
                raise error_type("injected unavailable writer resource")
        return real_start(thread)

    monkeypatch.setattr(threading, "Thread", construct)
    monkeypatch.setattr(real_thread, "start", start)

    async def scenario():
        io = MemoryIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        assert log.prepare()
        try:
            assert not record(log, 0)
            assert await log.flush(timeout=0.01)
            assert not record(log, 1)
            assert await log.flush(timeout=0.01)
            assert len(attempts) == 2 and io.lines == []

            unavailable[0] = False
            assert record(log, 2), "a rejected event must not reserve its throttle fingerprint"
            assert await log.flush(timeout=0.5)
            assert len(attempts) == 3
            written = records(io)
            assert len(written) == 1 and written[0]["time"].endswith("18:00:02")
            assert not record(log, 3)  # A successfully accepted event still throttles.
            assert record(log, 3, target="independent")
            assert await log.flush(timeout=0.5)
            assert len(attempts) == 3  # Both admitted events share one writer.
            assert [item["object_id"] for item in records(io)] == ["chat", "independent"]
        finally:
            assert await log.close(timeout=0.5)

            async def stopped():
                while any(thread.is_alive() for thread in threads):
                    await asyncio.sleep(0.001)

            await asyncio.wait_for(stopped(), 0.5)

    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_close_after_rejected_start_does_not_wait_for_a_phantom_event(tmp_path, monkeypatch):
    attempts = []
    real_start = threading.Thread.start

    def start(thread):
        if thread.name == "joi-observer-error-log":
            attempts.append(None)
            raise RuntimeError("injected writer exhaustion")
        return real_start(thread)

    monkeypatch.setattr(threading.Thread, "start", start)

    async def scenario():
        io = MemoryIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        assert log.prepare()
        assert not record(log, 0)
        assert await asyncio.wait_for(log.close(timeout=0.01), 0.1)
        assert await log.close(timeout=0.01)
        assert not record(log, 1, target="after-close")
        assert len(attempts) == 1 and io.lines == []

    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["construct", "start"])
def test_unexpected_writer_programming_error_is_not_silenced(tmp_path, monkeypatch, stage):
    real_thread = threading.Thread
    real_start = real_thread.start

    def construct(*args, **kwargs):
        if stage == "construct" and kwargs.get("name") == "joi-observer-error-log":
            raise ValueError("injected programming error")
        return real_thread(*args, **kwargs)

    def start(thread):
        if stage == "start" and thread.name == "joi-observer-error-log":
            raise ValueError("injected programming error")
        return real_start(thread)

    monkeypatch.setattr(threading, "Thread", construct)
    monkeypatch.setattr(real_thread, "start", start)

    async def scenario():
        log = ErrorLog(LogConfig(directory=tmp_path), io=MemoryIO())
        assert log.prepare()
        with pytest.raises(ValueError, match="programming error"):
            record(log, 0)
        assert await log.flush(timeout=0.01)
        assert await log.close(timeout=0.01)

    asyncio.run(scenario())


async def eventually(predicate):
    async with asyncio.timeout(0.5):
        while not predicate():
            await asyncio.sleep(0.001)


class PartialStart:
    """Use a real OS thread whose Thread.start handshake raises first."""

    def __init__(self, monkeypatch):
        self.threads = []
        self.release_bootstrap = threading.Event()
        self.started_before_failure = None
        real_start = threading.Thread.start
        real_spawn = threading._start_new_thread

        def spawn(function, args):
            owner = getattr(function, "__self__", None)
            if self.threads and owner is self.threads[0]:
                def delayed_bootstrap():
                    self.release_bootstrap.wait(2)
                    function(*args)
                return real_spawn(delayed_bootstrap, ())
            return real_spawn(function, args)

        def start(thread):
            if thread.name != "joi-observer-error-log":
                return real_start(thread)
            self.threads.append(thread)
            if len(self.threads) != 1:
                return real_start(thread)
            real_wait = thread._started.wait

            def fail_wait(timeout=None):
                self.started_before_failure = thread._started.is_set()
                raise MemoryError("injected Thread.start handshake waiter failure")

            thread._started.wait = fail_wait
            try:
                return real_start(thread)
            finally:
                thread._started.wait = real_wait

        monkeypatch.setattr(threading.Thread, "start", start)
        monkeypatch.setattr(threading, "_start_new_thread", spawn)

    def first_exited(self):
        # False is_alive alone cannot distinguish a delayed bootstrap from
        # a never-created thread. Require that the real bootstrap ran first.
        first = self.threads[0]
        return first._started.is_set() and not first.is_alive()

    def all_exited(self):
        return all(thread._started.is_set() and not thread.is_alive() for thread in self.threads)


@pytest.mark.parametrize("release_before_retry", [True, False])
def test_failed_handshake_candidate_cannot_consume_a_retry_queue(
        tmp_path, monkeypatch, release_before_retry):
    race = PartialStart(monkeypatch)

    class ObservedIO(GatedIO):
        def __init__(self):
            super().__init__()
            self.entered = []

        def append(self, config, line):
            self.entered.append(json.loads(line)["object_id"])
            super().append(config, line)

    async def scenario():
        io = ObservedIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        assert log.prepare()
        try:
            assert not record(log, 0)
            assert race.started_before_failure is False
            assert await log.flush(timeout=0.01)
            if release_before_retry:
                race.release_bootstrap.set()
                await eventually(race.first_exited)

            assert record(log, 1)  # The same fingerprint is immediately retryable.
            await eventually(io.started.is_set)
            assert record(log, 2, target="queued")
            if not release_before_retry:
                race.release_bootstrap.set()
                await eventually(race.first_exited)

            # The admitted writer is blocked in its first append. A failed
            # candidate must exit, rather than consume the queued second event.
            assert io.entered == ["chat"]
            io.release.set()
            assert await log.flush(timeout=0.5)
            assert [item["object_id"] for item in records(io)] == ["chat", "queued"]
            assert await log.close(timeout=0.5)
            await eventually(race.all_exited)
        finally:
            io.release.set()
            race.release_bootstrap.set()
            await log.close(timeout=0.5)
            await eventually(race.all_exited)

    asyncio.run(scenario())


def test_rejected_candidate_bootstrapping_after_close_exits_without_waiting(tmp_path, monkeypatch):
    race = PartialStart(monkeypatch)

    async def scenario():
        io = MemoryIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        assert log.prepare()
        try:
            assert not record(log, 0)
            assert race.started_before_failure is False
            assert not race.threads[0]._started.is_set()
            assert await log.close(timeout=0.01)
            assert not record(log, 1)
            # close cannot make an OS thread that has not been scheduled
            # physically disappear. Its eventual entry must have no side effect.
            race.release_bootstrap.set()
            await eventually(race.all_exited)
            assert io.lines == []
        finally:
            race.release_bootstrap.set()
            await log.close(timeout=0.5)
            await eventually(race.all_exited)

    asyncio.run(scenario())


def test_admitted_writer_delayed_until_close_still_drains_accepted_events(tmp_path, monkeypatch):
    real_thread = threading.Thread
    entered, release = threading.Event(), threading.Event()
    threads = []

    def construct(*args, **kwargs):
        if kwargs.get("name") == "joi-observer-error-log":
            target = kwargs["target"]

            def delayed_target(*target_args):
                entered.set()
                release.wait(2)
                target(*target_args)

            kwargs["target"] = delayed_target
            thread = real_thread(*args, **kwargs)
            threads.append(thread)
            return thread
        return real_thread(*args, **kwargs)

    monkeypatch.setattr(threading, "Thread", construct)

    async def scenario():
        io = MemoryIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        closing = None
        assert log.prepare()
        try:
            assert record(log, 0)
            await eventually(entered.is_set)
            closing = asyncio.create_task(log.close(timeout=0.5))
            await asyncio.sleep(0)
            assert not closing.done() and io.lines == []
            release.set()
            assert await closing
            assert [item["object_id"] for item in records(io)] == ["chat"]
            await eventually(lambda: all(not thread.is_alive() for thread in threads))
        finally:
            release.set()
            if closing is not None:
                await asyncio.gather(closing, return_exceptions=True)
            await log.close(timeout=0.5)
            await eventually(lambda: all(not thread.is_alive() for thread in threads))

    asyncio.run(scenario())
