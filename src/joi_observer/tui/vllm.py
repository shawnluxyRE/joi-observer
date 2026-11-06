"""从已计算的只读快照生成 vLLM 服务窗口内容，不访问采集器或状态写接口。

布局边框、服务切换位和键位栏由外层绘制；本模块只产生服务矩形内部的文字。
输入计数、速率、窗口均值均已由状态层确定，视图不进行计数差分或跨采样求和。
"""

from __future__ import annotations

import math
from decimal import Decimal
from urllib.parse import urlsplit

from joi_observer.config import AppConfig, ModelType
from joi_observer.data.models import Metric, ObjectSnapshot, StateSnapshot
from joi_observer.tui.history import HistoryScale, _scale_upper, bucket_history
from joi_observer.tui.layout import Region, TextCell, ViewSelection, _clip, format_metric


def vllm_cells(
    snapshot: StateSnapshot,
    config: AppConfig,
    region: Region,
    view: ViewSelection,
    *,
    now: float,
    history_scales: tuple[HistoryScale, ...] | None = None,
) -> tuple[TextCell, ...]:
    """绘制选中模型和全部可见模型条目；返回不可变文字单元，无 I/O。

    region 是包含外边框的 service 区，width>=120、height>=16；row/column
    为非负整数。只绘制其内部，不覆盖边框或外层 service_switch/footer。
    左栏内容固定[column+2,column+26)，分隔线column+27，右详情起于
    L=column+30，止于R=column+width-2（不含）。120列时历史图区宽88。
    左+1行'MODELS / n'为muted；每项3行加1空行，容量(height-2)//4，
    按配置顺序保留含选中项的连续窗口，不因列表数量提高最小窗口高度。
    第i个可见项在+2+4i行，column+2可绘选中›，名称从column+4起；
    名称必须在column+19前结束，column+20起预留6字符READY/QUEUED/STALE，
    槽内文字右对齐到column+26，未知—也贴同一右缘。
    选中名primary，其他名text；状态按各自快照判定，不能因未选中隐藏故障。
    次行大写类型及URL显式端口，如'CHAT / :8000'，muted；无端口只画类型，
    不猜80/443。第三行左槽[column+2,column+14)，右槽[column+15,column+26)，
    中间1空格；'3 running'左齐、'7 waiting'右齐。running数字text、标签muted；
    waiting标签muted，数字仅新鲜正值amber，其他text；无值用—而不是0。
    选中id未知或None回退首项；空配置只显示一次No models configured。

    右+1行留空；+2行模型名和6字符状态槽[R-6,R)，文字右对齐到R，无额外[type]；
    +3只显示所选服务的 :端口，secondary，省略端口时采用协议默认值。
    +4/+8为覆盖[L,R)的muted水平分隔。
    +5行留空，+6是RUNNING/WAITING两组，
    text标签在组内左齐，至少空1列后纯数值在组内右齐；不画大字或ASCII数字。
    不将Total作为第三组。RUNNING数字text，WAITING数字沿用新鲜正值amber规则。
    separator=L+(R-L)//2，左组截止separator-1（不含），右组从separator+2
    起，中间在separator列的+6/+7两行画muted竖分隔。+7左caption从L起为
    'Total {total} seq'，右caption从separator+2起；Chat为'Avg queue {seconds}s'，
    pooling为'Unit: seq'，两边caption全部muted，不越过各自统计组边界。
    +9四等分标签，+10对应值；列间1空格，可用宽R-L-3，前三列宽为其//4，
    最后一列取余。Chat标签DECODE / tok/s、PREFILL / tok/s、TTFT / s、
    KV CACHE / %；pooling为RATE / seq/s、Avg queue / s、Avg latency / s、
    KV CACHE / %（值N/A）。四列标签muted、值text；值仅数字/—/N/A，单位只放标签，所有类型仍显示
    Avg queue。+11行留空，+12历史标题，+13..height-3柱图区，height-2相对时间轴。
    最低height=16时保留1行柱图区；三个空行仅在右详情内容范围内，左栏不移位。
    更高区域仅扩展柱图区与左栏容量。三类模型、正常/失败、空字段共用槽位。
    仅右+6行RUNNING/WAITING及右+10行四指标的真实数值加粗，包括0、科学记数
    和STALE保留旧数；—/N/A/…不加粗。加粗使用TextCell.bold，不改变颜色role；
    左模型栏、caption、标签、状态和历史不增加加粗。

    只读取ObjectKey('vllm',config.id)；字段名为running/waiting/total、
    decode_rate/prefill_rate/rate、ttft_seconds/queue_seconds/latency_seconds、
    kv_cache_percent。计数单位seq；Chat吞吐tok/s，pooling RATE为seq/s。
    Total直接使用状态字段，不能用保留的running与新waiting重新计算。
    Chat显示DECODE、PREFILL、TTFT、Avg queue、KV CACHE；pooling显示RATE、
    Avg queue、Avg latency，KV固定槽只写N/A，不显示TTFT/DECODE/PREFILL。
    None显示—，有效0显示0；applicable=False显示N/A，不能伪造零。
    普通数值保留已有精度；数值超出当前槽时先用最多3有效数字的科学记数，
    保留完整指数，不以裁掉数字尾部的方式伪造更小值。左栏空间不足可将
    running/waiting缩为run/wait；仍放不下则该数值显示明确的…，不侵占标签、
    分隔、其他指标列或状态。该压缩仅属于此视图，不改快照或公共format_metric。

    stale优先显示STALE；只有sampled_at非None、running/waiting均有效、
    对象非stale时才能显示READY或QUEUED。waiting>0显示QUEUED，仅QUEUED
    与此时的正等待值用amber；WAITING标签、0、保留旧等待值均为text。
    缺队列数据保持未知状态—，不能默认READY。主题不改变amber规则。
    路由展示配置的名称和服务端口。

    历史只取选中模型、相应主吞吐字段，保留[now-60,now]内的点；now须为
    与HistoryPoint.sampled_at同域的有限非负单调秒数，不能传墙钟datetime。
    无历史写—；相对时间轴固定-60s/0s，单点/空图也保留两端。短历史只绘制
    真实时间位置、左侧留白，不用earliest..now拉伸；不显示采样绝对时间。
    正值用竖柱，零值在基线用·，metrics=None或主字段None为留白缺口。
    W为可用图区宽度，Δ=60/(W-1)，B=floor(now/Δ)，b=floor(sampled_at/Δ)，
    列=W-1-(B-b)；先按真实闭窗口过滤再分箱，不因浮点误差丢掉合法端点。
    同W/B时旧点横坐标不变，B增加1时统一左移1列；resize才重分箱。当前
    部分桶立即收新点，最旧点过期不拉伸其他点。同箱取有效主吞吐最大值，若含缺口则该箱
    留白，不能连线/插值/延续旧值。空白旧区间不补零，失败旧值不画新柱。

    history_scales是冻结HistoryScale元组，按model_id+field精确匹配主指标。
    None/空/无匹配项时按本帧有效桶峰值选一次性不小于它的1/2/5×10^n上限，
    n非负，最小1；不隐藏维护跨帧状态。显式上限由应用HistoryScaleTracker
    提供，五秒迟降只属于会话控制器。本函数仅消费上限，不能改输入或计时。
    重复(model_id,field)、upper非正int/不是1-2-5档或匹配上限低于当前有效
    桶峰值均抛ValueError；bool不是int。不采用其他模型/字段的上限。极大有限
    吞吐的尺度可超过浮点上限，使用任意精度整数且比例/格式化不能溢出。
    历史标题+12行右侧显示'Scale ≤ {upper} {unit}'，muted、右对齐、保留至少
    一列间隔；普通数值用十进制，超长上限可科学计数，不覆盖左侧标题或加行。
    柱高按真实桶值/上限及已有1/8字符精度绘制；不强制峰值铺满整个高度。
    分桶与即时档位复用history模块；跨帧迟降只由应用会话维护。

    所有文字按终端显示宽度裁成单行，清理控制字符；不得输出诊断、采集
    时间、mock标记、ANSI转义或未声明的原始字段。重复调用不改变snapshot、
    config或view，不更新revision，不使未选中模型停采或清空历史。

    Raises:
        ValueError: region名称/尺寸/原点非法（整数拒bool），或now非有限、
            负数、bool。输入快照和指标的业务合法性由状态层保证。
    """
    dimensions = (region.row, region.column, region.width, region.height)
    if (region.name != "service" or any(type(value) is not int or value < 0 for value in dimensions)
            or region.width < 120 or region.height < 16):
        raise ValueError("Invalid service region")
    if type(now) not in (int, float) or not math.isfinite(now) or now < 0:
        raise ValueError("History time must be finite and nonnegative")

    scales = _validated_scales(history_scales)
    cells: list[TextCell] = []
    right = region.column + 30
    end = region.column + region.width - 2  # Exclusive content edge.

    def put(offset: int, column: int, text: str, width: int, role: str = "text", *, bold: bool = False) -> None:
        text = _clip(text, width)
        if text:
            cells.append(TextCell(region.row + offset, column, text, role, bold=bold))

    if not config.models:
        put(1, region.column + 2, "No models configured", region.width - 4, "muted")
        return tuple(cells)

    objects = {obj.key.object_id: obj for obj in snapshot.objects if obj.key.collector == "vllm"}
    selected = next((index for index, model in enumerate(config.models) if model.id == view.model_id), 0)
    capacity = (region.height - 2) // 4
    first = max(0, selected - capacity + 1)

    def status_at(offset: int, stop: int, obj: ObjectSnapshot | None) -> None:
        status, role = _status(obj)
        put(offset, stop - len(status), status, len(status), role)

    def count_role(name: str, obj: ObjectSnapshot | None) -> str:
        return "amber" if name == "waiting" and _status(obj)[0] == "QUEUED" else "text"

    def rail_count(offset: int, start: int, stop: int, name: str,
                   obj: ObjectSnapshot | None, *, align_right: bool) -> None:
        label = name
        metric = _metric(obj, name, "seq")
        value = _bounded_number(metric, stop - start - len(label) - 1)
        if value == "…":
            label = "run" if name == "running" else "wait"
            value = _bounded_number(metric, stop - start - len(label) - 1)
        column = stop - len(value) - len(label) - 1 if align_right else start
        put(offset, column, value, len(value), count_role(name, obj))
        put(offset, column + len(value) + 1, label, len(label), "muted")

    put(1, region.column + 2, f"MODELS / {len(config.models)}", 24, "muted")
    for index in range(first, min(first + capacity, len(config.models))):
        model = config.models[index]
        obj = objects.get(model.id)
        offset = 2 + 4 * (index - first)
        if index == selected:
            put(offset, region.column + 2, "›", 1, "primary")
        put(offset, region.column + 4, model.name, 15,
            "primary" if index == selected else "text")
        status_at(offset, region.column + 26, obj)
        port = urlsplit(model.base_url).port
        type_text = model.type.value.upper() + (f" / :{port}" if port is not None else "")
        put(offset + 1, region.column + 2, type_text, 24, "muted")
        rail_count(offset + 2, region.column + 2, region.column + 14,
                   "running", obj, align_right=False)
        rail_count(offset + 2, region.column + 15, region.column + 26,
                   "waiting", obj, align_right=True)

    model = config.models[selected]
    obj = objects.get(model.id)
    put(2, right, model.name, end - right - 7, "primary")
    status_at(2, end, obj)
    origin = urlsplit(model.base_url)
    port = origin.port if origin.port is not None else (443 if origin.scheme == "https" else 80)
    put(3, right, f":{port}", end - right, "secondary")
    for offset in (4, 8):
        put(offset, right, "─" * (end - right), end - right, "muted")
    middle = right + (end - right) // 2
    left_end, right_start = middle - 1, middle + 2
    for offset in (6, 7):
        put(offset, middle, "│", 1, "muted")
    for start, stop, name in ((right, left_end, "running"), (right_start, end, "waiting")):
        label = name.upper()
        put(6, start, label, len(label))
        metric = _metric(obj, name, "seq")
        value = _bounded_number(metric, stop - start - len(label) - 1)
        put(6, stop - len(value), value, len(value), count_role(name, obj),
            bold=_visible_number(metric, value))
    total = _bounded_number(_metric(obj, "total", "seq"), left_end - right - len("Total  seq"))
    put(7, right, f"Total {total} seq", left_end - right, "muted")

    chat = model.type == ModelType.CHAT
    if chat:
        queue = _metric(obj, "queue_seconds", "s")
        suffix = "s" if queue.applicable and queue.value is not None else ""
        value = _bounded_number(queue, end - right_start - len("Avg queue ") - len(suffix))
        put(7, right_start, f"Avg queue {value}{suffix}", end - right_start, "muted")
        details = (("DECODE / tok/s", "decode_rate", "tok/s"),
                   ("PREFILL / tok/s", "prefill_rate", "tok/s"),
                   ("TTFT / s", "ttft_seconds", "s"),
                   ("KV CACHE / %", "kv_cache_percent", "%"))
    else:
        put(7, right_start, "Unit: seq", end - right_start, "muted")
        details = (("RATE / seq/s", "rate", "seq/s"),
                   ("Avg queue / s", "queue_seconds", "s"),
                   ("Avg latency / s", "latency_seconds", "s"),
                   ("KV CACHE / %", "kv_cache_percent", "%"))
    column_width = (end - right - 3) // 4
    for index, (label, name, unit) in enumerate(details):
        start = right + index * (column_width + 1)
        width = end - start if index == 3 else column_width
        put(9, start, label, width, "muted")
        metric = _metric(obj, name, unit)
        value = "N/A" if not chat and index == 3 else _bounded_number(metric, width)
        put(10, start, value, width, bold=_visible_number(metric, value))
    cells.extend(_history_cells(obj, model.id, "decode_rate" if chat else "rate",
                                "tok/s" if chat else "seq/s", region, right, end, now, scales))
    return tuple(cells)


