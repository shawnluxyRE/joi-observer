"""Public contracts; real entry points with offline byte/HTTP ports.

Recorded excerpts have provenance under fixtures/vllm/0.31.0. Mutations below are
synthetic edge cases, not additional server observations. Unimplemented behavior
must fail normally: no xfail/skip or NotImplementedError-as-success assertions.
"""

import asyncio
import builtins
from dataclasses import FrozenInstanceError
import hashlib
import json
from pathlib import Path
import socket

import pytest

from joi_observer.collectors.vllm import (
    AsyncHttpClient,
    HttpBodyTooLargeError,
    HttpResponse,
    MAX_LINE_BYTES,
    MAX_RESPONSE_BYTES,
    MAX_SAMPLE_LINES,
    VllmCollector,
    build_vllm_collectors,
    parse_scrape,
)
from joi_observer.config import AppConfig, ModelConfig, ModelType
from joi_observer.data.models import ObjectKey
from joi_observer.data.vllm import ChatEngineSample, PoolingEngineSample, VllmCollectionResult
from joi_observer.error_log import ErrorKind


FIXTURES = Path(__file__).parent / "fixtures" / "vllm" / "0.31.0"
NAMES = {
    "chat": "qwen3.8-flash-next",
    "embedding": "qwen3-embedding-4b",
    "reranker": "qwen3-reranker-0.6b",
}


@pytest.fixture(autouse=True)
def no_live_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("vLLM tests require offline HTTP/client ports, including localhost.")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def model(profile="chat", *, identity=None, display=None, object_id=None):
    return ModelConfig(
        object_id or profile, ModelType(profile), display or NAMES[profile],
        f"http://{profile}.example.invalid:8000", served_model_name=identity,
    )


def inputs(profile="chat", round_number=1):
    return {
        "version": (FIXTURES / f"{profile}-version.json").read_bytes(),
        "models": (FIXTURES / f"{profile}-models.json").read_bytes(),
        "metrics": (FIXTURES / f"{profile}-metrics-{round_number}.prom").read_bytes(),
    }


def parse(profile="chat", *, config=None, **updates):
    data = inputs(profile)
    data.update(updates)
    return parse_scrape(config or model(profile), **data)


def metric_line(raw, name, *, contains=b""):
    prefix = name.encode() + b"{"
    return next(line for line in raw.splitlines() if line.startswith(prefix) and contains in line)


def value_changed(raw, name, value, *, contains=b""):
    line = metric_line(raw, name, contains=contains)
    changed = line.rsplit(b" ", 1)[0] + b" " + str(value).encode()
    return raw.replace(line, changed, 1)


def without_samples(raw, *names):
    names = tuple(name.encode() for name in names)
    return b"\n".join(
        line for line in raw.splitlines()
        if not any(line.startswith(name + b"{") or line.startswith(name + b" ") for name in names)
    ) + b"\n"


def assert_failure(result, kind=ErrorKind.PARSE, code="response.invalid", *, partial=False):
    assert isinstance(result, VllmCollectionResult)
    assert not hasattr(result, "metrics")
    assert result.failure is not None
    assert (result.failure.kind, result.failure.code) == (kind, code)
    assert (result.observation is not None) == partial
    assert "PRIVATE" not in repr(result)


def engine(result, engine_id="0"):
    assert result.observation is not None
    expected_type = ChatEngineSample if result.observation.model_type is ModelType.CHAT else PoolingEngineSample
    assert all(isinstance(item, expected_type) for item in result.observation.engines)
    return next(item for item in result.observation.engines if item.engine_id == engine_id)


