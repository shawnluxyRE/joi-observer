"""REQ-002 原始离线材料到公开采集结果的黑盒契约。

不访问本机 proc、GPU 或挂载点；HardwareIO 只替代原始 IO，不预计算业务结果。
未实现入口应当失败，不能将 NotImplementedError、xfail 或 skip 视为验收成功。
"""

import asyncio
from collections import deque

import pytest

from joi_observer.collectors.hardware import (
    CommandOutput,
    CpuCollector,
    FileSystemStat,
    GpuCollector,
    GpuDiscovery,
    LocalHardwareIO,
    MemoryCollector,
    StorageCollector,
    build_hardware_sources,
)
from joi_observer.config import AppConfig
from joi_observer.data.models import ObjectKey
from joi_observer.data.state import MonitorState
from joi_observer.error_log import ErrorKind


UUIDS = tuple(f"GPU-00000000-0000-0000-0000-{index:012d}" for index in range(5))
GPU_QUERY = (
    "nvidia-smi",
    "--query-gpu=index,uuid,name,utilization.gpu,memory.used,memory.total,temperature.gpu,power.draw",
    "--format=csv,noheader,nounits",
)
DISCOVERY_QUERY = (
    "nvidia-smi", "--query-gpu=index,uuid", "--format=csv,noheader,nounits",
)
MOUNTINFO = "/proc/self/mountinfo"
ROOT = "20 1 8:1 / / rw,relatime - ext4 /dev/sda1 rw\n"
DATA = "31 20 8:2 / /data rw,relatime - ext4 /dev/sdb1 rw\n"


class RawIO:
    """按调用返回原始材料，记录调用以发现父路径回退及跨卡批量查询。"""

    def __init__(self, *, texts=None, stats=(), outputs=()):
        self.texts = {path: deque(values) for path, values in (texts or {}).items()}
        self.stats = deque(stats)
        self.outputs = deque(outputs)
        self.calls = []
        self.closed = False

    @staticmethod
    def next_value(values):
        assert values, "Unexpected extra IO operation"
        result = values.popleft()
        if isinstance(result, BaseException):
            raise result
        return result

    async def read_text(self, path):
        self.calls.append(("read_text", path))
        await asyncio.sleep(0)
        return self.next_value(self.texts[path])

    async def statvfs(self, path):
        self.calls.append(("statvfs", path))
        await asyncio.sleep(0)
        return self.next_value(self.stats)

    async def run(self, argv):
        self.calls.append(("run", argv))
        await asyncio.sleep(0)
        return self.next_value(self.outputs)

    async def close(self):
        self.closed = True


def values(result):
    return {metric.name: metric.value for metric in result.metrics}


def units(result):
    return {metric.name: metric.unit for metric in result.metrics}


def assert_failure(result, kind, code):
    assert result.failure is not None
    assert result.failure.kind is kind
    assert result.failure.code == code
    assert "PRIVATE" not in result.failure.reason


async def collect_many(collector, count):
    return [await collector.collect() for _ in range(count)]


def gpu_row(index=0, *, uuid=None, name=None, utilization="50", used="4096",
            total="24576", temperature="61", power="123.5"):
    return ", ".join((str(index), uuid or UUIDS[index], name or f"Offline GPU {index}",
                      utilization, used, total, temperature, power)) + "\n"


def test_collectors_construct_unknown_templates_without_io():
    io = RawIO()
    sources = (CpuCollector(io), MemoryCollector(io), StorageCollector(0, "/", io),
               GpuCollector(UUIDS[0], io), GpuDiscovery(io))
    assert [source.spec.key for source in sources] == [
        ObjectKey("host", "cpu"), ObjectKey("host", "ram"),
        ObjectKey("storage", "mount-0"), ObjectKey("gpu", UUIDS[0]),
        ObjectKey("gpu_inventory", "local"),
    ]
    assert all(metric.value is None for source in sources for metric in source.spec.metrics)
    assert io.calls == []


