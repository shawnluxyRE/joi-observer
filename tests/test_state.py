"""REQ-001 的公开状态行为；不检查私有容器，不把未实现当作成功。"""

from dataclasses import FrozenInstanceError, replace

import pytest

from joi_observer.data.models import CollectionResult, MetricCollectionResult, Metric, ObjectKey, ObjectSpec
from joi_observer.data.state import MonitorState
from joi_observer.error_log import ErrorKind, Failure


KEY = ObjectKey("vllm", "chat")
SPEC = ObjectSpec(KEY, (Metric("running", None),))
FAILURE = Failure(ErrorKind.TIMEOUT, "collection.timeout", "Collection timed out.")


def state_at(now=0.0, **kwargs):
    return MonitorState((SPEC,), clock=lambda: now, **kwargs)


def success(value):
    return MetricCollectionResult(KEY, (Metric("running", value),))


def test_ac101_initial_unknown_is_not_stale_or_zero():
    snapshot = state_at().snapshot()
    assert snapshot.revision == 0
    assert snapshot.objects[0].metrics == (Metric("running", None),)
    assert snapshot.objects[0].sampled_at is None
    assert not snapshot.objects[0].stale


def test_ac101_first_failure_marks_stale_with_no_error_in_snapshot():
    state = state_at()
    state.accept(CollectionResult(KEY, failure=FAILURE), sampled_at=0)
    item = state.snapshot().objects[0]
    assert item.stale and item.metrics[0].value is None
    assert item.history[0].metrics is None
    assert "Collection timed out" not in repr(item)
    assert not hasattr(item, "failure")


@pytest.mark.parametrize("failure_type", [CollectionResult, MetricCollectionResult])
def test_failure_retains_value_inserts_gap_and_success_recovers(failure_type):
    state = state_at(2)
    state.accept(success(7), sampled_at=0)
    state.accept(failure_type(KEY, failure=FAILURE), sampled_at=1)
    failed = state.snapshot().objects[0]
    assert failed.stale and failed.metrics[0].value == 7
    assert failed.metrics == success(7).metrics
    assert failed.history[-1].metrics is None
    state.accept(success(0), sampled_at=2)
    recovered = state.snapshot().objects[0]
    assert not recovered.stale and recovered.metrics[0].value == 0
    assert recovered.history[-1].metrics == (Metric("running", 0),)
    assert failed.stale  # 后续写入不能更改已经交给读者的旧快照。


def test_snapshot_is_deeply_immutable_and_reading_does_not_update_revision():
    state = state_at()
    view = state.snapshot()
    with pytest.raises(FrozenInstanceError):
        view.objects[0].stale = True
    assert isinstance(view.objects, tuple)
    assert isinstance(view.objects[0].metrics, tuple)
    assert state.snapshot().revision == view.revision


def test_history_uses_inclusive_sixty_second_window_and_point_cap():
    now = [0.0]
    state = MonitorState((SPEC,), clock=lambda: now[0], max_history_points=3)
    for stamp in (0, 1, 30, 60):
        now[0] = stamp
        state.accept(success(stamp), sampled_at=stamp)
    assert [p.sampled_at for p in state.snapshot().objects[0].history] == [1, 30, 60]
    now[0] = 61
    assert [p.sampled_at for p in state.snapshot().objects[0].history] == [1, 30, 60]
    now[0] = 61.1
    assert [p.sampled_at for p in state.snapshot().objects[0].history] == [30, 60]
    now[0] = 121
    assert state.snapshot().objects[0].history == ()
    assert state.snapshot().objects[0].metrics[0].value == 60


def test_partial_failure_preserves_only_missing_fields():
    state = MonitorState((ObjectSpec(KEY, (Metric("a", None), Metric("b", None))),),
                         clock=lambda: 1)
    state.accept(MetricCollectionResult(KEY, (Metric("a", 1), Metric("b", 2))), sampled_at=0)
    state.accept(MetricCollectionResult(KEY, (Metric("a", 3),), failure=FAILURE), sampled_at=1)
    item = state.snapshot().objects[0]
    assert item.metrics == (Metric("a", 3), Metric("b", 2))
    assert item.stale
    assert item.history[-1].metrics is None


