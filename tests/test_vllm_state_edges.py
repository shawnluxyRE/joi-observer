"""REQ-004 independent group continuity and numeric/state boundary regressions."""

from dataclasses import replace
import math

import pytest

from joi_observer.config import ModelConfig, ModelType
from joi_observer.data.models import CollectionResult, MetricCollectionResult, Metric, ObjectKey, ObjectSpec
from joi_observer.data.state import MonitorState
from joi_observer.data.vllm import (
    ChatEngineSample, PoolingEngineSample, CounterSample as C, LatencySample as L,
    VllmAccumulator, VllmCollectionResult, VllmObservation, make_vllm_spec,
)
from joi_observer.data.vllm_window import EngineCounter, LatencyInterval, counter_rate, weighted_latency
from joi_observer.error_log import ErrorKind, Failure


SPEC = make_vllm_spec(ModelConfig("chat", ModelType.CHAT, "served", "http://127.0.0.1:8000"))
FAILURE = Failure(ErrorKind.TIMEOUT, "collection.timeout", "Collection timed out.")


def engine(identity="0", **changes):
    return replace(ChatEngineSample(identity, running=3, waiting=7, queue=L(0, 0, 10),
                                   kv_cache_fraction=.25, prompt_tokens=C(1000, 10),
                                   generation_tokens=C(200, 10), ttft=L(0, 0, 10)), **changes)


def result(*engines, failure=None, epoch=10):
    return VllmCollectionResult(SPEC.key, VllmObservation(ModelType.CHAT, "served",
                                                         engines or (engine(),), epoch), failure=failure)


def values(metrics):
    return {metric.name: metric.value for metric in metrics}


@pytest.mark.parametrize("old,new", [(None, 10), (10, None), (10, 11)])
def test_creation_marker_change_only_breaks_its_own_group(old, new):
    acc = VllmAccumulator(SPEC)
    acc.accept(result(engine(generation_tokens=C(200, old))), sampled_at=0)
    changed = acc.accept(result(engine(generation_tokens=C(400, new), prompt_tokens=C(2000, 10),
                                       ttft=L(4, 2, 10))), sampled_at=2)
    assert values(changed)["decode_rate"] is None
    assert values(changed)["prefill_rate"] == 500
    assert values(changed)["ttft_seconds"] == 2
    recovered = acc.accept(result(engine(generation_tokens=C(410, new))), sampled_at=3)
    assert values(recovered)["decode_rate"] == 10


@pytest.mark.parametrize("old,new", [(None, 10), (10, None), (10, 11)])
def test_process_marker_change_breaks_every_group_but_retains_verified_window(old, new):
    acc = VllmAccumulator(SPEC)
    acc.accept(result(epoch=old), sampled_at=0)
    acc.accept(result(engine(ttft=L(4, 2, 10)), epoch=old), sampled_at=2)
    changed = values(acc.accept(result(engine(generation_tokens=C(800, 10), prompt_tokens=C(3000, 10),
                                             ttft=L(100, 10, 10)), epoch=new), sampled_at=3))
    assert changed["decode_rate"] is None and changed["prefill_rate"] is None
    assert changed["ttft_seconds"] == 2


def test_missing_engine_shard_preserves_whole_field_and_only_breaks_affected_baseline():
    acc = VllmAccumulator(SPEC)
    acc.accept(result(engine("a"), engine("b")), sampled_at=0)
    acc.accept(result(engine("a", generation_tokens=C(300, 10)),
                      engine("b", generation_tokens=C(300, 10))), sampled_at=2)
    partial = values(acc.accept(result(
        engine("a", running=10, waiting=None, kv_cache_fraction=None, generation_tokens=None),
        engine("b", running=10, waiting=1, kv_cache_fraction=.75, generation_tokens=C(400, 10)),
        failure=FAILURE), sampled_at=3))
    assert (partial["running"], partial["waiting"], partial["total"]) == (20, 14, 20)
    assert partial["kv_cache_percent"] == 25 and partial["decode_rate"] == 100
    recovered = values(acc.accept(result(
        engine("b", generation_tokens=C(500, 10), prompt_tokens=C(1100, 10)),
        engine("a", generation_tokens=C(500, 10), prompt_tokens=C(1100, 10))), sampled_at=4))
    assert recovered["decode_rate"] is None and recovered["prefill_rate"] == 200


