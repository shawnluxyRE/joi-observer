"""REQ-001 终端生命周期与只读刷新；不启动采集。"""

import asyncio
from collections.abc import Callable
from datetime import datetime
import math
import os
import sys
from typing import Protocol

from joi_observer.config import AppConfig
from joi_observer.data.models import StateSnapshot
from joi_observer.tui.history import HistoryScaleTracker
from joi_observer.tui.layout import Frame, HostInfo, TerminalSize, ViewSelection, compose_frame, required_size
from joi_observer.tui.navigation import SessionViewActions
from joi_observer.tui.theme import CursesTheme
from joi_observer.tui.timing import FrameSchedule


def _create_screen(curses_api, fd: int):
    """Use extended colors for xterm sessions without changing their environment.

    MobaXterm can advertise plain xterm while supporting indexed 256 colors.
    initscr reads TERM itself, so setupterm alone does not select the profile.
    Keep the override inside this synchronous call; collectors and callers see
    the original TERM even if screen initialization fails.
    """
    original_term = os.environ.get("TERM")
    if original_term != "xterm":
        return curses_api.initscr()

    try:
        cached_colors = curses_api.tigetnum("colors")
    except curses_api.error:
        pass  # No terminal description has been initialized yet.
    else:
        if cached_colors < 256:
            # setupterm can silently reuse an earlier description. Do not let
            # that cache masquerade as a successful extended-profile check.
            return curses_api.initscr()

    profile = "xterm-256color"
    try:
        curses_api.setupterm(term=profile, fd=fd)
    except curses_api.error:
        # A minimal terminfo installation may only contain the original entry.
        return curses_api.initscr()

    os.environ["TERM"] = profile
    try:
        return curses_api.initscr()
    finally:
        os.environ["TERM"] = original_term


class SnapshotReader(Protocol):
    """只提供读取能力；UI 不持有 MonitorState 的写接口。"""

    def snapshot(self) -> StateSnapshot:
        """返回不可变快照；无 I/O；调用不触发任何采样。"""
        ...


class TerminalPort(Protocol):
    """系统终端边界。生产为 curses，测试为内存终端；所有方法仅UI调用。"""

    def enter(self) -> None:
        """保存原终端模式，进入全屏、隐藏光标、关闭输入回显。

        部分初始化失败可抛异常；restore 必须仍能安全调用并尽力恢复。
        不运行采集/外部命令，不打印诊断。一次会话只进入一次。
        """
        ...

    def restore(self) -> None:
        """幂等恢复输入回显、光标与原屏幕；未进入/部分进入时也安全。

        必须尝试所有已取得资源的恢复，即使单项恢复失败；不得输出故障文本。
        Python 可处理的退出需保证调用，SIGKILL/断电不作恢复保证。
        """
        ...

    def size(self) -> TerminalSize:
        """读取当前字符尺寸；每轮重新读取以处理缩放，不改变终端。"""
        ...

    def render(self, frame: Frame) -> None:
        """绘制完整帧并覆盖上一帧残留；只绘制frame，不附加任何文字。

        根据 frame.theme 同步本帧所有语义色与空白背景；小窗口也应用该主题。
        不能往 stdout/stderr 打印诊断。遇缩放造成坐标短暂失效时可放弃本帧，
        下轮重绘；不可吞掉其他内部程序异常。
        """
        ...

    async def read_key(self, timeout: float) -> str | None:
        """在至多 timeout 秒内返回 q/t/up/down/left/right/interrupt 或 None。

        timeout 为正有限秒；不得阻塞事件循环或采样任务；resize通过size感知。
        其他键可原样返回并由应用忽略。支持取消，Ctrl+C映射interrupt或抛
        KeyboardInterrupt。不启用鼠标主题切换，不暴露shell执行入口。
        """
        ...


