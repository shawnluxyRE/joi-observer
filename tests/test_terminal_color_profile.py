"""Terminal initialization must not leak its color profile into the application."""

import os
import sys
from types import SimpleNamespace

import pytest

from joi_observer.tui.app import CursesTerminal


class CursesBoundary:
    class error(Exception):
        pass

    def __init__(self, failure=None, *, cached_colors=None):
        self.failure = failure
        self.cached_colors = cached_colors
        self.events = []
        self.screen = SimpleNamespace(
            keypad=lambda value: self.record("keypad", value),
            nodelay=lambda value: self.record("nodelay", value),
        )

    def record(self, operation, *args):
        self.events.append((operation, os.environ.get("TERM"), args))
        if self.failure and self.failure[0] == operation:
            raise self.failure[1]

    def setupterm(self, *, term, fd):
        self.record("setupterm", term, fd)

    def tigetnum(self, name):
        self.record("tigetnum", name)
        if self.cached_colors is None:
            raise self.error("setupterm has not been called")
        return self.cached_colors

    def initscr(self):
        self.record("initscr")
        return self.screen

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
        self.record("tigetstr", name)
        return None


def install_boundary(monkeypatch, api):
    original_mode = ["original terminal mode"]
    restored = []
    termios = SimpleNamespace(
        TCSANOW=0,
        tcgetattr=lambda fd: original_mode,
        tcsetattr=lambda fd, action, mode: restored.append((fd, action, mode)),
    )
    monkeypatch.setitem(sys.modules, "curses", api)
    monkeypatch.setitem(sys.modules, "termios", termios)
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(fileno=lambda: 11))
    return original_mode, restored


@pytest.mark.parametrize("term", (
    "xterm", "xterm-256color", "linux", "screen-256color", "tmux-256color", "", None,
))
def test_only_plain_xterm_uses_extended_profile_and_environment_is_restored(monkeypatch, term):
    if term is None:
        monkeypatch.delenv("TERM", raising=False)
    else:
        monkeypatch.setenv("TERM", term)
    api = CursesBoundary()
    original_mode, restored = install_boundary(monkeypatch, api)
    terminal = CursesTerminal()
    terminal.enter()
    assert os.environ.get("TERM") == term
    initialized = [event[1] for event in api.events if event[0] == "initscr"]
    assert initialized == ["xterm-256color" if term == "xterm" else term]
    probes = [event for event in api.events if event[0] == "setupterm"]
    assert probes == ([("setupterm", "xterm", ("xterm-256color", 11))] if term == "xterm" else [])
    assert all(event[1] == term for event in api.events if event[0] != "initscr")
    terminal.restore()
    assert os.environ.get("TERM") == term
    assert restored == [(11, 0, original_mode)]


def test_missing_extended_entry_falls_back_before_screen_initialization(monkeypatch):
    monkeypatch.setenv("TERM", "xterm")
    api = CursesBoundary(("setupterm", CursesBoundary.error("entry unavailable")))
    original_mode, restored = install_boundary(monkeypatch, api)
    terminal = CursesTerminal()
    terminal.enter()
    assert [event[1] for event in api.events if event[0] == "initscr"] == ["xterm"]
    assert all(event[1] == "xterm" for event in api.events)
    terminal.restore()
    assert os.environ["TERM"] == "xterm"
    assert restored == [(11, 0, original_mode)]


@pytest.mark.parametrize("colors", (-1, 8, 16))
def test_existing_low_color_description_is_not_mistaken_for_extended_profile(monkeypatch, colors):
    monkeypatch.setenv("TERM", "xterm")
    api = CursesBoundary(("setupterm", AssertionError("must not trust cached setupterm")),
                         cached_colors=colors)
    install_boundary(monkeypatch, api)
    terminal = CursesTerminal()
    terminal.enter()
    assert [event[1] for event in api.events if event[0] == "initscr"] == ["xterm"]
    assert not any(event[0] == "setupterm" for event in api.events)
    terminal.restore()
    assert os.environ["TERM"] == "xterm"


@pytest.mark.parametrize("operation,exception", (
    ("setupterm", RuntimeError("probe failure")),
    ("initscr", CursesBoundary.error("screen failure")),
    ("initscr", RuntimeError("unexpected screen failure")),
    ("initscr", KeyboardInterrupt()),
    ("cbreak", CursesBoundary.error("terminal mode failure")),
))
def test_initialization_failure_restores_environment_and_terminal_mode(monkeypatch, operation, exception):
    monkeypatch.setenv("TERM", "xterm")
    api = CursesBoundary((operation, exception))
    original_mode, restored = install_boundary(monkeypatch, api)
    terminal = CursesTerminal()
    with pytest.raises(type(exception)):
        terminal.enter()
    assert os.environ["TERM"] == "xterm"
    terminal.restore()
    assert restored == [(11, 0, original_mode)]
    assert ("endwin", "xterm", ()) in api.events


def test_same_terminal_can_reenter_without_leaking_extended_profile(monkeypatch):
    monkeypatch.setenv("TERM", "xterm")
    api = CursesBoundary()
    original_mode, restored = install_boundary(monkeypatch, api)
    terminal = CursesTerminal()
    for _ in range(2):
        terminal.enter()
        assert os.environ["TERM"] == "xterm"
        terminal.restore()
    assert [event[1] for event in api.events if event[0] == "initscr"] == ["xterm-256color"] * 2
    assert restored == [(11, 0, original_mode)] * 2
    assert os.environ["TERM"] == "xterm"
