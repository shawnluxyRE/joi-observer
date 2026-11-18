"""Service/client command dispatch; imports never initialize runtime resources."""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Callable, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
import os
from pathlib import Path
import signal
import sys
from typing import Protocol, TextIO

from joi_observer import __version__
from joi_observer.config import ConfigError, example_config_path, resolve_config_path
from joi_observer.ipc.client import ConnectionFailure, SnapshotClient
from joi_observer.service import CollectorService, ServiceStartError
from joi_observer.tui.app import CursesTerminal
from joi_observer.tui.session import TuiClientSession


class ClientSessionPort(Protocol):
    """A single client owns its terminal and connection, never collectors."""

    async def run(self) -> None: ...
    async def close(self) -> None: ...


class ServiceSessionPort(Protocol):
    """Headless collector lifetime, stopped by an explicit event or signal."""

    async def run(self, stop: asyncio.Event) -> None: ...
    async def close(self) -> None: ...


@dataclass(frozen=True)
class CommandDependencies:
    """Environment and lifecycle ports; factories do not replace parsing."""

    cwd: Path
    home: Path
    stdin_isatty: bool
    stdout_isatty: bool
    term: str
    stdout: TextIO
    stderr: TextIO
    tui_factory: Callable[[Path], ClientSessionPort]
    service_factory: Callable[[Path, Path], ServiceSessionPort]


class _ArgumentParser(argparse.ArgumentParser):
    def error(self, message):
        raise ValueError("Invalid command arguments.")


class _SignalExit(Exception):
    def __init__(self, signum):
        self.signum = signum


def _safe_isatty(stream: TextIO | None) -> bool:
    """An absent, closed or unusable standard stream is noninteractive."""
    if stream is None:
        return False
    try:
        return bool(stream.isatty())
    except Exception:
        # This capability probe must fail closed, before constructing a client.
        # Process interruption remains a BaseException and is not reclassified.
        return False


@contextmanager
def _tui_stderr():
    """Keep terminal diagnostics off the curses screen; honor file/pipe redirection."""
    if not os.isatty(2):
        yield
        return
    if sys.stderr is not None:
        sys.stderr.flush()
    inheritable = os.get_inheritable(2)
    original = os.dup(2)
    try:
        with open(os.devnull, "wb") as sink:
            os.dup2(sink.fileno(), 2, inheritable=inheritable)
        try:
            yield
        finally:
            try:
                if sys.stderr is not None:
                    sys.stderr.flush()
            finally:
                os.dup2(original, 2, inheritable=inheritable)
    finally:
        os.close(original)


async def _session(target, service):
    loop = asyncio.get_running_loop()
    current = asyncio.current_task()
    stop = asyncio.Event()
    received = []
    handlers = {}

    def on_signal(signum, frame):
        if not received:
            received.append(signum)
            loop.call_soon_threadsafe(stop.set if service else current.cancel)

    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            handlers[signum] = signal.signal(signum, on_signal)
        except (ValueError, OSError):
            pass
    try:
        try:
            if service:
                await target.run(stop)
            else:
                await target.run()
        finally:
            original = sys.exc_info()[0]
            try:
                await target.close()
            except BaseException:
                if original is None:
                    raise
    except asyncio.CancelledError:
        if received:
            raise _SignalExit(received[0]) from None
        raise
    finally:
        for signum, previous in handlers.items():
            signal.signal(signum, previous)
    if received:
        raise _SignalExit(received[0])


def run_command(argv: Sequence[str] | None = None, *,
                dependencies: CommandDependencies | None = None) -> int:
    """Run one service or one TUI session and return its safe public exit code.

    Configuration lookup is exclusive to service. Its factory receives a path;
    CollectorService validates that file once, under the instance lock. TUI
    failures never create a service or retry. All cleanup uses the same loop.
    Default environment paths are read only for service configuration lookup;
    information, argument checks and the TUI do not require a live cwd/home.
    """
    deps = dependencies
    stdout = sys.stdout if deps is None else deps.stdout
    stderr = sys.stderr if deps is None else deps.stderr
    parser = _ArgumentParser(prog="joi-observer", add_help=False,
                             description="Host collector service and read-only terminal client")
    parser.add_argument("command", nargs="?", choices=("tui", "service"), default="tui")
    parser.add_argument("--socket", metavar="PATH", default="/run/joi-observer/snapshot.sock",
                        help="Absolute local Unix socket path")
    parser.add_argument("--config", metavar="PATH", help="Collector configuration (service only)")
    parser.add_argument("--help", "-h", action="store_true")
    parser.add_argument("--version", "-V", action="store_true")
    parser.add_argument("--example-config", action="store_true")
    try:
        args = parser.parse_args(argv)
    except ValueError as error:
        print(str(error), file=stderr)
        return 2
    if args.help:
        parser.print_help(stdout)
        return 0
    if args.version:
        print(f"joi-observer {__version__}", file=stdout)
        return 0
    if args.example_config:
        print(example_config_path(), file=stdout)
        return 0
    service = args.command == "service"
    if not service and args.config is not None:
        print("Use joi-observer service --config PATH.", file=stderr)
        return 2
    endpoint = Path(args.socket)
    if not endpoint.is_absolute() or "://" in args.socket:
        print("Socket path must be absolute and local.", file=stderr)
        return 2
    if not service:
        if deps is None:
            stdin_isatty, stdout_isatty = _safe_isatty(sys.stdin), _safe_isatty(stdout)
            term = os.environ.get("TERM", "")
        else:
            stdin_isatty, stdout_isatty, term = deps.stdin_isatty, deps.stdout_isatty, deps.term
        if not stdin_isatty or not stdout_isatty or not term.strip() or term.strip().lower() == "dumb":
            print("An interactive terminal is required.", file=stderr)
            return 3
    try:
        if service:
            if deps is None:
                try:
                    cwd, home = Path.cwd(), Path.home()
                except (OSError, RuntimeError, ValueError):
                    print("Cannot determine configuration path context.", file=stderr)
                    return 2
                path = resolve_config_path(args.config, cwd=cwd, home=home)
                target = CollectorService(path, endpoint=endpoint,
                                          on_warning=lambda message: print(message, file=stderr))
            else:
                path = resolve_config_path(args.config, cwd=deps.cwd, home=deps.home)
                target = deps.service_factory(path, endpoint)
        else:
            target = (TuiClientSession(SnapshotClient(endpoint), CursesTerminal())
                      if deps is None else deps.tui_factory(endpoint))
        with nullcontext() if service else _tui_stderr():
            asyncio.run(_session(target, service))
        return 0
    except ConfigError as error:
        print(str(error), file=stderr)
        return 2
    except ConnectionFailure:
        print("Cannot connect to collector service. Run joi-observer again to retry.", file=stderr)
        return 4
    except ServiceStartError:
        print("Collector service could not start.", file=stderr)
        return 5
    except _SignalExit as error:
        return 128 + error.signum
    except KeyboardInterrupt:
        return 130
    except (Exception, asyncio.CancelledError):
        print("Observer stopped unexpectedly.", file=stderr)
        return 1


def main(argv: Sequence[str] | None = None, *,
         dependencies: CommandDependencies | None = None) -> int:
    """Installed and python -m entry point, with no standalone sampling mode."""
    return run_command(argv, dependencies=dependencies)
