"""终端主题值与配色适配边界；不读取指标、配置文件或用户偏好。

配色会话使用终端已有色号，管理色对、能力降级和会话恢复，不修改调色板。
"""

from dataclasses import dataclass
from typing import Any


DEFAULT_THEME = "hologram"
RGB = tuple[int, int, int]


@dataclass(frozen=True)
class Palette:
    """不可变颜色值；RGB 是三个 0..255 的整数，不是 curses 的 0..1000。

    name 为小写主题标识。前景角色共用 background；amber 只供绘制层
    已判定的新鲜正等待数量与 QUEUED 使用，不在此层检查文字或监控状态。
    track 是硬件未填充分段的独立深灰，末尾默认值兼容旧七参数构造。
    """

    name: str
    background: RGB
    text: RGB
    muted: RGB
    primary: RGB
    secondary: RGB
    amber: RGB
    track: RGB = (62, 74, 91)
    brand_shadow: RGB = (118, 118, 118)


def palette_for(name: str) -> Palette:
    """纯查询主题，不初始化终端，无 I/O；只接受 hologram / moonlight。

    公共 background/text/muted/amber 分别为 #080E18/#D4DDEB/#8A9DB5/#FFA45B；
    track 为硬件未填充段的 #3E4A5B，brand_shadow 为像素品牌影线的 #767676。
    Hologram primary/secondary 为 #7B9FFF/#E570D0，Moonlight 为
    #7DDFFF/#C6A7FF。未知名称（含大小写变体、空白、非字符串）抛 ValueError，
    不静默回退，以免标题和实际颜色不一致。返回值不共享可变容器。
    """
    if not isinstance(name, str) or name not in ("hologram", "moonlight"):
        raise ValueError("Unknown theme")
    primary, secondary = ((123, 159, 255), (229, 112, 208)) if name == "hologram" else (
        (125, 223, 255), (198, 167, 255)
    )
    return Palette(name, (8, 14, 24), (212, 221, 235), (138, 157, 181),
                   primary, secondary, (255, 164, 91))


_ROLES = ("text", "muted", "primary", "secondary", "amber", "track")
_BRAND_SHADOW_PAIR = 7


def _nearest_xterm(rgb: RGB, *, gray_only: bool = False) -> int:
    """Find the closest fixed color, using only the gray ramp for neutral roles."""
    levels = (0, 95, 135, 175, 215, 255)
    colors = ((16 + red * 36 + green * 6 + blue,
               (levels[red], levels[green], levels[blue]))
              for red in range(6) for green in range(6) for blue in range(6))
    gray_ramp = ((232 + step, (8 + 10 * step,) * 3) for step in range(24))
    candidates = gray_ramp if gray_only else (*colors, *gray_ramp)
    return min(candidates, key=lambda item: (
        sum((actual - target) ** 2 for actual, target in zip(item[1], rgb)), item[0]
    ))[0]