def test_cpu_uses_aggregate_ticks_and_does_not_double_count_guest():
    io = RawIO(texts={"/proc/stat": [
        "cpu 100 20 30 400 50 10 20 5 4 1\ncpu0 999 0 0 0 0 0 0 0\n",
        "cpu 140 30 50 420 55 12 22 6 34 6\ncpu0 999 0 0 0 0 0 0 0\n",
    ]})
    first, second = asyncio.run(collect_many(CpuCollector(io), 2))
    assert first.failure is None and values(first) == {"cpu_percent": None}
    assert second.failure is None and values(second) == {"cpu_percent": 75.0}
    assert units(second) == {"cpu_percent": "%"}
    assert io.calls == [("read_text", "/proc/stat")] * 2


def test_cpu_true_zero_all_busy_and_no_new_ticks_are_distinct():
    io = RawIO(texts={"/proc/stat": [
        "cpu 100 0 0 900 0 0 0 0\n", "cpu 100 0 0 1000 0 0 0 0\n",
        "cpu 200 0 0 1000 0 0 0 0\n", "cpu 200 0 0 1000 0 0 0 0\n",
    ]})
    results = asyncio.run(collect_many(CpuCollector(io), 4))
    assert [values(result)["cpu_percent"] for result in results] == [None, 0.0, 100.0, None]
    assert all(result.failure is None for result in results)


def test_cpu_counter_rollback_rebases_without_negative_or_spike():
    io = RawIO(texts={"/proc/stat": [
        "cpu 100 0 0 1000 50 0 0 0\n", "cpu 110 0 0 1100 40 0 0 0\n",
        "cpu 160 0 0 1150 40 0 0 0\n",
    ]})
    results = asyncio.run(collect_many(CpuCollector(io), 3))
    assert [values(result)["cpu_percent"] for result in results] == [None, None, 50.0]
    assert all(result.failure is None for result in results)


def test_cpu_failure_breaks_baseline_and_recovery_needs_new_interval():
    io = RawIO(texts={"/proc/stat": [
        "cpu 100 0 0 100 0 0 0 0\n", PermissionError("PRIVATE denied"),
        "cpu 900 0 0 200 0 0 0 0\n", "cpu 925 0 0 275 0 0 0 0\n",
    ]})
    first, failed, recovered, next_sample = asyncio.run(collect_many(CpuCollector(io), 4))
    assert values(first) == {"cpu_percent": None}
    assert_failure(failed, ErrorKind.PERMISSION, "access.denied")
    assert failed.metrics == ()
    assert recovered.failure is None and values(recovered) == {"cpu_percent": None}
    assert next_sample.failure is None and values(next_sample) == {"cpu_percent": 25.0}


def test_cpu_cancellation_propagates_and_invalidates_the_previous_baseline(capsys):
    async def scenario():
        io = RawIO(texts={"/proc/stat": [
            "cpu 100 0 0 100 0 0 0 0\n", asyncio.CancelledError(),
            "cpu 900 0 0 200 0 0 0 0\n", "cpu 925 0 0 275 0 0 0 0\n",
        ]})
        collector = CpuCollector(io)
        first = await collector.collect()
        with pytest.raises(asyncio.CancelledError):
            await collector.collect()
        recovered = await collector.collect()
        next_sample = await collector.collect()
        return first, recovered, next_sample, io
    first, recovered, next_sample, io = asyncio.run(scenario())
    assert first.failure is None and values(first) == {"cpu_percent": None}
    assert recovered.failure is None and values(recovered) == {"cpu_percent": None}
    assert next_sample.failure is None and values(next_sample) == {"cpu_percent": 25.0}
    assert io.calls == [("read_text", "/proc/stat")] * 4
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("raw", [
    "cpu0 1 2 3 4 5 6 7 8\n", "cpu 1 2 3\n", "cpu 1 2 3 4 5 6 7 nan\n",
    "cpu 1 2 3 -4 5 6 7 8\n", "cpu 1 2 3 4.5 5 6 7 8\n",
])
def test_cpu_invalid_raw_material_is_failure_not_zero(raw):
    result = asyncio.run(CpuCollector(RawIO(texts={"/proc/stat": [raw]})).collect())
    assert_failure(result, ErrorKind.PARSE, "response.invalid")
    assert result.metrics == ()


