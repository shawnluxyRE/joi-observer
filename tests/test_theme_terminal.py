"""Theme contracts through public APIs and an offline curses boundary.

The recorder substitutes terminal IO, not palette selection or theme behavior.
Assertions inspect fixed color indices, rendered cells, and restoration effects.
"""

from types import SimpleNamespace
import sys

import pytest

from joi_observer.tui.app import CursesTerminal
from joi_observer.tui.layout import Frame, TerminalSize, TextCell
from joi_observer.tui.theme import CursesTheme


ROLES = ("text", "muted", "primary", "secondary", "amber", "track", "brand_shadow")
COMMON_SLOTS = {
    "text": 253, "muted": 247, "amber": 215, "track": 239, "brand_shadow": 243,
}
ACCENT_SLOTS = {
    "hologram": {"primary": 111, "secondary": 170},
    "moonlight": {"primary": 117, "secondary": 183},
}
PALETTE_OPERATIONS = {"can_change_color", "color_content", "init_color"}


class RecordingCurses:
    class error(Exception):
        pass

    COLOR_BLACK, COLOR_BLUE, COLOR_CYAN = 0, 4, 6
    COLOR_MAGENTA, COLOR_WHITE, COLOR_YELLOW = 5, 7, 3
    A_DIM = 1 << 24
    A_BOLD = 1 << 25
    KEY_UP, KEY_DOWN, KEY_LEFT, KEY_RIGHT = 300, 301, 302, 303
    KEY_ENTER, KEY_RESIZE = 304, 305

    def __init__(self, *, colors=256, pairs=256, mutable=True, enabled=True):
        self.COLORS, self.COLOR_PAIRS = colors, pairs
        self.mutable, self.enabled = mutable, enabled
        self.events, self.pairs = [], {}
        self.colors = {index: (index % 1001, (index + 19) % 1001, (index + 37) % 1001)
                       for index in range(colors)}
        self.original = dict(self.colors)
        self.failure = None
        self.screen = RecordingScreen(self.events)

    def record(self, name, *args):
        self.events.append((name, *args))
        if self.failure and self.failure[0] == name:
            remaining = self.failure[1] - 1
            exception = self.failure[2]
            self.failure = (name, remaining, exception) if remaining else None
            if not remaining:
                raise exception

    def has_colors(self):
        self.record("has_colors")
        return self.enabled

    def start_color(self):
        self.record("start_color")

    def can_change_color(self):
        self.record("can_change_color")
        return self.mutable

    def color_content(self, number):
        self.record("color_content", number)
        return self.colors[number]

    def init_color(self, number, red, green, blue):
        self.record("init_color", number, red, green, blue)
        assert 0 <= number < self.COLORS
        assert all(0 <= component <= 1000 for component in (red, green, blue))
        self.colors[number] = (red, green, blue)

    def init_pair(self, number, foreground, background):
        self.record("init_pair", number, foreground, background)
        assert 0 < number < self.COLOR_PAIRS
        assert 0 <= foreground < self.COLORS and 0 <= background < self.COLORS
        self.pairs[number] = (foreground, background)

    def color_pair(self, number):
        self.record("color_pair", number)
        return number << 8

    def pair_for(self, attribute):
        return self.pairs[(attribute & ~(self.A_DIM | self.A_BOLD)) >> 8]

    def setupterm(self, term=None, fd=-1):
        self.record("setupterm", term, fd)

    def initscr(self):
        self.record("initscr")
        return self.screen

    def tigetnum(self, name):
        self.record("tigetnum", name)
        raise self.error("setupterm has not been called")

    def noecho(self):
        self.record("noecho")

    def cbreak(self):
        self.record("cbreak")

    def nocbreak(self):
        self.record("nocbreak")

    def echo(self):
        self.record("echo")

    def endwin(self):
        self.record("endwin")

    def curs_set(self, value):
        self.record("curs_set", value)
        return 1

    def tigetstr(self, name):
        return None

    def use_default_colors(self):
        self.record("use_default_colors")


class RecordingScreen:
    def __init__(self, events):
        self.events = events
        self.background = 0
        self.blank_attribute = 0
        self.drawn = []

    def keypad(self, value):
        self.events.append(("keypad", value))

    def nodelay(self, value):
        self.events.append(("nodelay", value))

    def getmaxyx(self):
        return 40, 120

    def bkgd(self, character, attribute):
        self.events.append(("bkgd", character, attribute))
        self.background = attribute

    def clearok(self, value):
        self.events.append(("clearok", value))

    def erase(self):
        self.events.append(("erase",))
        self.blank_attribute = self.background
        self.drawn.clear()

    def addstr(self, row, column, text, attribute):
        self.events.append(("addstr", row, column, text, attribute))
        self.drawn.append((row, column, text, attribute))

    def refresh(self):
        self.events.append(("refresh",))


