"""Public semantic observations to state projection, offline and independent of UI."""

from dataclasses import FrozenInstanceError, replace

import pytest

from joi_observer.config import ModelConfig, ModelType
from joi_observer.data.models import CollectionResult, MetricCollectionResult, Metric, ObjectKey, ObjectSpec
from joi_observer.data.state import MonitorState
from joi_observer.data.vllm import (CounterSample as C, LatencySample as L, EngineSample,
                                    ChatEngineSample, PoolingEngineSample,
                                    VllmCollectionResult, VllmObservation,
                                    VllmAccumulator, make_vllm_spec)
from joi_observer.error_log import ErrorKind, Failure


FAILURE = Failure(ErrorKind.TIMEOUT, "collection.timeout", "Collection timed out.")


def config(kind=ModelType.CHAT, identity="model"):
    return ModelConfig(identity, kind, identity, "http://127.0.0.1:8000")


def engine(identity="0", **changes):
    return replace(ChatEngineSample(identity, running=3, waiting=7, kv_cache_fraction=0.25,
                                   prompt_tokens=C(1000, 10), generation_tokens=C(200, 10),
                                   ttft=L(0, 0, 10), queue=L(0, 0, 10)), **changes)


def pooling_engine(identity="0", **changes):
    return replace(PoolingEngineSample(identity, running=3, waiting=7,
                                      completed_sequences=C(6, 10), queue=L(0, 0, 10),
                                      latency=L(0, 0, 10)), **changes)


def result(cfg, *engines, failure=None, epoch=10):
    if not engines:
        engines = (engine(),) if cfg.type is ModelType.CHAT else (pooling_engine(),)
    return VllmCollectionResult(ObjectKey("vllm", cfg.id), failure=failure,
                                observation=VllmObservation(cfg.type, cfg.served_model_name or cfg.name,
                                                            engines, epoch))


def values(metrics):
    return {m.name: m.value for m in metrics}


@pytest.mark.parametrize("kind", list(ModelType))
def test_static_templates_have_unknown_values_and_type_applicability(kind):
    spec = make_vllm_spec(config(kind))
    metrics = {m.name: m for m in spec.metrics}
    assert all(m.value is None for m in spec.metrics)
    assert metrics["running"].unit == "seq"
    assert metrics["rate"].unit == "seq/s"
    assert metrics["rate"].applicable == (kind is not ModelType.CHAT)
    assert metrics["ttft_seconds"].applicable == (kind is ModelType.CHAT)
    assert metrics["kv_cache_percent"].applicable == (kind is ModelType.CHAT)


def test_first_sample_has_instantaneous_load_and_no_rate_or_latency():
    cfg = config()
    acc = VllmAccumulator(make_vllm_spec(cfg))
    view = values(acc.accept(result(cfg), sampled_at=0))
    assert (view["running"], view["waiting"], view["total"]) == (3, 7, 10)
    assert view["kv_cache_percent"] == 25
    assert view["decode_rate"] is None and view["ttft_seconds"] is None


def test_independent_token_differences_and_weighted_latency():
    cfg = config()
    acc = VllmAccumulator(make_vllm_spec(cfg))
    acc.accept(result(cfg), sampled_at=0)
    view = values(acc.accept(result(cfg, engine(prompt_tokens=C(2000, 10),
                     generation_tokens=C(400, 10), ttft=L(4, 2, 10), queue=L(1, 4, 10))), sampled_at=2))
    assert view["decode_rate"] == 100 and view["prefill_rate"] == 500
    assert view["ttft_seconds"] == 2 and view["queue_seconds"] == 0.25
    acc.accept(result(cfg, engine(prompt_tokens=C(2000, 10), generation_tokens=C(400, 10),
                                 ttft=L(9, 3, 10), queue=L(3, 6, 10))), sampled_at=3)
    view = values(acc.metrics(now=3))
    assert view["ttft_seconds"] == 3 and view["queue_seconds"] == 0.5


@pytest.mark.parametrize("kind", [ModelType.EMBEDDING, ModelType.RERANKER])
def test_pooling_rate_and_own_latency_counts(kind):
    cfg = config(kind)
    acc = VllmAccumulator(make_vllm_spec(cfg))
    acc.accept(result(cfg), sampled_at=0)
    projected = acc.accept(result(cfg, pooling_engine(completed_sequences=C(12, 10),
                                                     latency=L(4, 2, 10), queue=L(1, 4, 10))), sampled_at=2)
    view = values(projected)
    assert view["rate"] == 3 and view["latency_seconds"] == 2
    assert view["queue_seconds"] == 0.25
    assert all(not m.applicable and m.value is None for m in projected
               if m.name in ("decode_rate", "prefill_rate", "ttft_seconds", "kv_cache_percent"))


