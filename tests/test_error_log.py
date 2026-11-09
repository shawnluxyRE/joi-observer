"""REQ-001 日志黑盒契约；只替换文件系统边界，不替换被测限频/队列业务。"""

from __future__ import annotations

import asyncio
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from joi_observer.config import LogConfig
from joi_observer.error_log import ErrorKind, ErrorLog, Failure


# 固定模拟服务器本地时间，不依赖测试执行机时区，也不将日志时间转成 UTC。
NOW = datetime(2026, 10, 28, 18, 0, tzinfo=timezone(timedelta(hours=8)))
TIMEOUT = Failure(ErrorKind.TIMEOUT, "collection.timeout", "Collection timed out.")
PERMISSION = Failure(ErrorKind.PERMISSION, "access.denied", "Permission denied.")


class MemoryIO:
    """离线文件系统替身；只保存传给IO的字节，并模拟OS写入失败。"""

    def __init__(self) -> None:
        self.lines: list[bytes] = []
        self.prepare_failure = False
        self.append_failure = False
        self.prepared: list[Path] = []

    def prepare(self, directory: Path) -> None:
        self.prepared.append(directory)
        if self.prepare_failure:
            raise PermissionError("injected private file-system detail")

    def append(self, config: LogConfig, line: bytes) -> None:
        if self.append_failure:
            raise OSError("injected private file-system detail")
        self.lines.append(line)


class GatedIO(MemoryIO):
    """用门闩模拟慢磁盘，测试结束始终释放，避免遗留线程。"""

    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def append(self, config: LogConfig, line: bytes) -> None:
        self.started.set()
        if not self.release.wait(2):
            raise OSError("test disk gate timed out")
        super().append(config, line)


def records(io: MemoryIO) -> list[dict]:
    return [json.loads(line) for line in io.lines]


def record(log: ErrorLog, seconds: float, *, source="vllm", target="chat", failure=TIMEOUT):
    return log.record(
        source, target, failure,
        monotonic_time=seconds,
        occurred_at=NOW + timedelta(seconds=seconds),
    )


def test_constructor_has_no_file_system_side_effects(tmp_path):
    target = tmp_path / "not-created"
    io = MemoryIO()
    ErrorLog(LogConfig(directory=target), io=io)
    assert io.prepared == []
    assert not target.exists()


@pytest.mark.parametrize("collector,object_id", [
    ("hardware", "gpu-0"), ("storage", "/data"),
    ("docker", "container-1"), ("vllm", "chat"),
])
def test_first_error_has_only_required_error_fields(tmp_path, collector, object_id):
    async def scenario():
        io = MemoryIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        assert log.prepare()
        assert record(log, 0, source=collector, target=object_id)
        assert await log.flush()
        [entry] = records(io)
        assert set(entry) == {"time", "level", "collector", "object_id", "kind", "code", "reason"}
        assert entry["time"] == "2026-10-28 18:00:00"
        assert entry == {
            **entry, "level": "ERROR", "collector": collector, "object_id": object_id,
            "kind": "timeout", "code": "collection.timeout", "reason": "Collection timed out.",
        }
        assert await log.close()
    asyncio.run(scenario())


def test_0_through_59_suppressed_and_60_allowed(tmp_path):
    async def scenario():
        io = MemoryIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        assert log.prepare()
        assert record(log, 0)
        for second in range(1, 60):
            assert not record(log, second)
        assert record(log, 60)
        assert await log.flush()
        assert [e["time"] for e in records(io)] == ["2026-10-28 18:00:00", "2026-10-28 18:01:00"]
        assert await log.close()
    asyncio.run(scenario())


def test_new_source_object_or_error_is_immediate_and_a_b_a_stays_limited(tmp_path):
    async def scenario():
        io = MemoryIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        assert log.prepare()
        assert record(log, 0)
        assert record(log, 1, source="hardware")
        assert record(log, 2, target="embedding")
        assert record(log, 3, failure=PERMISSION)
        assert not record(log, 4)
        assert await log.flush()
        assert len(records(io)) == 4
        assert await log.close()
    asyncio.run(scenario())


