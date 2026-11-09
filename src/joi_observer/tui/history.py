"""只读历史的时间分桶与会话显示尺度；不采集或修改监控数据。

分桶是纯函数；迟降计时由应用持有的独立展示会话推进。渲染函数只消费
冻结的尺度值，不通过全局状态、MonitorState 或文件保存显示偏好。
"""

from dataclasses import dataclass
import math

from joi_observer.config import ModelConfig, ModelType
from joi_observer.data.models import HistoryPoint, StateSnapshot


def bucket_history(
    history: tuple[HistoryPoint, ...],
    field: str,
    *,
    now: float,
    columns: int,
) -> tuple[float | int | None, ...]:
    """返回从左到右恰好 columns 个时间桶，无 I/O 或输入修改。

    now 必须为有限非负 int/float，拒绝 bool；columns 必须为不小于2的
    真 int，非法参数抛 ValueError。sampled_at 与 now 同属单调时钟域。
    历史身份和指标合法性由数据层保证；本接口不重新计算吞吐或单位。

    先保留真实闭窗口 [now-60, now]，不把未来或过期点夹入窗口。令
    Δ=60/(columns-1)、B=floor(now/Δ)、b=floor(sampled_at/Δ)，绝对时间
    桶为 [b*Δ,(b+1)*Δ)，相对列为 columns-1-(B-b)。同一 B 内位置不变，
    B 前进一格时旧桶统一左移。当前未闭合桶立即接收真实新点。浮点边界
    处理不得丢弃已通过窗口过滤的端点，也不得容纳相邻的窗口外点。

    同桶有效主字段取最大值；出现 metrics=None、主字段缺失、value=None
    或 applicable=False 时整个桶为 None，其他有效值也不能掩盖缺口。
    无点桶为 None，真实全0桶为0；不插值、补零、延长或复制旧观测。
    顺序不影响结果。宽度改变才重新分桶，不按最早观测伸缩横轴。
    """
    _validate_clock_width(now, columns)
    buckets: list[float | int | None] = [None] * columns
    gaps: set[int] = set()
    current_bucket = _time_bucket(now, columns)
    for point in history:
        if not now - 60 <= point.sampled_at <= now:
            continue
        # Closed-window endpoints can differ by the final binary rounding of
        # now - 60. Only after that exact window check may the index be bounded.
        index = max(0, min(columns - 1,
                           columns - 1 - (current_bucket - _time_bucket(point.sampled_at, columns))))
        metric = next((metric for metric in point.metrics or () if metric.name == field), None)
        if metric is None or metric.value is None or not metric.applicable:
            gaps.add(index)
            buckets[index] = None
        elif index not in gaps:
            current = buckets[index]
            buckets[index] = metric.value if current is None else max(current, metric.value)
    return tuple(buckets)


def scan_history(
    history: tuple[HistoryPoint, ...],
    field: str,
    *,
    now: float,
) -> tuple[float | int | None, ...]:
    """Return 60 fixed one-second slots indexed by the monotonic second modulo 60.

    The current second and previous 59 seconds occupy distinct slots. Points
    before floor(now)-59 or after now are excluded. Advancing to a new second
    expires that slot's previous revolution, even when the new second has no
    samples. A partial current second accepts observations immediately.

    Values in the same second use their maximum. A missing or inapplicable
    primary metric makes that whole second a gap. Zero remains an observed
    value. All calculations use the input monotonic timestamps, with no I/O
    or mutation and no dependence on the terminal's width.
    """
    _validate_clock_width(now, 60)
    earliest = math.floor(now) - 59
    buckets: list[float | int | None] = [None] * 60
    gaps: set[int] = set()
    for point in history:
        if not earliest <= point.sampled_at <= now:
            continue
        index = math.floor(point.sampled_at) % 60
        metric = next((metric for metric in point.metrics or () if metric.name == field), None)
        if metric is None or metric.value is None or not metric.applicable:
            gaps.add(index)
            buckets[index] = None
        elif index not in gaps:
            current = buckets[index]
            buckets[index] = metric.value if current is None else max(current, metric.value)
    return tuple(buckets)


def _validate_clock_width(now: float, columns: int) -> None:
    if (isinstance(now, bool) or not isinstance(now, (int, float)) or now < 0
            or (isinstance(now, float) and not math.isfinite(now))):
        raise ValueError("now must be a finite nonnegative number")
    if type(columns) is not int or columns < 2:
        raise ValueError("columns must be an integer of at least two")


