"""Additional parser and port lifecycle boundaries; all input is synthetic."""

import asyncio
import json

import pytest

from joi_observer.collectors.vllm import AsyncHttpClient, VllmCollector, parse_scrape
from joi_observer.config import LogConfig, ModelConfig, ModelType
from joi_observer.data.state import MonitorState
from joi_observer.error_log import ErrorKind, ErrorLog
from joi_observer.monitor import Monitor
from test_vllm_collector import (
    NAMES, OfflineClient, OfflineHttp, StreamResponse, client_factory, inputs, model, value_changed,
)
from test_vllm_integration import RawHttp, configs, settle


def test_model_identity_with_comma_quote_and_backslash_is_parsed_exactly():
    identity = 'model,variant"with\\slash'
    escaped = identity.replace("\\", "\\\\").replace('"', '\\"')
    data = inputs()
    data["models"] = json.dumps({"data": [{"id": identity}]}).encode()
    data["metrics"] = data["metrics"].replace(NAMES["chat"].encode(), escaped.encode())
    config = ModelConfig("edge", ModelType.CHAT, "Display name", "http://model.invalid",
                         served_model_name=identity)
    result = parse_scrape(config, **data)
    assert result.failure is None
    assert result.observation.model_name == identity
    assert result.observation.engines[0].generation_tokens.value == 253_067


def test_zero_with_maximum_legal_exponent_has_one_integer_digit():
    data = inputs()
    data["metrics"] = value_changed(data["metrics"], "vllm:prompt_tokens_total", "0e400")
    result = parse_scrape(model(), **data)
    assert result.failure is None
    assert result.observation.engines[0].prompt_tokens.value == 0


@pytest.mark.parametrize("engine", [b"", b"bad\\n", b"bad\x7f", b"bad\x01"])
def test_nonprintable_or_empty_engine_is_a_safe_overall_parse_failure(engine):
    data = inputs()
    data["metrics"] = data["metrics"].replace(b'engine="0"', b'engine="' + engine + b'"')
    result = parse_scrape(model(), **data)
    assert result.observation is None
    assert result.failure.kind is ErrorKind.PARSE
    assert result.failure.code == "response.invalid"


def test_bad_engine_cannot_escape_state_validation_or_stop_other_models(tmp_path):
    async def case():
        cfgs = configs()
        ports = tuple(RawHttp(config) for config in cfgs)
        collectors = tuple(VllmCollector(config, port) for config, port in zip(cfgs, ports))
        clock = [0.0]
        state = MonitorState(tuple(item.spec for item in collectors), clock=lambda: clock[0])
        log = ErrorLog(LogConfig(directory=tmp_path / "logs"))
        assert log.prepare()
        monitor = Monitor(collectors, state, log, clock=lambda: clock[0])
        try:
            await settle(monitor)
            ports[0].metrics_override = ports[0].responses["metrics-1.prom"].replace(
                b'engine="0"', b'engine="bad\\n"')
            clock[0] = 2
            await settle(monitor)
            snapshots = state.snapshot().objects
            assert [item.stale for item in snapshots] == [True, False, False]
            assert all(item.sampled_at == 2 for item in snapshots)
            assert snapshots[0].history[-1].metrics is None
            assert all({metric.name: metric.value for metric in item.metrics}["rate"] == 0
                       for item in snapshots[1:])
            assert await log.flush()
            recorded = (tmp_path / "logs/error.log").read_text()
            assert "response.invalid" in recorded and "bad" not in recorded
            ports[0].metrics_override = None
            clock[0] = 4
            await settle(monitor)
            assert all(not item.stale and item.sampled_at == 4 for item in state.snapshot().objects)
        finally:
            await monitor.stop()
            await log.close()

    asyncio.run(case())


@pytest.mark.parametrize("extra", [
    b'unknown{detail="bad\\q"} 1\n',
    b'unknown{detail="unclosed} 1\n',
    b'unknown 1 2 3\n',
    b'unknown PRIVATE\n',
])
def test_illegal_exposition_is_not_ignored_as_an_unknown_family(extra):
    data = inputs()
    data["metrics"] += extra
    result = parse_scrape(model(), **data)
    assert result.observation is None
    assert result.failure.kind is ErrorKind.PARSE
    assert "PRIVATE" not in repr(result)


