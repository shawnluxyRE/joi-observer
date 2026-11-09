"""Model identity configuration contracts; no service discovery or network."""

import pytest

from joi_observer.config import ConfigError, load_config


def write(tmp_path, suffix=""):
    path = tmp_path / "config.yaml"
    path.write_text("models:\n  - id: embedding\n    type: embedding\n"
                    "    name: Display label\n    base_url: http://127.0.0.1:8001\n" + suffix,
                    encoding="utf-8")
    return path


def test_explicit_served_identity_preserves_display_name(tmp_path):
    model = load_config(write(tmp_path, "    served_model_name: qwen3-embedding-4b\n")).models[0]
    assert model.name == "Display label"
    assert model.served_model_name == "qwen3-embedding-4b"


def test_omitted_identity_keeps_legacy_configuration(tmp_path):
    assert load_config(write(tmp_path)).models[0].served_model_name is None


@pytest.mark.parametrize("value", ["null", "''", "42", "true", "[]", "' trailing '",
                                   '"bad\\nname"', "'" + "x" * 129 + "'"])
def test_invalid_explicit_identity_has_field_error(tmp_path, value):
    with pytest.raises(ConfigError) as caught:
        load_config(write(tmp_path, f"    served_model_name: {value}\n"))
    assert caught.value.field == "models[0].served_model_name"
    assert "Unknown field" not in str(caught.value)


def test_printable_slash_identity_is_exact_not_a_filesystem_path(tmp_path):
    assert load_config(write(tmp_path, "    served_model_name: org/model\n")).models[0].served_model_name == "org/model"
