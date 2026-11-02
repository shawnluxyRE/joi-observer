"""Raw GPU response boundaries through real state merging and frame composition."""

import asyncio
from datetime import datetime, timezone

import pytest

from joi_observer.collectors.hardware import (
    CommandOutput, CpuCollector, FileSystemStat, GpuCollector, MemoryCollector, StorageCollector,
)
from joi_observer.config import AppConfig, ModelConfig, ModelType
from joi_observer.data.state import MonitorState
from joi_observer.error_log import ErrorKind
from joi_observer.tui.layout import HostInfo, TerminalSize, ViewSelection, compose_frame
from test_hardware import DATA, MOUNTINFO, ROOT, RawIO, UUIDS, gpu_row, values
from test_hardware_monitor import entries, objects, running_monitor, tick


def frame(state):
    return compose_frame(state.snapshot(), AppConfig(mount_points=()), TerminalSize(120, 36),
                         HostInfo("offline", "Linux"), datetime.now(timezone.utc),
                         gpu_slots=(UUIDS[0],))


@pytest.mark.parametrize("prior_sample", [False, True])
def test_gpu_name_driver_error_is_retained_as_failure_and_never_shown_in_frame(prior_sample):
    async def scenario():
        responses = [CommandOutput(0, gpu_row(name="Known GPU"))] if prior_sample else []
        responses.append(CommandOutput(0, gpu_row(name="[Unknown Error]", utilization="75")))
        collector = GpuCollector(UUIDS[0], RawIO(outputs=responses))
        state = MonitorState((collector.spec,), clock=lambda: 2)
        if prior_sample:
            state.accept(await collector.collect(), sampled_at=1)
        result = await collector.collect()
        assert result.failure is not None and result.failure.kind is ErrorKind.PARSE
        assert "name" not in values(result)
        assert values(result)["utilization_percent"] == 75
        state.accept(result, sampled_at=2)
        card = state.snapshot().objects[0]
        assert card.stale and card.history[-1].metrics is None
        assert values(card)["name"] == ("Known GPU" if prior_sample else None)
        text = " ".join(cell.text for cell in frame(state).cells)
        assert "[Unknown Error]" not in text
        assert "STALE" in text and "75%" in text

    asyncio.run(scenario())


def test_gpu_positive_mib_that_converts_to_zero_bytes_cannot_break_frame_rendering():
    async def scenario():
        collector = GpuCollector(UUIDS[0], RawIO(outputs=[
            CommandOutput(0, gpu_row(used="8192", total="16384")),
            CommandOutput(0, gpu_row(used="0", total="0.0000001", utilization="75")),
        ]))
        state = MonitorState((collector.spec,), clock=lambda: 2)
        state.accept(await collector.collect(), sampled_at=1)
        result = await collector.collect()
        assert result.failure is not None and result.failure.kind is ErrorKind.PARSE
        assert "memory_used_bytes" not in values(result)
        assert "memory_total_bytes" not in values(result)
        assert values(result)["utilization_percent"] == 75
        state.accept(result, sampled_at=2)
        card = state.snapshot().objects[0]
        assert card.stale and values(card)["memory_total_bytes"] == 16 * 2**30
        text = " ".join(cell.text for cell in frame(state).cells)
        assert "16.0 GiB" in text and "STALE" in text and "75%" in text

    asyncio.run(scenario())


@pytest.mark.parametrize("configured_path", ["/data/", "//data//", "/symlink/../data"])
def test_storage_capacity_uses_the_same_lexical_path_as_mount_identity(configured_path):
    # No filesystem traversal is needed to expose the mismatch: the IO port must
    # receive the path whose identity the two mountinfo snapshots actually verify.
    io = RawIO(texts={MOUNTINFO: [ROOT + DATA, ROOT + DATA]},
               stats=[FileSystemStat(4096, 100, 20)])
    collector = StorageCollector(0, configured_path, io)
    result = asyncio.run(collector.collect())
    assert result.failure is None and values(result)["used_percent"] == 80
    assert io.calls == [("read_text", MOUNTINFO), ("statvfs", "/data"), ("read_text", MOUNTINFO)]
    assert collector.mount_point == configured_path