def test_independent_failure_recovery_does_not_erase_other_latency_observations():
    acc = VllmAccumulator(SPEC)
    acc.accept(result(), sampled_at=0)
    acc.accept(result(engine(ttft=L(4, 2, 10), queue=L(2, 2, 10))), sampled_at=2)
    partial = values(acc.accept(result(engine(ttft=None, queue=L(6, 4, 10)), failure=FAILURE), sampled_at=3))
    assert partial["ttft_seconds"] == 2 and partial["queue_seconds"] == 1.5
    recovered = values(acc.accept(result(engine(ttft=L(99, 10, 10), queue=L(9, 5, 10))), sampled_at=4))
    assert recovered["ttft_seconds"] == 2 and recovered["queue_seconds"] == 1.8
    assert values(acc.metrics(now=63))["ttft_seconds"] is None
    assert values(acc.metrics(now=63))["queue_seconds"] == 3


def test_multi_engine_latency_weights_observations_and_survives_sum_overflow():
    acc = VllmAccumulator(SPEC)
    acc.accept(result(engine("a"), engine("b")), sampled_at=0)
    current = values(acc.accept(result(engine("a", ttft=L(1e308, 1, 10), queue=L(4, 2, 10)),
                                       engine("b", ttft=L(1e308, 1, 10), queue=L(5, 1, 10))), sampled_at=2))
    assert current["ttft_seconds"] == 1e308
    assert current["queue_seconds"] == 3


@pytest.mark.parametrize("new", [L(1, 1, 10), L(10, 2, 10), L(3, 2, 10), L(20, 4, 11)])
def test_one_engine_reset_or_inconsistent_histogram_discards_the_whole_interval(new):
    acc = VllmAccumulator(SPEC)
    acc.accept(result(engine("a", ttft=L(4, 2, 10)), engine("b")), sampled_at=0)
    current = values(acc.accept(result(engine("a", ttft=new),
                                       engine("b", ttft=L(100, 5, 10))), sampled_at=2))
    assert current["ttft_seconds"] is None


@pytest.mark.parametrize("bad", [
    engine(queue=L(math.inf, 1)), engine(queue=L(1, True)),
    engine(prompt_tokens=C(True)), engine(prompt_tokens=C(0, math.nan)),
    engine(""), engine("bad\n"), engine(kv_cache_fraction=True),
])
def test_rejection_does_not_advance_time_or_change_existing_baselines(bad):
    acc = VllmAccumulator(SPEC)
    acc.accept(result(), sampled_at=0)
    with pytest.raises(ValueError):
        acc.accept(result(bad, failure=FAILURE), sampled_at=2)
    # The same timestamp is still available, and the old baseline is intact.
    current = values(acc.accept(result(engine(generation_tokens=C(400, 10))), sampled_at=2))
    assert current["decode_rate"] == 100


@pytest.mark.parametrize("kwargs", [
    {"history_seconds": 0}, {"history_seconds": True}, {"history_seconds": math.inf},
    {"max_intervals": 0}, {"max_intervals": True}, {"max_intervals": 1.5},
])
def test_accumulator_validates_window_bounds_at_construction(kwargs):
    with pytest.raises(ValueError):
        VllmAccumulator(SPEC, **kwargs)


def test_state_registration_failure_and_projection_keep_generic_objects_independent():
    clock = [0]
    generic = ObjectSpec(ObjectKey("host", "cpu"), (Metric("usage", None),))
    state = MonitorState((generic,), clock=lambda: clock[0], max_history_points=2)
    state.register(SPEC)
    state.accept(MetricCollectionResult(generic.key, (Metric("usage", 25),)), sampled_at=0)
    state.accept(result(), sampled_at=0)
    clock[0] = 2
    state.accept(result(engine(generation_tokens=C(400, 10), ttft=L(4, 2, 10))), sampled_at=2)
    before = state.snapshot()
    with pytest.raises(ValueError):
        state.accept(result(engine(queue=L(1, 0))), sampled_at=3)
    assert state.snapshot() == before
    clock[0] = 3
    state.accept(CollectionResult(SPEC.key, failure=FAILURE), sampled_at=3)
    current = state.snapshot()
    assert current.objects[0].metrics == (Metric("usage", 25),)
    assert len(current.objects[1].history) == 2
    assert current.objects[1].history[-1].metrics is None
    clock[0] = 63
    expired = state.snapshot()
    assert expired.revision == current.revision
    assert values(expired.objects[1].metrics)["ttft_seconds"] is None