@pytest.mark.parametrize("profile", list(NAMES))
@pytest.mark.parametrize("round_number", [1, 2])
def test_recorded_three_profiles_produce_typed_observations_without_ui_metrics(profile, round_number):
    result = parse_scrape(model(profile), **inputs(profile, round_number))
    assert result.key == ObjectKey("vllm", profile)
    assert result.failure is None
    assert isinstance(result, VllmCollectionResult)
    assert not hasattr(result, "metrics")
    assert result.observation.model_type == ModelType(profile)
    assert result.observation.model_name == NAMES[profile]
    sample = engine(result)
    assert (sample.running, sample.waiting) == (0, 0)
    assert result.observation.process_started_at > 0
    if profile == "chat":
        assert isinstance(sample, ChatEngineSample)
        assert sample.prompt_tokens.value == 4_694_991
        assert sample.generation_tokens.value == 253_067
        assert sample.kv_cache_fraction == 0
        assert sample.ttft.observations == 270
        assert sample.ttft.total_seconds == pytest.approx(75.12002778053284)
        assert sample.queue.observations == 269
        assert sample.queue.total_seconds == pytest.approx(0.008854439096467104)
        assert not hasattr(sample, "completed_sequences") and not hasattr(sample, "latency")
    else:
        assert isinstance(sample, PoolingEngineSample)
        expected = 365 if profile == "embedding" else 84
        assert sample.completed_sequences.value == expected
        assert sample.queue.observations == sample.latency.observations == expected
        assert sample.latency.total_seconds == pytest.approx(
            20.24644899368286 if profile == "embedding" else 26.37080717086792)
        assert all(not hasattr(sample, attribute)
                   for attribute in ("prompt_tokens", "generation_tokens", "ttft", "kv_cache_fraction"))


def test_fixture_hashes_match_provenance():
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    assert provenance["archive_sha256"] == "69a51042dcbf641e59db5d0f3479376cb53133b911bfff5d37903f8a2aeeb408"
    for record in provenance["files"]:
        assert hashlib.sha256((FIXTURES / record["fixture"]).read_bytes()).hexdigest() == record["fixture_sha256"]


def test_explicit_served_identity_is_separate_from_display_name():
    result = parse(config=model(identity=NAMES["chat"], display="My local chat"))
    assert result.failure is None
    assert result.observation.model_name == NAMES["chat"]


@pytest.mark.parametrize("identity", ["qwen3.8", "QWEN3.8-flash-next", "another-model"])
def test_identity_requires_exact_models_and_metrics_match(identity):
    assert_failure(parse(config=model(identity=identity)), ErrorKind.NOT_FOUND, "object.not_found")


@pytest.mark.parametrize("endpoint", ["models", "metrics"])
def test_one_identity_endpoint_cannot_validate_the_other(endpoint):
    changed = inputs()[endpoint].replace(NAMES["chat"].encode(), b"PRIVATE-other-model")
    assert_failure(parse(**{endpoint: changed}), ErrorKind.NOT_FOUND, "object.not_found")


@pytest.mark.parametrize("body", [b'{"version":"0.30.0"}', b'{"version":"0.31.0+dev"}',
                                  b'{"version":31}', b'{"version":null}', b'{}',
                                  b'{"version":"0.31.0","version":"0.31.0"}', b'PRIVATE'])
def test_only_exact_supported_version_and_unambiguous_json_are_valid(body):
    assert_failure(parse(version=body))


@pytest.mark.parametrize("body", [b'[]', b'{"data":null}', b'{"data":[{"id":1}]}',
                                  b'{"data":[],"data":[]}', b'PRIVATE'])
def test_malformed_model_catalog_is_not_treated_as_normal_empty_data(body):
    assert_failure(parse(models=body))


def test_successful_empty_catalog_means_configured_model_not_found():
    assert_failure(parse(models=b'{"object":"list","data":[]}'),
                   ErrorKind.NOT_FOUND, "object.not_found")


@pytest.mark.parametrize("bad", ["-1", "1.5", "NaN", "+Inf", "-Inf", "true", "1e400", "1e401",
                                 "1e-401", "9" * 129, "PRIVATE"])
