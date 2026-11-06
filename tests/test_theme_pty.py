"""Fixed-palette output, theme changes and re-entry through a real local PTY."""

import os
from pathlib import Path
import re
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Requires a local Unix PTY; verified in WSL")


CHILD = r'''
import curses, os, socket, sys
from joi_observer.tui.app import CursesTerminal
from joi_observer.tui.layout import Frame, TerminalSize, TextCell

def forbidden(*args, **kwargs):
    raise AssertionError('Theme PTY verification is offline')
socket.getaddrinfo = socket.create_connection = forbidden
socket.socket.connect = socket.socket.connect_ex = forbidden

def forbidden_palette_write(*args, **kwargs):
    raise AssertionError('Fixed palettes must not redefine terminal colors')
curses.init_color = forbidden_palette_write

commands, completed = map(int, sys.argv[1:])
original_term = os.environ.get('TERM')
terminal = CursesTerminal()
cells = (TextCell(0, 0, 'SECONDARY-SENTINEL', 'secondary'),
         TextCell(1, 0, 'PRIMARY-SENTINEL', 'primary'),
         TextCell(2, 0, 'BODY-SENTINEL', 'text'),
         TextCell(3, 0, 'TRACK-SENTINEL', 'track'),
         TextCell(4, 0, 'MUTED-SENTINEL', 'muted'),
         TextCell(5, 0, 'AFTER-TRACK-SENTINEL', 'text'),
         TextCell(6, 0, 'AMBER-SENTINEL', 'amber'))

def acknowledge(marker):
    os.write(completed, marker)
    if os.read(commands, 1) != b'n':
        raise AssertionError('Parent closed the frame handshake')

# The second session uses the same terminal object and process. Both initial
# xterm and xterm-256color must work without a shell TERM command prefix.
for _ in range(2):
    try:
        terminal.enter()
        assert os.environ.get('TERM') == original_term
        for theme in ('hologram', 'moonlight', 'moonlight', 'hologram'):
            terminal.render(Frame(cells, (), TerminalSize(120, 36), theme=theme))
            assert curses.COLORS >= 256
            assert os.environ.get('TERM') == original_term
            acknowledge(b'r')
    finally:
        terminal.restore()
    assert os.environ.get('TERM') == original_term
    acknowledge(b's')
'''


def _sgr_before(frame, text):
    """Read the emitted SGR state, independently of curses' color bookkeeping."""
    bold, dim, foreground, background = False, False, None, None
    for match in re.finditer(rb"\x1b\[([0-9;]*)m", frame[:frame.index(text)]):
        codes = [int(value or b"0") for value in match[1].split(b";")]
        index = 0
        while index < len(codes):
            code = codes[index]
            if code == 0:
                bold, dim, foreground, background = False, False, None, None
            elif code == 1:
                bold = True
            elif code == 2:
                dim = True
            elif code == 22:
                bold, dim = False, False
            elif 30 <= code <= 37:
                foreground = code - 30
            elif 40 <= code <= 47:
                background = code - 40
            elif code == 39:
                foreground = None
            elif code == 49:
                background = None
            elif code in (38, 48) and codes[index + 1:index + 2] == [5]:
                value = codes[index + 2]
                if code == 38:
                    foreground = value
                else:
                    background = value
                index += 2
            index += 1
    return bold, dim, foreground, background


@pytest.mark.parametrize("term", ("xterm", "xterm-256color"))
def test_fixed_palette_theme_switch_same_frame_and_reentry_preserve_term(term):
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

    def receive(marker):
        assert select.select([completed_r], [], [], 5)[0], drain()
        assert os.read(completed_r, 1) == marker, drain()
        return drain()

    sessions, restored_outputs = [], []
    try:
        for _ in range(2):
            frames = []
            for _ in range(4):
                frames.append(receive(b"r"))
                os.write(commands_w, b"n")
            sessions.append(frames)
            restored_outputs.append(receive(b"s"))
            # Check each restore before allowing the same object to re-enter.
            assert termios.tcgetattr(slave) == original
            os.write(commands_w, b"n")
        child.wait(timeout=5)
        restored_outputs.append(drain())
        assert child.returncode == 0, restored_outputs
        assert termios.tcgetattr(slave) == original

        fixed = {b"BODY-SENTINEL": 253, b"TRACK-SENTINEL": 239,
                 b"MUTED-SENTINEL": 247, b"AFTER-TRACK-SENTINEL": 253,
                 b"AMBER-SENTINEL": 215}
        for frames in sessions:
            for frame, primary, secondary in ((frames[0], 111, 170),
                                               (frames[1], 117, 183),
                                               (frames[3], 111, 170)):
                expected = dict(fixed)
                expected.update({b"PRIMARY-SENTINEL": primary, b"SECONDARY-SENTINEL": secondary})
                for text, foreground in expected.items():
                    assert text in frame, (text, frame)
                    assert _sgr_before(frame, text) == (False, False, foreground, 233), frame
            assert all(text not in frames[2] for text in (*fixed, b"PRIMARY-SENTINEL", b"SECONDARY-SENTINEL"))
            assert b"\x1b[2J" not in frames[2]
        output = b"".join(frame for frames in sessions for frame in frames) + b"".join(restored_outputs)
        assert b"\x1b]4;" not in output
        assert b"\x1b[?1049h" in output and b"\x1b[?1049l" in output
        assert b"\x1b[?25l" in output and b"\x1b[?25h" in output
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        for fd in (master, slave, commands_w, completed_r):
            os.close(fd)