def test_large_representable_rate_with_huge_counter_is_supported():
    assert counter_rate((EngineCounter("a", 0),), (EngineCounter("a", 10**399),),
                        elapsed=1e300) == pytest.approx(1e99)


@pytest.mark.parametrize("time", [True, -1, math.inf, math.nan, 10**400])
def test_invalid_projection_time_does_not_change_accumulator(time):
    acc = VllmAccumulator(SPEC)
    acc.accept(result(), sampled_at=2)
    before = acc.metrics(now=2)
    with pytest.raises(ValueError):
        acc.metrics(now=time)
    assert acc.metrics(now=2) == before


def test_state_latency_window_excludes_straddling_intervals_at_read_time():
    clock = [0]
    state = MonitorState((SPEC,), clock=lambda: clock[0])
    state.accept(result(), sampled_at=0)
    state.accept(result(engine(ttft=L(4, 2, 10))), sampled_at=2)
    state.accept(result(engine(ttft=L(9, 3, 10))), sampled_at=4)
    clock[0] = 60
    before = state.snapshot()
    assert values(before.objects[0].metrics)["ttft_seconds"] == 3

    # [0, 2] stops contributing as soon as the left boundary moves past 0.
    # The observations are not prorated across the remaining overlap.
    for now, expected in ((60.1, 5), (62, 5), (62.1, None)):
        clock[0] = now
        current = state.snapshot()
        assert values(current.objects[0].metrics)["ttft_seconds"] == expected
        assert current.revision == before.revision
        assert not current.objects[0].stale
    assert values(before.objects[0].metrics)["ttft_seconds"] == 3


def test_expired_projection_does_not_discard_intervals_or_advance_baselines():
    acc = VllmAccumulator(SPEC)
    acc.accept(result(), sampled_at=0)
    acc.accept(result(engine(ttft=L(4, 2, 10), generation_tokens=C(400, 10))), sampled_at=2)
    assert values(acc.metrics(now=100))["ttft_seconds"] is None
    # Each projection may use any time at or after the latest submission.
    assert values(acc.metrics(now=2))["ttft_seconds"] == 2
    current = values(acc.accept(result(engine(ttft=L(9, 3, 10),
                                             generation_tokens=C(500, 10))), sampled_at=3))
    assert current["ttft_seconds"] == 3
    assert current["decode_rate"] == 100


@pytest.mark.parametrize("kind", [ModelType.EMBEDDING, ModelType.RERANKER])
@pytest.mark.parametrize("partial", [False, True])
def test_pooling_state_failure_recovery_preserves_only_verified_latency_and_history(kind, partial):
    cfg = ModelConfig("pooling", kind, "pooling-served", "http://offline.invalid:8000")
    spec = make_vllm_spec(cfg)
    clock = [0]
    state = MonitorState((spec,), clock=lambda: clock[0])

    def submit(at, completed, latency, *, failure=None):
        clock[0] = at
        sample = PoolingEngineSample("0", running=3, waiting=0, queue=L(0, 0, 10),
                                     completed_sequences=completed, latency=latency)
        incoming = VllmCollectionResult(
            spec.key, VllmObservation(kind, "pooling-served", (sample,), 10), failure=failure)
        state.accept(incoming, sampled_at=at)
        return state.snapshot().objects[0]

    submit(0, C(10, 10), L(0, 0, 10))
    healthy = submit(2, C(16, 10), L(4, 2, 10))
    assert values(healthy.metrics)["rate"] == 3
    if partial:
        failed = submit(3, None, L(9, 3, 10), failure=FAILURE)
    else:
        clock[0] = 3
        state.accept(CollectionResult(spec.key, failure=FAILURE), sampled_at=3)
        failed = state.snapshot().objects[0]
    assert failed.stale and failed.history[-1].metrics is None
    assert values(failed.metrics)["rate"] == 3

    recovered = submit(4, C(22, 10), L(13, 4, 10))
    assert not recovered.stale
    assert values(recovered.metrics)["rate"] is None
    assert values(recovered.history[-1].metrics)["rate"] is None
    final = submit(6, C(28, 10), L(18, 5, 10))
    assert values(final.metrics)["rate"] == 3
    assert values(final.metrics)["latency_seconds"] == pytest.approx(3.6 if partial else 3)
    assert final.history[2].metrics is None
    assert values(final.history[-1].metrics)["rate"] == 3
    assert not healthy.stale and values(healthy.metrics)["rate"] == 3


