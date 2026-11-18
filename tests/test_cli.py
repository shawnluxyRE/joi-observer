"""REQ-001 CLI公开行为；配置读取是真实入口，终端/运行期为离线边界替身。"""

from io import StringIO
from pathlib import Path
import os
import subprocess
import sys

import pytest

import joi_observer.config as config_module
from joi_observer.cli import CommandDependencies, main


class MemoryRuntime:
    """只隔离运行期环境，不模拟被测main的参数/错误/生命周期逻辑。"""

    def __init__(self, *, error=None):
        self.error = error
        self.calls = []

    def prepare_log(self):
        self.calls.append("prepare")

    async def run(self, stop=None):
        self.calls.append("run")
        if self.error:
            raise self.error

    async def close(self):
        self.calls.append("close")


def environment(tmp_path: Path, *, error=None):
    """创建纯内存运行期与流；调用清单可验证main何时越过启动边界。"""
    runtime = MemoryRuntime(error=error)
    configs = []

    def factory(path, endpoint):
        # Configuration loading remains real: invalid YAML must fail before
        # this environment stub records any runtime/log initialization.
        config = config_module.load_config(path)
        configs.append(config)
        runtime.prepare_log()
        return runtime

    deps = CommandDependencies(
        cwd=tmp_path,
        home=tmp_path / "home",
        stdin_isatty=True,
        stdout_isatty=True,
        term="xterm-256color",
        stdout=StringIO(),
        stderr=StringIO(),
        tui_factory=lambda endpoint: runtime,
        service_factory=factory,
    )
    return deps, runtime, configs


def valid_config(tmp_path: Path, content="{}\n"):
    path = tmp_path / "config.yaml"
    path.write_text(content, encoding="utf-8")
    return path


@pytest.mark.parametrize("argv,expected", [
    (["--help"], 0), (["--version"], 0), (["--example-config"], 0), ([], 3),
])
def test_default_cli_information_and_non_tty_checks_do_not_require_a_live_working_directory(argv, expected):
    """Use the real default environment after Linux getcwd loses its directory."""
    source = Path(__file__).resolve().parents[1] / "src"
    script = """
import os
import sys
import tempfile
sys.path.insert(0, sys.argv[1])
from joi_observer.cli import main
original_directory = os.getcwd()
removed_directory = tempfile.mkdtemp(prefix='joi-offline-deleted-cwd-')
os.chdir(removed_directory)
os.rmdir(removed_directory)
try:
    result = main(sys.argv[2:])
finally:
    os.chdir(original_directory)
raise SystemExit(result)
"""
    result = subprocess.run([sys.executable, "-c", script, str(source), *argv],
                            capture_output=True, text=True, timeout=5)
    assert result.returncode == expected, result.stderr
    assert "Traceback" not in result.stderr
    if expected == 0:
        assert result.stdout and result.stderr == ""
    else:
        assert result.stdout == "" and "interactive terminal" in result.stderr.lower()


def test_shared_configuration_runs_directly_and_closes(tmp_path, monkeypatch):
    config_path = valid_config(tmp_path, "sample_interval: 2\n")
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    cwd = tmp_path / "work"
    cwd.mkdir()
    deps, runtime, configs = environment(cwd)
    assert main(["service"], dependencies=deps) == 0
    assert runtime.calls == ["prepare", "run", "close"]
    assert len(configs) == 1
    assert configs[0].sample_interval == 2.0
    assert deps.stdout.getvalue() == deps.stderr.getvalue() == ""


def test_missing_configuration_exits_before_runtime_and_names_example(tmp_path, monkeypatch):
    config_path = tmp_path / "shared" / "config.yaml"
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", config_path)
    deps, runtime, configs = environment(tmp_path)
    assert main(["service"], dependencies=deps) == 2
    error = deps.stderr.getvalue()
    assert "config.yaml" in error
    assert "example" in error.lower()
    assert str(config_path) in error
    assert configs == runtime.calls == []


def test_explicit_missing_configuration_does_not_fall_back(tmp_path):
    valid_config(tmp_path)
    deps, runtime, configs = environment(tmp_path)
    missing = tmp_path / "absent.yaml"
    assert main(["service", "--config", str(missing)], dependencies=deps) == 2
    assert str(missing) in deps.stderr.getvalue()
    assert configs == runtime.calls == []


