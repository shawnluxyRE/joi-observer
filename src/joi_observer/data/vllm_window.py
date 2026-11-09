"""vLLM 累计观测的纯计算接口；由状态层调用，不执行采集或持有状态。

这里只接收已经核实单位并按引擎身份归一的计数，不解释 Prometheus 名称。
调用者为每个模型、每类指标维护独立基线和有界区间，禁止跨故障或重启差分。
所有校验与计算均为纯函数，不修改调用者的数据。
"""

from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
import math


def _finite_number(value: object, *, positive: bool = False) -> bool:
    """Validate floating-point domains without coercing arbitrary large integers."""
    try:
        return (type(value) in (int, float) and math.isfinite(value)
                and (value > 0 if positive else value >= 0))
    except OverflowError:
        return False


def _counters(samples: tuple[EngineCounter, ...]) -> dict[str, int]:
    if not isinstance(samples, tuple):
        raise ValueError("Counters must be an immutable tuple.")
    result: dict[str, int] = {}
    for sample in samples:
        if (not isinstance(sample, EngineCounter)
                or not isinstance(sample.engine_id, str) or not sample.engine_id
                or not sample.engine_id.isprintable() or sample.engine_id in result
                or type(sample.value) is not int or sample.value < 0):
            raise ValueError("Invalid or duplicate engine counter.")
        result[sample.engine_id] = sample.value
    return result


@dataclass(frozen=True)
class EngineCounter:
    """单引擎某一类累计量；不同单位必须分别调用计算入口。

    engine_id 是非空可打印字符串，同一次采样内唯一；不能用数组位置替代
    来源身份。value 是非负整数，拒绝 bool；保留整数精度，不预先转 float。
    结构构造不校验，counter_rate 在入口统一验证整批数据。
    """

    engine_id: str
    value: int


@dataclass(frozen=True)
class LatencyInterval:
    """相邻可比较采样之间，某一延迟指标的观测增量。

    started_at/ended_at 为有限非负单调秒数，ended_at > started_at。
    total_seconds 为有限非负观测总时长；observations 为非负整数，拒绝 bool。
    observations=0 时 total_seconds 必须为0；有观测的合法零时长均值仍是0。
    时间戳是采样区间边界，不表示各个请求的到达时刻。

    该对象仅能表示已核实、同单位、无故障/重置的完整差分区间；不能将累计
    _sum/_count 直接塞入。不同延迟指标有各自的计数，不能共用其他指标分母。
    结构构造不校验，weighted_latency 在入口校验整批数据。
    """

    started_at: float
    ended_at: float
    total_seconds: float
    observations: int


def counter_rate(
    previous: tuple[EngineCounter, ...] | None,
    current: tuple[EngineCounter, ...],
    *,
    elapsed: float,
    continuous: bool = True,
) -> float | None:
    """返回同单位累计量的每秒速率；不修改参数或保留基线。

    校验整批输入后，首次、空引擎集合、continuous=False、引擎身份集合变化，
    或任一引擎计数回退均返回None。相同引擎集合允许顺序改变；必须逐引擎
    比较，再汇总增量，不能让另一引擎的增长掩盖某引擎重置。有效区间无增量
    返回0.0；除数使用实际 elapsed 秒数，不使用配置采样周期。

    continuous 由状态层依据前次尝试、字段有效性及可靠重启标记提供；本函数
    不能从仍增长的计数判断是否发生隐蔽重启，不能猜测回退后的剩余增量。

    Raises:
        ValueError: elapsed 不是有限正实数（拒bool），continuous不是bool，
            容器不是tuple、元素类型/身份/计数非法，或引擎身份重复。
            previous=None 合法；输入校验也适用于不可比较的区间。
            计算结果无法表示为有限float时同样抛ValueError，不返回Infinity。
    """
    if not _finite_number(elapsed, positive=True) or type(continuous) is not bool:
        raise ValueError("Invalid rate interval.")
    before = None if previous is None else _counters(previous)
    after = _counters(current)
    if (not continuous or not before or not after or before.keys() != after.keys()
            or any(after[key] < before[key] for key in after)):
        return None
    delta = sum(after[key] - before[key] for key in after)
    try:
        # Dividing exact integers first also handles a huge numerator with a
        # large elapsed value whose final quotient remains representable.
        rate = float(Fraction(delta) / Fraction(elapsed))
    except OverflowError as exc:
        raise ValueError("Rate exceeds the finite display range.") from exc
    if not math.isfinite(rate):
        raise ValueError("Rate exceeds the finite display range.")
    return rate


def weighted_latency(
    intervals: tuple[LatencyInterval, ...],
    *,
    now: float,
    window_seconds: float = 60.0,
) -> float | None:
    """返回窗口内有效区间的总观测时长 / 总观测数，单位为秒。

    输入按started_at递增、互不重叠，相邻端点相同合法；允许故障造成的空档。
    仅纳入完整位于[now-window_seconds, now]的区间，含两端边界。跨左边界
    或尚未完成的区间整体排除，不能按时间占比臆造请求在桶内的分布。
    调用者在声明的有界窗口内维护区间；本函数不裁剪或修改调用者的数据。

    各有效区间先合计total_seconds和observations再相除，不能对每秒均值作
    等权平均。无区间或观测数为0返回None；有观测且总时长为0返回0.0。
    初次累计样本没有对应增量区间，不得将服务启动以来数据冒充近期观测。
    使用稳定求值避免中间总和溢出掩盖可表示的有限均值；不返回NaN/Infinity。

    Raises:
        ValueError: now不是有限非负实数、window_seconds不是有限正实数
            （均拒bool），输入非tuple或含非法/重叠/乱序区间。
            已过期或尚未完成的区间也必须符合结构和数值约束。
    """
    seconds, observations = _latency_totals(intervals, now=now, window_seconds=window_seconds)
    return float(seconds / observations) if observations else None


def _latency_totals(
    intervals: tuple[LatencyInterval, ...],
    *,
    now: float,
    window_seconds: float,
) -> tuple[Fraction, int]:
    """Validate one timeline and retain its exact in-window sum and count.

    Shared by the public single-timeline mean and the multi-engine accumulator.
    No float mean is formed here: combining already rounded engine means could
    erase a representable service-wide result near the subnormal boundary.
    """
    if (not _finite_number(now) or not _finite_number(window_seconds, positive=True)
            or not isinstance(intervals, tuple)):
        raise ValueError("Invalid latency window.")
    previous_end = None
    seconds = Fraction(0)
    observations = 0
    oldest = now - window_seconds
    for interval in intervals:
        if (not isinstance(interval, LatencyInterval)
                or not _finite_number(interval.started_at)
                or not _finite_number(interval.ended_at)
                or interval.ended_at <= interval.started_at
                or not _finite_number(interval.total_seconds)
                or type(interval.observations) is not int or interval.observations < 0
                or interval.observations == 0 and interval.total_seconds != 0
                or previous_end is not None and interval.started_at < previous_end):
            raise ValueError("Invalid, overlapping or unordered latency interval.")
        previous_end = interval.ended_at
        if oldest <= interval.started_at and interval.ended_at <= now:
            seconds += Fraction(interval.total_seconds)
            observations += interval.observations
    # Exact rational summation avoids intermediate float overflow, and retains
    # exact count weights even beyond the range representable as float.
    return seconds, observations
