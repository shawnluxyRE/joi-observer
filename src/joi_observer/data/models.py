"""采集、调度与展示的不可变值对象。

所有 tuple 元素及标量均须不可变。数值为有限数，0 为有效值，None 表示
尚无有效观测或已知不支持；不适用由 applicable=False 表示，不能用 0 代替。
这些声明不执行采集、聚合、输入校验或持久化；校验在 R4 的模块边界实现。
"""

from __future__ import annotations

from dataclasses import dataclass

from joi_observer.error_log import Failure


@dataclass(frozen=True)
class ObjectKey:
    """稳定的监控身份；collector 为来源命名空间，object_id 为对象标识。

    约定来源为 host/gpu/storage/docker/vllm；同名模型按配置 id 区分。
    字符串非空，不得含凭据、控制字符或原始 URL。collector 最多32个ASCII字符，
    满足[a-z][a-z0-9_.-]*；object_id 最多128个Unicode字符；大小写敏感，联合唯一。
    """

    collector: str
    object_id: str


@dataclass(frozen=True)
class Metric:
    """命名指标。name 在同一对象中唯一；value 是标量或 None。

    unit 是显示单位（如 '%'、'GiB'），值与单位必须保持原语义。applicable=False
    时 value 必须为 None，展示 N/A。非适用/未知字段本身不代表失败。
    name/value/unit 不得夹带异常、请求内容、凭据或 UI 诊断文字。
    """

    name: str
    value: float | int | str | None
    unit: str = ""
    applicable: bool = True


@dataclass(frozen=True)
class ObjectSpec:
    """状态对象声明，metrics 为首屏字段模板（值均为 None）。

    配置顺序决定静态对象顺序，GPU 使用发现顺序。模板保证首次采集前也有
    固定字段与状态槽；真实 GPU 数量尚未知时由展示层显示单行空态。
    """

    key: ObjectKey
    metrics: tuple[Metric, ...] = ()


@dataclass(frozen=True)
class CollectionResult:
    """单对象一次采集结果，返回后不得修改。

    成功时 failure=None，metrics 必须覆盖声明的字段；已知不支持/无观测
    显式使用 None。失败可携带本次成功取得的字段；未返回的字段保留最后值，
    对象标记 STALE。整对象失败返回空 metrics 和 Failure。字段级细分由后续
    采集器契约补充，不得把成功字段置零。Failure 只交给 Monitor/日志，不能
    进入只读快照。一次结果只属于一个 key，不借单对象失败覆盖其他对象。
    """

    key: ObjectKey
    metrics: tuple[Metric, ...] = ()
    failure: Failure | None = None


@dataclass(frozen=True)
class HistoryPoint:
    """单调时刻与历史观测；metrics=None 是失败缺口，不能画成零或保持值。

    部分失败也保留缺口，细粒度曲线语义由 REQ-004 扩展。这里不计算吞吐
    或窗口均值，也不将历史点写到文件。
    """

    sampled_at: float
    metrics: tuple[Metric, ...] | None


@dataclass(frozen=True)
class ObjectSnapshot:
    """仅用于展示的对象视图，不含任何错误原因。

    sampled_at 是最近一次尝试完成的单调时间，首次为 None；仅供内部有效性
    与窗口计算，UI 不显示。stale 仅由采集失败置位，成功自动清除。最后值可
    保留但历史中的故障必须为缺口；所有容器生命周期包括 Exited 都可为成功值。
    """

    key: ObjectKey
    metrics: tuple[Metric, ...] = ()
    stale: bool = False
    sampled_at: float | None = None
    history: tuple[HistoryPoint, ...] = ()


@dataclass(frozen=True)
class StateSnapshot:
    """一次原子只读视图，objects 按注册顺序排列；revision 为非负更新序号。

    更新后旧快照仍不变；初始 revision=0，每次有效 accept/register 增加一。
    UI 选择、主题、时钟刷新和 snapshot 调用不增加 revision、不触发采集。
    """

    objects: tuple[ObjectSnapshot, ...]
    revision: int = 0

