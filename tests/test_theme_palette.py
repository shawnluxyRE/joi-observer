"""Public palette contracts: design RGB values, without terminal or service IO."""

from dataclasses import FrozenInstanceError

import pytest

from joi_observer.tui.theme import DEFAULT_THEME, Palette, palette_for


def test_new_session_theme_metadata_is_hologram():
    assert DEFAULT_THEME == "hologram"


@pytest.mark.parametrize("name,primary,secondary", [
    ("hologram", (123, 159, 255), (229, 112, 208)),
    ("moonlight", (125, 223, 255), (198, 167, 255)),
])
def test_palette_matches_neon_grid_roles(name, primary, secondary):
    palette = palette_for(name)
    assert palette.name == name
    assert palette.background == (8, 14, 24)
    assert palette.text == (212, 221, 235)
    assert palette.muted == (138, 157, 181)
    assert palette.amber == (255, 164, 91)
    assert palette.track == (62, 74, 91)
    assert palette.brand_shadow == (118, 118, 118)
    assert palette.primary == primary
    assert palette.secondary == secondary


def test_palette_is_frozen_and_lookups_cannot_mutate_other_theme():
    hologram = palette_for("hologram")
    with pytest.raises(FrozenInstanceError):
        hologram.primary = (0, 0, 0)
    with pytest.raises(FrozenInstanceError):
        hologram.track = (0, 0, 0)
    assert isinstance(hologram.primary, tuple)
    palette_for("moonlight")
    assert palette_for("hologram") == hologram


def test_track_default_preserves_legacy_seven_position_palette_construction():
    expected = palette_for("moonlight")
    palette = Palette(expected.name, expected.background, expected.text, expected.muted,
                      expected.primary, expected.secondary, expected.amber)
    assert palette == expected
    assert palette.track == (62, 74, 91)


@pytest.mark.parametrize("name", ["", "Hologram", " hologram", "moonlight ", "other", None, 0, []])
def test_unknown_palette_is_rejected_without_silent_fallback(name):
    with pytest.raises(ValueError):
        palette_for(name)
