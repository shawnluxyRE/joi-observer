"""vLLM 的不可变语义观测、静态展示声明与状态层计算接口。

采集器仅产生当前观测，MonitorState 独占 VllmAccumulator；展示层只读 Metric。
构造与静态字段声明不访问任何外部资源；窗口仅由状态提交推进。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from fractions import Fraction
import math
from types import MappingProxyType

from joi_observer.config import ModelConfig, ModelType
from joi_observer.data.models import CollectionResult, Metric, ObjectKey, ObjectSpec
from joi_observer.data.vllm_window import EngineCounter, LatencyInterval, _latency_totals, counter_rate
from joi_observer.error_log import Failure


@dataclass(frozen=True)
class CounterSample:
    """精确非负整数累计量；created_at 为可选的指标创建时间。

    创建时间仅作连续性提示，不代表引擎启动时刻。缺失正常；从有到无、
    从无到有或值变化时保守打断该指标基线。拒bool及非有限/负创建时间。
    """

    value: int
    created_at: float | None = None


@dataclass(frozen=True)
class LatencySample:
    """同一引擎、同一延迟指标的累计秒数/累计观测数原子组。

    total_seconds有限且非负，observations为非负整数（拒bool）；零计数必须
    配零总时长。created_at语义同CounterSample，不能复用其他直方图的分母。
    """

    total_seconds: float
    observations: int
    created_at: float | None = None


@dataclass(frozen=True)
class EngineSample:
    """单引擎观测的公共字段；engine_id不是GPU/TP编号。

    running/waiting是非负整数内部序列数；queue携带自己的sum/count。
    None仅表示本次未取得适用字段，实际失败由结果failure另行标识。
    基类只用于复用公共结构，提交观测须使用匹配模型类型的具体子类。
    payload内不保存HTTP正文、任意标签、错误原因、请求内容或动态配置。
    """

    engine_id: str
    running: int | None = None
    waiting: int | None = None
    queue: LatencySample | None = None


@dataclass(frozen=True)
class ChatEngineSample(EngineSample):
    """生成模型的单引擎观测，只声明Chat适用指标。

    KV比例范围[0,1]；输入/生成Token独立累计，TTFT使用自身sum/count。
    不提供pooling完成量或完成延迟字段，不以None伪装不存在的指标。
    """

    kv_cache_fraction: float | None = None
    prompt_tokens: CounterSample | None = None
    generation_tokens: CounterSample | None = None
    ttft: LatencySample | None = None


@dataclass(frozen=True)
class PoolingEngineSample(EngineSample):
    """Embedding/Reranker共用的单引擎观测，只声明pooling适用指标。

    completed_sequences仅为正常STOP结束计数，不含abort/error/length。
    latency和继承的queue各用自身sum/count，可能包含来源记录的非成功终止。
    不提供生成Token、TTFT或KV字段；不按输入批大小或候选数换算完成量。
    """

    completed_sequences: CounterSample | None = None
    latency: LatencySample | None = None


@dataclass(frozen=True)
class VllmObservation:
    """一次已核对版本与身份的采样，不含差分、窗口或界面状态。

    model_name为服务身份而非展示名；engines为非空、唯一engine_id的冻结tuple。
    Chat仅包含ChatEngineSample；Embedding/Reranker仅包含PoolingEngineSample。
    消费边界拒绝裸EngineSample、混合子类或与model_type不匹配的子类。
    process_started_at为可选导出进程启动秒数，不证明单个引擎生命周期。
    该标记缺失本身不报错；变化或可用性变化使全部计数组重新建立基线。
    """

    model_type: ModelType
    model_name: str
    engines: tuple[ChatEngineSample, ...] | tuple[PoolingEngineSample, ...]
    process_started_at: float | None = None


@dataclass(frozen=True)
class VllmCollectionResult(CollectionResult):
    """模型语义结果；签名为(key, observation=None, *, failure=None)。

    仅携带原始不可变观测，不提供metrics字段；展示指标由状态层计算。
    成功必须有完整观测，局部失败保留有效观测字段；整对象失败可无观测。
    消费边界校验其与VllmSpec的身份/类型，构造不做业务计算或I/O。
    """

    observation: VllmObservation | None = None


@dataclass(frozen=True)
class VllmSpec(ObjectSpec):
    """携带模型类型和期望身份的ObjectSpec；仅由State的vLLM分支消费。

    key使用vllm命名空间与配置id；metrics为相应类型固定模板，所有初值为None。
    不能通过Metric排列或字符串字段名猜测模型类型。默认仅满足数据类声明顺序，
    生产声明由make_vllm_spec从已验证配置创建。
    """

    model_type: ModelType = ModelType.CHAT
    served_model_name: str = ""


_CHAT = (
    Metric("running", None, "seq"), Metric("waiting", None, "seq"),
    Metric("total", None, "seq"), Metric("decode_rate", None, "tok/s"),
    Metric("prefill_rate", None, "tok/s"), Metric("rate", None, "seq/s", False),
    Metric("ttft_seconds", None, "s"), Metric("queue_seconds", None, "s"),
    Metric("latency_seconds", None, "s", False), Metric("kv_cache_percent", None, "%"),
)
_POOLING = (
    Metric("running", None, "seq"), Metric("waiting", None, "seq"),
    Metric("total", None, "seq"), Metric("decode_rate", None, "tok/s", False),
    Metric("prefill_rate", None, "tok/s", False), Metric("rate", None, "seq/s"),
    Metric("ttft_seconds", None, "s", False), Metric("queue_seconds", None, "s"),
    Metric("latency_seconds", None, "s"), Metric("kv_cache_percent", None, "%", False),
)
VLLM_TEMPLATES = MappingProxyType({
    ModelType.CHAT: _CHAT,
    ModelType.EMBEDDING: _POOLING,
    ModelType.RERANKER: _POOLING,
})


def make_vllm_spec(config: ModelConfig) -> VllmSpec:
    """从已验证配置构造静态声明；无IO、采集、聚合或窗口计算。"""
    return VllmSpec(ObjectKey("vllm", config.id), VLLM_TEMPLATES[config.type],
                    config.type, config.served_model_name or config.name)


def _number(value: object, *, positive: bool = False) -> bool:
    try:
        return (type(value) in (int, float) and math.isfinite(value)
                and (value > 0 if positive else value >= 0))
    except OverflowError:
        return False


def _identity(value: object) -> bool:
    return isinstance(value, str) and bool(value) and value.isprintable()


def _integer(value: object) -> bool:
    return type(value) is int and value >= 0


def _sample(value: object, cls: type) -> bool:
    if type(value) is not cls or value.created_at is not None and not _number(value.created_at):
        return False
    if cls is CounterSample:
        return _integer(value.value)
    return (_number(value.total_seconds) and _integer(value.observations)
            and (value.observations != 0 or value.total_seconds == 0))


@dataclass(frozen=True)
class _Baseline:
    sampled_at: float
    process_started_at: float | None
    samples: dict[str, CounterSample | LatencySample]


def _comparable(previous: _Baseline | None, current: _Baseline) -> bool:
    return (previous is not None
            and previous.process_started_at == current.process_started_at
            and previous.samples.keys() == current.samples.keys()
            and all(previous.samples[key].created_at == sample.created_at
                    for key, sample in current.samples.items()))


# Each batch is one sampling interval, containing independent finite engine
# sums. Keeping shards avoids overflowing a service-wide sum before weighting.
_LatencyBatch = tuple[tuple[str, LatencyInterval], ...]


def _window_value(batches: deque[_LatencyBatch], *, now: float, seconds: float) -> float | None:
    engines: dict[str, list[LatencyInterval]] = {}
    for batch in batches:
        for key, interval in batch:
            engines.setdefault(key, []).append(interval)
    total_seconds = Fraction(0)
    count = 0
    for intervals in engines.values():
        engine_seconds, observations = _latency_totals(
            tuple(intervals), now=now, window_seconds=seconds)
        total_seconds += engine_seconds
        count += observations
    # Preserve original interval sums through global weighting. Rounding a
    # per-engine mean first can underflow even when the global mean is nonzero.
    return float(total_seconds / count) if count else None


class VllmAccumulator:
    """由MonitorState独占的每模型基线和延迟窗口，不含IO或日志。

    history_seconds为有限正秒数；max_intervals正整数，默认602且每指标独立限制。
    声明与输入验证在实现边界完成，构造不读取时间或外部资源。
    """

    def __init__(self, spec: VllmSpec, *, history_seconds: float = 60.0,
                 max_intervals: int = 602) -> None:
        if (not isinstance(spec, VllmSpec) or not isinstance(spec.key, ObjectKey)
                or spec.key.collector != "vllm" or not _identity(spec.key.object_id)
                or len(spec.key.object_id) > 128 or "://" in spec.key.object_id
                or not isinstance(spec.model_type, ModelType)
                or not _identity(spec.served_model_name)
                or spec.metrics != VLLM_TEMPLATES[spec.model_type]
                or not _number(history_seconds, positive=True)
                or type(max_intervals) is not int or max_intervals <= 0):
            raise ValueError("Invalid vLLM accumulator specification.")
        self.spec = spec
        self.history_seconds = history_seconds
        self.max_intervals = max_intervals
        self._sampled_at: float | None = None
        self._values = {metric.name: metric.value for metric in spec.metrics}
        self._baselines: dict[str, _Baseline] = {}
        if spec.model_type is ModelType.CHAT:
            self._counter_groups = {"generation_tokens": "decode_rate", "prompt_tokens": "prefill_rate"}
            self._latency_groups = {"ttft": "ttft_seconds", "queue": "queue_seconds"}
        else:
            self._counter_groups = {"completed_sequences": "rate"}
            self._latency_groups = {"latency": "latency_seconds", "queue": "queue_seconds"}
        self._windows: dict[str, deque[_LatencyBatch]] = {
            metric: deque(maxlen=max_intervals) for metric in self._latency_groups.values()
        }

    def _validate(self, result: CollectionResult, sampled_at: float) -> VllmObservation | None:
        """Reject the complete input before deriving or committing any state."""
        if (not _number(sampled_at)
                or self._sampled_at is not None and sampled_at <= self._sampled_at
                or type(result) not in (CollectionResult, VllmCollectionResult)
                or result.key != self.spec.key
                or result.failure is not None and not isinstance(result.failure, Failure)):
            raise ValueError("Invalid vLLM result or sample time.")
        observation = result.observation if type(result) is VllmCollectionResult else None
        if observation is None:
            if result.failure is None:
                raise ValueError("A successful vLLM result requires an observation.")
            return None
        if (not isinstance(observation, VllmObservation)
                or observation.model_type is not self.spec.model_type
                or observation.model_name != self.spec.served_model_name
                or not isinstance(observation.engines, tuple) or not observation.engines
                or observation.process_started_at is not None and not _number(observation.process_started_at)):
            raise ValueError("Invalid vLLM observation identity or structure.")
        expected = ChatEngineSample if self.spec.model_type is ModelType.CHAT else PoolingEngineSample
        seen: set[str] = set()
        for engine in observation.engines:
            if (type(engine) is not expected or not _identity(engine.engine_id)
                    or engine.engine_id in seen):
                raise ValueError("Invalid or duplicate vLLM engine.")
            seen.add(engine.engine_id)
            fields = [(engine.running, _integer), (engine.waiting, _integer)]
            fields.extend((getattr(engine, group), lambda value: _sample(value, CounterSample))
                          for group in self._counter_groups)
            fields.extend((getattr(engine, group), lambda value: _sample(value, LatencySample))
                          for group in self._latency_groups)
            if expected is ChatEngineSample:
                fields.append((engine.kv_cache_fraction, lambda value: _number(value) and value <= 1))
            if any((value is None and result.failure is None)
                   or (value is not None and not validate(value)) for value, validate in fields):
                raise ValueError("Missing or invalid vLLM engine field.")
        return observation

    def _project(self, values: dict, windows: dict, now: float) -> tuple[Metric, ...]:
        values = dict(values)
        for metric, intervals in windows.items():
            values[metric] = _window_value(intervals, now=now, seconds=self.history_seconds)
        return tuple(Metric(metric.name, values[metric.name], metric.unit, metric.applicable)
                     for metric in self.spec.metrics)

    def accept(self, result: CollectionResult, *, sampled_at: float) -> tuple[Metric, ...]:
        """原子消费一次结果，返回完整展示字段；时间须有限非负且严格递增。

        VllmCollectionResult的key及observation.model_type/model_name必须匹配spec，观测的
        元素/单位/所有数值必须合法。成功必须有观测；整对象失败允许无观测；局部失败
        仅把未取得字段置None，其余字段仍可更新。验证错误抛ValueError且不改状态。
        无failure时，各引擎必须提供相应类型所有适用字段；不接受健康但缺必需值。
        引擎子类必须统一并与model_type匹配；有failure也不能接受裸基类、混合
        子类或错误的模型载荷。原子拒绝后，不改之前的值、基线或窗口。
        也接受Monitor生成的无载荷公共CollectionResult整对象失败；拒绝公共基类
        成功、MetricCollectionResult、重复/空engine_id以及不匹配身份。

        RUNNING/WAITING按不同engine相加，Total仅在同次二者都有效时相加；
        同快照某指标缺少引擎分片/字段时不能把子集当完整服务值；完整引擎集合
        变化则按拓扑变化处理。KV为各引擎比例算术平均*100。
        计数先逐engine比较、再汇总，调用counter_rate；直方图分别差分sum/count。
        首次、拓扑/创建时间/进程标记变化、任何引擎回退使相应组返回None并重建
        基线；已验证的旧延迟区间保留至自然过期，不视为采集故障。
        count不变却sum增加为不可比较区间，重新建立该组基线，不产生虚假均值。
        原始数值通过校验后，若单组速率无法表示为有限float，仅把该速率设None，
        当前合法计数作为下次基线；不能让counter_rate的溢出ValueError逸出到Monitor。
        其余字段仍更新，不伪造0或采集错误；输入校验错误仍按上述原子拒绝处理。

        全失败保留最后显示值并打断全部基线；局部失败保留失败字段最后值、打断
        相应组，其他独立字段可继续差分。不以新RUNNING配旧WAITING生成新Total。
        可验证的旧延迟区间仍按时间过期，故障空档不补0，恢复首点只建立基线。
        此处不写HistoryPoint；State按任何failure保守记录整点gap。
        """
        observation = self._validate(result, sampled_at)
        values = dict(self._values)
        baselines = dict(self._baselines)
        windows = {metric: deque(batches, maxlen=self.max_intervals)
                   for metric, batches in self._windows.items()}
        if observation is None:
            baselines.clear()
        else:
            engines = observation.engines
            for name in ("running", "waiting"):
                if all(getattr(engine, name) is not None for engine in engines):
                    values[name] = sum(getattr(engine, name) for engine in engines)
            if all(engine.running is not None and engine.waiting is not None for engine in engines):
                values["total"] = values["running"] + values["waiting"]
            if self.spec.model_type is ModelType.CHAT:
                fractions = [engine.kv_cache_fraction for engine in engines]
                if all(fraction is not None for fraction in fractions):
                    values["kv_cache_percent"] = math.fsum(fractions) / len(fractions) * 100
            for group, metric in (self._counter_groups | self._latency_groups).items():
                samples = {engine.engine_id: getattr(engine, group) for engine in engines}
                if any(sample is None for sample in samples.values()):
                    baselines.pop(group, None)
                    continue
                current = _Baseline(sampled_at, observation.process_started_at, samples)
                previous = baselines.get(group)
                comparable = _comparable(previous, current)
                if group in self._counter_groups:
                    # A validated counter may be larger than the display's float
                    # range. Only its derived rate becomes unknown in that case.
                    try:
                        values[metric] = counter_rate(
                            None if previous is None else tuple(EngineCounter(key, value.value)
                                                                for key, value in previous.samples.items()),
                            tuple(EngineCounter(key, value.value) for key, value in samples.items()),
                            elapsed=sampled_at - previous.sampled_at if previous is not None else 1.0,
                            continuous=comparable,
                        )
                    except ValueError:
                        values[metric] = None
                elif comparable:
                    deltas = []
                    for key, sample in samples.items():
                        old = previous.samples[key]
                        total = sample.total_seconds - old.total_seconds
                        count = sample.observations - old.observations
                        if total < 0 or count < 0 or count == 0 and total != 0:
                            break
                        deltas.append((key, LatencyInterval(previous.sampled_at, sampled_at, total, count)))
                    else:
                        windows[metric].append(tuple(deltas))
                baselines[group] = current
        for batches in windows.values():
            while batches and batches[0][0][1].started_at < sampled_at - self.history_seconds:
                batches.popleft()
        projected = self._project(values, windows, sampled_at)
        self._values, self._baselines, self._windows = values, baselines, windows
        self._sampled_at = sampled_at
        return projected

    def metrics(self, *, now: float) -> tuple[Metric, ...]:
        """只读投影最新字段与当前窗口均值，now有限非负且不早于最后提交。

        复用weighted_latency的精确汇总内核计算完整落窗区间；无有效观测为None。
        调用不改基线、区间、revision，不采集。返回新冻结tuple，旧返回值不受影响。
        初次返回模板；最后瞬时值和速率可保留，stale及历史由MonitorState管理。
        """
        if not _number(now) or self._sampled_at is not None and now < self._sampled_at:
            raise ValueError("Projection time must be finite and not precede the latest sample.")
        return self._project(self._values, self._windows, now)