def test_tiny_latency_with_huge_count_uses_relative_tolerance_and_stays_nonzero():
    mean = weighted_latency((LatencyInterval(0, 1, 1e308, 10**400),), now=1)
    # The default 1e-12 absolute tolerance would incorrectly accept zero here.
    assert mean > 0
    assert mean == pytest.approx(1e-92, rel=1e-12, abs=0.0)


_LATENCY_GROUPS = (
    (ModelType.CHAT, "ttft", "ttft_seconds"),
    (ModelType.CHAT, "queue", "queue_seconds"),
    (ModelType.EMBEDDING, "latency", "latency_seconds"),
    (ModelType.EMBEDDING, "queue", "queue_seconds"),
    (ModelType.RERANKER, "latency", "latency_seconds"),
    (ModelType.RERANKER, "queue", "queue_seconds"),
)


def _two_engine_latency_accumulator(kind):
    cfg = ModelConfig("exact-window", kind, "served", "http://offline.invalid:8000")
    spec = make_vllm_spec(cfg)
    acc = VllmAccumulator(spec)
    if kind is ModelType.CHAT:
        samples = tuple(engine(identity) for identity in ("a", "b"))
    else:
        samples = tuple(PoolingEngineSample(identity, running=0, waiting=0, queue=L(0, 0, 10),
                                            completed_sequences=C(0, 10), latency=L(0, 0, 10))
                        for identity in ("a", "b"))

    def submit(at, current):
        return acc.accept(VllmCollectionResult(
            spec.key, VllmObservation(kind, "served", current, 10)), sampled_at=at)

    submit(0, samples)
    return acc, samples, submit


@pytest.mark.parametrize("kind,field,metric", _LATENCY_GROUPS)
@pytest.mark.parametrize("reverse", [False, True])
def test_every_latency_group_rounds_once_after_global_weighting(kind, field, metric, reverse):
    tiny = math.ulp(0.0)
    assert tiny > 0
    acc, samples, submit = _two_engine_latency_accumulator(kind)
    updated = (replace(samples[0], **{field: L(tiny, 2, 10)}),
               replace(samples[1], **{field: L(tiny, 1, 10)}))
    current = submit(2, updated[::-1] if reverse else updated)
    assert values(current)[metric] == tiny
    # The closed left boundary includes the original complete interval.
    assert values(acc.metrics(now=60))[metric] == tiny
    assert values(acc.metrics(now=60.1))[metric] is None
    assert values(acc.metrics(now=2))[metric] == tiny  # Expiry projection is read-only.
    assert values(current)[metric] == tiny


@pytest.mark.parametrize("kind,field,metric", _LATENCY_GROUPS)
def test_global_latency_combines_raw_intervals_before_rounding_and_expiry(kind, field, metric):
    tiny = math.ulp(0.0)
    acc, samples, submit = _two_engine_latency_accumulator(kind)
    first = (replace(samples[0], **{field: L(tiny, 2, 10)}), samples[1])
    submit(2, first)
    current = submit(4, (first[0], replace(samples[1], **{field: L(4 * tiny, 1, 10)})))
    # Five binary64 steps / three observations rounds to two steps. The first
    # engine's separate mean would round to zero and change this global result.
    assert values(current)[metric] == 2 * tiny
    assert values(acc.metrics(now=60))[metric] == 2 * tiny
    assert values(acc.metrics(now=60.1))[metric] == 4 * tiny
    assert values(acc.metrics(now=62))[metric] == 4 * tiny
    assert values(acc.metrics(now=62.1))[metric] is None


