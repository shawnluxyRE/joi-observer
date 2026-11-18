"""宿主机独占采集、快照发布故障隔离与有界服务生命周期。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
import errno
import os
from pathlib import Path
import stat
import time
from typing import Protocol
from uuid import uuid4

from joi_observer._shutdown import ShutdownBudget, await_owner, join_tasks, run_cleanup, spawn
from joi_observer.config import AppConfig, load_config
from joi_observer.ipc.protocol import SnapshotEnvelope, build_metadata
from joi_observer.ipc.server import ListenerPort, SnapshotPublisher, UnixListener
from joi_observer.runtime import CollectorRuntime


DEFAULT_ENDPOINT = Path("/run/joi-observer/snapshot.sock")
DEFAULT_LOCK_PATH = Path("/run/joi-observer/service.lock")


def _host_label(value: str) -> str:
    """Make local presentation single-line before strict metadata validation.

    Preserve printable Unicode for each client's display capabilities, without
    querying a terminal locale, clipping, stripping, or inferring missing text.
    Wrong types and empty values remain the protocol validator's responsibility.
    """
    if type(value) is not str:
        return value
    return "".join(character if character.isprintable() else " " for character in value)


class ServiceStartError(RuntimeError):
    """可预期的启动/权限/监听失败；入口使用固定安全提示与退出码。"""


class ServiceAlreadyRunning(ServiceStartError):
    """另一个进程持有服务锁；不得启动第二套采集器。"""


class LeasePort(Protocol):
    """独占宿主机采集权的本地 OS 边界。"""

    def acquire(self) -> None:
        """非阻塞获取；冲突抛 ServiceAlreadyRunning，不连接 socket 探活。"""
        ...

    def release(self) -> None:
        """幂等释放锁，不删除锁文件，防止出现不同 inode 的两个锁持有者。"""
        ...


class InstanceLease:
    """Linux flock 独占锁；构造无 I/O，锁覆盖完整服务运行和清理过程。

    默认锁不随客户端 endpoint 选项变化；一个宿主机只有一个配置/采样运行期。
    拒绝符号链接和非普通文件，以 O_NOFOLLOW 打开、0600 创建，不回显文件内容。
    目录必须属于服务账户且不允许读者写入；持锁后才能处理残留 socket。
    测试可显式指定临时锁路径，不需要启动或连接任何服务器。
    """

    def __init__(self, path: Path = DEFAULT_LOCK_PATH) -> None:
        self.path = path
        self._fd: int | None = None

    def acquire(self) -> None:
        """获取 LOCK_EX|LOCK_NB；重复 acquire 抛 RuntimeError，冲突抛专用异常。"""
        import fcntl

        if self._fd is not None:
            raise RuntimeError("Lease is already acquired")
        parent = self.path.parent.lstat()
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.geteuid()
                or stat.S_IMODE(parent.st_mode) & 0o022):
            raise ValueError("Unsafe collector lock directory")
        descriptor = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
        try:
            info = os.fstat(descriptor)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
                    or stat.S_IMODE(info.st_mode) & 0o077):
                raise ValueError("Unsafe collector lock")
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno in (errno.EAGAIN, errno.EACCES):
                    raise ServiceAlreadyRunning("Collector service already running.") from None
                raise
        except BaseException:
            os.close(descriptor)
            raise
        self._fd = descriptor

    def release(self) -> None:
        """关闭本实例持有的 fd；重复调用无副作用，进程死亡由内核释放锁。"""
        if self._fd is not None:
            descriptor, self._fd = self._fd, None
            os.close(descriptor)


class CollectorService:
    """只在服务启动时加载配置、创建运行期并发布同源快照。

    构造仅保存参数。run 获取锁、读取并校验 config_path 一次，创建新的
    instance_id/config_revision（随机 UUID），装配唯一 runtime、准备日志及
    metadata，然后并发运行采样与发布。所有 config 的文件改动到下次新进程
    才生效。host_factory 返回设备标签和系统版本，仅启动调用一次；生产复用
    现有本机 os-release 读取，不调用 DNS。listener/lease 是外部 OS 替换点。
    """

    def __init__(self, config_path: Path, *, endpoint: Path = DEFAULT_ENDPOINT,
                 runtime_factory: Callable[[AppConfig], CollectorRuntime] = CollectorRuntime,
                 listener: ListenerPort | None = None,
                 lease: LeasePort | None = None,
                 host_factory: Callable[[], tuple[str, str]] | None = None,
                 on_warning: Callable[[str], None] | None = None) -> None:
        self.config_path = config_path
        self.endpoint = endpoint
        self._runtime_factory = runtime_factory
        self._listener = listener
        self._lease = lease
        self._host_factory = host_factory
        self._on_warning = on_warning
        self._runtime: CollectorRuntime | None = None
        self._publisher: SnapshotPublisher | None = None
        self._metadata = None
        self._instance_id: str | None = None
        self._config_revision: str | None = None
        self._sequence = 0
        self._started = False
        self._closed = False
        self._export_ready = False
        self._lease_acquired = False
        self._stop: asyncio.Event | None = None
        self._tasks: set[asyncio.Task] = set()
        self._close_task: asyncio.Task | None = None
        self._warnings: set[str] = set()
        self._shutdown_budget = ShutdownBudget()
        self._startup_task: asyncio.Task | None = None

    def export_snapshot(self) -> SnapshotEnvelope:
        """投影当前完整原子 envelope，不采集、不访问配置或其他 I/O。

        仅发布任务在更新通知或无变化心跳时调用，sequence 从 1 递增；
        State revision 可保持不变。读者加入不触发额外 source 调用。
        每帧使用同一生效 metadata、instance_id/config_revision，published_at
        与 State 共用宿主 monotonic 秒。先读取 published_at，再在同一无 await
        同步段调用 runtime.snapshot()，避免 60 秒边界点因较晚发布时钟被拒绝。
        初始化前或关闭后抛 RuntimeError。
        """
        if not self._export_ready or self._closed or self._runtime is None:
            raise RuntimeError("Collector service has no active snapshot")
        published_at = time.monotonic()
        snapshot = self._runtime.snapshot()
        self._sequence += 1
        return SnapshotEnvelope(self._instance_id, self._config_revision, self._sequence,
                                published_at, self._metadata, snapshot)

    async def run(self, stop: asyncio.Event) -> None:
        """持续采集直到 stop；无需 TTY，无客户端也运行。

        配置非法在构建 runtime 前抛 ConfigError；预置 stop 不获取锁或采集。
        锁/配置/装配/监听失败必须清理已取得资源，不能留下采样后台任务。
        可预期的 OS 权限/绑定错误归一为 ServiceStartError，禁止附带原始错误；
        配置错误保留 ConfigError，编程错误继续向上传播。日志 prepare 为 False
        时经 on_warning 最多一次发送固定文本 'Error log unavailable; monitoring
        will continue.'；生产 CLI 注入 stderr 回调，服务自身不打印采集事件。
        先 await publisher.start() 完成绑定，再并发 publisher.run 与 runtime.run；
        publisher.run 复用已有监听，不能再次绑定。runtime 内部错误结束整个服务。
        监听启动失败在采样启动前抛
        ServiceStartError；成功启动后的发布任务失败则只关闭发布器/客户端，
        不取消 Monitor，不自动重启发布器。on_warning 最多一次接收固定文本
        'Snapshot publishing stopped; collection continues. Restart collector
        service to restore access.'。回调异常不得停止采集。显式重启服务才
        恢复发布；旧客户端仍须手动重新运行。单一来源/客户端失败各自隔离。
        finally 以同一个一秒预算先停发布，再停采集/日志，最后释放锁。
        stop 不代表成功结果；清理后仍检查并传播运行期已发生的内部错误。
        取消传播 CancelledError；SIGINT/SIGTERM 由 CLI 转为 stop/取消。
        run 只能执行一次，重复运行抛 RuntimeError。
        """
        if self._started or self._closed:
            raise RuntimeError("Collector service is already running or closed")
        self._started = True
        self._stop = stop
        if stop.is_set():
            self._closed = True
            return
        runtime_task: asyncio.Task | None = None
        primary_error: BaseException | None = None
        try:
            lease = self._lease if self._lease is not None else InstanceLease()
            self._lease = lease
            try:
                lease.acquire()
            except ServiceStartError:
                raise
            except (OSError, ValueError):
                raise ServiceStartError("Collector service could not start.") from None
            self._lease_acquired = True
            config = load_config(self.config_path)
            self._instance_id, self._config_revision = str(uuid4()), str(uuid4())
            self._runtime = self._runtime_factory(config)
            self._runtime._bind_cleanup_budget(self._shutdown_budget)
            if not self._runtime.prepare_log():
                self._warn("Error log unavailable; monitoring will continue.")
            if self._host_factory is None:
                from joi_observer._host import local_host_info
                host = local_host_info()
                hostname, system = host.hostname, host.system
            else:
                hostname, system = self._host_factory()
            self._metadata = build_metadata(config, hostname=_host_label(hostname),
                                            system=_host_label(system))
            self._export_ready = True
            listener = self._listener if self._listener is not None else UnixListener(self.endpoint)
            self._publisher = SnapshotPublisher(self.export_snapshot, listener,
                                                wait_updated=self._runtime.wait_updated)
            self._publisher._bind_cleanup_budget(self._shutdown_budget)
            try:
                self._startup_task = spawn(self._publisher.start(), name="collector-listen-start")
                await self._startup_task
            except asyncio.CancelledError:
                if self._closed:
                    return
                raise
            except (OSError, ValueError):
                raise ServiceStartError("Collector service could not start.") from None
            if self._closed or stop.is_set():
                return
            runtime_task = spawn(self._capture(self._runtime.run, stop), name="collector-runtime")
            self._tasks.add(runtime_task)
            publisher_task = spawn(self._capture(self._publisher.run, stop), name="collector-publisher")
            self._tasks.add(publisher_task)
            stopping = spawn(stop.wait())
            self._tasks.add(stopping)
            done, _ = await asyncio.wait(self._tasks, return_when=asyncio.FIRST_COMPLETED)
            if runtime_task in done:
                error = runtime_task.result()
                if error is not None and not (self._closed and isinstance(error, asyncio.CancelledError)):
                    raise error
                return
            if stopping in done or self._closed:
                return
            # All running publisher failures are isolated from collection.
            if publisher_task in done:
                self._warn("Snapshot publishing stopped; collection continues. Restart collector service to restore access.")
                done, _ = await asyncio.wait((runtime_task, stopping), return_when=asyncio.FIRST_COMPLETED)
                if runtime_task in done:
                    error = runtime_task.result()
                    if error is not None and not (self._closed and isinstance(error, asyncio.CancelledError)):
                        raise error
        except BaseException as caught:
            primary_error = caught
        finally:
            cleanup_error: BaseException | None = None
            try:
                await self.close()
            except BaseException as caught:
                cleanup_error = caught
            # Cleanup must preserve a config/start/factory failure. With no
            # earlier failure (or only cancellation), a joined runtime failure
            # still wins over a stop request that became ready during cleanup.
            joined_error = None
            if runtime_task is not None and runtime_task.done() and not runtime_task.cancelled():
                error = runtime_task.result()
                if error is not None and not isinstance(error, asyncio.CancelledError):
                    joined_error = error
            selected = primary_error
            if selected is None or isinstance(selected, asyncio.CancelledError):
                if joined_error is not None:
                    selected = joined_error
                elif selected is None:
                    selected = cleanup_error
            if selected is not None:
                raise selected

    async def close(self) -> None:
        """幂等清理部分启动、监听及采集资源；清理错误不掩盖原错误。

        本实例 socket 清理完成后才释放锁，锁文件保留；不删除配置/指标文件。
        """
        if self._closed and self._close_task is None:
            return
        if self._close_task is None:
            self._shutdown_budget.begin()
            self._closed = True
            self._export_ready = False
            await run_cleanup(self._cleanup, name="collector-service-close",
                              publish=lambda owner: setattr(self, "_close_task", owner))
        else:
            await await_owner(self._close_task)

    @staticmethod
    async def _capture(operation, *args) -> BaseException | None:
        # KeyboardInterrupt must reach the owner after all siblings are cleaned.
        try:
            await operation(*args)
        except BaseException as error:
            return error
        return None

    def _warn(self, message: str) -> None:
        if message in self._warnings:
            return
        self._warnings.add(message)
        if self._on_warning is not None:
            with suppress(Exception):
                self._on_warning(message)

    async def _cleanup(self) -> None:
        error: BaseException | None = None
        try:
            if self._stop is not None:
                self._stop.set()
            if self._publisher is not None:
                # Close may unblock a partially initialized listener. It must
                # finish before sampling or lock release can be considered.
                try:
                    await self._publisher.close()
                except BaseException as caught:
                    error = caught
            if self._startup_task is not None:
                if not self._startup_task.done():
                    self._startup_task.cancel()
                try:
                    await join_tasks((self._startup_task,))
                except BaseException as caught:
                    if error is None:
                        error = caught
            jobs = set(self._tasks)
            runtime_close = None
            if self._runtime is not None:
                try:
                    runtime_close = spawn(self._runtime.close())
                    jobs.add(runtime_close)
                except BaseException as caught:
                    if error is None:
                        error = caught
                    # No Task owns this coroutine. Join the real runtime in
                    # this cleanup owner before releasing collection authority.
                    try:
                        await self._runtime.close()
                    except BaseException as caught:
                        if error is None:
                            error = caught
            if jobs:
                # Runtime/Monitor bound their real work with the same budget;
                # joining them prevents a shielded cleanup outliving the lease.
                try:
                    await join_tasks(jobs)
                except BaseException as caught:
                    if error is None:
                        error = caught
            if runtime_close is not None:
                try:
                    runtime_close.result()
                except BaseException as caught:
                    if error is None:
                        error = caught
            self._tasks.clear()
        finally:
            if self._lease_acquired:
                self._lease_acquired = False
                with suppress(Exception):
                    self._lease.release()
        if error is not None:
            raise error
