"""采集服务独占的来源装配、更新通知与有界资源回收。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, TYPE_CHECKING

from joi_observer._shutdown import (
    ShutdownBudget, await_owner, cleanup_inline, join_tasks, run_cleanup, settle, spawn,
)
from joi_observer.collectors.docker import LocalDockerCommand, build_docker_collectors
from joi_observer.collectors.hardware import build_hardware_sources
from joi_observer.collectors.vllm import AsyncHttpClient, build_vllm_collectors
from joi_observer.config import AppConfig
from joi_observer.data.models import StateSnapshot
from joi_observer.data.state import MonitorState
from joi_observer.monitor import Monitor
from joi_observer.error_log import ErrorLog

if TYPE_CHECKING:
    from joi_observer.collectors.docker import DockerCommandPort
    from joi_observer.collectors.vllm import HttpPort


class RuntimeLog(Protocol):
    """日志外部生命周期；采集事件仍由真实 Monitor 统一提交。"""

    def prepare(self) -> bool:
        """启动采集前准备文件；失败允许继续采集，由服务入口提示一次。"""
        ...

    async def close(self, *, timeout: float = 1.0) -> bool:
        """在剩余退出预算内排空日志，不向控制台补打采集错误。"""
        ...


@dataclass(frozen=True)
class CollectorComponents:
    """同一服务独占的状态、真实调度器与日志；不包含终端或客户端。

    monitor 必须写入 state，使用 error_log，且 on_update=updates.set；
    updates 仅为更新通知，不持有业务结果。注入仅替换装配和外部端口，
    不替换监控计算。所有组件随运行期一起关闭，不随客户端退出关闭。
    """

    state: MonitorState
    monitor: Monitor
    error_log: RuntimeLog
    updates: asyncio.Event


class CollectorRuntime:
    """持有唯一采集运行期；构造只保存参数，无 I/O。

    默认装配复用硬件/Docker/vLLM 工厂，保留全部配置对象和 GPU 动态发现。
    prepare_log 或 run 首次组装，每次运行期只创建一套 State/Monitor/日志。
    已注入 components 时不调用来源工厂。无客户端时仍连续采样。
    """

    def __init__(self, config: AppConfig, *, components: CollectorComponents | None = None,
                 docker_command_factory: Callable[[], DockerCommandPort] | None = None,
                 vllm_http_factory: Callable[[], HttpPort] | None = None) -> None:
        self.config = config
        self.components = components
        self._docker_command_factory = docker_command_factory
        self._vllm_http_factory = vllm_http_factory
        self._closed = False
        self._running = False
        self._stop_event: asyncio.Event | None = None
        self._monitor_task: asyncio.Task | None = None
        self._deadline: float | None = None
        self._shutdown_budget = ShutdownBudget()
        self._close_task: asyncio.Task | None = None
        self._waiters: set[asyncio.Task] = set()
        self._unowned: list[object] = []
        if components is not None:
            components.monitor._bind_cleanup_budget(self._shutdown_budget)

    def prepare_log(self) -> bool:
        """组装一次并准备日志，不采样；False 不阻断服务启动。"""
        if self._closed:
            raise RuntimeError("Collector runtime is closed.")
        return self._components().error_log.prepare()

    def snapshot(self) -> StateSnapshot:
        """返回已组装 State 的深不可变快照；无 I/O、不采集、不改变 revision。

        未组装时抛 RuntimeError。客户端不能取得此运行期或可变 State 引用。
        """
        if self.components is None:
            raise RuntimeError("Collector runtime is not assembled.")
        return self.components.state.snapshot()

    async def wait_updated(self, after_revision: int) -> None:
        """等到 State revision 大于 after_revision；不采样，不访问外部来源。

        after_revision 是非负真整数。已发生更新时立即返回；否则等待 Monitor
        的常量时间通知，清除通知和检查 revision 必须防止丢失更新。连续通知
        可以合并，但不能靠固定一秒轮询代替。取消向上传播；close 取消等待者。
        只用通知唤醒发布任务，不在 Monitor 回调内编码、发送或等待客户端。
        """
        if type(after_revision) is not int or after_revision < 0:
            raise ValueError("Revision must be a nonnegative integer.")
        if self.components is None:
            raise RuntimeError("Collector runtime is not assembled.")
        task = asyncio.current_task()
        assert task is not None
        self._waiters.add(task)
        try:
            while not self._closed:
                if self.snapshot().revision > after_revision:
                    return
                self.components.updates.clear()
                # Check again after clearing: an already committed revision is
                # observable even when its coalesced notification was consumed.
                if self.snapshot().revision > after_revision:
                    return
                await self.components.updates.wait()
            raise asyncio.CancelledError
        finally:
            self._waiters.discard(task)

    async def run(self, stop: asyncio.Event) -> None:
        """运行真实 Monitor 至 stop；预置 stop 不发起采样。

        无 TTY/客户端检查。来源失败隔离为 STALE，编程错误传播给服务。
        重复并发 run 或关闭后 run 抛 RuntimeError；取消保留 CancelledError。
        finally 关闭自身资源，服务端退出预算与 close 共用最多一秒。
        stop 只是停止请求；清理收束后仍传播 Monitor 已发生的内部错误。
        """
        if self._running or self._closed:
            raise RuntimeError("Collector runtime is already running or closed.")
        self._running = True
        self._stop_event = stop
        stopping: asyncio.Task | None = None
        primary_error: BaseException | None = None
        try:
            if stop.is_set():
                return
            components = self._components()

            async def capture_monitor():
                # Keep BaseException inside this task until the owner has
                # recovered resources, as in the original runtime boundary.
                try:
                    await components.monitor.run(stop)
                except BaseException as error:
                    return error
                return None

            self._monitor_task = spawn(capture_monitor(), name="collector-monitor")
            stopping = spawn(stop.wait(), name="collector-stop")
            done, _ = await asyncio.wait((self._monitor_task, stopping),
                                         return_when=asyncio.FIRST_COMPLETED)
            if self._monitor_task in done:
                error = self._monitor_task.result()
                if error is not None:
                    raise error
        except BaseException as caught:
            primary_error = caught
        finally:
            cleanup_error: BaseException | None = None
            try:
                if stopping is not None:
                    stopping.cancel()
                    await join_tasks((stopping,))
            except BaseException as caught:
                cleanup_error = caught
            try:
                await self.close()
            except BaseException as caught:
                if cleanup_error is None:
                    cleanup_error = caught
            self._running = False
            joined_error = None
            monitor_task = self._monitor_task
            if monitor_task is not None and monitor_task.done() and not monitor_task.cancelled():
                error = monitor_task.result()
                if error is not None and not isinstance(error, asyncio.CancelledError):
                    joined_error = error
            # An early assembly failure remains primary; a real Monitor fatal
            # observed after cleanup still outranks a concurrent stop/cancel.
            selected = primary_error
            if selected is None or isinstance(selected, asyncio.CancelledError):
                if joined_error is not None:
                    selected = joined_error
                elif selected is None:
                    selected = cleanup_error
            if selected is not None:
                raise selected

    async def close(self) -> None:
        """幂等停止 Monitor、来源与日志；部分装配失败也可调用。

        清理错误不覆盖原异常，不生成正常指标文件，也不因客户端退出调用。
        """
        if self._closed and (self._close_task is None or self._close_task.done()):
            return
        self._deadline = self._shutdown_budget.begin()
        if self._close_task is None:
            await run_cleanup(self._cleanup, name="collector-cleanup",
                              publish=lambda owner: setattr(self, "_close_task", owner))
        else:
            await await_owner(self._close_task)

    def _bind_cleanup_budget(self, budget: ShutdownBudget) -> None:
        """Service wiring only; injected components inherit the same deadline."""
        if self._close_task is not None and budget is not self._shutdown_budget:
            raise RuntimeError("Cannot replace an active cleanup budget.")
        self._shutdown_budget = budget
        if self.components is not None:
            self.components.monitor._bind_cleanup_budget(budget)

    def _components(self) -> CollectorComponents:
        """Assemble each source once without starting any source IO."""
        if self.components is not None:
            self.components.monitor._bind_cleanup_budget(self._shutdown_budget)
            return self.components
        hardware = build_hardware_sources(self.config)
        self._unowned.extend((*hardware.collectors, hardware.discovery))
        staged: list[object] = []

        def tracked(factory):
            def create():
                port = factory()
                staged.append(port)
                self._unowned.append(port)
                return port
            return create

        def adopt(collectors):
            identities = {id(port) for port in staged}
            self._unowned[:] = [source for source in self._unowned if id(source) not in identities]
            staged.clear()
            self._unowned.extend(collectors)

        docker = build_docker_collectors(
            self.config.containers, timeout=self.config.collection_timeout,
            command_factory=tracked(self._docker_command_factory if self._docker_command_factory is not None
                                    else LocalDockerCommand),
        )
        adopt(docker)
        vllm = build_vllm_collectors(
            self.config, http_factory=tracked(self._vllm_http_factory if self._vllm_http_factory is not None
                                             else AsyncHttpClient),
        )
        adopt(vllm)
        collectors = hardware.collectors + docker + vllm
        state = MonitorState(tuple(collector.spec for collector in collectors))
        log = ErrorLog(self.config.logging)
        self._unowned.append(log)
        updates = asyncio.Event()
        monitor = Monitor(collectors, state, log, interval=self.config.sample_interval,
                          timeout=self.config.collection_timeout, on_update=updates.set)
        monitor._bind_cleanup_budget(self._shutdown_budget)
        monitor.register_discovery(hardware.discovery)
        self.components = CollectorComponents(state, monitor, log, updates)
        self._unowned.clear()  # Monitor now owns every source.
        return self.components

    def _remaining(self) -> float:
        return self._shutdown_budget.remaining()

    async def _cleanup(self) -> None:
        self._closed = True
        if self._stop_event is not None:
            self._stop_event.set()
        current = asyncio.current_task()
        for waiter in tuple(self._waiters):
            if waiter is not current:
                waiter.cancel()
        pending: set[asyncio.Task] = set()
        deferred = []
        error: BaseException | None = None

        def register(factory, *, bounded=False):
            nonlocal error
            try:
                job = spawn(factory())
            except BaseException as caught:
                if error is None:
                    error = caught
                deferred.append((factory, bounded))
                return None
            pending.add(job)
            return job

        if self._monitor_task is not None:
            # stop + Monitor.stop own cancellation of actual source work. A
            # cancellation of this wrapper can replace a genuine
            # Monitor error while it is awaiting its cleanup finally.
            pending.add(self._monitor_task)
        stop_task = log_settle = None
        if self.components is not None:
            self.components.monitor._bind_cleanup_budget(self._shutdown_budget)
            stop_task = register(self.components.monitor.stop)
            log = register(lambda: self.components.error_log.close(timeout=max(self._remaining(), 1e-9)),
                           bounded=True)
            if log is not None:
                # Keep this explicit settle owner: allocation failure must join
                # the already registered log, rather than abandon its drain.
                log_settle = register(lambda: settle({log}, self._deadline))
            # Monitor owns and bounds its real source tasks. Do not cancel its
            # shielded stop waiter at another deadline and abandon the owner.
        else:
            # A later factory may fail after an earlier source group was built.
            for source in self._unowned:
                register(source.close, bounded=True)
        for factory, bounded in deferred:
            try:
                if bounded:
                    await cleanup_inline(factory, self._deadline)
                else:
                    await factory()
            except BaseException as caught:
                if error is None:
                    error = caught
        try:
            if self.components is None:
                await settle(pending, self._deadline)
            else:
                await join_tasks(pending)
        except BaseException as caught:
            if error is None:
                error = caught
        finally:
            self._unowned.clear()
        for owner in (stop_task, log_settle):
            if owner is not None:
                try:
                    owner.result()
                except BaseException as caught:
                    if error is None:
                        error = caught
        if error is not None:
            raise error
