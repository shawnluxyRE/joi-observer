"""Views consume only service metadata; source endpoints never reach the UI."""

from datetime import datetime, timezone
from itertools import product

import pytest

from joi_observer.config import ModelType
from joi_observer.data.models import StateSnapshot
from joi_observer.ipc.protocol import DisplayMetadata, ModelDisplay
from joi_observer.tui.layout import HostInfo, Region, TerminalSize, ViewSelection, compose_frame
from joi_observer.tui.navigation import SessionViewActions
from joi_observer.tui.vllm import vllm_cells


def metadata(*, served="served/title", name="List Alias"):
    return DisplayMetadata("Host", "Ubuntu 24.04", models=(
        ModelDisplay("a", ModelType.CHAT, name, served, ("GPU-a",), None, 443),
        ModelDisplay("b", ModelType.CHAT, name, "second/title", ("GPU-b",), 8001, 8001),
    ))


@pytest.mark.parametrize("name,served", [("List Alias", "served/title"), ("fallback", "fallback")])
def test_list_and_detail_names_from_same_metadata_before_first_sample(name, served):
    region = Region("service", 18, 0, 120, 16)
    cells = vllm_cells(StateSnapshot(()), metadata(name=name, served=served),
                       region, ViewSelection("a"), now=100.0)
    list_cells = [cell for cell in cells if cell.column < 30]
    detail_cells = [cell for cell in cells if cell.column >= 30]
    assert name in " ".join(cell.text for cell in list_cells)
    assert served in " ".join(cell.text for cell in detail_cells)
    assert ":443" in " ".join(cell.text for cell in detail_cells)


def test_long_served_title_is_clipped_without_covering_status_or_other_cells():
    region = Region("service", 18, 0, 120, 16)
    cells = vllm_cells(StateSnapshot(()), metadata(served="S" * 128), region,
                       ViewSelection("a"), now=100.0)
    title = [cell for cell in cells if cell.row == region.row + 2 and cell.column >= 30]
    assert any(cell.text.startswith("SSS") for cell in title)
    occupied = set()
    for cell in title:
        for column in range(cell.column, cell.column + len(cell.text)):
            assert column < region.column + region.width - 1
            assert column not in occupied
            occupied.add(column)


def test_same_named_models_keep_independent_ids_and_per_session_selection():
    data = metadata()
    left, right = SessionViewActions(data.models), SessionViewActions(data.models)
    left.on_key("down")
    left.on_key("t")
    assert left.selection().model_id == "b"
    assert right.selection().model_id == "a"
    assert left.selection().theme != right.selection().theme
    assert data.models[0].gpu_ids == ("GPU-a",) and data.models[1].gpu_ids == ("GPU-b",)


def test_complete_frame_accepts_metadata_without_synthetic_config_or_source_url():
    data = metadata()
    frame = compose_frame(StateSnapshot(()), data, TerminalSize(120, 40),
                          HostInfo(data.hostname, data.system), datetime(2026, 11, 13, tzinfo=timezone.utc),
                          view=ViewSelection("b"), monotonic_now=100.0)
    assert not frame.too_small
    assert "second/title" in " ".join(cell.text for cell in frame.cells)


def metadata_frame_case(state, long_names):
    """Reuse the established complete TUI fixture at the new wire boundary."""
    from dataclasses import replace
    from test_theme_view import configured, snapshot

    config = configured(long_names=long_names)
    origins = ("https://offline.invalid", "http://offline.invalid", "http://offline.invalid:8123")
    models = tuple(replace(
        model, base_url=origin,
        served_model_name=(None if index == 1 else
                           ("Served-" + ("界" * 60 if long_names else model.id))),
        gpu_ids=(("0",) if index == 0 else model.gpu_ids),
    ) for index, (model, origin) in enumerate(zip(config.models, origins)))
    config = replace(config, models=models)
    data = snapshot(waiting=7 if state in ("queued", "stale") else 0,
                    stale=state == "stale", long_names=long_names)
    if state in ("initial", "zero"):
        objects = []
        for item in data.objects:
            metrics = tuple(replace(metric, value=(
                None if state == "initial" else
                0 if type(metric.value) in (int, float)
                and metric.name not in ("index", "memory_total_bytes", "ram_total_bytes", "total_bytes")
                else metric.value))
                for metric in item.metrics)
            objects.append(replace(item, metrics=metrics,
                                   sampled_at=None if state == "initial" else item.sampled_at,
                                   history=() if state == "initial" else item.history))
        data = replace(data, objects=tuple(objects))
    return config, data


@pytest.mark.parametrize("state", ("initial", "zero", "queued", "stale", "recovered"))
@pytest.mark.parametrize("long_names", (False, True), ids=("short-names", "long-names"))
def test_complete_frame_metadata_wire_migration_matches_existing_config_path(state, long_names):
    """All cells, geometry and styles must survive metadata projection/JSON."""
    from copy import deepcopy
    from joi_observer.ipc.protocol import SnapshotEnvelope, build_metadata, decode_envelope, encode_envelope
    from joi_observer.tui.history import HistoryScaleTracker
    from test_theme_view import HOST, NOW, UUIDS

    config, data = metadata_frame_case(state, long_names)
    before = deepcopy((config, data))
    projected = build_metadata(config, hostname=HOST.hostname, system=HOST.system)
    received = decode_envelope(encode_envelope(SnapshotEnvelope(
        "display-instance", "display-config", 1, 100.0, projected, data)))
    assert received.snapshot == data
    old_scales = HistoryScaleTracker(config.models).update(data, now=100.0, columns=88)
    new_scales = HistoryScaleTracker(received.metadata.models).update(
        received.snapshot, now=100.0, columns=88)
    assert new_scales == old_scales
    sizes = (TerminalSize(80, 24), TerminalSize(120, 36), TerminalSize(120, 39),
             TerminalSize(120, 44), TerminalSize(140, 49))
    for kind, theme, size in product(ModelType, ("hologram", "moonlight"), sizes):
        options = dict(gpu_slots=UUIDS, view=ViewSelection(kind.value, theme),
                       monotonic_now=100.0, history_scales=old_scales)
        expected = compose_frame(data, config, size, HOST, NOW, **options)
        actual = compose_frame(received.snapshot, received.metadata, size,
                               HostInfo(received.metadata.hostname, received.metadata.system),
                               NOW, **options)
        assert actual == expected, (state, kind, theme, long_names, size)
    assert (config, data) == before