@pytest.mark.parametrize("invalid", ("", "Hologram", " moonlight", "hologram ", "neon", None, 0, [], {}))
def test_invalid_palette_names_are_rejected_before_terminal_io(invalid):
    api = RecordingCurses()
    theme = CursesTheme(api)
    with pytest.raises(ValueError):
        theme.activate(invalid)
    assert api.events == []


def test_construct_style_and_repeated_restore_are_inert_before_activation():
    api = RecordingCurses()
    theme = CursesTheme(api)
    assert api.events == []
    assert all(theme.style(role) == 0 for role in (*ROLES, "unknown"))
    theme.restore()
    theme.restore()
    assert api.events == []


@pytest.mark.parametrize("mutable", (True, False))
def test_fixed_colors_are_bounded_and_palette_is_untouched_across_two_switches(mutable):
    api = RecordingCurses(mutable=mutable)
    theme = CursesTheme(api)
    for name in ("hologram", "moonlight", "hologram"):
        theme.activate(name)
        for role in ROLES:
            assert api.pair_for(theme.style(role)) == ((COMMON_SLOTS | ACCENT_SLOTS[name])[role], 233)
        assert not theme.style("muted") & api.A_DIM
        assert not theme.style("secondary") & api.A_BOLD
        assert not theme.style("track") & (api.A_BOLD | api.A_DIM)
        assert theme.style("unknown") == theme.style("text")
        before = tuple(api.events)
        theme.activate(name)
        assert tuple(api.events) == before
    assert set(api.pairs) == set(range(1, 8)) and api.pairs[7] == (243, 233)
    assert sum(event[0] == "start_color" for event in api.events) == 1
    before = tuple(api.events)
    theme.restore()
    assert tuple(api.events) == before
    assert api.colors == api.original
    assert all(theme.style(role) == 0 for role in ROLES)
    before = tuple(api.events)
    theme.restore()
    assert tuple(api.events) == before
    theme.activate("hologram")
    assert sum(event[0] == "start_color" for event in api.events) == 2
    theme.restore()
    assert api.colors == api.original
    assert not any(event[0] in PALETTE_OPERATIONS for event in api.events)


def test_invalid_theme_after_activation_preserves_colors_styles_and_avoids_io():
    api = RecordingCurses()
    theme = CursesTheme(api)
    theme.activate("hologram")
    try:
        colors, pairs = dict(api.colors), dict(api.pairs)
        styles = tuple(theme.style(role) for role in ROLES)
        events = tuple(api.events)
        for invalid in ("Hologram", "", None, []):
            with pytest.raises(ValueError):
                theme.activate(invalid)
            assert tuple(theme.style(role) for role in ROLES) == styles
            assert api.colors == colors and api.pairs == pairs
            assert tuple(api.events) == events
        theme.activate("hologram")
        assert tuple(api.events) == events
    finally:
        theme.restore()


@pytest.mark.parametrize("name,accents", (
    ("hologram", (111, 170)), ("moonlight", (117, 183)),
))
@pytest.mark.parametrize("colors", (256, 512))
@pytest.mark.parametrize("mutable", (False, True))
def test_fixed_256_colors_use_documented_nearest_xterm_slots(name, accents, colors, mutable):
    api = RecordingCurses(colors=colors, mutable=mutable)
    theme = CursesTheme(api)
    theme.activate(name)
    expected = dict(text=253, muted=247, primary=accents[0], secondary=accents[1],
                    amber=215, track=239, brand_shadow=243)
    for role, foreground in expected.items():
        assert api.pair_for(theme.style(role)) == (foreground, 233)
        assert not theme.style(role) & api.A_DIM
        assert not theme.style(role) & api.A_BOLD
    theme.restore()
    assert api.colors == api.original
    assert not any(event[0] in PALETTE_OPERATIONS for event in api.events)