def test_invalid_single_count_is_local_failure_and_retains_other_raw_fields(bad):
    raw = value_changed(inputs()["metrics"], "vllm:num_requests_waiting", bad)
    result = parse(metrics=raw)
    assert_failure(result, partial=True)
    assert engine(result).waiting is None
    assert engine(result).running == 0
    assert engine(result).generation_tokens.value == 253_067


@pytest.mark.parametrize("name,attribute", [
    ("vllm:num_requests_running", "running"),
    ("vllm:num_requests_waiting", "waiting"),
    ("vllm:prompt_tokens_total", "prompt_tokens"),
    ("vllm:generation_tokens_total", "generation_tokens"),
    ("vllm:kv_cache_usage_perc", "kv_cache_fraction"),
])
def test_missing_required_field_is_partial_failure_not_zero(name, attribute):
    result = parse(metrics=without_samples(inputs()["metrics"], name))
    assert_failure(result, partial=True)
    assert getattr(engine(result), attribute) is None


@pytest.mark.parametrize("suffix", ["sum", "count"])
def test_histogram_sum_and_count_fail_as_one_group(suffix):
    raw = without_samples(inputs()["metrics"], f"vllm:request_queue_time_seconds_{suffix}")
    result = parse(metrics=raw)
    assert_failure(result, partial=True)
    assert engine(result).queue is None
    assert engine(result).ttft.observations == 270


@pytest.mark.parametrize("value", [-0.1, 1.01, "NaN"])
def test_kv_fraction_is_bounded_without_changing_token_fields(value):
    result = parse(metrics=value_changed(inputs()["metrics"], "vllm:kv_cache_usage_perc", value))
    assert_failure(result, partial=True)
    assert engine(result).kv_cache_fraction is None
    assert engine(result).prompt_tokens.value == 4_694_991


def test_kv_fraction_is_preserved_for_state_percentage_conversion():
    result = parse(metrics=value_changed(inputs()["metrics"], "vllm:kv_cache_usage_perc", "0.375"))
    assert result.failure is None
    assert engine(result).kv_cache_fraction == 0.375


def test_decimal_scientific_token_counter_keeps_exact_integer_precision():
    raw = value_changed(inputs()["metrics"], "vllm:prompt_tokens_total", "1.152921504606846982e18")
    result = parse(metrics=raw)
    assert result.failure is None
    assert engine(result).prompt_tokens.value == 2**60 + 6


def test_exact_400_digit_counter_remains_raw_integer_without_float_conversion():
    raw = value_changed(inputs()["metrics"], "vllm:prompt_tokens_total", "1e399")
    result = parse(metrics=raw)
    assert result.failure is None
    assert engine(result).prompt_tokens.value == 10**399


@pytest.mark.parametrize("profile", ["embedding", "reranker"])
def test_pooling_ignores_inapplicable_chat_families_even_if_present_or_absent(profile):
    raw = without_samples(inputs(profile)["metrics"], "vllm:prompt_tokens_total",
                          "vllm:generation_tokens_total", "vllm:kv_cache_usage_perc",
                          "vllm:time_to_first_token_seconds_sum", "vllm:time_to_first_token_seconds_count")
    result = parse(profile, metrics=raw)
    assert result.failure is None
    assert all(not hasattr(engine(result), attribute)
               for attribute in ("prompt_tokens", "generation_tokens", "ttft", "kv_cache_fraction"))
    assert engine(result).completed_sequences.value > 0


@pytest.mark.parametrize("profile", ["embedding", "reranker"])
def test_pooling_rate_source_is_stop_only_not_all_finish_reasons(profile):
    raw = inputs(profile)["metrics"]
    for reason in (b"length", b"abort", b"error", b"repetition"):
        raw = value_changed(raw, "vllm:request_success_total", 999999,
                            contains=b'finished_reason="' + reason + b'"')
    result = parse(profile, metrics=raw)
    assert result.failure is None
    assert engine(result).completed_sequences.value == (365 if profile == "embedding" else 84)