def _metric(obj: ObjectSnapshot | None, name: str, unit: str) -> Metric:
    """Look up only the declared state field, preserving unknown and N/A."""
    return next((metric for metric in obj.metrics if metric.name == name), Metric(name, None, unit)) if obj else Metric(name, None, unit)


def _visible_number(metric: Metric, text: str) -> bool:
    """Emphasize actual numeric data, never placeholders or numeric-looking strings."""
    return metric.applicable and type(metric.value) in (int, float) and text not in {"—", "N/A", "…"}


def _status(obj: ObjectSnapshot | None) -> tuple[str, str]:
    if obj and obj.stale:
        return "STALE", "text"
    if obj is None or obj.sampled_at is None:
        return "—", "text"
    running, waiting = (_metric(obj, name, "seq") for name in ("running", "waiting"))
    if not running.applicable or not waiting.applicable or running.value is None or waiting.value is None:
        return "—", "text"
    return ("QUEUED", "amber") if waiting.value > 0 else ("READY", "text")


def _bounded_number(metric: Metric, width: int) -> str:
    """Keep regular precision; compress the whole number before any clipping."""
    plain = format_metric(Metric(metric.name, metric.value, "", metric.applicable))
    if len(plain) <= width:
        return plain
    if metric.applicable and type(metric.value) in (int, float):
        number = Decimal(metric.value) if type(metric.value) is int else Decimal(str(metric.value))
        for precision in (2, 1, 0):
            mantissa, exponent = format(number, f".{precision}E").split("E")
            if "." in mantissa:
                mantissa = mantissa.rstrip("0").rstrip(".")
            compact = f"{mantissa}e{int(exponent)}"
            if len(compact) <= width:
                return compact
    return "…"