@pytest.mark.parametrize("operation", sorted(PALETTE_OPERATIONS))
@pytest.mark.parametrize("error_type", (RecordingCurses.error, RuntimeError))
def test_palette_capability_queries_and_mutation_are_never_attempted(operation, error_type):
    api = RecordingCurses(mutable=True)
    failure = (operation, 1, error_type("palette API must not be called"))
    api.failure = failure
    theme = CursesTheme(api)
    for name in ("hologram", "moonlight", "hologram"):
        theme.activate(name)
        for role, foreground in (COMMON_SLOTS | ACCENT_SLOTS[name]).items():
            assert api.pair_for(theme.style(role)) == (foreground, 233)
    theme.restore()
    assert api.failure == failure
    assert api.colors == api.original
    assert not any(event[0] in PALETTE_OPERATIONS for event in api.events)


@pytest.mark.parametrize("colors", (8, 16, 88, 255))
def test_basic_colors_keep_theme_accents_distinct_and_share_black_background(colors):
    api = RecordingCurses(colors=colors)
    theme = CursesTheme(api)
    for name, primary in (("hologram", api.COLOR_BLUE), ("moonlight", api.COLOR_CYAN)):
        theme.activate(name)
        expected = dict(text=api.COLOR_WHITE, muted=api.COLOR_WHITE, primary=primary,
                        secondary=api.COLOR_MAGENTA, amber=api.COLOR_YELLOW, track=api.COLOR_BLACK)
        for role, foreground in expected.items():
            assert api.pair_for(theme.style(role)) == (foreground, api.COLOR_BLACK)
        assert theme.style("muted") & api.A_DIM
        assert theme.style("brand_shadow") == theme.style("muted")
        assert not theme.style("text") & api.A_DIM
        assert bool(theme.style("secondary") & api.A_BOLD) == (name == "moonlight")
        assert theme.style("track") & api.A_BOLD
        assert not theme.style("track") & api.A_DIM
        assert theme.style("track") != theme.style("muted")
        assert all(not theme.style(role) & api.A_BOLD for role in ROLES if role not in {"secondary", "track"})
    theme.restore()
    assert not any(event[0] in PALETTE_OPERATIONS for event in api.events)


@pytest.mark.parametrize("settings", (
    {"enabled": False}, {"colors": 0}, {"colors": 7}, {"pairs": 6}, {"pairs": 5}, {"pairs": 0},
))
def test_insufficient_color_capability_preserves_monochrome_operation(settings):
    api = RecordingCurses(**settings)
    theme = CursesTheme(api)
    for name in ("hologram", "moonlight", "hologram"):
        theme.activate(name)
        assert all(theme.style(role) == 0 for role in (*ROLES, "unknown"))
    assert not any(event[0] in ("init_color", "init_pair") for event in api.events)
    events = tuple(api.events)
    with pytest.raises(ValueError, match="Unknown theme"):
        theme.activate("invalid")
    assert tuple(api.events) == events
    theme.restore()


@pytest.mark.parametrize("colors", (8, 256))
@pytest.mark.parametrize("capacity", (7, 8))
def test_brand_shadow_uses_a_spare_fixed_pair_or_falls_back_to_muted(colors, capacity):
    api = RecordingCurses(colors=colors, pairs=capacity)
    theme = CursesTheme(api)
    try:
        theme.activate("moonlight")
        assert all(theme.style(role) != 0 for role in ROLES)
        if colors == 256 and capacity == 8:
            assert set(api.pairs) == set(range(1, 8))
            assert api.pair_for(theme.style("brand_shadow")) == api.pairs[7] == (243, 233)
        else:
            assert set(api.pairs) == set(range(1, 7))
            assert theme.style("brand_shadow") == theme.style("muted")
        assert api.pair_for(theme.style("track")) != api.pair_for(theme.style("muted"))
    finally:
        theme.restore()
    assert api.colors == api.original


@pytest.mark.parametrize("operation,occurrence", (
    ("has_colors", 1), ("start_color", 1),
    ("init_pair", 1), ("color_pair", 1),
    ("init_pair", 3), ("color_pair", 3),
    ("init_pair", 6), ("color_pair", 6), ("init_pair", 7), ("color_pair", 7),
))
def test_curses_errors_clear_partial_styles_and_latch_monochrome(operation, occurrence):
    api = RecordingCurses()
    api.failure = operation, occurrence, api.error("terminal capability failure")
    theme = CursesTheme(api)
    theme.activate("hologram")
    assert api.colors == api.original
    assert all(theme.style(role) == 0 for role in ROLES)
    after_failure = tuple(api.events)
    theme.activate("moonlight")
    assert all(theme.style(role) == 0 for role in ROLES)
    assert tuple(api.events) == after_failure
    with pytest.raises(ValueError, match="Unknown theme"):
        theme.activate("invalid")
    assert tuple(api.events) == after_failure
    theme.restore()
    assert tuple(api.events) == after_failure
    theme.activate("moonlight")
    for role, foreground in (COMMON_SLOTS | ACCENT_SLOTS["moonlight"]).items():
        assert api.pair_for(theme.style(role)) == (foreground, 233)
    theme.restore()
    assert api.colors == api.original
    assert not any(event[0] in PALETTE_OPERATIONS for event in api.events)