@pytest.mark.parametrize("namespace_root", ["net:[4026532238]", "mnt:[4026531841]"])
def test_unrelated_namespace_mount_root_does_not_invalidate_storage(namespace_root):
    namespace = f"621 186 0:4 {namespace_root} /run/docker/netns/local rw shared:327 - nsfs nsfs rw\n"
    raw = ROOT + DATA + namespace
    io = RawIO(texts={MOUNTINFO: [raw, raw]}, stats=[FileSystemStat(4096, 100, 20)])
    result = asyncio.run(StorageCollector(0, "/data", io).collect())
    assert result.failure is None and values(result)["used_percent"] == 80
    assert io.calls[1] == ("statvfs", "/data")


@pytest.mark.parametrize("alias,expected_roles", [
    ("0", ("primary", "muted", "muted")),
    ("1", ("muted", "muted", "primary")),
    (UUIDS[0], ("primary", "primary", "primary")),
])
def test_gpu_partial_failure_and_index_change_update_frame_mapping_without_extra_io(alias, expected_roles):
    """A failed current index must not inherit a successful association.

    The UUID remains the stable identity when the driver's index changes. A
    partial temperature failure still updates independent values, preserves
    the old temperature, and suppresses index-based linking until recovery.
    """
    async def scenario():
        io = RawIO(outputs=[
            CommandOutput(0, gpu_row(utilization="25", temperature="61")),
            CommandOutput(0, gpu_row(1, uuid=UUIDS[0], utilization="75", temperature="[Unknown Error]")),
            CommandOutput(0, gpu_row(1, uuid=UUIDS[0], utilization="50", temperature="65")),
        ])
        collector = GpuCollector(UUIDS[0], io)
        state = MonitorState((collector.spec,), clock=lambda: 3)
        config = AppConfig(mount_points=(), models=(
            ModelConfig("selected", ModelType.CHAT, "Selected", "http://offline.invalid", (alias,)),
        ))
        snapshots = []
        frames = []
        for index, role in enumerate(expected_roles):
            result = await collector.collect()
            state.accept(result, sampled_at=index + 1)
            snapshot = state.snapshot()
            snapshots.append(snapshot)
            current = compose_frame(snapshot, config, TerminalSize(120, 36),
                                    HostInfo("offline", "Linux"), datetime.now(timezone.utc),
                                    gpu_slots=(UUIDS[0],), view=ViewSelection("selected"))
            frames.append(current)
            label = next(cell for cell in current.cells if cell.row == 3 and cell.column == 2)
            filled = next(cell for cell in current.cells if cell.row == 4 and "█" in cell.text)
            percent = next(cell for cell in current.cells if cell.row == 4 and "%" in cell.text)
            assert label.text == ("GPU 0" if index == 0 else "GPU 1")
            assert (label.role, filled.role, percent.role) == (role, role, role)
            assert percent.text == ("25%", "75%", "50%")[index]
            assert any(cell.text == "STALE" for cell in current.cells) == (index == 1)
            details = next(cell.text for cell in current.cells if cell.row == 5 and "°C" in cell.text)
            assert ("61°C" if index < 2 else "65°C") in details
            assert "Unknown Error" not in " ".join(cell.text for cell in current.cells)

            # Rendering alternate selections is pure and does not resample or
            # mutate the state; unknown mapping must clear even UUID linkage.
            unlinked = compose_frame(snapshot, config, TerminalSize(120, 36),
                                     HostInfo("offline", "Linux"), datetime.now(timezone.utc),
                                     gpu_slots=(UUIDS[0],), view=ViewSelection("missing"))
            assert next(cell for cell in unlinked.cells if cell.row == 3 and cell.column == 2).role == "muted"
            assert state.snapshot() == snapshot and len(io.calls) == index + 1

        assert frames[0].regions == frames[1].regions == frames[2].regions
        assert values(snapshots[0].objects[0])["index"] == 0
        assert not snapshots[0].objects[0].stale
        history = snapshots[-1].objects[0].history
        assert len(history) == 3 and history[1].metrics is None
        assert history[0].metrics is not None and history[2].metrics is not None
        await collector.close()
        assert io.closed

    asyncio.run(scenario())