@pytest.mark.parametrize("content", ["sample_interval: 0\n", "models: [\n", "models:\n - {id: a, type: chat, name: A, base_url: 'http://127.0.0.1:8000'}\n - {id: a, type: embedding, name: B, base_url: 'http://127.0.0.1:8001'}\n"])
def test_bad_configuration_never_initializes_terminal_or_log(tmp_path, content):
    path = valid_config(tmp_path, content)
    deps, runtime, configs = environment(tmp_path)
    assert main(["service"], dependencies=deps) == 2
    assert str(path) in deps.stderr.getvalue()
    assert configs == runtime.calls == []
    assert not (tmp_path / "error.log").exists()


@pytest.mark.parametrize("error,code", [(RuntimeError("PRIVATE-DIAGNOSTIC"), 1), (KeyboardInterrupt(), 130)])
def test_abnormal_exit_closes_without_leaking_exception(tmp_path, error, code):
    valid_config(tmp_path)
    deps, runtime, _ = environment(tmp_path, error=error)
    assert main(["service"], dependencies=deps) == code
    assert runtime.calls[-1] == "close"
    output = deps.stdout.getvalue() + deps.stderr.getvalue()
    assert "PRIVATE-DIAGNOSTIC" not in output
    assert "Traceback" not in output


def test_restart_uses_changed_configuration_without_code_changes(tmp_path):
    valid_config(tmp_path, "sample_interval: 2\nmount_points: []\ncontainers: []\nmodels: []\n")
    deps, _, configs = environment(tmp_path)
    assert main(["service"], dependencies=deps) == 0
    valid_config(tmp_path, "sample_interval: 5\nmount_points: ['/']\ncontainers: [{id: worker, name: actual-container}]\nmodels: [{id: model, type: chat, name: Display, base_url: 'http://127.0.0.1:8000'}]\n")
    assert main(["service"], dependencies=deps) == 0
    assert configs[0].sample_interval == 2
    assert configs[0].mount_points == ()
    assert configs[1].sample_interval == 5
    assert configs[1].containers[0].name == "actual-container"
    assert configs[1].models[0].id == "model"