@pytest.mark.parametrize("available,used,percent", [(8192, 0, 0.0), (6144, 2097152, 25.0), (0, 8388608, 100.0)])
def test_ram_uses_available_and_consistent_binary_byte_numerator(available, used, percent):
    raw = f"MemTotal: 8192 kB\nMemFree: 16 kB\nMemAvailable: {available} kB\nCached: 1000 kB\n"
    result = asyncio.run(MemoryCollector(RawIO(texts={"/proc/meminfo": [raw]})).collect())
    assert result.failure is None
    assert values(result) == {"ram_used_bytes": used, "ram_total_bytes": 8388608, "ram_percent": percent}
    assert units(result) == {"ram_used_bytes": "B", "ram_total_bytes": "B", "ram_percent": "%"}


@pytest.mark.parametrize("raw", [
    "MemTotal: 0 kB\nMemAvailable: 0 kB\n",
    "MemTotal: 100 kB\nMemAvailable: 101 kB\n",
    "MemTotal: 100 kB\nMemAvailable: -1 kB\n",
    "MemTotal: 100 kB\nMemFree: 20 kB\n",
    "MemTotal: 100 MB\nMemAvailable: 20 kB\n",
    "MemTotal: 100 kB\nMemAvailable: nan kB\n",
    "MemTotal: 100 kB\nMemTotal: 100 kB\nMemAvailable: 20 kB\n",
])
def test_ram_missing_or_invalid_required_fields_do_not_fall_back_to_memfree(raw):
    result = asyncio.run(MemoryCollector(RawIO(texts={"/proc/meminfo": [raw]})).collect())
    assert_failure(result, ErrorKind.PARSE, "response.invalid")
    assert result.metrics == ()


def test_ram_failure_does_not_change_successful_cpu_result():
    async def scenario():
        cpu = CpuCollector(RawIO(texts={"/proc/stat": [
            "cpu 0 0 0 100 0 0 0 0\n", "cpu 40 0 0 160 0 0 0 0\n",
        ]}))
        ram = MemoryCollector(RawIO(texts={"/proc/meminfo": [OSError("PRIVATE broken source")]}))
        await cpu.collect()
        return await asyncio.gather(cpu.collect(), ram.collect())
    cpu, ram = asyncio.run(scenario())
    assert cpu.failure is None and values(cpu) == {"cpu_percent": 40.0}
    assert_failure(ram, ErrorKind.UNAVAILABLE, "source.unavailable")


@pytest.mark.parametrize("mount,index,raw", [("/", 0, ROOT), ("/data", 1, ROOT + DATA)])
def test_storage_counts_all_blocks_and_verifies_same_mount_before_and_after(mount, index, raw):
    io = RawIO(texts={MOUNTINFO: [raw, raw]}, stats=[FileSystemStat(4096, 1000, 250)])
    result = asyncio.run(StorageCollector(index, mount, io).collect())
    assert result.key == ObjectKey("storage", f"mount-{index}")
    assert result.failure is None
    assert values(result) == {"used_bytes": 3072000, "total_bytes": 4096000, "used_percent": 75.0}
    assert io.calls == [("read_text", MOUNTINFO), ("statvfs", mount), ("read_text", MOUNTINFO)]


@pytest.mark.parametrize("mount", ["/data", "/data/subdir", "/missing", "/data-link"])
def test_storage_requires_exact_mount_not_parent_or_existing_directory(mount):
    # statvfs would succeed on an ordinary directory; it must not be queried here.
    raw = ROOT if mount == "/data" else ROOT + DATA
    io = RawIO(texts={MOUNTINFO: [raw]}, stats=[FileSystemStat(4096, 1000, 500)])
    result = asyncio.run(StorageCollector(1, mount, io).collect())
    assert_failure(result, ErrorKind.NOT_FOUND, "object.not_found")
    assert result.metrics == () and io.calls == [("read_text", MOUNTINFO)]