def test_multi_engine_gauges_sum_kv_means_and_rates_difference_before_sum():
    cfg = config()
    acc = VllmAccumulator(make_vllm_spec(cfg))
    acc.accept(result(cfg, engine("0"), engine("1", kv_cache_fraction=0.75)), sampled_at=0)
    view = values(acc.accept(result(cfg, engine("1", generation_tokens=C(300, 10), kv_cache_fraction=0.75),
                                     engine("0", generation_tokens=C(300, 10))), sampled_at=2))
    assert view["total"] == 20 and view["kv_cache_percent"] == 50
    assert view["decode_rate"] == 100


@pytest.mark.parametrize("changed", [
    engine(generation_tokens=C(1, 10)),
    engine(generation_tokens=C(500, 11)),
    engine("new", generation_tokens=C(500, 10)),
])
def test_counter_reset_creation_or_engine_changes_do_not_create_spikes(changed):
    cfg = config()
    acc = VllmAccumulator(make_vllm_spec(cfg))
    acc.accept(result(cfg), sampled_at=0)
    assert values(acc.accept(result(cfg, changed), sampled_at=2))["decode_rate"] is None


def test_export_process_change_breaks_all_rate_baselines():
    cfg = config()
    acc = VllmAccumulator(make_vllm_spec(cfg))
    acc.accept(result(cfg), sampled_at=0)
    view = values(acc.accept(result(cfg, engine(generation_tokens=C(999, 10)), epoch=11), sampled_at=2))
    assert view["decode_rate"] is None


def test_unrepresentable_rate_is_isolated_and_next_finite_delta_recovers():
    cfg = config()
    acc = VllmAccumulator(make_vllm_spec(cfg))
    acc.accept(result(cfg), sampled_at=0)
    view = values(acc.accept(result(cfg, engine(generation_tokens=C(10**399, 10))), sampled_at=2))
    assert view["decode_rate"] is None and view["total"] == 10
    view = values(acc.accept(result(cfg, engine(generation_tokens=C(10**399 + 10, 10))), sampled_at=4))
    assert view["decode_rate"] == 5


def test_per_engine_reset_cannot_be_masked_by_another_engine_growth():
    cfg = config()
    acc = VllmAccumulator(make_vllm_spec(cfg))
    acc.accept(result(cfg, engine("0"), engine("1")), sampled_at=0)
    view = values(acc.accept(result(cfg, engine("0", generation_tokens=C(1, 10)),
                                   engine("1", generation_tokens=C(1000, 10))), sampled_at=2))
    assert view["decode_rate"] is None


@pytest.mark.parametrize("failure_type", [CollectionResult, VllmCollectionResult])
def test_failure_preserves_value_recovery_never_bridges_failed_interval(failure_type):
    cfg = config()
    acc = VllmAccumulator(make_vllm_spec(cfg))
    acc.accept(result(cfg), sampled_at=0)
    acc.accept(result(cfg, engine(generation_tokens=C(400, 10))), sampled_at=2)
    assert values(acc.accept(failure_type(make_vllm_spec(cfg).key, failure=FAILURE), sampled_at=3))["decode_rate"] == 100
    assert values(acc.accept(result(cfg, engine(generation_tokens=C(900, 10))), sampled_at=4))["decode_rate"] is None
    assert values(acc.accept(result(cfg, engine(generation_tokens=C(910, 10))), sampled_at=5))["decode_rate"] == 10


def test_partial_failure_does_not_mix_gauge_total_or_break_other_counter():
    cfg = config()
    acc = VllmAccumulator(make_vllm_spec(cfg))
    acc.accept(result(cfg), sampled_at=0)
    view = values(acc.accept(result(cfg, engine(running=8, waiting=None,
                                   generation_tokens=C(400, 10)), failure=FAILURE), sampled_at=2))
    assert view["running"] == 8 and view["waiting"] == 7 and view["total"] == 10
    assert view["decode_rate"] == 100


def test_reading_after_window_expiry_does_not_reuse_lifetime_average():
    cfg = config()
    acc = VllmAccumulator(make_vllm_spec(cfg))
    acc.accept(result(cfg, engine(ttft=L(900, 100, 10))), sampled_at=0)
    acc.accept(result(cfg, engine(ttft=L(904, 102, 10))), sampled_at=2)
    old = acc.metrics(now=2)
    assert values(old)["ttft_seconds"] == 2
    assert values(acc.metrics(now=62.1))["ttft_seconds"] is None
    assert values(old)["ttft_seconds"] == 2


