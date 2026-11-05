"""UI 帧时钟接口；使用单调秒，不访问终端、采集器或任何外部时钟。"""

import math
from fractions import Fraction

FRAME_RATE = 60
FRAME_INTERVAL = 1 / FRAME_RATE


class FrameSchedule:
    """固定起点的帧节拍；慢帧跳过已逝槽位，不积压补帧。

    start 必须为非负有限 int/float，排除 bool；非法值抛 ValueError。
    构造只保存会话起点和进度，首个截止时间就是 start，首帧立即到期。
    不读取系统时钟，不休眠，不调用采集或执行终端操作。
    """

    def __init__(self, start: float) -> None:
        self._validate_time(start, minimum=0)
        self._start = start
        self._deadline = start
        self._last_advance: float | None = None

    def due(self, now: float) -> bool:
        """只读判断 now 是否达到当前截止时间，相等也为到期。

        now 必须为有限 int/float、非 bool 且不早于 start，否则 ValueError。
        查询不改变任何进度；多次查询可以使用不同先后顺序的合法时间值。
        """
        self._validate_time(now, minimum=self._start)
        return now >= self._deadline

    def timeout(self, now: float) -> float:
        """只读返回距截止时间的非负等待秒数，上限为 0.05 秒。

        等价于 max(0, min(0.05, deadline-now))；已到期返回零，调用者应先
        完成本帧并推进，不能向要求正超时的读键端口传入零。now 的合法性
        与 due 相同；查询既不推进截止时间，也不记录最后推进时刻。
        """
        self._validate_time(now, minimum=self._start)
        if now >= self._deadline:
            return 0.0
        remaining = (self._deadline - Fraction(now) if isinstance(self._deadline, Fraction)
                     else self._deadline - now)
        return float(min(0.05, remaining))

    def advance(self, now: float) -> None:
        """按绘制完成时刻推进到严格晚于 now 的首个原始节拍。

        节拍始终为 start+n/60，不将完成时间重新当作起点。已过期帧不补画；
        同一完成时刻重复调用不得额外跳槽。缩放触发的即时帧也调用本入口，
        若尚未跨越正常截止时间则保持原截止时间，避免紧接着重复绘制。

        now 遵守 due 的有限数值规则，且不得早于上次成功 advance 的时刻。
        非法调用抛 ValueError，原截止时间及上次推进记录均保持不变。正常
        返回 None；模型选择、快照、硬件槽位和采样计划完全独立。
        """
        self._validate_time(now, minimum=self._start)
        if self._last_advance is not None and now < self._last_advance:
            raise ValueError("Frame completion time cannot move backward")
        if now >= self._deadline:
            if now > 2**44:
                # At large clock origins, float spacing can exceed a frame;
                # adding one tick would then never make a later deadline.
                # Keep the same original grid exactly instead of iterating
                # through unrepresentable floats or overflowing now * FRAME_RATE.
                origin = Fraction(self._start)
                tick = (Fraction(now) - origin) * FRAME_RATE // 1 + 1
                self._deadline = origin + Fraction(tick, FRAME_RATE)
                self._last_advance = now
                return
            tick = math.floor((now - self._start) * FRAME_RATE) + 1
            deadline = self._start + tick / FRAME_RATE
            # Correct rounding at representable tick boundaries without
            # accumulating frame-to-frame additions or adding an epsilon.
            while deadline <= now:
                tick += 1
                deadline = self._start + tick / FRAME_RATE
            while tick > 1 and self._start + (tick - 1) / FRAME_RATE > now:
                tick -= 1
                deadline = self._start + tick / FRAME_RATE
            self._deadline = deadline
        self._last_advance = now

    @staticmethod
    def _validate_time(value: float, *, minimum: float) -> None:
        if (type(value) not in (int, float)
                or type(value) is float and not math.isfinite(value)
                or value < minimum):
            raise ValueError("Frame time must be finite and not precede the start")