def test_storage_supports_mountinfo_escaped_spaces_and_long_path_identity():
    path = "/data space/" + "x" * 140
    escaped = path.replace(" ", r"\040")
    raw = ROOT + f"32 20 8:3 / {escaped} rw - ext4 /dev/sdc1 rw\n"
    io = RawIO(texts={MOUNTINFO: [raw, raw]}, stats=[FileSystemStat(4096, 100, 100)])
    result = asyncio.run(StorageCollector(2, path, io).collect())
    assert result.key == ObjectKey("storage", "mount-2")
    assert result.failure is None and values(result)["used_percent"] == 0.0
    assert ("statvfs", path) in io.calls


@pytest.mark.parametrize("mount", ["/data/", "/data//"])
def test_storage_trailing_slashes_do_not_turn_valid_mount_into_missing(mount):
    io = RawIO(texts={MOUNTINFO: [ROOT + DATA, ROOT + DATA]}, stats=[FileSystemStat(4096, 100, 0)])
    result = asyncio.run(StorageCollector(0, mount, io).collect())
    assert result.failure is None and values(result)["used_percent"] == 100.0


@pytest.mark.parametrize("after", [ROOT, ROOT + DATA.replace("31 20", "41 20"),
                                      ROOT + DATA.replace("8:2", "8:3"),
                                      ROOT + DATA.replace("8:2 / /data", "8:2 /subdir /data")])
def test_storage_mount_disappearing_or_replaced_during_sample_discards_values(after):
    io = RawIO(texts={MOUNTINFO: [ROOT + DATA, after]}, stats=[FileSystemStat(4096, 1000, 250)])
    result = asyncio.run(StorageCollector(1, "/data", io).collect())
    assert_failure(result, ErrorKind.UNAVAILABLE, "source.unavailable")
    assert result.metrics == ()


def test_storage_ambiguous_stacked_mounts_do_not_guess_visible_layer():
    raw = ROOT + DATA + "45 20 8:3 / /data rw - ext4 /dev/sdc1 rw\n"
    io = RawIO(texts={MOUNTINFO: [raw]}, stats=[FileSystemStat(4096, 1000, 250)])
    result = asyncio.run(StorageCollector(1, "/data", io).collect())
    assert_failure(result, ErrorKind.UNAVAILABLE, "source.unavailable")
    assert result.metrics == () and io.calls == [("read_text", MOUNTINFO)]


@pytest.mark.parametrize("counts", [FileSystemStat(0, 100, 50), FileSystemStat(4096, 0, 0),
                                       FileSystemStat(4096, 100, -1), FileSystemStat(4096, 100, 101)])
def test_storage_invalid_capacity_is_failure(counts):
    io = RawIO(texts={MOUNTINFO: [ROOT + DATA, ROOT + DATA]}, stats=[counts])
    result = asyncio.run(StorageCollector(1, "/data", io).collect())
    assert_failure(result, ErrorKind.PARSE, "response.invalid")
    assert result.metrics == ()


def test_storage_first_failure_then_mount_recovery_keeps_its_identity():
    io = RawIO(texts={MOUNTINFO: [ROOT, ROOT + DATA, ROOT + DATA]}, stats=[FileSystemStat(4096, 100, 25)])
    failed, recovered = asyncio.run(collect_many(StorageCollector(1, "/data", io), 2))
    assert failed.key == recovered.key == ObjectKey("storage", "mount-1")
    assert_failure(failed, ErrorKind.NOT_FOUND, "object.not_found")
    assert recovered.failure is None and values(recovered)["used_percent"] == 75.0