class ViewActions(Protocol):
    """会话展示操作边界，不允许持有 Collector 或触发采集。

    默认实现为 navigation.SessionViewActions；可显式注入其他实现。
    应用每帧只读取一次 selection，并将同一值用于模型详情和 GPU 关联。
    """

    def selection(self) -> ViewSelection:
        """返回不可变的当前模型/主题；空配置模型为 None，默认 hologram。

        非空配置初始选择首个模型 id。刷新、失败或缩放不改变选择；不能
        由显示名判断身份或自动跳过不可用项。已返回的值保持不变。
        """
        ...

    def on_key(self, key: str) -> None:
        """接收归一化键名；up/down 单步且首尾停留，t 切主题而保留模型。

        left/right 及未声明键无动作；服务固定 vLLM，不进入 WebUI。
        操作不能修改快照、配置、GPU 槽位或采样。q 由应用全局处理。
        """
        ...


class CursesTerminal:
    """Ubuntu curses 后端。构造无I/O，curses仅在enter中延迟导入。

    这样Windows可离线导入模块和运行测试；正式运行仍以Ubuntu24.04为目标。
    enter须保存终端状态；restore在finally中恢复。关闭ncurses的同步序列
    判别，用非阻塞getch读字节，再以私有有界前缀状态异步解析方向键。
    不完整序列跨read_key调用保留，但不会阻塞事件循环或无限积累。
    目标配色委托 theme.CursesTheme，每次 enter 创建独立配色会话；render
    先 activate(frame.theme)，再 bkgd(' ', style('text'))、erase、逐项绘制。
    主题变化时强制重绘物理画面，避免只更新色表而留下终端已缓存的旧色；
    同主题普通帧继续使用curses差分，成功refresh后才记录已显示主题。
    同一帧背景、角色与主题名一致，不启用鼠标；无色/低色终端仍可操作。
    xterm会话仅在初始化期间使用进程内256色描述，随后立即还原TERM；
    不更改Shell或终端设置。配色使用固定色表，restore不改写终端调色板。
    不把全屏异常送到 logging 或 stderr。
    """

    def __init__(self) -> None:
        self._screen = None
        self._curses = None
        self._termios = None
        self._terminal_mode = None
        self._fd = None
        self._cursor = None
        self._theme: CursesTheme | None = None
        self._rendered_theme: str | None = None
        self._input_prefix = b""
        self._input_expires = 0.0
        self._key_sequences: dict[bytes, str] = {}
        self._key_prefixes: set[bytes] = set()

    def enter(self) -> None:
        """实现 TerminalPort.enter；失败后可调用restore。"""
        import curses
        import termios

        self._curses = curses
        self._termios = termios
        self._theme = CursesTheme(curses)
        self._rendered_theme = None
        self._cursor = None
        self._fd = sys.stdin.fileno()
        self._terminal_mode = termios.tcgetattr(self._fd)
        self._screen = _create_screen(curses, self._fd)
        curses.noecho()
        curses.cbreak()
        # nodelay does not disable ncurses' separate ESCDELAY wait when keypad
        # decoding is enabled. Read bytes without that decoder and assemble
        # only our supported keys while yielding to the asyncio loop instead.
        self._screen.keypad(False)
        self._screen.nodelay(True)
        self._input_prefix = b""
        self._input_expires = 0.0
        self._key_sequences = {
            prefix + suffix: key
            for prefix in (b"\x1b[", b"\x1bO")
            for suffix, key in ((b"A", "up"), (b"B", "down"), (b"C", "right"), (b"D", "left"))
        }
        for capability, key in (("kcuu1", "up"), ("kcud1", "down"), ("kcub1", "left"),
                                ("kcuf1", "right"), ("kent", "enter")):
            sequence = curses.tigetstr(capability)
            if sequence:
                self._key_sequences[sequence] = key
        self._key_prefixes = {sequence[:length] for sequence in self._key_sequences
                              for length in range(1, len(sequence))}
        try:
            self._cursor = curses.curs_set(0)
        except curses.error:
            pass  # A terminal without cursor controls can still draw safely.

    def restore(self) -> None:
        """实现 TerminalPort.restore；幂等且不打印诊断。"""
        screen, curses = self._screen, self._curses
        self._screen = None
        self._rendered_theme = None
        self._input_prefix = b""
        self._input_expires = 0.0
        theme, self._theme = self._theme, None
        if theme is not None:
            try:
                theme.restore()
            except Exception:
                pass  # Color cleanup must never prevent terminal restoration.
        if curses is not None and self._terminal_mode is not None:
            # Each restoration is independent: one unavailable feature must not
            # prevent echo or the original terminal screen from being restored.
            operations = (lambda: screen.keypad(False) if screen is not None else None, curses.nocbreak, curses.echo,
                          lambda: curses.curs_set(self._cursor if self._cursor is not None else 1),
                          curses.endwin)
            for operation in operations:
                try:
                    operation()
                except Exception:
                    pass
        if self._terminal_mode is not None:
            mode, self._terminal_mode = self._terminal_mode, None
            try:
                self._termios.tcsetattr(self._fd, self._termios.TCSANOW, mode)
            except Exception:
                pass

    def size(self) -> TerminalSize:
        """实现 TerminalPort.size，返回字符单元而非像素。"""
        if self._screen is None:
            raise RuntimeError("Terminal is not active")
        rows, columns = self._screen.getmaxyx()
        return TerminalSize(columns, rows)

    def render(self, frame: Frame) -> None:
        """实现 TerminalPort.render；控制字符必须在布局边界处理。

        逐单元组合原颜色属性与bold字体标记，不向后续文字泄漏加粗。
        """
        if self._screen is None:
            raise RuntimeError("Terminal is not active")
        before = self.size()
        self._theme.activate(frame.theme)
        if self._rendered_theme is not None and frame.theme != self._rendered_theme:
            # Color-pair IDs are reused across themes. Repaint existing cells
            # when those IDs select different fixed colors.
            self._screen.clearok(True)
        self._screen.bkgd(" ", self._theme.style("text"))
        self._screen.erase()
        for cell in frame.cells:
            try:
                attribute = self._theme.style(cell.role)
                if cell.bold:
                    attribute |= self._curses.A_BOLD
                self._screen.addstr(cell.row, cell.column, cell.text, attribute)
            except self._curses.error:
                # ncurses also reports ERR after successfully painting the
                # lower-right cell; that cell is outside our regular content.
                if self.size() != before:
                    return
                if cell.row == before.rows - 1 and cell.column + len(cell.text) >= before.columns:
                    continue
                raise
        self._screen.refresh()
        self._rendered_theme = frame.theme

    async def read_key(self, timeout: float) -> str | None:
        """实现 TerminalPort.read_key，必须可取消且不阻塞事件循环。"""
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Key timeout must be positive and finite")
        if self._screen is None:
            raise RuntimeError("Terminal is not active")
        loop = asyncio.get_running_loop()
        deadline = loop.time() + min(timeout, 0.05)
        curses = self._curses
        keys = {curses.KEY_UP: "up", curses.KEY_DOWN: "down", curses.KEY_LEFT: "left",
                curses.KEY_RIGHT: "right", curses.KEY_ENTER: "enter"}
        # A ready input stream must not starve sampling or cancellation just
        # because every read could otherwise return without an await.
        await asyncio.sleep(0)
        while True:
            now = loop.time()
            if now >= deadline:
                return None
            if self._input_prefix and now >= self._input_expires:
                self._input_prefix = b""
            key = self._screen.getch()  # nodelay returns -1 without an ESC wait.
            if key != -1:
                if key == curses.KEY_RESIZE:
                    return None
                if key in keys:
                    return keys[key]
                result = self._decode_byte(key, now) if 0 <= key <= 255 else None
                if result is not None:
                    return result
                await asyncio.sleep(0)
                continue
            remaining = deadline - loop.time()
            if self._input_prefix:
                remaining = min(remaining, self._input_expires - loop.time())
            if remaining <= 0:
                continue
            await asyncio.sleep(min(0.01, remaining))

    def _decode_byte(self, value: int, now: float) -> str | None:
        """Consume one byte without waiting; retain only a known key prefix.

        Prefixes expire 50ms after their first byte, independently of any
        individual caller's timeout. Thus short polls can reconstruct fragmented
        arrows without extending their deadlines. Unknown UTF-8 bytes or escape
        prefixes are ignored; the next independent ASCII key is still handled.
        """
        byte = bytes((value,))
        sequence = self._input_prefix + byte
        if sequence in self._key_sequences:
            self._input_prefix = b""
            return self._key_sequences[sequence]
        if sequence in self._key_prefixes:
            if not self._input_prefix:
                self._input_expires = now + 0.05
            self._input_prefix = sequence
            return None
        # A malformed prefix must not swallow a following q/t. Reconsider this
        # final byte on its own, including an ESC that begins a new sequence.
        self._input_prefix = b""
        if byte in self._key_prefixes:
            self._input_prefix = byte
            self._input_expires = now + 0.05
            return None
        if value == 3:
            return "interrupt"
        if value in (10, 13):
            return "enter"
        return chr(value) if 32 <= value < 127 else None


