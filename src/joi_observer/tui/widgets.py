"""硬件纯展示入口；复用Frame的区域和语义颜色。

无采集器、日志或可变State引用；只接受不可变值。所有行沿用layout.py既定
Region，按同一帧的分组和可用高度绘制。
"""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from itertools import pairwise
import re
import unicodedata

from joi_observer.config import AppConfig
from joi_observer.data.models import Metric, ObjectSnapshot, StateSnapshot
from joi_observer.tui.layout import GpuGroups, Region, TextCell, ViewSelection, _clip, format_metric, grouped_gpu_rows


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


def _configured_gpus(snapshot: StateSnapshot, config: AppConfig) -> dict[str, set[str | None]]:
    """Keep an unresolved alias as None so a partial match cannot claim a TP size."""
    aliases: dict[str, str | None] = {}
    for obj in snapshot.objects:
        if obj.key.collector != "gpu":
            continue
        card = obj.key.object_id
        if _UUID.fullmatch(card):
            aliases[card] = card
        value = _value(obj, "index")
        if not obj.stale and obj.sampled_at is not None and type(value) is int and value >= 0:
            index = format_metric(Metric("index", value))
            aliases[index] = None if index in aliases else card

    return {
        model.id: {aliases.get(alias) for alias in model.gpu_ids}
        for model in config.models
    }


def _selected_gpus(by_model: dict[str, set[str | None]], view: ViewSelection) -> set[str | None]:
    if view.model_id is None:
        return next(iter(by_model.values()), set())
    return by_model.get(view.model_id, set())


def _gpu_range(numbers: list[int]) -> str:
    """Compact actual device indices, including sparse sets such as 0–2, 5."""
    runs: list[tuple[int, int]] = []
    for number in sorted(numbers):
        if runs and runs[-1][1] + 1 == number:
            runs[-1] = (runs[-1][0], number)
        else:
            runs.append((number, number))
    labels = []
    for first, last in runs:
        label = format(Decimal(first), "f")
        if last != first:
            label += "–" + format(Decimal(last), "f")
        labels.append(label)
    return "GPU " + ", ".join(labels)


def _gpu_group_headers(gpu_slots: tuple[str, ...], by_model: dict[str, set[str | None]],
                       snapshot: StateSnapshot) -> dict[int, tuple[str, str]]:
    """Keep every model's span intact in display order, including overlaps."""
    positions = {card: index for index, card in enumerate(gpu_slots)}
    assigned: set[str | None] = set()
    shared: set[str | None] = set()
    crossed: set[int] = set()
    for cards in by_model.values():
        shared.update(assigned & cards)
        assigned.update(cards)
        indices = [positions[card] for card in cards if card in positions]
        if indices:
            crossed.update(range(min(indices), max(indices)))

    numbers = {}
    for obj in snapshot.objects:
        card = obj.key.object_id
        if obj.key.collector != "gpu" or card not in positions:
            continue
        number = _value(obj, "index")
        if type(number) is int and number >= 0:
            numbers[card] = number
    counts = Counter(numbers.values())
    identifiable = {card for card, number in numbers.items() if counts[number] == 1}
    boundaries = [0] + [i + 1 for i in range(len(gpu_slots)) if i not in crossed]
    headers = {}
    for start, stop in pairwise(boundaries):
        members = set(gpu_slots[start:stop])
        if not (members <= assigned and members <= identifiable):
            continue
        badge = ""
        if members & shared:
            badge = "SHARED"
        elif members in by_model.values():
            badge = f"TP {len(members)}"
        headers[start] = _gpu_range([numbers[card] for card in members]), badge
    return headers


def resolve_gpu_groups(snapshot: StateSnapshot, config: AppConfig, gpu_slots: tuple[str, ...],
                       view: ViewSelection) -> GpuGroups:
    by_model = _configured_gpus(snapshot, config)
    return GpuGroups(_gpu_group_headers(gpu_slots, by_model, snapshot), _selected_gpus(by_model, view))


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
    linked = _selected_gpus(_configured_gpus(snapshot, config), view)
    return tuple(obj.key.object_id for obj in snapshot.objects
                 if obj.key.collector == "gpu" and obj.key.object_id in linked)