@pytest.mark.parametrize("exception,kind,code", [
    (PermissionError("PRIVATE mount permission"), ErrorKind.PERMISSION, "access.denied"),
    (FileNotFoundError("PRIVATE missing mount"), ErrorKind.NOT_FOUND, "object.not_found"),
    (TimeoutError("PRIVATE blocked filesystem"), ErrorKind.TIMEOUT, "collection.timeout"),
    (OSError("PRIVATE IO failure"), ErrorKind.UNAVAILABLE, "source.unavailable"),
])
def test_storage_stat_failure_preserves_values_and_recovers_in_its_own_slot(exception, kind, code):
    async def scenario():
        io = RawIO(texts={MOUNTINFO: [ROOT + DATA] * 5}, stats=[
            FileSystemStat(4096, 100, 25), exception, FileSystemStat(4096, 100, 50),
        ])
        collector = StorageCollector(1, "/data", io)
        now = [0.0]
        state = MonitorState((collector.spec,), clock=lambda: now[0])
        results, snapshots = [], []
        for tick in (1, 2, 3):
            now[0] = tick
            result = await collector.collect()
            state.accept(result, sampled_at=tick)
            results.append(result)
            snapshots.append(state.snapshot().objects[0])
        return results, snapshots, io
    results, snapshots, io = asyncio.run(scenario())
    assert_failure(results[1], kind, code)
    assert values(snapshots[0])["used_percent"] == 75
    assert snapshots[1].stale and values(snapshots[1])["used_percent"] == 75
    assert not snapshots[2].stale and values(snapshots[2])["used_percent"] == 50
    assert all(snapshot.key == ObjectKey("storage", "mount-1") for snapshot in snapshots)
    assert [path for operation, path in io.calls if operation == "statvfs"] == ["/data"] * 3


def test_five_gpu_samples_are_independent_and_preserve_driver_units():
    async def scenario():
        ios = [RawIO(outputs=[CommandOutput(0, gpu_row(
            index, utilization=str(index * 20), used=str(index * 1024), total="24576",
            temperature=str(40 + index), power=str(100 + index + 0.5),
        ))]) for index in range(5)]
        results = await asyncio.gather(*(GpuCollector(uuid, io).collect() for uuid, io in zip(UUIDS, ios)))
        return results, ios
    results, ios = asyncio.run(scenario())
    for index, (result, io) in enumerate(zip(results, ios)):
        assert result.key == ObjectKey("gpu", UUIDS[index]) and result.failure is None
        assert values(result) == {
            "index": index, "name": f"Offline GPU {index}", "utilization_percent": index * 20,
            "memory_used_bytes": index * 1073741824, "memory_total_bytes": 25769803776,
            "temperature_c": 40 + index, "power_w": 100 + index + 0.5,
        }
        assert units(result)["memory_used_bytes"] == "B"
        assert units(result)["power_w"] == "W"
        assert io.calls == [("run", GPU_QUERY + (f"--id={UUIDS[index]}",))]


@pytest.mark.parametrize("marker", ["N/A", "[N/A]", "[Not Supported]"])
def test_gpu_known_unsupported_field_is_none_without_failure(marker):
    io = RawIO(outputs=[CommandOutput(0, gpu_row(power=marker))])
    result = asyncio.run(GpuCollector(UUIDS[0], io).collect())
    assert result.failure is None
    assert values(result)["power_w"] is None
    assert values(result)["utilization_percent"] == 50
    assert len(result.metrics) == 7


@pytest.mark.parametrize("bad", ["", "[Unknown Error]", "nan", "inf", "-1", "101"])
def test_gpu_bad_utilization_is_partial_failure_without_losing_other_fields(bad):
    io = RawIO(outputs=[CommandOutput(0, gpu_row(utilization=bad))])
    result = asyncio.run(GpuCollector(UUIDS[0], io).collect())
    assert_failure(result, ErrorKind.PARSE, "response.invalid")
    assert "utilization_percent" not in values(result)
    assert values(result)["memory_used_bytes"] == 4294967296
    assert values(result)["temperature_c"] == 61


@pytest.mark.parametrize("column,metric,bad", [("power", "power_w", "-0.5"),
                                                 ("power", "power_w", "nan"),
                                                 ("temperature", "temperature_c", "-1"),
                                                 ("temperature", "temperature_c", "inf")])