def test_counter_reset_retains_already_verified_latency_intervals():
    cfg = config()
    acc = VllmAccumulator(make_vllm_spec(cfg))
    acc.accept(result(cfg), sampled_at=0)
    acc.accept(result(cfg, engine(ttft=L(4, 2, 10))), sampled_at=2)
    acc.accept(result(cfg, engine(ttft=L(0, 0, 11))), sampled_at=3)
    assert values(acc.metrics(now=3))["ttft_seconds"] == 2


def test_interval_count_cap_is_observable_from_weighted_result():
    cfg = config()
    acc = VllmAccumulator(make_vllm_spec(cfg), max_intervals=2)
    for at, total, count in ((0, 0, 0), (1, 100, 1), (2, 104, 3), (3, 109, 4)):
        acc.accept(result(cfg, engine(ttft=L(total, count, 10))), sampled_at=at)
    assert values(acc.metrics(now=3))["ttft_seconds"] == 3


def test_sum_change_without_count_creates_no_observation():
    cfg = config()
    acc = VllmAccumulator(make_vllm_spec(cfg))
    acc.accept(result(cfg, engine(ttft=L(4, 2, 10))), sampled_at=0)
    assert values(acc.accept(result(cfg, engine(ttft=L(5, 2, 10))), sampled_at=2))["ttft_seconds"] is None


def test_state_projects_raw_payload_gaps_windows_and_immutable_snapshots():
    cfg = config()
    clock = [0]
    spec = make_vllm_spec(cfg)
    state = MonitorState((spec,), clock=lambda: clock[0])
    state.accept(result(cfg), sampled_at=0)
    clock[0] = 2
    state.accept(result(cfg, engine(generation_tokens=C(400, 10), ttft=L(4, 2, 10))), sampled_at=2)
    old = state.snapshot()
    assert values(old.objects[0].metrics)["decode_rate"] == 100
    assert not hasattr(old.objects[0], "vllm")
    assert not hasattr(old.objects[0], "observation")
    clock[0] = 3
    state.accept(CollectionResult(spec.key, failure=FAILURE), sampled_at=3)
    current = state.snapshot()
    assert current.objects[0].stale and current.objects[0].history[-1].metrics is None
    assert not old.objects[0].stale
    clock[0] = 63
    expired = state.snapshot()
    assert expired.revision == current.revision
    assert values(expired.objects[0].metrics)["ttft_seconds"] is None
    assert expired.objects[0].history[-1].metrics is None


def test_generic_objects_cannot_silently_accept_vllm_payload():
    cfg = config()
    spec = ObjectSpec(ObjectKey("host", "cpu"), (Metric("usage", None),))
    state = MonitorState((spec,), clock=lambda: 0)
    before = state.snapshot()
    incoming = replace(result(cfg), key=spec.key)
    with pytest.raises(ValueError):
        state.accept(incoming, sampled_at=0)
    assert state.snapshot() == before


@pytest.mark.parametrize("bad", [engine(running=-1), engine(waiting=True),
                                  engine(kv_cache_fraction=2), engine(ttft=L(1, 0))])
def test_invalid_semantic_input_is_atomic(bad):
    cfg = config()
    acc = VllmAccumulator(make_vllm_spec(cfg))
    before = acc.metrics(now=0)
    with pytest.raises(ValueError):
        acc.accept(result(cfg, bad), sampled_at=0)
    assert acc.metrics(now=0) == before


@pytest.mark.parametrize("field", ["running", "waiting", "prompt_tokens", "generation_tokens",
                                   "kv_cache_fraction", "ttft", "queue"])
def test_success_cannot_omit_required_chat_fields(field):
    cfg = config()
    acc = VllmAccumulator(make_vllm_spec(cfg))
    with pytest.raises(ValueError):
        acc.accept(result(cfg, replace(engine(), **{field: None})), sampled_at=0)


@pytest.mark.parametrize("mismatch", ["key", "type", "name", "duplicate_engine", "metric_result"])
def test_mismatched_identity_or_ambiguous_payload_does_not_change_state(mismatch):
    cfg = config()
    acc = VllmAccumulator(make_vllm_spec(cfg))
    acc.accept(result(cfg), sampled_at=0)
    before = acc.metrics(now=0)
    incoming = result(cfg)
    if mismatch == "key":
        incoming = replace(incoming, key=ObjectKey("vllm", "different"))
    elif mismatch == "type":
        incoming = replace(incoming, observation=replace(incoming.observation, model_type=ModelType.EMBEDDING))
    elif mismatch == "name":
        incoming = replace(incoming, observation=replace(incoming.observation, model_name="other"))
    elif mismatch == "duplicate_engine":
        incoming = replace(incoming, observation=replace(incoming.observation, engines=(engine(), engine())))
    else:
        incoming = MetricCollectionResult(incoming.key, (Metric("running", 99, "seq"),))
    with pytest.raises(ValueError):
        acc.accept(incoming, sampled_at=1)
    assert acc.metrics(now=1) == before