@pytest.mark.parametrize("damaged_field", ["gpu_index", "ram_total"])
def test_large_raw_integer_does_not_abort_monitor_or_other_hardware_updates(tmp_path, damaged_field):
    """Large integers cannot terminate monitoring, even at an unusual boundary.

    No numeric upper bound is specified for these integer fields. An adapter
    may either preserve the exact integer or isolate an unrepresentable value
    as a parse failure. This test does not choose that bound for the design;
    both outcomes must preserve other sampling and allow the following sample.
    """
    async def scenario():
        huge = 10**309
        if damaged_field == "gpu_index":
            bad_io = RawIO(outputs=[
                CommandOutput(0, gpu_row()),
                CommandOutput(0, gpu_row(index=huge, uuid=UUIDS[0])),
                CommandOutput(0, gpu_row(utilization="0")),
            ])
            affected = GpuCollector(UUIDS[0], bad_io)
            retained_field = "index"
        else:
            bad_io = RawIO(texts={"/proc/meminfo": [
                "MemTotal: 100 kB\nMemAvailable: 50 kB\n",
                f"MemTotal: {huge} kB\nMemAvailable: 0 kB\n",
                "MemTotal: 200 kB\nMemAvailable: 25 kB\n",
            ]})
            affected = MemoryCollector(bad_io)
            retained_field = "ram_total_bytes"
        good_io = RawIO(texts={"/proc/stat": [
            "cpu 100 0 0 100 0 0 0 0\n",
            "cpu 125 0 0 175 0 0 0 0\n",
            "cpu 200 0 0 200 0 0 0 0\n",
        ]})
        healthy = CpuCollector(good_io)
        async with running_monitor(tmp_path, (affected, healthy)) as (monitor, state, log, clock, _):
            await tick(monitor, clock, 0)
            initial = objects(state)[affected.spec.key]
            assert not initial.stale

            await tick(monitor, clock, 1)
            current = objects(state)
            unusual = current[affected.spec.key]
            assert not current[healthy.spec.key].stale
            assert values(current[healthy.spec.key])["cpu_percent"] == 25
            recorded = await entries(log, tmp_path)
            if unusual.stale:
                assert unusual.history[-1].metrics is None
                assert values(unusual)[retained_field] == values(initial)[retained_field]
                assert len(recorded) == 1 and recorded[0]["kind"] == "parse"
            else:
                expected = huge if damaged_field == "gpu_index" else huge * 1024
                assert values(unusual)[retained_field] == expected
                assert unusual.history[-1].metrics is not None
                assert recorded == []

            await tick(monitor, clock, 2)
            recovered = objects(state)
            assert not recovered[affected.spec.key].stale
            assert recovered[affected.spec.key].history[-1].metrics is not None
            assert values(recovered[healthy.spec.key])["cpu_percent"] == 75
        assert bad_io.closed and good_io.closed

    asyncio.run(scenario())