def test_gpu_bad_sensor_field_only_omits_that_field(column, metric, bad):
    io = RawIO(outputs=[CommandOutput(0, gpu_row(**{column: bad}))])
    result = asyncio.run(GpuCollector(UUIDS[0], io).collect())
    assert_failure(result, ErrorKind.PARSE, "response.invalid")
    assert metric not in values(result)
    assert values(result)["utilization_percent"] == 50
    assert values(result)["memory_used_bytes"] == 4294967296


def test_gpu_used_capacity_above_total_omits_the_pair_and_keeps_other_metrics():
    io = RawIO(outputs=[CommandOutput(0, gpu_row(used="24577", total="24576"))])
    result = asyncio.run(GpuCollector(UUIDS[0], io).collect())
    assert_failure(result, ErrorKind.PARSE, "response.invalid")
    assert "memory_used_bytes" not in values(result)
    assert "memory_total_bytes" not in values(result)
    assert values(result)["utilization_percent"] == 50
    assert values(result)["temperature_c"] == 61


@pytest.mark.parametrize("damaged_capacity", [
    {"used": "[Unknown Error]", "total": "4096"},
    {"used": "20480", "total": "bad"},
])
def test_gpu_capacity_parse_failure_preserves_the_pair_across_samples(damaged_capacity):
    async def scenario():
        io = RawIO(outputs=[
            CommandOutput(0, gpu_row(used="8192", total="16384", utilization="25")),
            CommandOutput(0, gpu_row(**damaged_capacity, utilization="50")),
            CommandOutput(0, gpu_row(used="2048", total="4096", utilization="0")),
        ])
        collector = GpuCollector(UUIDS[0], io)
        now = [0.0]
        state = MonitorState((collector.spec,), clock=lambda: now[0])
        results, snapshots = [], []
        for tick in (1, 2, 3):
            now[0] = tick
            result = await collector.collect()
            state.accept(result, sampled_at=tick)
            results.append(result)
            snapshots.append(state.snapshot().objects[0])
        return results, snapshots
    results, snapshots = asyncio.run(scenario())
    assert_failure(results[1], ErrorKind.PARSE, "response.invalid")
    assert "memory_used_bytes" not in values(results[1])
    assert "memory_total_bytes" not in values(results[1])
    healthy, failed, recovered = snapshots
    for snapshot in (healthy, failed):
        assert values(snapshot)["memory_used_bytes"] == 8589934592
        assert values(snapshot)["memory_total_bytes"] == 17179869184
    assert not healthy.stale and failed.stale and failed.history[-1].metrics is None
    assert values(failed)["utilization_percent"] == 50
    assert not recovered.stale
    assert values(recovered)["memory_used_bytes"] == 2147483648
    assert values(recovered)["memory_total_bytes"] == 4294967296
    assert values(recovered)["utilization_percent"] == 0


@pytest.mark.parametrize("raw", [gpu_row(uuid=UUIDS[1]), gpu_row() + gpu_row(),
                                     "0, invalid\n", "", gpu_row(index=0).replace("0, GPU-", "N/A, GPU-", 1)])
def test_gpu_invalid_identity_or_shape_rejects_entire_card(raw):
    result = asyncio.run(GpuCollector(UUIDS[0], RawIO(outputs=[CommandOutput(0, raw)])).collect())
    assert_failure(result, ErrorKind.PARSE, "response.invalid")
    assert result.metrics == ()