class CursesTheme:
    """会话内配色资源的唯一所有者；注入标准 curses 模块或离线替身。

    构造仅保存依赖。调用者先 initscr，再 activate；restore 在 endwin 前。
    不导入 curses、不执行终端输入、不改模型选择、不保存文件、不记录日志。
    """

    def __init__(self, curses_api: Any) -> None:
        self._curses = curses_api
        self._mode: str | None = None
        self._name: str | None = None
        self._styles: dict[str, int] = {}

    def activate(self, name: str) -> None:
        """为本帧启用主题；先校验名称，再在首次激活时探测终端颜色能力。

        支持颜色时 start_color 一次。COLORS>=256、COLOR_PAIRS>=7 时统一在
        标准xterm色表中按RGB平方距离选最近色，同距取较小索引。次要文字
        muted及像素品牌影线使用232..255中性灰阶，其他角色使用16..255。
        不查询或修改调色板，也不以 can_change_color 的能力声明选择改色路径。
        色对共享背景，固定色不额外加 A_DIM/A_BOLD。六个基础角色使用色对1..6。
        固定256色且色对7可用时，用它显示243号品牌影线；否则影线复用muted。

        8..255色：背景黑、正文白、次要白加
        A_DIM，主色 Hologram 蓝/Moonlight 青；辅色 Hologram 紫，Moonlight
        使用紫加A_BOLD作为终端亮紫近似，排队黄；track为黑加A_BOLD的亮黑/
        深灰近似。实际RGB及明暗依终端ANSI调色板和bold/dim设置，不能保证
        所有低色终端的视觉差异。不支持颜色、少于8色或色对数不足7时颜色
        属性全0，保留完整文字与操作，不输出提示。

        任一颜色探测/色对初始化发生 curses.error 时清空样式，整次会话降为
        单色，不留下半套样式；未知名称与其他程序异常原样抛出。
        同主题重复激活不重建资源；单色会话也校验名称。restore 后可重新激活。
        """
        palette = palette_for(name)
        if name == self._name or self._mode == "monochrome":
            return
        api = self._curses
        try:
            if self._mode is None:
                if not api.has_colors():
                    self._mode = "monochrome"
                    return
                api.start_color()
                if api.COLORS < 8 or api.COLOR_PAIRS < len(_ROLES) + 1:
                    self._mode = "monochrome"
                    return
                self._mode = "fixed" if api.COLORS >= 256 else "basic"

            if self._mode == "fixed":
                background = _nearest_xterm(palette.background)
                foregrounds = {
                    role: _nearest_xterm(getattr(palette, role), gray_only=role == "muted")
                    for role in _ROLES
                }
            else:
                background = api.COLOR_BLACK
                foregrounds = dict(text=api.COLOR_WHITE, muted=api.COLOR_WHITE,
                                   primary=api.COLOR_BLUE if name == "hologram" else api.COLOR_CYAN,
                                   secondary=api.COLOR_MAGENTA, amber=api.COLOR_YELLOW,
                                   track=api.COLOR_BLACK)
            styles = {}
            for number, role in enumerate(_ROLES, 1):
                api.init_pair(number, foregrounds[role], background)
                styles[role] = api.color_pair(number)
            if self._mode == "basic":
                styles["muted"] |= api.A_DIM
                styles["track"] |= api.A_BOLD
                if name == "moonlight":
                    # Basic-color terminals cannot represent #C6A7FF. The
                    # user-selected approximation is terminal bright magenta;
                    # do not alter TERM or the fixed 256-color palette.
                    styles["secondary"] |= api.A_BOLD
            if self._mode == "fixed" and api.COLOR_PAIRS > _BRAND_SHADOW_PAIR:
                shadow = _nearest_xterm(palette.brand_shadow, gray_only=True)
                api.init_pair(_BRAND_SHADOW_PAIR, shadow, background)
                styles["brand_shadow"] = api.color_pair(_BRAND_SHADOW_PAIR)
            else:
                styles["brand_shadow"] = styles["muted"]
            self._styles = styles
            self._name = name
        except api.error:
            self.restore()
            # A failed capability probe must not be retried on each frame.
            self._mode = "monochrome"

    def style(self, role: str) -> int:
        """返回基础角色或 brand_shadow 的 curses 属性。

        未知角色按 text；未激活或 restore 后为0。不读屏幕或按文字猜角色，
        不进行初始化。调用者用 style('text') 给空白区域设置统一背景。
        """
        return self._styles.get(role, self._styles.get("text", 0))

    def restore(self) -> None:
        """清空样式、能力及主题缓存；调色板从未修改，无需写回色槽。

        未激活、部分激活失败或重复调用均安全，不执行终端 I/O。
        不调用 endwin，也不阻断外层回显/光标/termios 恢复，不输出诊断。
        """
        self._styles.clear()
        self._mode = None
        self._name = None
