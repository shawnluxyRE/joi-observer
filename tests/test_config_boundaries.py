"""Additional whole-document and diagnostic boundaries for startup YAML.

Historical container-tail names preserve R5-001 regression selectors. Since the
v1.12 contract includes every container, those same cases now cover later active
items. Additional mount-tail cases protect whole-document checks in ignored data.
"""

import pytest

from joi_observer.config import ConfigError, load_config


@pytest.mark.parametrize("tail", ["{id: x, id: y}", "!private secret", "[unterminated"])
def test_ignored_container_tail_still_requires_valid_yaml(tmp_path, tail):
    path = tmp_path / "config.yaml"
    first_five = "\n".join(f"  - {{id: c{i}, name: actual-{i}}}" for i in range(5))
    path.write_text(f"containers:\n{first_five}\n  - {tail}\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.line == 7 or caught.value.line == 8
    assert caught.value.column is not None


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


@pytest.mark.parametrize("tagged", ["!!int PRIVATE", "!!bool PRIVATE", "!!float PRIVATE", "!!timestamp 2026-99-99"])
@pytest.mark.parametrize("in_tail", [False, True])
def test_invalid_standard_tag_scalar_has_safe_location(tmp_path, tagged, in_tail):
    path = tmp_path / "config.yaml"
    text = f"sample_interval: {tagged}\n"
    if in_tail:
        text = "containers:\n" + "".join(f"  - {{id: c{i}, name: n{i}}}\n" for i in range(5)) + f"  - {tagged}\n"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.field == ("containers[5]" if in_tail else "sample_interval")
    assert caught.value.line == (7 if in_tail else 1)
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("origin", ["http://example.com\\path", "http://host%2fpath", "http://-host", "http://host..name"])
def test_malformed_http_authority_is_rejected(tmp_path, origin):
    path = tmp_path / "config.yaml"
    path.write_text(f"models: [{{id: a, type: chat, name: a, base_url: '{origin}'}}]\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.field == "models[0].base_url"


@pytest.mark.parametrize("scalar", ['!!int ""', '!!float ""', '!!timestamp PRIVATE'])
@pytest.mark.parametrize("ignored_tail", [False, True])
def test_standard_scalar_constructor_failures_are_localized_config_errors(
    tmp_path, scalar, ignored_tail
):
    """Keep the original R5 scalar matrix, including the sixth container."""
    path = tmp_path / "config.yaml"
    if ignored_tail:
        text = "containers:\n" + "".join(
            f"  - {{id: c{i}, name: actual-{i}}}\n" for i in range(5)
        ) + f"  - {scalar}\n"
        expected_field, expected_line = "containers[5]", 7
    else:
        text = f"sample_interval: {scalar}\n"
        expected_field, expected_line = "sample_interval", 1
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert caught.value.path == path
    assert caught.value.field == expected_field
    assert caught.value.line == expected_line
    assert caught.value.column is not None
    assert "PRIVATE" not in str(caught.value)


@pytest.mark.parametrize("scalar", ['!!int "+"', '!!int "-"', '!!int "_"',
                                    '!!float "_"', '!!timestamp ""'])
def test_invalid_scalar_in_nested_ignored_tail_preserves_exact_field(tmp_path, scalar):
    """Retain exact nested diagnostics from the historical R5 tail regression."""
    path = tmp_path / "config.yaml"
    text = "containers:\n" + "".join(
        f"  - {{id: c{i}, name: actual-{i}}}\n" for i in range(5)
    ) + f"  - ignored: {scalar}\n"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ConfigError) as caught:
        load_config(path)

    assert caught.value.path == path
    assert caught.value.field == "containers[5].ignored"
    assert (caught.value.line, caught.value.column) == (7, 14)
    assert scalar not in str(caught.value)


@pytest.mark.parametrize("tail", ["{id: x, id: y}", "!private secret", "[unterminated"])
def test_ignored_mount_tail_still_requires_valid_yaml(tmp_path, tail):
    path = tmp_path / "config.yaml"
    path.write_text(f"mount_points:\n  - /\n  - /data\n  - /srv\n  - {tail}\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.line in (5, 6)
    assert caught.value.column is not None


@pytest.mark.parametrize("scalar", [
    "!!int PRIVATE", "!!bool PRIVATE", "!!float PRIVATE", "!!timestamp 2026-99-99",
    '!!int ""', '!!float ""', "!!timestamp PRIVATE",
])
def test_ignored_mount_tail_standard_scalar_errors_keep_safe_location(tmp_path, scalar):
    """Application-level truncation must not bypass scalar constructors or safety."""
    path = tmp_path / "config.yaml"
    path.write_text(f"mount_points:\n  - /\n  - /data\n  - /srv\n  - {scalar}\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.path == path
    assert caught.value.field == "mount_points[3]"
    assert (caught.value.line, caught.value.column) == (5, 5)
    assert "PRIVATE" not in str(caught.value)
    assert scalar not in str(caught.value)


@pytest.mark.parametrize("scalar", ['!!int "+"', '!!int "-"', '!!int "_"',
                                    '!!float "_"', '!!timestamp ""'])
def test_nested_invalid_scalar_in_ignored_mount_tail_keeps_exact_field(tmp_path, scalar):
    path = tmp_path / "config.yaml"
    path.write_text(f"mount_points:\n  - /\n  - /data\n  - /srv\n  - ignored: {scalar}\n", encoding="utf-8")
    with pytest.raises(ConfigError) as caught:
        load_config(path)
    assert caught.value.path == path
    assert caught.value.field == "mount_points[3].ignored"
    assert (caught.value.line, caught.value.column) == (5, 14)
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
