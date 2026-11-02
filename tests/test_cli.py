"""REQ-001 CLI公开行为；配置读取是真实入口，终端/运行期为离线边界替身。"""

from io import StringIO
from pathlib import Path
import os
import subprocess
import sys

import pytest

from joi_observer.cli import CliDependencies, main


class MemoryRuntime:
    """只隔离运行期环境，不模拟被测main的参数/错误/生命周期逻辑。"""

    def __init__(self, *, writable=True, error=None):
        self.writable = writable
        self.error = error
        self.calls = []

    def prepare_log(self):
        self.calls.append("prepare")
        return self.writable

    async def run(self):
        self.calls.append("run")
        if self.error:
            raise self.error

    async def close(self):
        self.calls.append("close")


def environment(tmp_path: Path, *, writable=True, error=None, tty=True, term="xterm-256color"):
    """创建纯内存运行期与流；调用清单可验证main何时越过启动边界。"""
    runtime = MemoryRuntime(writable=writable, error=error)
    configs = []

    def factory(config):
        configs.append(config)
        return runtime

    deps = CliDependencies(
        cwd=tmp_path,
        home=tmp_path / "home",
        stdin_isatty=tty,
        stdout_isatty=tty,
        term=term,
        stdout=StringIO(),
        stderr=StringIO(),
        runtime_factory=factory,
    )
    return deps, runtime, configs


def valid_config(tmp_path: Path, content="{}\n"):
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def test_valid_configuration_runs_directly_and_closes(tmp_path):
    valid_config(tmp_path)
    deps, runtime, configs = environment(tmp_path)
    assert main([], dependencies=deps) == 0
    assert runtime.calls == ["prepare", "run", "close"]
    assert len(configs) == 1
    assert configs[0].sample_interval == 1.0
    assert deps.stdout.getvalue() == deps.stderr.getvalue() == ""


def test_missing_configuration_exits_before_runtime_and_names_example(tmp_path):
    deps, runtime, configs = environment(tmp_path)
    assert main([], dependencies=deps) == 2
    error = deps.stderr.getvalue()
    assert "config.yaml" in error
    assert "example" in error.lower()
    assert str(tmp_path / "home" / ".joi-observer" / "config.yaml") in error
    assert configs == runtime.calls == []


def test_explicit_missing_configuration_does_not_fall_back(tmp_path):
    valid_config(tmp_path)
    deps, runtime, configs = environment(tmp_path)
    missing = tmp_path / "absent.yaml"
    assert main(["--config", str(missing)], dependencies=deps) == 2
    assert str(missing) in deps.stderr.getvalue()
    assert configs == runtime.calls == []


@pytest.mark.parametrize("content", ["sample_interval: 0\n", "models: [\n", "models:\n - {id: a, type: chat, name: A, base_url: 'http://127.0.0.1:8000'}\n - {id: a, type: embedding, name: B, base_url: 'http://127.0.0.1:8001'}\n"])
def test_bad_configuration_never_initializes_terminal_or_log(tmp_path, content):
    path = valid_config(tmp_path, content)
    deps, runtime, configs = environment(tmp_path)
    assert main([], dependencies=deps) == 2
    assert str(path) in deps.stderr.getvalue()
    assert configs == runtime.calls == []
    assert not (tmp_path / "error.log").exists()


@pytest.mark.parametrize("tty,term", [(False, "xterm"), (True, "dumb"), (True, "")])
def test_noninteractive_terminal_rejected_before_runtime(tmp_path, tty, term):
    valid_config(tmp_path)
    deps, runtime, configs = environment(tmp_path, tty=tty, term=term)
    assert main([], dependencies=deps) == 3
    assert "terminal" in deps.stderr.getvalue().lower()
    assert configs == runtime.calls == []


@pytest.mark.parametrize("argument", ["--help", "--version", "--example-config"])
def test_information_options_need_neither_configuration_nor_tty(tmp_path, argument):
    deps, runtime, configs = environment(tmp_path, tty=False)
    assert main([argument], dependencies=deps) == 0
    assert deps.stdout.getvalue().strip()
    assert deps.stderr.getvalue() == ""
    assert configs == runtime.calls == []