def test_http_port_rejects_overlapping_get_without_starting_second_request():
    async def case():
        stream = StreamResponse(gate=asyncio.Event())
        client = OfflineClient(stream)
        port = AsyncHttpClient(client_factory(client, []))
        first = asyncio.create_task(port.get("http://model.invalid/metrics", timeout=1, max_bytes=10))
        await asyncio.wait_for(stream.started.wait(), 0.3)
        with pytest.raises(RuntimeError):
            await port.get("http://model.invalid/version", timeout=1, max_bytes=10)
        assert len(client.calls) == 1
        await port.close()
        with pytest.raises(asyncio.CancelledError):
            await first
        assert stream.closed and client.close_calls == 1

    asyncio.run(case())


def test_closing_unused_port_does_not_construct_a_client():
    async def case():
        created = []
        port = AsyncHttpClient(lambda **options: created.append(options))
        await port.close()
        await port.close()
        assert created == []
        with pytest.raises(RuntimeError):
            await port.get("http://model.invalid/metrics", timeout=1, max_bytes=10)

    asyncio.run(case())


def test_collector_close_cancels_pending_read_and_forbids_future_collections():
    async def case():
        port = OfflineHttp([], delay=100)
        collector = VllmCollector(model(), port)
        task = asyncio.create_task(collector.collect())
        await asyncio.sleep(0)
        await asyncio.wait_for(collector.close(), 0.25)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert port.cancelled and port.close_calls == 1
        await collector.close()
        assert port.close_calls == 1
        with pytest.raises(RuntimeError):
            await collector.collect()

    asyncio.run(case())


def test_transport_os_error_does_not_expose_arbitrary_exception_text():
    async def case():
        port = AsyncHttpClient(client_factory(OfflineClient(OSError("PRIVATE")), []))
        with pytest.raises(OSError) as error:
            await port.get("http://model.invalid/metrics", timeout=1, max_bytes=10)
        assert "PRIVATE" not in str(error.value)
        await port.close()

    asyncio.run(case())


@pytest.mark.parametrize("profile,extra", [
    ("chat", b'vllm:num_requests_running{engine="0",model_name="unrelated"} PRIVATE\n'),
    ("chat", b'vllm:request_queue_time_seconds_bucket{engine="0",'
             b'model_name="qwen3.8-flash-next",le="0.123456"} PRIVATE\n'),
    ("embedding", b'vllm:request_success_total{engine="0",'
                  b'model_name="qwen3-embedding-4b",finished_reason="other"} PRIVATE\n'),
])
def test_ignored_series_must_still_be_legal_exposition(profile, extra):
    """Filtering a series must not turn a malformed response into fresh data."""
    data = inputs(profile)
    data["metrics"] += extra
    result = parse_scrape(model(profile), **data)
    assert result.observation is None
    assert result.failure.kind is ErrorKind.PARSE
    assert result.failure.code == "response.invalid"
    assert "PRIVATE" not in repr(result)


_IGNORED_SERIES = (
    ("chat", b'custom_independent{detail="ignored"} '),
    ("chat", b'vllm:num_requests_running{engine="0",model_name="unrelated"} '),
    ("chat", b'vllm:request_queue_time_seconds_bucket{engine="0",'
             b'model_name="qwen3.8-flash-next",le="0.123456"} '),
    ("embedding", b'vllm:request_success_total{engine="0",'
                  b'model_name="qwen3-embedding-4b",finished_reason="other"} '),
)


@pytest.mark.parametrize("profile,prefix", _IGNORED_SERIES)
@pytest.mark.parametrize("token", [b"9" * 129, b"1e401", b"1e-401", b"1e400"])
def test_ignored_series_cannot_bypass_numeric_resource_limits(profile, prefix, token):
    data = inputs(profile)
    data["metrics"] += prefix + token + b"\n"
    result = parse_scrape(model(profile), **data)
    assert result.observation is None
    assert result.failure.kind is ErrorKind.PARSE
    assert result.failure.code == "response.invalid"


@pytest.mark.parametrize("profile,prefix", _IGNORED_SERIES)
def test_legal_ignored_values_are_not_interpreted_as_business_counts(profile, prefix):
    data = inputs(profile)
    baseline = parse_scrape(model(profile), **data)
    assert baseline.failure is None
    for token in (b"-2.5", b"+3e1", b"NaN", b"+Inf", b"-Inf", b"1e399", b"0e400"):
        result = parse_scrape(model(profile), **{**data, "metrics": data["metrics"] + prefix + token + b"\n"})
        assert result == baseline, token
