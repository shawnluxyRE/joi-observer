"""REQ-003 的本机 Docker 生命周期采集。

只查询显式配置的本机容器；不扫描、管理容器或读取其业务指标。采集器返回
CollectionResult，由 Monitor 写状态及错误日志；本模块不依赖 TUI、不打印。
原始命令响应只在本模块边界内存在，不进入快照、历史或日志。
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from joi_observer.config import ContainerConfig
from joi_observer.data.models import CollectionResult, Metric, ObjectKey, ObjectSpec
from joi_observer.error_log import ErrorKind, Failure


LOCAL_DOCKER_HOST = "unix:///var/run/docker.sock"
DOCKER_INSPECT_TEMPLATE = (
    '{"Id":{{json .Id}},"Name":{{json .Name}},'
    '"State":{"Status":{{json .State.Status}}}}'
)
MAX_OUTPUT_BYTES = 65_536
_FULL_ID = re.compile(r"[0-9a-f]{64}")
_LIFECYCLE_STATES = {
    "created": "Created", "running": "Running", "paused": "Paused",
    "restarting": "Restarting", "removing": "Removing", "exited": "Exited", "dead": "Dead",
}
_FAILURES = {
    ErrorKind.PERMISSION: ("access.denied", "Permission denied."),
    ErrorKind.NOT_FOUND: ("object.not_found", "Configured object was not found."),
    ErrorKind.UNAVAILABLE: ("source.unavailable", "Data source is unavailable."),
    ErrorKind.PARSE: ("response.invalid", "Invalid collection response."),
    ErrorKind.TIMEOUT: ("collection.timeout", "Collection timed out."),
}


@dataclass(frozen=True)
class CommandOutput:
    """已结束 inspect 命令的退出码及原始管道字节，供纯解析边界使用。

    stdout/stderr 分别最多 MAX_OUTPUT_BYTES 字节；外部替身超过上限时解析器
    也须拒绝。非零退出不解析 stdout；stderr 仅用于受控分类，不得直接展示、
    持久化或放入 Failure.reason。成功退出的 stderr 不改变成功语义。
    """

    returncode: int
    stdout: bytes = b""
    stderr: bytes = b""


class DockerOutputLimitError(Exception):
    """任一管道超过 MAX_OUTPUT_BYTES；采集器将其归为 response.invalid。

    不携带已读正文；抛出前本地命令端口须终止、回收子进程并清理读取任务。
    """


class DockerCommandPort(Protocol):
    """一次 inspect 的外部命令端口，每个采集器独占一个实例。

    替身提供原始 CommandOutput 或 IO 异常，不替换被测解析、状态或业务结果。
    构造无 IO；run/close 不打印、不写日志、不调用 shell。真实实现只能访问
    LOCAL_DOCKER_HOST，不接受远程 context、环境地址或其他命令。
    """

    async def run(self, argv: tuple[str, ...], *, timeout: float) -> CommandOutput:
        """执行唯一一次有界读取；timeout 为有限正 int/float（不含 bool），不重试。

        超时抛 TimeoutError，OS 启动异常原样交给采集器；取消直接传播
        CancelledError。超时、取消、超限在 250ms 内终止/回收子进程并清理
        任务，不能留下在后台执行的命令。单实例不支持重叠 run。
        """
        ...

    async def close(self) -> None:
        """幂等关闭自身资源，250ms 内终止/回收在途命令；不补打输出。

        有在途 run 时取消其任务，run 调用方收到 CancelledError；close 返回前
        完成进程回收及读取任务清理，不把终止退出码当作新采集结果返回。
        """
        ...


class LocalDockerCommand:
    """受限的本机 Docker CLI 适配器；构造不启动进程或检查 Docker。

    使用 asyncio.create_subprocess_exec 的参数数组和 stdin=DEVNULL、
    stdout/stderr=PIPE，不经 shell。仅接受 DockerCollector.collect 文档中
    的 inspect argv 形状（含固定 host/template 和一个非空 target）；其他
    argv 或非法 timeout 抛 ValueError 且不启动进程。close 后 run 抛 RuntimeError。

    从父环境复制 env，删除全部 DOCKER_* 变量并设置 LC_ALL=C、LANG=C；
    不更改父环境。显式 --host 锁定 /var/run/docker.sock，不跟随用户远程
    context，不自动探测其他 socket、rootless 路径或 Docker Desktop。

    同时排空两条管道，各自限制 65536 字节。恰好上限允许，超过即抛
    DockerOutputLimitError；不能无限 communicate 后才检查内存大小。
    超时、取消、超限和 close 均须 kill 并 await wait 回收子进程，等待并
    清理读取任务；清理总预算 250ms。取消不包装成采集错误，正常结束不 kill。
    close 主动取消在途 run，其调用方收到 CancelledError；close 返回前完成清理。
    """

    def __init__(self) -> None:
        self._closed = False
        self._process: asyncio.subprocess.Process | None = None
        self._read_tasks: set[asyncio.Task] = set()
        self._operation: asyncio.Task[CommandOutput] | None = None
        self._cleanup_retry: asyncio.Task[None] | None = None
        self._spawn: asyncio.Task[asyncio.subprocess.Process] | None = None
        self._finishing = False
        self._cancel_requested = False

    async def run(self, argv: tuple[str, ...], *, timeout: float) -> CommandOutput:
        """在独立任务中持有进程，调用方取消时先回收再传播取消。"""
        if self._closed:
            raise RuntimeError("Docker command is closed.")
        prefix = ("docker", "--host", LOCAL_DOCKER_HOST, "container", "inspect",
                  "--format", DOCKER_INSPECT_TEMPLATE, "--")
        if (not isinstance(argv, tuple) or len(argv) != 9 or argv[:-1] != prefix
                or not isinstance(argv[-1], str) or not argv[-1]
                or "\x00" in argv[-1]):
            raise ValueError("Only a local single-container inspect is allowed.")
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Timeout must be a finite positive number.")
        if self._operation is not None:
            raise RuntimeError("Docker command is already running.")
        if self._has_resources():
            raise RuntimeError("Docker command cleanup is incomplete; close is required.")
        self._finishing = self._cancel_requested = False
        operation = self._operation = asyncio.create_task(self._execute(argv, timeout))
        try:
            try:
                output = await asyncio.shield(operation)
            except asyncio.CancelledError:
                self._cancel_operation()
                await self._settle(operation)
                raise
            # close can arrive while normal completion is already reaping the
            # child. That completed output must not become a shutdown sample.
            if self._closed:
                raise asyncio.CancelledError
            return output
        finally:
            if self._operation is operation:
                self._operation = None

    async def close(self) -> None:
        """按端口协议幂等回收本实例，禁止关闭其他容器的命令。"""
        self._closed = True
        operation = self._operation
        if operation is not None and not operation.done():
            self._cancel_operation()
            cancelled = await self._settle(operation)
            if cancelled:
                raise asyncio.CancelledError
        elif self._has_resources():
            # A previous cleanup failure retains ownership. Later close calls
            # share one retry; callers cannot cancel the cleanup out from under
            # one another, and an unsuccessful retry remains observable.
            if self._cleanup_retry is None or self._cleanup_retry.done():
                self._cleanup_retry = asyncio.create_task(self._cleanup())
            retry = self._cleanup_retry
            cancelled = await self._settle(retry)
            if cancelled:
                raise asyncio.CancelledError
            retry.result()

    def _has_resources(self) -> bool:
        return self._process is not None or self._spawn is not None or bool(self._read_tasks)

    def _cancel_operation(self) -> None:
        # Monitor.stop cancels collect and closes its port concurrently. Only
        # one cancellation may enter the owner task; cleanup must finish intact.
        if (self._operation is not None and not self._operation.done()
                and not self._cancel_requested and not self._finishing):
            self._cancel_requested = True
            self._operation.cancel()

    @staticmethod
    async def _settle(operation: asyncio.Task) -> bool:
        """Wait through repeated caller cancellation, consuming child failures.

        Return whether this waiting caller was cancelled (as distinct from the
        operation itself), so close preserves its own cancellation semantics.
        """
        cancelled = False
        caller = asyncio.current_task()
        assert caller is not None
        cancellation_count = caller.cancelling()
        while not operation.done():
            try:
                await asyncio.shield(operation)
            except asyncio.CancelledError:
                # The operation may finish in the same event-loop turn as an
                # external cancel. Its done() state cannot identify which task
                # was cancelled; only new requests on this caller can do that.
                if caller.cancelling() > cancellation_count:
                    cancelled = True
                    cancellation_count = caller.cancelling()
            except Exception:
                break
        if not operation.cancelled():
            operation.exception()
        return cancelled

    @staticmethod
    async def _read_bounded(stream: asyncio.StreamReader) -> bytes:
        output = bytearray()
        while True:
            # At most one byte beyond the limit is retained; a full buffer
            # still needs one EOF probe to distinguish exact-limit output.
            chunk = await stream.read(min(8192, MAX_OUTPUT_BYTES + 1 - len(output)))
            if not chunk:
                return bytes(output)
            output.extend(chunk)
            if len(output) > MAX_OUTPUT_BYTES:
                raise DockerOutputLimitError

    async def _execute(self, argv: tuple[str, ...], timeout: float) -> CommandOutput:
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith("DOCKER_")}
        environment.update(LC_ALL="C", LANG="C")
        try:
            async with asyncio.timeout(timeout):
                self._spawn = asyncio.create_task(asyncio.create_subprocess_exec(
                    *argv, stdin=asyncio.subprocess.DEVNULL,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    env=environment,
                ))
                # Retain ownership even if cancellation races with creation.
                self._process = await asyncio.shield(self._spawn)
                assert self._process.stdout is not None and self._process.stderr is not None
                stdout = asyncio.create_task(self._read_bounded(self._process.stdout))
                stderr = asyncio.create_task(self._read_bounded(self._process.stderr))
                wait = asyncio.create_task(self._process.wait())
                self._read_tasks = {stdout, stderr, wait}
                out, err, returncode = await asyncio.gather(stdout, stderr, wait)
                output = CommandOutput(returncode, out, err)
        except BaseException:
            self._finishing = True
            try:
                await self._cleanup()
            except Exception:
                # Cleanup must not change output-limit or cancellation into a
                # different sample. Retained resources can be retried by close.
                pass
            raise
        else:
            self._finishing = True
            await self._cleanup()
            return output

    @staticmethod
    def _close_read_pipes(process: asyncio.subprocess.Process) -> None:
        """Close paused pipes without reading or retaining more response bytes.

        asyncio.Process exposes no public close API for its read pipes. Access
        to StreamReader's asyncio transport is confined here. Closing the pipes
        lets wait() finish even when backpressure had paused further EOF reads.
        The parent transport is closed only after reaping, avoiding asyncio's
        debug-mode warning about closing a running child.
        """
        for stream in (process.stdout, process.stderr):
            transport = getattr(stream, "_transport", None)
            if transport is not None:
                transport.close()

    async def _cleanup(self) -> None:
        """Release pipes and reap within 250ms; retain ownership on failure."""
        async with asyncio.timeout(0.25):
            if self._spawn is not None:
                if not self._spawn.done():
                    self._spawn.cancel()
                # asyncio's subprocess creation cleans its transport when
                # cancelled. If it completed in the meantime, reap here.
                created, = await asyncio.gather(self._spawn, return_exceptions=True)
                if not isinstance(created, BaseException):
                    self._process = created
            for task in self._read_tasks:
                if not task.done():
                    task.cancel()
            if self._process is not None:
                if self._process.returncode is None:
                    try:
                        self._process.kill()
                    except ProcessLookupError:
                        pass
                self._close_read_pipes(self._process)
                await self._process.wait()
                transport = getattr(self._process, "_transport", None)
                if transport is not None:
                    transport.close()
            if self._read_tasks:
                await asyncio.gather(*self._read_tasks, return_exceptions=True)
        self._process = self._spawn = None
        self._read_tasks.clear()


def _failure_result(config: ContainerConfig, kind: ErrorKind) -> CollectionResult:
    """Keep response bytes and exception messages outside the result boundary."""
    code, reason = _FAILURES[kind]
    return CollectionResult(ObjectKey("docker", config.id), failure=Failure(kind, code, reason))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    # Python's JSON decoder otherwise accepts NaN and Infinity extensions.
    raise ValueError("Invalid JSON constant.")


def parse_inspect(config: ContainerConfig, output: CommandOutput) -> CollectionResult:
    """把一次原始命令结果转成配置 id 对应的生命周期结果；无 IO。

    先检查任一输出是否超过 MAX_OUTPUT_BYTES，超限为 parse/response.invalid。
    非零退出只按 stderr 的 ASCII 不区分大小写子串分类，优先级依次为：
    ``permission denied`` -> permission/access.denied；``no such container`` 或
    ``no such object`` -> not_found/object.not_found；其他 ->
    unavailable/source.unavailable。不解析非零退出的 stdout。

    成功 stdout 必须为严格 UTF-8 的单个 JSON object（允许首尾空白）；拒绝
    重复 JSON key、列表、多文档、缺失/错误类型字段。Id 为 64 位小写十六进制；
    Name 为恰好一个前导 / 后跟非空、可打印、无空白且无 / 的名称。
    State.Status 必须是 created/running/paused/restarting/removing/exited/dead
    之一，输出对应的 Created/Running/Paused/Restarting/Removing/Exited/Dead。
    未知状态、缺失或非法字段都是 parse/response.invalid，不伪装成未知成功值。
    额外字段（包括 Health、Error、ExitCode、环境与日志）忽略且不透传。

    身份只在结构合法后比较：config.name 恰为 64 位小写十六进制时只解释为
    完整 Id，必须与响应 Id 精确相等，不能被同名但不同 Id 的容器改绑；其他
    target 只与 Name 去掉首个 / 后的完整名称精确比较。否则为
    not_found/object.not_found；禁止只凭短 ID、子串、Compose 项目名推断
    和带 / 名称匹配。短十六进制字符串若恰为完整真实名称则仍可按名称匹配。
    按名称监控可跟随同名重建后的新 Id，按完整 Id 不可改绑。
    ObjectKey 永远使用 config.id。

    成功 metrics 恰为 (Metric("state", 规范状态),)，failure=None；Exited 等
    所有合法状态均属成功，不含 healthcheck 语义。失败 metrics=()，Failure
    使用上述既有目录和固定受控英文 reason，不含任何响应/异常原文。
    不抛出响应解析异常、不记日志、不更新状态，也不输出到 stdout/stderr。
    """
    if len(output.stdout) > MAX_OUTPUT_BYTES or len(output.stderr) > MAX_OUTPUT_BYTES:
        return _failure_result(config, ErrorKind.PARSE)
    if output.returncode != 0:
        error = output.stderr.lower()
        if b"permission denied" in error:
            kind = ErrorKind.PERMISSION
        elif b"no such container" in error or b"no such object" in error:
            kind = ErrorKind.NOT_FOUND
        else:
            kind = ErrorKind.UNAVAILABLE
        return _failure_result(config, kind)

    try:
        data = json.loads(output.stdout.decode("utf-8"), object_pairs_hook=_unique_object,
                          parse_constant=_reject_json_constant)
    except (ValueError, RecursionError):
        # Includes invalid UTF-8, malformed/duplicate JSON and decoder limits.
        return _failure_result(config, ErrorKind.PARSE)
    if not isinstance(data, dict):
        return _failure_result(config, ErrorKind.PARSE)
    identity, name, state = data.get("Id"), data.get("Name"), data.get("State")
    status = state.get("Status") if isinstance(state, dict) else None
    if (not isinstance(identity, str) or _FULL_ID.fullmatch(identity) is None
            or not isinstance(name, str) or not name.startswith("/") or len(name) < 2
            or "/" in name[1:] or not name.isprintable() or any(char.isspace() for char in name)
            or not isinstance(status, str) or status not in _LIFECYCLE_STATES):
        return _failure_result(config, ErrorKind.PARSE)

    expected = identity if _FULL_ID.fullmatch(config.name) is not None else name[1:]
    if config.name != expected:
        return _failure_result(config, ErrorKind.NOT_FOUND)
    return CollectionResult(ObjectKey("docker", config.id),
                            (Metric("state", _LIFECYCLE_STATES[status]),))


class DockerCollector:
    """一个配置项对应一个 Collector；配置顺序及显示容量不改变采样集合。

    config 已经启动配置校验，timeout 为有限正数（生产使用 collection_timeout）。
    构造只保存依赖及声明未知 state 模板，不校验 Docker 安装、启动命令或记日志。
    command 未传时构造 LocalDockerCommand；每个实例独占并负责关闭自己的端口。
    相同真实目标、不同 config.id 的配置项仍是各自独立的监控对象。
    """

    def __init__(self, config: ContainerConfig, *, command: DockerCommandPort | None = None,
                 timeout: float = 3.0) -> None:
        self.config = config
        self.timeout = timeout
        self.spec = ObjectSpec(ObjectKey("docker", config.id), (Metric("state", None),))
        self._command = command if command is not None else LocalDockerCommand()
        self._closed = False

    async def collect(self) -> CollectionResult:
        """读取一次当前状态，命令恰为：

        ("docker", "--host", LOCAL_DOCKER_HOST, "container", "inspect", "--format",
         DOCKER_INSPECT_TEMPLATE, "--", config.name)。target 始终为单个参数，
        不经 shell、不列举其他容器、不管理对象、不读取额外字段、不重试。
        每次都查询，失败不能永久缓存；结果交给 parse_inspect。

        FileNotFoundError/其他 OSError -> unavailable/source.unavailable；
        PermissionError -> permission/access.denied；TimeoutError ->
        timeout/collection.timeout；DockerOutputLimitError -> parse/response.invalid。
        Failure 不含异常文本；未知异常交 Monitor 归一。CancelledError 原样传播，
        端口负责在 250ms 内清理，不产生失败样本；close 后调用抛 RuntimeError。
        """
        if self._closed:
            raise RuntimeError("Docker collector is closed.")
        argv = ("docker", "--host", LOCAL_DOCKER_HOST, "container", "inspect", "--format",
                DOCKER_INSPECT_TEMPLATE, "--", self.config.name)
        try:
            output = await self._command.run(argv, timeout=self.timeout)
        except DockerOutputLimitError:
            return _failure_result(self.config, ErrorKind.PARSE)
        except TimeoutError:
            return _failure_result(self.config, ErrorKind.TIMEOUT)
        except PermissionError:
            return _failure_result(self.config, ErrorKind.PERMISSION)
        except OSError:
            return _failure_result(self.config, ErrorKind.UNAVAILABLE)
        return parse_inspect(self.config, output)

    async def close(self) -> None:
        """幂等关闭自己独占的 command，250ms 内完成，不影响其他容器或打印。"""
        if not self._closed:
            self._closed = True
            await self._command.close()


def build_docker_collectors(
    containers: tuple[ContainerConfig, ...], *, timeout: float,
    command_factory: Callable[[], DockerCommandPort] | None = None,
) -> tuple[DockerCollector, ...]:
    """为全部配置项按原顺序组装独立采集器；不按终端高度或数量截断。

    0 项返回空 tuple 且不调用 factory。其余每项调用 factory 一次，缺省使用
    LocalDockerCommand；每个 collector 使用相同 timeout，但独占返回的端口。
    factory 必须每次返回不同实例。相同 name、不同 id 不合并；不修改原配置。
    此函数和构造均不启动 IO。生产组合根据 spec 注册状态，并将完整 tuple
    交给同一 Monitor；仅 Frame 决定可见前缀，隐藏对象仍持续采样。
    """
    factory = command_factory if command_factory is not None else LocalDockerCommand
    return tuple(DockerCollector(config, command=factory(), timeout=timeout) for config in containers)