@pytest.mark.parametrize("profile", ["embedding", "reranker"])
def test_pooling_missing_stop_series_does_not_substitute_other_finish_reasons(profile):
    raw = inputs(profile)["metrics"]
    raw = raw.replace(metric_line(raw, "vllm:request_success_total", contains=b'finished_reason="stop"'), b"")
    result = parse(profile, metrics=raw)
    assert_failure(result, partial=True)
    assert engine(result).completed_sequences is None
    assert engine(result).queue is not None and engine(result).latency is not None


def test_zero_histogram_observations_and_zero_sum_are_valid():
    raw = inputs()["metrics"]
    for suffix in ("sum", "count"):
        raw = value_changed(raw, f"vllm:request_queue_time_seconds_{suffix}", 0)
    result = parse(metrics=raw)
    assert result.failure is None
    assert engine(result).queue.observations == engine(result).queue.total_seconds == 0


def test_positive_histogram_sum_with_zero_count_is_local_failure():
    raw = value_changed(inputs()["metrics"], "vllm:request_queue_time_seconds_count", 0)
    result = parse(metrics=raw)
    assert_failure(result, partial=True)
    assert engine(result).queue is None


def test_missing_optional_creation_and_process_markers_is_not_collection_failure():
    raw = b"\n".join(line for line in inputs()["metrics"].splitlines()
                     if b"_created" not in line and b"process_start_time_seconds" not in line) + b"\n"
    result = parse(metrics=raw)
    assert result.failure is None
    assert result.observation.process_started_at is None
    assert engine(result).generation_tokens.created_at is None
    assert engine(result).ttft.created_at is None


def test_created_markers_are_timestamps_and_do_not_enter_counter_values():
    result = parse()
    assert result.failure is None
    assert engine(result).prompt_tokens.created_at == pytest.approx(1793077470.7055366)
    assert engine(result).prompt_tokens.value == 4_694_991


def test_invalid_optional_created_marker_invalidates_its_field_only():
    raw = value_changed(inputs()["metrics"], "vllm:generation_tokens_created", "NaN")
    result = parse(metrics=raw)
    assert_failure(result, partial=True)
    assert engine(result).generation_tokens is None
    assert engine(result).prompt_tokens.value == 4_694_991


def test_invalid_process_marker_is_overall_structure_failure():
    raw = inputs()["metrics"].replace(b"process_start_time_seconds 1.79307726963e+09",
                                    b"process_start_time_seconds NaN")
    assert_failure(parse(metrics=raw))


def test_multiple_engines_remain_separate_without_gpu_multiplication():
    raw = inputs()["metrics"]
    second = b"\n".join(line.replace(b'engine="0"', b'engine="1"')
                         for line in raw.splitlines() if line.startswith(b"vllm:")) + b"\n"
    second = value_changed(second, "vllm:num_requests_running", 3)
    second = value_changed(second, "vllm:num_requests_waiting", 7)
    result = parse(metrics=raw + second)
    assert result.failure is None
    assert {item.engine_id for item in result.observation.engines} == {"0", "1"}
    assert (engine(result, "0").running, engine(result, "1").running) == (0, 3)
    assert engine(result, "1").waiting == 7
    assert engine(result, "0").prompt_tokens.value == engine(result, "1").prompt_tokens.value == 4_694_991


@pytest.mark.parametrize("mode", ["identical", "reordered", "extra-label", "missing-engine", "duplicate-label"])
def test_ambiguous_target_series_is_not_silently_summed_or_chosen(mode):
    raw = inputs()["metrics"]
    line = metric_line(raw, "vllm:num_requests_running")
    if mode == "identical":
        raw += line + b"\n"
    elif mode == "reordered":
        raw += line.replace(b'engine="0",model_name="qwen3.8-flash-next"',
                            b'model_name="qwen3.8-flash-next",engine="0"') + b"\n"
    elif mode == "extra-label":
        raw = raw.replace(line, line.replace(b"}", b',pid="42"}'))
    elif mode == "missing-engine":
        raw = raw.replace(line, line.replace(b'engine="0",', b""))
    else:
        raw = raw.replace(line, line.replace(b"}", b',engine="0"}'))
    assert_failure(parse(metrics=raw))