@pytest.mark.parametrize("kind,samples", [
    (ModelType.CHAT, (EngineSample("0", running=3, waiting=7, queue=L(0, 0)),)),
    (ModelType.EMBEDDING, (EngineSample("0", running=3, waiting=7, queue=L(0, 0)),)),
    (ModelType.RERANKER, (EngineSample("0", running=3, waiting=7, queue=L(0, 0)),)),
    (ModelType.CHAT, (pooling_engine(),)),
    (ModelType.EMBEDDING, (engine(),)),
    (ModelType.RERANKER, (engine(),)),
    (ModelType.CHAT, (engine("0"), pooling_engine("1"))),
    (ModelType.EMBEDDING, (pooling_engine("0"), engine("1"))),
    (ModelType.RERANKER, (pooling_engine("0"), engine("1"))),
])
@pytest.mark.parametrize("failure", [None, FAILURE])
def test_wrong_engine_family_is_rejected_atomically_even_for_partial_failure(kind, samples, failure):
    cfg = config(kind)
    acc = VllmAccumulator(make_vllm_spec(cfg))
    acc.accept(result(cfg), sampled_at=0)
    before = acc.metrics(now=0)
    with pytest.raises(ValueError):
        acc.accept(result(cfg, *samples, failure=failure), sampled_at=1)
    assert acc.metrics(now=1) == before


@pytest.mark.parametrize("kind", [ModelType.EMBEDDING, ModelType.RERANKER])
def test_pooling_partial_counter_failure_preserves_rate_and_updates_valid_latency(kind):
    cfg = config(kind)
    acc = VllmAccumulator(make_vllm_spec(cfg))
    acc.accept(result(cfg), sampled_at=0)
    acc.accept(result(cfg, pooling_engine(completed_sequences=C(12, 10),
                                         latency=L(4, 2, 10))), sampled_at=2)
    current = values(acc.accept(result(cfg, pooling_engine(completed_sequences=None,
                            latency=L(9, 3, 10)), failure=FAILURE), sampled_at=4))
    assert current["rate"] == 3 and current["latency_seconds"] == 3


def test_sibling_results_expose_only_their_own_payload():
    observed = result(config())
    metrics = MetricCollectionResult(ObjectKey("host", "cpu"), (Metric("usage", 25, "%"),))
    assert isinstance(metrics, CollectionResult) and isinstance(observed, CollectionResult)
    assert not isinstance(metrics, VllmCollectionResult)
    assert not isinstance(observed, MetricCollectionResult)
    assert metrics.metrics == (Metric("usage", 25, "%"),) and not hasattr(metrics, "observation")
    assert observed.observation.model_name == "model" and not hasattr(observed, "metrics")
    assert not hasattr(metrics, "vllm") and not hasattr(observed, "vllm")


def test_vllm_result_does_not_accept_a_metrics_payload():
    with pytest.raises(TypeError):
        VllmCollectionResult(ObjectKey("vllm", "model"), metrics=(Metric("running", 25),))


def test_vllm_failure_requires_a_keyword_and_cannot_change_observation_position():
    observed = result(config())
    with pytest.raises(TypeError):
        VllmCollectionResult(observed.key, observed.observation, FAILURE)


def test_vllm_result_is_frozen_and_replace_preserves_payload():
    observed = result(config(), failure=FAILURE)
    with pytest.raises(FrozenInstanceError):
        observed.failure = None
    changed = replace(observed, key=ObjectKey("vllm", "next"))
    assert type(changed) is VllmCollectionResult and changed.failure == FAILURE
    assert changed.observation is observed.observation
    assert observed.key == ObjectKey("vllm", "model")


def test_metric_success_is_rejected_for_vllm_spec_even_with_complete_fields():
    spec = make_vllm_spec(config())
    state = MonitorState((spec,), clock=lambda: 0)
    before = state.snapshot()
    with pytest.raises(ValueError):
        state.accept(MetricCollectionResult(spec.key, spec.metrics), sampled_at=0)
    assert state.snapshot() == before


def test_public_failure_is_accepted_for_vllm_spec_without_a_payload():
    spec = make_vllm_spec(config())
    state = MonitorState((spec,), clock=lambda: 0)
    state.accept(CollectionResult(spec.key, failure=FAILURE), sampled_at=0)
    current = state.snapshot().objects[0]
    assert current.metrics == spec.metrics and current.stale
    assert current.history[0].metrics is None