@pytest.mark.parametrize("value,applicable", [(None, True), (None, False), (0, True), ("Exited", True)])
def test_successful_unknown_inapplicable_zero_or_exited_is_not_failure(value, applicable):
    state = state_at()
    state.accept(MetricCollectionResult(KEY, (Metric("running", value, applicable=applicable),)), sampled_at=0)
    assert not state.snapshot().objects[0].stale


@pytest.mark.parametrize("stamp", [-1, 0, float("nan"), float("inf")])
def test_invalid_or_out_of_order_commit_is_atomic(stamp):
    state = state_at()
    state.accept(success(4), sampled_at=0)
    before = state.snapshot()
    with pytest.raises(ValueError):
        state.accept(success(8), sampled_at=stamp)
    assert state.snapshot() == before


def test_unknown_key_and_fields_are_rejected_without_mutation():
    state = state_at()
    before = state.snapshot()
    with pytest.raises(KeyError):
        state.accept(MetricCollectionResult(ObjectKey("gpu", "unknown")), sampled_at=0)
    with pytest.raises(ValueError):
        state.accept(MetricCollectionResult(KEY, (Metric("missing", 1),)), sampled_at=0)
    assert state.snapshot() == before


def test_dynamic_registration_is_ordered_and_idempotent():
    state = state_at()
    new_spec = ObjectSpec(ObjectKey("gpu", "GPU-1"), (Metric("util", None, "%"),))
    state.register(new_spec)
    before = state.snapshot()
    state.register(new_spec)
    assert state.snapshot() == before
    assert [item.key for item in before.objects] == [KEY, new_spec.key]


def test_public_base_contains_only_identity_and_failure():
    result = CollectionResult(KEY, failure=FAILURE)
    assert result.key == KEY and result.failure == FAILURE
    assert not hasattr(result, "metrics")
    assert not hasattr(result, "observation")
    assert not hasattr(result, "vllm")


@pytest.mark.parametrize("constructor,kwargs", [
    (CollectionResult, {"metrics": (Metric("running", 25),)}),
    (CollectionResult, {"observation": None}),
    (CollectionResult, {"vllm": None}),
    (MetricCollectionResult, {"observation": None}),
])
def test_foreign_payload_is_not_a_constructor_parameter(constructor, kwargs):
    with pytest.raises(TypeError):
        constructor(KEY, **kwargs)


@pytest.mark.parametrize("constructor,args", [
    (CollectionResult, (KEY, FAILURE)),
    (MetricCollectionResult, (KEY, (Metric("running", 25),), FAILURE)),
])
def test_failure_requires_a_keyword_and_cannot_change_payload_position(constructor, args):
    with pytest.raises(TypeError):
        constructor(*args)


@pytest.mark.parametrize("result", [
    CollectionResult(KEY, failure=FAILURE),
    MetricCollectionResult(KEY, (Metric("running", 25),), failure=FAILURE),
])
def test_common_results_are_frozen_and_replace_preserves_fields(result):
    with pytest.raises(FrozenInstanceError):
        result.failure = None
    changed = replace(result, key=ObjectKey("test", "next"))
    assert type(changed) is type(result)
    assert changed.failure == FAILURE and result.key == KEY
    if isinstance(result, MetricCollectionResult):
        assert changed.metrics == result.metrics


def test_empty_base_success_is_rejected_atomically_even_for_empty_spec():
    state = MonitorState((ObjectSpec(KEY),), clock=lambda: 0)
    before = state.snapshot()
    with pytest.raises(ValueError):
        state.accept(CollectionResult(KEY), sampled_at=0)
    assert state.snapshot() == before