def test_dynamic_reason_does_not_bypass_limit_or_leak_payload(tmp_path):
    async def scenario():
        io = MemoryIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        assert log.prepare()
        secret = "Authorization: Bearer secret-token; prompt=private-model-input; https://user:pass@host"
        assert record(log, 0, failure=Failure(ErrorKind.TIMEOUT, "collection.timeout", secret))
        assert not record(log, 1, failure=Failure(ErrorKind.TIMEOUT, "collection.timeout", "timestamp=123 changed"))
        assert await log.flush()
        assert records(io)[0]["reason"] == "Collection timed out."
        raw = b"".join(io.lines).decode()
        for private in ("secret-token", "private-model-input", "user:pass", "Authorization", "timestamp"):
            assert private not in raw
        assert await log.close()
    asyncio.run(scenario())


def test_unknown_error_code_is_safe_fixed_unexpected_category(tmp_path):
    async def scenario():
        io = MemoryIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        assert log.prepare()
        assert record(log, 0, failure=Failure(ErrorKind.PARSE, "token=secret", "response body"))
        assert await log.flush()
        [entry] = records(io)
        assert (entry["kind"], entry["code"], entry["reason"]) == (
            "unexpected", "collector.unexpected", "Unexpected collector failure.",
        )
        assert "secret" not in b"".join(io.lines).decode()
        assert await log.close()
    asyncio.run(scenario())


def test_recovery_clears_all_errors_and_itself_emits_nothing(tmp_path):
    async def scenario():
        io = MemoryIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        assert log.prepare()
        assert record(log, 0)
        assert record(log, 1, failure=PERMISSION)
        assert await log.flush()
        log.recovered("vllm", "chat")
        log.recovered("vllm", "never-failed")
        assert await log.flush()
        assert len(io.lines) == 2
        assert record(log, 2)
        assert record(log, 3, failure=PERMISSION)
        assert await log.flush()
        assert len(io.lines) == 4
        assert await log.close()
    asyncio.run(scenario())


def test_wall_clock_change_does_not_change_monotonic_throttle(tmp_path):
    async def scenario():
        io = MemoryIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        assert log.prepare()
        assert record(log, 0)
        assert not log.record("vllm", "chat", TIMEOUT, monotonic_time=1, occurred_at=NOW + timedelta(days=1))
        assert log.record("vllm", "chat", TIMEOUT, monotonic_time=60, occurred_at=NOW - timedelta(days=1))
        assert await log.flush()
        assert len(io.lines) == 2
        assert [e["time"] for e in records(io)] == ["2026-10-28 18:00:00", "2026-10-27 18:00:00"]
        assert await log.close()
    asyncio.run(scenario())


def test_prepare_failure_is_silent_and_later_samples_retry_without_backfill(tmp_path, capsys):
    async def scenario():
        io = MemoryIO()
        io.prepare_failure = True
        io.append_failure = True
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        assert not log.prepare()
        assert record(log, 0)
        assert await log.flush()
        assert io.lines == []
        io.prepare_failure = False
        io.append_failure = False
        assert record(log, 1)
        assert await log.flush()
        assert len(io.lines) == 1
        assert records(io)[0]["time"] == "2026-10-28 18:00:01"
        assert await log.close()
    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_runtime_write_failure_does_not_reserve_full_60_seconds(tmp_path, capsys):
    async def scenario():
        io = MemoryIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        assert log.prepare()
        io.append_failure = True
        assert record(log, 0)
        assert await log.flush()
        io.append_failure = False
        assert record(log, 1)
        assert await log.flush()
        assert len(io.lines) == 1
        assert await log.close()
    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_slow_disk_queue_is_bounded_and_does_not_block_event_loop(tmp_path):
    async def scenario():
        io = GatedIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io, queue_capacity=2)
        try:
            assert log.prepare()
            assert record(log, 0, target="first")
            for _ in range(100):
                if io.started.is_set():
                    break
                await asyncio.sleep(0.001)
            assert io.started.is_set()
            assert record(log, 1, target="second")
            assert record(log, 2, target="third")
            assert not record(log, 3, target="fourth")
            # 有界 flush 返回期间 loop 仍可执行；队满不阻塞或挤占采集线程池。
            assert not await log.flush(timeout=0.01)
            io.release.set()
            assert await log.flush()
            assert record(log, 4, target="fourth")
            assert await log.flush()
            assert len(io.lines) == 4
            assert await log.close()
        finally:
            io.release.set()
    asyncio.run(scenario())


