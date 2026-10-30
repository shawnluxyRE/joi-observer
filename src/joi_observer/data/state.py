"""Monitor 的单写者内存状态和隔离的只读快照。"""

from __future__ import annotations

import time
import math
import re
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field

from joi_observer.data.models import (
    CollectionResult,
    HistoryPoint,
    Metric,
    ObjectKey,
    ObjectSpec,
    ObjectSnapshot,
    StateSnapshot,
)
from joi_observer.error_log import Failure


def _number(value: object, *, positive: bool = False) -> bool:
    return (type(value) in (int, float) and math.isfinite(value)
            and (value > 0 if positive else value >= 0))


def _text(value: object, *, allow_empty: bool = True) -> bool:
    return (isinstance(value, str) and (allow_empty or bool(value))
            and all(character.isprintable() for character in value))


def _validate_key(key: ObjectKey) -> None:
    if (not isinstance(key, ObjectKey)
            or not isinstance(key.collector, str)
            or re.fullmatch(r"[a-z][a-z0-9_.-]{0,31}", key.collector) is None
            or not _text(key.object_id, allow_empty=False)
            or len(key.object_id) > 128
            or "://" in key.object_id):
        raise ValueError("Invalid monitoring object key.")


def _validate_metrics(metrics: tuple[Metric, ...], *, template: bool = False) -> None:
    if not isinstance(metrics, tuple):
        raise ValueError("Metrics must be an immutable tuple.")
    names: set[str] = set()
    for metric in metrics:
        if (not isinstance(metric, Metric)
                or not _text(metric.name, allow_empty=False)
                or metric.name in names
                or not _text(metric.unit)
                or type(metric.applicable) is not bool):
            raise ValueError("Invalid or duplicate metric.")
        value = metric.value
        if (value is not None and type(value) not in (int, float, str)
                or type(value) in (int, float) and not math.isfinite(value)
                or isinstance(value, str) and not _text(value)
                or (template or not metric.applicable) and value is not None):
            raise ValueError("Invalid metric value.")
        names.add(metric.name)


def _validate_spec(spec: ObjectSpec) -> None:
    if not isinstance(spec, ObjectSpec):
        raise ValueError("Invalid monitoring object specification.")
    _validate_key(spec.key)
    _validate_metrics(spec.metrics, template=True)


@dataclass
class _ObjectState:
    """单对象的可变内存状态，由所属 MonitorState 创建并独占持有。

    spec 为注册声明；metrics 保存当前展示值，字段初始化及失败时保留最后值的
    合并由 MonitorState 原子完成。latest_result 是最近提交的采集结果，sampled_at 是该次
    尝试实际完成的单调时刻；首次未提交时二者均为None。错误详情仅从
    latest_result.failure 获取，不另外复制，也不进入对外快照。

    previous_success 为最近一次提交之前的最后完整成功结果，
    previous_success_at 为其单调完成时刻。失败期间可保留这份旧成功样本，
    但 baseline_valid 必须为False；恢复后的第一次完整成功仍不能跨故障
    比较，直到再取得下一次可比较的完整成功才可置True。该标记只声明基线
    可比性，不在此计算吞吐、计数器重置或均值。

    stale 表示最近一次提交是否仍有实际采集失败；history 保存有效点和失败
    缺口，时间/点数裁剪由MonitorState统一执行。每个实例有独立deque，不能
    向采集器、TUI或Web暴露本对象及其可变容器；对外仅生成不可变快照。
    """

    spec: ObjectSpec
    metrics: tuple[Metric, ...] = ()
    latest_result: CollectionResult | None = None
    sampled_at: float | None = None
    previous_success: CollectionResult | None = None
    previous_success_at: float | None = None
    baseline_valid: bool = False
    stale: bool = False
    history: deque[HistoryPoint] = field(default_factory=deque)


