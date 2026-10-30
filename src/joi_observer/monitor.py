"""独立采样、状态提交与受控错误日志协调的单一写入者。"""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from joi_observer.collectors.base import Collector
from joi_observer.data.models import CollectionResult, ObjectKey
from joi_observer.data.state import MonitorState
from joi_observer.error_log import ErrorKind, ErrorLog, Failure


@dataclass
class _CollectorSlot:
    """一个来源的私有调度状态，由所属 Monitor 创建并独占持有。

    collector 是注入的采集端口引用，不因存于本结构而转移对象所有权。
    origin 为该来源首次调度的单调时刻；next_due 为下一个尚未消耗的周期槽，
    两者在首次调度前均为 None。来源忙时观察到的到期槽必须推进并跳过，
    不能在随后收割完成结果时重新使用，从而避免补采或重叠。

    task 为至多一个在途采集任务，空闲时为 None。completed_at 为本次任务
    实际结束或超时瞬间的单调时刻，不能使用后续 poll 收割时刻代替；发起新任务
    时清空。该结构不暴露给采集器或展示层，不自行采集、更新状态或记日志。
    """

    collector: Collector
    origin: float | None = None
    next_due: float | None = None
    task: asyncio.Task[CollectionResult] | None = None
    completed_at: float | None = None
    completed_wall_at: datetime | None = None