def hardware_cells(
    snapshot: StateSnapshot,
    config: AppConfig,
    regions: tuple[Region, ...],
    *,
    gpu_slots: tuple[str, ...],
    view: ViewSelection = ViewSelection(),
    gpu_groups: GpuGroups | None = None,
) -> tuple[TextCell, ...]:
    """生成GPU/Host/Storage内部内容及预留状态，不画边框、不触碰其他区域。

    区域由布局传入并遵守以下几何：
    全屏GPU宽floor((columns-1)*3/5)，一列间隔，右侧使用余宽；Host外壳6行，
    Storage外壳6行且内容3行。最小高度、GPU槽数预算与下半页分界不变。

    每个区域内容边界L=column+2，R=column+width-2（不含R）。后续组头上方独占一行横线。
    有组头时标题下固定留一行，再放设备信息和条；有余高时在组内设备间留一行；
    无组头时从槽首行开始放设备信息和条。方括号编号最多10格；显存槽[L+12,R-12)，温度槽[R-10,R)，
    数值均右对齐。编号后至少一空格，名称只占显存之前的余位，可为空；
    有名称时和编号/显存至少各隔一空格，不能覆盖显存或温度。
    次行：GPU条从L起，占floor((width-4)/2)格，百分比紧随条后的一格空白；
    功率在同一[R-10,R)组右对齐，条/百分比不可碰该组。有组头时STALE放在功率槽左侧；
    无组头时STALE使用槽第三行右端。未知身份用[—]，
    不拿UUID假装编号。极长编号只裁自身10格；数值按下述有界显示规则处理。
    只有关联卡的编号/填充条/百分比用primary，其余同位置muted；名称text，
    显存/功率muted，温度text，轨道track。功率的正常文本为数值+' W'，
    温度仍紧接°C；未知独立显示—。没有模型映射时全部取消关联高亮。
    GPU/CPU/RAM条仅在呈现层统一用▌显示填充段和轨道，每字形仍占1字符列；
    半块自带半格空隙，轨道使用独立深灰track，与未关联GPU的muted填充区分。
    段数、总宽、填充角色和数字位置沿用percentage_bar的返回长度，公开█/░格式与算法不变。
    inventory首次未采集显示—；成功0卡且会话无槽显示No NVIDIA GPUs；失败在
    面板标题原状态槽显示STALE，无槽时内容仍—，不能把失败显示成成功无卡。

    Host内部4行：row+1为CPU标签（L）与百分比（右端R），row+2为CPU条；
    row+3为RAM标签（L）与紧凑容量（右端R），row+4为RAM条。两条都从L起，
    宽floor((width-4)/2)，填充secondary、轨道track，不在条旁重复百分比。
    Host数值槽[L+4,R)，不挤占左侧CPU/RAM标签。CPU百分比固定1位小数，
    数字text、%为muted，
    未知—为text；只有进度条使用secondary。RAM已用/分隔符/末尾共享单位
    muted、总量数字text；未知值沿所属数字片段角色。cpu/ram任一失败令标题
    [R-5,R)固定槽STALE。未知比例保留空轨道，未知值不能伪装为0。
    GPU/RAM容量组合共享末尾单位；GPU保留1位，RAM的GiB/TiB均从原始字节
    ROUND_HALF_UP为整数，例如'4 / 16 GiB'、'— / 16 GiB'、'4 / — GiB'；
    双未知为'— / —'。RAM不增加百分比文字。capacity_text接口仍返回各自带单位
    的1位小数值，仅私有展示改变精度与组合，不修改原始指标。
    Storage在row+2..+4恰好3行，按config前3项匹配storage/mount-0..2，原路径单行
    靠L绘制；容量与百分比槽[L+2,R)，整体贴内容右缘，内容行不占状态槽。
    前3个配置挂载点任一STALE时仅在标题[R-5,R)显示一次STALE，角色text。
    Storage的GiB数值从原始字节ROUND_HALF_UP为整数，TiB仍保留1位小数；
    不先按1位小数格式化再整数舍入。组文本例如'1 / 4 GiB · 25.0%'，全未知为
    '— / — · —'；路径text，容量/中点分隔muted，百分比固定1位小数、含%为text。路径只裁剩余宽度，
    和数值至少隔一格；未配置及第4个起的挂载点不参与面板状态。
    无配置在这三行内以text显示No mount points configured。
    其他数值格式不变。数值组过宽时先采用最多3位有效数字的科学记数，
    保留指数和单位，不修改原始指标或capacity_text返回值；仍放不下时，
    只在该槽显示明确的…，不能截成看似较小的完整数或冒充—/0/N/A。
    先保留身份/标签/状态及分隔，再安排数值槽；巨大整数不得先转float溢出。
    兼容原通用快照：无index字段的旧GPU对象/纯十进制空槽使用方括号编号
    及次行通用name: value指标、首行旧状态槽，host/local保留通用字段和STALE；有index模板即走新契约，
    即使其值None也不能退回UUID标签。旧路径key兼容读取（序号key优先）。这些兼容
    不创建生产来源，生产仅生成具名指标schema，不能将无UUID的卡作为新发现设备。
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
            width: int, *, show_value: bool = True) -> None:
        display = percentage_bar(value, width)
        put(region, row, column, "▌" * len(display.filled), role, width)
        put(region, row, column + len(display.filled), "▌" * len(display.empty), "track", width - len(display.filled))
        if show_value:
            put(region, row, column + width + 1, display.text, role,
                max(0, region.column + region.width - 12 - column - width - 1))

    def right_parts(region: Region, row: int, end: int,
                    parts: tuple[tuple[str, str], ...]) -> int:
        """Draw pre-bounded spans without losing per-part semantic colors."""
        column = end - sum(_width(text) for text, _ in parts)
        start = column
        spans: list[tuple[str, str]] = []
        for text, role in parts:
            if not text:
                continue
            if spans and spans[-1][1] == role:
                spans[-1] = (spans[-1][0] + text, role)
            else:
                spans.append((text, role))
        for text, role in spans:
            put(region, row, column, text, role, _width(text))
            column += _width(text)
        return start

    gpu = by_region.get("gpu")
    if gpu is not None:
        inventory = objects.get(("gpu_inventory", "local"))
        status(gpu, gpu.row, bool(inventory and inventory.stale))
        if not gpu_slots:
            empty = "No NVIDIA GPUs" if (inventory is not None and not inventory.stale
                and inventory.sampled_at is not None and _value(inventory, "device_count") == 0) else "—"
            put(gpu, gpu.row + 1, gpu.column + 2, empty, "muted", gpu.width - 4)
        if gpu_groups is None:
            gpu_groups = resolve_gpu_groups(snapshot, config, gpu_slots, view)
        headers = gpu_groups.headers
        left, right = gpu.column + 2, gpu.column + gpu.width - 2
        first_header = next(iter(headers), None)
        cursor = gpu.row + 1
        bottom = gpu.row + gpu.height - 1
        spare_rows = bottom - cursor - grouped_gpu_rows(len(gpu_slots), len(headers))
        for index, object_id in enumerate(gpu_slots):
            row = cursor
            has_header = index in headers
            divider = has_header and index != first_header
            if has_header:
                header_row = cursor + int(divider)
                row = header_row + 2
            elif headers and spare_rows > 0:
                row += 1
                spare_rows -= 1
            cursor = row + (2 if headers else 3)
            if cursor > bottom:
                break
            if has_header:
                if divider:
                    put(gpu, header_row - 1, left, "─" * (right - left), "muted")
                title, badge = headers[index]
                badge_start = right - len(badge)
                title_end = badge_start - 1 if badge else right
                width = title_end - left
                if len(title) > width:
                    title = title[:max(0, width - 1)] + "…"
                put(gpu, header_row, left, title, "text")
                put(gpu, header_row, badge_start, badge, "secondary")
            obj = objects.get(("gpu", object_id))
            metrics = {metric.name: metric for metric in obj.metrics} if obj else {}
            legacy_number = re.fullmatch(r"(?:0|[1-9][0-9]*)", object_id) is not None
            legacy = (obj is not None and "index" not in metrics) or (obj is None and legacy_number)
            stale = bool(obj and obj.stale)
            role = "primary" if object_id in gpu_groups.linked else "muted"
            number = format_metric(metrics.get("index", Metric("index", None)))
            if legacy and legacy_number:
                number = object_id
            label = "[" + (number if len(number) <= 8 else number[:7] + "…") + "]"
            put(gpu, row, left, label, role, 10)
            if legacy:
                put(gpu, row + 1, gpu.column + 2, _generic_metrics(obj), "muted", gpu.width - 4)
                status(gpu, row, stale)
            else:
                memory_parts = _capacity_parts(_value(obj, "memory_used_bytes"),
                                               _value(obj, "memory_total_bytes"),
                                               max(0, right - left - 24))
                memory_start = right_parts(gpu, row, right - 12, memory_parts)
                name_column = left + _width(label) + 1
                put(gpu, row, name_column,
                    format_metric(metrics.get("name", Metric("name", None))),
                    "text", max(0, memory_start - name_column - 1))
                bar(gpu, row + 1, left, _value(obj, "utilization_percent"), role,
                    max(1, (gpu.width - 4) // 2))
                temperature = _bounded_number(_value(obj, "temperature_c"), "°C", 10)
                power = _bounded_number(_value(obj, "power_w"), " W", 10)
                right_parts(gpu, row, right, ((temperature, "text"),))
                right_parts(gpu, row + 1, right, ((power, "muted"),))
                if not headers:
                    status(gpu, row + 2, stale)
                elif stale:
                    put(gpu, row + 1, right - 16, "STALE")

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
            left, right = host.column + 2, host.column + host.width - 2
            for index, (label, obj, field) in enumerate((("CPU", cpu, "cpu_percent"), ("RAM", ram, "ram_percent"))):
                row = host.row + 1 + index * 2
                put(host, row, left, label, width=3)
                bar(host, row + 1, left, _value(obj, field), "secondary",
                    max(1, (host.width - 4) // 2), show_value=False)
            percent = _fixed_percentage(_value(cpu, "cpu_percent"))
            percent_parts = ((percent[:-1], "text"), ("%", "muted")) if percent.endswith("%") else ((percent, "text"),)
            right_parts(host, host.row + 1, right, percent_parts)
            right_parts(host, host.row + 3, right,
                        _capacity_parts(_value(ram, "ram_used_bytes"), _value(ram, "ram_total_bytes"),
                                        max(0, right - left - 4), total_role="text",
                                        integer_units=("GiB", "TiB")))

    storage = by_region.get("storage")
    if storage is not None:
        visible = tuple((mount, objects.get(("storage", f"mount-{index}"),
                                            objects.get(("storage", mount))))
                        for index, mount in enumerate(config.mount_points[:3]))
        status(storage, storage.row, any(obj is not None and obj.stale for _, obj in visible))
        if not config.mount_points:
            put(storage, storage.row + 2, storage.column + 2, "No mount points configured", "text", storage.width - 4)
        for index, (mount, obj) in enumerate(visible):
            row = storage.row + 2 + index
            metric_names = {metric.name for metric in obj.metrics} if obj else set()
            if obj is not None and not metric_names.intersection({"used_bytes", "total_bytes", "used_percent"}):
                put(storage, row, storage.column + 2, f"{mount}  {_generic_metrics(obj)}", width=storage.width - 4)
            else:
                left, right = storage.column + 2, storage.column + storage.width - 2
                percent = _fixed_percentage(_value(obj, "used_percent"))
                parts = _capacity_parts(_value(obj, "used_bytes"), _value(obj, "total_bytes"),
                                        max(0, right - left - 2), integer_units=("GiB",),
                                        suffix=((" · ", "muted"), (percent, "text")))
                values_start = right_parts(storage, row, right, parts)
                put(storage, row, left, mount, "text", max(0, values_start - left - 1))
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


def _scientific(number: str) -> str:
    """At most three significant digits; Decimal never narrows huge ints to float."""
    value = Decimal(number)
    if not value:
        return "0"
    mantissa, exponent = format(value, ".2E").split("E")
    return mantissa.rstrip("0").rstrip(".") + "e" + str(int(exponent))


def _bounded_number(value: int | float | None, unit: str, width: int) -> str:
    """Keep a whole value and unit, or explicitly mark a slot that cannot fit."""
    number = format_metric(Metric("value", value))
    text = number if value is None else number + unit
    if _width(text) <= width:
        return text
    compressed = _scientific(number) + unit
    return compressed if _width(compressed) <= width else "…"


def _fixed_percentage(value: float | None) -> str:
    """Retain the public bar's rounding while displaying one decimal place."""
    text = percentage_bar(value, 1).text
    return text if value is None else format(Decimal(text[:-1]), ".1f") + "%"