@pytest.mark.parametrize("kind,field,metric", _LATENCY_GROUPS)
def test_global_latency_retains_nonzero_mean_with_unrepresentable_sum_and_count(kind, field, metric):
    acc, samples, submit = _two_engine_latency_accumulator(kind)
    updated = tuple(replace(sample, **{field: L(1e308, 10**400, 10)}) for sample in samples)
    current = submit(2, updated)
    mean = values(current)[metric]
    assert mean > 0
    assert mean == pytest.approx(1e-92, rel=1e-12, abs=0.0)
    assert values(acc.metrics(now=2))[metric] == mean


@pytest.mark.parametrize("kind", tuple(ModelType))
def test_raw_multi_engine_partial_rate_recovery_and_window_roundtrip(tmp_path, kind):
    import asyncio
    from joi_observer.collectors.vllm import HttpResponse, VllmCollector
    from joi_observer.config import AppConfig, LogConfig
    from joi_observer.error_log import ErrorLog
    from joi_observer.ipc.protocol import SnapshotEnvelope, build_metadata, decode_envelope, encode_envelope
    from joi_observer.monitor import Monitor
    from test_vllm_full_response_integration import MemoryLogIO

    async def scenario():
        cfg = ModelConfig("raw-multi", kind, "Display alias", "http://offline.invalid:8000",
                          served_model_name="served")
        primary = "vllm:generation_tokens" if kind is ModelType.CHAT else "vllm:request_success"
        latency = ("vllm:time_to_first_token_seconds" if kind is ModelType.CHAT
                   else "vllm:e2e_request_latency_seconds")
        primary_metric = "decode_rate" if kind is ModelType.CHAT else "rate"
        latency_metric = "ttft_seconds" if kind is ModelType.CHAT else "latency_seconds"
        primary_counts = ((10, 20), (14, 28), (None, 32), (20, 36), (24, 44))
        prompt_counts = ((100, 200), (104, 212), (106, 216), (108, 220), (110, 224))
        queue_samples = (((0, 0), (0, 0)), ((2, 1), (6, 3)), ((5, 2), (7, 4)),
                         ((5, 2), (7, 4)), ((7, 3), (11, 6)))
        latency_samples = (((0, 0), (0, 0)), ((4, 2), (6, 1)), ((9, 3), (8, 2)),
                           ((9, 3), (8, 2)), ((10, 4), (16, 3)))

        def raw_metrics(round_index):
            lines = ["process_start_time_seconds 10"]
            # The second scrape reverses exposition order without changing
            # engine identity. Expected values below use per-engine deltas.
            order = (1, 0) if round_index == 1 else (0, 1)
            for index in order:
                labels = f'model_name="served",engine="{("a", "b")[index]}"'

                def emit(name, value, extra=""):
                    if value is not None:
                        lines.append(f"{name}{{{labels}{extra}}} {value}")

                emit("vllm:num_requests_running", (7, 11)[index])
                emit("vllm:num_requests_waiting", (1, 2)[index])
                counter_labels = '' if kind is ModelType.CHAT else ',finished_reason="stop"'
                emit(primary + "_total", primary_counts[round_index][index], counter_labels)
                emit(primary + "_created", 10, counter_labels)
                if kind is ModelType.CHAT:
                    emit("vllm:prompt_tokens_total", prompt_counts[round_index][index])
                    emit("vllm:prompt_tokens_created", 10)
                    emit("vllm:kv_cache_usage_perc", (0.2, 0.8)[index])
                else:
                    emit("vllm:request_success_total", 999999, ',finished_reason="abort"')
                for base, samples in (("vllm:request_queue_time_seconds", queue_samples),
                                      (latency, latency_samples)):
                    seconds, count = samples[round_index][index]
                    emit(base + "_sum", seconds)
                    emit(base + "_count", count)
                    emit(base + "_created", 10)
            return ("\n".join(lines) + "\n").encode()

        class RawPort:
            body = b""
            closed = False

            async def get(self, url, *, timeout, max_bytes):
                await asyncio.sleep(0)
                body = (b'{"version":"0.31.0"}' if url.endswith("/version") else
                        b'{"data":[{"id":"served"}]}' if url.endswith("/v1/models") else self.body)
                return HttpResponse(200, body)

            async def close(self):
                self.closed = True

        port = RawPort()
        collector = VllmCollector(cfg, port)
        clock = [0.0]
        state = MonitorState((collector.spec,), clock=lambda: clock[0])
        log_io = MemoryLogIO()
        log = ErrorLog(LogConfig(directory=tmp_path / "unused-log-path"), io=log_io)
        assert log.prepare()
        monitor = Monitor((collector,), state, log, clock=lambda: clock[0])
        metadata = build_metadata(AppConfig(mount_points=(), models=(cfg,)),
                                  hostname="Host", system="Ubuntu 24.04")
        snapshots = []
        try:
            for round_index, at in enumerate((0.0, 2.0, 3.0, 4.0, 6.0)):
                clock[0] = at
                port.body = raw_metrics(round_index)
                for _ in range(100):
                    await monitor.poll()
                    if state.snapshot().objects[0].sampled_at == at:
                        break
                else:
                    raise AssertionError("Real raw-source collection did not complete")
                snapshot = state.snapshot()
                envelope = SnapshotEnvelope("instance", "config", round_index + 1, at,
                                            metadata, snapshot)
                assert decode_envelope(encode_envelope(envelope)) == envelope
                item = snapshot.objects[0]
                current = values(item.metrics)
                assert (current["running"], current["waiting"], current["total"]) == (18, 3, 21)
                assert current[primary_metric] == (None, 6.0, 6.0, None, 6.0)[round_index]
                assert current["queue_seconds"] == (None, 2.0, 2.0, 2.0, 2.0)[round_index]
                expected_latency = (None, 10 / 3, 17 / 5, 17 / 5, 26 / 7)[round_index]
                assert (current[latency_metric] is None if expected_latency is None
                        else current[latency_metric] == pytest.approx(expected_latency))
                assert item.stale is (round_index == 2)
                assert (item.history[-1].metrics is None) is (round_index == 2)
                if kind is ModelType.CHAT:
                    assert current["prefill_rate"] == (None, 8.0, 6.0, 6.0, 3.0)[round_index]
                    assert current["kv_cache_percent"] == 50.0
                snapshots.append(snapshot)
            assert await log.flush()
            assert len(log_io.lines) == 1
            revision = snapshots[-1].revision
            for now, expected in ((60.0, 26 / 7), (60.1, 4.0), (62.0, 4.0),
                                  (62.1, 4.5), (64.0, 4.5), (64.1, None)):
                clock[0] = now
                snapshot = state.snapshot()
                actual = values(snapshot.objects[0].metrics)[latency_metric]
                assert actual is None if expected is None else actual == pytest.approx(expected)
                assert snapshot.revision == revision
            assert values(snapshots[1].objects[0].metrics)[primary_metric] == 6.0
        finally:
            await monitor.stop()
            await log.close()
        assert port.closed
    asyncio.run(scenario())


