"""Two browser requests and a host client consume one offline sampling service."""

import asyncio
from pathlib import Path
import time

from joi_observer.collectors.hardware import CpuCollector
from joi_observer.data.state import MonitorState
from joi_observer.ipc.client import SnapshotClient
from joi_observer.monitor import Monitor
from joi_observer.runtime import CollectorComponents, CollectorRuntime
from joi_observer.service import CollectorService
from joi_observer.web.app import create_app

from test_hardware import RawIO
from test_service_contract import MemoryLease, MemoryListener, MemoryLog, runtime_fixture, until
from test_web_api import HttpRequest, lifespan


class MemoryPipe:
    """One full-duplex OS transport substitute with EOF in both directions."""

    def __init__(self):
        self.reader = asyncio.StreamReader()
        self.closed = asyncio.Event()

    async def send(self, data):
        if self.closed.is_set():
            raise BrokenPipeError()
        self.reader.feed_data(data)

    async def receive(self, max_bytes):
        await self.closed.wait()
        return b""

    async def readexactly(self, size):
        return await self.reader.readexactly(size)

    async def close(self):
        self.closed.set()
        self.reader.feed_eof()


class MountedEndpoint:
    """Route each explicit connector attempt to the real publisher's accept port."""

    def __init__(self, listener):
        self.listener = listener
        self.connections = []

    async def connect(self, endpoint):
        assert endpoint == Path("/run/joi-observer/snapshot.sock")
        pipe = MemoryPipe()
        self.connections.append(pipe)
        self.listener.peers.put_nowait(pipe)
        return pipe


async def browser_revision(page, expected):
    async with asyncio.timeout(3):
        while True:
            frame = await page.frame()
            if frame["snapshot"]["revision"] >= expected:
                return frame


def test_browser_fanout_and_web_recreation_preserve_one_host_sampling_schedule(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")

    async def scenario():
        # Move only the sampling clock; the publisher uses the host monotonic clock.
        base = time.monotonic() - 10
        now = [base]
        raw = RawIO(texts={"/proc/stat": [
            "cpu 100 0 0 100 0 0 0 0\n",   # establish baseline without any viewer
            "cpu 125 0 0 175 0 0 0 0\n",   # 25% while two pages and a host client view it
            "cpu 175 0 0 225 0 0 0 0\n",   # 50% while the Web application is stopped
        ]})
        runtimes = []

        def build_runtime(config):
            collector = CpuCollector(raw)
            state = MonitorState((collector.spec,), clock=lambda: now[0])
            updates, log = asyncio.Event(), MemoryLog()
            monitor = Monitor((collector,), state, log, interval=config.sample_interval,
                              clock=lambda: now[0], on_update=updates.set)
            runtime = CollectorRuntime(config, components=CollectorComponents(state, monitor, log, updates))
            runtimes.append(runtime)
            return runtime

        listener = MemoryListener()
        service = CollectorService(config_path, runtime_factory=build_runtime, listener=listener,
                                   lease=MemoryLease(), host_factory=lambda: ("batch-host", "Ubuntu 24.04"))
        web_mount, tui_mount = MountedEndpoint(listener), MountedEndpoint(listener)
        tui = SnapshotClient(connector=tui_mount)
        stop = asyncio.Event()
        running = asyncio.create_task(service.run(stop))
        try:
            await until(lambda: runtimes and runtimes[0].snapshot().revision == 1, running)
            assert len(raw.calls) == 1
            await tui.connect()
            app = create_app(connector=web_mount)
            async with lifespan(app):
                assert not web_mount.connections
                async with HttpRequest(app) as left, HttpRequest(app) as right:
                    for page in (left, right):
                        assert (await page.response())[0] == 200
                        initial = await browser_revision(page, 1)
                        assert initial["metadata"]["hostname"] == "batch-host"
                        assert initial["snapshot"]["objects"][0]["metrics"][0]["value"] is None
                    assert len(web_mount.connections) == 1 and len(raw.calls) == 1
                    now[0] = base + 1
                    left_frame, right_frame = await asyncio.gather(
                        browser_revision(left, 2), browser_revision(right, 2))
                    await until(lambda: tui.snapshot().revision == 2, running)
                    assert left_frame["snapshot"] == right_frame["snapshot"]
                    cpu, = left_frame["snapshot"]["objects"]
                    assert cpu["key"] == {"collector": "host", "object_id": "cpu"}
                    assert cpu["metrics"] == [
                        {"name": "cpu_percent", "value": 25.0, "unit": "%", "applicable": True}
                    ]
                    assert tui.snapshot().objects[0].metrics[0].value == 25.0
                    assert len(raw.calls) == 2
            assert web_mount.connections[0].closed.is_set()
            now[0] = base + 2
            await until(lambda: tui.snapshot().revision == 3, running)
            assert tui.snapshot().objects[0].metrics[0].value == 50.0 and not raw.closed
            rebuilt = create_app(connector=web_mount)
            async with lifespan(rebuilt), HttpRequest(rebuilt) as refreshed:
                assert (await refreshed.response())[0] == 200
                current = await browser_revision(refreshed, 3)
                assert current["instance_id"] == left_frame["instance_id"]
                assert current["snapshot"]["objects"][0]["metrics"][0]["value"] == 50.0
            assert len(runtimes) == 1 and len(raw.calls) == 3
            assert len(web_mount.connections) == 2 and len(tui_mount.connections) == 1
        finally:
            await tui.close()
            stop.set()
            await asyncio.wait_for(running, 1.5)
        assert raw.closed

    asyncio.run(scenario())


def test_service_restart_supplies_new_metadata_only_to_a_fresh_page_request(tmp_path):
    config_path = tmp_path / "config.yaml"

    async def scenario():
        async def start_host(mount_point):
            # Mount the directory once; each host start publishes a fresh endpoint in it.
            config_path.write_text(f"mount_points: ['{mount_point}']\n", encoding="utf-8")
            listener = MemoryListener()
            service = CollectorService(
                config_path, runtime_factory=lambda config: runtime_fixture(config)[0],
                listener=listener, lease=MemoryLease(), host_factory=lambda: ("host", "Ubuntu"),
            )
            stop = asyncio.Event()
            run = asyncio.create_task(service.run(stop))
            await until(listener.started.is_set, run)
            return listener, stop, run

        listener, stop, running = await start_host("/first")
        mount = MountedEndpoint(listener)
        try:
            app = create_app(connector=mount)
            async with lifespan(app), HttpRequest(app) as left, HttpRequest(app) as right:
                for page in (left, right):
                    assert (await page.response())[0] == 200
                    first = await page.frame()
                    assert first["metadata"]["mount_points"] == ["/first"]
                assert len(mount.connections) == 1
                stop.set()
                await asyncio.wait_for(running, 1.5)
                # EOF is permanent for both old response streams, including when
                # the second host comes up before either user refreshes.
                await asyncio.wait_for(asyncio.gather(left.finish(), right.finish()), 2)
                mount.listener, stop, running = await start_host("/second")
                assert len(mount.connections) == 1
                async with HttpRequest(app) as refreshed:
                    assert (await refreshed.response())[0] == 200
                    fresh = await refreshed.frame()
                    assert fresh["metadata"]["mount_points"] == ["/second"]
                    assert fresh["instance_id"] != first["instance_id"]
                    assert fresh["config_revision"] != first["config_revision"]
                    assert len(mount.connections) == 2
        finally:
            stop.set()
            await asyncio.wait_for(running, 1.5)

    asyncio.run(scenario())