def _validated_scales(scales: tuple[HistoryScale, ...] | None) -> dict[tuple[str, str], int]:
    """Validate the entire explicit input, including unselected model entries."""
    result: dict[tuple[str, str], int] = {}
    for scale in scales or ():
        key = (scale.model_id, scale.field)
        upper = scale.upper
        if key in result or type(upper) is not int or upper <= 0:
            raise ValueError("Invalid or duplicate history scale")
        digit = upper
        while digit >= 10 and digit % 10 == 0:
            digit //= 10
        if digit not in (1, 2, 5):
            raise ValueError("History scale must use a 1/2/5 decimal step")
        result[key] = upper
    return result


def _history_cells(obj: ObjectSnapshot | None, model_id: str, field: str, unit: str,
                   region: Region, start: int, end: int, now: float,
                   scales: dict[tuple[str, str], int]) -> tuple[TextCell, ...]:
    """Render stable time buckets against a supplied or one-frame upper bound."""
    history = obj.history if obj else ()
    bins = bucket_history(history, field, now=now, columns=end - start)
    maximum = max((value for value in bins if value is not None), default=0)
    upper = scales.get((model_id, field))
    if upper is None:
        upper = _scale_upper(maximum)
    elif upper < maximum:
        raise ValueError("History scale cannot clip the visible peak")
    title = "DECODE HISTORY / tok/s" if field == "decode_rate" else "RATE HISTORY / seq/s"
    label_width = end - start - len(title) - 1
    number = _bounded_number(Metric("scale", upper), label_width - len("Scale ≤ ") - len(unit) - 1)
    label = f"Scale ≤ {number} {unit}"
    cells = [TextCell(region.row + 12, start, title, "secondary"),
             TextCell(region.row + 12, end - len(label), label, "muted")]
    top, bottom = region.row + 13, region.row + region.height - 3
    height = bottom - top + 1
    if not any(now - 60 <= point.sampled_at <= now for point in history):
        cells.append(TextCell(bottom, start, "—", "muted"))
    for index, value in enumerate(bins):
        if value is None:
            continue
        if value == 0:
            cells.append(TextCell(bottom, start + index, "·", "primary"))
            continue
        # Exact integer ratios avoid float overflow for huge scales and retain
        # a visible eighth-cell for the smallest positive subnormal value.
        numerator, denominator = value.as_integer_ratio() if type(value) is float else (value, 1)
        denominator *= upper
        eighths = max(1, (numerator * height * 8 + denominator - 1) // denominator)
        for offset in range(height):
            filled = min(8, max(0, eighths - offset * 8))
            if filled:
                cells.append(TextCell(bottom - offset, start + index, "▁▂▃▄▅▆▇█"[filled - 1], "primary"))
    axis_row = region.row + region.height - 2
    cells.append(TextCell(axis_row, start, "-60s", "muted"))
    cells.append(TextCell(axis_row, end - 2, "0s", "muted"))
    return tuple(cells)
