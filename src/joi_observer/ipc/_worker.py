"""Cancellable codec execution over private subprocess pipes on Ubuntu.

Large inputs use a fresh interpreter, safe after the log thread has started.
Trusted pipe records are serialized per object between loop yields; wire data
is never unpickled. Small inputs have bounded synchronous work and avoid process
startup. No executor or background thread survives cancellation.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
import os
import pickle
import signal
import struct
import sys

from joi_observer.data.models import StateSnapshot
from joi_observer._shutdown import cancel_once, join_tasks, run_cleanup, spawn
from joi_observer.ipc.protocol import (
    IO_CHUNK_BYTES, ProtocolError, SnapshotEnvelope, decode_envelope, encode_envelope,
)


def _shell(value):
    return replace(value, snapshot=StateSnapshot((), revision=value.snapshot.revision))


def _blocking_write(stream, kind, payload=b""):
    stream.write(kind + struct.pack(">Q", len(payload)))
    for offset in range(0, len(payload), IO_CHUNK_BYTES):
        stream.write(payload[offset:offset + IO_CHUNK_BYTES])
    stream.flush()


def _blocking_read(stream):
    header = stream.read(9)
    if len(header) != 9:
        raise EOFError
    size = struct.unpack(">Q", header[1:])[0]
    payload = stream.read(size)
    if len(payload) != size:
        raise EOFError
    return header[:1], payload


def _child(mode):
    source, sink = sys.stdin.buffer, sys.stdout.buffer
    try:
        if mode == "encode":
            _, payload = _blocking_read(source)
            shell = pickle.loads(payload)
            objects = []
            while True:
                kind, payload = _blocking_read(source)
                if kind == b"D":
                    break
                if kind != b"O":
                    raise ValueError
                objects.append(pickle.loads(payload))
            value = replace(shell, snapshot=StateSnapshot(tuple(objects), revision=shell.snapshot.revision))
            _blocking_write(sink, b"E", encode_envelope(value))
        else:
            kind, payload = _blocking_read(source)
            if kind != b"B":
                raise ValueError
            value = decode_envelope(payload)
            _blocking_write(sink, b"H", pickle.dumps(_shell(value), protocol=5))
            for obj in value.snapshot.objects:
                _blocking_write(sink, b"O", pickle.dumps(obj, protocol=5))
        _blocking_write(sink, b"D")
    except BaseException:
        try:
            _blocking_write(sink, b"F")
        except BaseException:
            pass


async def _write(stream, kind, payload=b""):
    stream.write(kind + struct.pack(">Q", len(payload)))
    for offset in range(0, len(payload), IO_CHUNK_BYTES):
        stream.write(payload[offset:offset + IO_CHUNK_BYTES])
        await stream.drain()
        await asyncio.sleep(0)
    await stream.drain()


async def _read(stream):
    header = await stream.readexactly(9)
    left = struct.unpack(">Q", header[1:])[0]
    pieces = []
    while left:
        part = await stream.readexactly(min(left, IO_CHUNK_BYTES))
        pieces.append(part)
        left -= len(part)
        await asyncio.sleep(0)
    return header[:1], b"".join(pieces)


async def _send(stream, mode, value):
    try:
        if mode == "decode":
            await _write(stream, b"B", value)
        else:
            await _write(stream, b"H", pickle.dumps(_shell(value), protocol=5))
            for obj in value.snapshot.objects:
                await _write(stream, b"O", pickle.dumps(obj, protocol=5))
                await asyncio.sleep(0)
            await _write(stream, b"D")
    finally:
        stream.close()


async def _reap(process):
    """An inline cleanup still owns the child through caller cancellation."""
    interrupted = False
    while True:
        try:
            await process.wait()
            break
        except asyncio.CancelledError:
            interrupted = True
    if interrupted:
        raise asyncio.CancelledError


async def _run(mode, value):
    # Preserve the current source checkout in child imports, including a WSL
    # native test checkout. No installed historical bundle is used.
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(sys.path)
    process = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "joi_observer.ipc._worker", mode,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL, env=env, start_new_session=True,
        limit=IO_CHUNK_BYTES,
    )
    sender = None
    failure = None
    shell, objects, encoded = None, [], None
    try:
        sender = spawn(_send(process.stdin, mode, value))
        while True:
            kind, payload = await _read(process.stdout)
            if kind == b"F":
                raise ProtocolError("Snapshot codec failed.")
            if kind == b"D":
                await sender
                if mode == "encode" and encoded is not None:
                    return encoded
                if mode == "decode" and shell is not None:
                    return replace(shell, snapshot=StateSnapshot(tuple(objects), revision=shell.snapshot.revision))
                raise ProtocolError("Snapshot codec worker failed.")
            if kind == b"E" and mode == "encode":
                encoded = payload
            elif kind == b"H" and mode == "decode":
                shell = pickle.loads(payload)
            elif kind == b"O" and mode == "decode":
                objects.append(pickle.loads(payload))
            else:
                raise ProtocolError("Snapshot codec worker failed.")
            await asyncio.sleep(0)
    except (EOFError, asyncio.IncompleteReadError, BrokenPipeError):
        failure = ProtocolError("Snapshot codec worker failed.")
        raise failure from None
    except BaseException as error:
        failure = error
        raise
    finally:
        async def cleanup():
            # Ownership starts at successful subprocess creation, before any
            # auxiliary task can be allocated. Closing stdin also releases a
            # child waiting for the sender that could not be scheduled.
            close_error = None

            def close_transport(transport):
                nonlocal close_error
                if transport is not None:
                    try:
                        transport.close()
                    except BaseException as error:
                        if close_error is None:
                            close_error = error

            close_transport(process.stdin)
            # Process.wait can depend on pipe disconnection as well as child
            # exit. A high-water pause prevents stdout from observing EOF even
            # after SIGKILL, so release our read pipe before joining the child.
            # StreamReader has no public close API; private transport access is
            # confined here and never reads or retains discarded output.
            close_transport(getattr(process.stdout, "_transport", None))
            if sender is not None:
                cancel_once(sender)
            try:
                if failure is None and process.returncode is None:
                    try:
                        async with asyncio.timeout(0.1):
                            await process.wait()
                    except TimeoutError:
                        pass
            finally:
                if process.returncode is None:
                    try:
                        if os.name == "posix":
                            os.killpg(process.pid, signal.SIGKILL)
                        else:
                            process.kill()
                    except ProcessLookupError:
                        pass
                try:
                    if sender is not None:
                        await join_tasks({sender})
                finally:
                    try:
                        await _reap(process)
                    finally:
                        if process.returncode is not None:
                            close_transport(getattr(process, "_transport", None))
            if close_error is not None:
                raise close_error

        try:
            await run_cleanup(cleanup, publish=lambda owner: None)
        except BaseException:
            if failure is None:
                raise


def _small(envelope):
    """Bound only synchronous work, never restrict accepted snapshot capacity."""
    if len(envelope.metadata.models) > 8 or len(envelope.metadata.containers) > 16 or len(envelope.snapshot.objects) > 16:
        return False
    labels = (envelope.metadata.hostname, envelope.metadata.system, *envelope.metadata.mount_points)
    if any(len(label) > 1024 for label in labels):
        return False
    for model in envelope.metadata.models:
        if len(model.gpu_ids) > 16 or any(len(label) > 128 for label in
                (model.id, model.name, model.served_model_name, *model.gpu_ids)):
            return False
    count = 0
    for obj in envelope.snapshot.objects:
        if len(obj.history) > 8:
            return False
        groups = [obj.metrics] + [point.metrics or () for point in obj.history]
        for metrics in groups:
            count += len(metrics)
            if count > 128:
                return False
            for metric in metrics:
                if isinstance(metric.value, str) and len(metric.value) > 1024:
                    return False
                if isinstance(metric.value, int) and metric.value.bit_length() > 1024:
                    return False
    return True


async def encode_async(envelope: SnapshotEnvelope) -> bytes:
    """Encode frozen data; at most one call is in flight per publisher."""
    if _small(envelope):
        return encode_envelope(envelope)
    return await _run("encode", envelope)


async def decode_async(frame: bytes) -> SnapshotEnvelope:
    """Validate untrusted wire data before reconstructing immutable records."""
    if len(frame) <= IO_CHUNK_BYTES:
        return decode_envelope(frame)
    return await _run("decode", frame)


if __name__ == "__main__":
    _child(sys.argv[1])