@pytest.mark.parametrize("changed", ("instance", "metadata"))
def test_manual_new_session_replaces_names_order_theme_and_history_scale(changed):
    """A failed old connection must never paint a new configuration's data."""
    import asyncio
    from dataclasses import replace

    from joi_observer.data.models import HistoryPoint, Metric, ObjectKey, ObjectSnapshot
    from joi_observer.ipc.client import ConnectionFailure, ConnectionState, SnapshotClient
    from joi_observer.ipc.protocol import SnapshotEnvelope, encode_envelope
    from joi_observer.tui.session import TuiClientSession
    from test_client_session import MemoryTerminal
    from test_ipc_client import MemoryConnector, MemoryStream

    async def scenario():
        at = asyncio.get_running_loop().time()
        old_metadata = DisplayMetadata("Old Host", "Ubuntu 24.04", models=(
            ModelDisplay("a", ModelType.CHAT, "Old A", "Old served A", (), 8001, 8001),
            ModelDisplay("b", ModelType.CHAT, "Old B", "Old served B", (), 8002, 8002),
        ))
        new_metadata = replace(old_metadata, hostname="New Host", models=tuple(
            replace(model, name=f"New {model.id.upper()}",
                    served_model_name=f"New served {model.id.upper()}",
                    explicit_port=9002 if model.id == "b" else 9001,
                    effective_port=9002 if model.id == "b" else 9001)
            for model in reversed(old_metadata.models)
        ))

        def encoded(metadata, value, *, instance, sequence):
            objects = tuple(ObjectSnapshot(
                ObjectKey("vllm", model.id),
                (Metric("running", 1, "seq"), Metric("waiting", 0, "seq"),
                 Metric("decode_rate", value, "tok/s")), sampled_at=at,
                history=(HistoryPoint(at, (Metric("decode_rate", value, "tok/s"),)),),
            ) for model in metadata.models)
            return encode_envelope(SnapshotEnvelope(
                instance, "config", sequence, at, metadata, StateSnapshot(objects, sequence)))

        old_wire = encoded(old_metadata, 150, instance="original", sequence=1)
        fresh_wire = encoded(new_metadata, 2,
                             instance="restarted" if changed == "instance" else "original",
                             sequence=2)
        stream = MemoryStream(old_wire)
        connector = MemoryConnector(stream)
        client = SnapshotClient(connector=connector)

        class FirstTerminal(MemoryTerminal):
            def __init__(self):
                super().__init__()
                self.stage = 0

            async def read_key(self, timeout):
                await asyncio.sleep(min(timeout, 0.005))
                texts = {cell.text for cell in self.frames[-1].cells}
                if self.stage == 0 and "Old served A" in texts:
                    self.stage = 1
                    return "down"
                if self.stage == 1 and "Old served B" in texts:
                    self.stage = 2
                    return "up"
                if self.stage == 2 and "Old served A" in texts:
                    self.stage = 3
                    return "t"
                if self.stage == 3 and self.frames[-1].theme == "moonlight":
                    assert "Old served A" in texts and "Scale ≤ 200 tok/s" in texts
                    self.stage = 4
                    stream.pending.put_nowait(fresh_wire)
                return None

        terminal = FirstTerminal()
        old_session = TuiClientSession(client, terminal)
        with pytest.raises(ConnectionFailure):
            await asyncio.wait_for(old_session.run(), 2)
        assert terminal.stage == 4 and terminal.events == ["enter", "restore"]
        assert client.state is ConnectionState.CLOSED and stream.closed
        assert len(connector.calls) == 1
        assert all(not cell.text.startswith("New ")
                   for value in terminal.frames for cell in value.cells)
        with pytest.raises(ConnectionFailure):
            client.envelope()

        # Only a new user session may consume the replacement configuration.
        fresh_stream = MemoryStream(fresh_wire)
        fresh_connector = MemoryConnector(fresh_stream)
        fresh_client = SnapshotClient(connector=fresh_connector)
        fresh_terminal = MemoryTerminal(("q",))
        await asyncio.wait_for(TuiClientSession(fresh_client, fresh_terminal).run(), 2)
        first = fresh_terminal.frames[0]
        texts = {cell.text for cell in first.cells}
        assert first.theme == "hologram"
        assert {"New Host", "New A", "New B", "New served B", ":9002",
                "Scale ≤ 2 tok/s"} <= texts
        assert "New served A" not in texts and not any(text.startswith("Old ") for text in texts)
        assert "Scale ≤ 200 tok/s" not in texts
        assert fresh_terminal.events == ["enter", "restore"] and fresh_stream.closed
        assert len(fresh_connector.calls) == 1
        assert [task for task in asyncio.all_tasks()
                if task is not asyncio.current_task() and not task.done()] == []

    asyncio.run(scenario())