def test_gpu_partial_failure_uses_existing_state_retention_and_recovers():
    async def scenario():
        io = RawIO(outputs=[CommandOutput(0, gpu_row(utilization="20", power="100")),
                            CommandOutput(0, gpu_row(utilization="bad", power="125")),
                            CommandOutput(0, gpu_row(utilization="0", power="90"))])
        collector = GpuCollector(UUIDS[0], io)
        now = [0.0]
        state = MonitorState((collector.spec,), clock=lambda: now[0])
        snapshots = []
        for tick in (1, 2, 3):
            now[0] = tick
            state.accept(await collector.collect(), sampled_at=tick)
            snapshots.append(state.snapshot().objects[0])
        return snapshots
    healthy, failed, recovered = asyncio.run(scenario())
    assert not healthy.stale and values(healthy)["utilization_percent"] == 20
    assert failed.stale and values(failed)["utilization_percent"] == 20
    assert values(failed)["power_w"] == 125 and failed.history[-1].metrics is None
    assert not recovered.stale and values(recovered)["utilization_percent"] == 0
    assert failed.stale  # Previously published snapshot remains immutable.


def test_gpu_failure_isolated_from_other_card_and_ram(capsys):
    async def scenario():
        bad = GpuCollector(UUIDS[0], RawIO(outputs=[CommandOutput(9, "PRIVATE driver failure", "PRIVATE stderr")]))
        good = GpuCollector(UUIDS[1], RawIO(outputs=[CommandOutput(0, gpu_row(1))]))
        ram = MemoryCollector(RawIO(texts={"/proc/meminfo": ["MemTotal: 100 kB\nMemAvailable: 25 kB\n"]}))
        return await asyncio.gather(bad.collect(), good.collect(), ram.collect())
    bad, good, ram = asyncio.run(scenario())
    assert_failure(bad, ErrorKind.UNAVAILABLE, "source.unavailable")
    assert bad.metrics == ()
    assert good.failure is None and values(good)["index"] == 1
    assert ram.failure is None and values(ram)["ram_percent"] == 75.0
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("exception,kind,code", [
    (PermissionError("PRIVATE"), ErrorKind.PERMISSION, "access.denied"),
    (TimeoutError("PRIVATE"), ErrorKind.TIMEOUT, "collection.timeout"),
    (OSError("PRIVATE"), ErrorKind.UNAVAILABLE, "source.unavailable"),
])
def test_raw_io_exceptions_are_controlled_collection_failures(exception, kind, code):
    result = asyncio.run(GpuCollector(UUIDS[0], RawIO(outputs=[exception])).collect())
    assert_failure(result, kind, code)
    assert result.metrics == ()


def test_cancellation_propagates_without_converting_to_failure():
    async def scenario():
        collector = GpuCollector(UUIDS[0], RawIO(outputs=[asyncio.CancelledError()]))
        with pytest.raises(asyncio.CancelledError):
            await collector.collect()
    asyncio.run(scenario())


def test_gpu_discovery_preserves_output_order_and_only_declares_unknown_templates():
    raw = f"4, {UUIDS[4]}\n0, {UUIDS[0]}\n"
    io = RawIO(outputs=[CommandOutput(0, raw)])
    result = asyncio.run(GpuDiscovery(io).discover())
    assert result.inventory.key == ObjectKey("gpu_inventory", "local")
    assert result.inventory.failure is None and values(result.inventory) == {"device_count": 2}
    assert [spec.key for spec in result.specs] == [ObjectKey("gpu", UUIDS[4]), ObjectKey("gpu", UUIDS[0])]
    assert all(metric.value is None for spec in result.specs for metric in spec.metrics)
    assert io.calls == [("run", DISCOVERY_QUERY)]


@pytest.mark.parametrize("output", [CommandOutput(0, ""), CommandOutput(0, "\n"),
                                      CommandOutput(0, "No devices were found\n"),
                                      CommandOutput(6, "No devices were found\n")])
def test_successful_gpu_discovery_with_no_devices_is_not_an_error(output):
    result = asyncio.run(GpuDiscovery(RawIO(outputs=[output])).discover())
    assert result.inventory.failure is None
    assert values(result.inventory) == {"device_count": 0} and result.specs == ()


@pytest.mark.parametrize("output", [CommandOutput(9, "PRIVATE driver unavailable"),
                                      CommandOutput(6, "PRIVATE cannot access requested GPU"),
                                      CommandOutput(1, "", "PRIVATE permission or driver error")])
