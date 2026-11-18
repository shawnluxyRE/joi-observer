"""本机只读快照发布、Unix 字节流适配及独立读者的资源隔离。"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field
import math
import os
import socket
import stat
import sys
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol, TYPE_CHECKING

from joi_observer._shutdown import ShutdownBudget, await_owner, cancel_once, settle, spawn, join_tasks, run_cleanup
from joi_observer.ipc.protocol import FRAME_TIMEOUT, HEARTBEAT_INTERVAL, IO_CHUNK_BYTES
from joi_observer.ipc._worker import encode_async

if TYPE_CHECKING:
    from joi_observer.ipc.protocol import SnapshotEnvelope


class PeerPort(Protocol):
    """一个已接受的字节流；测试可以用内存队列替换 OS 传输。"""

    async def send(self, data: bytes) -> None:
        """写入 1..IO_CHUNK_BYTES 字节并 drain；可取消，无重试或无限缓冲。

        这是有序字节流的一次外部写入，不代表一份完整快照或应用层分片。
        """
        ...

    async def receive(self, max_bytes: int) -> bytes:
        """返回最多 max_bytes 字节；空字节表示 EOF；不解析执行内容。"""
        ...

    async def close(self) -> None:
        """幂等关闭该连接；必须可取消。"""
        ...


class ListenerPort(Protocol):
    """仅允许本机 Unix 字节流，不接受主机名、URL 或 TCP 监听参数。"""

    async def start(self) -> None:
        """绑定 endpoint；权限校验失败时不留下可用的宽权限 socket。"""
        ...

    async def accept(self) -> PeerPort:
        """等待一个连接；不阻塞事件循环，不隐式读取监控配置。"""
        ...

    async def close(self) -> None:
        """停止接受连接并幂等清理本实例绑定的 socket。"""
        ...


class UnixListener:
    """AF_UNIX/SOCK_STREAM 适配器；仅在获得实例锁后 start。

    父目录须由服务账户拥有且模式 0750，socket 为 0660，组为专用只读组。
    不跟随 socket/锁符号链接，不覆盖普通文件。残留 socket 的删除必须在
    持有实例锁时验证类型及所有者。服务进程独占写目录，读者只有搜索权限。
    """

    def __init__(self, endpoint: Path) -> None:
        self.endpoint = endpoint
        self._socket: socket.socket | None = None
        self._identity: tuple[int, int] | None = None
        self._closed = False
        self._shutdown_budget: ShutdownBudget | None = None

    def _bind_cleanup_budget(self, budget: ShutdownBudget) -> None:
        self._shutdown_budget = budget

    async def start(self) -> None:
        """绑定并校验权限；不连接其他服务或执行任意命令。"""
        if self._closed:
            raise RuntimeError("Listener is closed")
        if self._socket is not None:
            return
        if not self.endpoint.is_absolute():
            raise ValueError("A local absolute socket path is required")
        parent = self.endpoint.parent.lstat()
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid()
                or stat.S_IMODE(parent.st_mode) != 0o750
                or parent.st_gid != os.getegid()):
            raise ValueError("Unsafe snapshot directory")
        try:
            previous = self.endpoint.lstat()
        except FileNotFoundError:
            pass
        else:
            if not stat.S_ISSOCK(previous.st_mode) or previous.st_uid != os.geteuid():
                raise ValueError("Unsafe existing snapshot endpoint")
            self.endpoint.unlink()

        connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket = connection
        try:
            connection.setblocking(False)
            connection.bind(str(self.endpoint))
            created = self.endpoint.lstat()
            self._identity = created.st_dev, created.st_ino
            os.chmod(self.endpoint, 0o660, follow_symlinks=False)
            configured = self.endpoint.lstat()
            if (not stat.S_ISSOCK(configured.st_mode)
                    or (configured.st_dev, configured.st_ino) != self._identity
                    or configured.st_uid != os.geteuid()
                    or configured.st_gid != parent.st_gid
                    or stat.S_IMODE(configured.st_mode) != 0o660):
                raise ValueError("Unsafe snapshot endpoint permissions")
            # No connection is accepted until the final permissions are verified.
            connection.listen(64)
        except BaseException:
            if self._shutdown_budget is not None:
                self._shutdown_budget.begin()
            # Cleanup is best effort; it must not replace the startup failure.
            with suppress(BaseException):
                await self.close()
            raise

    async def accept(self) -> PeerPort:
        """返回受限连接；OS 错误使发布服务失败，单客户端断开仅影响该客户端。"""
        if self._socket is None or self._closed:
            raise RuntimeError("Listener is not active")
        connection, _ = await asyncio.get_running_loop().sock_accept(self._socket)
        try:
            connection.setblocking(False)
            return _UnixPeer(connection)
        except BaseException:
            with suppress(BaseException):
                connection.close()
            raise

    async def close(self) -> None:
        """仅 unlink 本实例创建且 inode 未被替换的 socket；不删除锁文件。"""
        self._closed = True
        if self._socket is not None:
            self._socket.close()
            self._socket = None
        if self._identity is not None:
            try:
                current = self.endpoint.lstat()
                if (stat.S_ISSOCK(current.st_mode)
                        and (current.st_dev, current.st_ino) == self._identity
                        and current.st_uid == os.geteuid()):
                    self.endpoint.unlink()
            except FileNotFoundError:
                pass
            finally:
                self._identity = None


class _UnixPeer:
    """Nonblocking accepted socket; no command/request handling exists here."""

    def __init__(self, connection: socket.socket) -> None:
        self._socket = connection

    async def send(self, data: bytes) -> None:
        if not 0 < len(data) <= IO_CHUNK_BYTES:
            raise ValueError("Invalid snapshot write size")
        await asyncio.get_running_loop().sock_sendall(self._socket, data)

    async def receive(self, max_bytes: int) -> bytes:
        if not 0 < max_bytes <= IO_CHUNK_BYTES:
            raise ValueError("Invalid snapshot read size")
        return await asyncio.get_running_loop().sock_recv(self._socket, max_bytes)

    async def close(self) -> None:
        self._socket.close()


@dataclass(frozen=True)
class _Publication:
    data: bytes
    published_at: float


@dataclass(eq=False)
class _Reader:
    peer: PeerPort
    pending: _Publication | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)


class SnapshotPublisher:
    """状态更新驱动的原子快照发布；采样与传输完全分离。

    source 同步返回一个完整 envelope，禁止 I/O 或触发采样。首次运行生成
    初始帧；wait_updated(after_revision) 通知 State 更新后在下一事件循环
    机会生成一帧，同轮通知合并，不增加采样或固定等待心跳。没有更新时距
    上次发布 heartbeat_interval 秒生成完整心跳帧。新客户端取得最近完整
    帧而不另调 source。每次发布编码一次并共享不可变 bytes。encode_async
    对大快照使用受控子进程，小输入按规模判定执行有界同步编码；至多一项
    编码在途，不排编码任务队列。worker 只消费已经冻结的 envelope，不读取
    可变 State 或回写状态。编码期间产生的更新由下一次 revision 检查合并。
    取消编码等待会终止并回收子进程，关闭后不安装迟到结果；不使用默认线程池。

    每客户端至多一帧在途、一帧待发，待发仅保留最新帧；有序逐次发送
    至多 IO_CHUNK_BYTES 字节，必须让出事件循环。完整帧写入/drain 共享
    write_timeout 的总预算，零碎进展不重置预算；超时仅关闭该客户端。
    完整快照无 8 MiB 总大小限制，不裁剪对象/历史。最多 64 个连接，
    超限仅关闭新连接，不驱逐已有健康客户端。

    首帧发送前以宿主 monotonic 检查缓存发布年龄；超过 FRAME_TIMEOUT 的
    已发布帧不能作为新读者的首帧。保持该连接等待下一次正常发布，不追加
    source 调用或采样，等待仍受客户端首帧预算约束。此判定不用来源的
    sampled_at，不把合法的慢采样或 STALE 误认为传输过期。
    """

    def __init__(self, source: Callable[[], SnapshotEnvelope], listener: ListenerPort,
                 *, wait_updated: Callable[[int], Awaitable[None]],
                 heartbeat_interval: float = HEARTBEAT_INTERVAL,
                 write_timeout: float = 2.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.source = source
        self.listener = listener
        self.wait_updated = wait_updated
        self.heartbeat_interval = heartbeat_interval
        self.write_timeout = write_timeout
        self.clock = clock
        for value in (heartbeat_interval, write_timeout):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError("Snapshot deadlines must be positive finite numbers")
        self._started = False
        self._closed = False
        self._running = False
        self._closed_event = asyncio.Event()
        self._tasks: set[asyncio.Task] = set()
        self._readers: dict[_Reader, asyncio.Task] = {}
        self._latest: _Publication | None = None
        self._close_task: asyncio.Task | None = None
        self._shutdown_budget: ShutdownBudget | None = None
        self._close_deadline: float | None = None

    def _bind_cleanup_budget(self, budget: ShutdownBudget) -> None:
        """Bind before start; ordinary publication failures do not begin it."""
        self._shutdown_budget = budget
        if isinstance(self.listener, UnixListener):
            self.listener._bind_cleanup_budget(budget)

    async def start(self) -> None:
        """Bind once, without taking a snapshot or starting sampling.

        Repeated successful start does not bind again. Bind failure propagates
        after partial listener cleanup. CollectorService awaits start before
        CollectorRuntime.run; a closed publisher cannot restart.
        """
        if self._closed:
            raise RuntimeError("Publisher is closed")
        if self._started:
            return
        try:
            await self.listener.start()
        except BaseException:
            # Include startup-failure cleanup in the enclosing service budget.
            if self._shutdown_budget is not None:
                self._shutdown_budget.begin()
            with suppress(BaseException):
                await self.close()
            raise
        if self._closed:
            raise asyncio.CancelledError
        self._started = True

    async def run(self, stop: asyncio.Event) -> None:
        """启动监听与发布，直到 stop；finally 关闭监听与客户端。

        任意客户端发送的首个字节均导致该连接关闭，不反序列化、不分派。
        EOF/发送失败/慢客户端只关闭相关连接；source/监听器内部错误在关闭
        全部发布资源后向上传播，由服务隔离为发布不可用而保持采样。不得
        自动重试监听或 source，亦不依据帧大小触发整个采集运行期停止。
        预置 stop 不绑定；NEW 时先调用 start，已 start 则复用现有监听，不双重绑定。
        重复并发 run 或关闭后 run 抛 RuntimeError。
        """
        if self._closed or self._running:
            raise RuntimeError("Publisher is already running or closed")
        self._running = True
        try:
            if stop.is_set():
                return
            await self.start()
            producing = spawn(self._produce(), name="snapshot-publish")
            self._tasks.add(producing)
            accepting = spawn(self._accept(), name="snapshot-accept")
            self._tasks.add(accepting)
            stopping = spawn(stop.wait())
            self._tasks.add(stopping)
            closing = spawn(self._closed_event.wait())
            self._tasks.add(closing)
            done, _ = await asyncio.wait(self._tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in (producing, accepting):
                if task in done and not task.cancelled():
                    task.result()
        finally:
            original = sys.exc_info()[1]
            try:
                await self.close()
            except BaseException:
                if original is None:
                    raise
            finally:
                self._running = False

    async def close(self) -> None:
        """幂等取消发布/接受/发送任务，250ms 内释放传输，不关闭采集运行期。"""
        if self._close_task is None:
            self._close_deadline = asyncio.get_running_loop().time() + 0.250
            if self._shutdown_budget is not None and self._shutdown_budget.deadline is not None:
                self._close_deadline = min(self._close_deadline, self._shutdown_budget.deadline)
            self._closed = True
            self._closed_event.set()
            await run_cleanup(self._cleanup, name="snapshot-publisher-close",
                              publish=lambda task: setattr(self, "_close_task", task))
        else:
            await await_owner(self._close_task)

    async def _produce(self) -> None:
        while True:
            heartbeat_deadline = asyncio.get_running_loop().time() + self.heartbeat_interval
            # This one synchronous read freezes state; workers only see its value.
            envelope = self.source()
            encoded = await encode_async(envelope)
            if self._closed:
                return
            publication = _Publication(encoded, envelope.published_at)
            self._latest = publication
            for reader in tuple(self._readers):
                self._offer(reader, publication)
            waiting = set()
            try:
                updated = spawn(self.wait_updated(envelope.snapshot.revision))
                waiting.add(updated)
                heartbeat = spawn(asyncio.sleep(max(
                    0.0, heartbeat_deadline - asyncio.get_running_loop().time())))
                waiting.add(heartbeat)
                done, _ = await asyncio.wait((updated, heartbeat), return_when=asyncio.FIRST_COMPLETED)
                if updated in done:
                    updated.result()
            finally:
                original = sys.exc_info()[1]
                for task in waiting:
                    cancel_once(task)
                try:
                    await join_tasks(waiting)
                except BaseException:
                    if original is None:
                        raise
            # Merge notifications already ready in this event-loop turn.
            await asyncio.sleep(0)

    @staticmethod
    def _offer(reader: _Reader, publication: _Publication) -> None:
        # Assignment replaces the sole pending frame, never an in-flight frame.
        reader.pending = publication
        reader.ready.set()

    async def _accept(self) -> None:
        while True:
            peer = await self.listener.accept()
            if len(self._readers) >= 64:
                await self._close_peer(peer)
                continue
            task = None
            try:
                reader = _Reader(peer)
                task = spawn(self._serve(reader), name="snapshot-reader")
                self._readers[reader] = task
                task.add_done_callback(self._observe_reader)
                if self._latest is not None:
                    self._offer(reader, self._latest)
            except BaseException:
                if task is not None:
                    cancel_once(task)
                    with suppress(BaseException):
                        await join_tasks({task})
                await self._close_peer(peer)
                raise

    @staticmethod
    def _observe_reader(task):
        # Reader failures are isolated; retain their exception without a
        # detached-task diagnostic after the slot is removed by its finally.
        with suppress(BaseException):
            task.result()

    async def _serve(self, reader: _Reader) -> None:
        jobs = set()
        try:
            sender = spawn(self._send(reader))
            jobs.add(sender)
            incoming = spawn(reader.peer.receive(1))
            jobs.add(incoming)
            await asyncio.wait((sender, incoming), return_when=asyncio.FIRST_COMPLETED)
        finally:
            original = sys.exc_info()[1]
            for task in jobs:
                cancel_once(task)
            try:
                await join_tasks(jobs)
            except BaseException:
                if original is None:
                    raise
            finally:
                await self._close_peer(reader.peer)
                self._readers.pop(reader, None)

    async def _send(self, reader: _Reader) -> None:
        first = True
        while True:
            await reader.ready.wait()
            reader.ready.clear()
            publication, reader.pending = reader.pending, None
            if publication is None:
                continue
            if first and self.clock() - publication.published_at > FRAME_TIMEOUT:
                continue
            async with asyncio.timeout(self.write_timeout):
                for offset in range(0, len(publication.data), IO_CHUNK_BYTES):
                    await reader.peer.send(publication.data[offset:offset + IO_CHUNK_BYTES])
                    await asyncio.sleep(0)
            first = False

    @staticmethod
    async def _close_peer(peer: PeerPort) -> None:
        with suppress(Exception):
            async with asyncio.timeout(0.100):
                await peer.close()

    async def _cleanup(self) -> None:
        jobs = self._tasks | set(self._readers.values())
        peers = tuple(reader.peer for reader in self._readers)
        for task in jobs:
            cancel_once(task)
        allocation_error = None
        factories = [self.listener.close] + [lambda peer=peer: self._close_peer(peer) for peer in peers]
        for factory in factories:
            try:
                jobs.add(spawn(factory()))
            except BaseException as error:
                if allocation_error is None:
                    allocation_error = error
                with suppress(BaseException):
                    async with asyncio.timeout_at(self._close_deadline):
                        await factory()
        try:
            await settle(jobs, self._close_deadline, reserve=0.010)
        finally:
            self._latest = None
            self._readers.clear()
            self._tasks.clear()
        if allocation_error is not None:
            raise allocation_error
