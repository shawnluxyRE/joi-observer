"""REQ-001 终端生命周期与只读刷新；不启动采集。"""

import asyncio
from collections.abc import Callable
from datetime import datetime
import math
import sys
from typing import Protocol

from joi_observer.config import AppConfig
from joi_observer.data.models import StateSnapshot
from joi_observer.tui.layout import Frame, HostInfo, TerminalSize, ViewSelection, compose_frame


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
    """REQ-005/006 的展示操作边界，不允许持有Collector或触发采集。"""

    def selection(self) -> ViewSelection:
        """返回当前模型/主题；默认 Moonlight，首个配置模型。"""
        ...

    def on_key(self, key: str) -> None:
        """接收 t/up/down/left/right；只更新会话选择，首版左右不能进入WebUI。"""
        ...


class CursesTerminal:
    """Ubuntu curses 后端。构造无I/O，curses仅在enter中延迟导入。

    这样Windows可离线导入骨架和运行测试；正式运行仍以Ubuntu24.04为目标。
    enter须保存终端状态；restore在finally中恢复。关闭ncurses的同步序列
    判别，用非阻塞getch读字节，再以私有有界前缀状态异步解析方向键。
    不完整序列跨read_key调用保留，但不会阻塞事件循环或无限积累。
    色彩角色细节留REQ-006；不能把全屏异常送到logging或stderr。
    """

    def __init__(self) -> None:
        self._screen = None
        self._curses = None
        self._termios = None
        self._terminal_mode = None
        self._fd = None
        self._cursor = None
        self._styles: dict[str, int] = {}
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
        self._fd = sys.stdin.fileno()
        self._terminal_mode = termios.tcgetattr(self._fd)
        self._screen = curses.initscr()
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
        if curses.has_colors():
            curses.start_color()
            try:
                curses.use_default_colors()
            except curses.error:
                pass
            for pair, (role, color) in enumerate((("primary", curses.COLOR_CYAN),
                                                  ("secondary", curses.COLOR_MAGENTA),
                                                  ("muted", curses.COLOR_WHITE),
                                                  ("text", curses.COLOR_WHITE)), 1):
                curses.init_pair(pair, color, curses.COLOR_BLACK)
                self._styles[role] = curses.color_pair(pair)
            self._styles["muted"] |= curses.A_DIM

    def restore(self) -> None:
        """实现 TerminalPort.restore；幂等且不打印诊断。"""
        screen, curses = self._screen, self._curses
        self._screen = None
        self._input_prefix = b""
        self._input_expires = 0.0
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
        """实现 TerminalPort.render；控制字符必须在布局边界处理。"""
        if self._screen is None:
            raise RuntimeError("Terminal is not active")
        before = self.size()
        self._screen.erase()
        for cell in frame.cells:
            try:
                self._screen.addstr(cell.row, cell.column, cell.text, self._styles.get(cell.role, 0))
            except self._curses.error:
                # ncurses also reports ERR after successfully painting the
                # lower-right cell; that cell is outside our regular content.
                if self.size() != before:
                    return
                if cell.row == before.rows - 1 and cell.column + len(cell.text) >= before.columns:
                    continue
                raise
        self._screen.refresh()

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

    构造只保留依赖，不读取状态、不进入终端、不采集。没有actions时使用
    首个模型和Moonlight初值；t/方向键交给后续展示实现。终端和时钟在测试中
    可替换，监控指标和STALE渲染必须使用真实compose_frame行为。
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
        self.actions = actions
        self._running = False

    async def run(self) -> None:
        """进入终端，先画初始快照，再刷新/读键，q正常返回。

        键盘轮询最长50ms；绘制正常最多10Hz，快照变化在下个绘制周期展示，
        当前时间至少每秒更新。尺寸变化例外：下一次读键前立即重绘，不受
        普通10Hz节流限制。小窗口仍保持同样读键与监控节奏。t和方向键
        仅送ViewActions，Enter/p不产生行为。UI不调用Monitor或Collector。
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
        last_draw = float("-inf")
        try:
            self.terminal.enter()
            loop = asyncio.get_running_loop()
            while True:
                size = self.terminal.size()
                if size != previous_size or loop.time() - last_draw >= 0.1:
                    snapshot = self.reader.snapshot()
                    for obj in snapshot.objects:
                        if obj.key.collector == "gpu" and obj.key.object_id not in gpu_slots:
                            gpu_slots.append(obj.key.object_id)
                    view = self.actions.selection() if self.actions else ViewSelection(
                        self.config.models[0].id if self.config.models else None)
                    frame = compose_frame(snapshot, self.config, size, self.host, self.wall_clock(),
                                          gpu_slots=tuple(gpu_slots), view=view)
                    self.terminal.render(frame)
                    previous_size = size
                    last_draw = loop.time()
                key = await self.terminal.read_key(0.05)
                if key == "q":
                    return
                if key == "interrupt":
                    raise KeyboardInterrupt
                if self.actions and key in {"t", "up", "down", "left", "right"}:
                    self.actions.on_key(key)
        finally:
            original_error = sys.exc_info()[0]
            try:
                self.terminal.restore()
            except BaseException:
                if original_error is None:
                    raise
            finally:
                self._running = False