def test_other_models_unknown_families_and_inf_bucket_labels_do_not_pollute_target():
    raw = inputs()["metrics"]
    raw += (b'vllm:num_requests_running{engine="0",model_name="unrelated"} 9999\n'
            b'custom_info{detail="comma,quote\\\"and\\\\slash"} 1\n')
    result = parse(metrics=raw)
    assert result.failure is None
    assert engine(result).running == 0
    assert engine(result).ttft.observations == 270


@pytest.mark.parametrize("endpoint", ["version", "models", "metrics"])
def test_every_raw_response_has_independent_two_mib_limit(endpoint):
    assert_failure(parse(**{endpoint: b"x" * (MAX_RESPONSE_BYTES + 1)}))


def test_metrics_line_limit_is_independent_of_response_limit():
    assert_failure(parse(metrics=inputs()["metrics"] + b"# " + b"x" * MAX_LINE_BYTES + b"\n"))


def test_sample_count_limit_applies_even_to_unrelated_families():
    raw = inputs()["metrics"] + b"custom_unrelated 0\n" * (MAX_SAMPLE_LINES + 1)
    assert len(raw) < MAX_RESPONSE_BYTES
    assert_failure(parse(metrics=raw))


def test_label_count_limit_applies_before_ignoring_unrelated_series():
    labels = b",".join(f'k{index}="v"'.encode() for index in range(17))
    assert_failure(parse(metrics=inputs()["metrics"] + b"custom_unrelated{" + labels + b"} 1\n"))


@pytest.mark.parametrize("endpoint", ["version", "models", "metrics"])
def test_invalid_utf8_is_a_safe_overall_failure(endpoint, capsys):
    assert_failure(parse(**{endpoint: b"\xffPRIVATE"}))
    assert capsys.readouterr() == ("", "")


class OfflineHttp:
    """Only response transport is faked; parser/collector under test stay real."""

    def __init__(self, responses, *, delay=0):
        self.responses = list(responses)
        self.delay = delay
        self.calls = []
        self.close_calls = 0
        self.cancelled = False

    async def get(self, url, *, timeout, max_bytes):
        self.calls.append((url, timeout, max_bytes))
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        output = self.responses.pop(0)
        if isinstance(output, BaseException):
            raise output
        return output

    async def close(self):
        self.close_calls += 1


def responses(profile="chat"):
    data = inputs(profile)
    return [HttpResponse(200, data[name]) for name in ("version", "models", "metrics")]


def test_collector_constructor_only_stores_dependencies_and_static_spec():
    port = OfflineHttp(responses())
    collector = VllmCollector(model(), port, timeout=2)
    assert collector.spec.key == ObjectKey("vllm", "chat")
    assert collector.spec.model_type == ModelType.CHAT
    assert collector.spec.served_model_name == NAMES["chat"]
    assert port.calls == [] and port.close_calls == 0


def test_http_response_is_frozen():
    response = HttpResponse(200, b"{}")
    with pytest.raises(FrozenInstanceError):
        response.body = b"changed"


def test_collector_uses_three_direct_gets_in_order_with_remaining_budget():
    async def case():
        port = OfflineHttp(responses(), delay=0.005)
        collector = VllmCollector(model(), port, timeout=1)
        result = await collector.collect()
        assert result.failure is None
        assert [call[0] for call in port.calls] == [
            model().base_url + path for path in ("/version", "/v1/models", "/metrics")]
        assert 0 < port.calls[2][1] < port.calls[1][1] < port.calls[0][1] <= 1
        assert all(call[2] == MAX_RESPONSE_BYTES for call in port.calls)
        assert engine(result).generation_tokens.value == 253_067

    asyncio.run(case())


