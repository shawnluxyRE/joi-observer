"""Offline adapter and cancellation coverage for the real client/codec worker."""

import asyncio
from io import StringIO
import json
from pathlib import Path
import struct

import pytest

from joi_observer.ipc import _worker
from joi_observer.cli import CommandDependencies, run_command
from joi_observer.ipc.client import ConnectionFailure, ConnectionState, SnapshotClient, UnixConnector
from joi_observer.ipc.protocol import IO_CHUNK_BYTES
from joi_observer.tui.session import TuiClientSession
from test_client_session import MemoryTerminal
from test_ipc_client import MemoryConnector, MemoryStream, frame
from test_ipc_protocol import large_snapshot_fixture


def test_real_two_model_sessions_keep_selection_through_resize_and_peer_exit():
    """AC-103/106/114: exercise selection through the real receive/UI wiring."""
    from joi_observer.config import ModelType
    from joi_observer.data.models import Metric, ObjectKey, ObjectSnapshot, StateSnapshot
    from joi_observer.ipc.protocol import DisplayMetadata, ModelDisplay, SnapshotEnvelope, encode_envelope
    from joi_observer.tui.layout import TerminalSize

    async def scenario():
        now = asyncio.get_running_loop().time()
        metadata = DisplayMetadata("Host", "Ubuntu 24.04", models=(
            ModelDisplay("a", ModelType.CHAT, "Same alias", "first/title", (), None, 80),
            ModelDisplay("b", ModelType.CHAT, "Same alias", "second/title", (), 8001, 8001),
        ))

        def published(sequence, running):
            snapshot = StateSnapshot(tuple(
                ObjectSnapshot(ObjectKey("vllm", model.id),
                               (Metric("running", running + index, "seq"),
                                Metric("waiting", 0, "seq"),
                                Metric("total", running + index, "seq")),
                               sampled_at=now)
                for index, model in enumerate(metadata.models)
            ), revision=sequence)
            return encode_envelope(SnapshotEnvelope("instance", "config", sequence,
                                                    now, metadata, snapshot))

        class ResizableTerminal(MemoryTerminal):
            dimensions = TerminalSize(120, 40)

            def size(self):
                return self.dimensions

        async def wait_until(predicate):
            async def poll():
                while not predicate():
                    await asyncio.sleep(0.005)
            await asyncio.wait_for(poll(), 1.0)

        def shows(terminal, title, theme):
            return bool(terminal.frames and terminal.frames[-1].theme == theme
                        and any(cell.text == title for cell in terminal.frames[-1].cells))

        left_stream, right_stream = MemoryStream(published(1, 10)), MemoryStream(published(1, 10))
        left_port, right_port = MemoryConnector(left_stream), MemoryConnector(right_stream)
        left_client, right_client = SnapshotClient(connector=left_port), SnapshotClient(connector=right_port)
        left, right = ResizableTerminal(), ResizableTerminal()
        sessions = (TuiClientSession(left_client, left), TuiClientSession(right_client, right))
        tasks = [asyncio.create_task(session.run()) for session in sessions]
        try:
            await wait_until(lambda: shows(left, "first/title", "hologram")
                             and shows(right, "first/title", "hologram"))
            left.keys.extend(("down", "t"))
            await wait_until(lambda: shows(left, "second/title", "moonlight"))
            assert shows(right, "first/title", "hologram")

            left.dimensions = TerminalSize(80, 20)
            await wait_until(lambda: left.frames[-1].too_small)
            left.keys.append("up")
            await wait_until(lambda: not left.keys)
            left.dimensions = TerminalSize(120, 40)
            await wait_until(lambda: shows(left, "first/title", "moonlight"))
            assert shows(right, "first/title", "hologram")

            left.keys.append("q")
            await asyncio.wait_for(tasks[0], 1.0)
            assert left_stream.closed and left.events[-1] == "restore"
            assert not tasks[1].done() and not right_stream.closed
            await right_stream.pending.put(published(2, 42))
            await wait_until(lambda: right_client.envelope().sequence == 2
                             and any(cell.text == "42" and cell.bold
                                     for cell in right.frames[-1].cells))
            assert shows(right, "first/title", "hologram")
            assert right_client.envelope().metadata == metadata
            assert len(left_port.calls) == len(right_port.calls) == 1
            right.keys.append("q")
            await asyncio.wait_for(tasks[1], 1.0)
            assert right_stream.closed and right.events[-1] == "restore"
            assert {value.theme for value in right.frames} == {"hologram"}
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.gather(*(session.close() for session in sessions))

    asyncio.run(scenario())


