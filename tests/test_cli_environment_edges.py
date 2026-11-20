"""Default CLI environment reads are ordered before offline runtime factories."""

from io import StringIO
from pathlib import Path
import signal

import pytest

import joi_observer.cli as cli
import joi_observer.config as config_module
from joi_observer.config import AppConfig
from joi_observer.service import CollectorService
from test_service_contract import MemoryLease, MemoryListener, runtime_fixture


class Console(StringIO):
    def __init__(self, tty=None):
        super().__init__()
        self.tty = tty

    def isatty(self):
        if self.tty is None:
            pytest.fail("This command must return before TTY inspection")
        return self.tty


def console(monkeypatch, *, stdin_tty=None, stdout_tty=None):
    stdout, stderr = Console(stdout_tty), Console()
    monkeypatch.setattr(cli.sys, "stdin", Console(stdin_tty))
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", stderr)
    monkeypatch.setenv("TERM", "xterm-256color")
    return stdout, stderr


def forbid_path_context(monkeypatch):
    def unavailable(cls):
        pytest.fail("This command must not read cwd or home")

    monkeypatch.setattr(Path, "cwd", classmethod(unavailable))
    monkeypatch.setattr(Path, "home", classmethod(unavailable))


def forbid_factories(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("No lifecycle factory may run before this command returns")

    for name in ("CollectorService", "TuiClientSession", "SnapshotClient", "CursesTerminal"):
        monkeypatch.setattr(cli, name, forbidden)


@pytest.mark.parametrize("descriptor", [0, 1], ids=["closed-stdin", "closed-stdout"])
@pytest.mark.parametrize("mode", ["missing-at-startup", "closed-wrapper", "closed-descriptor"])
def test_default_tui_with_a_missing_standard_descriptor_reports_noninteractive(descriptor, mode):
    """Closed standard streams are noninteractive in all actual OS forms."""
    import subprocess
    import sys

    source = Path(__file__).resolve().parents[1] / "src"
    bootstrap = r'''
import os, sys
if sys.argv[3] == 'missing-at-startup':
    os.close(int(sys.argv[2]))
entry = """
import os, sys
sys.path.insert(0, sys.argv[1])
from joi_observer.cli import main
stream = getattr(sys, 'stdin' if sys.argv[2] == '0' else 'stdout')
if sys.argv[3] == 'missing-at-startup':
    assert stream is None
elif sys.argv[3] == 'closed-wrapper':
    stream.close()
    assert stream.closed
else:
    os.close(int(sys.argv[2]))
    assert stream is not None and not stream.closed
raise SystemExit(main([]))
"""
os.execv(sys.executable, [sys.executable, '-c', entry, *sys.argv[1:]])
'''
    child = subprocess.run([sys.executable, "-c", bootstrap, str(source), str(descriptor), mode],
                           capture_output=True, text=True, timeout=5)
    assert child.returncode == 3, child.stderr
    assert child.stdout == ""
    assert child.stderr == "An interactive terminal is required.\n"


@pytest.mark.parametrize("argv", [["--help"], ["--version"], ["--example-config"], ["service", "--help"]])
def test_default_information_needs_neither_paths_tty_nor_lifecycle(monkeypatch, argv):
    stdout, stderr = console(monkeypatch)
    forbid_path_context(monkeypatch)
    forbid_factories(monkeypatch)
    assert cli.main(argv) == 0
    assert stdout.getvalue().strip() and stderr.getvalue() == ""


@pytest.mark.parametrize("argv", [
    ["--pause"], ["tui", "--config", "unused.yaml"], ["service", "--socket", "relative.sock"],
])
def test_default_bad_arguments_return_before_paths_tty_or_lifecycle(monkeypatch, argv):
    stdout, stderr = console(monkeypatch)
    forbid_path_context(monkeypatch)
    forbid_factories(monkeypatch)
    assert cli.main(argv) == 2
    assert stdout.getvalue() == "" and stderr.getvalue()
    assert "Traceback" not in stderr.getvalue()


@pytest.mark.parametrize("stdin_tty,stdout_tty,term", [
    (False, True, "xterm"), (True, False, "xterm"), (False, False, "xterm"),
    (True, True, "dumb"), (True, True, ""),
])
def test_noninteractive_environment_refuses_tui_before_startup(monkeypatch, stdin_tty, stdout_tty, term):
    stdout, stderr = console(monkeypatch, stdin_tty=stdin_tty, stdout_tty=stdout_tty)
    monkeypatch.setenv("TERM", term)
    forbid_path_context(monkeypatch)
    forbid_factories(monkeypatch)
    assert cli.main([]) == 3
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "An interactive terminal is required.\n"


@pytest.mark.parametrize("field,error_type", [("cwd", FileNotFoundError), ("home", RuntimeError)])
def test_default_service_path_context_failure_is_safe_exit_two(monkeypatch, field, error_type):
    stdout, stderr = console(monkeypatch)
    forbid_factories(monkeypatch)

    def unavailable(cls):
        raise error_type("PRIVATE environment diagnostic")

    monkeypatch.setattr(Path, field, classmethod(unavailable))
    assert cli.main(["service"]) == 2
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "Cannot determine configuration path context.\n"
    assert "PRIVATE" not in stderr.getvalue() and "Traceback" not in stderr.getvalue()


@pytest.mark.parametrize("selection", ["working-directory", "relative-explicit", "home-explicit"])
def test_default_real_service_factory_keeps_config_selection_and_headless_behavior(tmp_path, monkeypatch, selection):
    stdout, stderr = console(monkeypatch)
    work, home = tmp_path / "work", tmp_path / "home"
    work.mkdir()
    home.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("HOME", str(home))
    paths = {
        "working-directory": work / "config.yaml",
        "relative-explicit": work / "selected.yaml",
        "home-explicit": home / "selected.yaml",
    }
    for index, path in enumerate(paths.values(), 2):
        path.write_text(f"sample_interval: {index}\nmount_points: []\n"
                        f"logging: {{directory: '{(tmp_path / 'logs').as_posix()}'}}\n", encoding="utf-8")
    system = tmp_path / "system.yaml"
    system.write_text("sample_interval: 9\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", system)
    argv = {"working-directory": ["service"],
            "relative-explicit": ["service", "--config", "selected.yaml"],
            "home-explicit": ["service", "--config", "~/selected.yaml"]}[selection]

    original_handlers = {number: signal.getsignal(number) for number in (signal.SIGINT, signal.SIGTERM)}
    installed = dict(original_handlers)

    def set_handler(number, handler):
        previous = installed[number]
        installed[number] = handler
        return previous

    monkeypatch.setattr(signal, "signal", set_handler)
    monkeypatch.setattr(signal, "getsignal", lambda number: installed[number])
    runtime, source, log = runtime_fixture(AppConfig(sample_interval=0.02, mount_points=()))
    original_collect = source.collect

    async def collect():
        result = await original_collect()
        # Controlled OS signal boundary stops the real service without a server.
        installed[signal.SIGTERM](signal.SIGTERM, None)
        return result

    source.collect = collect
    lease, listener, selected = MemoryLease(), MemoryListener(), []

    def default_service_factory(path, *, endpoint, on_warning):
        selected.append((path, endpoint))

        def runtime_factory(config):
            assert config.sample_interval == {"working-directory": 2, "relative-explicit": 3,
                                              "home-explicit": 4}[selection]
            return runtime

        return CollectorService(path, endpoint=endpoint, runtime_factory=runtime_factory,
                                listener=listener, lease=lease,
                                host_factory=lambda: ("Host", "Ubuntu 24.04"), on_warning=on_warning)

    monkeypatch.setattr(cli, "CollectorService", default_service_factory)
    monkeypatch.setattr(cli, "TuiClientSession",
                        lambda *args, **kwargs: pytest.fail("Headless service cannot create a TUI"))
    assert cli.main(argv) == 143
    assert selected == [(paths[selection], Path("/run/joi-observer/snapshot.sock"))]
    assert source.calls == 1 and source.closed and log.closed and listener.closed and not lease.held
    assert stdout.getvalue() == stderr.getvalue() == ""
    assert installed == original_handlers