def test_every_collection_revalidates_version_and_identity():
    async def case():
        port = OfflineHttp(responses() + [HttpResponse(200, b'{"version":"0.32.0"}')])
        collector = VllmCollector(model(), port)
        assert (await collector.collect()).failure is None
        changed = await collector.collect()
        assert_failure(changed)
        assert len(port.calls) == 4

    asyncio.run(case())


def test_changed_catalog_identity_stops_before_reading_metrics_on_later_collection():
    async def case():
        data = inputs()
        changed_models = data["models"].replace(NAMES["chat"].encode(), b"other-model")
        port = OfflineHttp(responses() + [HttpResponse(200, data["version"]), HttpResponse(200, changed_models)])
        collector = VllmCollector(model(), port)
        assert (await collector.collect()).failure is None
        result = await collector.collect()
        assert_failure(result, ErrorKind.NOT_FOUND, "object.not_found")
        assert len(port.calls) == 5

    asyncio.run(case())


@pytest.mark.parametrize("status,kind,code", [
    (401, ErrorKind.PERMISSION, "access.denied"),
    (403, ErrorKind.PERMISSION, "access.denied"),
    (404, ErrorKind.NOT_FOUND, "object.not_found"),
    (302, ErrorKind.UNAVAILABLE, "source.unavailable"),
    (429, ErrorKind.UNAVAILABLE, "source.unavailable"),
    (500, ErrorKind.UNAVAILABLE, "source.unavailable"),
    (True, ErrorKind.PARSE, "response.invalid"),
])
def test_http_failure_stops_following_requests_and_never_exposes_body(status, kind, code, capsys):
    async def case():
        port = OfflineHttp([HttpResponse(status, b"PRIVATE server error")])
        result = await VllmCollector(model(), port).collect()
        assert_failure(result, kind, code)
        assert len(port.calls) == 1

    asyncio.run(case())
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("error,kind,code", [
    (TimeoutError("PRIVATE"), ErrorKind.TIMEOUT, "collection.timeout"),
    (OSError("PRIVATE"), ErrorKind.UNAVAILABLE, "source.unavailable"),
    (HttpBodyTooLargeError(), ErrorKind.PARSE, "response.invalid"),
])
def test_expected_transport_errors_use_existing_safe_failure_catalog(error, kind, code):
    async def case():
        port = OfflineHttp([error])
        assert_failure(await VllmCollector(model(), port).collect(), kind, code)
        assert len(port.calls) == 1

    asyncio.run(case())


def test_total_collect_budget_does_not_restart_for_each_endpoint():
    async def case():
        port = OfflineHttp(responses(), delay=0.02)
        result = await asyncio.wait_for(VllmCollector(model(), port, timeout=0.03).collect(), 0.4)
        assert_failure(result, ErrorKind.TIMEOUT, "collection.timeout")
        assert len(port.calls) < 3
        assert port.cancelled

    asyncio.run(case())


def test_cancelled_collection_propagates_instead_of_returning_stale():
    async def case():
        port = OfflineHttp([asyncio.CancelledError()])
        with pytest.raises(asyncio.CancelledError):
            await VllmCollector(model(), port).collect()
        assert len(port.calls) == 1

    asyncio.run(case())


def test_collector_close_is_idempotent_and_closes_owned_port_once():
    async def case():
        port = OfflineHttp([])
        collector = VllmCollector(model(), port)
        await collector.close()
        await collector.close()
        assert port.close_calls == 1

    asyncio.run(case())