class Monitor:
    """独立调度各对象；采样节奏与 UI 刷新/交互完全分离。

    collectors 的 spec.key 唯一；state 包含这些声明（动态发现通过 register）。
    容器来源包含全部有效配置项，挂载来源只包含有效配置的前三项；UI可见行数
    不参与本模块调度，隐藏容器仍按相同周期更新状态并记录真实采集错误。
    interval/timeout 为有限正秒数；生产值由配置限制在[0.1,60]，测试可用更短超时。
    clock 必须为单调时钟；wall_clock 返回服务器本地的带时区 datetime，仅用于
    错误发生时间，未注入时取运行主机 datetime.now().astimezone()。日志只输出其
    YYYY-MM-DD HH:MM:SS 本地时间部分，不附带时区信息，也不转换成UTC。
    on_update 为常量时间的通知回调，不能在回调内采集、阻塞或抛异常。
    _slots 按 ObjectKey 保存独占的 _CollectorSlot；各slot由本Monitor创建，
    不与其他Monitor共享，不向外返回。_running 表示run正在执行，_stopped
    表示已进入永久停止状态。构造校验依赖并创建每对象的调度槽和初始标记，
    不启动任务或访问服务。
    """

    def __init__(
        self,
        collectors: tuple[Collector, ...],
        state: MonitorState,
        error_log: ErrorLog,
        *,
        interval: float = 1.0,
        timeout: float = 3.0,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] | None = None,
        on_update: Callable[[], None] | None = None,
    ) -> None:
        self._collectors: tuple[Collector, ...] = collectors
        self._state: MonitorState = state
        self._error_log: ErrorLog = error_log
        self._interval: float = interval
        self._timeout: float = timeout
        self._clock: Callable[[], float] = clock
        self._wall_clock: Callable[[], datetime] | None = wall_clock
        self._on_update: Callable[[], None] | None = on_update
        self._slots: dict[ObjectKey, _CollectorSlot] = {}
        self._running: bool = False
        self._stopped: bool = False
        self._polling = False
        self._shutdown_task: asyncio.Task[None] | None = None
        for value in (interval, timeout):
            if type(value) not in (int, float) or not math.isfinite(value) or value <= 0:
                raise ValueError("Sampling interval and timeout must be finite positive numbers.")
        registered = {item.key for item in state.snapshot().objects}
        for collector in collectors:
            key = collector.spec.key
            if key in self._slots:
                raise ValueError("Duplicate collector key.")
            if key not in registered:
                raise ValueError("Collector object is not registered in state.")
            self._slots[key] = _CollectorSlot(collector)

    async def poll(self) -> None:
        """一次非阻塞调度迭代，供 run 和确定性测试共用；不等待任何采集完成。

        首次迭代立即为所有来源发起任务，以该 clock 时刻为各自周期原点；后续
        迭代收割已完成任务、逐对象提交/通知，再启动到期且空闲的来源。每次调用
        至少让出一次事件循环。按 start+n*interval 固定节奏，忙时跳过到期槽，
        不堆积、追赶或重叠请求。每次迭代推进已观察到的到期槽，忙时跳过的槽
        即使本次随后收割成功也不能重用。完成时间在任务结束/超时瞬间取 clock()，
        非计划发起或后续收割时刻，避免延迟收割改变窗口口径。
        超时采用事件循环单调计时器（timeout），记录 timeout/collection.timeout；
        意外异常或错误key归一为 unexpected/collector.unexpected，无原始异常文本。
        失败也提交状态并通知、调用 error_log.record；完整成功调用 recovered，
        无论值是否0/None/N/A/Exited。日志限频绝不能影响提交。取消不记录。
        poll 不可并发调用，run 运行时外部调用抛 RuntimeError；stop 后调用亦抛错。
        run 应复用同一内部迭代核心或持有调度所有权，不能使自己的内部调用报错。
        """
        if self._running:
            raise RuntimeError("Cannot poll while Monitor.run is active.")
        await self._iterate()

    def _after(self, slot: _CollectorSlot, timestamp: float) -> float:
        """First grid slot strictly after timestamp, retaining the original phase."""
        assert slot.origin is not None
        count = math.floor((timestamp - slot.origin) / self._interval) + 1
        due = slot.origin + count * self._interval
        # Floating point division can round an exact boundary down by one ULP.
        if due <= timestamp:
            due = slot.origin + (count + 1) * self._interval
        return due

    async def _collect(self, slot: _CollectorSlot) -> CollectionResult:
        key = slot.collector.spec.key
        try:
            try:
                async with asyncio.timeout(self._timeout):
                    result = await slot.collector.collect()
                if not isinstance(result, CollectionResult) or result.key != key:
                    raise ValueError("Unexpected collection identity.")
                return result
            except TimeoutError:
                return CollectionResult(key, failure=Failure(
                    ErrorKind.TIMEOUT, "collection.timeout", "Collection timed out."))
            except Exception:
                return CollectionResult(key, failure=Failure(
                    ErrorKind.UNEXPECTED, "collector.unexpected", "Unexpected collector failure."))
        finally:
            slot.completed_at = self._clock()
            slot.completed_wall_at = (self._wall_clock() if self._wall_clock is not None
                                      else datetime.now().astimezone())

    async def _iterate(self) -> None:
        if self._stopped:
            raise RuntimeError("Monitor has stopped.")
        if self._polling:
            raise RuntimeError("Concurrent Monitor.poll calls are not allowed.")
        self._polling = True
        try:
            now = self._clock()
            for key, slot in self._slots.items():
                if slot.origin is None:
                    slot.origin = slot.next_due = now
                assert slot.next_due is not None
                if slot.task is not None:
                    if slot.task.done():
                        task, slot.task = slot.task, None
                        assert slot.completed_at is not None
                        # Slots elapsed during collection stay consumed, even when
                        # the caller did not poll until long after completion.
                        if slot.next_due < slot.completed_at:
                            slot.next_due = self._after(slot, slot.completed_at)
                        if not task.cancelled():
                            result = task.result()
                            self._state.accept(result, sampled_at=slot.completed_at)
                            if result.failure is None:
                                self._error_log.recovered(key.collector, key.object_id)
                            else:
                                self._error_log.record(
                                    key.collector, key.object_id, result.failure,
                                    monotonic_time=slot.completed_at,
                                    occurred_at=slot.completed_wall_at,
                                )
                            if self._on_update is not None:
                                self._on_update()
                    elif slot.next_due <= now:
                        slot.next_due = self._after(slot, now)
                if slot.next_due <= now:
                    slot.next_due = self._after(slot, now)
                    if slot.task is None:
                        slot.completed_at = slot.completed_wall_at = None
                        slot.task = asyncio.create_task(self._collect(slot))
            await asyncio.sleep(0)
        finally:
            self._polling = False

    async def run(self, stop: asyncio.Event) -> None:
        """直到 stop 被置位前持续 poll，最迟50ms处理完成/停止通知，空闲不忙等。

        stop 初始已置位时不发起采集。重复并发 run 抛 RuntimeError。finally 总是
        await self.stop()，因调用方取消而退出时保留 CancelledError。采集异常由 poll
        隔离，不终止本循环；状态契约违反等编程错误向上层传播并触发终端恢复。
        """
        if self._running or self._polling:
            raise RuntimeError("Monitor is already running.")
        if self._stopped:
            raise RuntimeError("Monitor has stopped.")
        self._running = True
        try:
            while not stop.is_set() and not self._stopped:
                await self._iterate()
                try:
                    await asyncio.wait_for(stop.wait(), timeout=0.025)
                except TimeoutError:
                    pass
        finally:
            try:
                await self.stop()
            finally:
                self._running = False

    async def stop(self) -> None:
        """幂等停止调度，取消并回收采集任务，关闭各采集器，不再提交迟到结果。

        采集器须遵守取消；总体关闭预算1秒（取消/close并发），超预算任务不能
        阻塞终端恢复。不能在关闭时记录取消或输出采集错误。ErrorLog 生命周期
        由组合根持有，本方法不关闭它。进程被 SIGKILL/断电无法保证恢复终端。
        """
        if self._shutdown_task is None:
            self._stopped = True
            active = [slot.task for slot in self._slots.values() if slot.task is not None]
            for task in active:
                task.cancel()
            self._shutdown_task = asyncio.create_task(self._cleanup(active))
        await asyncio.shield(self._shutdown_task)

    @staticmethod
    def _consume(task: asyncio.Task) -> None:
        if not task.cancelled():
            task.exception()

    async def _cleanup(self, active: list[asyncio.Task]) -> None:
        tasks = set(active)
        tasks.update(asyncio.create_task(collector.close()) for collector in self._collectors)
        try:
            if tasks:
                done, pending = await asyncio.wait(tasks, timeout=1.0)
                for task in done:
                    self._consume(task)
                for task in pending:
                    task.cancel()
                    task.add_done_callback(self._consume)
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
                    task.add_done_callback(self._consume)