def test_programming_errors_are_not_disguised_as_color_degradation():
    api = RecordingCurses()
    api.failure = "start_color", 1, RuntimeError("programming error")
    theme = CursesTheme(api)
    with pytest.raises(RuntimeError, match="programming error"):
        theme.activate("hologram")
    theme.restore()


@pytest.mark.parametrize("settings", ({}, {"colors": 8}, {"enabled": False}))
def test_restore_clears_session_without_terminal_io_and_rechecks_capabilities(settings):
    api = RecordingCurses(**settings)
    theme = CursesTheme(api)
    theme.activate("hologram")
    before = tuple(api.events)
    theme.restore()
    assert tuple(api.events) == before
    assert all(theme.style(role) == 0 for role in ROLES)
    theme.restore()
    assert tuple(api.events) == before
    api.enabled = True
    api.COLORS = 256
    theme.activate("moonlight")
    for role, foreground in (COMMON_SLOTS | ACCENT_SLOTS["moonlight"]).items():
        assert api.pair_for(theme.style(role)) == (foreground, 233)
    theme.restore()
    assert api.colors == api.original
    assert not any(event[0] in PALETTE_OPERATIONS for event in api.events)


def install_terminal_boundary(monkeypatch, api):
    mode = ["original mode"]
    termios = SimpleNamespace(TCSANOW=0, tcgetattr=lambda fd: mode,
                             tcsetattr=lambda fd, when, saved: api.events.append(("tcsetattr", saved)))
    monkeypatch.setitem(sys.modules, "curses", api)
    monkeypatch.setitem(sys.modules, "termios", termios)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(fileno=lambda: 11))


def test_terminal_uses_frame_theme_for_cells_and_blank_background_then_restores(monkeypatch):
    api = RecordingCurses()
    install_terminal_boundary(monkeypatch, api)
    terminal = CursesTerminal()
    terminal.enter()
    try:
        # Deliberately no Theme title: the frame value is the rendering contract.
        cells = tuple(TextCell(index, 2, role, role) for index, role in enumerate(ROLES))
        for name in ("hologram", "moonlight", "hologram"):
            frame = Frame(cells, (), TerminalSize(120, 36), theme=name)
            start = len(api.events)
            terminal.render(frame)
            events = api.events[start:]
            names = [event[0] for event in events]
            assert "bkgd" in names, "Each frame must paint its blank background"
            assert names.index("bkgd") < names.index("erase")
            assert api.pair_for(api.screen.blank_attribute) == (253, 233)
            for _, _, role, attribute in api.screen.drawn:
                assert api.pair_for(attribute) == ((COMMON_SLOTS | ACCENT_SLOTS[name])[role], 233)
            assert [item[:3] for item in api.screen.drawn] == [
                (cell.row, cell.column, cell.text) for cell in cells
            ]
    finally:
        terminal.restore()
    assert api.colors == api.original
    assert not any(event[0] in PALETTE_OPERATIONS for event in api.events)
    assert ("endwin",) in api.events
    assert ("echo",) in api.events and ("tcsetattr", ["original mode"]) in api.events
    before = tuple(api.events)
    terminal.restore()
    assert tuple(api.events) == before


def test_terminal_reentry_reprobes_monochrome_without_old_color_attributes(monkeypatch):
    api = RecordingCurses()
    install_terminal_boundary(monkeypatch, api)
    terminal = CursesTerminal()
    frame = Frame((TextCell(0, 0, "Observer", "primary"),), (), TerminalSize(120, 36))
    terminal.enter()
    terminal.render(frame)
    terminal.restore()
    api.enabled = False
    terminal.enter()
    try:
        terminal.render(frame)
        assert api.screen.blank_attribute == 0
        assert api.screen.drawn == [(0, 0, "Observer", 0)]
    finally:
        terminal.restore()


