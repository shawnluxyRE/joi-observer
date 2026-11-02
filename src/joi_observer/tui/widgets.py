"""REQ-002 硬件纯展示入口；复用Frame的区域和语义颜色。

无采集器、日志或可变State引用；只接受不可变值。所有行沿用layout.py既定
Region，不改变最小尺寸、半页分界、Storage三行、Docker剩余高度。
"""

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import re
import unicodedata

from joi_observer.config import AppConfig
from joi_observer.data.models import Metric, ObjectSnapshot, StateSnapshot
from joi_observer.tui.layout import Region, TextCell, ViewSelection, _clip, format_metric


@dataclass(frozen=True)
class PercentageBar:
    """分段条与紧随其后的百分比文字；无值时空填充、保留轨道且文字为 —。"""

    filled: str
    empty: str
    text: str


def percentage_bar(value: float | None, width: int) -> PercentageBar:
    """有限百分比0..100；width为正整数，否则ValueError（bool也非法）。

    先按十进制ROUND_HALF_UP将百分比保留1位小数，去掉无意义尾零；filled数量
    为同一显示值*width/100按ROUND_HALF_UP取整，用█，其余width格用░。
    文本如0%、25.5%、100%；None为—且全轨道。条与文字不能分别取不同口径。
    """
    if type(width) is not int or width <= 0:
        raise ValueError("Bar width must be a positive integer")
    if value is None:
        return PercentageBar("", "░" * width, "—")
    # Range comparisons reject NaN/inf and oversized integers without converting
    # an arbitrary-precision integer to float first.
    if type(value) not in (int, float) or not 0 <= value <= 100:
        raise ValueError("Percentage must be finite and between 0 and 100")
    rounded = Decimal(str(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    count = int((rounded * width / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    label = "0" if rounded == 0 else format(rounded, "f").rstrip("0").rstrip(".")
    return PercentageBar("█" * count, "░" * (width - count), label + "%")


def capacity_text(used: int | None, total: int | None) -> tuple[str, str]:
    """返回分开的已用/总量文字槽，方便RAM已用灰色、总量正文色。

    单位由有效total决定：>=2**40用TiB，否则GiB；total未知但used>=2**40时
    采用TiB，其他情况GiB。字节除以2**30/2**40，ROUND_HALF_UP保留1位小数
    且保留该小数，如('4.0 GiB','16.0 GiB')；None独立显示—，0不冒充未知。
    值必须非负整数，total为非None时必须>0；used>total/非法类型抛ValueError。
    """
    if any(value is not None and (type(value) is not int or value < 0) for value in (used, total)):
        raise ValueError("Capacity must contain nonnegative integer bytes")
    if total is not None and (total == 0 or (used is not None and used > total)):
        raise ValueError("Total capacity must be positive and at least the used capacity")
    reference = total if total is not None else used
    unit, divisor = ("TiB", 2**40) if reference is not None and reference >= 2**40 else ("GiB", 2**30)

    def text(value: int | None) -> str:
        if value is None:
            return "—"
        # Round the rational byte count directly to tenths. This stays exact for
        # every integer size without Decimal context precision or float limits.
        tenths, remainder = divmod(value * 10, divisor)
        if remainder * 2 >= divisor:
            tenths += 1
        whole, fraction = divmod(tenths, 10)
        return f"{format(Decimal(whole), 'f')}.{fraction} {unit}"

    return text(used), text(total)


def linked_gpu_ids(
    snapshot: StateSnapshot, config: AppConfig, view: ViewSelection,
) -> tuple[str, ...]:
    """按快照GPU顺序返回显式映射命中的UUID；不采集、不排序、不持久化选择。

    model_id=None采用配置第一个模型；未知id/空模型/空gpu_ids返回()。完整UUID
    精确匹配key可用于保留的旧卡；索引仅匹配本次非STALE、已采样、index为非负
    整数的卡，且该索引在当前非STALE卡中唯一，字符串必须为规范十进制。
    '04'不视为'4'，UUID前缀/型号/占用均不猜测；同卡被多种标识命中也只返回一次。
    失败卡的过期index不得继续高亮；明确UUID映射仍有效，不把局部失败猜作换卡。
    """
    selected = view.model_id if view.model_id is not None else (config.models[0].id if config.models else None)
    model = next((model for model in config.models if model.id == selected), None)
    if model is None or not model.gpu_ids:
        return ()
    cards = tuple(obj for obj in snapshot.objects if obj.key.collector == "gpu")
    indices: dict[str, list[str]] = {}
    for obj in cards:
        value = _value(obj, "index")
        if not obj.stale and obj.sampled_at is not None and type(value) is int and value >= 0:
            indices.setdefault(format_metric(Metric("index", value)), []).append(obj.key.object_id)
    linked = {obj.key.object_id for obj in cards
              if _UUID.fullmatch(obj.key.object_id) and obj.key.object_id in model.gpu_ids}
    for alias in model.gpu_ids:
        matches = indices.get(alias, ())
        if len(matches) == 1:
            linked.add(matches[0])
    return tuple(obj.key.object_id for obj in cards if obj.key.object_id in linked)


def hardware_cells(
    snapshot: StateSnapshot,
    config: AppConfig,
    regions: tuple[Region, ...],
    *,
    gpu_slots: tuple[str, ...],
    view: ViewSelection = ViewSelection(),
) -> tuple[TextCell, ...]:
    """生成GPU/Host/Storage内部内容及预留状态，不画边框、不触碰其他区域。

    GPU每槽3行：row+1+3*i为GPU编号/裁切名称/STALE；下一行分段条与紧邻百分比；
    第三行显存已用/总量、温度、功耗。内容内宽=region.width-4，条宽=floor(内宽/2)。
    名称截断不能挤占编号与5字符状态槽。未知身份用GPU —，不拿UUID假装编号。
    只有关联卡的编号/填充条/百分比用primary，其余同位置muted；名称text，
    显存muted，温度功耗text，轨道muted。没有模型映射时全部取消关联高亮。
    inventory首次未采集显示—；成功0卡且会话无槽显示No NVIDIA GPUs；失败在
    面板标题原状态槽显示STALE，无槽时内容仍—，不能把失败显示成成功无卡。

    Host保留3个内部行：CPU条/百分比，RAM条/百分比，RAM已用/总量；条用secondary，
    轨道muted，RAM已用muted、总量text。cpu/ram任一失败令标题固定槽STALE。
    Storage在row+2..+4恰好3行，按config前3项匹配storage/mount-0..2，原路径单行
    截断并给容量/百分比/STALE留位；无配置在这三行内显示No mount points configured。
    兼容REQ-001通用快照：无index字段的旧GPU对象/纯十进制空槽保留GPU {key}标签
    及通用name: value指标，host/local保留通用字段和STALE；有index模板即走新契约，
    即使其值None也不能退回UUID标签。旧路径key兼容读取（序号key优先）。这些兼容
    不创建生产来源，生产仅生成REQ-002新schema，不能将无UUID的卡作为新发现设备。
    不支持字段显示—；失败仅状态位STALE、保留已有值，不添加时间/原因/诊断。
    所有TextCell须限制在所属Region内，颜色仅语义role，无amber或ANSI转义。
    """
    objects = {(obj.key.collector, obj.key.object_id): obj for obj in snapshot.objects}
    by_region = {region.name: region for region in regions}
    cells: list[TextCell] = []

    def put(region: Region, row: int, column: int, value: str, role: str = "text",
            width: int | None = None) -> None:
        if not (region.row <= row < region.row + region.height
                and region.column <= column < region.column + region.width):
            return
        available = region.column + region.width - column
        clipped = _clip(value, min(available, width) if width is not None else available)
        if clipped:
            cells.append(TextCell(row, column, clipped, role))

    def status(region: Region, row: int, stale: bool) -> None:
        put(region, row, region.column + region.width - 7, "STALE" if stale else "     ", width=5)

    def bar(region: Region, row: int, column: int, value: float | None, role: str,
            width: int) -> None:
        display = percentage_bar(value, width)
        put(region, row, column, display.filled, role, width)
        put(region, row, column + len(display.filled), display.empty, "muted", width - len(display.filled))
        put(region, row, column + width + 1, display.text, role, region.width - 4 - width - (column - region.column - 2) - 1)

    gpu = by_region.get("gpu")
    if gpu is not None:
        inventory = objects.get(("gpu_inventory", "local"))
        status(gpu, gpu.row, bool(inventory and inventory.stale))
        if not gpu_slots:
            empty = "No NVIDIA GPUs" if (inventory is not None and not inventory.stale
                and inventory.sampled_at is not None and _value(inventory, "device_count") == 0) else "—"
            put(gpu, gpu.row + 1, gpu.column + 2, empty, "muted", gpu.width - 4)
        linked = set(linked_gpu_ids(snapshot, config, view))
        for index, object_id in enumerate(gpu_slots):
            row = gpu.row + 1 + 3 * index
            if row + 2 >= gpu.row + gpu.height - 1:
                break
            obj = objects.get(("gpu", object_id))
            metrics = {metric.name: metric for metric in obj.metrics} if obj else {}
            legacy = (obj is not None and "index" not in metrics) or (
                obj is None and re.fullmatch(r"(?:0|[1-9][0-9]*)", object_id) is not None)
            role = "primary" if object_id in linked else "muted"
            if legacy:
                put(gpu, row, gpu.column + 2, f"GPU {object_id}", role, gpu.width - 11)
                put(gpu, row + 1, gpu.column + 2, _generic_metrics(obj), "muted", gpu.width - 4)
            else:
                number = format_metric(metrics.get("index", Metric("index", None)))
                label = f"GPU {number}"
                put(gpu, row, gpu.column + 2, label, role, gpu.width - 11)
                name_column = gpu.column + 2 + _width(label) + 2
                put(gpu, row, name_column, format_metric(metrics.get("name", Metric("name", None))),
                    "text", max(0, gpu.column + gpu.width - 8 - name_column))
                bar(gpu, row + 1, gpu.column + 2, _value(obj, "utilization_percent"), role,
                    max(1, (gpu.width - 4) // 2))
                used, total = capacity_text(_value(obj, "memory_used_bytes"), _value(obj, "memory_total_bytes"))
                memory = f"{used} / {total}"
                put(gpu, row + 2, gpu.column + 2, memory, "muted", gpu.width - 4)
                details_column = gpu.column + 2 + _width(memory) + 2
                temperature = format_metric(Metric("temperature", _value(obj, "temperature_c"), "°C"))
                power = format_metric(Metric("power", _value(obj, "power_w"), "W"))
                put(gpu, row + 2, details_column, f"{temperature}  {power}", "text",
                    max(0, gpu.column + gpu.width - 2 - details_column))
            status(gpu, row, bool(obj and obj.stale))

    host = by_region.get("host")
    if host is not None:
        cpu, ram = objects.get(("host", "cpu")), objects.get(("host", "ram"))
        legacy = objects.get(("host", "local")) if cpu is None and ram is None else None
        status(host, host.row, any(obj is not None and obj.stale for obj in (cpu, ram, legacy)))
        if legacy is not None:
            for index, label in enumerate(("CPU", "RAM")):
                metric = legacy.metrics[index] if index < len(legacy.metrics) else None
                value = f"{metric.name}: {format_metric(metric)}" if metric else f"{label}: —"
                put(host, host.row + 1 + index, host.column + 2, value, width=host.width - 4)
        else:
            for index, (label, obj, field) in enumerate((("CPU", cpu, "cpu_percent"), ("RAM", ram, "ram_percent"))):
                row = host.row + 1 + index
                put(host, row, host.column + 2, label, width=3)
                bar(host, row, host.column + 6, _value(obj, field), "secondary", max(1, (host.width - 8) // 2))
            used, total = capacity_text(_value(ram, "ram_used_bytes"), _value(ram, "ram_total_bytes"))
            put(host, host.row + 3, host.column + 6, used, "muted", host.width - 8)
            total_column = host.column + 6 + _width(used)
            put(host, host.row + 3, total_column, " / ", "muted", host.width - 2 - (total_column - host.column))
            put(host, host.row + 3, total_column + 3, total, "text", max(0, host.width - 5 - (total_column - host.column)))

    storage = by_region.get("storage")
    if storage is not None:
        if not config.mount_points:
            put(storage, storage.row + 2, storage.column + 2, "No mount points configured", "muted", storage.width - 4)
        for index, mount in enumerate(config.mount_points[:3]):
            row = storage.row + 2 + index
            obj = objects.get(("storage", f"mount-{index}"), objects.get(("storage", mount)))
            metric_names = {metric.name for metric in obj.metrics} if obj else set()
            if obj is not None and not metric_names.intersection({"used_bytes", "total_bytes", "used_percent"}):
                put(storage, row, storage.column + 2, f"{mount}  {_generic_metrics(obj)}", width=storage.width - 11)
            else:
                used, total = capacity_text(_value(obj, "used_bytes"), _value(obj, "total_bytes"))
                percent = percentage_bar(_value(obj, "used_percent"), 1).text
                values = f"{used} / {total}  {percent}"
                # Keep a gap before the fixed state slot; clip names before capacity.
                available = storage.width - 11
                path_width = max(0, available - _width(values) - 2)
                path = _clip(mount, path_width)
                put(storage, row, storage.column + 2, f"{path}  {values}", width=available)
            status(storage, row, bool(obj and obj.stale))
    return tuple(cells)


_UUID = re.compile(r"GPU-[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")


def _value(obj: ObjectSnapshot | None, name: str):
    """Read named metrics without relying on registration or field ordering."""
    return next((metric.value for metric in obj.metrics if metric.name == name), None) if obj else None


def _generic_metrics(obj: ObjectSnapshot | None) -> str:
    if obj is None or not obj.metrics:
        return "—"
    return "  ".join(f"{metric.name}: {format_metric(metric)}" for metric in obj.metrics)


def _width(value: str) -> int:
    return sum(0 if unicodedata.combining(char) else 2 if unicodedata.east_asian_width(char) in "WF" else 1
               for char in value)
