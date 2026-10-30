"""Additional raw-input boundaries for the REQ-002 hardware collectors."""

import asyncio

import pytest

from joi_observer.collectors import hardware
from joi_observer.collectors.hardware import (
    CommandOutput, CpuCollector, FileSystemStat, GpuCollector, GpuDiscovery,
    MemoryCollector, StorageCollector,
)
from joi_observer.data.models import Metric, ObjectKey, ObjectSpec
from joi_observer.data.state import MonitorState
from joi_observer.error_log import ErrorKind
from test_hardware import DATA, MOUNTINFO, ROOT, UUIDS, RawIO, assert_failure, gpu_row, values


def test_duplicate_cpu_aggregate_invalidates_baseline_until_two_healthy_samples():
    async def scenario():
        first = "cpu 100 0 0 100 0 0 0 0\n"
        io = RawIO(texts={"/proc/stat": [first, first + first,
            "cpu 500 0 0 100 0 0 0 0\n", "cpu 525 0 0 175 0 0 0 0\n"]})
        source = CpuCollector(io)
        return [await source.collect() for _ in range(4)]
    first, failed, recovered, current = asyncio.run(scenario())
    assert values(first)["cpu_percent"] is None
    assert_failure(failed, ErrorKind.PARSE, "response.invalid")
    assert values(recovered)["cpu_percent"] is None
    assert values(current)["cpu_percent"] == 25


@pytest.mark.parametrize("raw", [
    "MemTotal: 100 kB\nMemAvailable: 10 kB\nMemAvailable: 10 kB\n",
    "MemTotal: 100 kB\nMemAvailable: 10 MB\n",
    "MemTotal: 100 kB\nMemAvailable: 1_0 kB\n",
])
def test_ram_rejects_duplicate_available_and_non_kernel_number_formats(raw):
    result = asyncio.run(MemoryCollector(RawIO(texts={"/proc/meminfo": [raw]})).collect())
    assert_failure(result, ErrorKind.PARSE, "response.invalid")
    assert result.metrics == ()


@pytest.mark.parametrize("raw", [
    "broken record\n", ROOT + DATA.replace(" - ", " "),
    ROOT + DATA.replace("8:2", "broken"), ROOT + DATA.replace("31 20", "x 20"),
    ROOT + DATA.replace("/data", r"/data\777"),
])
def test_malformed_mountinfo_fails_before_capacity_io(raw):
    io = RawIO(texts={MOUNTINFO: [raw]})
    result = asyncio.run(StorageCollector(0, "/data", io).collect())
    assert_failure(result, ErrorKind.PARSE, "response.invalid")
    assert result.metrics == () and io.calls == [("read_text", MOUNTINFO)]


@pytest.mark.parametrize("escaped,path", [
    (r"/data\011tab", "/data\ttab"),
    (r"/data\012line", "/data\nline"),
    (r"/data\134040", r"/data\040"),
])
def test_mount_escapes_decode_once_and_keep_the_configured_capacity_path(escaped, path):
    raw = ROOT + DATA.replace("/data", escaped)
    io = RawIO(texts={MOUNTINFO: [raw, raw]}, stats=[FileSystemStat(4096, 100, 20)])
    result = asyncio.run(StorageCollector(0, path, io).collect())
    assert result.failure is None and values(result)["used_percent"] == 80
    assert io.calls[1] == ("statvfs", path)


def test_normalized_mount_paths_still_require_unique_identity():
    raw = ROOT + DATA + DATA.replace("31 20", "41 20").replace("/data", "//data/")
    io = RawIO(texts={MOUNTINFO: [raw]})
    result = asyncio.run(StorageCollector(0, "/data/", io).collect())
    assert_failure(result, ErrorKind.UNAVAILABLE, "source.unavailable")
    assert io.calls == [("read_text", MOUNTINFO)]


@pytest.mark.parametrize("used,total,expected_used,expected_total", [
    ("N/A", "4096", None, 4294967296),
    ("2048", "[Not Supported]", 2147483648, None),
])
def test_known_unavailable_gpu_capacity_does_not_discard_the_other_capacity(
        used, total, expected_used, expected_total):
    result = asyncio.run(GpuCollector(UUIDS[0], RawIO(outputs=[
        CommandOutput(0, gpu_row(used=used, total=total)),
    ])).collect())
    assert result.failure is None
    assert values(result)["memory_used_bytes"] == expected_used
    assert values(result)["memory_total_bytes"] == expected_total


def test_gpu_csv_quoted_name_keeps_comma_without_changing_fields():
    result = asyncio.run(GpuCollector(UUIDS[0], RawIO(outputs=[
        CommandOutput(0, gpu_row(name='"NVIDIA, Test GPU"')),
    ])).collect())
    assert result.failure is None
    assert values(result)["name"] == "NVIDIA, Test GPU"
    assert values(result)["utilization_percent"] == 50


@pytest.mark.parametrize("power", ["1_0", "１", "1e999", "[Driver Error]"])
def test_gpu_non_driver_numeric_formats_are_partial_failures(power):
    result = asyncio.run(GpuCollector(UUIDS[0], RawIO(outputs=[
        CommandOutput(0, gpu_row(power=power)),
    ])).collect())
    assert_failure(result, ErrorKind.PARSE, "response.invalid")
    assert "power_w" not in values(result)
    assert values(result)["utilization_percent"] == 50


@pytest.mark.parametrize("raw", [f"0, GPU-prefix\n", f"0, {UUIDS[0]}suffix\n"])
def test_discovery_rejects_incomplete_or_extended_uuid(raw):
    result = asyncio.run(GpuDiscovery(RawIO(outputs=[CommandOutput(0, raw)])).discover())
    assert_failure(result.inventory, ErrorKind.PARSE, "response.invalid")
    assert result.specs == ()