def test_factory_keeps_every_model_order_and_separate_ports_without_fetching():
    made = []

    def factory():
        port = OfflineHttp([])
        made.append(port)
        return port

    same = model(object_id="same-name-other-service")
    config = AppConfig(models=(model(), model("embedding"), model("reranker"), same), collection_timeout=2)
    collectors = build_vllm_collectors(config, http_factory=factory)
    assert tuple(item.spec.key.object_id for item in collectors) == tuple(item.id for item in config.models)
    assert len(made) == 4 and len({id(item.http) for item in collectors}) == 4
    assert all(item.timeout == 2 for item in collectors)
    assert all(item.calls == [] for item in made)


def test_empty_model_configuration_never_calls_http_factory():
    def forbidden():
        raise AssertionError("No model means no HTTP client")

    assert build_vllm_collectors(AppConfig(models=()), http_factory=forbidden) == ()


class StreamResponse:
    def __init__(self, status=200, chunks=(b"ok",), *, gate=None):
        self.status_code = status
        self.headers = {}
        self.chunks = tuple(chunks)
        self.gate = gate
        self.started = asyncio.Event()
        self.closed = False

    async def aiter_bytes(self, *, chunk_size=None):
        assert type(chunk_size) is int and 0 < chunk_size <= 64 * 1024
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        for chunk in self.chunks:
            await asyncio.sleep(0)
            if isinstance(chunk, BaseException):
                raise chunk
            yield chunk

    async def aclose(self):
        self.closed = True


class StreamContext:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, *args):
        await self.response.aclose()


class OfflineClient:
    def __init__(self, *items):
        self.items = list(items)
        self.calls = []
        self.close_calls = 0

    def stream(self, method, url, *, timeout):
        self.calls.append((method, url, timeout))
        item = self.items.pop(0)
        if isinstance(item, BaseException):
            raise item
        return StreamContext(item)

    async def aclose(self):
        self.close_calls += 1


def client_factory(client, created):
    def factory(**options):
        created.append(options)
        return client

    return factory


def test_async_http_constructor_neither_constructs_client_nor_imports_httpx(monkeypatch):
    original_import = builtins.__import__

    def guard(name, *args, **kwargs):
        if name == "httpx" or name.startswith("httpx."):
            raise AssertionError("HTTPX must be lazily imported only for a real default client")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)
    created = []
    AsyncHttpClient(client_factory=lambda **options: created.append(options))
    AsyncHttpClient()
    assert created == []


def test_http_port_uses_injected_client_and_safe_options_then_closes_stream():
    async def case():
        response = StreamResponse(chunks=(b"ab", b"cd"))
        client = OfflineClient(response)
        created = []
        port = AsyncHttpClient(client_factory(client, created))
        result = await port.get("https://chat.example.invalid/metrics", timeout=1, max_bytes=4)
        assert result == HttpResponse(200, b"abcd")
        assert len(created) == 1
        assert {name: created[0][name] for name in ("follow_redirects", "trust_env", "verify")} == {
            "follow_redirects": False, "trust_env": False, "verify": True}
        assert client.calls == [("GET", "https://chat.example.invalid/metrics", 1)]
        assert response.closed
        await port.close()
        await port.close()
        assert client.close_calls == 1

    asyncio.run(case())


def test_injected_client_remains_independent_of_httpx_imports(monkeypatch):
    original_import = builtins.__import__

    def guard(name, *args, **kwargs):
        if name == "httpx" or name.startswith("httpx."):
            raise AssertionError("An injected client must not require HTTPX to be installed")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guard)

    async def case():
        client = OfflineClient(StreamResponse())
        response = await AsyncHttpClient(client_factory(client, [])).get(
            "http://chat.example.invalid/metrics", timeout=1, max_bytes=10)
        assert response == HttpResponse(200, b"ok")

    asyncio.run(case())


def test_http_redirect_is_returned_without_following_location_or_retrying():
    async def case():
        response = StreamResponse(status=307, chunks=(b"PRIVATE",))
        response.headers["location"] = "http://litellm.example.invalid/metrics"
        client = OfflineClient(response)
        port = AsyncHttpClient(client_factory(client, []))
        result = await port.get("http://chat.example.invalid/metrics", timeout=1, max_bytes=100)
        assert result.status == 307
        assert len(client.calls) == 1
        assert client.calls[0][1] == "http://chat.example.invalid/metrics"
        assert response.closed

    asyncio.run(case())


