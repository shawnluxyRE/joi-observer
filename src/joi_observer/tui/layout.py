"""REQ-001 终端容量与纯函数屏幕生成；不持有采集或状态写入端口。

按需求v1.12平分页面，Storage固定三行内容，Docker只绘制可见前缀。
可见容量只影响Frame，不改变完整配置、只读快照或采集状态。
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import math
import unicodedata

from joi_observer.config import AppConfig
from joi_observer.data.models import Metric, StateSnapshot


@dataclass(frozen=True)
class TerminalSize:
    """终端字符单元尺寸，columns/rows 均为非负整数，不能使用像素。"""

    columns: int
    rows: int


@dataclass(frozen=True)
class HostInfo:
    """本机静态名称和系统说明；从本地 OS 获取，不进行 DNS 或网络探测。"""

    hostname: str
    system: str


@dataclass(frozen=True)
class ViewSelection:
    """仅会话内的展示选择。theme 为 moonlight/hologram；未知选择用 None。"""

    model_id: str | None = None
    theme: str = "moonlight"


@dataclass(frozen=True)
class TextCell:
    """一次文字绘制：零基 row/column；role 为语义样式，不嵌入 ANSI 转义。

    text 不得含控制字符、换行或诊断详情；过长文字由布局层按显示宽度
    截断为一行。role 供 REQ-006 映射色彩，不能用文本内容推断故障原因。
    """

    row: int
    column: int
    text: str
    role: str = "text"


@dataclass(frozen=True)
class Region:
    """命名区域的字符单元矩形，可有或无边框；用于验证故障前后布局稳定。"""

    name: str
    row: int
    column: int
    width: int
    height: int


@dataclass(frozen=True)
class Frame:
    """不可变屏幕；不引用状态内部容器，不携带异常、错误类型或采样时间。

    minimum_size 是当前容量所需尺寸；too_small 时 cells 只包含简短英文
    放大提示与 q 提示，regions 为空。正常布局含 header/gpu/host/storage/
    docker/service/service_switch/footer 八个区域。
    service_switch 独立于服务窗口，和footer各1行，均属于全页下半区。
    后端不得自行追加诊断文字、Docker溢出提示或滚动区域。
    """

    cells: tuple[TextCell, ...]
    regions: tuple[Region, ...]
    minimum_size: TerminalSize
    too_small: bool = False


def format_metric(metric: Metric) -> str:
    """通用值槽格式化；不负责业务派生、单位换算或模型类型映射。

    applicable=False优先返回'N/A'；value=None返回'—'且不追加单位；数字0
    返回'0'再接unit，其他数值保留调用方精度（常规十进制，不输出nan/inf）；
    string值不追加单位。控制字符与换行替换为空格以维持单行布局。metric的
    业务数值合法性由采集/状态契约保证，显示层不能把非法值转成正常0。
    示例：Metric('usage', 0, '%') -> '0%'。
    """
    if not metric.applicable:
        return "N/A"
    if metric.value is None:
        return "—"
    if isinstance(metric.value, str):
        return _single_line(metric.value)
    if isinstance(metric.value, bool) or not math.isfinite(metric.value):
        raise ValueError("Metric must contain a finite number")
    value = format(Decimal(str(metric.value)), "f")
    if "." in value:
        value = value.rstrip("0").rstrip(".")
    if metric.value == 0:
        value = "0"
    return value + _single_line(metric.unit)


def required_size(*, gpu_count: int, mount_count: int, container_count: int) -> TerminalSize:
    """返回完整 Neon Grid 所需最小尺寸，无 I/O 或状态变化。

    v1.12契约保留现有三个计数参数签名。所有参数
    必须是非负int，bool/小数/负数抛ValueError；container_count不设上限，
    mount_count超过3不增高。后两参数仅验证输入，不参与最小尺寸计算。
    gpu_count为会话保留的GPU槽数；列数固定120。
    行数 = max(36, 2 * (2 + max(3 * max(gpu_count, 1) + 2, 16)) - 1)。

    全页H行：下半L=H//2，上半U=H-L，header2包含在上半内；硬件高度U-2。
    右侧最低16行=Host5+间距1+Storage6+间距1+Docker外壳3，允许Docker零
    内容行；下半最低18行=服务窗口16+切换位1+键位1。GPU每卡3行另加边框2。
    0～4GPU最低120×36，5GPU120×37，6GPU120×43，10GPU120×67。
    Docker数量只影响显示前缀长度，不导致放大提示；模型数也不参与公式。
    """
    counts = (gpu_count, mount_count, container_count)
    if any(type(count) is not int or count < 0 for count in counts):
        raise ValueError("Object counts must be nonnegative integers")
    hardware_minimum = max(3 * max(gpu_count, 1) + 2, 16)
    return TerminalSize(120, max(36, 2 * (2 + hardware_minimum) - 1))


def compose_frame(
    snapshot: StateSnapshot,
    config: AppConfig,
    size: TerminalSize,
    host: HostInfo,
    now: datetime,
    *,
    gpu_slots: tuple[str, ...] = (),
    view: ViewSelection = ViewSelection(),
) -> Frame:
    """从只读快照生成屏幕，不采集、不写日志、不更改选择或快照。

    now 必须含时区，直接显示该本机时区的 YYYY-MM-DD HH:MM:SS；不使用
    监控样本时间冒充当前时间。gpu_slots 是本会话已见 GPU object_id 的稳定
    顺序（reader 中 collector='gpu'）；新卡追加，故障或消失不删槽。禁止
    根据模型选择过滤或重排 GPU。以下为v1.12半页布局契约。

    H为总可绘制高度，L=H//2，U=H-L。header为row0/height2；gpu为row2/
    height(U-2)；右侧host为row2/height5，row7留白，storage为row8/height6
    （内容row10..12共3行），row14留白，docker为row15/height(U-15)。
    service从rowU开始、height(L-2)；service_switch为row(H-2)/height1，
    footer为row(H-1)/height1；两半之外不再额外占行。

    Storage只画配置前三项，不足3项保留内容空行；失败不以第四项补位。
    Docker内容容量=max(0,U-18)，按配置顺序只画前capacity个容器，余项
    仍保留在配置/快照并由Monitor持续采集。容量零时不画条目或空态；容量
    大于零且未配置容器时在内容区画空态。不作省略号、更多/隐藏数量或放大
    提示，不滚动/分页；少量容器允许留白，不能压缩面板或把余高让给Storage。
    所有内容必须限制在各自region内，禁止越过边框覆盖下半区。

    空值/尚未采集显示 —，真实0显示0，applicable=False显示 N/A；仅 stale
    对象的预留5字符状态位显示 STALE，不展示 sampled_at/history时间、原因
    或任何错误诊断。正常/失败/恢复、不同模型类型共用同样区域高度。
    顶部文字 Joi::Observer，hostname/system 在时间左侧；默认主题 Moonlight。
    底部 vLLM 与禁用 WebUI；键位仅 ↑↓ Models、t Theme、q Quit。

    实际尺寸低于 required_size 任一维度时返回 too_small=True，只显示
    'Enlarge terminal to at least {columns}x{rows}' 和 'q Quit'（极小终端可
    裁切可见文字，但 q 事件仍有效）。恢复尺寸自动返回常规 frame。
    所有 TextCell 均须落在 size 范围内；长名称截断，不增加行数。
    业务面板详细排版/色彩由 REQ-002～006 在本接口上继续设计。
    """
    if any(type(value) is not int or value < 0 for value in (size.columns, size.rows)):
        raise ValueError("Terminal dimensions must be nonnegative integers")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Current time must include a timezone")
    minimum = required_size(gpu_count=len(gpu_slots), mount_count=len(config.mount_points),
                            container_count=len(config.containers))
    cells: list[TextCell] = []

    def put(row: int, column: int, value: str, role: str = "text", width: int | None = None) -> None:
        if 0 <= row < size.rows and 0 <= column < size.columns:
            available = size.columns - column
            value = _clip(value, min(available, width) if width is not None else available)
            if value:
                cells.append(TextCell(row, column, value, role))

    if size.columns < minimum.columns or size.rows < minimum.rows:
        put(0, 0, f"Enlarge terminal to at least {minimum.columns}x{minimum.rows}")
        put(1, 0, "q Quit", "primary")
        return Frame(tuple(cells), (), minimum, too_small=True)

    lower = size.rows // 2
    upper = size.rows - lower
    left_width = size.columns // 2
    right_column = left_width + 1
    right_width = size.columns - right_column
    regions = (
        Region("header", 0, 0, size.columns, 2),
        Region("gpu", 2, 0, left_width, upper - 2),
        Region("host", 2, right_column, right_width, 5),
        Region("storage", 8, right_column, right_width, 6),
        Region("docker", 15, right_column, right_width, upper - 15),
        Region("service", upper, 0, size.columns, lower - 2),
        Region("service_switch", size.rows - 2, 0, size.columns, 1),
        Region("footer", size.rows - 1, 0, size.columns, 1),
    )
    by_region = {region.name: region for region in regions}

    def region_put(region: Region, row: int, column: int, value: str,
                   role: str = "text", width: int | None = None) -> None:
        """Constrain drawing locally, not merely to the overall terminal size."""
        if (region.row <= row < region.row + region.height
                and region.column <= column < region.column + region.width):
            available = region.column + region.width - column
            put(row, column, value, role, min(available, width) if width is not None else available)

    def border(region: Region, title: str, role: str = "secondary") -> None:
        region_put(region, region.row, region.column, "┌" + "─" * (region.width - 2) + "┐", "muted")
        region_put(region, region.row + region.height - 1, region.column,
            "└" + "─" * (region.width - 2) + "┘", "muted")
        for row in range(region.row + 1, region.row + region.height - 1):
            region_put(region, row, region.column, "│", "muted")
            region_put(region, row, region.column + region.width - 1, "│", "muted")
        region_put(region, region.row, region.column + 2, f" {title} ", role, region.width - 4)

    for name, title in (("gpu", "GPU"), ("host", "Host Resources"),
                        ("storage", "Storage"), ("docker", "Docker"), ("service", "vLLM")):
        border(by_region[name], title)

    header = by_region["header"]
    region_put(header, 0, 0, "Joi", "secondary")
    region_put(header, 0, 3, "::", "muted")
    region_put(header, 0, 5, "Observer", "primary")
    theme = "Hologram" if view.theme == "hologram" else "Moonlight"
    region_put(header, 0, size.columns - 23, f"Theme: {theme} [t]", "secondary")
    clock_text = now.strftime("%Y-%m-%d %H:%M:%S")
    region_put(header, 1, 0, f"{host.hostname}  {host.system}", "muted", size.columns - len(clock_text) - 2)
    region_put(header, 1, size.columns - len(clock_text), clock_text, "text")
    objects = {(obj.key.collector, obj.key.object_id): obj for obj in snapshot.objects}

    def status(row: int, region: Region, obj) -> None:
        region_put(region, row, region.column + region.width - 7,
                   "STALE" if obj and obj.stale else "     ", "text", 5)

    def metrics(obj) -> str:
        if obj is None or not obj.metrics:
            return "—"
        return "  ".join(f"{metric.name}: {format_metric(metric)}" for metric in obj.metrics)

    gpu = by_region["gpu"]
    if not gpu_slots:
        region_put(gpu, gpu.row + 1, gpu.column + 2, "No GPU data", "muted", gpu.width - 4)
    for index, object_id in enumerate(gpu_slots):
        row = gpu.row + 1 + 3 * index
        obj = objects.get(("gpu", object_id))
        region_put(gpu, row, gpu.column + 2, f"GPU {object_id}", "primary", gpu.width - 11)
        status(row, gpu, obj)
        region_put(gpu, row + 1, gpu.column + 2, metrics(obj), "muted", gpu.width - 4)

    host_region = by_region["host"]
    host_objects = [obj for obj in snapshot.objects if obj.key.collector == "host"]
    host_obj = next((obj for obj in host_objects if obj.stale), host_objects[0] if host_objects else None)
    status(host_region.row, host_region, host_obj)
    host_metrics = tuple(metric for obj in host_objects for metric in obj.metrics)
    for index, label in enumerate(("CPU", "RAM")):
        metric = host_metrics[index] if index < len(host_metrics) else None
        value = f"{metric.name}: {format_metric(metric)}" if metric else f"{label}: —"
        region_put(host_region, host_region.row + 1 + index, host_region.column + 2,
                   value, "text", host_region.width - 4)

    storage = by_region["storage"]
    if not config.mount_points:
        region_put(storage, storage.row + 2, storage.column + 2,
                   "No mount points configured", "muted", storage.width - 4)
    for index, mount in enumerate(config.mount_points[:3]):
        obj = objects.get(("storage", mount))
        row = storage.row + 2 + index
        region_put(storage, row, storage.column + 2, f"{mount}  {metrics(obj)}", "text", storage.width - 11)
        status(row, storage, obj)

    docker = by_region["docker"]
    docker_capacity = max(0, docker.height - 3)
    if docker_capacity and not config.containers:
        region_put(docker, docker.row + 2, docker.column + 2,
                   "No containers configured", "muted", docker.width - 4)
    for index, container in enumerate(config.containers[:docker_capacity]):
        obj = objects.get(("docker", container.id))
        row = docker.row + 2 + index
        state = "STALE" if obj and obj.stale else (
            format_metric(obj.metrics[0]) if obj and obj.metrics else "—")
        region_put(docker, row, docker.column + 2, container.name, "text", docker.width - 19)
        region_put(docker, row, docker.column + docker.width - 16, state, "text", 14)

    service = by_region["service"]
    model_id = view.model_id if view.model_id is not None else (config.models[0].id if config.models else None)
    selected = next((i for i, model in enumerate(config.models) if model.id == model_id), 0)
    model_capacity = service.height - 2
    first = max(0, selected - model_capacity + 1)
    model_width = max(30, size.columns // 3)
    if not config.models:
        region_put(service, service.row + 2, 2, "No models configured", "muted", model_width - 3)
        region_put(service, service.row + 2, model_width + 2, "—", "muted")
    for index, model in enumerate(config.models[first:first + model_capacity], first):
        row = service.row + 1 + index - first
        obj = objects.get(("vllm", model.id))
        region_put(service, row, 2, model.name, "primary" if model.id == model_id else "text", model_width - 10)
        region_put(service, row, model_width - 7, "STALE" if obj and obj.stale else "     ", "text", 5)
    if config.models:
        model = config.models[selected]
        obj = objects.get(("vllm", model.id))
        region_put(service, service.row + 1, model_width + 2,
                   f"{model.name}  [{model.type.value}]", "secondary", service.width - model_width - 11)
        status(service.row + 1, service, obj)
        region_put(service, service.row + 2, model_width + 2,
                   model.base_url, "secondary", service.width - model_width - 4)
        metric_rows = min(9, service.height - 5)
        visible_metrics = obj.metrics[:metric_rows] if obj else (Metric("RUNNING", None), Metric("WAITING", None))
        for index, metric in enumerate(visible_metrics):
            region_put(service, service.row + 4 + index, model_width + 2,
                       f"{metric.name}: {format_metric(metric)}", "text", service.width - model_width - 4)
    switch = by_region["service_switch"]
    region_put(switch, switch.row, 2, "vLLM  /  WebUI (disabled)", "muted")
    footer = by_region["footer"]
    region_put(footer, footer.row, 0, "↑↓ Models    t Theme    q Quit", "primary")
    return Frame(tuple(cells), regions, minimum)


def _single_line(value: str) -> str:
    """Strip terminal controls, including bidi controls, before any display operation."""
    return "".join(" " if unicodedata.category(char).startswith("C") or char in "\u2028\u2029" else char
                   for char in value)


def _clip(value: str, width: int) -> str:
    """Truncate by terminal cells, keeping combining marks with their base character."""
    result: list[str] = []
    used = 0
    for char in _single_line(value):
        char_width = 0 if unicodedata.combining(char) else (2 if unicodedata.east_asian_width(char) in "WF" else 1)
        if used + char_width > width:
            break
        if used or char_width:
            result.append(char)
        used += char_width
    return "".join(result)