@pytest.mark.parametrize("output", [
    CommandOutput(9, "No devices were found\n"),
    CommandOutput(6, "prefix No devices were found\n"),
])
def test_no_devices_phrase_cannot_hide_other_command_failures(output):
    result = asyncio.run(GpuDiscovery(RawIO(outputs=[output])).discover())
    assert_failure(result.inventory, ErrorKind.UNAVAILABLE, "source.unavailable")
    assert result.specs == ()


def test_gpu_factory_is_strict_and_creates_independent_owned_io(monkeypatch):
    class FactoryIO(RawIO):
        def __init__(self, *, timeout):
            super().__init__()
            self.timeout = timeout
    monkeypatch.setattr(hardware, "LocalHardwareIO", FactoryIO)
    discovery_io = RawIO()
    discovery = GpuDiscovery(discovery_io, timeout=2.25)
    specs = [ObjectSpec(ObjectKey("gpu", uuid), hardware.GPU_METRICS) for uuid in UUIDS[:2]]
    children = [discovery.create_collector(spec) for spec in specs]
    assert [child.spec for child in children] == specs
    assert len({id(source.io) for source in (discovery, *children)}) == 3
    assert all(child.io.timeout == 2.25 and not child.io.calls for child in children)
    invalid = (
        ObjectSpec(ObjectKey("host", UUIDS[0]), hardware.GPU_METRICS),
        ObjectSpec(ObjectKey("gpu", "GPU-prefix"), hardware.GPU_METRICS),
        ObjectSpec(ObjectKey("gpu", UUIDS[0]), (Metric("index", None),)),
    )
    for spec in invalid:
        with pytest.raises(ValueError):
            discovery.create_collector(spec)
    asyncio.run(children[0].close())
    assert children[0].io.closed and not children[1].io.closed and not discovery_io.closed


def test_bind_mount_capacity_survives_unrelated_mountinfo_reordering():
    # The bind root identifies a subtree, while the configured mountpoint is
    # the exact destination. Unrelated entries may reorder between snapshots.
    bind = "51 20 8:2 /models/current /data rw - ext4 /dev/sdb1 rw\n"
    unrelated = "61 20 0:9 / /run/user/1000 rw - tmpfs tmpfs rw\n"
    io = RawIO(texts={MOUNTINFO: [ROOT + bind + unrelated, unrelated + bind + ROOT]},
               stats=[FileSystemStat(4096, 1000, 750)])
    result = asyncio.run(StorageCollector(1, "/data", io).collect())
    assert result.failure is None
    assert values(result) == {
        "used_bytes": 1024000, "total_bytes": 4096000, "used_percent": 25.0,
    }
    assert io.calls == [("read_text", MOUNTINFO), ("statvfs", "/data"),
                        ("read_text", MOUNTINFO)]


@pytest.mark.parametrize("marker", ["N/A", "[N/A]", "[Not Supported]"])
def test_known_unsupported_gpu_fields_clear_old_values_and_recover_without_stale(marker):
    async def scenario():
        io = RawIO(outputs=[
            CommandOutput(0, gpu_row()),
            CommandOutput(0, gpu_row(power="[Unknown Error]")),
            CommandOutput(0, gpu_row(name=marker, utilization=marker, used=marker,
                                     total=marker, temperature=marker, power=marker)),
            CommandOutput(0, gpu_row(utilization="0", used="0", power="0")),
        ])
        source = GpuCollector(UUIDS[0], io)
        state = MonitorState((source.spec,), clock=lambda: 4)
        snapshots = []
        for tick in range(1, 5):
            state.accept(await source.collect(), sampled_at=tick)
            snapshots.append(state.snapshot().objects[0])
        return snapshots

    healthy, failed, unsupported, recovered = asyncio.run(scenario())
    assert not healthy.stale and failed.stale
    assert values(failed)["power_w"] == values(healthy)["power_w"] == 123.5
    assert not unsupported.stale
    assert values(unsupported) == {"index": 0, "name": None, "utilization_percent": None,
                                   "memory_used_bytes": None, "memory_total_bytes": None,
                                   "temperature_c": None, "power_w": None}
    assert unsupported.history[-1].metrics is not None
    assert not recovered.stale
    assert values(recovered)["utilization_percent"] == 0
    assert values(recovered)["memory_used_bytes"] == 0
    assert values(recovered)["power_w"] == 0


def test_gpu_capacity_conversion_overflow_retains_both_old_capacity_values():
    async def scenario():
        source = GpuCollector(UUIDS[0], RawIO(outputs=[
            CommandOutput(0, gpu_row(used="8192", total="16384")),
            CommandOutput(0, gpu_row(used="4096", total="1e308", utilization="0")),
        ]))
        state = MonitorState((source.spec,), clock=lambda: 2)
        state.accept(await source.collect(), sampled_at=1)
        damaged = await source.collect()
        state.accept(damaged, sampled_at=2)
        return damaged, state.snapshot().objects[0]

    damaged, snapshot = asyncio.run(scenario())
    assert_failure(damaged, ErrorKind.PARSE, "response.invalid")
    assert "memory_used_bytes" not in values(damaged)
    assert "memory_total_bytes" not in values(damaged)
    assert snapshot.stale and snapshot.history[-1].metrics is None
    assert values(snapshot)["memory_used_bytes"] == 8 * 2**30
    assert values(snapshot)["memory_total_bytes"] == 16 * 2**30
    assert values(snapshot)["utilization_percent"] == 0