def test_unknown_option_has_usage_error_without_runtime(tmp_path):
    deps, runtime, configs = environment(tmp_path)
    assert main(["--pause"], dependencies=deps) == 2
    assert configs == runtime.calls == []


def test_unwritable_log_warns_once_then_monitors(tmp_path):
    valid_config(tmp_path)
    deps, runtime, _ = environment(tmp_path, writable=False)
    assert main([], dependencies=deps) == 0
    assert runtime.calls == ["prepare", "run", "close"]
    assert deps.stderr.getvalue().splitlines() == ["Error log unavailable; monitoring will continue."]
    assert deps.stdout.getvalue() == ""


@pytest.mark.parametrize("error,code", [(RuntimeError("PRIVATE-DIAGNOSTIC"), 1), (KeyboardInterrupt(), 130)])
def test_abnormal_exit_closes_without_leaking_exception(tmp_path, error, code):
    valid_config(tmp_path)
    deps, runtime, _ = environment(tmp_path, error=error)
    assert main([], dependencies=deps) == code
    assert runtime.calls[-1] == "close"
    output = deps.stdout.getvalue() + deps.stderr.getvalue()
    assert "PRIVATE-DIAGNOSTIC" not in output
    assert "Traceback" not in output


def test_restart_uses_changed_configuration_without_code_changes(tmp_path):
    valid_config(tmp_path, "sample_interval: 2\nmount_points: []\ncontainers: []\nmodels: []\n")
    deps, _, configs = environment(tmp_path)
    assert main([], dependencies=deps) == 0
    valid_config(tmp_path, "sample_interval: 5\nmount_points: ['/']\ncontainers: [{id: worker, name: actual-container}]\nmodels: [{id: model, type: chat, name: Display, base_url: 'http://127.0.0.1:8000'}]\n")
    assert main([], dependencies=deps) == 0
    assert configs[0].sample_interval == 2
    assert configs[0].mount_points == ()
    assert configs[1].sample_interval == 5
    assert configs[1].containers[0].name == "actual-container"
    assert configs[1].models[0].id == "model"


def test_malformed_timestamp_cli_exits_two_with_safe_configuration_diagnostic(tmp_path):
    """Bad YAML must not escape the pre-TUI CLI as a Python traceback."""
    path = tmp_path / "config.yaml"
    path.write_text("sample_interval: !!timestamp PRIVATE\n", encoding="utf-8")
    runtime_calls = []

    def factory(config):
        runtime_calls.append(config)
        pytest.fail("Invalid configuration must not construct the runtime")

    stdout, stderr = StringIO(), StringIO()
    deps = CliDependencies(
        cwd=tmp_path,
        home=tmp_path / "home",
        stdin_isatty=True,
        stdout_isatty=True,
        term="xterm-256color",
        stdout=stdout,
        stderr=stderr,
        runtime_factory=factory,
    )

    assert main([], dependencies=deps) == 2
    diagnostic = stderr.getvalue()
    assert str(path) in diagnostic
    assert "sample_interval" in diagnostic and "line 1" in diagnostic
    assert "PRIVATE" not in diagnostic and "Traceback" not in diagnostic
    assert stdout.getvalue() == ""
    assert runtime_calls == []
    assert not (tmp_path / "home" / ".joi-observer" / "error.log").exists()


@pytest.mark.parametrize("scalar", ['!!int ""', '!!float ""', '!!timestamp PRIVATE'])
def test_malformed_scalar_module_process_exits_with_safe_diagnostic(tmp_path, scalar):
    """The real module entry point reports bad YAML before terminal/log setup."""
    path = tmp_path / "config.yaml"
    log_directory = tmp_path / "unused-log"
    path.write_text(f"sample_interval: {scalar}\nlogging:\n  directory: '{log_directory.as_posix()}'\n",
                    encoding="utf-8")
    environment = os.environ.copy()
    source = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (source, environment.get("PYTHONPATH", "")) if value
    )
    process = subprocess.run(
        [sys.executable, "-m", "joi_observer", "--config", str(path)],
        cwd=tmp_path, env=environment, capture_output=True, text=True, timeout=5,
    )

    assert process.returncode == 2
    assert process.stdout == ""
    assert str(path) in process.stderr
    assert "sample_interval" in process.stderr and "line 1" in process.stderr
    assert "PRIVATE" not in process.stderr and "Traceback" not in process.stderr
    assert "\x1b" not in process.stderr
    assert not log_directory.exists()