class ObserverApp:
    """全屏会话，依赖仅包含只读状态、终端、本地时钟与展示操作。

    构造只保留依赖，不读取状态、不进入终端、不采集。actions
    为 None 时创建独立的 SessionViewActions(config.models)，显式注入时
    原样使用，不以真假值替代 None 判断；默认控制器贯穿整个应用实例。
    读取选择和分派按键也不得因控制器真假值为 false 而跳过。
    不因刷新、重绘、失败、resize 或再次 run 重建；新应用实例才重置选择。
    同一 ViewSelection 传给整帧，保证详情与 GPU 关联一致。终端和时钟在
    测试中可替换，监控指标和 STALE 渲染必须使用真实 compose_frame。

    本应用持有HistoryScaleTracker(config.models)，从每帧同一次读取的
    快照和单调时间推进全部配置模型尺度，再传冻结元组给compose_frame。
    不因选择/主题/resize/小窗口清空尺度；小窗口以最近有效图区列数继续推进，
    未有有效尺寸时使用最小正常布局的图区宽度。现有选择控制器不持有尺度，
    MonitorState不保存展示状态。再次run沿用本应用尺度和选择，新实例独立。
    帧调度使用timing.FrameSchedule，每次run独立建立截止点。
    """

    def __init__(
        self,
        config: AppConfig,
        reader: SnapshotReader,
        terminal: TerminalPort,
        *,
        host: HostInfo,
        wall_clock: Callable[[], datetime],
        actions: ViewActions | None = None,
    ) -> None:
        self.config = config
        self.reader = reader
        self.terminal = terminal
        self.host = host
        self.wall_clock = wall_clock
        self.actions = SessionViewActions(config.models) if actions is None else actions
        self._history_scales = HistoryScaleTracker(config.models)
        # The service detail starts at c+30, with two columns at the right.
        # Keep the last valid width even while the terminal is too small.
        self._history_columns = required_size(gpu_count=0, mount_count=0, container_count=0).columns - 32
        self._running = False

    async def run(self) -> None:
        """进入终端，先画初始快照，再刷新/读键，q正常返回。

        普通绘制目标60FPS，以会话单调起点+n/60维护截止点。读键等待为下一
        截止点剩余时间与50ms的较小值，不给read_key传非正超时。本轮尚未
        绘制就跨过截止点时，保留到期节拍，下一轮先绘制；不能丢弃待画帧。
        本轮已经绘制后若读键前再次跨点，按同一当前时刻跳到未来节拍并
        提供一次读键机会，不能反复重绘而饿死输入。慢绘制后跳过过期节拍，
        不积压或补画旧帧，不按
        绘制结束时间另起周期。首次和尺寸变化可立即绘制，完成后推进到首个
        未来节拍，防止紧接重复普通帧。当前时间至少每秒更新。小窗口仍保持
        同样读键与监控节奏，并继续更新
        会话选择，放大后显示该选择。t和方向键仅送ViewActions，Enter/p/
        Tab及其他未声明键不产生行为。导航与主题在下一普通绘制周期可见，
        不为按键突破普通帧上限。相同cells/theme/尺寸可省略终端写入；状态或
        长文本缩短时须清除残留，不省略读键、尺度计时或调度。采样仍由Monitor
        按配置独立运行；UI不调用Monitor或Collector。所有模型尺度用本帧同一
        快照与同域now更新，5秒计时按时间而非帧数，compose_frame只读消费。
        新见GPU追加会话槽位；失败恢复不删槽，保证大小与配置不变时布局稳定。

        将enter也置于try/finally保护内；q、KeyboardInterrupt、协程取消及
        render/read错误均调用restore。原异常在恢复后传播给组合根，不打印
        或记录；恢复错误不掩盖原错误。调用者负责停止并发Monitor及日志worker。
        本方法不可重复并发运行；重复并发调用应抛RuntimeError。
        """
        if self._running:
            raise RuntimeError("ObserverApp is already running")
        self._running = True
        gpu_slots: list[str] = []
        previous_size = None
        try:
            self.terminal.enter()
            loop = asyncio.get_running_loop()
            schedule = FrameSchedule(loop.time())
            while True:
                drew_frame = False
                size = self.terminal.size()
                now = loop.time()
                if size != previous_size or schedule.due(now):
                    snapshot = self.reader.snapshot()
                    for obj in snapshot.objects:
                        if obj.key.collector == "gpu" and obj.key.object_id not in gpu_slots:
                            gpu_slots.append(obj.key.object_id)
                    view = self.actions.selection()
                    minimum = required_size(gpu_count=len(gpu_slots),
                                            mount_count=len(self.config.mount_points),
                                            container_count=len(self.config.containers))
                    if size.columns >= minimum.columns and size.rows >= minimum.rows:
                        self._history_columns = size.columns - 32
                    scales = self._history_scales.update(snapshot, now=now,
                                                         columns=self._history_columns)
                    frame = compose_frame(snapshot, self.config, size, self.host, self.wall_clock(),
                                          gpu_slots=tuple(gpu_slots), view=view,
                                          monotonic_now=now, history_scales=scales)
                    self.terminal.render(frame)
                    drew_frame = True
                    previous_size = size
                    schedule.advance(loop.time())
                read_now = loop.time()
                timeout = schedule.timeout(read_now)
                if timeout <= 0:
                    if not drew_frame:
                        # A deadline reached during input bookkeeping still
                        # owes a frame. Keep it due for the next loop instead
                        # of discarding unrendered slots under periodic input.
                        await asyncio.sleep(0)
                        continue
                    # Bookkeeping may cross the tick chosen at draw completion.
                    # Skip that expired slot, then service input before drawing
                    # again. Use one clock observation for both operations so
                    # repeated deadline crossings cannot bypass read_key.
                    schedule.advance(read_now)
                    timeout = schedule.timeout(read_now)
                key = await self.terminal.read_key(timeout)
                if key == "q":
                    return
                if key == "interrupt":
                    raise KeyboardInterrupt
                if key in {"t", "up", "down", "left", "right"}:
                    self.actions.on_key(key)
                # Injected input ports may return ready keys without yielding.
                await asyncio.sleep(0)
        finally:
            original_error = sys.exc_info()[0]
            try:
                self.terminal.restore()
            except BaseException:
                if original_error is None:
                    raise
            finally:
                self._running = False