class MonitorState:
    """独立于 UI/采集适配器的有界内存状态。

    参数 specs 不得重复，history_seconds 为有限正数（默认60），max_history_points
    为正整数（默认602，可容纳最小0.1秒周期的60秒窗口及边界）。clock 提供不回退
    的单调秒数，不能用墙上时间计算速率/历史。构造仅保存参数，禁止 IO。

    实现须保留每对象最近结果、上次成功结果及时间、失败状态和历史；失败使跨故障
    差分基线失效，原始计数器差分和均值由 REQ-004 补充。Monitor 在一个事件循环
    线程中统一写入；读者只能获得冻结快照，不能访问可变容器。_entries 按ObjectKey
    保存本State独占创建的_ObjectState，_revision记录有效状态更新的版本。
    构造校验声明并创建初始条目，初始版本为零。
    无需数据库或锁服务。
    """

    def __init__(
        self,
        specs: tuple[ObjectSpec, ...] = (),
        *,
        history_seconds: float = 60.0,
        max_history_points: int = 602,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._specs: tuple[ObjectSpec, ...] = specs
        self._history_seconds: float = history_seconds
        self._max_history_points: int = max_history_points
        self._clock: Callable[[], float] = clock
        self._entries: dict[ObjectKey, _ObjectState] = {}
        self._revision: int = 0
        if (not _number(history_seconds, positive=True)
                or type(max_history_points) is not int or max_history_points <= 0
                or not callable(clock) or not isinstance(specs, tuple)):
            raise ValueError("Invalid state configuration.")
        for spec in specs:
            _validate_spec(spec)
            if spec.key in self._entries:
                raise ValueError("Duplicate monitoring object key.")
            self._entries[spec.key] = _ObjectState(spec=spec, metrics=spec.metrics)

    def register(self, spec: ObjectSpec) -> None:
        """由 Monitor 注册新发现的 GPU 等对象；保留顺序，创建 None 字段模板。

        已有 key 且模板相同为幂等无操作；模板不同抛 ValueError。失败和恢复不能
        删除已知对象/模板。设备发现接口在 REQ-002 设计，不在此猜测设备或分组。
        """
        _validate_spec(spec)
        existing = self._entries.get(spec.key)
        if existing is not None:
            if existing.spec != spec:
                raise ValueError("Registered object template cannot change.")
            return
        self._entries[spec.key] = _ObjectState(spec=spec, metrics=spec.metrics)
        self._revision += 1

    def accept(self, result: CollectionResult, *, sampled_at: float) -> None:
        """原子提交一次采集完成，改变该对象的当前值、历史、状态和 revision。

        key 未注册抛 KeyError；时间非有限/负数/早于或等于该对象前次提交时刻、
        未声明或重复字段、成功结果缺少声明字段抛 ValueError，失败不改变状态。
        成功覆盖字段并清除 stale；失败保留缺失字段的最后值、置 stale、插入历史
        缺口，本次成功取得的字段仍可更新。初次失败保持 None。内部可保留失败详情，
        snapshot 永不暴露。保留 [sampled_at-history_seconds, sampled_at] 内的点，
        再按 max_history_points 上限裁剪。
        方法无 IO、不记日志、不通知 UI；Monitor 在提交后统一发通知。
        """
        if not isinstance(result, CollectionResult):
            raise ValueError("Invalid collection result.")
        _validate_key(result.key)
        entry = self._entries[result.key]
        if (not _number(sampled_at)
                or entry.sampled_at is not None and sampled_at <= entry.sampled_at):
            raise ValueError("Sample time must be finite, nonnegative and increasing.")
        _validate_metrics(result.metrics)
        if result.failure is not None and not isinstance(result.failure, Failure):
            raise ValueError("Invalid collection failure.")
        declared = {metric.name for metric in entry.spec.metrics}
        incoming = {metric.name: metric for metric in result.metrics}
        if (not incoming.keys() <= declared
                or result.failure is None and incoming.keys() != declared):
            raise ValueError("Collection fields do not match the declared template.")

        # Validate the entire submission before changing any live state.
        merged = tuple(incoming.get(metric.name, metric) for metric in entry.metrics)
        previous = entry.latest_result
        if previous is not None and previous.failure is None:
            entry.previous_success = previous
            entry.previous_success_at = entry.sampled_at
        entry.baseline_valid = (result.failure is None and previous is not None
                                and previous.failure is None)
        entry.latest_result = result
        entry.sampled_at = sampled_at
        entry.metrics = merged
        entry.stale = result.failure is not None
        entry.history.append(HistoryPoint(sampled_at, None if entry.stale else merged))
        oldest = sampled_at - self._history_seconds
        while entry.history and (entry.history[0].sampled_at < oldest
                                 or len(entry.history) > self._max_history_points):
            entry.history.popleft()
        self._revision += 1

    def snapshot(self) -> StateSnapshot:
        """返回深不可变且与随后写入隔离的视图；不采集、不写文件、不改变 revision。

        视图历史进一步按 clock() 的当前60秒窗口过滤，即使该对象长时间没有提交，
        旧历史也不会冒充近期有效观测。最近值仍保留，不按年龄自动生成采集错误。
        """
        now = self._clock()
        oldest = now - self._history_seconds
        return StateSnapshot(tuple(
            ObjectSnapshot(
                key=entry.spec.key,
                metrics=entry.metrics,
                stale=entry.stale,
                sampled_at=entry.sampled_at,
                history=tuple(point for point in entry.history
                              if oldest <= point.sampled_at <= now),
            )
            for entry in self._entries.values()
        ), self._revision)

