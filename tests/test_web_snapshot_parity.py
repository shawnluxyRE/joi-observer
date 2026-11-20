"""Check the browser wire data against the same raw samples used by the TUI."""

import asyncio

from joi_observer.config import AppConfig, ModelType
from joi_observer.data.state import MonitorState
from joi_observer.data.vllm import make_vllm_spec
from joi_observer.ipc.protocol import FRAME_HEADER_BYTES, SnapshotEnvelope, build_metadata, encode_envelope
from joi_observer.web.app import create_app
from test_snapshot_pipeline import (
    PipelineConnector,
    PipelineStream,
    assert_reference_values,
    collect_reference_rounds,
    pipeline_config,
)
from test_web_api import HttpRequest, lifespan
from test_vllm_collector import inputs, model, parse, value_changed


async def browser_reference_response(tmp_path):
    """Return one real ASGI header set and the four records from the TUI samples."""
    config = pipeline_config(tmp_path)
    snapshots = await collect_reference_rounds(config, ModelType.EMBEDDING)
    assert_reference_values(snapshots, ModelType.EMBEDDING)
    metadata = build_metadata(config, hostname="Offline Host", system="Ubuntu 24.04")
    stream = PipelineStream()
    connector = PipelineConnector(stream)
    published = 0.0
    app = create_app(connector=connector, clock=lambda: published)
    lines = []
    async with lifespan(app), HttpRequest(app) as page:
        for sequence, snapshot in enumerate(snapshots, start=1):
            published = max(item.sampled_at for item in snapshot.objects)
            envelope = SnapshotEnvelope("same-host", "same-config", sequence,
                                        published, metadata, snapshot)
            frame = encode_envelope(envelope)
            stream.deliver(frame)
            if sequence == 1:
                status, headers = await page.response()
                assert status == 200
                assert float(headers[b"x-joi-sent-at"]) == published
                assert b"date" in headers
                browser_headers = {key.decode("ascii"): value.decode("latin-1")
                                   for key, value in headers.items()}
            line = await page.line()
            assert line == frame[FRAME_HEADER_BYTES:] + b"\n"
            assert b"private-container-target" not in line
            assert b"http://" not in line and str(config.logging.directory).encode() not in line
            lines.append(line)
    assert connector.calls == 1 and stream.closed
    return browser_headers, lines


def test_browser_receives_tui_reference_samples_including_source_failure_and_recovery(tmp_path):
    _, lines = asyncio.run(browser_reference_response(tmp_path))
    assert len(lines) == 4


def test_active_model_rates_reach_the_live_stream_in_their_own_units():
    # Two seconds of work: 17 generated tokens, 7 completed embeddings,
    # and 3 completed reranks. Each model uses the served-name fallback.
    config = AppConfig(mount_points=(), models=tuple(model(kind.value) for kind in ModelType))
    state = MonitorState(tuple(make_vllm_spec(item) for item in config.models), clock=lambda: 102.0)
    cases = (
        ("chat", "generation_tokens_total", 253_084, b"", "decode_rate", 8.5, "tok/s"),
        ("embedding", "request_success_total", 372, b'finished_reason="stop"', "rate", 3.5, "seq/s"),
        ("reranker", "request_success_total", 87, b'finished_reason="stop"', "rate", 1.5, "seq/s"),
    )
    for item, (kind, counter, final_count, label, *_) in zip(config.models, cases, strict=True):
        assert item.id == kind
        state.accept(parse(kind, config=item), sampled_at=100.0)
        raw = value_changed(inputs(kind)["metrics"], "vllm:" + counter, final_count, contains=label)
        state.accept(parse(kind, config=item, metrics=raw), sampled_at=102.0)

    async def scenario():
        metadata = build_metadata(config, hostname="offline", system="Ubuntu")
        stream = PipelineStream()
        stream.deliver(encode_envelope(SnapshotEnvelope("host", "config", 1, 102.0, metadata, state.snapshot())))
        app = create_app(connector=PipelineConnector(stream), clock=lambda: 102.0)
        async with lifespan(app), HttpRequest(app) as page:
            assert (await page.response())[0] == 200
            published = await page.frame()
        objects = {item["key"]["object_id"]: item for item in published["snapshot"]["objects"]}
        for identity, case, cfg in zip(published["metadata"]["models"], cases, config.models, strict=True):
            kind, _, _, _, field, expected, unit = case
            assert (identity["id"], identity["name"], identity["served_model_name"]) == (kind, cfg.name, cfg.name)
            obj = objects[kind]
            assert not obj["stale"]
            for source in (obj, obj["history"][-1]):
                metric = next(entry for entry in source["metrics"] if entry["name"] == field)
                assert (source["sampled_at"], metric["value"], metric["unit"]) == (102.0, expected, unit)

    asyncio.run(scenario())