def test_discovery_command_failure_is_not_successful_zero_devices(output):
    result = asyncio.run(GpuDiscovery(RawIO(outputs=[output])).discover())
    assert_failure(result.inventory, ErrorKind.UNAVAILABLE, "source.unavailable")
    assert result.inventory.metrics == () and result.specs == ()


def test_missing_nvidia_smi_is_unavailable_not_no_gpu():
    result = asyncio.run(GpuDiscovery(RawIO(outputs=[FileNotFoundError("PRIVATE executable missing")])).discover())
    assert_failure(result.inventory, ErrorKind.UNAVAILABLE, "source.unavailable")
    assert result.specs == () and result.inventory.metrics == ()


def test_missing_nvidia_smi_during_card_query_is_unavailable_not_missing_card():
    result = asyncio.run(GpuCollector(UUIDS[0], RawIO(outputs=[FileNotFoundError("PRIVATE missing executable")])).collect())
    assert_failure(result, ErrorKind.UNAVAILABLE, "source.unavailable")
    assert result.metrics == ()


@pytest.mark.parametrize("raw", [
    f"0, {UUIDS[0]}\n1, {UUIDS[0]}\n", f"0, {UUIDS[0]}\n0, {UUIDS[1]}\n",
    f"-1, {UUIDS[0]}\n", f"0, {UUIDS[0]}, extra\n", "0, \n", "PRIVATE invalid output\n",
])
def test_malformed_discovery_is_atomic_failure_not_partial_device_list(raw):
    result = asyncio.run(GpuDiscovery(RawIO(outputs=[CommandOutput(0, raw)])).discover())
    assert_failure(result.inventory, ErrorKind.PARSE, "response.invalid")
    assert result.specs == () and result.inventory.metrics == ()


def test_hardware_factory_limits_only_mounts_and_performs_no_io(monkeypatch):
    def forbid_io(*args, **kwargs):
        pytest.fail("Factory must not perform IO")
    for method in ("read_text", "statvfs", "run"):
        monkeypatch.setattr(LocalHardwareIO, method, forbid_io)
    config = AppConfig(mount_points=("/", "/data", "/archive", "/ignored"), collection_timeout=2.5)
    sources = build_hardware_sources(config)
    assert [source.spec.key for source in sources.collectors] == [
        ObjectKey("host", "cpu"), ObjectKey("host", "ram"),
        ObjectKey("storage", "mount-0"), ObjectKey("storage", "mount-1"), ObjectKey("storage", "mount-2"),
    ]
    mounts = [source for source in sources.collectors if isinstance(source, StorageCollector)]
    assert [source.mount_point for source in mounts] == ["/", "/data", "/archive"]
    assert config.mount_points == ("/", "/data", "/archive", "/ignored")
    assert sources.discovery.spec.key == ObjectKey("gpu_inventory", "local")
    assert sources.discovery.timeout == 2.5
    assert all(source.io.timeout == 2.5 for source in sources.collectors)
    assert len({id(source.io) for source in (*sources.collectors, sources.discovery)}) == 6


@pytest.mark.parametrize("mounts", [(), ("/",), ("/", "/data"), ("/", "/data", "/archive")])
def test_hardware_factory_keeps_zero_to_three_mount_order(mounts):
    sources = build_hardware_sources(AppConfig(mount_points=mounts))
    assert [source.mount_point for source in sources.collectors if isinstance(source, StorageCollector)] == list(mounts)
    assert len(sources.collectors) == 2 + len(mounts)


@pytest.mark.parametrize("factory", [CpuCollector, MemoryCollector,
                                       lambda io: StorageCollector(0, "/", io),
                                       lambda io: GpuCollector(UUIDS[0], io), GpuDiscovery])
def test_hardware_close_is_idempotent_and_only_closes_owned_io(factory):
    async def scenario():
        own, other = RawIO(), RawIO()
        source = factory(own)
        await source.close()
        await source.close()
        assert own.closed and not other.closed
    asyncio.run(scenario())