def test_http_limit_is_streamed_even_without_content_length():
    async def case():
        response = StreamResponse(chunks=(b"ab", b"cd", b"e"))
        client = OfflineClient(response)
        with pytest.raises(HttpBodyTooLargeError):
            await AsyncHttpClient(client_factory(client, [])).get(
                "http://chat.example.invalid/metrics", timeout=1, max_bytes=4)
        assert response.closed
        assert len(client.calls) == 1

    asyncio.run(case())


@pytest.mark.parametrize("url", ["ftp://host/metrics", "http://user:PRIVATE@host/metrics",
                                 "http://host/metrics?token=PRIVATE", "http://host/metrics#x",
                                 "http://host/v1/chat/completions", "http://host/v1/embeddings"])
def test_http_port_rejects_non_readonly_target_before_constructing_client(url):
    async def case():
        created = []
        with pytest.raises(ValueError):
            await AsyncHttpClient(client_factory(OfflineClient(), created)).get(url, timeout=1, max_bytes=10)
        assert created == []

    asyncio.run(case())


@pytest.mark.parametrize("timeout,max_bytes", [(0, 10), (-1, 10), (float("inf"), 10),
                                               (True, 10), (1, 0), (1, True), (1, 1.5)])
def test_http_port_rejects_bad_limits_before_client_creation(timeout, max_bytes):
    async def case():
        created = []
        with pytest.raises(ValueError):
            await AsyncHttpClient(client_factory(OfflineClient(), created)).get(
                "http://chat.example.invalid/metrics", timeout=timeout, max_bytes=max_bytes)
        assert created == []

    asyncio.run(case())


def test_http_read_timeout_closes_the_inflight_stream():
    async def case():
        response = StreamResponse(gate=asyncio.Event())
        client = OfflineClient(response)
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(AsyncHttpClient(client_factory(client, [])).get(
                "http://chat.example.invalid/metrics", timeout=0.01, max_bytes=10), 0.5)
        assert response.closed
        assert len(client.calls) == 1

    asyncio.run(case())


def test_http_cancellation_closes_stream_and_is_not_reclassified():
    async def case():
        response = StreamResponse(gate=asyncio.Event())
        port = AsyncHttpClient(client_factory(OfflineClient(response), []))
        task = asyncio.create_task(port.get("http://chat.example.invalid/metrics", timeout=1, max_bytes=10))
        await asyncio.sleep(0)
        if task.done():
            await task
        await asyncio.wait_for(response.started.wait(), 0.3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.25)
        assert response.closed

    asyncio.run(case())


def test_http_close_cancels_inflight_get_and_rejects_later_requests():
    async def case():
        response = StreamResponse(gate=asyncio.Event())
        client = OfflineClient(response)
        port = AsyncHttpClient(client_factory(client, []))
        task = asyncio.create_task(port.get("http://chat.example.invalid/metrics", timeout=1, max_bytes=10))
        await asyncio.sleep(0)
        if task.done():
            await task
        await asyncio.wait_for(response.started.wait(), 0.3)
        await asyncio.wait_for(port.close(), 0.25)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert response.closed and client.close_calls == 1
        with pytest.raises(RuntimeError):
            await port.get("http://chat.example.invalid/metrics", timeout=1, max_bytes=10)

    asyncio.run(case())


def test_http_transport_failure_is_not_retried():
    async def case():
        client = OfflineClient(OSError("PRIVATE transport detail"))
        with pytest.raises(OSError):
            await AsyncHttpClient(client_factory(client, [])).get(
                "http://chat.example.invalid/metrics", timeout=1, max_bytes=10)
        assert len(client.calls) == 1

    asyncio.run(case())
