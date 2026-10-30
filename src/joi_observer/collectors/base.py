"""无 UI 依赖的异步单对象采集端口。"""

from __future__ import annotations

from typing import Protocol

from joi_observer.data.models import CollectionResult, ObjectSpec


class Collector(Protocol):
    """每个实例对应一个稳定监控对象；spec 在该实例生命周期内不变。

    Monitor 对不同实例独立调度，同一实例同时最多一次 collect。GPU 发现和批量
    读取可以在适配器层复用，但不能使单卡失败覆盖整个批次或重入同一物理查询。
    不能依赖 TUI、直接更新状态、打印、记日志或修改被监控对象。
    """

    spec: ObjectSpec

    async def collect(self) -> CollectionResult:
        """返回 spec.key 的当前结果，不在此计算 UI 数据、休眠到下个周期或重试。

        预期错误转为受控 Failure，已知不支持字段用 None，未知异常由 Monitor
        归一为 unexpected/collector.unexpected。必须让出事件循环，遵守取消并在250ms内
        清理自身任务；网络/子进程必须有底层超时，不可用不可取消线程包裹无限阻塞IO。
        取消是正常关闭，不能转为采集错误。禁止发送推理请求或进行任何服务管理。
        """
        ...

    async def close(self) -> None:
        """幂等释放自身资源，在250ms预算内完成；不得打印或在关闭时补打采集日志。"""
        ...

