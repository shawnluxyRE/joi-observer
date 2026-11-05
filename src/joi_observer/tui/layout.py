"""REQ-001 终端容量与纯函数屏幕生成；不持有采集或状态写入端口。

按需求v1.12平分页面，Storage固定三行内容，Docker只绘制可见前缀。
可见容量只影响Frame，不改变完整配置、只读快照或采集状态。
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
import math
import time
import unicodedata

from joi_observer.config import AppConfig
from joi_observer.data.models import Metric, StateSnapshot
from joi_observer.tui import services
from joi_observer.tui.history import HistoryScale
from joi_observer.tui.theme import DEFAULT_THEME


@dataclass(frozen=True)
class TerminalSize:
    """终端字符单元尺寸，columns/rows 均为非负整数，不能使用像素。"""

    columns: int
    rows: int


@dataclass(frozen=True)
class HostInfo:
    """静态设备展示标签与系统发行版本；布局不进行 OS、DNS 或网络探测。

    保留hostname字段兼容调用方；生产由组合根传固定设备标签H3C R5300 G6，
    system为本地读取的Ubuntu发行版本，不能用内核release代替。
    """

    hostname: str
    system: str


@dataclass(frozen=True)
class ViewSelection:
    """不可变的会话选择；theme 为 moonlight/hologram。

    默认 theme 为 hologram；仅由本次应用会话保存。
    默认控制器在非空配置中只返回有效模型 id；空配置返回 None。
    纯渲染兼容外部 None/未知 id 的既有回退，不负责修改控制器选择。
    """

    model_id: str | None = None
    theme: str = DEFAULT_THEME


@dataclass(frozen=True)
class TextCell:
    """一次文字绘制：零基 row/column；role 为语义样式，不嵌入 ANSI 转义。

    text 不得含控制字符、换行或诊断详情；过长文字由布局层按显示宽度
    截断为一行。role 供 REQ-006 映射色彩，不能用文本内容推断故障原因。
    bold是独立字体强调标记，默认False，保留既有构造参数与颜色角色；
    后端逐单元应用，不由坐标、数值内容或颜色角色猜测加粗范围。
    """

    row: int
    column: int
    text: str
    role: str = "text"
    bold: bool = False


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
    theme 为本帧的 moonlight/hologram 颜色标识，来自同一 ViewSelection，
    正常及 too_small 帧均须携带；终端不得从标题文字推断主题。
    """

    cells: tuple[TextCell, ...]
    regions: tuple[Region, ...]
    minimum_size: TerminalSize
    too_small: bool = False
    theme: str = "hologram"


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
    if (type(metric.value) not in (int, float)
            or type(metric.value) is float and not math.isfinite(metric.value)):
        raise ValueError("Metric must contain a finite number")
    # Decimal(int) is exact and avoids both a float conversion and Python's
    # safety limit on int-to-decimal-string conversion for very large integers.
    number = Decimal(metric.value) if type(metric.value) is int else Decimal(str(metric.value))
    value = format(number, "f")
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
    目标右侧最低16行=Host6+Storage6+间距1+Docker外壳3，允许Docker零
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
    monotonic_now: float | None = None,
    history_scales: tuple[HistoryScale, ...] | None = None,
) -> Frame:
    """从只读快照生成屏幕，不采集、不写日志、不更改选择或快照。

    now 必须含时区，直接显示该本机时区的 YYYY-MM-DD HH:MM:SS；不使用
    监控样本时间冒充当前时间。gpu_slots 是本会话已见 GPU object_id 的稳定
    顺序（reader 中 collector='gpu'）；新卡追加，故障或消失不删槽。禁止
    根据模型选择过滤或重排 GPU。以下为v1.12半页布局契约。

    monotonic_now仅用于vLLM历史横轴，None时生产接线使用time.monotonic()；
    显式值须有限非负且与快照history同一时钟域，不能从墙钟now转换得到。
    显式时钟在布局前验证；同域数值原样传给vllm_cells。

    history_scales是应用会话从同一快照计算的冻结尺度元组，原样传给
    vllm_cells；本函数不推进五秒迟降状态。None/空元组/无匹配模型指标时
    按本帧有效历史桶选一次性1/2/5档位，最小1，无隐式跨帧记忆。显式元组
    按model_id+field匹配；重复键、非法upper或匹配上限低于有效峰值抛ValueError。
    固定60秒轴、绝对时间桶和尺度标签遵守vllm_cells契约。

    H为总可绘制高度，L=H//2，U=H-L。header为row0/height2；gpu为row2/
    height(U-2)。目标GPU宽floor((columns-1)*3/5)，间隔1列后右侧取余宽，
    接近参考稿约3:2分区。右侧host为row2/height6，紧接storage为row8/height6
    （内容row10..12共3行），row14留白，docker为row15/height(U-15)。
    service从rowU开始、height(L-2)；service_switch为row(H-2)/height1，
    footer为row(H-1)/height1；两半之外不再额外占行。

    Host增加第四内容行用来把CPU/RAM各自的条置于标签/右侧数值下一行，
    消耗原Host与Storage之间的一行留白，不改变基础最小高度或Docker容量。
    硬件字段按hardware_cells的固定右边缘契约绘制；服务内部采用固定24列
    模型栏、两组统计块及四列指标，按vllm_cells目标契约适配字符行列。
    compose_frame在service.column+27画muted的竖分隔，覆盖服务内部行
    row+1..row+height-2；不覆盖标题或底边，不交给vllm_cells重复绘制。
    面板标题GPU用primary，Host Resources/Storage/Docker/当前服务标题用
    secondary；所有外框与分隔仍用muted。标题不占额外行，不侵入状态槽。

    Storage只画配置前三项，不足3项保留内容空行；失败不以第四项补位。
    Docker内容容量=max(0,U-18)，按配置顺序只画前capacity个容器，余项
    仍保留在配置/快照并由Monitor持续采集。容量零时不画条目或空态；容量
    大于零且未配置容器时在内容区画空态。不作省略号、更多/隐藏数量或放大
    提示，不滚动/分页；少量容器允许留白，不能压缩面板或把余高让给Storage。
    Docker行内容边界L=column+2、R=column+width-2（不含R）。状态槽固定为
    [R-14,R)，生命周期/—/STALE文字都以R为右端；名称从L开始，只能占
    [L,R-15)，状态槽前至少空一格。新鲜且sampled_at非None的Running用
    primary；其余生命周期、未知和STALE用text，绝不用amber。失败原位
    以STALE替换状态，不能同时显示旧生命周期或因短状态扩展名称槽。
    所有内容必须限制在各自region内，禁止越过边框覆盖下半区。

    空值/尚未采集显示 —，真实0显示0，applicable=False显示 N/A；仅 stale
    对象在各自预留状态槽显示 STALE，不展示 sampled_at/history时间、原因
    或任何错误诊断。正常/失败/恢复、不同模型类型共用同样区域高度。
    顶部row0为Joi::Observer，Joi/::/Observer分别secondary/muted/primary。
    Theme为纯状态文字'Theme: Hologram [t]'或'Theme: Moonlight [t]'，primary，
    每种主题按实际显示宽度定位，右端均为全页columns；不画可点击按钮。
    row1的hostname设备标签用text，紧随' / '及system发行版本用muted；合计左区最多
    columns-19-2列，过长按终端宽度裁切，不能覆盖右侧19列时钟及两格间隔。
    时钟muted，以columns为右端，显示传入本机aware墙钟的
    YYYY-MM-DD HH:MM:SS，不强转UTC、不补CST。默认主题Hologram。
    Frame.theme 与 view.theme 一致，包含小窗口分支；不从标题反向推断主题。
    底部切换位单独绘制当前 vLLM（primary），分隔符与 WebUI (disabled)
    为 muted；不新增焦点或可切换入口。从 services.VLLM_SERVICE
    读取一次当前服务描述，title 用于服务标题和当前服务项，同一描述传入
    services.footer_text 生成页脚。Select model 属于 vLLM 的
    navigation_label；不能固定为所有服务共用的文字。当前页脚为
    '↑↓ Select model    t Theme    q Quit'，role=primary；箭头、间距及
    t Theme/q Quit 不随服务变化。沿用服务切换位和
    页脚各一行及下半页预算。

    实际尺寸低于 required_size 任一维度时返回 too_small=True，只显示
    'Enlarge terminal to at least {columns}x{rows}' 和 'q Quit'（极小终端可
    裁切可见文字，但 q 事件仍有效）。恢复尺寸自动返回常规 frame。
    所有 TextCell 均须落在 size 范围内；长名称截断，不增加行数。
    REQ-002硬件内容由widgets.hardware_cells在同一组regions中绘制，采用UUID槽、
    inventory面板状态、host/cpu及host/ram字段名和storage/mount-N身份；旧通用
    快照保持只读兼容。其他业务面板由REQ-003～006继续设计。
    """
    if any(type(value) is not int or value < 0 for value in (size.columns, size.rows)):
        raise ValueError("Terminal dimensions must be nonnegative integers")
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Current time must include a timezone")
    if monotonic_now is None:
        monotonic_now = time.monotonic()
    if (type(monotonic_now) not in (int, float)
            or not math.isfinite(monotonic_now) or monotonic_now < 0):
        raise ValueError("History time must be finite and nonnegative")
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
        return Frame(tuple(cells), (), minimum, too_small=True, theme=view.theme)

    lower = size.rows // 2
    upper = size.rows - lower
    left_width = (size.columns - 1) * 3 // 5
    right_column = left_width + 1
    right_width = size.columns - right_column
    regions = (
        Region("header", 0, 0, size.columns, 2),
        Region("gpu", 2, 0, left_width, upper - 2),
        Region("host", 2, right_column, right_width, 6),
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

    current_service = services.VLLM_SERVICE
    for name, title in (("gpu", "GPU"), ("host", "Host Resources"),
                        ("storage", "Storage"), ("docker", "Docker"),
                        ("service", current_service.title)):
        border(by_region[name], title, "primary" if name == "gpu" else "secondary")

    header = by_region["header"]
    region_put(header, 0, 0, "Joi", "secondary")
    region_put(header, 0, 3, "::", "muted")
    region_put(header, 0, 5, "Observer", "primary")
    theme = "Hologram" if view.theme == "hologram" else "Moonlight"
    theme_text = f"Theme: {theme} [t]"
    region_put(header, 0, size.columns - len(theme_text), theme_text, "primary")
    clock_text = now.strftime("%Y-%m-%d %H:%M:%S")
    host_width = size.columns - len(clock_text) - 2
    hostname = _clip(host.hostname, host_width)
    region_put(header, 1, 0, hostname, "text", host_width)
    hostname_width = sum(0 if unicodedata.combining(char) else
                         2 if unicodedata.east_asian_width(char) in "WF" else 1
                         for char in hostname)
    region_put(header, 1, hostname_width, f" / {host.system}", "muted",
               max(0, host_width - hostname_width))
    region_put(header, 1, size.columns - len(clock_text), clock_text, "muted")
    objects = {(obj.key.collector, obj.key.object_id): obj for obj in snapshot.objects}

    # A local import keeps the public Region/TextCell types available to widgets
    # without a module import cycle. Hardware content is drawn exactly once.
    from joi_observer.tui.widgets import hardware_cells

    cells.extend(hardware_cells(snapshot, config, regions, gpu_slots=gpu_slots, view=view))

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
        state = _clip(state, 14)
        state_role = ("primary" if state == "Running" and obj is not None
                      and not obj.stale and obj.sampled_at is not None else "text")
        region_put(docker, row, docker.column + docker.width - 2 - len(state), state, state_role, 14)

    service = by_region["service"]
    from joi_observer.tui.vllm import vllm_cells

    for row in range(service.row + 1, service.row + service.height - 1):
        region_put(service, row, service.column + 27, "│", "muted")
    cells.extend(vllm_cells(snapshot, config, service, view, now=monotonic_now,
                            history_scales=history_scales))
    switch = by_region["service_switch"]
    region_put(switch, switch.row, 2, current_service.title, "primary")
    region_put(switch, switch.row, 2 + len(current_service.title),
               "  /  WebUI (disabled)", "muted")
    footer = by_region["footer"]
    region_put(footer, footer.row, 0, services.footer_text(current_service), "primary")
    return Frame(tuple(cells), regions, minimum, theme=view.theme)


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
