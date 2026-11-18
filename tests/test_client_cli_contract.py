"""Public dispatcher contracts for the host service and TUI client."""

from io import StringIO
from pathlib import Path

import pytest

from joi_observer.cli import CommandDependencies, run_command
from joi_observer.ipc.client import ConnectionFailure


class ClientBoundary:
    def __init__(self, error=None):
        self.events = []
        self.error = error

    async def run(self):
        self.events.append("run")
        if self.error:
            self.events.append("restored")
            raise self.error

    async def close(self):
        self.events.append("close")


class ServiceBoundary(ClientBoundary):
    async def run(self, stop):
        self.events.append("run")
        assert not stop.is_set()


def environment(tmp_path, *, tty=True, error=None):
    client, service = ClientBoundary(error), ServiceBoundary()
    clients, services = [], []
    def tui_factory(endpoint):
        clients.append(endpoint)
        return client
    def service_factory(path, endpoint):
        services.append((path, endpoint))
        return service
    deps = CommandDependencies(tmp_path, tmp_path / "home", tty, tty, "xterm-256color",
                               StringIO(), StringIO(), tui_factory, service_factory)
    return deps, client, service, clients, services


@pytest.mark.parametrize("argv", [[], ["tui"], ["--socket", "/tmp/custom.sock"]])
def test_default_and_explicit_tui_ignore_invalid_local_monitoring_config(tmp_path, argv):
    (tmp_path / "config.yaml").write_text("invalid: [", encoding="utf-8")
    deps, client, _, clients, services = environment(tmp_path)
    assert run_command(argv, dependencies=deps) == 0
    assert client.events == ["run", "close"] and services == []
    assert clients == [Path("/tmp/custom.sock" if argv and argv[0] == "--socket"
                            else "/run/joi-observer/snapshot.sock")]
    assert deps.stderr.getvalue() == ""


@pytest.mark.parametrize("argv", [["--config", "x.yaml"], ["tui", "--config", "x.yaml"]])
def test_old_config_option_is_rejected_with_service_migration_hint(tmp_path, argv):
    deps, _, _, clients, services = environment(tmp_path)
    assert run_command(argv, dependencies=deps) == 2
    assert "service --config" in deps.stderr.getvalue()
    assert clients == services == []


def test_service_dispatches_without_interactive_terminal(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("{}\n", encoding="utf-8")
    deps, _, service, clients, services = environment(tmp_path, tty=False)
    assert run_command(["service", "--config", str(path)], dependencies=deps) == 0
    assert services == [(path, Path("/run/joi-observer/snapshot.sock"))]
    assert clients == [] and service.events == ["run", "close"]


def test_connection_error_is_safe_and_never_starts_local_service(tmp_path):
    deps, client, _, clients, services = environment(tmp_path, error=ConnectionFailure("private detail"))
    assert run_command([], dependencies=deps) == 4
    assert client.events == ["run", "restored", "close"]
    assert len(clients) == 1 and services == []
    assert deps.stderr.getvalue().strip() == (
        "Cannot connect to collector service. Run joi-observer again to retry.")


def test_service_internal_state_error_exits_one_after_real_runtime_cleanup(tmp_path):
    """The formal service command must retain a failed runtime's exit status."""
    from joi_observer.data.models import Metric, MetricCollectionResult
    from joi_observer.service import CollectorService
    from test_service_contract import MemoryLease, MemoryListener, runtime_fixture

    path = tmp_path / "config.yaml"
    path.write_text("mount_points: []\n", encoding="utf-8")
    runtime, source, log = runtime_fixture()

    async def invalid_result():
        source.calls += 1
        # The real State rejects undeclared metric fields. This is an internal
        # contract error, rather than an ordinary source failure/STALE result.
        return MetricCollectionResult(source.spec.key, (Metric("undeclared", 1.0),))

    source.collect = invalid_result
    listener, lease = MemoryListener(), MemoryLease()
    service = CollectorService(path, runtime_factory=lambda config: runtime,
                               listener=listener, lease=lease,
                               host_factory=lambda: ("Host", "Ubuntu 24.04"))
    stdout, stderr = StringIO(), StringIO()
    deps = CommandDependencies(tmp_path, tmp_path / "home", False, False, "dumb",
                               stdout, stderr,
                               lambda endpoint: pytest.fail("service must not construct a TUI"),
                               lambda config_path, endpoint: service)
    result = run_command(["service", "--config", str(path)], dependencies=deps)
    assert source.calls == 1 and source.closed and log.closed and listener.closed
    assert not lease.held and stdout.getvalue() == ""
    assert result == 1
    assert stderr.getvalue().strip() == "Observer stopped unexpectedly."
