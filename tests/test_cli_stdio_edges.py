"""Default TTY admission treats unavailable stream capabilities as noninteractive."""

import asyncio
from io import StringIO

import pytest

import joi_observer.cli as cli
from test_cli_environment_edges import forbid_factories, forbid_path_context
from test_client_session import MemoryTerminal
from test_ipc_client import MemoryStream, frame


class ProbeStream(StringIO):
    def __init__(self, error=None):
        super().__init__()
        self.error = error
        self.probes = 0

    def isatty(self):
        self.probes += 1
        if self.error is not None:
            raise self.error
        return True


class FalseyStream(ProbeStream):
    def __bool__(self):
        return False


def install_streams(monkeypatch, stdin, stdout):
    stderr = StringIO()
    monkeypatch.setattr(cli.sys, "stdin", stdin)
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", stderr)
    monkeypatch.setenv("TERM", "xterm-256color")
    return stderr


@pytest.mark.parametrize("descriptor", ["stdin", "stdout"])
@pytest.mark.parametrize("error_type", [OSError, ValueError])
def test_default_tui_failed_tty_probe_returns_three_before_any_factory(monkeypatch, descriptor, error_type):
    stdin, stdout = ProbeStream(), ProbeStream()
    failed = stdin if descriptor == "stdin" else stdout
    failed.error = error_type("PRIVATE standard stream failure")
    stderr = install_streams(monkeypatch, stdin, stdout)
    forbid_path_context(monkeypatch)
    forbid_factories(monkeypatch)
    assert cli.main([]) == 3
    assert failed.probes == 1
    assert stdout.getvalue() == ""
    assert stderr.getvalue() == "An interactive terminal is required.\n"


@pytest.mark.parametrize("descriptor,argv,endpoint", [
    pytest.param("stdin", [], "/run/joi-observer/snapshot.sock", id="falsey-stdin"),
    pytest.param("stdout", [], "/run/joi-observer/snapshot.sock", id="falsey-stdout"),
    pytest.param(None, ["tui", "--socket", "/tmp/offline-view.sock"], "/tmp/offline-view.sock",
                 id="explicit-socket"),
])
def test_interactive_streams_open_one_real_client_without_reading_config(monkeypatch, descriptor, argv, endpoint):
    stdin = FalseyStream() if descriptor == "stdin" else ProbeStream()
    stdout = FalseyStream() if descriptor == "stdout" else ProbeStream()
    stderr = install_streams(monkeypatch, stdin, stdout)
    forbid_path_context(monkeypatch)
    reader, attempts = MemoryStream(frame()), []

    class Writer:
        def __init__(self):
            self.closed = False
            self.transport = self

        def close(self):
            self.closed = True

        async def wait_closed(self):
            return None

        def abort(self):
            self.closed = True

    writer = Writer()

    async def open_stream(endpoint, **kwargs):
        attempts.append(endpoint)
        return reader, writer

    terminal = MemoryTerminal(("q",))
    monkeypatch.setattr(asyncio, "open_unix_connection", open_stream)
    monkeypatch.setattr(cli, "CursesTerminal", lambda: terminal)
    monkeypatch.setattr(cli, "CollectorService",
                        lambda *args, **kwargs: pytest.fail("TUI must never create collection"))
    assert cli.main(argv) == 0
    assert stdin.probes == stdout.probes == 1
    assert attempts == [endpoint] and writer.closed
    assert terminal.events == ["enter", "restore"] and terminal.frames
    assert stdout.getvalue() == stderr.getvalue() == ""


def test_tty_probe_does_not_reclassify_process_interruption(monkeypatch):
    stdin, stdout = ProbeStream(KeyboardInterrupt()), ProbeStream()
    stderr = install_streams(monkeypatch, stdin, stdout)
    forbid_path_context(monkeypatch)
    forbid_factories(monkeypatch)
    with pytest.raises(KeyboardInterrupt):
        cli.main([])
    assert stdin.probes == 1 and stdout.probes == 0
    assert stdout.getvalue() == stderr.getvalue() == ""