def test_terminal_color_restore_failure_does_not_block_other_terminal_cleanup(monkeypatch):
    api = RecordingCurses()
    install_terminal_boundary(monkeypatch, api)
    terminal = CursesTerminal()
    terminal.enter()
    try:
        terminal.render(Frame((TextCell(0, 0, "Observer", "primary"),), (), TerminalSize(120, 36)))
        start = len(api.events)

        def failed_theme_restore():
            api.events.append(("theme_restore",))
            raise RuntimeError("theme cleanup failed")

        monkeypatch.setattr(terminal._theme, "restore", failed_theme_restore)
    finally:
        terminal.restore()
    events = api.events[start:]
    assert events[0] == ("theme_restore",)
    assert ("keypad", False) in events and ("nocbreak",) in events
    assert ("curs_set", 1) in events and ("endwin",) in events
    assert ("echo",) in events and ("tcsetattr", ["original mode"]) in events
    assert api.colors == api.original
    assert not any(event[0] in PALETTE_OPERATIONS for event in api.events)
    before = tuple(api.events)
    terminal.restore()
    assert tuple(api.events) == before


@pytest.mark.parametrize("operation", ("init_pair", "color_pair"))
def test_theme_switch_failure_clears_prior_styles_and_latches_monochrome(monkeypatch, operation):
    """A later pair failure must also discard all previously active styles."""
    api = RecordingCurses()
    install_terminal_boundary(monkeypatch, api)
    terminal = CursesTerminal()
    terminal.enter()
    try:
        initial = Frame((TextCell(0, 0, "Theme: Hologram [t]", "primary"),
                         TextCell(1, 0, "a longer prior label", "secondary")),
                        (), TerminalSize(120, 36), theme="hologram")
        terminal.render(initial)
        assert api.screen.blank_attribute != 0
        assert all(attribute != 0 for _, _, _, attribute in api.screen.drawn)

        api.failure = operation, 3, api.error("theme switch failed")
        switched = Frame((TextCell(0, 0, "Theme: Moonlight [t]", "primary"),
                          TextCell(1, 0, "short", "secondary")),
                         (), TerminalSize(120, 36), theme="moonlight")
        terminal.render(switched)
        assert api.colors == api.original
        assert api.screen.blank_attribute == 0
        assert api.screen.drawn == [(cell.row, cell.column, cell.text, 0)
                                    for cell in switched.cells]

        # Theme metadata can keep changing, but this enter/restore session
        # must not retry partially failed color initialization on later frames.
        after_failure = len(api.events)
        terminal.render(initial)
        assert api.screen.blank_attribute == 0
        assert api.screen.drawn == [(cell.row, cell.column, cell.text, 0)
                                    for cell in initial.cells]
        color_operations = {"has_colors", "start_color", "can_change_color",
                            "color_content", "init_color", "init_pair", "color_pair"}
        assert not any(event[0] in color_operations for event in api.events[after_failure:])
    finally:
        terminal.restore()
    assert api.colors == api.original
    assert ("echo",) in api.events
    assert ("endwin",) in api.events
    assert ("tcsetattr", ["original mode"]) in api.events


@pytest.mark.parametrize("too_small", (False, True))
def test_theme_transition_invalidates_physical_screen_but_same_theme_does_not(monkeypatch, too_small):
    api = RecordingCurses()
    install_terminal_boundary(monkeypatch, api)
    terminal = CursesTerminal()
    cells = (TextCell(1, 0, "unchanged label", "secondary"),)
    terminal.enter()
    try:
        previous = None
        for name in ("hologram", "hologram", "moonlight", "moonlight", "hologram"):
            start = len(api.events)
            terminal.render(Frame(cells, (), TerminalSize(120, 36), too_small, name))
            events = api.events[start:]
            invalidations = [event for event in events if event[0] == "clearok"]
            assert invalidations == ([("clearok", True)] if previous and name != previous else [])
            if invalidations:
                operations = [event[0] for event in events]
                assert operations.index("init_pair") < operations.index("clearok")
                assert operations.index("clearok") < operations.index("bkgd") < operations.index("erase")
            previous = name
    finally:
        terminal.restore()


