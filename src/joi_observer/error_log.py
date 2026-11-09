"""REQ-001 的有界、异步采集失败日志。

本模块不使用全局/root logger，不把日志接到 stdout/stderr。诊断对象不得
进入展示快照；详见 docs/design/error-logging.md。构造对象不会创建文件或线程。
"""

from __future__ import annotations

import asyncio
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
import json
import math
from pathlib import Path
import re
import stat
import threading
import unicodedata
from typing import Protocol

from joi_observer.config import LogConfig


class ErrorKind(str, Enum):
    """稳定失败类别；不包含正常停止、无负载、N/A 或已知不支持字段。"""

    TIMEOUT = "timeout"
    PERMISSION = "permission"
    NOT_FOUND = "not_found"
    PARSE = "parse"
    UNAVAILABLE = "unavailable"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True, slots=True)
class Failure:
    """采集失败描述，不得包含请求/响应正文、凭据或原始异常。

    kind 为稳定错误类型；code 为项目登记的稳定原因代码，不包含时间、URL、
    测量值或异常文本。reason 是采集器写入的受控原因描述，供适配器契约核对；
    为避免任意文本泄漏，日志器永不直接序列化此字段，而按 kind/code 查固定
    英文原因模板。未知代码或类别不匹配时归一为 collector.unexpected。
    reason 既不能进入 TUI，也不能用于重复错误判定。

    有效目录：collection.timeout / access.denied / object.not_found /
    response.invalid / source.unavailable / collector.unexpected，分别对应
    ErrorKind 的 TIMEOUT / PERMISSION / NOT_FOUND / PARSE / UNAVAILABLE /
    UNEXPECTED。未来采集器若要细分原因，须扩展目录及测试，不能拼接异常消息。
    """

    kind: ErrorKind
    code: str
    reason: str


class LogIO(Protocol):
    """文件系统边界，供真实文件后端及离线故障注入使用。

    ErrorLog 是唯一调用者；prepare 在进入全屏前调用，append 仅在专用单写者
    线程调用。后端不得打印信息、记录日志或访问网络。OSError 交给 ErrorLog
    消化，禁止传播到 Monitor/TUI。协议不负责限频、队列或失败归一。
    """

    def prepare(self, directory: Path) -> None:
        """创建缺失目录并以追加方式打开/关闭 error.log，验证实际可写性。

        directory 已由配置层展开为绝对路径。保留已有内容，不向文件写入
        启动记录；成功返回 None，不可写/无法创建/不是普通文件则抛 OSError。
        失败不得选择备用目录。每次调用均允许重新检查文件是否恢复可写。
        """
        ...

    def append(self, config: LogConfig, line: bytes) -> None:
        """追加一条完整 UTF-8 JSONL ERROR，必要时在写入前轮转。

        line 含末尾 LF，长度不超过 1024 字节且不超过 config.max_bytes。
        error.log 加此行将超过阈值时：淘汰最旧备份，.N-1 移到 .N，
        当前文件移到 .1，再追加新行；刚好等于阈值不提前轮转。
        总计保留当前文件及 backup_count 份备份。失败抛 OSError，不打印。
        每次调用重新打开文件，允许路径在运行中恢复；不补写失败记录。
        """
        ...


class FileLogIO:
    """真实本地文件后端；公开行为遵循 LogIO，轮转使用追加语义。"""

    @staticmethod
    def _check_file(path: Path) -> int:
        """拒绝目录和特殊文件，避免将 FIFO 等当作普通日志打开。"""
        try:
            info = path.stat()
        except FileNotFoundError:
            return 0
        if not stat.S_ISREG(info.st_mode):
            raise OSError("Error log must be a regular file.")
        return info.st_size

    def prepare(self, directory: Path) -> None:
        """实现 LogIO.prepare 的目录创建与实际打开检查，不输出任何文本。"""
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "error.log"
        self._check_file(path)
        with path.open("ab"):
            pass

    def append(self, config: LogConfig, line: bytes) -> None:
        """实现 LogIO.append 的有界文件轮转；捕获/上报边界见协议注释。"""
        path = config.directory / "error.log"
        size = self._check_file(path)
        if size + len(line) > config.max_bytes:
            oldest = path.with_name(f"error.log.{config.backup_count}")
            oldest.unlink(missing_ok=True)
            for index in range(config.backup_count - 1, 0, -1):
                source = path.with_name(f"error.log.{index}")
                if source.exists():
                    source.replace(path.with_name(f"error.log.{index + 1}"))
            if path.exists():
                path.replace(path.with_name("error.log.1"))
        with path.open("ab") as stream:
            stream.write(line)


