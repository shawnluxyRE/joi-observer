"""Safe local host presentation crosses the service boundary exactly once."""

import asyncio
from dataclasses import replace
import json
import locale
from pathlib import Path
import struct

import pytest

from joi_observer.config import AppConfig
from joi_observer.ipc.protocol import ProtocolError, decode_envelope, encode_envelope
from joi_observer.service import CollectorService
from test_service_contract import MemoryLease, MemoryListener, MemoryPeer, runtime_fixture, until


@pytest.mark.parametrize("field", ["hostname", "system"])
def test_local_host_labels_are_safe_without_terminal_locale_or_wire_relaxation(
        tmp_path, monkeypatch, field):
    async def scenario():
        raw = "\u0301设备\tA\u202eB\x00C\nD\u2028E\u2029F\u00a0G\ud800Z"
        expected = "\u0301设备 A B C D E F G Z"
        fields = {"hostname": "Local Host", "system": "Ubuntu 24.04"}
        fields[field] = raw
        calls = []

        def host_factory():
            calls.append(tuple(fields.values()))
            return fields["hostname"], fields["system"]

        def no_terminal_locale(*args, **kwargs):
            raise AssertionError("Service presentation must not query terminal locale")

        monkeypatch.setattr(locale, "setlocale", no_terminal_locale)
        config_path = tmp_path / "config.yaml"
        config_path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")
        runtime, source, log = runtime_fixture(AppConfig(sample_interval=0.02, mount_points=()))
        listener, peer, lease = MemoryListener(), MemoryPeer(), MemoryLease()
        await listener.peers.put(peer)
        service = CollectorService(config_path, runtime_factory=lambda _: runtime,
                                   listener=listener, lease=lease, host_factory=host_factory)
        stop = asyncio.Event()
        running = asyncio.create_task(service.run(stop))
        try:
            await until(lambda: source.calls >= 2 and bool(peer.frames), running)
            envelope = decode_envelope(peer.frames[-1])
            assert getattr(envelope.metadata, field) == expected
            other_field = "system" if field == "hostname" else "hostname"
            assert getattr(envelope.metadata, other_field) == fields[other_field]
            assert len(calls) == 1 and listener.start_calls == 1 and lease.held

            # The service owns presentation cleanup. Raw untrusted frames and
            # directly constructed metadata retain the strict protocol boundary.
            with pytest.raises(ProtocolError):
                encode_envelope(replace(envelope, metadata=replace(envelope.metadata, **{field: raw})))
            payload = json.loads(peer.frames[-1][8:].decode("utf-8"))
            payload["metadata"][field] = "untrusted\tlabel\u202e"
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            with pytest.raises(ProtocolError):
                decode_envelope(struct.pack(">Q", len(body)) + body)

            fields[field] = "Changed factory result"
            first_revision = envelope.snapshot.revision
            await until(lambda: source.calls >= 4, running)
            assert getattr(service.export_snapshot().metadata, field) == expected
            assert service.export_snapshot().snapshot.revision > first_revision
            assert len(calls) == 1
        finally:
            stop.set()
            await asyncio.gather(running, return_exceptions=True)
            await service.close()
        assert source.closed and log.closed and listener.closed and not lease.held

    asyncio.run(scenario())


def test_safe_release_metadata_keeps_single_read_priority_and_restart_freezing(tmp_path, monkeypatch):
    primary, vendor = tmp_path / "local-release", tmp_path / "vendor-release"
    primary.write_text('PRETTY_NAME="Ubuntu\t本地\u202e24.04"\n', encoding="utf-8")
    vendor.write_text('PRETTY_NAME="Vendor Release"\nVERSION_ID="99"\n', encoding="utf-8")
    monkeypatch.setattr("joi_observer._host._OS_RELEASE_PATHS", (primary, vendor))
    reads = []
    real_open = Path.open

    def observed_open(path, *args, **kwargs):
        mode = kwargs.get("mode", args[0] if args else "r")
        if path in (primary, vendor) and "r" in mode:
            reads.append(path)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observed_open)

    async def scenario():
        config_path = tmp_path / "config.yaml"
        config_path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")
        first_metadata = None
        for index, expected in enumerate(("Ubuntu 本地 24.04", "New Local Release")):
            runtime, source, log = runtime_fixture(AppConfig(sample_interval=0.02, mount_points=()))
            listener, peer, lease = MemoryListener(), MemoryPeer(), MemoryLease()
            await listener.peers.put(peer)
            service = CollectorService(config_path, runtime_factory=lambda _: runtime,
                                       listener=listener, lease=lease)
            stop = asyncio.Event()
            running = asyncio.create_task(service.run(stop))
            try:
                await until(lambda: source.calls >= 2 and bool(peer.frames), running)
                envelope = decode_envelope(peer.frames[-1])
                assert envelope.metadata.system == expected
                assert reads == [primary] * (index + 1)
                if first_metadata is None:
                    first_metadata = envelope.metadata
                    primary.write_text('PRETTY_NAME="New Local Release"\n', encoding="utf-8")
                    await until(lambda: source.calls >= 4, running)
                    assert service.export_snapshot().metadata == first_metadata
                    assert reads == [primary]
                else:
                    assert envelope.metadata != first_metadata
            finally:
                stop.set()
                await asyncio.gather(running, return_exceptions=True)
                await service.close()
            assert source.closed and log.closed and listener.closed and not lease.held

    asyncio.run(scenario())


@pytest.mark.parametrize("invalid", ["", None, 12, False])
def test_host_presentation_cleanup_does_not_infer_missing_or_invalid_labels(tmp_path, invalid):
    async def scenario():
        config_path = tmp_path / "config.yaml"
        config_path.write_text("mount_points: []\nsample_interval: 1\n", encoding="utf-8")
        runtime, source, log = runtime_fixture(AppConfig(sample_interval=0.02, mount_points=()))
        listener, lease = MemoryListener(), MemoryLease()
        service = CollectorService(config_path, runtime_factory=lambda _: runtime,
                                   listener=listener, lease=lease,
                                   host_factory=lambda: (invalid, "Ubuntu 24.04"))
        with pytest.raises(ProtocolError):
            await service.run(asyncio.Event())
        assert listener.start_calls == 0 and source.calls == 0
        assert source.closed and log.closed and not lease.held
        await service.close()

    asyncio.run(scenario())