@pytest.mark.parametrize("source_kind", ["gpu", "ram", "storage"])
def test_large_integer_hardware_reaches_frame_and_preserves_failure_recovery_semantics(tmp_path, source_kind):
    async def scenario():
        huge = 10**309
        if source_kind == "gpu":
            io = RawIO(outputs=[
                CommandOutput(0, gpu_row(index=huge, uuid=UUIDS[0])),
                CommandOutput(0, gpu_row(index="invalid", uuid=UUIDS[0])),
                CommandOutput(0, gpu_row()),
            ])
            source, field, expected, recovered_value = GpuCollector(UUIDS[0], io), "index", huge, 0
        elif source_kind == "ram":
            io = RawIO(texts={"/proc/meminfo": [
                f"MemTotal: {huge} kB\nMemAvailable: 0 kB\n",
                "MemTotal: nan kB\nMemAvailable: 0 kB\n",
                "MemTotal: 200 kB\nMemAvailable: 25 kB\n",
            ]})
            source, field, expected, recovered_value = MemoryCollector(io), "ram_total_bytes", huge * 1024, 204800
        else:
            io = RawIO(texts={MOUNTINFO: [ROOT] * 6}, stats=[
                FileSystemStat(4096, huge, huge // 2), FileSystemStat(4096, -1, 0),
                FileSystemStat(4096, 200, 50),
            ])
            source, field, expected, recovered_value = StorageCollector(0, "/", io), "total_bytes", huge * 4096, 819200
        good_io = RawIO(texts={"/proc/stat": [
            "cpu 100 0 0 100 0 0 0 0\n", "cpu 125 0 0 175 0 0 0 0\n",
            "cpu 200 0 0 200 0 0 0 0\n",
        ]})
        healthy = CpuCollector(good_io)
        config = AppConfig(mount_points=("/",) if source_kind == "storage" else ())
        slots = (UUIDS[0],) if source_kind == "gpu" else ()
        frames = []
        async with running_monitor(tmp_path, (source, healthy)) as (monitor, state, log, clock, _):
            for timestamp in (0, 1, 2):
                await tick(monitor, clock, timestamp)
                current = objects(state)
                affected = current[source.spec.key]
                if timestamp == 0:
                    assert not affected.stale and values(affected)[field] == expected
                    assert await entries(log, tmp_path) == []
                elif timestamp == 1:
                    assert affected.stale and values(affected)[field] == expected
                    assert affected.history[-1].metrics is None
                    assert values(current[healthy.spec.key])["cpu_percent"] == 25
                    recorded = await entries(log, tmp_path)
                    assert len(recorded) == 1 and recorded[0]["kind"] == "parse"
                else:
                    assert not affected.stale and values(affected)[field] == recovered_value
                    assert affected.history[-1].metrics is not None
                    assert values(current[healthy.spec.key])["cpu_percent"] == 75
                    assert len(await entries(log, tmp_path)) == 1
                frames.append(compose_frame(state.snapshot(), config, TerminalSize(120, 36),
                    HostInfo("offline", "Linux"), datetime.now(timezone.utc), gpu_slots=slots))
                assert not frames[-1].too_small
            assert frames[0].regions == frames[1].regions == frames[2].regions
            assert "STALE" not in " ".join(cell.text for cell in frames[0].cells)
            assert "STALE" in " ".join(cell.text for cell in frames[1].cells)
            assert "STALE" not in " ".join(cell.text for cell in frames[2].cells)
        assert io.closed and good_io.closed

    asyncio.run(scenario())


def test_ram_byte_conversion_past_integer_string_limit_remains_exact_and_renderable():
    async def scenario():
        raw_total = "1" + "0" * 4299
        io = RawIO(texts={"/proc/meminfo": [f"MemTotal: {raw_total} kB\nMemAvailable: 0 kB\n"]})
        source = MemoryCollector(io)
        state = MonitorState((source.spec,), clock=lambda: 1)
        result = await source.collect()
        assert result.failure is None
        state.accept(result, sampled_at=1)
        snapshot = state.snapshot().objects[0]
        assert values(snapshot)["ram_total_bytes"] == 10**4299 * 1024
        assert values(snapshot)["ram_used_bytes"] == 10**4299 * 1024
        assert values(snapshot)["ram_percent"] == 100
        rendered = frame(state)
        assert not rendered.too_small
        assert "100%" in " ".join(cell.text for cell in rendered.cells)
        await source.close()
        assert io.closed

    asyncio.run(scenario())