_REASONS = {
    (ErrorKind.TIMEOUT, "collection.timeout"): "Collection timed out.",
    (ErrorKind.PERMISSION, "access.denied"): "Permission denied.",
    (ErrorKind.NOT_FOUND, "object.not_found"): "Configured object was not found.",
    (ErrorKind.PARSE, "response.invalid"): "Invalid collection response.",
    (ErrorKind.UNAVAILABLE, "source.unavailable"): "Data source is unavailable.",
    (ErrorKind.UNEXPECTED, "collector.unexpected"): "Unexpected collector failure.",
}
_UNEXPECTED = (ErrorKind.UNEXPECTED, "collector.unexpected")
_COLLECTOR = re.compile(r"[a-z][a-z0-9_.-]{0,31}\Z")
_Fingerprint = tuple[str, str, ErrorKind, str]


@dataclass(frozen=True, slots=True)
class _LogEvent:
    """队列仅持有安全序列化记录和撤销预占所需的稳定标识。"""

    sequence: int
    episode: int
    fingerprint: _Fingerprint
    line: bytes


class ErrorLog:
    """独立、非阻塞、ERROR-only 采集诊断出口。

    config 必须是已经验证和展开路径的 LogConfig。queue_capacity 为正整数，
    默认 256；config.max_bytes >= 1024，backup_count >= 1。构造无 IO。
    所有公开调用来自同一个 Monitor/CLI 事件循环线程；只有 LogIO.append
    在专用守护写线程中执行，不占用采集线程池或事件循环。外部只注入文件
    IO 边界，不能替换限频业务。close 后不得重新启用本实例。
    """

    def __init__(
        self,
        config: LogConfig,
        *,
        io: LogIO | None = None,
        queue_capacity: int = 256,
    ) -> None:
        if type(queue_capacity) is not int or queue_capacity < 1:
            raise ValueError("queue_capacity must be a positive integer.")
        if type(config.max_bytes) is not int or config.max_bytes < 1024:
            raise ValueError("max_bytes must be an integer of at least 1024.")
        if type(config.backup_count) is not int or config.backup_count < 1:
            raise ValueError("backup_count must be a positive integer.")
        self.config = config
        self.io = io if io is not None else FileLogIO()
        self.queue_capacity = queue_capacity
        self._condition = threading.Condition()
        self._queue: deque[_LogEvent] = deque()
        self._pending: set[int] = set()
        self._reservations: dict[_Fingerprint, tuple[float, int, int]] = {}
        self._episodes: dict[tuple[str, str], int] = {}
        self._sequence = 0
        self._worker: threading.Thread | None = None
        self._prepared = False
        self._closed = False

    def prepare(self) -> bool:
        """全屏前检查文件，成功 True；OSError 失败 False，不打印、不抛出。

        CLI 仅根据首次 False 在进入 TUI 前提示一次；日志器自身不提示。
        失败不会关闭实例，下一条 record 接纳后由写线程重试 prepare/append。
        成功不写启动日志；重复调用不清空文件。业务调用序列要求先 prepare。
        """
        if self._closed:
            return False
        try:
            self.io.prepare(self.config.directory)
        except OSError:
            self._prepared = False
        else:
            self._prepared = True
        return self._prepared

    def record(
        self,
        collector: str,
        object_id: str,
        failure: Failure,
        *,
        monotonic_time: float,
        occurred_at: datetime,
    ) -> bool:
        """尝试非阻塞接纳一次真实采集失败，返回值不代表落盘成功。

        collector/object_id 是稳定身份，不得使用 URL、原始异常或数据值；
        两者必须为非空字符串，分别不超过 32/128 字符。collector 满足
        [a-z][a-z0-9_.-]*；object_id 是不含控制字符的 Unicode 字符串，
        不截断身份。JSON 使用 ensure_ascii=False，单条编码不超过1024字节。
        monotonic_time 为非负有限单调秒数；occurred_at 是 Monitor 提供的服务器
        本地发生时间（内部仍为带时区 datetime）。日志 time 固定写为
        YYYY-MM-DD HH:MM:SS，精确到秒，不输出时区名、UTC偏移、Z或T分隔符，
        不转换成UTC；例如 2026-10-28 18:00:00。不使用写线程落盘时刻覆盖发生时间。
        系统墙钟变化不影响限频。程序员违反参数约束抛 ValueError。

        按 (collector, object_id, 归一kind, 归一code) 限频：首次入队立即
        True；同一连续故障轮次在 [t,t+60) 返回 False，t+60 可再入队。
        reason 中动态文本不参与指纹；A→B→A 仍保留 A 的限频状态。
        新对象或新代码不受其他指纹限制。recovered 清除此对象所有指纹。

        队满/已关闭返回 False，不等待、不抛 IO 错误、不增加日志或提示。
        队满不占用限频时间；入队成功先预占，写失败撤销该次预占，后续
        新采样可立即重试，旧记录不重放。异步完成须携带故障轮次及事件序号，
        不得用旧写入失败撤销恢复后新故障的预占。每条 JSONL 只含 time、level
        固定 ERROR、collector、object_id、kind、code、reason；reason 来自
        固定目录，永不保存传入的自由文本、指标、traceback 或 HTTP 内容。
        """
        self._validate_identity(collector, object_id)
        if (
            isinstance(monotonic_time, bool)
            or not isinstance(monotonic_time, (int, float))
            or not math.isfinite(monotonic_time)
            or monotonic_time < 0
        ):
            raise ValueError("monotonic_time must be a nonnegative finite number.")
        if not isinstance(occurred_at, datetime) or occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be a timezone-aware datetime.")
        if not isinstance(failure, Failure):
            raise ValueError("failure must be a Failure.")
        category = (failure.kind, failure.code)
        # Do not retain caller-supplied diagnostics in the queue or throttle state.
        if not isinstance(failure.kind, ErrorKind) or not isinstance(failure.code, str):
            category = _UNEXPECTED
        if category not in _REASONS:
            category = _UNEXPECTED
        kind, code = category
        line = (json.dumps({
            "time": occurred_at.replace(tzinfo=None).isoformat(sep=" ", timespec="seconds"),
            "level": "ERROR",
            "collector": collector,
            "object_id": object_id,
            "kind": kind.value,
            "code": code,
            "reason": _REASONS[category],
        }, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        if len(line) > 1024:
            raise ValueError("Encoded error record exceeds 1024 bytes.")
        fingerprint = (collector, object_id, kind, code)
        identity = (collector, object_id)
        with self._condition:
            if self._closed:
                return False
            previous = self._reservations.get(fingerprint)
            if previous is not None and monotonic_time - previous[0] < 60:
                return False
            if len(self._queue) >= self.queue_capacity:
                return False
            self._sequence += 1
            sequence = self._sequence
            episode = self._episodes.get(identity, 0)
            self._reservations[fingerprint] = (monotonic_time, episode, sequence)
            self._queue.append(_LogEvent(sequence, episode, fingerprint, line))
            self._pending.add(sequence)
            if self._worker is None:
                self._worker = threading.Thread(
                    target=self._write_loop, name="joi-observer-error-log", daemon=True,
                )
                self._worker.start()
            self._condition.notify()
        return True

    def recovered(self, collector: str, object_id: str) -> None:
        """采集对象本轮已无实际失败时调用，清除其全部指纹，不写恢复日志。

        未见过的对象为幂等空操作。部分字段仍失败不得调用，避免绕过限频。
        已入队的真实历史故障可以落盘，但其完成回调不能覆盖新故障轮次状态。
        """
        self._validate_identity(collector, object_id)
        identity = (collector, object_id)
        with self._condition:
            self._episodes[identity] = self._episodes.get(identity, 0) + 1
            for fingerprint in tuple(self._reservations):
                if fingerprint[:2] == identity:
                    del self._reservations[fingerprint]

    async def flush(self, *, timeout: float = 1.0) -> bool:
        """等待调用前已接纳记录处理完成；成功处理或丢弃均视为已排空。

        只供验证/有界退出使用，不在每次采样中等待。timeout 必须有限且>0；
        到时返回 False，IO 失败不抛出。True 不保证每条均成功落盘，不能用于
        判断采集成功。等待期间事件循环/键位仍可运行，不等待之后的新记录。
        """
        self._validate_timeout(timeout)
        with self._condition:
            through_sequence = self._sequence
        return await self._wait_processed(through_sequence, timeout)

    async def close(self, *, timeout: float = 1.0) -> bool:
        """幂等停止接纳并有界排空，关闭正常可关闭的资源，仍不输出错误。

        返回 True 表示排空完成，超时 False 并丢弃未开始记录；不在退出后补打
        任何文本。文件系统调用不能强行中断，专用守护线程不得阻挡进程退出；
        已开始的单次文件调用可能稍后完成。终端恢复不等待此方法无限挂起。
        """
        self._validate_timeout(timeout)
        with self._condition:
            self._closed = True
            through_sequence = self._sequence
            self._condition.notify()
        drained = await self._wait_processed(through_sequence, timeout)
        if not drained:
            with self._condition:
                while self._queue:
                    event = self._queue.popleft()
                    self._finish(event, failed=True)
                self._condition.notify()
        return drained

    @staticmethod
    def _validate_identity(collector: str, object_id: str) -> None:
        if not isinstance(collector, str) or not _COLLECTOR.fullmatch(collector):
            raise ValueError("collector must be a stable identifier of at most 32 characters.")
        if (
            not isinstance(object_id, str) or not 1 <= len(object_id) <= 128
            or any(unicodedata.category(char) in {"Cc", "Cs"} for char in object_id)
        ):
            raise ValueError("object_id must contain 1 to 128 characters without controls.")

    @staticmethod
    def _validate_timeout(timeout: float) -> None:
        if (
            isinstance(timeout, bool) or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout) or timeout <= 0
        ):
            raise ValueError("timeout must be a positive finite number.")

    async def _wait_processed(self, through_sequence: int, timeout: float) -> bool:
        # Never join the disk thread or consume the collectors' executor pool.
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            with self._condition:
                if not any(sequence <= through_sequence for sequence in self._pending):
                    return True
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(0.005, remaining))

    def _finish(self, event: _LogEvent, *, failed: bool) -> None:
        """在 condition 锁内完成事件；旧回调只能撤销自己的预占。"""
        if failed:
            reservation = self._reservations.get(event.fingerprint)
            if reservation is not None and reservation[1:] == (event.episode, event.sequence):
                del self._reservations[event.fingerprint]
        self._pending.discard(event.sequence)

    def _write_loop(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(lambda: self._queue or self._closed)
                if not self._queue:
                    return
                event = self._queue.popleft()
            failed = False
            try:
                if not self._prepared:
                    self.io.prepare(self.config.directory)
                    self._prepared = True
                self.io.append(self.config, event.line)
            except OSError:
                self._prepared = False
                failed = True
            finally:
                with self._condition:
                    self._finish(event, failed=failed)
