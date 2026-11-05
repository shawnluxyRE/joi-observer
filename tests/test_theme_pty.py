"""Theme changes must repaint physical cells, not only ncurses' color table."""

import os
from pathlib import Path
import re
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Requires a local Unix PTY; verified in WSL")


CHILD = r'''
import os, socket, sys
from joi_observer.tui.app import CursesTerminal
from joi_observer.tui.layout import Frame, TerminalSize, TextCell

def forbidden(*args, **kwargs):
    raise AssertionError('Theme PTY verification is offline')
socket.getaddrinfo = socket.create_connection = forbidden
socket.socket.connect = socket.socket.connect_ex = forbidden
commands, completed = map(int, sys.argv[1:])
terminal = CursesTerminal()
try:
    terminal.enter()
    cells = (TextCell(0, 0, 'SECONDARY-SENTINEL', 'secondary'),
             TextCell(1, 0, 'PRIMARY-SENTINEL', 'primary'),
             TextCell(2, 0, 'BODY-SENTINEL', 'text'),
             TextCell(3, 0, 'TRACK-SENTINEL', 'track'),
             TextCell(4, 0, 'MUTED-SENTINEL', 'muted'),
             TextCell(5, 0, 'AFTER-TRACK-SENTINEL', 'text'))
    for theme in ('hologram', 'moonlight', 'moonlight', 'hologram'):
        terminal.render(Frame(cells, (), TerminalSize(120, 36), theme=theme))
        os.write(completed, b'r')
        if os.read(commands, 1) != b'n':
            raise AssertionError('Parent closed the frame handshake')
finally:
    terminal.restore()
'''


@pytest.mark.parametrize("term", ("xterm", "xterm-256color"))
def test_theme_switch_repaints_unchanged_text_after_palette_update_but_same_theme_does_not(term):
    import fcntl
    import pty
    import select
    import struct
    import termios

    master, slave = pty.openpty()
    fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 36, 120, 0, 0))
    original = termios.tcgetattr(slave)
    commands_r, commands_w = os.pipe()
    completed_r, completed_w = os.pipe()
    env = dict(os.environ, TERM=term, LANG="C.UTF-8",
               PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    child = subprocess.Popen([sys.executable, "-c", CHILD, str(commands_r), str(completed_w)],
                             stdin=slave, stdout=slave, stderr=slave, env=env,
                             pass_fds=(commands_r, completed_w))
    os.close(commands_r)
    os.close(completed_w)

    def drain():
        result = bytearray()
        while select.select([master], [], [], 0.01)[0]:
            try:
                result.extend(os.read(master, 65536))
            except OSError:
                break
        return bytes(result)

    frames = []
    try:
        for _ in range(4):
            assert select.select([completed_r], [], [], 5)[0], drain()
            assert os.read(completed_r, 1) == b"r", drain()
            frames.append(drain())
            os.write(commands_w, b"n")
        child.wait(timeout=5)
        restored_output = drain()
        assert child.returncode == 0, restored_output
        assert termios.tcgetattr(slave) == original

        sentinels = (b"SECONDARY-SENTINEL", b"PRIMARY-SENTINEL", b"BODY-SENTINEL",
                     b"TRACK-SENTINEL", b"MUTED-SENTINEL", b"AFTER-TRACK-SENTINEL")
        for frame, expected, bold in ((frames[1], (198, 167, 255), True),
                                      (frames[3], (229, 112, 208), False)):
            for text in sentinels:
                assert text in frame, f"Theme changed its color table without repainting {text!r}: {frame!r}"
            if term == "xterm-256color":
                changes = list(re.finditer(rb"\x1b\]4;\d+;rgb:([0-9A-F]{2})/([0-9A-F]{2})/([0-9A-F]{2})\x1b\\", frame))
                # ncurses' byte -> 0..1000 -> terminfo byte conversion can lose
                # one level. This does not justify changing the design RGB.
                secondary = next((change for change in changes if all(
                    abs(int(channel, 16) - target) <= 1 for channel, target in zip(change.groups(), expected)
                )), None)
                assert secondary is not None, frame
                assert secondary.end() < frame.index(b"SECONDARY-SENTINEL"), frame
                for expected_rgb, text in (((62, 74, 91), b"TRACK-SENTINEL"),
                                           ((138, 157, 181), b"MUTED-SENTINEL")):
                    color = next((change for change in changes if all(
                        abs(int(channel, 16) - target) <= 1
                        for channel, target in zip(change.groups(), expected_rgb)
                    )), None)
                    assert color is not None and color.end() < frame.index(text), frame
            else:
                # Check the actual SGR state immediately before each physical
                # write. Basic Moonlight uses bold magenta, while Hologram and
                # following primary/body text do not inherit the extra bold.
                def sgr_before(text):
                    bright, dim, foreground = False, False, None
                    for match in re.finditer(rb"\x1b\[([0-9;]*)m", frame[:frame.index(text)]):
                        for code in (int(value or b"0") for value in match[1].split(b";")):
                            if code == 0:
                                bright, dim, foreground = False, False, None
                            elif code == 1:
                                bright = True
                            elif code == 2:
                                dim = True
                            elif code == 22:
                                bright, dim = False, False
                            elif 30 <= code <= 37:
                                foreground = code - 30
                    return bright, dim, foreground

                assert sgr_before(b"SECONDARY-SENTINEL") == (bold, False, 5), frame
                assert sgr_before(b"PRIMARY-SENTINEL")[:2] == (False, False), frame
                assert sgr_before(b"BODY-SENTINEL") == (False, False, 7), frame
                assert sgr_before(b"TRACK-SENTINEL") == (True, False, 0), frame
                assert sgr_before(b"MUTED-SENTINEL") == (False, True, 7), frame
                assert sgr_before(b"AFTER-TRACK-SENTINEL") == (False, False, 7), frame
                assert b"\x1b]4;" not in frame
        assert all(text not in frames[2] for text in sentinels)
        assert b"\x1b[2J" not in frames[2] and b"\x1b]4;" not in frames[2]
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        for fd in (master, slave, commands_w, completed_r):
            os.close(fd)