def test_restart_passes_original_three_mounts_and_complete_containers_to_runtime(tmp_path):
    deps, runtime, configs = environment(tmp_path)
    for prefix, count in (("first", 10), ("second", 6)):
        containers = ", ".join(f"{{id: {prefix}{i}, name: {prefix}-{i}}}" for i in range(count))
        valid_config(tmp_path, f"mount_points: ['/{prefix}-0', '/{prefix}-1', '/{prefix}-2', null]\n"
                     f"containers: [{containers}]\n")
        assert main([], dependencies=deps) == 0

    assert configs[0].mount_points == ("/first-0", "/first-1", "/first-2")
    assert configs[1].mount_points == ("/second-0", "/second-1", "/second-2")
    assert [item.id for item in configs[0].containers] == [f"first{i}" for i in range(10)]
    assert [item.id for item in configs[1].containers] == [f"second{i}" for i in range(6)]
    assert runtime.calls == ["prepare", "run", "close"] * 2
    assert deps.stderr.getvalue() == ""


def test_real_runtime_keeps_all_loaded_container_slots_with_only_three_mounts(
        tmp_path, monkeypatch, pending_docker_command_factory):
    """Production assembly retains all objects even when the terminal is small."""
    from joi_observer.cli import ApplicationRuntime
    from joi_observer.tui.layout import TerminalSize

    class QuittingTerminal:
        def __init__(self):
            self.frames = []
            self.restored = False

        def enter(self):
            pass

        def restore(self):
            self.restored = True

        def size(self):
            return TerminalSize(80, 24)

        def render(self, frame):
            self.frames.append(frame)

        async def read_key(self, timeout):
            return "q"

    terminal = QuittingTerminal()
    monkeypatch.setattr("joi_observer.cli.CursesTerminal", lambda: terminal)
    containers = ", ".join(f"{{id: c{i}, name: actual-{i}}}" for i in range(10))
    path = valid_config(tmp_path,
        "mount_points: ['/first', '/second', '/third', '/not-monitored']\n"
        f"containers: [{containers}]\nlogging: {{directory: '{tmp_path.as_posix()}'}}\n")
    before = path.read_bytes()
    runtimes = []

    def factory(config):
        runtime = ApplicationRuntime(config, docker_command_factory=pending_docker_command_factory)
        runtimes.append(runtime)
        return runtime

    deps = CliDependencies(tmp_path, tmp_path / "home", True, True, "xterm-256color",
                           StringIO(), StringIO(), factory)
    assert main([], dependencies=deps) == 0
    runtime = runtimes[0]
    app = runtime.components.app
    snapshot = app.reader.snapshot()
    objects = [item for item in snapshot.objects if item.key.collector == "docker"]
    assert [item.key.object_id for item in objects] == [f"c{i}" for i in range(10)]
    assert all(not item.stale and item.sampled_at is None and not item.history for item in objects)
    assert app.config.mount_points == runtime.config.mount_points == ("/first", "/second", "/third")
    assert len(runtime.config.containers) == 10
    assert terminal.frames and all(frame.too_small for frame in terminal.frames)
    assert terminal.restored and deps.stderr.getvalue() == ""
    assert path.read_bytes() == before


@pytest.mark.parametrize("content,field", [
    ("mount_points: ['/', null, '/third', '/valid-fourth']\n", "mount_points[1]"),
    ("mount_points: ['/', '/second', '/third', !!timestamp PRIVATE]\n", "mount_points[3]"),
    ("containers: [" + ", ".join(f"{{id: c{i}, name: n{i}}}" for i in range(5))
     + ", {id: c5}]\n", "containers[5].name"),
])
def test_quantity_boundary_errors_exit_before_runtime_and_keep_safe_location(tmp_path, content, field):
    valid_config(tmp_path, content)
    deps, runtime, configs = environment(tmp_path)
    assert main([], dependencies=deps) == 2
    assert configs == runtime.calls == []
    assert field in deps.stderr.getvalue() and "line 1" in deps.stderr.getvalue()
    assert "PRIVATE" not in deps.stderr.getvalue() and "Traceback" not in deps.stderr.getvalue()
    assert deps.stdout.getvalue() == ""