@pytest.mark.parametrize("scalar", ['!!int ""', '!!float ""', '!!timestamp PRIVATE'])
def test_malformed_scalar_module_process_exits_with_safe_diagnostic(tmp_path, scalar):
    """The real module entry point reports bad YAML before terminal/log setup."""
    path = tmp_path / "config.yaml"
    log_directory = tmp_path / "unused-log"
    path.write_text(f"sample_interval: {scalar}\nlogging:\n  directory: '{log_directory.as_posix()}'\n",
                    encoding="utf-8")
    environment = os.environ.copy()
    source = str(Path(__file__).resolve().parents[1] / "src")
    # The service acquires its instance lease before loading YAML. Isolate that
    # OS boundary in this real module process rather than requiring /run setup;
    # invalid YAML must still exercise production dispatch/load/error handling.
    lease_directory = tmp_path / "runtime"
    lease_directory.mkdir(mode=0o700)
    (tmp_path / "sitecustomize.py").write_text(
        "from pathlib import Path\nimport joi_observer.service as service\n"
        "Lease = service.InstanceLease\n"
        f"service.InstanceLease = lambda: Lease(Path({str(lease_directory / 'service.lock')!r}))\n"
        "def forbidden_startup(*args, **kwargs):\n"
        "    raise AssertionError('Invalid config must not create runtime resources')\n"
        "service.UnixListener = forbidden_startup\n"
        "service.CollectorRuntime.__init__ = forbidden_startup\n",
        encoding="utf-8",
    )
    environment["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(tmp_path), source, environment.get("PYTHONPATH", "")) if value
    )
    process = subprocess.run(
        [sys.executable, "-m", "joi_observer", "service", "--config", str(path)],
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
        assert main(["service"], dependencies=deps) == 0

    assert configs[0].mount_points == ("/first-0", "/first-1", "/first-2")
    assert configs[1].mount_points == ("/second-0", "/second-1", "/second-2")
    assert [item.id for item in configs[0].containers] == [f"first{i}" for i in range(10)]
    assert [item.id for item in configs[1].containers] == [f"second{i}" for i in range(6)]
    assert runtime.calls == ["prepare", "run", "close"] * 2
    assert deps.stderr.getvalue() == ""


def test_real_runtime_keeps_all_loaded_container_slots_with_only_three_mounts(
        tmp_path, monkeypatch, pending_docker_command_factory):
    """Production assembly retains all objects even when the terminal is small."""
    from runtime_harness import ApplicationRuntime
    from joi_observer.tui.layout import HostInfo, TerminalSize

    def forbidden_kernel_version():
        raise AssertionError("Header must use distribution metadata, not the kernel release")

    release_path = tmp_path / "os-release"
    release_path.write_text('PRETTY_NAME="Ubuntu 24.04.3 LTS"\nVERSION_ID="24.04"\n', encoding="utf-8")
    monkeypatch.setattr("joi_observer._host._OS_RELEASE_PATHS", (release_path,))
    monkeypatch.setattr("platform.release", forbidden_kernel_version)

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
    monkeypatch.setattr("runtime_harness.CursesTerminal", lambda: terminal)
    containers = ", ".join(f"{{id: c{i}, name: actual-{i}}}" for i in range(10))
    path = valid_config(tmp_path,
        "mount_points: ['/first', '/second', '/third', '/not-monitored']\n"
        f"containers: [{containers}]\nlogging: {{directory: '{tmp_path.as_posix()}'}}\n")
    before = path.read_bytes()
    runtimes = []

    def factory(path, endpoint):
        config = config_module.load_config(path)
        runtime = ApplicationRuntime(config, docker_command_factory=pending_docker_command_factory)
        runtimes.append(runtime)
        assert runtime.prepare_log()

        class ServiceFixture:
            async def run(self, stop):
                await runtime.run()

            async def close(self):
                # Explicitly stop the service after this test's small TUI has
                # quit; leaving the client itself does not own collection.
                await runtime.close()
        return ServiceFixture()

    deps = CommandDependencies(tmp_path, tmp_path / "home", True, True, "xterm-256color",
                               StringIO(), StringIO(), lambda endpoint: None, factory)
    assert main(["service"], dependencies=deps) == 0
    runtime = runtimes[0]
    app = runtime.components.app
    assert app.host == HostInfo("H3C R5300 G6", "Ubuntu 24.04.3 LTS")
    snapshot = app.reader.snapshot()
    objects = [item for item in snapshot.objects if item.key.collector == "docker"]
    assert [item.key.object_id for item in objects] == [f"c{i}" for i in range(10)]
    assert all(not item.stale and item.sampled_at is None and not item.history for item in objects)
    assert app.config.mount_points == runtime.config.mount_points == ("/first", "/second", "/third")
    assert len(runtime.config.containers) == 10
    assert terminal.frames and all(frame.too_small for frame in terminal.frames)
    assert terminal.restored and deps.stderr.getvalue() == ""
    assert path.read_bytes() == before


@pytest.mark.parametrize("release_text,expected_system", (
    ('NAME="Ubuntu"\nVERSION_ID="24.04"\n', "Ubuntu 24.04"),
    ("", "Ubuntu —"),
    ('PRETTY_NAME=""\nVERSION_ID="24.04"\n', "Ubuntu 24.04"),
    ('PRETTY_NAME="Linux"\nNAME="Ubuntu"\nVERSION_ID="24.04"\n', "Linux"),
    ('PRETTY_NAME=""\nNAME="Linux"\nVERSION_ID="6.8"\n', "Linux 6.8"),
    ("PRETTY_NAME='Ubuntu 24.04 LTS'\n", "Ubuntu 24.04 LTS"),
    (r'''PRETTY_NAME="Ubuntu \"LTS\" \\ \$VERSION \`release\`"''' + "\n",
     'Ubuntu "LTS" \\ $VERSION `release`'),
    ('PRETTY_NAME="Old"\nPRETTY_NAME=""\nNAME="Ubuntu"\nVERSION_ID="24.04"\n', "Ubuntu 24.04"),
    ('PRETTY_NAME="Linux $HOME $(uname)"\n', "Linux $HOME $(uname)"),
    ('PRETTY_NAME=""\nNAME=""\nVERSION_ID=""\n', "Ubuntu —"),
), ids=("missing-pretty-name", "empty-release-file", "empty-pretty-missing-name",
         "explicit-pretty-linux", "explicit-name-linux", "single-quotes", "escaped-literals",
         "last-assignment-wins", "no-shell-expansion", "explicit-empty-fields"))
def test_real_runtime_os_release_text_fallback_uses_distribution_fields(
        tmp_path, monkeypatch, release_text, expected_system):
    """Keep real os-release text and production assembly in the startup path."""
    import asyncio
    import platform

    from runtime_harness import ApplicationRuntime
    from joi_observer.config import load_config
    from joi_observer.tui.layout import HostInfo

    release_path = tmp_path / "os-release"
    release_path.write_text(release_text, encoding="utf-8")
    # The source reader now preserves actual fields rather than using the
    # stdlib's defaults. Substitute only its file location, not parsed values.
    monkeypatch.setattr("joi_observer._host._OS_RELEASE_PATHS", (release_path,))

    def forbidden_kernel_or_hostname():
        raise AssertionError("Header must use the fixed label and local distribution metadata")

    for name in ("node", "system", "release"):
        monkeypatch.setattr(platform, name, forbidden_kernel_or_hostname)
    path = valid_config(tmp_path,
        "mount_points: []\ncontainers: []\nmodels: []\n"
        f"logging: {{directory: '{tmp_path.as_posix()}'}}\n")
    runtime = ApplicationRuntime(load_config(path))
    try:
        assert runtime.prepare_log()
        actual = runtime.components.app.host
    finally:
        asyncio.run(runtime.close())
    assert actual == HostInfo("H3C R5300 G6", expected_system)
    assert release_path.read_text(encoding="utf-8") == release_text


@pytest.mark.parametrize("primary,vendor,expected_system", (
    (b'PRETTY_NAME="Local Ubuntu"\n', b'PRETTY_NAME="Vendor Ubuntu"\n', "Local Ubuntu"),
    (b'NAME="Ubuntu"\n', b'PRETTY_NAME="Vendor Ubuntu"\nVERSION_ID="24.04"\n', "Ubuntu —"),
    (b"", b'PRETTY_NAME="Vendor Ubuntu"\n', "Ubuntu —"),
    (None, b'NAME="Ubuntu"\nVERSION_ID="24.04"\n', "Ubuntu 24.04"),
    (None, None, "Ubuntu —"),
    (b"\xff", b'PRETTY_NAME="Vendor Ubuntu"\n', "Ubuntu —"),
    (b'NAME="Partial"\n' + b"# padding\n" * 1024 + b"\xff", None, "Ubuntu —"),
), ids=("primary-wins", "no-field-merging", "empty-primary-wins", "missing-primary",
         "both-missing", "invalid-utf8", "discard-partial-decoding"))
def test_real_runtime_os_release_reads_one_candidate_without_merging_or_partial_data(
        tmp_path, monkeypatch, primary, vendor, expected_system):
    import asyncio

    from runtime_harness import ApplicationRuntime
    from joi_observer.config import load_config
    from joi_observer.tui.layout import HostInfo

    paths = (tmp_path / "local-release", tmp_path / "vendor-release")
    for path, contents in zip(paths, (primary, vendor)):
        if contents is not None:
            path.write_bytes(contents)
    monkeypatch.setattr("joi_observer._host._OS_RELEASE_PATHS", paths)
    opened = []
    real_open = Path.open

    def observed_open(path, *args, **kwargs):
        if path in paths:
            opened.append(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observed_open)
    config = valid_config(tmp_path,
        "mount_points: []\ncontainers: []\nmodels: []\n"
        f"logging: {{directory: '{tmp_path.as_posix()}'}}\n")
    runtime = ApplicationRuntime(load_config(config))
    try:
        assert runtime.prepare_log()
        assert runtime.components.app.host == HostInfo("H3C R5300 G6", expected_system)
    finally:
        asyncio.run(runtime.close())
    assert opened == list(paths if primary is None else paths[:1])
    for path, contents in zip(paths, (primary, vendor)):
        if contents is not None:
            assert path.read_bytes() == contents


def test_runtime_reads_release_once_but_new_runtime_observes_changed_file(tmp_path, monkeypatch):
    import asyncio

    from runtime_harness import ApplicationRuntime
    from joi_observer.config import load_config
    from joi_observer.tui.layout import HostInfo

    release_path = tmp_path / "os-release"
    release_path.write_text('PRETTY_NAME="Ubuntu first"\n', encoding="utf-8")
    monkeypatch.setattr("joi_observer._host._OS_RELEASE_PATHS", (release_path,))
    opened = []
    real_open = Path.open

    def observed_open(path, *args, **kwargs):
        mode = kwargs.get("mode", args[0] if args else "r")
        if path == release_path and "r" in mode:
            opened.append(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observed_open)
    config = load_config(valid_config(tmp_path,
        "mount_points: []\ncontainers: []\nmodels: []\n"
        f"logging: {{directory: '{tmp_path.as_posix()}'}}\n"))
    first = ApplicationRuntime(config)
    try:
        assert first.prepare_log()
        assert first.components.app.host == HostInfo("H3C R5300 G6", "Ubuntu first")
        release_path.write_text('PRETTY_NAME="Ubuntu second"\n', encoding="utf-8")
        assert first.prepare_log()
        assert first.components.app.host == HostInfo("H3C R5300 G6", "Ubuntu first")
        assert opened == [release_path]
    finally:
        asyncio.run(first.close())

    second = ApplicationRuntime(config)
    try:
        assert second.prepare_log()
        assert second.components.app.host == HostInfo("H3C R5300 G6", "Ubuntu second")
        assert opened == [release_path, release_path]
    finally:
        asyncio.run(second.close())


def test_runtime_discards_partial_release_after_read_error_before_trying_vendor(tmp_path, monkeypatch):
    import asyncio

    from runtime_harness import ApplicationRuntime
    from joi_observer.config import load_config
    from joi_observer.tui.layout import HostInfo

    primary, vendor = tmp_path / "local-release", tmp_path / "vendor-release"
    primary.write_text('NAME="Partial"\nVERSION_ID="99"\n', encoding="utf-8")
    vendor.write_text('VERSION_ID="24.04"\n', encoding="utf-8")
    monkeypatch.setattr("joi_observer._host._OS_RELEASE_PATHS", (primary, vendor))
    opened, primary_lines = [], []
    real_open = Path.open

    class FailingRead:
        def __init__(self, source):
            self.source = source

        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.source.close()

        def __iter__(self):
            return self

        def __next__(self):
            if primary_lines:
                raise OSError("Injected read failure after a partial field")
            line = next(self.source)
            primary_lines.append(line)
            return line

    def observed_open(path, *args, **kwargs):
        source = real_open(path, *args, **kwargs)
        if path in (primary, vendor):
            opened.append(path)
        return FailingRead(source) if path == primary else source

    monkeypatch.setattr(Path, "open", observed_open)
    config = load_config(valid_config(tmp_path,
        "mount_points: []\ncontainers: []\nmodels: []\n"
        f"logging: {{directory: '{tmp_path.as_posix()}'}}\n"))
    runtime = ApplicationRuntime(config)
    try:
        assert runtime.prepare_log()
        assert runtime.components.app.host == HostInfo("H3C R5300 G6", "Ubuntu 24.04")
        assert opened == [primary, vendor]
        assert primary_lines == ['NAME="Partial"\n']
    finally:
        asyncio.run(runtime.close())


@pytest.mark.parametrize("content,field", [
    ("mount_points: ['/', null, '/third', '/valid-fourth']\n", "mount_points[1]"),
    ("mount_points: ['/', '/second', '/third', !!timestamp PRIVATE]\n", "mount_points[3]"),
    ("containers: [" + ", ".join(f"{{id: c{i}, name: n{i}}}" for i in range(5))
     + ", {id: c5}]\n", "containers[5].name"),
])
def test_quantity_boundary_errors_exit_before_runtime_and_keep_safe_location(tmp_path, content, field):
    valid_config(tmp_path, content)
    deps, runtime, configs = environment(tmp_path)
    assert main(["service"], dependencies=deps) == 2
    assert configs == runtime.calls == []
    assert field in deps.stderr.getvalue() and "line 1" in deps.stderr.getvalue()
    assert "PRIVATE" not in deps.stderr.getvalue() and "Traceback" not in deps.stderr.getvalue()
    assert deps.stdout.getvalue() == ""
