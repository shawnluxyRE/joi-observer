"""Additional whole-document and diagnostic boundaries for startup YAML.

Historical container-tail names preserve R5-001 regression selectors. Since the
v1.12 contract includes every container, those same cases now cover later active
items. Additional mount-tail cases protect whole-document checks in ignored data.
"""

import pytest

from joi_observer.config import ConfigError, load_config


@pytest.mark.parametrize("field", ["models", "logging"])
def test_deep_invalid_yaml_structure_is_a_safe_configuration_error(tmp_path, field):
    path = tmp_path / "config.yaml"
    # Short, syntactically valid YAML whose field shape is invalid. Parser
    # recursion limits must remain a local configuration diagnostic as well.
    source = field + ": " + "[" * 600 + "PRIVATE-depth-marker" + "]" * 600 + "\n"
    assert len(source) < 1500
    path.write_text(source, encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert str(path.absolute()) in str(caught.value)
    assert "PRIVATE-depth-marker" not in str(caught.value)


def test_service_with_deep_invalid_yaml_exits_two_without_constructing_runtime(tmp_path):
    from io import StringIO

    from joi_observer.cli import CommandDependencies, run_command
    from joi_observer.service import CollectorService
    from test_service_contract import MemoryLease, MemoryListener

    path = tmp_path / "config.yaml"
    path.write_text("models: " + "[" * 600 + "PRIVATE-depth-marker" + "]" * 600 + "\n",
                    encoding="utf-8")
    lease, listener = MemoryLease(), MemoryListener()
    constructed = []

    def runtime_factory(config):
        constructed.append(config)
        pytest.fail("Invalid configuration must not construct a runtime")

    service = CollectorService(path, runtime_factory=runtime_factory,
                               lease=lease, listener=listener)
    stdout, stderr = StringIO(), StringIO()
    dependencies = CommandDependencies(
        tmp_path, tmp_path, False, False, "dumb", stdout, stderr,
        lambda endpoint: pytest.fail("Service must not construct a TUI"),
        lambda config_path, endpoint: service,
    )
    result = run_command(["service", "--config", str(path)], dependencies=dependencies)
    assert not constructed and not lease.held and listener.start_calls == 0
    assert result == 2
    assert str(path.absolute()) in stderr.getvalue()
    assert "PRIVATE-depth-marker" not in stderr.getvalue()
    assert stdout.getvalue() == ""


def test_config_path_permission_race_during_regular_file_check_is_a_config_error(
        tmp_path, monkeypatch):
    from pathlib import Path

    from joi_observer.config import resolve_config_path

    path = tmp_path / "config.yaml"
    path.write_text("{}\n", encoding="utf-8")
    real_stat = Path.stat
    calls = []

    def stat(candidate, *args, **kwargs):
        if candidate == path:
            calls.append(candidate)
            if len(calls) == 2:
                raise PermissionError("PRIVATE-permission-race")
        return real_stat(candidate, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    try:
        selected = resolve_config_path(str(path), cwd=tmp_path, home=tmp_path)
    except ConfigError as caught:
        assert caught.path == path.absolute()
        assert "PRIVATE-permission-race" not in str(caught)
    else:
        # Reusing the first validated stat result is also correct and removes
        # the race entirely; the API does not require a redundant second stat.
        assert selected == path.absolute() and len(calls) == 1


def test_small_shared_alias_dag_does_not_expand_every_reference_path(tmp_path):
    """Valid ignored tails must not turn a tiny YAML graph into exponential work."""
    import os
    from pathlib import Path
    import subprocess
    import sys

    lines = ["mount_points:", "  - /", "  - /data", "  - /srv", "  - &node0 [0]"]
    for index in range(1, 12):
        lines.append(f"  - &node{index} [" + ", ".join([f"*node{index - 1}"] * 6) + "]")
    source = "\n".join(lines) + "\n"
    assert len(source.encode()) < 1024
    path = tmp_path / "shared-aliases.yaml"
    path.write_text(source, encoding="utf-8")
    script = """import json, sys
from pathlib import Path
try:
    import resource
except ImportError:
    pass
else:
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024 * 1024, 256 * 1024 * 1024))
from joi_observer.config import load_config
config = load_config(Path(sys.argv[1]))
print(json.dumps(config.mount_points))
"""
    environment = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    try:
        # Limits protect this regression runner and its machine from the old
        # exponential traversal; they are not a new product parsing-time SLA.
        result = subprocess.run([sys.executable, "-c", script, str(path)],
                                env=environment, capture_output=True, text=True, timeout=3.0)
    except subprocess.TimeoutExpired:
        # subprocess.run kills and reaps its owned process before raising.
        pytest.fail("A valid YAML graph below 1 KiB expanded into unbounded alias-path work")
    assert result.returncode == 0, result.stderr[-1500:]
    assert result.stdout.strip() == '["/", "/data", "/srv"]'


def test_field_validation_retains_yaml_location_without_echoing_value(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_text("models:\n  - id: one\n    type: private-secret\n    name: a\n    base_url: http://localhost\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.field == "models[0].type"
    assert (caught.value.line, caught.value.column) == (3, 11)
    assert "private-secret" not in str(caught.value)


@pytest.mark.parametrize("text", ["models: &loop [*loop]", "logging: {directory: '\u0000'}"])
def test_recursive_alias_and_control_character_are_local_errors(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(path)


_CONTAINER_PREFIX = "containers:\n" + "".join(
    f"  - {{id: c{index}, name: actual-{index}}}\n" for index in range(5)) + "  - "
_MOUNT_PREFIX = "mount_points:\n  - /\n  - /data\n  - /srv\n  - "


@pytest.mark.parametrize("prefix,line", [
    pytest.param(_CONTAINER_PREFIX, 7, id="sixth-container"),
    pytest.param(_MOUNT_PREFIX, 5, id="ignored-mount"),
])
@pytest.mark.parametrize("tail", ["{id: x, id: y}", "!private secret", "[unterminated"])
def test_list_tails_still_require_valid_yaml(tmp_path, prefix, line, tail):
    path = tmp_path / "config.yaml"
    path.write_text(f"{prefix}{tail}\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.line in (line, line + 1)
    assert caught.value.column is not None


@pytest.mark.parametrize("prefix,field,line,column", [
    pytest.param("sample_interval: ", "sample_interval", 1, 18, id="interval"),
    pytest.param(_CONTAINER_PREFIX, "containers[5]", 7, 5, id="sixth-container"),
    pytest.param(_MOUNT_PREFIX, "mount_points[3]", 5, 5, id="ignored-mount"),
])
@pytest.mark.parametrize("scalar", [
    "!!int PRIVATE", "!!bool PRIVATE", "!!float PRIVATE", "!!timestamp 2026-99-99",
    '!!int ""', '!!float ""', "!!timestamp PRIVATE",
])
def test_invalid_standard_scalar_reports_safe_location(tmp_path, prefix, field, line, column, scalar):
    path = tmp_path / "config.yaml"
    path.write_text(f"{prefix}{scalar}\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.path == path and caught.value.field == field
    assert (caught.value.line, caught.value.column) == (line, column)
    assert "PRIVATE" not in str(caught.value) and scalar not in str(caught.value)


@pytest.mark.parametrize("prefix,field,line", [
    pytest.param(_CONTAINER_PREFIX, "containers[5].ignored", 7, id="sixth-container"),
    pytest.param(_MOUNT_PREFIX, "mount_points[3].ignored", 5, id="ignored-mount"),
])
@pytest.mark.parametrize("scalar", ['!!int "+"', '!!int "-"', '!!int "_"',
                                    '!!float "_"', '!!timestamp ""'])
def test_nested_invalid_scalar_keeps_exact_field(tmp_path, prefix, field, line, scalar):
    path = tmp_path / "config.yaml"
    path.write_text(f"{prefix}ignored: {scalar}\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.path == path and caught.value.field == field
    assert (caught.value.line, caught.value.column) == (line, 14)
    assert scalar not in str(caught.value)


@pytest.mark.parametrize("tail", [
    "{1: ignored}", "{true: ignored}", "{2026-10-30: ignored}",
    "{null: [1, false]}", "{nested: [{1: ignored}]}", "!!set {1: null, 2: null}",
])
def test_ignored_mount_tail_accepts_valid_non_string_mapping_keys(tmp_path, tail):
    path = tmp_path / "config.yaml"
    path.write_text(f"mount_points: ['/', '/a', '/b', {tail}]\n", encoding="utf-8")
    before = path.read_bytes()
    assert load_config(path).mount_points == ("/", "/a", "/b")
    assert path.read_bytes() == before


@pytest.mark.parametrize("tail", [
    "{1: first, 1: second}", "{true: first, true: second}",
    "{2026-10-30: first, 2026-10-30: second}",
    "{1: first, true: second}", "{1: first, 0x1: second}",
])
def test_ignored_mount_tail_still_rejects_duplicate_non_string_keys(tmp_path, tail):
    path = tmp_path / "config.yaml"
    path.write_text(f"mount_points: ['/', '/a', '/b', {tail}]\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="Duplicate YAML key") as caught:
        load_config(path)
    assert caught.value.field == "mount_points[3].<key>"
    assert caught.value.line == 1 and caught.value.column is not None


@pytest.mark.parametrize("tail", [
    '{!!int "": ignored}', '{!!timestamp PRIVATE: ignored}',
    '{!private secret: ignored}', '&loop {*loop: ignored}', '{[1, 2]: ignored}',
])
def test_ignored_mount_tail_keys_keep_whole_yaml_safety(tmp_path, tail):
    path = tmp_path / "config.yaml"
    path.write_text(f"mount_points: ['/', '/a', '/b', {tail}]\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.field.startswith("mount_points[3]")
    assert caught.value.line == 1 and caught.value.column is not None
    assert "PRIVATE" not in str(caught.value) and "secret" not in str(caught.value)


@pytest.mark.parametrize("text", [
    "{1: ignored}", "containers: [{id: c0, name: actual, 1: ignored}]",
    "mount_points: ['/', {1: ignored}, '/b', '/valid-fourth']",
])
def test_active_configuration_still_requires_string_mapping_keys(tmp_path, text):
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="Mapping keys must be strings"):
        load_config(path)


def test_nonrecursive_aliases_in_ignored_mount_tail_preserve_active_values(tmp_path):
    """Ignored data may share nodes with valid active configuration without mutation."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "mount_points:\n"
        "  - &first /\n"
        "  - /data\n"
        "  - /srv\n"
        "  - &shared {id: c0, name: actual-first}\n"
        "  - {1: *first, nested: [*first, *first]}\n"
        "containers: [*shared, {id: c1, name: actual-second}]\n",
        encoding="utf-8",
    )
    original = path.read_bytes()

    config = load_config(path)

    assert config.mount_points == ("/", "/data", "/srv")
    assert [(item.id, item.name) for item in config.containers] == [
        ("c0", "actual-first"), ("c1", "actual-second"),
    ]
    assert path.read_bytes() == original


@pytest.mark.parametrize("active,field", [
    ("containers: [*shared]\n", "containers[0]"),
    ("logging: *shared\n", "logging"),
])
def test_ignored_tail_alias_does_not_bypass_active_mapping_key_validation(tmp_path, active, field):
    """A node accepted in an ignored tail must still be validated at its active use."""
    path = tmp_path / "config.yaml"
    path.write_text(
        "mount_points:\n"
        "  - /\n"
        "  - /data\n"
        "  - /srv\n"
        "  - &shared {1: ignored}\n"
        + active,
        encoding="utf-8",
    )
    original = path.read_bytes()

    with pytest.raises(ConfigError, match="Mapping keys must be strings") as caught:
        load_config(path)

    assert caught.value.field == field
    assert caught.value.line == 5 and caught.value.column is not None
    assert path.read_bytes() == original
