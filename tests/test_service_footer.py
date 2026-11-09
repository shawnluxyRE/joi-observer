"""Service-owned navigation wording; the global footer keys stay unchanged."""

from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timezone

import pytest

from joi_observer.config import AppConfig
from joi_observer.data.models import StateSnapshot
from joi_observer.tui.layout import HostInfo, TerminalSize, compose_frame
from joi_observer.tui.services import VLLM_SERVICE, footer_text


def test_vllm_presentation_owns_its_model_navigation_wording():
    assert (VLLM_SERVICE.service_id, VLLM_SERVICE.title, VLLM_SERVICE.navigation_label) == (
        "vllm", "vLLM", "Select model",
    )


def test_service_presentation_is_immutable():
    service = replace(VLLM_SERVICE)
    with pytest.raises(FrozenInstanceError):
        service.navigation_label = "Select item"
    assert service == VLLM_SERVICE


@pytest.mark.parametrize("label", ("Select model", "Select item"))
def test_footer_uses_service_navigation_wording_and_keeps_global_keys(label):
    # Input metadata varies; no navigation, composition or output is mocked.
    service = replace(VLLM_SERVICE, navigation_label=label)
    assert footer_text(service) == f"↑↓ {label}    t Theme    q Quit"
    assert service.navigation_label == label
    assert VLLM_SERVICE.navigation_label == "Select model"


def test_frame_binds_navigation_wording_to_its_current_service(monkeypatch):
    # Replace only the current service's presentation input. This does not
    # introduce an enabled service or simulate a result from the composer.
    service = replace(VLLM_SERVICE, title="vLLM custom", navigation_label="Select item")
    monkeypatch.setattr("joi_observer.tui.services.VLLM_SERVICE", service)
    frame = compose_frame(StateSnapshot(()), AppConfig(), TerminalSize(120, 40),
                          HostInfo("offline", "Ubuntu"),
                          datetime(2026, 11, 3, tzinfo=timezone.utc), monotonic_now=0)
    footer = next(region for region in frame.regions if region.name == "footer")
    assert [(cell.text, cell.role) for cell in frame.cells if cell.row == footer.row] == [
        ("↑↓ Select item    t Theme    q Quit", "primary"),
    ]
    service_region = next(region for region in frame.regions if region.name == "service")
    assert [(cell.text, cell.role) for cell in frame.cells
            if cell.row == service_region.row and cell.role == "secondary"] == [
        (" vLLM custom ", "secondary"),
    ]
    switch = next(region for region in frame.regions if region.name == "service_switch")
    switch_cells = tuple(cell for cell in frame.cells if cell.row == switch.row)
    assert [(cell.text, cell.role) for cell in switch_cells if cell.text == service.title] == [
        ("vLLM custom", "primary"),
    ]
    assert any("WebUI (disabled)" in cell.text and cell.role == "muted" for cell in switch_cells)
    assert service.service_id == "vllm"