def _capacity_parts(
    used: int | None, total: int | None, width: int, *, total_role: str = "muted",
    integer_units: tuple[str, ...] = (),
    suffix: tuple[tuple[str, str], ...] = (),
) -> tuple[tuple[str, str], ...]:
    """Share the existing formatter's unit, then bound the complete numeric group."""
    used_text, total_text = capacity_text(used, total)
    unit = next((text.rsplit(" ", 1)[1] for text in (total_text, used_text) if " " in text), "")
    left, right = used_text.split(" ", 1)[0], total_text.split(" ", 1)[0]
    if unit in integer_units:
        # Round raw bytes once. Rounding capacity_text's tenths again would
        # incorrectly turn, for example, 1.49 GiB into 2 GiB.
        divisor = 2**40 if unit == "TiB" else 2**30

        def whole(value: int | None) -> str:
            if value is None:
                return "—"
            number, remainder = divmod(value, divisor)
            return format(Decimal(number + (remainder * 2 >= divisor)), "f")

        left, right = whole(used), whole(total)

    def parts() -> tuple[tuple[str, str], ...]:
        return ((left + " / ", "muted"), (right, total_role),
                ((" " + unit) if unit else "", "muted"), *suffix)

    result = parts()
    if sum(_width(text) for text, _ in result) > width:
        left = _scientific(left) if used is not None else left
        right = _scientific(right) if total is not None else right
        result = parts()
    return result if sum(_width(text) for text, _ in result) <= width else (("…", "muted"),)
