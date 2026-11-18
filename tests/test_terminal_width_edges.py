"""Measure terminal columns with ncurses, independently of product formulas."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Requires the target Ubuntu/WSL terminal backend")


# Fixed inputs from the independently observed difference classes; no expected
# widths or product classification formula are encoded in this fixture.
DIFFERENCE_CODEPOINTS = (
    0x1715, 0x1734, 0x1B44, 0x1BAA, 0x1BF2, 0x1BF3, 0x302E, 0x302F,
    *range(0x3248, 0x3250), *range(0x4DC0, 0x4E00),
    0xA953, 0xA9C0, 0x111C0, 0x11235, 0x1134D, 0x116B6, 0x1193D, 0x11F41,
    0x16FF0, 0x16FF1, 0x1D165, 0x1D166, *range(0x1D16D, 0x1D173),
)
SAMPLES = tuple(chr(point) for point in DIFFERENCE_CODEPOINTS) + ("x", "界", "e\u0301", "\u093e")


NCURSES_CHILD = r'''
import ctypes, json, locale, socket, sys
from datetime import datetime, timezone
from pathlib import Path
from joi_observer.config import load_config
from joi_observer.data.models import Metric, ObjectKey, ObjectSnapshot, StateSnapshot
from joi_observer.data.vllm import make_vllm_spec
from joi_observer.ipc.protocol import SnapshotEnvelope, build_metadata, decode_envelope, encode_envelope
from joi_observer.tui.app import CursesTerminal
from joi_observer.tui.layout import HostInfo, TerminalSize, ViewSelection, _clip, compose_frame
from joi_observer.tui.widgets import _width

mode, report, samples, columns, rows = sys.argv[1], Path(sys.argv[2]), json.loads(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
def forbidden(*args, **kwargs):
    raise AssertionError('No server connections are permitted')
socket.socket.connect = socket.create_connection = forbidden
libc = ctypes.CDLL(None)
libc.wcwidth.argtypes = [ctypes.c_wchar]
libc.wcwidth.restype = ctypes.c_int
before_locale = locale.setlocale(locale.LC_CTYPE)
terminal = CursesTerminal()
observations = []
try:
    terminal.enter()
    import curses
    pad = curses.newpad(4, 4096)
    measured = {}
    def measure(text):
        if text not in measured:
            pad.erase()
            # A leading base makes a zero-width mark measurable without
            # asking ncurses to invent a preceding cell at column zero.
            pad.addstr(0, 0, 'A' + text)
            row, column = pad.getyx()
            assert row == 0, ('oracle pad unexpectedly wrapped', repr(text), row, column)
            measured[text] = column - 1
        return measured[text]

    if mode == 'helpers':
        for unit in samples:
            text = 'A' + unit * 12 + 'Z'
            supported = all(libc.wcwidth(character) >= 0 for character in text)
            if supported:
                assert _width(text) == measure(text), (repr(unit), 'widgets width', _width(text), measure(text))
                prefixes = [(text[:index], measure(text[:index])) for index in range(len(text) + 1)]
            for limit in (0, 1, 2, 3, 4, 7, 8, 14, 15, 16, 31):
                clipped = _clip(text, limit)
                actual = measure(clipped)
                assert actual <= limit, (repr(unit), limit, repr(clipped), actual)
                if supported:
                    fitting = [prefix for prefix, width in prefixes if width <= limit]
                    expected = max(fitting, key=len)
                    assert clipped == expected, (repr(unit), limit, repr(clipped), repr(expected))
            observations.append({'input': [hex(ord(c)) for c in unit], 'supported': supported,
                                 'actual_columns': measure(_clip(text, 4095))})
        assert _clip('\u0301A\u0301', 1) == 'A\u0301'
        assert measure(_clip('\u0301A\u0301', 1)) == 1
    else:
        uuid = 'GPU-00000000-0000-0000-0000-000000000001'
        now = datetime(2026, 11, 17, 12, 34, 56, tzinfo=timezone.utc)
        for unit in samples:
            title = 'A' + unit * 50
            path = '/A' + unit * 30
            config_path = report.with_suffix('.yaml')
            config_path.write_text(json.dumps({'mount_points': [path], 'models': [{
                'id': 'model', 'type': 'chat', 'name': title, 'served_model_name': title,
                'base_url': 'http://offline.invalid'}]}, ensure_ascii=False), encoding='utf-8')
            config = load_config(config_path)
            # HostInfo is an explicit presentation input here. This does not
            # change the production service's fixed hardware label.
            metadata = build_metadata(config, hostname='HOST' + unit * 3, system='A' + unit * 80)
            spec = make_vllm_spec(config.models[0])
            items = (
                ObjectSnapshot(ObjectKey('host', 'cpu'), (Metric('cpu_percent', 37.5, '%'),), sampled_at=1.0),
                ObjectSnapshot(ObjectKey('host', 'ram'), (Metric('ram_used_bytes', 4 * 2**30, 'B'),
                    Metric('ram_total_bytes', 16 * 2**30, 'B'), Metric('ram_percent', 25.0, '%')), sampled_at=1.0),
                ObjectSnapshot(ObjectKey('gpu_inventory', 'local'), (Metric('device_count', 1),), sampled_at=1.0),
                ObjectSnapshot(ObjectKey('gpu', uuid), (Metric('index', 0), Metric('name', title),
                    Metric('utilization_percent', 50, '%'), Metric('memory_used_bytes', 4 * 2**30, 'B'),
                    Metric('memory_total_bytes', 16 * 2**30, 'B'), Metric('temperature_c', 61, '°C'),
                    Metric('power_w', 123.5, 'W')), sampled_at=1.0),
                ObjectSnapshot(ObjectKey('storage', 'mount-0'), (Metric('used_bytes', 10 * 2**30, 'B'),
                    Metric('total_bytes', 100 * 2**30, 'B'), Metric('used_percent', 10.0, '%')), sampled_at=1.0),
                ObjectSnapshot(spec.key, spec.metrics),
            )
            received = decode_envelope(encode_envelope(SnapshotEnvelope(
                'width-instance', 'width-config', 1, 1.0, metadata, StateSnapshot(items, 1))))
            frame = compose_frame(received.snapshot, received.metadata, TerminalSize(columns, rows),
                HostInfo(received.metadata.hostname, received.metadata.system), now,
                gpu_slots=(uuid,), view=ViewSelection('model'), monotonic_now=1.0)
            assert not frame.too_small
            regions = {region.name: region for region in frame.regions}
            def end(cell):
                return cell.column + measure(cell.text)
            def one(predicate):
                matches = [cell for cell in frame.cells if predicate(cell)]
                assert len(matches) == 1, (repr(unit), [cell.text for cell in matches])
                return matches[0]
            for cell in frame.cells:
                assert 0 <= cell.row < rows and 0 <= cell.column <= end(cell) <= columns, (repr(unit), cell)
            header = regions['header']
            info_row = header.row + header.height - 2
            host = one(lambda c: c.row == info_row and c.column == 0 and c.role == 'text')
            system = one(lambda c: c.row == info_row and c.text.startswith(' / '))
            clock = one(lambda c: c.row == info_row and c.text == now.strftime('%Y-%m-%d %H:%M:%S'))
            assert system.column == end(host), (repr(unit), 'hostname/system boundary')
            assert end(system) <= clock.column - 2 and end(clock) == columns

            service = regions['service']
            rail_name = one(lambda c: c.row == service.row + 2 and c.column == service.column + 4)
            detail_name = one(lambda c: c.row == service.row + 2 and c.column == service.column + 30)
            right = service.column + service.width - 2
            detail_status = one(lambda c: c.row == service.row + 2 and right - 6 <= c.column < right)
            assert measure(rail_name.text) <= 15 and end(rail_name) <= service.column + 19
            assert end(detail_name) <= right - 7 and end(detail_status) == right

            gpu = regions['gpu']
            gpu_right = gpu.column + gpu.width - 2
            name = one(lambda c: c.row == gpu.row + 1 and c.role == 'text' and c.text.startswith('A'))
            memory = one(lambda c: c.row == gpu.row + 1 and 'GiB' in c.text)
            temperature = one(lambda c: c.row == gpu.row + 1 and c.text.endswith('°C'))
            power = one(lambda c: c.row == gpu.row + 2 and c.text.endswith(' W'))
            assert end(name) <= memory.column - 1 and end(memory) == gpu_right - 12
            assert end(temperature) == end(power) == gpu_right

            def right_group(region, row, lower):
                spans = sorted((c for c in frame.cells if c.row == row and lower <= c.column
                    and c.column < region.column + region.width - 2), key=lambda c: c.column)
                assert spans, (repr(unit), region.name, row)
                assert all(end(left) == right.column for left, right in zip(spans, spans[1:]))
                assert end(spans[-1]) == region.column + region.width - 2
                return spans[0].column
            host_region = regions['host']
            for offset in (1, 3):
                right_group(host_region, host_region.row + offset, host_region.column + 6)
            storage = regions['storage']
            storage_path = one(lambda c: c.row == storage.row + 2 and c.text.startswith('/A'))
            values_start = right_group(storage, storage.row + 2, storage.column + 6)
            assert end(storage_path) <= values_start - 1
            observations.append({'input': [hex(ord(c)) for c in unit], 'name_columns': measure(rail_name.text),
                                 'system_columns': measure(system.text), 'gpu_name_columns': measure(name.text),
                                 'storage_path_columns': measure(storage_path.text)})
    assert locale.setlocale(locale.LC_CTYPE) == before_locale
finally:
    terminal.restore()
report.write_text(json.dumps({'mode': mode, 'size': [columns, rows], 'locale': before_locale,
                              'sample_count': len(samples), 'observations': observations}), encoding='utf-8')
'''


def run_ncurses_probe(tmp_path, mode, columns=120, rows=40):
    import fcntl
    import pty
    import select
    import struct
    import termios

    report = tmp_path / "width.json"
    master, slave = pty.openpty()
    child = None
    captured = bytearray()
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, columns, 0, 0))
        original_mode = termios.tcgetattr(slave)
        environment = dict(os.environ, TERM="xterm-256color", LANG="C.UTF-8", LC_ALL="C.UTF-8")
        environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
        child = subprocess.Popen([sys.executable, "-c", NCURSES_CHILD, mode, str(report),
                                  json.dumps(SAMPLES), str(columns), str(rows)],
                                 stdin=slave, stdout=slave, stderr=slave, env=environment)
        child.wait(timeout=10)
        while select.select([master], [], [], 0)[0]:
            captured.extend(os.read(master, 65536))
        assert child.returncode == 0, captured.decode("utf-8", errors="replace")
        assert termios.tcgetattr(slave) == original_mode
        result = json.loads(report.read_text(encoding="utf-8"))
        assert result["sample_count"] == len(SAMPLES) == 102
        evidence_directory = os.environ.get("JOI_PTY_EVIDENCE_DIR")
        if evidence_directory:
            destination = Path(evidence_directory)
            destination.mkdir(parents=True, exist_ok=True)
            (destination / f"ncurses-independent-{mode}-{columns}x{rows}.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait(timeout=1)
        os.close(master)
        os.close(slave)


def test_clip_and_widget_width_match_independent_ncurses_columns(tmp_path):
    run_ncurses_probe(tmp_path, "helpers")


@pytest.mark.parametrize("columns,rows", [(120, 40), (160, 48)])
def test_all_variable_text_slots_and_hardware_right_edges_use_actual_columns(tmp_path, columns, rows):
    run_ncurses_probe(tmp_path, "frame", columns, rows)


def test_locale_changes_negative_width_and_zero_width_are_handled_without_mutating_locale():
    script = r'''
import ctypes, json, locale
from joi_observer.tui.layout import _clip
from joi_observer.tui.widgets import _width
libc = ctypes.CDLL(None)
libc.wcswidth.argtypes = [ctypes.c_wchar_p, ctypes.c_size_t]
libc.wcswidth.restype = ctypes.c_int
observations = []
for requested in ('C.UTF-8', 'C', 'C.UTF-8'):
    locale.setlocale(locale.LC_CTYPE, requested)
    before = locale.setlocale(locale.LC_CTYPE)
    normalized = 'A?Z' if requested == 'C' else 'A界Z'
    raw = 'A界Z'
    expected_width = libc.wcswidth(normalized, len(normalized))
    assert _width(raw) == expected_width, (requested, _width(raw), expected_width)
    fitting = [normalized[:end] for end in range(len(normalized) + 1)
               if 0 <= libc.wcswidth(normalized[:end], end) <= 3]
    assert _clip(raw, 3) == max(fitting, key=len)
    assert _clip('A\tB\nC\x1bD', 20) == 'A B C D'
    if requested != 'C':
        assert _clip('\u0301A\u0301', 1) == 'A\u0301'
        assert _width('A\u0301') == 1
    assert locale.setlocale(locale.LC_CTYPE) == before
    observations.append({'locale': before, 'width': expected_width, 'clipped': _clip(raw, 3)})
assert [item['width'] for item in observations] == [4, 3, 4]
print(json.dumps(observations))
'''
    environment = dict(os.environ, LANG="C.UTF-8", LC_ALL="C.UTF-8")
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    child = subprocess.run([sys.executable, "-c", script], env=environment,
                           capture_output=True, text=True, timeout=5)
    assert child.returncode == 0, child.stderr
    assert len(json.loads(child.stdout)) == 3