def test_unix_connector_uses_only_the_selected_local_endpoint(monkeypatch):
    async def scenario():
        calls = []

        class Reader:
            async def readexactly(self, count):
                calls.append(("read", count))
                return b"x" * count

        class Writer:
            def __init__(self):
                self.closed = False

            def close(self):
                self.closed = True

            async def wait_closed(self):
                pass

        reader, writer = Reader(), Writer()

        async def open_stream(path, *, limit):
            calls.append(("open", path, limit))
            return reader, writer

        monkeypatch.setattr(asyncio, "open_unix_connection", open_stream)
        connector = UnixConnector()
        assert calls == []
        stream = await connector.connect(Path("/run/offline-selected.sock"))
        assert await stream.readexactly(8) == b"x" * 8
        await stream.close()
        assert writer.closed
        assert calls == [("open", "/run/offline-selected.sock", IO_CHUNK_BYTES), ("read", 8)]
    asyncio.run(scenario())


def test_unix_close_aborts_a_stalled_os_writer_within_budget(monkeypatch):
    async def scenario():
        class Writer:
            def __init__(self):
                self.closed = False
                self.aborted = False
                self.transport = self

            def close(self):
                self.closed = True

            def abort(self):
                self.aborted = True

            async def wait_closed(self):
                await asyncio.Future()

        writer = Writer()

        async def open_stream(*args, **kwargs):
            return object(), writer

        monkeypatch.setattr(asyncio, "open_unix_connection", open_stream)
        stream = await UnixConnector().connect(Path("/run/offline.sock"))
        await asyncio.wait_for(stream.close(), 0.5)
        assert writer.closed and writer.aborted
    asyncio.run(scenario())


@pytest.mark.parametrize("stage", ["connector", "first-frame"])
def test_close_ends_an_inflight_first_connection(stage):
    async def scenario():
        entered = asyncio.Event()
        cancelled = asyncio.Event()
        stream = MemoryStream()

        class Connector:
            async def connect(self, endpoint):
                entered.set()
                if stage == "connector":
                    try:
                        await asyncio.Future()
                    finally:
                        cancelled.set()
                return stream

        client = SnapshotClient(connector=Connector())
        connecting = asyncio.create_task(client.connect())
        try:
            await entered.wait()
            await asyncio.sleep(0)
            await asyncio.wait_for(client.close(), 1.0)
            assert connecting.done(), "close must cancel the owned first-connection wait"
            with pytest.raises(asyncio.CancelledError):
                await connecting
            assert client.state is ConnectionState.CLOSED
            assert cancelled.is_set() if stage == "connector" else stream.closed
        finally:
            connecting.cancel()
            await asyncio.gather(connecting, return_exceptions=True)
            await client.close()
    asyncio.run(scenario())


def test_session_close_during_first_connection_does_not_enter_terminal():
    async def scenario():
        entered = asyncio.Event()

        class Connector:
            async def connect(self, endpoint):
                entered.set()
                await asyncio.Future()

        terminal = MemoryTerminal()
        session = TuiClientSession(SnapshotClient(connector=Connector()), terminal)
        running = asyncio.create_task(session.run())
        try:
            await entered.wait()
            await asyncio.wait_for(session.close(), 1.0)
            await asyncio.sleep(0)
            assert running.done()
            with pytest.raises(asyncio.CancelledError):
                await running
            assert not terminal.events
        finally:
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)
            await session.close()
    asyncio.run(scenario())


