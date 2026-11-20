"""Shared YAML nodes preserve context, diagnostics and file-selection safety."""

from pathlib import Path

import pytest

import joi_observer.config as config_module
from joi_observer.config import ConfigError, load_config, resolve_config_path


@pytest.mark.parametrize("mounts_first", [True, False])
def test_shared_sequence_only_grants_tail_exemption_at_the_mount_root(tmp_path, mounts_first):
    content = "['/', '/data', '/srv', {1: ignored}]"
    source = (f"mount_points: &shared {content}\nmodels: *shared\n" if mounts_first else
              f"models: &shared {content}\nmount_points: *shared\n")
    path = tmp_path / "config.yaml"
    path.write_text(source, encoding="utf-8")

    with pytest.raises(ConfigError, match="Mapping keys must be strings") as caught:
        load_config(path)

    # Full-document safety reaches the active fourth model before application
    # validation of the earlier strings. Caching the mount root as a generic
    # active sequence would incorrectly skip this separate context.
    assert caught.value.field == "models[3]"
    assert caught.value.line == 1 and caught.value.column is not None
    assert path.read_text(encoding="utf-8") == source


@pytest.mark.parametrize("source,field,line,token", [
    ("containers:\n  - &shared\n    id: c0\n    name: worker\nlogging: *shared\n",
     "logging.id", 3, "c0"),
    ("logging: &shared\n  directory: /var/log/joi\ncontainers: [*shared]\n",
     "containers[0].directory", 2, "/var/log/joi"),
])
def test_cached_active_alias_still_locates_the_exact_invalid_child(tmp_path, source, field, line, token):
    path = tmp_path / "config.yaml"
    path.write_text(source, encoding="utf-8")

    with pytest.raises(ConfigError, match="Unknown field") as caught:
        load_config(path)

    assert caught.value.field == field
    assert (caught.value.line, caught.value.column) == (
        line, source.splitlines()[line - 1].index(token) + 1,
    )
    assert path.read_text(encoding="utf-8") == source


def test_missing_child_of_cached_alias_uses_the_existing_parent_location(tmp_path):
    source = "containers:\n  - &shared\n    id: c0\n    name: worker\nmodels: [*shared]\n"
    path = tmp_path / "config.yaml"
    path.write_text(source, encoding="utf-8")

    with pytest.raises(ConfigError, match="Required field is missing") as caught:
        load_config(path)

    assert caught.value.field == "models[0].base_url"
    assert (caught.value.line, caught.value.column) == (2, 5)
    assert path.read_text(encoding="utf-8") == source


def test_active_alias_can_be_reused_by_ignored_nested_data_without_mutation(tmp_path):
    source = (
        "logging: &shared {directory: /var/log/joi, max_bytes: 2048}\n"
        "mount_points: ['/', '/data', '/srv', *shared, {1: [*shared, *shared]}]\n"
    )
    path = tmp_path / "config.yaml"
    path.write_text(source, encoding="utf-8")

    config = load_config(path)

    assert config.mount_points == ("/", "/data", "/srv")
    assert config.logging.directory == Path("/var/log/joi")
    assert config.logging.max_bytes == 2048
    assert path.read_text(encoding="utf-8") == source


@pytest.mark.parametrize("tail,reason", [
    ("*shared", "Recursive YAML aliases"),
    ("{nested: !private secret}", "Unsupported YAML tag"),
    ("{nested: {1: a, true: b}}", "Duplicate YAML key"),
])
def test_shared_mount_graph_keeps_whole_document_safety(tmp_path, tail, reason):
    source = f"mount_points: &shared ['/', '/data', '/srv', {tail}]\n"
    path = tmp_path / "config.yaml"
    path.write_text(source, encoding="utf-8")

    with pytest.raises(ConfigError, match=reason) as caught:
        load_config(path)

    assert caught.value.field.startswith("mount_points[3]")
    assert caught.value.line == 1 and caught.value.column is not None
    assert "secret" not in str(caught.value)
    assert path.read_text(encoding="utf-8") == source


@pytest.mark.parametrize("error_type", [PermissionError, OSError, ValueError])
def test_missing_candidate_symlink_check_errors_do_not_fall_back(tmp_path, monkeypatch, error_type):
    local, shared = tmp_path / "config.yaml", tmp_path / "shared.yaml"
    shared.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", shared)
    real_stat, real_lstat = Path.stat, Path.lstat
    shared_accesses = []

    def stat(path, *args, **kwargs):
        if path == shared:
            shared_accesses.append(path)
        return real_stat(path, *args, **kwargs)

    def lstat(path, *args, **kwargs):
        if path == local:
            raise error_type("PRIVATE-symlink-access")
        return real_lstat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", stat)
    monkeypatch.setattr(Path, "lstat", lstat)

    with pytest.raises(ConfigError) as caught:
        resolve_config_path(None, cwd=tmp_path, home=tmp_path)

    assert caught.value.path == local.absolute() and caught.value.field == "<file>"
    assert "PRIVATE" not in str(caught.value)
    assert shared_accesses == []


def test_dangling_higher_priority_symlink_does_not_select_shared_config(tmp_path, monkeypatch):
    local, shared = tmp_path / "config.yaml", tmp_path / "shared.yaml"
    shared.write_text("{}\n", encoding="utf-8")
    local.symlink_to(tmp_path / "missing.yaml")
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", shared)

    with pytest.raises(ConfigError) as caught:
        resolve_config_path(None, cwd=tmp_path, home=tmp_path)

    assert caught.value.path == local.absolute()
    assert "does not exist" in str(caught.value)
    assert local.is_symlink() and shared.read_text(encoding="utf-8") == "{}\n"


def test_regular_symlink_candidate_keeps_its_selected_path(tmp_path, monkeypatch):
    local, target, shared = (tmp_path / name for name in ("config.yaml", "target.yaml", "shared.yaml"))
    target.write_text("mount_points: ['/selected']\n", encoding="utf-8")
    shared.write_text("mount_points: ['/fallback']\n", encoding="utf-8")
    local.symlink_to(target)
    monkeypatch.setattr(config_module, "DEFAULT_CONFIG_PATH", shared)

    selected = resolve_config_path(None, cwd=tmp_path, home=tmp_path)

    assert selected == local.absolute()
    assert load_config(selected).mount_points == ("/selected",)