@pytest.mark.parametrize("kind", tuple(ModelType))
@pytest.mark.parametrize("interval", [1.0, 60.0])
def test_raw_scientific_counters_survive_monitor_and_wire_at_production_intervals(kind, interval):
    """Valid raw boundary values must not turn a rate overflow into source failure."""
    import asyncio
    from joi_observer.collectors.vllm import HttpResponse, VllmCollector
    from joi_observer.config import AppConfig
    from joi_observer.ipc.protocol import SnapshotEnvelope, build_metadata, decode_envelope, encode_envelope
    from joi_observer.monitor import Monitor
    from test_state_monitor_edges import Log

    async def scenario():
        cfg = ModelConfig("numeric-boundary", kind, "Display", "http://offline.invalid:8000",
                          served_model_name="served")
        primary = "vllm:generation_tokens" if kind is ModelType.CHAT else "vllm:request_success"
        primary_metric = "decode_rate" if kind is ModelType.CHAT else "rate"
        latency = ("vllm:time_to_first_token_seconds" if kind is ModelType.CHAT
                   else "vllm:e2e_request_latency_seconds")
        latency_metric = "ttft_seconds" if kind is ModelType.CHAT else "latency_seconds"

        def raw_metrics(round_index):
            labels = 'model_name="served",engine="0"'
            lines = ["process_start_time_seconds 10"]

            def emit(name, value, extra=""):
                lines.append(f"{name}{{{labels}{extra}}} {value}")

            # Each token is short and within the parser's 400-digit integer bound.
            emit("vllm:num_requests_running", "1e399")
            emit("vllm:num_requests_waiting", "2e399")
            reason = '' if kind is ModelType.CHAT else ',finished_reason="stop"'
            emit(primary + "_total", ("1e399", "2e399", "2e399")[round_index], reason)
            if kind is ModelType.CHAT:
                # Adjacent integers above float's exact range provide a finite control.
                emit("vllm:prompt_tokens_total", 9007199254740992 + round_index)
                emit("vllm:kv_cache_usage_perc", "0.25")
            else:
                emit("vllm:request_success_total", "9e399", ',finished_reason="abort"')
            for base in ("vllm:request_queue_time_seconds", latency):
                emit(base + "_sum", (0, 4, 7)[round_index])
                emit(base + "_count", (0, 2, 3)[round_index])
            return ("\n".join(lines) + "\n").encode()

        class RawPort:
            body = b""
            closed = False

            async def get(self, url, *, timeout, max_bytes):
                await asyncio.sleep(0)
                body = (b'{"version":"0.31.0"}' if url.endswith("/version") else
                        b'{"data":[{"id":"served"}]}' if url.endswith("/v1/models") else self.body)
                return HttpResponse(200, body)

            async def close(self):
                self.closed = True

        port = RawPort()
        collector = VllmCollector(cfg, port)
        clock = [0.0]
        state = MonitorState((collector.spec,), clock=lambda: clock[0])
        log = Log()
        monitor = Monitor((collector,), state, log, interval=interval, clock=lambda: clock[0])
        metadata = build_metadata(AppConfig(mount_points=(), models=(cfg,), sample_interval=interval),
                                  hostname="Host", system="Ubuntu 24.04")
        snapshots = []
        try:
            for round_index in range(3):
                clock[0] = at = round_index * interval
                port.body = raw_metrics(round_index)
                for _ in range(100):
                    await monitor.poll()
                    if state.snapshot().objects[0].sampled_at == at:
                        break
                else:
                    raise AssertionError("Raw numeric boundary collection did not complete")
                snapshot = state.snapshot()
                envelope = SnapshotEnvelope("numeric-instance", "numeric-config", round_index + 1,
                                            at, metadata, snapshot)
                assert decode_envelope(encode_envelope(envelope)) == envelope
                item = snapshot.objects[0]
                current = values(item.metrics)
                assert (current["running"], current["waiting"], current["total"]) == (
                    10**399, 2 * 10**399, 3 * 10**399)
                assert current[primary_metric] == (None, None, 0.0)[round_index]
                assert not item.stale and item.history[-1].metrics is not None
                expected_latency = (None, 2.0, 3.0 if interval == 60 else 7 / 3)[round_index]
                for name in ("queue_seconds", latency_metric):
                    assert (current[name] is None if expected_latency is None else
                            current[name] == pytest.approx(expected_latency))
                if kind is ModelType.CHAT:
                    assert current["prefill_rate"] == (None if round_index == 0 else 1 / interval)
                    assert current["kv_cache_percent"] == 25.0
                snapshots.append(snapshot)
            assert not log.events
            assert len(snapshots[-1].objects[0].history) == (2 if interval == 60 else 3)
            assert values(snapshots[0].objects[0].metrics)[primary_metric] is None
        finally:
            await monitor.stop()
        assert port.closed

    asyncio.run(scenario())