def test_late_connector_result_after_close_is_discarded_and_released():
    async def scenario():
        entered = asyncio.Event()
        stream = MemoryStream(frame())

        class Connector:
            async def connect(self, endpoint):
                entered.set()
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    # Emulate completion racing with cancellation at the OS
                    # boundary; even this complete real frame is no longer live.
                    return stream

        client = SnapshotClient(connector=Connector())
        connecting = asyncio.create_task(client.connect())
        try:
            await entered.wait()
            await asyncio.wait_for(client.close(), 1.0)
            with pytest.raises((ConnectionFailure, asyncio.CancelledError)):
                await connecting
            assert client.state is ConnectionState.CLOSED and stream.closed
            with pytest.raises(ConnectionFailure):
                client.envelope()
        finally:
            connecting.cancel()
            await asyncio.gather(connecting, return_exceptions=True)
            await client.close()
    asyncio.run(scenario())


def test_parallel_close_waits_for_the_same_receiver_cleanup():
    async def scenario():
        receive_cancelled = asyncio.Event()
        release = asyncio.Event()

        class Stream(MemoryStream):
            async def readexactly(self, count):
                try:
                    return await super().readexactly(count)
                except asyncio.CancelledError:
                    receive_cancelled.set()
                    await release.wait()
                    raise

        stream = Stream(frame())
        client = SnapshotClient(connector=MemoryConnector(stream))
        await client.connect()
        await asyncio.sleep(0)
        first = asyncio.create_task(client.close())
        second = None
        try:
            await receive_cancelled.wait()
            second = asyncio.create_task(client.close())
            await asyncio.sleep(0)
            assert not second.done(), "a repeated close must share in-progress cleanup"
            release.set()
            await asyncio.wait_for(asyncio.gather(first, second), 0.5)
            assert stream.closed and client.state is ConnectionState.CLOSED
        finally:
            release.set()
            await asyncio.gather(*(task for task in (first, second) if task is not None),
                                 return_exceptions=True)
    asyncio.run(scenario())


def test_large_codec_work_yields_to_the_ui_loop_and_roundtrips():
    async def scenario():
        expected, _ = large_snapshot_fixture(32)
        beats = []
        stop = asyncio.Event()

        async def pulse():
            while not stop.is_set():
                beats.append(asyncio.get_running_loop().time())
                await asyncio.sleep(0.005)

        pulse_task = asyncio.create_task(pulse())
        try:
            encoded = await asyncio.wait_for(_worker.encode_async(expected), 5.0)
            before_decode = len(beats)
            decoded = await asyncio.wait_for(_worker.decode_async(encoded), 5.0)
            assert decoded == expected
            assert before_decode >= 2 and len(beats) - before_decode >= 2
        finally:
            stop.set()
            await pulse_task
    asyncio.run(scenario())


def test_cancelling_large_codec_work_reaps_its_process(monkeypatch):
    async def scenario():
        expected, _ = large_snapshot_fixture()
        started = asyncio.Event()
        processes = []
        original = asyncio.create_subprocess_exec

        async def observed_start(*args, **kwargs):
            process = await original(*args, **kwargs)
            processes.append(process)
            started.set()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", observed_start)
        task = asyncio.create_task(_worker.encode_async(expected))
        try:
            await asyncio.wait_for(started.wait(), 1.0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1.0)
            assert processes and all(process.returncode is not None for process in processes)
        finally:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    asyncio.run(scenario())


@pytest.mark.parametrize("ending", ["natural", "late-cancel", "stuck"])
def test_final_codec_record_keeps_exit_status_owned_by_asyncio(monkeypatch, caplog, ending):
    import os
    import signal
    import sys

    async def scenario():
        envelope, _ = large_snapshot_fixture(2)
        reader, writer = os.pipe()
        children = []
        original_start, original_read = asyncio.create_subprocess_exec, _worker._read
        child = ("import os, sys; from joi_observer.ipc._worker import _child; "
                 "_child(sys.argv[1]); os.read(int(sys.argv[2]), 1)")

        async def start(*args, **kwargs):
            process = await original_start(sys.executable, "-c", child, args[-1], str(reader),
                                           pass_fds=(reader,), **kwargs)
            children.append(process)
            return process

        async def read(stream):
            record = await original_read(stream)
            if record[0] == b"D" and ending != "stuck":
                os.write(writer, b".")
                os.waitid(os.P_PID, children[0].pid, os.WEXITED | os.WNOWAIT)
                if ending == "late-cancel":
                    raise asyncio.CancelledError
            return record

        async def inline_cleanup(factory, *, publish):
            await factory()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", start)
        monkeypatch.setattr(_worker, "_read", read)
        monkeypatch.setattr(_worker, "run_cleanup", inline_cleanup)
        try:
            operation = asyncio.create_task(_worker._run("encode", envelope))
            _, pending = await asyncio.wait({operation}, timeout=3)
            assert not pending
            if ending == "late-cancel":
                assert operation.cancelled()
            else:
                assert _worker.decode_envelope(operation.result()) == envelope
            assert children[0].returncode == (-signal.SIGKILL if ending == "stuck" else 0)
            assert not [record for record in caplog.records if record.name == "asyncio"
                        and "exit status already read" in record.getMessage()]
        finally:
            os.close(writer)
            os.close(reader)
            await asyncio.gather(operation, return_exceptions=True)

    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["first-frame", "after-render"])