def test_real_directory_creation_append_only_error_and_no_console(tmp_path, capsys):
    async def scenario():
        directory = tmp_path / "custom" / "nested"
        config = LogConfig(directory=directory)
        log = ErrorLog(config)
        assert log.prepare()
        assert (directory / "error.log").read_bytes() == b""
        assert record(log, 0)
        assert await log.close()
        old = (directory / "error.log").read_bytes()
        restarted = ErrorLog(config)
        assert restarted.prepare()
        assert record(restarted, 0, target="embedding")
        assert await restarted.close()
        current = (directory / "error.log").read_bytes()
        assert current.startswith(old)
        assert len(current.splitlines()) == 2
        assert all(json.loads(line)["level"] == "ERROR" for line in current.splitlines())
    asyncio.run(scenario())
    assert capsys.readouterr() == ("", "")


def test_size_rotation_retains_only_configured_backups_and_latest_error(tmp_path):
    async def scenario():
        log = ErrorLog(LogConfig(directory=tmp_path, max_bytes=1024, backup_count=2))
        assert log.prepare()
        for number in range(30):
            assert record(log, number, target=f"model-{number}")
            assert await log.flush()
        assert await log.close()
        files = sorted(tmp_path.glob("error.log*"))
        assert {p.name for p in files} == {"error.log", "error.log.1", "error.log.2"}
        assert all(0 < p.stat().st_size <= 1024 for p in files)
        retained = [json.loads(line) for p in files for line in p.read_bytes().splitlines()]
        assert len(retained) < 30
        assert not any(entry["object_id"] == "model-0" for entry in retained)
        assert json.loads((tmp_path / "error.log").read_bytes().splitlines()[-1])["object_id"] == "model-29"
    asyncio.run(scenario())


def test_close_is_idempotent_and_refuses_new_records(tmp_path):
    async def scenario():
        io = MemoryIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        assert log.prepare()
        assert record(log, 0)
        assert await log.close()
        assert await log.close()
        assert not record(log, 61)
        assert len(io.lines) == 1
    asyncio.run(scenario())


@pytest.mark.parametrize("seconds", [-1, float("nan"), float("inf")])
def test_invalid_event_clock_is_a_programmer_error(tmp_path, seconds):
    async def scenario():
        log = ErrorLog(LogConfig(directory=tmp_path), io=MemoryIO())
        assert log.prepare()
        with pytest.raises(ValueError):
            log.record("vllm", "chat", TIMEOUT, monotonic_time=seconds, occurred_at=NOW)
        assert await log.close()
    asyncio.run(scenario())


def test_close_deadline_does_not_wait_forever_for_slow_disk(tmp_path):
    async def scenario():
        io = GatedIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        try:
            assert log.prepare()
            assert record(log, 0)
            for _ in range(100):
                if io.started.is_set():
                    break
                await asyncio.sleep(0.001)
            assert io.started.is_set()
            assert not await asyncio.wait_for(log.close(timeout=0.01), timeout=0.5)
            assert not record(log, 61)
        finally:
            io.release.set()
    asyncio.run(scenario())


def test_utf8_object_identity_is_not_truncated_or_collapsed(tmp_path):
    async def scenario():
        io = MemoryIO()
        log = ErrorLog(LogConfig(directory=tmp_path), io=io)
        assert log.prepare()
        first = "模" * 127 + "一"
        second = "模" * 127 + "二"
        assert record(log, 0, target=first)
        assert record(log, 0, target=second)
        assert await log.flush()
        assert [entry["object_id"] for entry in records(io)] == [first, second]
        assert all(len(line) <= 1024 for line in io.lines)
        assert await log.close()
    asyncio.run(scenario())