def test_failed_refresh_keeps_theme_transition_pending_for_retry(monkeypatch):
    api = RecordingCurses()
    install_terminal_boundary(monkeypatch, api)
    terminal = CursesTerminal()
    cells = (TextCell(1, 0, "same text", "secondary"),)
    terminal.enter()
    try:
        terminal.render(Frame(cells, (), TerminalSize(120, 36), theme="hologram"))
        frame = Frame(cells, (), TerminalSize(120, 36), theme="moonlight")

        def failed_refresh():
            raise api.error("flush interrupted")

        with monkeypatch.context() as patch:
            patch.setattr(api.screen, "refresh", failed_refresh)
            with pytest.raises(api.error, match="flush interrupted"):
                terminal.render(frame)
        start = len(api.events)
        terminal.render(frame)
        assert ("clearok", True) in api.events[start:]
        start = len(api.events)
        terminal.render(frame)
        assert ("clearok", True) not in api.events[start:]
    finally:
        terminal.restore()


def test_reentry_discards_the_previous_sessions_rendered_theme(monkeypatch):
    api = RecordingCurses()
    install_terminal_boundary(monkeypatch, api)
    terminal = CursesTerminal()
    terminal.enter()
    terminal.render(Frame((), (), TerminalSize(120, 36), theme="moonlight"))
    terminal.restore()
    start = len(api.events)
    terminal.enter()
    try:
        terminal.render(Frame((), (), TerminalSize(120, 36), theme="hologram"))
        assert not any(event[0] == "clearok" for event in api.events[start:])
    finally:
        terminal.restore()


def test_resize_aborted_theme_switch_keeps_physical_redraw_pending(monkeypatch):
    """An abandoned draw must not count as a successfully presented theme."""
    api = RecordingCurses()
    install_terminal_boundary(monkeypatch, api)
    terminal = CursesTerminal()
    cells = (TextCell(1, 0, "same text", "secondary"),)
    terminal.enter()
    try:
        terminal.render(Frame(cells, (), TerminalSize(120, 36), theme="hologram"))
        switched = Frame(cells, (), TerminalSize(120, 36), theme="moonlight")
        physical_size = [40, 120]

        def resized_addstr(row, column, text, attribute):
            physical_size[:] = [24, 80]
            raise api.error("terminal resized during draw")

        start = len(api.events)
        with monkeypatch.context() as patch:
            patch.setattr(api.screen, "getmaxyx", lambda: tuple(physical_size))
            patch.setattr(api.screen, "addstr", resized_addstr)
            terminal.render(switched)
        aborted = api.events[start:]
        assert ("clearok", True) in aborted
        assert ("refresh",) not in aborted

        start = len(api.events)
        terminal.render(switched)
        retried = api.events[start:]
        assert ("clearok", True) in retried
        assert retried.index(("clearok", True)) < retried.index(("refresh",))
        assert [drawn[:3] for drawn in api.screen.drawn] == [
            (cell.row, cell.column, cell.text) for cell in cells
        ]
        assert api.pair_for(api.screen.drawn[0][3]) == (183, 233)

        start = len(api.events)
        terminal.render(switched)
        assert ("clearok", True) not in api.events[start:]
        assert ("refresh",) in api.events[start:]
    finally:
        terminal.restore()
    assert api.colors == api.original
    assert ("echo",) in api.events
    assert ("endwin",) in api.events
    assert ("tcsetattr", ["original mode"]) in api.events


@pytest.mark.parametrize("enabled", (True, False), ids=("color", "monochrome"))
def test_cell_bold_preserves_color_pairs_and_does_not_leak_to_following_text(monkeypatch, enabled):
    api = RecordingCurses(enabled=enabled)
    install_terminal_boundary(monkeypatch, api)
    terminal = CursesTerminal()
    cells = (
        TextCell(0, 0, "RUNNING", "text"),
        TextCell(0, 12, "3", "text", bold=True),
        TextCell(1, 0, "WAITING", "text"),
        TextCell(1, 12, "7", "amber", bold=True),
        TextCell(2, 0, "Total 10 seq", "muted"),
    )
    assert cells[0].bold is False  # Existing four-position construction remains normal.
    terminal.enter()
    try:
        terminal.render(Frame(cells, (), TerminalSize(120, 36)))
        assert [item[:3] for item in api.screen.drawn] == [
            (cell.row, cell.column, cell.text) for cell in cells
        ]
        for cell, (_, _, _, attribute) in zip(cells, api.screen.drawn):
            assert bool(attribute & api.A_BOLD) is cell.bold
            if enabled:
                assert api.pair_for(attribute) == (COMMON_SLOTS[cell.role], 233)
            else:
                assert attribute == (api.A_BOLD if cell.bold else 0)
        assert not api.screen.blank_attribute & api.A_BOLD
    finally:
        terminal.restore()
    assert api.colors == api.original
