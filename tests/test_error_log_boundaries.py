"""日志异步回调、容量边界与有界退出的离线行为补证。"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import threading

import pytest

from joi_observer.config import LogConfig
from joi_observer.error_log import ErrorKind, ErrorLog, Failure, FileLogIO


NOW = datetime(2026, 10, 28, 18, 0, tzinfo=timezone(timedelta(hours=8)))
FAILURE = Failure(ErrorKind.TIMEOUT, "collection.timeout", "private detail")


def emit(log, second, target="chat"):
    return log.record(
        "vllm", target, FAILURE, monotonic_time=second,
        occurred_at=NOW + timedelta(seconds=second),
    )


async def wait_started(event):
    for _ in range(1000):
        if event.is_set():
            return
        await asyncio.sleep(0.001)
    pytest.fail("Local file IO boundary did not start.")


class TwoStageIO:
    """两次写入可分别释放，第一条可在新轮次入队后报告失败。"""

    def __init__(self, *, first_fails=False):
        self.first_fails = first_fails
        self.started = [threading.Event(), threading.Event()]
        self.release = [threading.Event(), threading.Event()]
        self.calls = 0
        self.lines = []

    def prepare(self, directory):
        pass

    def append(self, config, line):
        index = self.calls
        self.calls += 1
        if index < 2:
            self.started[index].set()
            if not self.release[index].wait(2):
                raise OSError("Test gate timed out.")
        if index == 0 and self.first_fails:
            raise OSError("Injected old write failure.")
        self.lines.append(line)

    def unblock(self):
        for gate in self.release:
            gate.set()


@pytest.mark.parametrize("recover", [False, True])
def test_old_failed_write_cannot_cancel_a_new_reservation(tmp_path, recover):
    async def scenario():
        io = TwoStageIO(first_fails=True)
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        try:
            assert log.prepare()
            assert emit(log, 0)
            await wait_started(io.started[0])
            if recover:
                log.recovered("vllm", "chat")
            next_time = 1 if recover else 60
            assert emit(log, next_time)
            io.release[0].set()
            await wait_started(io.started[1])
            assert not emit(log, next_time + 1)
            io.release[1].set()
            assert await log.flush()
            assert len(io.lines) == 1
            assert json.loads(io.lines[0])["time"] == (
                NOW + timedelta(seconds=next_time)
            ).strftime("%Y-%m-%d %H:%M:%S")
        finally:
            io.unblock()
            await log.close()
    asyncio.run(scenario())


def test_flush_waits_only_for_records_accepted_before_the_call(tmp_path):
    async def scenario():
        io = TwoStageIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        try:
            assert log.prepare()
            assert emit(log, 0, "first")
            await wait_started(io.started[0])
            flushing = asyncio.create_task(log.flush(timeout=0.2))
            await asyncio.sleep(0)
            assert emit(log, 1, "second")
            io.release[0].set()
            await wait_started(io.started[1])
            assert await flushing
            assert len(io.lines) == 1
        finally:
            io.unblock()
            await log.close()
    asyncio.run(scenario())


def test_close_timeout_discards_unstarted_records_and_stays_closed(tmp_path):
    async def scenario():
        io = TwoStageIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        try:
            assert log.prepare()
            assert emit(log, 0, "in-progress")
            await wait_started(io.started[0])
            assert emit(log, 1, "queued")
            assert not await log.close(timeout=0.01)
            assert not emit(log, 2, "new")
            io.unblock()
            assert await log.close()
            assert [json.loads(line)["object_id"] for line in io.lines] == ["in-progress"]
            assert not log.prepare()
        finally:
            io.unblock()
            await log.close()
    asyncio.run(scenario())


def test_equal_size_is_allowed_before_next_append_rotates(tmp_path):
    config = LogConfig(directory=tmp_path, max_bytes=1024, backup_count=2)
    io = FileLogIO()
    io.prepare(tmp_path)
    line = b'{"level":"ERROR"}\n'
    initial = b"x" * (1024 - len(line))
    (tmp_path / "error.log").write_bytes(initial)
    io.append(config, line)
    assert (tmp_path / "error.log").read_bytes() == initial + line
    assert not (tmp_path / "error.log.1").exists()
    io.append(config, line)
    assert (tmp_path / "error.log.1").read_bytes() == initial + line
    assert (tmp_path / "error.log").read_bytes() == line


def test_existing_oversized_log_is_rotated_without_truncation(tmp_path):
    config = LogConfig(directory=tmp_path, max_bytes=1024, backup_count=2)
    oversized = b"old entry\n" * 200
    (tmp_path / "error.log").write_bytes(oversized)
    io = FileLogIO()
    io.prepare(tmp_path)
    assert (tmp_path / "error.log").read_bytes() == oversized
    line = b'{"level":"ERROR"}\n'
    io.append(config, line)
    assert (tmp_path / "error.log.1").read_bytes() == oversized
    assert (tmp_path / "error.log").read_bytes() == line


def test_non_regular_log_target_is_rejected_silently(tmp_path, capsys):
    (tmp_path / "error.log").mkdir()
    log = ErrorLog(LogConfig(directory=tmp_path))
    assert not log.prepare()
    assert asyncio.run(log.close())
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("collector,object_id", [
    ("A", "chat"), ("vllm", ""), ("vllm", "line\nbreak"),
    ("x" * 33, "chat"), ("vllm", "x" * 129), ("vllm", "bad\ud800"),
])
def test_invalid_identity_is_rejected_without_creating_log(tmp_path, collector, object_id):
    log = ErrorLog(LogConfig(directory=tmp_path))
    with pytest.raises(ValueError):
        log.record(collector, object_id, FAILURE, monotonic_time=0, occurred_at=NOW)
    assert not (tmp_path / "error.log").exists()
    assert asyncio.run(log.close())


FAILURE_TIME = datetime(2026, 10, 29, 12, tzinfo=timezone(timedelta(hours=8)))
TIMEOUT = Failure(ErrorKind.TIMEOUT, "collection.timeout", "PRIVATE response")


class MemoryIO:
    def __init__(self):
        self.lines = []

    def prepare(self, directory):
        pass

    def append(self, config, line):
        self.lines.append(line)


def emit_failure(log, second, *, collector="vllm", object_id="chat", failure=TIMEOUT):
    return log.record(
        collector, object_id, failure, monotonic_time=second,
        occurred_at=FAILURE_TIME + timedelta(seconds=second),
    )


@pytest.mark.parametrize("kind,code,reason", [
    (ErrorKind.TIMEOUT, "collection.timeout", "Collection timed out."),
    (ErrorKind.PERMISSION, "access.denied", "Permission denied."),
    (ErrorKind.NOT_FOUND, "object.not_found", "Configured object was not found."),
    (ErrorKind.PARSE, "response.invalid", "Invalid collection response."),
    (ErrorKind.UNAVAILABLE, "source.unavailable", "Data source is unavailable."),
    (ErrorKind.UNEXPECTED, "collector.unexpected", "Unexpected collector failure."),
])
def test_each_registered_failure_emits_its_fixed_reason(tmp_path, capsys, kind, code, reason):
    """Every registered failure retains diagnostic meaning without free-text payloads."""
    async def scenario():
        io = MemoryIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        try:
            assert log.prepare()
            assert emit_failure(log, 0, failure=Failure(kind, code, "PRIVATE prompt and secret"))
            assert await log.flush()
            [entry] = [json.loads(line) for line in io.lines]
            assert entry == {
                "time": "2026-10-29 12:00:00", "level": "ERROR",
                "collector": "vllm", "object_id": "chat", "kind": kind.value,
                "code": code, "reason": reason,
            }
        finally:
            assert await log.close()
    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_mismatched_and_unknown_failures_share_normalized_throttle(tmp_path):
    """Input variations cannot turn the same normalized unexpected error into new errors."""
    async def scenario():
        io = MemoryIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        try:
            assert log.prepare()
            mismatch = Failure(ErrorKind.PERMISSION, "collection.timeout", "PRIVATE one")
            unknown = Failure(ErrorKind.PARSE, "private.unregistered", "PRIVATE two")
            expected = Failure(ErrorKind.UNEXPECTED, "collector.unexpected", "PRIVATE three")
            assert emit_failure(log, 0, failure=mismatch)
            assert not emit_failure(log, 1, failure=unknown)
            assert not emit_failure(log, 59, failure=expected)
            assert emit_failure(log, 60, failure=expected)
            assert await log.flush()
            entries = [json.loads(line) for line in io.lines]
            assert len(entries) == 2
            assert all(entry["kind"] == "unexpected" for entry in entries)
            assert all(entry["code"] == "collector.unexpected" for entry in entries)
            assert b"PRIVATE" not in b"".join(io.lines)
        finally:
            assert await log.close()
    asyncio.run(scenario())


def test_recovery_resets_only_matching_collector_and_object(tmp_path):
    """A healthy object's recovery must not unthrottle other failing objects or sources."""
    async def scenario():
        io = MemoryIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        try:
            assert log.prepare()
            for collector, object_id in (("vllm", "chat"), ("vllm", "embedding"), ("docker", "chat")):
                assert emit_failure(log, 0, collector=collector, object_id=object_id)
            assert await log.flush()
            log.recovered("vllm", "chat")
            log.recovered("vllm", "never-failed")
            assert emit_failure(log, 1)
            assert not emit_failure(log, 1, object_id="embedding")
            assert not emit_failure(log, 1, collector="docker")
            assert await log.flush()
            entries = [json.loads(line) for line in io.lines]
            assert [(entry["collector"], entry["object_id"]) for entry in entries] == [
                ("vllm", "chat"), ("vllm", "embedding"), ("docker", "chat"), ("vllm", "chat"),
            ]
        finally:
            assert await log.close()
    asyncio.run(scenario())


def test_unavailable_log_directory_recovers_on_next_failure_without_backfill(tmp_path, capsys):
    """A real local path obstruction stays silent and does not disable future logging."""
    async def scenario():
        directory = tmp_path / "logs"
        log = ErrorLog(LogConfig(directory=directory))
        try:
            assert log.prepare()
            (directory / "error.log").unlink()
            directory.rmdir()
            directory.write_bytes(b"temporary non-directory obstruction")
            assert emit_failure(log, 0)
            assert await log.flush()
            assert directory.read_bytes() == b"temporary non-directory obstruction"
            directory.unlink()
            assert emit_failure(log, 1)
            assert await log.flush()
            entries = [json.loads(line) for line in (directory / "error.log").read_text(encoding="utf-8").splitlines()]
            assert len(entries) == 1
            assert entries[0]["time"] == "2026-10-29 12:00:01"
        finally:
            assert await log.close()
    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")
