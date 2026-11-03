"""从已计算的只读快照生成 vLLM 服务窗口内容，不访问采集器或状态写接口。

布局边框、服务切换位和键位栏由外层绘制；本模块只产生服务矩形内部的文字。
输入计数、速率、窗口均值均已由状态层确定，视图不进行计数差分或跨采样求和。
"""

from __future__ import annotations

import math

from joi_observer.config import AppConfig, ModelType
from joi_observer.data.models import Metric, ObjectSnapshot, StateSnapshot
from joi_observer.tui.layout import Region, TextCell, ViewSelection, _clip, format_metric


def vllm_cells(
    snapshot: StateSnapshot,
    config: AppConfig,
    region: Region,
    view: ViewSelection,
    *,
    now: float,
) -> tuple[TextCell, ...]:
    """绘制选中模型和全部可见模型条目；返回不可变文字单元，无 I/O。

    region 是包含外边框的 service 区，width>=120、height>=16；row/column
    为非负整数。只绘制其内部，不覆盖边框或外层 service_switch/footer。
    左栏占width//3列，每项两行，容量为(height-2)//2；按配置顺序保留
    能看到选中项的连续窗口。选中id未知或None时回退首项，空配置只显示
    No models configured。首行是名称、类型和状态；次行是RUNNING/WAITING。
    名称单独成格，选中名称role=primary，其他名称role=text。

    右栏起于column+width//3+2，内容右缘column+width-3。相对row的固定槽：
    +1名称/类型/状态，+2路由，+4 RUNNING/WAITING/Total，+6/+7两行双列
    指标，+8 KV槽，+9历史标题，+10..height-3柱图区，height-2相对时间轴。
    更高区域仅扩展柱图区与左栏容量。三类模型、正常/失败、空字段共用槽位。

    只读取ObjectKey('vllm',config.id)；字段名为running/waiting/total、
    decode_rate/prefill_rate/rate、ttft_seconds/queue_seconds/latency_seconds、
    kv_cache_percent。计数单位seq；Chat吞吐tok/s，pooling RATE为seq/s。
    Total直接使用状态字段，不能用保留的running与新waiting重新计算。
    Chat显示DECODE、PREFILL、TTFT、Avg queue、KV CACHE；pooling显示RATE、
    Avg queue、Avg latency，未使用槽写N/A且不出现Chat专用标签。
    None显示—，有效0显示0；applicable=False显示N/A，不能伪造零。

    stale优先显示STALE；只有sampled_at非None、running/waiting均有效、
    对象非stale时才能显示READY或QUEUED。waiting>0显示QUEUED，仅QUEUED
    与此时的正等待值用amber；WAITING标签、0、保留旧等待值均为text。
    缺队列数据保持未知状态—，不能默认READY。主题不改变amber规则。
    路由只展示配置name和base_url，不推断并发上限、TP或额外参数。

    历史只取选中模型、相应主吞吐字段，保留[now-60,now]内的点；now须为
    与HistoryPoint.sampled_at同域的有限非负单调秒数，不能传墙钟datetime。
    无历史写—；可见轴范围从最早保留点到now，少于60秒时标真实已有范围，
    相对秒数使用-s/0s，单点零跨度只标0s。不显示采样绝对时间或故障时长。
    正值用竖柱，零值在基线用·，metrics=None或主字段None为留白缺口。
    时间分箱保留真实先后与间隔；同箱取有效主吞吐最大值，若含缺口则该箱
    留白，不能连线/插值/延续旧值。空白旧区间不补零，失败旧值不画新柱。

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

    cells: list[TextCell] = []
    divider = region.column + region.width // 3
    right = divider + 2
    end = region.column + region.width - 2  # Exclusive content edge.

    def put(offset: int, column: int, text: str, width: int, role: str = "text") -> None:
        text = _clip(text, width)
        if text:
            cells.append(TextCell(region.row + offset, column, text, role))

    if not config.models:
        put(1, region.column + 2, "No models configured", region.width - 4, "muted")
        return tuple(cells)

    objects = {obj.key.object_id: obj for obj in snapshot.objects if obj.key.collector == "vllm"}
    selected = next((index for index, model in enumerate(config.models) if model.id == view.model_id), 0)
    capacity = (region.height - 2) // 2
    first = max(0, selected - capacity + 1)

    def identity(offset: int, start: int, stop: int, model, obj: ObjectSnapshot | None,
                 *, selected_name: bool) -> None:
        # Reserve independent name, type and six-character status slots before
        # clipping names, including on a narrow terminal or with wide glyphs.
        status, role = _status(obj)
        status_column = stop - 6
        type_column = status_column - 13
        put(offset, start, model.name, type_column - start - 1,
            "primary" if selected_name else "text")
        put(offset, type_column, f"[{model.type.value}]", 11, "muted")
        put(offset, status_column, status, 6, role)

    def count(offset: int, start: int, width: int, label: str, name: str,
              obj: ObjectSnapshot | None) -> None:
        put(offset, start, label + ":", width)
        value_start = start + len(label) + 2
        metric = _metric(obj, name, "seq")
        role = "amber" if name == "waiting" and _status(obj)[0] == "QUEUED" else "text"
        put(offset, value_start, format_metric(metric), width - len(label) - 2, role)

    for index in range(first, min(first + capacity, len(config.models))):
        model = config.models[index]
        obj = objects.get(model.id)
        offset = 1 + 2 * (index - first)
        identity(offset, region.column + 2, divider - 1, model, obj, selected_name=index == selected)
        half = (divider - region.column - 3) // 2
        count(offset + 1, region.column + 2, half, "RUNNING", "running", obj)
        count(offset + 1, region.column + 2 + half, divider - region.column - 3 - half,
              "WAITING", "waiting", obj)

    model = config.models[selected]
    obj = objects.get(model.id)
    identity(1, right, end, model, obj, selected_name=True)
    put(2, right, model.base_url, end - right, "secondary")
    count_width = (end - right) // 3
    for index, (label, name) in enumerate((("RUNNING", "running"), ("WAITING", "waiting"), ("Total", "total"))):
        start = right + index * count_width
        count(4, start, count_width if index < 2 else end - start, label, name, obj)

    half = (end - right) // 2

    def detail(offset: int, side: int, label: str, name: str, unit: str) -> None:
        start = right + side * half
        width = half if side == 0 else end - start
        put(offset, start, f"{label}: {format_metric(_metric(obj, name, unit))}", width)

    chat = model.type == ModelType.CHAT
    if chat:
        detail(6, 0, "DECODE", "decode_rate", "tok/s")
        detail(6, 1, "PREFILL", "prefill_rate", "tok/s")
        detail(7, 0, "TTFT", "ttft_seconds", "s")
        detail(7, 1, "Avg queue", "queue_seconds", "s")
        detail(8, 0, "KV CACHE", "kv_cache_percent", "%")
    else:
        detail(6, 0, "RATE", "rate", "seq/s")
        put(6, right + half, "N/A", end - right - half)
        detail(7, 0, "Avg queue", "queue_seconds", "s")
        detail(7, 1, "Avg latency", "latency_seconds", "s")
        put(8, right, "N/A", end - right)
    put(9, right, "DECODE HISTORY / tok/s" if chat else "RATE HISTORY / seq/s", end - right, "secondary")
    cells.extend(_history_cells(obj, "decode_rate" if chat else "rate", region, right, end, now))
    return tuple(cells)


def _metric(obj: ObjectSnapshot | None, name: str, unit: str) -> Metric:
    """Look up only the declared state field, preserving unknown and N/A."""
    return next((metric for metric in obj.metrics if metric.name == name), Metric(name, None, unit)) if obj else Metric(name, None, unit)


def _status(obj: ObjectSnapshot | None) -> tuple[str, str]:
    if obj and obj.stale:
        return "STALE", "text"
    if obj is None or obj.sampled_at is None:
        return "—", "text"
    running, waiting = (_metric(obj, name, "seq") for name in ("running", "waiting"))
    if not running.applicable or not waiting.applicable or running.value is None or waiting.value is None:
        return "—", "text"
    return ("QUEUED", "amber") if waiting.value > 0 else ("READY", "text")


def _history_cells(obj: ObjectSnapshot | None, field: str, region: Region,
                   start: int, end: int, now: float) -> tuple[TextCell, ...]:
    """Bin by elapsed time and render gaps before scaling the remaining bars."""
    history = tuple(point for point in obj.history if now - 60 <= point.sampled_at <= now) if obj else ()
    top, bottom = region.row + 10, region.row + region.height - 3
    if not history:
        return (TextCell(bottom, start, "—", "muted"),)
    earliest = min(point.sampled_at for point in history)
    span = now - earliest
    width = end - start
    bins: dict[int, float | int | None] = {}
    for point in history:
        index = min(width - 1, int((point.sampled_at - earliest) / span * (width - 1))) if span else width - 1
        metric = next((metric for metric in point.metrics if metric.name == field), None) if point.metrics else None
        value = metric.value if metric is not None and metric.applicable else None
        if value is None or index in bins and bins[index] is None:
            bins[index] = None
        else:
            bins[index] = max(bins.get(index, 0), value)
    maximum = max((value for value in bins.values() if value is not None), default=0)
    height = bottom - top + 1
    cells: list[TextCell] = []
    for index, value in bins.items():
        if value is None:
            continue
        if value == 0:
            cells.append(TextCell(bottom, start + index, "·", "primary"))
            continue
        eighths = max(1, math.ceil(value / maximum * height * 8))
        for offset in range(height):
            filled = min(8, max(0, eighths - offset * 8))
            if filled:
                cells.append(TextCell(bottom - offset, start + index, "▁▂▃▄▅▆▇█"[filled - 1], "primary"))
    axis_row = region.row + region.height - 2
    if span:
        cells.append(TextCell(axis_row, start, _clip(f"-{span:g}s", width - 3), "muted"))
    cells.append(TextCell(axis_row, end - 2, "0s", "muted"))
    return tuple(cells)
