"""Real UI/client composition over memory transport and terminal boundaries."""

import asyncio

import pytest

from joi_observer.ipc.client import ConnectionFailure, SnapshotClient
from joi_observer.tui.layout import TerminalSize
from joi_observer.tui.session import TuiClientSession
from test_ipc_client import MemoryConnector, MemoryStream, frame


class MemoryTerminal:
    def __init__(self, keys=(), disconnect=None):
        self.keys = list(keys)
        self.events = []
        self.frames = []
        self.disconnect = disconnect

    def enter(self):
        self.events.append("enter")

    def restore(self):
        self.events.append("restore")

    def size(self):
        return TerminalSize(120, 40)

    def render(self, value):
        self.frames.append(value)

    async def read_key(self, timeout):
        if self.disconnect:
            self.disconnect.pending.put_nowait(None)
            self.disconnect = None
        await asyncio.sleep(min(timeout, 0.005))
        return self.keys.pop(0) if self.keys else None


def test_initial_connection_failure_does_not_enter_terminal():
    async def scenario():
        terminal = MemoryTerminal()
        connector = MemoryConnector(error=OSError("unavailable"))
        session = TuiClientSession(SnapshotClient(connector=connector), terminal)
        with pytest.raises(ConnectionFailure):
            await session.run()
        assert "enter" not in terminal.events and len(connector.calls) == 1
    asyncio.run(scenario())


def test_mid_session_disconnect_restores_before_error_escapes():
    async def scenario():
        stream = MemoryStream(frame())
        terminal = MemoryTerminal(disconnect=stream)
        connector = MemoryConnector(stream)
        session = TuiClientSession(SnapshotClient(connector=connector), terminal)
        with pytest.raises(ConnectionFailure):
            await asyncio.wait_for(session.run(), 0.5)
        assert terminal.events[0] == "enter" and terminal.events[-1] == "restore"
        assert terminal.frames and stream.closed and len(connector.calls) == 1
    asyncio.run(scenario())


def test_stalled_receive_does_not_block_theme_keys_or_normal_exit():
    async def scenario():
        stream = MemoryStream(frame(stale=True))
        terminal = MemoryTerminal(("t", None, None, None, None, "q"))
        session = TuiClientSession(SnapshotClient(connector=MemoryConnector(stream)), terminal)
        await asyncio.wait_for(session.run(), 0.5)
        assert {value.theme for value in terminal.frames} == {"hologram", "moonlight"}
        assert terminal.events[-1] == "restore" and stream.closed
    asyncio.run(scenario())


@pytest.mark.parametrize("small", (False, True), ids=("normal", "small-window"))
def test_real_session_keeps_unselected_history_scale_delay_across_heartbeats(monkeypatch, small):
    """The formal session must preserve the old app's scan/scale contract."""
    from copy import deepcopy
    from dataclasses import replace
    from joi_observer.ipc.protocol import SnapshotEnvelope, build_metadata, encode_envelope
    from test_history_app import HOST, NOW, Terminal, inputs, labels

    async def scenario():
        config, original = inputs()
        before = deepcopy(original)
        metadata = build_metadata(config, hostname=HOST.hostname, system=HOST.system)
        clock = [100.0]
        sequence = [1]

        def published(at):
            data = replace(original, objects=tuple(replace(item, history=tuple(
                point for point in item.history if at - 60 <= point.sampled_at <= at
            )) for item in original.objects))
            return encode_envelope(SnapshotEnvelope("scale-instance", "scale-config",
                                                    sequence[0], at, metadata, data))

        stream = MemoryStream(published(100.0))
        connector = MemoryConnector(stream)
        client = SnapshotClient(connector=connector)

        class HeartbeatTerminal(Terminal):
            async def read_key(self, timeout):
                assert 0 < timeout <= 0.05
                when, key = self.schedule[self.index]
                self.index += 1
                clock[0] = when
                sequence[0] += 1
                stream.pending.put_nowait(published(when))
                while client.envelope().sequence != sequence[0]:
                    await asyncio.sleep(0)
                return key

        terminal = HeartbeatTerminal(clock, ((101, "down"), (103, "t"), (105.9, "up"),
                                              (106, None), (107, "q")),
                                     small_at=(103,) if small else ())
        session = TuiClientSession(client, terminal, wall_clock=lambda: NOW)
        with monkeypatch.context() as patch:
            patch.setattr(asyncio.get_running_loop(), "time", lambda: clock[0])
            patch.setattr("joi_observer.tui.layout.time.monotonic", lambda: clock[0])
            await session.run()
        observed = dict(terminal.frames)
        assert labels(observed[100]) == ["Scale ≤ 200 tok/s"]
        assert labels(observed[101]) == ["Scale ≤ 10 seq/s"]
        assert observed[103].too_small is small
        assert labels(observed[105.9]) == ["Scale ≤ 200 tok/s"]
        assert labels(observed[106]) == ["Scale ≤ 50 tok/s"]
        assert observed[106].theme == "moonlight"
        assert original == before
        assert terminal.events == ["enter", "restore"] and stream.closed
        assert len(connector.calls) == 1

    asyncio.run(scenario())
