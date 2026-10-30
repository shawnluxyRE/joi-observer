"""REQ-002 本机硬件采集、发现与无 IO 组装入口。

所有构造无 IO；采集入口读取 HardwareIO 原始材料并返回 CollectionResult，
不写 MonitorState、不记日志、不打印。指标目录及失败分类见 hardware.md。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from joi_observer.collectors._local_io import LocalProcessIO

from joi_observer.collectors import _hardware_parsing as parsing
from joi_observer.collectors.base import Collector, DiscoveryResult
from joi_observer.config import AppConfig
from joi_observer.data.models import CollectionResult, Metric, ObjectKey, ObjectSpec


@dataclass(frozen=True)
class CommandOutput:
    """本地只读子进程结果；stdout/stderr 仅在采集层解析，不能进入快照或日志。"""

    returncode: int
    stdout: str
    stderr: str = ""


@dataclass(frozen=True)
class FileSystemStat:
    """同一挂载点的一次 statvfs 原值；不使用面向普通用户的 bavail 算使用率。

    fragment_size=f_frsize，blocks=f_blocks，free_blocks=f_bfree；均为整数。
    总量=fragment_size*blocks，已用=fragment_size*(blocks-free_blocks)。
    分母是总量，包含保留块；used/total 与百分比必须采用同一口径。
    """

    fragment_size: int
    blocks: int
    free_blocks: int


class HardwareIO(Protocol):
    """可替换的原始本地 IO，离线测试注入文本/计数，不模拟派生业务结果。

    方法必须让出事件循环、支持取消且底层有 timeout。不得建立网络连接。
    PermissionError/FileNotFoundError/TimeoutError/OSError 分别由采集器归一。
    timeout 由构造参数给出；close 幂等，取消及资源清理预算为 250ms。
    """

    async def read_text(self, path: str) -> str:
        """读取 /proc/stat、/proc/meminfo 或 /proc/self/mountinfo；上限 1 MiB。"""
        ...

    async def statvfs(self, path: str) -> FileSystemStat:
        """返回该路径原始文件系统计数，不查父路径、不换算容量或使用率。"""
        ...

    async def run(self, argv: tuple[str, ...]) -> CommandOutput:
        """执行固定参数的 nvidia-smi 查询；不使用 shell，捕获两路输出且各限 1 MiB。"""
        ...

    async def close(self) -> None:
        """幂等清理本端口所有在途本地 IO，不能打印或记录取消。"""
        ...


class LocalHardwareIO(LocalProcessIO):
    """Ubuntu 本地实现入口；仅使用标准库及已安装的 nvidia-smi。

    阻塞文件读取/statvfs 使用可终止的本地 worker 子进程；不以不可取消线程
    包装潜在阻塞文件系统。worker 只接收允许的操作与路径，输出有界结构数据。
    父进程负责超时、取消、终止及回收；nvidia-smi 同样使用异步子进程。
    禁止 shell/SSH/网络、安装驱动及任何修改硬件操作。每个采集器独占一个端口；
    discovery 与其新建子采集器各有独立端口，关闭单卡不关闭其他来源。
    """

    def __init__(self, *, timeout: float = 3.0) -> None:
        super().__init__(timeout=timeout)

    async def read_text(self, path: str) -> str:
        """遵循 HardwareIO.read_text；白名单路径与有界子进程协议。"""
        return await super().read_text(path)

    async def statvfs(self, path: str) -> FileSystemStat:
        """遵循 HardwareIO.statvfs；不接受父文件系统作为挂载验证。"""
        return await super().statvfs(path)

    async def run(self, argv: tuple[str, ...]) -> CommandOutput:
        """遵循 HardwareIO.run；timeout/取消必须回收直接创建的进程。"""
        return await super().run(argv)

    async def close(self) -> None:
        """遵循 HardwareIO.close；未启动 IO 时同样安全。"""
        await super().close()


GPU_METRICS = (
    Metric("index", None), Metric("name", None),
    Metric("utilization_percent", None, "%"),
    Metric("memory_used_bytes", None, "B"), Metric("memory_total_bytes", None, "B"),
    Metric("temperature_c", None, "°C"), Metric("power_w", None, "W"),
)


class CpuCollector:
    """host/cpu：整机 CPU，读取 /proc/stat 的 aggregate cpu 行。

    total=user+nice+system+idle+iowait+irq+softirq+steal，不重复加 guest/guest_nice；
    busy=total-idle-iowait。百分比=100*Δbusy/Δtotal，不除以核心数或墙上时间。
    首次、Δtotal=0、任一计数回退、前次失败后的首个成功样本都返回 None 且成功；
    有效区间 Δbusy=0 返回真 0。回退/失败丢弃旧基线；回退当前样本作为新基线。
    aggregate 缺失/字段非法为 parse；恢复后不得跨故障计算。CancelledError包括
    Monitor超时取消，必须先清空基线再原样重抛，不能保留取消前样本作下一轮基线。
    """

    def __init__(self, io: HardwareIO) -> None:
        self.io = io
        self.spec = ObjectSpec(ObjectKey("host", "cpu"), (Metric("cpu_percent", None, "%"),))
        self._previous: tuple[int, ...] | None = None

    async def collect(self) -> CollectionResult:
        """按类契约解析原始累计 tick；不得调用带阻塞采样间隔的 API。"""
        try:
            current = parsing.cpu_ticks(await self.io.read_text("/proc/stat"))
            previous, self._previous = self._previous, current
            percent = None
            if previous is not None and all(new >= old for new, old in zip(current, previous)):
                delta = tuple(new - old for new, old in zip(current, previous))
                total = sum(delta)
                if total:
                    percent = 100 * (total - delta[3] - delta[4]) / total
            return CollectionResult(self.spec.key, (Metric("cpu_percent", percent, "%"),))
        except asyncio.CancelledError:
            self._previous = None
            raise
        except OSError as error:
            self._previous = None
            return CollectionResult(self.spec.key, failure=parsing.io_failure(error))
        except ValueError:
            self._previous = None
            return CollectionResult(self.spec.key, failure=parsing.PARSE)
        except Exception:
            self._previous = None
            raise

    async def close(self) -> None:
        """幂等关闭独占 IO，清理 CPU 基线；取消不作为采集错误。"""
        self._previous = None
        await self.io.close()


class MemoryCollector:
    """host/ram：/proc/meminfo 的 MemTotal 与 MemAvailable，kB 按 1024 字节。

    used=total-available，percent=100*used/total；此口径包含可回收缓存影响，
    不能用 MemFree 或显存代替。total>0、0<=available<=total；缺失、重复必要键、
    非法单位或数值为 parse，不回退估算。保留精确字节，UI 只负责显示换算。
    """

    def __init__(self, io: HardwareIO) -> None:
        self.io = io
        self.spec = ObjectSpec(ObjectKey("host", "ram"), (
            Metric("ram_used_bytes", None, "B"), Metric("ram_total_bytes", None, "B"),
            Metric("ram_percent", None, "%"),
        ))

    async def collect(self) -> CollectionResult:
        """同时产出同口径的 used/total/percent；RAM 故障不影响 CPU 来源。"""
        try:
            metrics = parsing.memory_metrics(await self.io.read_text("/proc/meminfo"))
            return CollectionResult(self.spec.key, metrics)
        except OSError as error:
            return CollectionResult(self.spec.key, failure=parsing.io_failure(error))
        except ValueError:
            return CollectionResult(self.spec.key, failure=parsing.PARSE)

    async def close(self) -> None:
        """幂等关闭本对象独占 IO。"""
        await self.io.close()


class StorageCollector:
    """storage/mount-{index}，index 为有效配置中的 0..2，路径不是对象主键。

    每次读取 mountinfo→statvfs→再次读取 mountinfo。解析分隔符 ' - ' 前第5列，
    解码 \134040/\134011/\134012/\134134 转义；对配置与挂载点只做 POSIX 词法规范化
    （允许尾斜杠、重复斜杠），不解析符号链接、不选最长父前缀。目标必须精确
    匹配挂载点；普通目录/符号链接不是替代挂载点。同路径有多条挂载记录时
    保守返回unavailable，不用文本顺序猜顶层挂载。前后该路径唯一记录的
    mount ID、major:minor、root、mountpoint 必须一致；卸载/替换时丢弃容量。
    这能拒绝观察到的挂载变化，无法保证两次读取之间的极短 ABA 变化检测。
    首次未挂载为 not_found，采样中变化为 unavailable，不回退到父文件系统。
    总字节>0且0<=free_blocks<=blocks；无效计数为parse。path用配置原字符串展示。
    """

    def __init__(self, index: int, mount_point: str, io: HardwareIO) -> None:
        self.index = index
        self.mount_point = mount_point
        self.io = io
        self.spec = ObjectSpec(ObjectKey("storage", f"mount-{index}"), (
            Metric("used_bytes", None, "B"), Metric("total_bytes", None, "B"),
            Metric("used_percent", None, "%"),
        ))

    async def collect(self) -> CollectionResult:
        """只采集自己的配置挂载点；前后验证均通过才发布本轮容量。"""
        try:
            before = parsing.matching_mounts(
                await self.io.read_text("/proc/self/mountinfo"), self.mount_point,
            )
            if not before:
                return CollectionResult(self.spec.key, failure=parsing.NOT_FOUND)
            if len(before) != 1:
                return CollectionResult(self.spec.key, failure=parsing.UNAVAILABLE)
            # Use the exact lexical path whose mount identity was validated.
            # Keep the original configuration string only for presentation.
            counts = await self.io.statvfs(parsing.normalized_mount(self.mount_point))
            after = parsing.matching_mounts(
                await self.io.read_text("/proc/self/mountinfo"), self.mount_point,
            )
            if after != before:
                return CollectionResult(self.spec.key, failure=parsing.UNAVAILABLE)
            if (any(type(value) is not int for value in
                    (counts.fragment_size, counts.blocks, counts.free_blocks))
                    or counts.fragment_size <= 0 or counts.blocks <= 0
                    or not 0 <= counts.free_blocks <= counts.blocks):
                return CollectionResult(self.spec.key, failure=parsing.PARSE)
            total = counts.fragment_size * counts.blocks
            used = counts.fragment_size * (counts.blocks - counts.free_blocks)
            return CollectionResult(self.spec.key, (
                Metric("used_bytes", used, "B"), Metric("total_bytes", total, "B"),
                Metric("used_percent", 100 * used / total, "%"),
            ))
        except OSError as error:
            return CollectionResult(self.spec.key, failure=parsing.io_failure(error))
        except ValueError:
            return CollectionResult(self.spec.key, failure=parsing.PARSE)

    async def close(self) -> None:
        """幂等关闭独占 IO，不进行卸载或文件系统修改。"""
        await self.io.close()


class GpuCollector:
    """gpu/<完整 UUID> 单卡来源；每次通过 UUID 查询，不通过可变 index 定位。

    固定查询列为 index,uuid,name,utilization.gpu,memory.used,memory.total,
    temperature.gpu,power.draw，CSV/noheader/nounits，显存 MiB 转字节。
    一行且 UUID 精确匹配。合法单字段 N/A/[N/A]/[Not Supported] 返回 None，
    不置 stale；[Unknown Error]、空字段、非法/越界数值等返回 parse 部分失败，
    省略坏字段（让State保留旧值），有效字段继续提交。显存used/total是关联组：
    任一容量字段实际解析失败时两者均省略，不能混合新旧容量造成used>total；
    已知N/A仍可独立返回None。坏 identity/列数/多行
    则整卡失败。容量 used<=total 且 total>0，used>total时成对省略容量字段；
    利用率0..100，温度/功耗非负有限。命令缺失归一source.unavailable。
    power.draw 为驱动最近测得板卡功率，可能为1秒平均，不能承诺瞬时功率。
    """

    def __init__(self, uuid: str, io: HardwareIO) -> None:
        self.uuid = uuid
        self.io = io
        self.spec = ObjectSpec(ObjectKey("gpu", uuid), GPU_METRICS)

    async def collect(self) -> CollectionResult:
        """受控返回本卡字段/失败；不查询所有卡或触发发现、重排、模型映射。"""
        try:
            output = await self.io.run((
                "nvidia-smi",
                "--query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
                "--format=csv,noheader,nounits", f"--id={self.uuid}",
            ))
            if output.returncode != 0:
                return CollectionResult(self.spec.key, failure=parsing.UNAVAILABLE)
            rows = parsing.csv_rows(output.stdout, 8)
            if len(rows) != 1:
                return CollectionResult(self.spec.key, failure=parsing.PARSE)
            metrics, failure = parsing.gpu_metrics(rows[0], self.uuid)
            return CollectionResult(self.spec.key, metrics, failure)
        except OSError as error:
            return CollectionResult(self.spec.key, failure=parsing.io_failure(error, command=True))
        except ValueError:
            return CollectionResult(self.spec.key, failure=parsing.PARSE)

    async def close(self) -> None:
        """幂等关闭独占查询端口；不影响其他 GPU。"""
        await self.io.close()


class GpuDiscovery:
    """gpu_inventory/local：独立周期发现，不是 GPU 槽，不提高最小终端高度。

    查询 index,uuid；成功时 specs 为完整枚举结果，保留输出顺序，UUID/index
    唯一；失败 specs=()，不删除历史卡。成功空CSV结果 count=0 与发现失败不同。
    独立完整文本No devices were found且退出码0或6也按成功无卡；其他非零返回
    不能按关键字猜测无卡。该特例为离线适配契约，目标驱动尚未经实机验证。
    驱动不可用、命令不存在、权限及无效响应不能当作0卡。已知卡消失后仍按UUID
    查询并在自己的状态位失败，重新出现沿用原槽；新UUID追加。子采集只由Monitor
    创建/调度，重复发现不重建来源、不重置采样相位或历史。
    """

    def __init__(self, io: HardwareIO, *, timeout: float = 3.0) -> None:
        self.io = io
        self.timeout = timeout
        self.spec = ObjectSpec(ObjectKey("gpu_inventory", "local"), (Metric("device_count", None),))

    async def discover(self) -> DiscoveryResult:
        """返回 inventory 及声明，不能直接注册 State 或执行新卡 collect。"""
        try:
            output = await self.io.run((
                "nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader,nounits",
            ))
            no_devices = (output.returncode in (0, 6)
                          and output.stdout.strip() == "No devices were found")
            if output.returncode != 0 and not no_devices:
                return DiscoveryResult(CollectionResult(self.spec.key, failure=parsing.UNAVAILABLE))
            rows = [] if no_devices else parsing.csv_rows(output.stdout, 2)
            indexes: set[int] = set()
            uuids: set[str] = set()
            specs = []
            for index_text, uuid_text in rows:
                index = parsing.unsigned_integer(index_text)
                uuid = parsing.gpu_uuid(uuid_text)
                if index in indexes or uuid in uuids:
                    raise ValueError("Duplicate GPU identity.")
                indexes.add(index)
                uuids.add(uuid)
                specs.append(ObjectSpec(ObjectKey("gpu", uuid), GPU_METRICS))
            return DiscoveryResult(CollectionResult(
                self.spec.key, (Metric("device_count", len(specs)),),
            ), tuple(specs))
        except OSError as error:
            return DiscoveryResult(CollectionResult(
                self.spec.key, failure=parsing.io_failure(error, command=True),
            ))
        except ValueError:
            return DiscoveryResult(CollectionResult(self.spec.key, failure=parsing.PARSE))

    def create_collector(self, spec: ObjectSpec) -> Collector:
        """同步无 IO，为新的 GPU UUID 创建独占 LocalHardwareIO 的 GpuCollector。

        只接受本发现器的 GPU 模板，输出 spec 必须完全相同。离线测试可替换本工厂
        的 IO，但不得把测试预计算的派生指标替代被测采集逻辑。
        """
        if (not isinstance(spec, ObjectSpec) or not isinstance(spec.key, ObjectKey)
                or spec.key.collector != "gpu" or spec.metrics != GPU_METRICS):
            raise ValueError("Invalid GPU declaration.")
        uuid = parsing.gpu_uuid(spec.key.object_id)
        return GpuCollector(uuid, LocalHardwareIO(timeout=self.timeout))

    async def close(self) -> None:
        """只关闭发现 IO；子采集器由 Monitor 逐一关闭。"""
        await self.io.close()


@dataclass(frozen=True)
class HardwareSources:
    """组合根的无 IO 组装结果；collectors 顺序为 CPU、RAM、配置前三挂载。"""

    collectors: tuple[Collector, ...]
    discovery: GpuDiscovery


def build_hardware_sources(config: AppConfig) -> HardwareSources:
    """创建来源而不采集；即使直接构造 AppConfig，仍只纳入 mount_points[:3]。

    collection_timeout 传递到每个独占 LocalHardwareIO。组合根把静态spec交给State，
    collectors交给Monitor，再调用register_discovery；CLI使用同一组来源与状态。
    不根据终端尺寸、容器数、模型选择裁剪采集，不连接任何模型或Docker服务。
    """
    timeout = config.collection_timeout
    collectors = (CpuCollector(LocalHardwareIO(timeout=timeout)),
                  MemoryCollector(LocalHardwareIO(timeout=timeout)),
                  *(StorageCollector(index, mount, LocalHardwareIO(timeout=timeout))
                    for index, mount in enumerate(config.mount_points[:3])))
    return HardwareSources(collectors, GpuDiscovery(LocalHardwareIO(timeout=timeout), timeout=timeout))