def _time_bucket(at: float, columns: int) -> int:
    """Exact floor(at / (60 / (columns - 1))) without floating-grid drift."""
    numerator, denominator = at.as_integer_ratio()
    return numerator * (columns - 1) // (denominator * 60)


def _scale_upper(peak: float | int) -> int:
    """Smallest integer 1/2/5 decade covering the actual binary input value."""
    decade = 1
    while True:
        for multiplier in (1, 2, 5):
            upper = multiplier * decade
            if peak <= upper:
                return upper
        decade *= 10


@dataclass(frozen=True)
class HistoryScale:
    """单模型、单主指标的不可变显示上限，不是监控指标。

    upper 是正整数，取 {1,2,5}×10^n（n>=0），最小1；使用任意精度整数
    避免很大但有限的历史值在求上限时溢出。这里只声明数据载体，合法
    输出由展示会话保证，不在构造时执行验证、分桶或计时业务。
    """

    model_id: str
    field: str
    upper: int


class HistoryScaleTracker:
    """按配置模型推进显示尺度；由应用拥有，与监控状态和选择解耦。

    models 为已验证、id 唯一且顺序固定的不可变配置元组；构造只保存
    依赖和空会话，不访问终端、采集器、时钟、文件或外部服务。
    """

    def __init__(self, models: tuple[ModelConfig, ...]) -> None:
        self._models = models
        self._scales: dict[tuple[str, str], HistoryScale] = {}
        self._lower_since: dict[tuple[str, str], float] = {}
        self._last_now: float | None = None

    def update(
        self,
        snapshot: StateSnapshot,
        *,
        now: float,
        columns: int,
    ) -> tuple[HistoryScale, ...]:
        """按全部配置模型顺序返回独立的冻结尺度，且原子推进会话。

        只读取 collector='vllm' 且 object_id 匹配配置 id 的历史；Chat
        使用 decode_rate，Embedding/Reranker 使用 rate。未配置对象和
        其他 collector 不参与。只按 scan_history 的同一窗口/分桶/
        缺口规则求可绘制峰值，不用最新 metrics 或对象 stale 猜测历史。

        目标上限是不小于有效桶峰值的最小1/2/5十进制档，最小1；全0
        是有效观测，无有效桶不是0。首次有效观测即采用目标档。未获得
        有效观测的模型返回上限1；之后无有效桶保持已有上限并清空迟降
        计时。未知桶内被遮蔽的有效峰值不参与上限计算。

        目标高于当前档立即升档；等于当前档保持；两者均清空迟降计时。
        目标连续低于当前档满5单调秒后降到届时目标档。低档之间变化不
        重启计时；没有有效桶也清空计时。重复绘制不重置起点，同一 now
        可重复调用；同一输入返回相等值，已返回的对象不能随后被修改。

        所有模型都推进，不依赖当前选择；尺度按模型id与指标隔离。
        显示宽度不影响固定秒桶、尺度或迟降计时。不会修改
        snapshot、模型配置或其历史，不执行 I/O，也不创建异步任务。

        now/columns 的合法性与 bucket_history 相同。now 小于上次成功
        update 的时间时抛 ValueError；任一校验异常均不得改变任何模型
        的上限、计时或最后成功时间，随后合法调用与未发生异常时一致。
        """
        _validate_clock_width(now, columns)
        if self._last_now is not None and now < self._last_now:
            raise ValueError("History scale time cannot move backwards")

        # Work on copies so a validation/calculation failure in any configured
        # model cannot partially advance another model or its pending timer.
        scales = dict(self._scales)
        lower_since = dict(self._lower_since)
        objects = {obj.key.object_id: obj for obj in snapshot.objects if obj.key.collector == "vllm"}
        result = []
        for model in self._models:
            field = "decode_rate" if model.type == ModelType.CHAT else "rate"
            key = (model.id, field)
            obj = objects.get(model.id)
            values = tuple(value for value in scan_history(
                obj.history if obj else (), field, now=now
            ) if value is not None)
            current = scales.get(key)
            if not values:
                lower_since.pop(key, None)
                result.append(current if current is not None else HistoryScale(model.id, field, 1))
                continue
            target = _scale_upper(max(values))
            if current is None or target >= current.upper:
                current = HistoryScale(model.id, field, target)
                lower_since.pop(key, None)
            else:
                since = lower_since.setdefault(key, now)
                if now - since >= 5:
                    current = HistoryScale(model.id, field, target)
                    lower_since.pop(key, None)
            scales[key] = current
            result.append(current)

        self._scales = scales
        self._lower_since = lower_since
        self._last_now = now
        return tuple(result)