@pytest.mark.parametrize("large", [False, True])
def test_malformed_wire_at_real_cli_restores_before_safe_failure_and_reaps_decoder(
        tmp_path, monkeypatch, phase, large):
    body = json.loads(frame()[8:])
    body["raw_error"] = "private-wire-value" * (5000 if large else 1)
    encoded_body = json.dumps(body).encode()
    malformed = struct.pack(">Q", len(encoded_body)) + encoded_body
    assert (len(malformed) > IO_CHUNK_BYTES) is large
    stream = MemoryStream(malformed if phase == "first-frame" else frame())
    connector = MemoryConnector(stream)
    client = SnapshotClient(connector=connector)
    events, workers, services = [], [], []
    original_start = asyncio.create_subprocess_exec

    async def observe_start(*args, **kwargs):
        process = await original_start(*args, **kwargs)
        workers.append(process)
        return process

    class Terminal(MemoryTerminal):
        async def read_key(self, timeout):
            if phase == "after-render" and not getattr(self, "delivered", False):
                self.delivered = True
                stream.pending.put_nowait(malformed)
            return await super().read_key(timeout)

    class ErrorOutput(StringIO):
        def write(self, value):
            if value.strip():
                events.append("diagnostic")
            return super().write(value)

    terminal = Terminal()
    terminal.events = events

    def forbid_service(*args):
        services.append(args)
        raise AssertionError("Client failure must not start collection")

    stderr = ErrorOutput()
    dependencies = CommandDependencies(
        tmp_path, tmp_path, True, True, "xterm-256color", StringIO(), stderr,
        lambda endpoint: TuiClientSession(client, terminal), forbid_service,
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", observe_start)
    assert run_command([], dependencies=dependencies) == 4
    assert stderr.getvalue().strip() == (
        "Cannot connect to collector service. Run joi-observer again to retry.")
    assert len(connector.calls) == 1 and stream.closed and services == []
    with pytest.raises(ConnectionFailure):
        client.snapshot()
    if phase == "first-frame":
        assert terminal.frames == [] and events == ["diagnostic"]
    else:
        assert terminal.frames
        assert events == ["enter", "restore", "diagnostic"]
    assert bool(workers) is large
    assert all(process.returncode is not None for process in workers)


@pytest.mark.parametrize("phase", ["first-frame", "after-connect"])
def test_continuous_partial_progress_cannot_extend_the_complete_frame_deadline(phase):
    async def scenario():
        initial = b"" if phase == "first-frame" else frame()
        stream = MemoryStream(initial)
        connector = MemoryConnector(stream)
        client = SnapshotClient(connector=connector, timeout=0.04)
        partial = frame(sequence=2)
        sent = []

        async def drip():
            # Make progress into the body immediately, then keep delivering
            # fragments throughout the wait. This does not depend on fitting
            # eight separate timer wakeups before the deadline under load.
            stream.pending.put_nowait(partial[:9])
            sent.extend(partial[:9])
            for byte in partial[9:]:
                await asyncio.sleep(0.002)
                stream.pending.put_nowait(bytes((byte,)))
                sent.append(byte)

        producer = None
        try:
            if phase == "after-connect":
                await client.connect()
            started = asyncio.get_running_loop().time()
            producer = asyncio.create_task(drip())
            with pytest.raises(ConnectionFailure):
                await asyncio.wait_for(
                    client.connect() if phase == "first-frame" else client.wait_failed(), 0.3,
                )
            assert asyncio.get_running_loop().time() - started < 0.2
            assert len(sent) > 8 and len(sent) < len(partial)
            assert client.state is ConnectionState.FAILED and stream.closed
            assert len(connector.calls) == 1
            with pytest.raises(ConnectionFailure):
                client.envelope()
            stream.pending.put_nowait(frame(sequence=3))
            await asyncio.sleep(0.005)
            assert len(connector.calls) == 1 and client.state is ConnectionState.FAILED
        finally:
            if producer is not None:
                producer.cancel()
                await asyncio.gather(producer, return_exceptions=True)
            await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("direction", ["encode", "decode"])
def test_codec_sender_task_resource_failure_reaps_already_started_worker(monkeypatch, direction):
    async def scenario():
        expected, _ = large_snapshot_fixture(2)
        from joi_observer.ipc.protocol import encode_envelope
        encoded = encode_envelope(expected)
        assert len(encoded) > IO_CHUNK_BYTES
        processes = []
        original_spawn = asyncio.create_subprocess_exec
        original_task = asyncio.create_task

        async def observe_spawn(*args, **kwargs):
            process = await original_spawn(*args, **kwargs)
            processes.append(process)
            return process

        def refuse_sender(coroutine, *args, **kwargs):
            if getattr(coroutine, "cr_code", None) is _worker._send.__code__:
                # Task allocation can fail after the OS child and pipes exist.
                # Close only the rejected coroutine to keep the fault injector
                # from adding an unrelated unawaited-coroutine warning.
                coroutine.close()
                raise MemoryError("offline sender task allocation failure")
            return original_task(coroutine, *args, **kwargs)

        monkeypatch.setattr(asyncio, "create_subprocess_exec", observe_spawn)
        monkeypatch.setattr(asyncio, "create_task", refuse_sender)
        try:
            with pytest.raises(MemoryError):
                await (_worker.encode_async(expected) if direction == "encode" else _worker.decode_async(encoded))
            assert len(processes) == 1
            assert processes[0].returncode is not None, "failed sender allocation must not detach the real codec worker"
        finally:
            # A failing implementation must not leave the real process running
            # after this offline regression has collected its failure evidence.
            for process in processes:
                if process.returncode is None:
                    process.kill()
                await process.wait()
                process.stdin.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("reject_cleanup", [False, True], ids=["watcher", "watcher-and-cleanup"])
def test_failure_watcher_task_allocation_error_still_joins_real_ui_restoration(monkeypatch, reject_cleanup):
    async def scenario():
        baseline = asyncio.all_tasks()
        stream = MemoryStream(frame())
        client = SnapshotClient(connector=MemoryConnector(stream))
        terminal = MemoryTerminal()
        session = TuiClientSession(client, terminal)
        original_task = asyncio.create_task
        initial = MemoryError("offline failure watcher task allocation failure")
        secondary = []

        def refuse_watcher(coroutine, *args, **kwargs):
            if getattr(coroutine, "cr_code", None) is SnapshotClient.wait_failed.__code__:
                coroutine.close()
                raise initial
            if reject_cleanup and coroutine.cr_code is TuiClientSession._cleanup.__code__:
                coroutine.close()
                secondary.append(True)
                raise MemoryError("cleanup owner unavailable")
            return original_task(coroutine, *args, **kwargs)

        monkeypatch.setattr(asyncio, "create_task", refuse_watcher)
        try:
            with pytest.raises(MemoryError) as caught:
                await session.run()
            assert caught.value is initial and bool(secondary) is reject_cleanup
            assert stream.closed and client.state is ConnectionState.CLOSED
            assert "enter" not in terminal.events or terminal.events[-1] == "restore", (
                "session must restore its entered terminal before propagating initialization failure")
            assert not {task for task in asyncio.all_tasks() - baseline if not task.done()}
        finally:
            # Clean an implementation's unregistered UI task after observing
            # the failed ownership assertion, without relying on asyncio.run's
            # global shutdown as the product's terminal restoration mechanism.
            remaining = {task for task in asyncio.all_tasks() - baseline
                         if task is not asyncio.current_task() and not task.done()}
            for task in remaining:
                task.cancel()
            await asyncio.gather(*remaining, return_exceptions=True)
            await session.close()
    asyncio.run(scenario())


def test_client_cleanup_task_allocation_failure_does_not_leave_connected_stream_open(monkeypatch):
    async def scenario():
        stream = MemoryStream(frame())
        client = SnapshotClient(connector=MemoryConnector(stream))
        await client.connect()
        original_task = asyncio.create_task
        refused = []

        def refuse_cleanup(coroutine, *args, **kwargs):
            if getattr(coroutine, "cr_code", None) is SnapshotClient._cleanup.__code__ and not refused:
                refused.append(True)
                coroutine.close()
                raise MemoryError("offline client cleanup task allocation failure")
            return original_task(coroutine, *args, **kwargs)

        monkeypatch.setattr(asyncio, "create_task", refuse_cleanup)
        try:
            try:
                await client.close()
            except MemoryError:
                pass
            assert refused == [True] and client.state is ConnectionState.CLOSED
            assert stream.closed, "a client cannot discard its live cache and leave its transport open on cleanup allocation failure"
            with pytest.raises(ConnectionFailure):
                client.envelope()
        finally:
            await client.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("direction", ["encode", "decode"])
def test_unexpected_real_codec_worker_exit_is_reported_safely_and_reaped(monkeypatch, direction):
    async def scenario():
        from joi_observer.ipc.protocol import ProtocolError, encode_envelope
        expected, _ = large_snapshot_fixture(2)
        encoded = encode_envelope(expected)
        original_spawn = asyncio.create_subprocess_exec
        workers = []

        async def kill_after_spawn(*args, **kwargs):
            worker = await original_spawn(*args, **kwargs)
            workers.append(worker)
            worker.kill()
            return worker

        monkeypatch.setattr(asyncio, "create_subprocess_exec", kill_after_spawn)
        try:
            with pytest.raises(ProtocolError) as caught:
                await (_worker.encode_async(expected) if direction == "encode" else _worker.decode_async(encoded))
            assert str(caught.value) == "Snapshot codec worker failed."
            assert len(workers) == 1 and workers[0].returncode is not None
        finally:
            for worker in workers:
                if worker.returncode is None:
                    worker.kill()
                await worker.wait()
    asyncio.run(scenario())


def test_session_cleanup_task_allocation_failure_still_restores_and_closes_client(monkeypatch):
    async def scenario():
        stream = MemoryStream(frame())
        client = SnapshotClient(connector=MemoryConnector(stream))
        terminal = MemoryTerminal()
        session = TuiClientSession(client, terminal)
        running = asyncio.create_task(session.run())
        original_task = asyncio.create_task
        refused = []

        def refuse_cleanup(coroutine, *args, **kwargs):
            if getattr(coroutine, "cr_code", None) is TuiClientSession._cleanup.__code__ and not refused:
                refused.append(True)
                coroutine.close()
                raise MemoryError("offline session cleanup task allocation failure")
            return original_task(coroutine, *args, **kwargs)

        try:
            async def rendered():
                while not terminal.frames:
                    await asyncio.sleep(0)
            await asyncio.wait_for(rendered(), 0.5)
            monkeypatch.setattr(asyncio, "create_task", refuse_cleanup)
            try:
                await session.close()
            except MemoryError:
                pass
            assert refused == [True]
            assert terminal.events[-1] == "restore" and stream.closed, (
                "session cleanup allocation failure must not leave its active UI and transport behind")
        finally:
            await session.close()
            await asyncio.gather(running, return_exceptions=True)
    asyncio.run(scenario())


def test_session_close_after_first_body_arrives_restores_any_entered_ui():
    async def scenario():
        baseline = asyncio.all_tasks()
        body_received = asyncio.Event()

        class Stream(MemoryStream):
            async def readexactly(self, count):
                result = await super().readexactly(count)
                if count > 8:
                    body_received.set()
                return result

        stream = Stream(frame())
        client = SnapshotClient(connector=MemoryConnector(stream))
        terminal = MemoryTerminal()
        session = TuiClientSession(client, terminal)
        close_states = []

        async def close_after_body_arrives():
            # A legitimate close request can arrive while the complete first
            # body has been read and connect is about to install its cache.
            await body_received.wait()
            close_states.append(client.state)
            await session.close()

        closing = asyncio.create_task(close_after_body_arrives())
        running = asyncio.create_task(session.run())
        try:
            await asyncio.wait_for(closing, 0.5)
            assert close_states == [ConnectionState.CONNECTING]
            assert stream.closed and client.state is ConnectionState.CLOSED
            assert "enter" not in terminal.events or terminal.events[-1] == "restore", (
                "close after receiving the first body must restore any UI that entered")
            await asyncio.wait_for(asyncio.gather(running, return_exceptions=True), 0.5)
            assert not {task for task in asyncio.all_tasks() - baseline if not task.done()}
        finally:
            remaining = {task for task in asyncio.all_tasks() - baseline
                         if task is not asyncio.current_task() and not task.done()}
            for task in remaining:
                task.cancel()
            await asyncio.gather(*remaining, return_exceptions=True)
            await session.close()
    asyncio.run(scenario())


@pytest.mark.parametrize("phase", ["first-frame", "next-frame"])
def test_whole_frame_deadline_includes_real_decoder_and_reaps_stopped_child(monkeypatch, phase):
    """Ubuntu: a complete body cannot extend its deadline while codec CPU stalls."""
    import copy
    import os
    import signal

    from test_ipc_protocol import wire

    async def scenario():
        _, data = large_snapshot_fixture(2)
        first_data = copy.deepcopy(data)
        for item in first_data["snapshot"]["objects"]:
            item["history"] = []
        first = wire(first_data)
        if phase == "next-frame":
            data["sequence"] = 2
            data["snapshot"]["revision"] = 2
        large = wire(data)
        assert len(first) < IO_CHUNK_BYTES < len(large)

        processes = []
        started = asyncio.Event()
        original_start = asyncio.create_subprocess_exec

        async def stop_actual_decoder(*args, **kwargs):
            assert args[1:] == ("-m", "joi_observer.ipc._worker", "decode")
            process = await original_start(*args, **kwargs)
            processes.append(process)
            # _run has not yet sent input, so the real child cannot complete
            # decoding before this signal. No listener or server is involved.
            os.kill(process.pid, signal.SIGSTOP)
            started.set()
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", stop_actual_decoder)
        stream = MemoryStream(large if phase == "first-frame" else first)
        connector = MemoryConnector(stream)
        client = SnapshotClient(connector=connector, timeout=0.3)
        operation = None
        try:
            if phase == "first-frame":
                operation = asyncio.create_task(client.connect())
            else:
                old = await client.connect()
                assert old.sequence == 1 and not processes
                stream.pending.put_nowait(large)
                operation = asyncio.create_task(client.wait_failed())
            await asyncio.wait_for(started.wait(), 2.0)
            with pytest.raises(ConnectionFailure):
                await asyncio.wait_for(operation, 2.0)
            assert client.state is ConnectionState.FAILED and stream.closed
            assert len(processes) == 1 and processes[0].returncode == -signal.SIGKILL
            with pytest.raises(ConnectionFailure):
                client.envelope()
            with pytest.raises(RuntimeError):
                await client.connect()
            assert len(connector.calls) == 1
        finally:
            # Keep the test safe if the resource assertions fail: never leave
            # a SIGSTOP child behind or allow asyncio.run to wait for it.
            for process in processes:
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                await process.wait()
            if operation is not None and not operation.done():
                operation.cancel()
            if operation is not None:
                await asyncio.gather(operation, return_exceptions=True)
            await client.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("direction", ["encode", "decode"])
@pytest.mark.parametrize("action", ["normal", "cancel"])
def test_real_codec_stdout_backpressure_does_not_block_cancellation(
        monkeypatch, record_testsuite_property, direction, action):
    """Real stdout high-water pause must not hold cleanup after the child exits."""
    import os
    import time

    from joi_observer.ipc.protocol import encode_envelope

    async def scenario():
        envelope, _ = large_snapshot_fixture(32)
        encoded = encode_envelope(envelope)
        expected = encoded if direction == "encode" else envelope
        baseline_tasks = asyncio.all_tasks()
        read_gate, paused = asyncio.Event(), asyncio.Event()
        original_start = asyncio.create_subprocess_exec
        processes = []
        observations = {"encoded_bytes": len(encoded), "gate_cancelled": False}
        operation = None

        async def observe_real_process(*args, **kwargs):
            process = await original_start(*args, **kwargs)
            processes.append(process)
            stream = process.stdout
            original_read = stream.readexactly
            original_pause = stream._transport.pause_reading

            async def slow_consumer(count):
                # Only the real OS stream's consumption is delayed. The gate
                # is bounded and cancellation exits it immediately; neither
                # the codec parser nor Process.wait is replaced or stalled.
                try:
                    async with asyncio.timeout(5):
                        await read_gate.wait()
                except asyncio.CancelledError:
                    observations["gate_cancelled"] = True
                    raise
                return await original_read(count)

            def observe_automatic_pause():
                original_pause()
                observations["buffer_at_pause"] = len(stream._buffer)
                observations["reader_limit"] = stream._limit
                paused.set()

            monkeypatch.setattr(stream, "readexactly", slow_consumer)
            monkeypatch.setattr(stream._transport, "pause_reading", observe_automatic_pause)
            return process

        monkeypatch.setattr(asyncio, "create_subprocess_exec", observe_real_process)
        result = None
        try:
            operation = asyncio.create_task(_worker.encode_async(envelope) if direction == "encode"
                                            else _worker.decode_async(encoded))
            await asyncio.wait_for(paused.wait(), 5)
            assert len(processes) == 1
            process = processes[0]
            assert process.stdout._paused
            assert observations["buffer_at_pause"] > 2 * observations["reader_limit"]
            if action == "normal":
                read_gate.set()
                _, pending = await asyncio.wait({operation}, timeout=5)
                assert not pending, "Normal codec work did not finish after releasing the reader"
                result = operation.result()
                observations["finished_without_rescue"] = operation.done()
                observations["returncode_before_rescue"] = process.returncode
            else:
                started = time.monotonic()
                operation.cancel()
                # wait_for would cancel a cleanup waiter and then potentially
                # wait forever itself. Observe completion without cancelling
                # the product's retained cleanup owner a second time.
                await asyncio.wait({operation}, timeout=1.1)
                observations["elapsed_after_cancel"] = time.monotonic() - started
                observations["finished_without_rescue"] = operation.done()
                observations["returncode_before_rescue"] = process.returncode
                observations["stdout_paused_before_rescue"] = process.stdout._paused
        finally:
            # Always unblock the REAL pipe before joining, including a failing
            # regression. This rescue is outside the measured product outcome.
            read_gate.set()
            for process in processes:
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                process.stdin.close()
                process.stdout._transport.close()
            if operation is not None:
                if not operation.done() and not operation.cancelling():
                    operation.cancel()
                _, pending = await asyncio.wait({operation}, timeout=2)
                assert not pending, "Codec owner did not settle after test pipe rescue"
                try:
                    operation.result()
                except asyncio.CancelledError:
                    observations["final_outcome"] = "cancelled"
                else:
                    observations["final_outcome"] = "success"
            for process in processes:
                await asyncio.wait_for(process.wait(), 1)
                process._transport.close()
                with pytest.raises(ProcessLookupError):
                    os.kill(process.pid, 0)
            await asyncio.sleep(0)
            remaining = {task for task in asyncio.all_tasks() - baseline_tasks
                         if task is not asyncio.current_task() and not task.done()}
            assert not remaining, "Codec regression left pending cleanup tasks"

        for name, value in observations.items():
            record_testsuite_property(f"codec_backpressure_{direction}_{action}_{name}", value)
        assert observations["returncode_before_rescue"] is not None
        if action == "normal":
            assert result == expected
            assert observations["final_outcome"] == "success"
            assert not observations["gate_cancelled"]
        else:
            assert observations["gate_cancelled"]
            assert observations["final_outcome"] == "cancelled"
            assert observations["finished_without_rescue"], (
                "Real codec cleanup exceeded 1.1s after stdout backpressure: the child exited "
                f"with {observations['returncode_before_rescue']}, but Process.wait stayed "
                f"blocked while stdout paused={observations['stdout_paused_before_rescue']}")

    asyncio.run(scenario())
