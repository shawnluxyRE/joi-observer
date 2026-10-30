"""REQ-001 配置黑盒契约；只读临时 YAML，不访问任何监控服务。"""

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from joi_observer.config import (
    AppConfig,
    ConfigError,
    ModelType,
    example_config_path,
    load_config,
    resolve_config_path,
)


def write_config(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_empty_mapping_uses_defaults_without_monitor_targets(tmp_path, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    config = load_config(write_config(tmp_path, "{}\n"))
    assert config.sample_interval == 1.0
    assert config.collection_timeout == 3.0
    assert config.mount_points == ("/", "/data")
    assert config.containers == ()
    assert config.models == ()
    assert config.logging.directory == home / ".joi-observer"
    assert config.logging.max_bytes == 10_000_000
    assert config.logging.backup_count == 3


def test_explicit_config_wins_and_relative_path_uses_cwd(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    chosen = tmp_path / "custom.yaml"
    chosen.write_text("{}", encoding="utf-8")
    write_config(tmp_path, "{}")
    assert resolve_config_path("custom.yaml", cwd=tmp_path, home=home) == chosen


def test_cwd_config_wins_over_home_config(tmp_path):
    home = tmp_path / "home"
    (home / ".joi-observer").mkdir(parents=True)
    (home / ".joi-observer" / "config.yaml").write_text("{}", encoding="utf-8")
    local = write_config(tmp_path, "{}")
    assert resolve_config_path(None, cwd=tmp_path, home=home) == local


def test_home_config_used_only_when_cwd_candidate_absent(tmp_path):
    home = tmp_path / "home"
    (home / ".joi-observer").mkdir(parents=True)
    expected = home / ".joi-observer" / "config.yaml"
    expected.write_text("{}", encoding="utf-8")
    assert resolve_config_path(None, cwd=tmp_path, home=home) == expected
    assert resolve_config_path("~/.joi-observer/config.yaml", cwd=tmp_path, home=home) == expected


def test_missing_explicit_file_never_falls_back(tmp_path):
    write_config(tmp_path, "{}")
    missing = tmp_path / "missing.yaml"
    with pytest.raises(ConfigError) as caught:
        resolve_config_path(missing, cwd=tmp_path, home=tmp_path)
    assert caught.value.path == missing
    assert str(missing) in str(caught.value)


def test_no_user_config_reports_expected_and_example_locations(tmp_path):
    home = tmp_path / "home"
    with pytest.raises(ConfigError) as caught:
        resolve_config_path(None, cwd=tmp_path, home=home)
    assert caught.value.path == home / ".joi-observer" / "config.yaml"
    assert str(tmp_path / "config.yaml") in str(caught.value)
    assert str(example_config_path()) in str(caught.value)


def test_directory_candidate_is_error_and_does_not_fall_back(tmp_path):
    (tmp_path / "config.yaml").mkdir()
    with pytest.raises(ConfigError) as caught:
        resolve_config_path(None, cwd=tmp_path, home=tmp_path / "home")
    assert caught.value.path == tmp_path / "config.yaml"


def test_load_handles_file_disappeared_after_resolution(tmp_path):
    missing = tmp_path / "missing.yaml"
    with pytest.raises(ConfigError) as caught:
        load_config(missing)
    assert caught.value.path == missing
    assert caught.value.field == "<file>"


def test_override_targets_and_intervals_are_loaded_in_order(tmp_path):
    path = write_config(tmp_path, """
sample_interval: 2.5
collection_timeout: 8
mount_points: ["/srv", "/data"]
containers:
  - {id: web, name: actual-webui}
  - {id: chat, name: actual-vllm}
models:
  - {id: copy-b, type: embedding, name: same-name, base_url: "http://127.0.0.1:8002/", gpu_ids: ["4"]}
  - {id: copy-a, type: chat, name: same-name, base_url: "http://127.0.0.1:8000"}
""")
    config = load_config(path)
    assert (config.sample_interval, config.collection_timeout) == (2.5, 8.0)
    assert config.mount_points == ("/srv", "/data")
    assert [item.id for item in config.containers] == ["web", "chat"]
    assert [item.id for item in config.models] == ["copy-b", "copy-a"]
    assert config.models[0].type is ModelType.EMBEDDING
    assert config.models[0].base_url == "http://127.0.0.1:8002"
    assert config.models[0].gpu_ids == ("4",)
    assert config.models[1].gpu_ids == ()


def test_reloading_changed_file_observes_new_configuration(tmp_path):
    path = write_config(tmp_path, "mount_points: ['/']\nmodels: []\n")
    first = load_config(path)
    path.write_text("mount_points: ['/data']\ncontainers: [{id: one, name: actual-one}]\n", encoding="utf-8")
    second = load_config(path)
    assert first.mount_points == ("/",)
    assert second.mount_points == ("/data",)
    assert second.containers[0].name == "actual-one"
    assert first.containers == ()


def test_empty_optional_lists_are_preserved(tmp_path):
    config = load_config(write_config(tmp_path, "mount_points: []\ncontainers: []\nmodels: []\n"))
    assert config.mount_points == config.containers == config.models == ()


@pytest.mark.parametrize("count", [0, 1, 5, 6, 10])
def test_complete_container_list_is_retained_in_order(tmp_path, count):
    items = ", ".join(f"{{id: c{i}, name: actual-{i}}}" for i in range(count))
    path = write_config(tmp_path, f"containers: [{items}]\n")
    before = path.read_bytes()
    config = load_config(path)
    assert [c.id for c in config.containers] == [f"c{i}" for i in range(count)]
    assert [c.name for c in config.containers] == [f"actual-{i}" for i in range(count)]
    assert path.read_bytes() == before


@pytest.mark.parametrize("count,index,replacement,field", [
    (6, 5, "{invalid: formerly-ignored}", "containers[5].invalid"),
    (6, 5, "null", "containers[5]"),
    (6, 5, "{id: c0, name: duplicate}", "containers[5].id"),
    (10, 9, "{id: c5, name: duplicate}", "containers[9].id"),
    (10, 9, "{id: c9, name: actual-9, extra: bad}", "containers[9].extra"),
])
def test_every_container_participates_in_validation(tmp_path, count, index, replacement, field):
    items = [f"{{id: c{i}, name: actual-{i}}}" for i in range(count)]
    items[index] = replacement
    path = write_config(tmp_path, "containers: [" + ", ".join(items) + "]\n")
    before = path.read_bytes()
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.field == field
    assert path.read_bytes() == before


@pytest.mark.parametrize("count", [0, 1, 2, 3, 4, 6])
def test_only_first_three_mount_points_are_retained_in_order(tmp_path, count):
    mounts = [f"/mount-{i}" for i in range(count)]
    path = write_config(tmp_path, "mount_points: [" + ", ".join(mounts) + "]\n")
    before = path.read_bytes()
    config = load_config(path)
    assert config.mount_points == tuple(mounts[:3])
    assert path.read_bytes() == before


@pytest.mark.parametrize("tail", ["relative", "null", "{invalid: ignored}", "'/'", "true", "0"])
def test_mount_tail_skips_application_validation_but_does_not_change_source(tmp_path, tail):
    path = write_config(tmp_path, f"mount_points: ['/', '/data', '/srv', {tail}]\n")
    before = path.read_bytes()
    config = load_config(path)
    assert config.mount_points == ("/", "/data", "/srv")
    assert path.read_bytes() == before


@pytest.mark.parametrize("second", ["null", "relative", "'/'"])
def test_invalid_first_three_mount_entries_are_not_replaced_by_later_values(tmp_path, second):
    path = write_config(tmp_path, f"mount_points: ['/', {second}, '/srv', '/valid-fourth']\n")
    before = path.read_bytes()
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.field == "mount_points[1]"
    assert path.read_bytes() == before


@pytest.mark.parametrize("field", ["sample_interval", "collection_timeout"])
@pytest.mark.parametrize("value", ["0", "-1", "0.09", "60.01", ".nan", ".inf", "true", "'1'", "null"])
def test_bad_timing_value_is_localizable_config_error(tmp_path, field, value):
    path = write_config(tmp_path, f"{field}: {value}\n")
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.path == path
    assert caught.value.field == field
    assert field in str(caught.value)


@pytest.mark.parametrize("value", [0.1, 60.0])
def test_timing_endpoints_are_valid(tmp_path, value):
    config = load_config(write_config(tmp_path, f"sample_interval: {value}\ncollection_timeout: {value}\n"))
    assert config.sample_interval == config.collection_timeout == value


@pytest.mark.parametrize("text", ["", "null\n", "[]\n", "42\n", "!!python/object:unknown {}\n"])
def test_invalid_top_level_and_unsafe_yaml_tags_are_rejected(tmp_path, text):
    with pytest.raises(ConfigError):
        load_config(write_config(tmp_path, text))


@pytest.mark.parametrize("text,field", [
    ("unknown: true\n", "unknown"),
    ("logging: {filename: custom.log}\n", "logging.filename"),
    ("models: [{id: a, type: chat, name: a, base_url: 'http://localhost:8000', unknown: true}]\n", "models[0].unknown"),
    ("containers: [{id: a, name: actual, unknown: true}]\n", "containers[0].unknown"),
    ("models: null\n", "models"),
    ("mount_points: ['/data', '/data']\n", "mount_points[1]"),
    ("mount_points: ['relative']\n", "mount_points[0]"),
    ("mount_points: ['/data/../srv']\n", "mount_points[0]"),
    ("models: [{id: a, type: rerank, name: a, base_url: 'http://localhost:8000'}]\n", "models[0].type"),
    ("containers: [{id: a, name: one}, {id: a, name: two}]\n", "containers[1].id"),
    ("models: [{id: a, type: chat, name: one, base_url: 'http://localhost:8000'}, {id: a, type: chat, name: two, base_url: 'http://localhost:8001'}]\n", "models[1].id"),
    ("models: [{id: a, type: chat, name: a, base_url: 'http://localhost:8000', gpu_ids: ['4', '4']}]\n", "models[0].gpu_ids[1]"),
])
def test_invalid_structure_identifies_field(tmp_path, text, field):
    with pytest.raises(ConfigError) as caught:
        load_config(write_config(tmp_path, text))
    assert caught.value.field == field


@pytest.mark.parametrize("text", ["sample_interval: 1\nsample_interval: 2\n", "logging:\n  max_bytes: 1024\n  max_bytes: 2048\n"])
def test_duplicate_yaml_keys_are_not_silently_overwritten(tmp_path, text):
    with pytest.raises(ConfigError) as caught:
        load_config(write_config(tmp_path, text))
    assert caught.value.line is not None and caught.value.line > 0
    assert caught.value.column is not None and caught.value.column > 0


def test_yaml_syntax_error_has_line_and_column(tmp_path):
    path = write_config(tmp_path, "models: [\n")
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.path == path
    assert caught.value.line is not None and caught.value.line > 0
    assert caught.value.column is not None and caught.value.column > 0


@pytest.mark.parametrize("url", [
    "ftp://localhost:8000", "http://localhost:8000/v1", "http://localhost:8000/metrics",
    "http://localhost:8000?token=DO_NOT_ECHO", "http://user:DO_NOT_ECHO@localhost:8000",
    "http://localhost:8000#fragment", "http://localhost:99999", "localhost:8000",
])
def test_service_url_is_direct_origin_without_credentials(tmp_path, url):
    text = f"models: [{{id: a, type: chat, name: one, base_url: '{url}'}}]\n"
    with pytest.raises(ConfigError) as caught:
        load_config(write_config(tmp_path, text))
    assert caught.value.field == "models[0].base_url"
    assert "DO_NOT_ECHO" not in str(caught.value)


@pytest.mark.parametrize("text,field", [
    ("directory: relative/logs", "logging.directory"),
    ("directory: '~somebody/logs'", "logging.directory"),
    ("directory: ''", "logging.directory"),
    ("max_bytes: 1023", "logging.max_bytes"),
    ("max_bytes: true", "logging.max_bytes"),
    ("backup_count: 0", "logging.backup_count"),
    ("backup_count: 1.5", "logging.backup_count"),
])
def test_invalid_log_settings_are_config_errors(tmp_path, text, field):
    with pytest.raises(ConfigError) as caught:
        load_config(write_config(tmp_path, f"logging:\n  {text}\n"))
    assert caught.value.field == field


def test_custom_log_directory_and_rotation_do_not_create_or_modify_files(tmp_path):
    directory = tmp_path / "not-created" / "logs"
    path = write_config(tmp_path, f"logging:\n  directory: '{directory.as_posix()}'\n  max_bytes: 2048\n  backup_count: 2\n")
    before = path.read_bytes()
    config = load_config(path)
    assert config.logging.directory == directory
    assert config.logging.max_bytes == 2048
    assert config.logging.backup_count == 2
    assert not directory.exists()
    assert path.read_bytes() == before


def test_configuration_snapshot_is_immutable():
    config = AppConfig()
    with pytest.raises(FrozenInstanceError):
        config.sample_interval = 2.0


def test_packaged_example_covers_three_types_and_loads_after_copy(tmp_path):
    example = example_config_path()
    assert example.is_absolute() and example.is_file()
    copied = tmp_path / "config.yaml"
    copied.write_bytes(example.read_bytes())
    config = load_config(copied)
    assert [m.type for m in config.models] == [ModelType.CHAT, ModelType.EMBEDDING, ModelType.RERANKER]
    assert [m.name for m in config.models] == ["qwen3.8-flash-next", "qwen3-embedding-4b", "qwen3-reranker-0.6b"]
    assert [m.base_url for m in config.models] == ["http://127.0.0.1:8000", "http://127.0.0.1:8001", "http://127.0.0.1:8002"]
