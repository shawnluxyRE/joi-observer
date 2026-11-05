"""Public time-bucket and display-scale contracts using immutable history inputs.

No reducer or renderer results are substituted. Expected positions are simple
examples on declared time grids, and scale examples use explicit decimal tiers.
"""

import asyncio
import builtins
from copy import deepcopy
from dataclasses import FrozenInstanceError
import math
from pathlib import Path
import subprocess
import sys

import pytest

from joi_observer.config import ModelConfig, ModelType
from joi_observer.data.models import HistoryPoint, Metric, ObjectKey, ObjectSnapshot, StateSnapshot
from joi_observer.tui.history import HistoryScale, HistoryScaleTracker, bucket_history


def point(at, value, field="decode_rate", *, applicable=True):
    return HistoryPoint(at, (Metric(field, value, "tok/s" if field == "decode_rate" else "seq/s", applicable),))


def model(identifier="chat", kind=ModelType.CHAT):
    return ModelConfig(identifier, kind, identifier, "http://offline.invalid:8000")


def snapshot(history=(), *, identifier="chat", latest=999999, stale=False):
    return StateSnapshot((ObjectSnapshot(ObjectKey("vllm", identifier),
                                        (Metric("decode_rate", latest, "tok/s"),), stale,
                                        history[-1].sampled_at if history else None, history),), 17)


def one_scale(tracker, data, now, columns=61):
    result = tracker.update(data, now=now, columns=columns)
    assert isinstance(result, tuple) and len(result) == 1
    assert result[0].model_id == "chat" and result[0].field == "decode_rate"
    return result[0]


@pytest.mark.parametrize("columns", (2, 61, 76))
def test_empty_history_returns_fixed_width_unknown_buckets(columns):
    result = bucket_history((), "decode_rate", now=100.0, columns=columns)
    assert result == (None,) * columns
    assert isinstance(result, tuple)


def test_short_history_is_right_aligned_on_fixed_sixty_second_axis():
    history = (point(98, 5), point(100, 0))
    before = deepcopy(history)
    result = bucket_history(history, "decode_rate", now=100.2, columns=61)
    assert result == (None,) * 58 + (5, None, 0)
    assert history == before


def test_fractional_width_grid_uses_full_width_without_stretching_to_first_sample():
    history = (point(40, 1), point(55, 2), point(98, 3), point(100, 4))
    result = bucket_history(history, "decode_rate", now=100.0, columns=76)
    assert [(index, value) for index, value in enumerate(result) if value is not None] == [
        (0, 1), (18, 2), (72, 3), (75, 4),
    ]


def test_current_incomplete_bucket_accepts_latest_point_and_moves_only_at_boundary():
    history = (point(80.2, 3), point(100.1, 7))
    initial = bucket_history(history, "decode_rate", now=100.1, columns=61)
    later = bucket_history(history, "decode_rate", now=100.99, columns=61)
    shifted = bucket_history(history, "decode_rate", now=101.0, columns=61)
    assert initial == later
    assert initial[40] == 3 and initial[60] == 7
    assert shifted == initial[1:] + (None,)


def test_oldest_point_expires_inside_bucket_without_repositioning_other_points():
    history = (point(40.05, 1), point(50.25, 2), point(99.5, 3))
    first = bucket_history(history, "decode_rate", now=100.0, columns=61)
    later = bucket_history(history, "decode_rate", now=100.1, columns=61)
    assert first[0] == 1 and later[0] is None
    assert later[1:] == first[1:]
    assert later[10] == 2 and later[59] == 3


@pytest.mark.parametrize("columns", (2, 17, 61, 76, 101))
@pytest.mark.parametrize("now", (100.0, 100.12345, 1_000_000.4))
def test_closed_window_endpoints_survive_rounding_but_adjacent_outside_points_do_not(columns, now):
    endpoints = (point(now - 60, 3), point(now, 7))
    outside = (point(now - 60 - 1e-6, 1e300), *endpoints, point(now + 1e-6, 1e300))
    result = bucket_history(outside, "decode_rate", now=now, columns=columns)
    assert result == bucket_history(endpoints, "decode_rate", now=now, columns=columns)
    assert result[0] == 3 and result[-1] == 7
    assert sum(value is not None for value in result) == 2


def test_half_open_bucket_boundary_keeps_adjacent_samples_separate():
    history = (point(69.999999, 3), point(70, 8), point(70.000001, 2))
    result = bucket_history(history, "decode_rate", now=100, columns=61)
    assert [(index, value) for index, value in enumerate(result) if value is not None] == [(29, 3), (30, 8)]


def test_same_bucket_takes_maximum_independent_of_input_order():
    history = (point(70.1, 3), point(70.2, 9), point(70.3, 0))
    expected = (None,) * 30 + (9,) + (None,) * 30
    assert bucket_history(history, "decode_rate", now=100, columns=61) == expected
    assert bucket_history(tuple(reversed(history)), "decode_rate", now=100, columns=61) == expected


@pytest.mark.parametrize("gap", (
    HistoryPoint(70.2, None), HistoryPoint(70.2, ()),
    point(70.2, 1000, field="rate"), point(70.2, None),
    point(70.2, None, applicable=False),
), ids=("failed", "missing-metrics", "missing-primary", "unknown-primary", "not-applicable"))
def test_any_gap_in_bucket_hides_other_values_without_fabricating_zero(gap):
    history = (point(70.1, 1e300), gap, point(70.3, 0), point(80.2, 0))
    expected = (None,) * 40 + (0,) + (None,) * 20
    assert bucket_history(history, "decode_rate", now=100, columns=61) == expected
    assert bucket_history(tuple(reversed(history)), "decode_rate", now=100, columns=61) == expected


def test_expired_gap_stops_hiding_valid_points_in_oldest_partial_bucket():
    history = (HistoryPoint(40.05, None), point(40.5, 7), point(99.5, 2))
    first = bucket_history(history, "decode_rate", now=100.0, columns=61)
    later = bucket_history(history, "decode_rate", now=100.1, columns=61)
    assert first[0] is None and later[0] == 7
    assert first[1:] == later[1:]


def test_resize_rebins_existing_points_without_mutating_history():
    history = (point(40, 1), point(70, 4), point(100, 9))
    before = deepcopy(history)
    narrow = bucket_history(history, "decode_rate", now=100, columns=61)
    wide = bucket_history(history, "decode_rate", now=100, columns=121)
    assert [(i, v) for i, v in enumerate(narrow) if v is not None] == [(0, 1), (30, 4), (60, 9)]
    assert [(i, v) for i, v in enumerate(wide) if v is not None] == [(0, 1), (60, 4), (120, 9)]
    assert bucket_history(history, "decode_rate", now=100, columns=61) == narrow
    assert history == before


@pytest.mark.parametrize("now", (-1, math.nan, math.inf, -math.inf, True, "100", None))
def test_bucket_rejects_invalid_clock(now):
    with pytest.raises(ValueError):
        bucket_history((), "decode_rate", now=now, columns=61)


@pytest.mark.parametrize("columns", (0, 1, -1, 2.0, True, "61", None))
def test_bucket_rejects_invalid_columns(columns):
    with pytest.raises(ValueError):
        bucket_history((), "decode_rate", now=100, columns=columns)


def test_scale_value_is_frozen_and_preserves_arbitrary_precision_integer():
    scale = HistoryScale("chat", "decode_rate", 2 * 10**300)
    assert type(scale.upper) is int
    assert scale.upper == 2 * 10**300
    for field, value in (("model_id", "other"), ("field", "rate"), ("upper", 1)):
        with pytest.raises(FrozenInstanceError):
            setattr(scale, field, value)


@pytest.mark.parametrize("value,upper", (
    (0, 1), (0.01, 1), (1, 1), (1.01, 2), (2, 2), (2.01, 5),
    (5, 5), (5.01, 10), (23, 50), (121, 200), (10**300, 10**300),
), ids=("zero", "fraction", "one", "above-one", "two", "above-two", "five",
        "above-five", "23-to-50", "121-to-200", "huge-exact-integer"))
def test_first_valid_history_uses_smallest_covering_decimal_tier(value, upper):
    tracker = HistoryScaleTracker((model(),))
    assert one_scale(tracker, snapshot((point(100, value),)), 100).upper == upper


def test_scale_for_huge_finite_float_is_integer_finite_and_covers_exact_input():
    tracker = HistoryScaleTracker((model(),))
    value = 1e300
    upper = one_scale(tracker, snapshot((point(100, value),)), 100).upper
    assert type(upper) is int and upper >= value
    # The binary float is slightly larger than the exact decimal 10**300.
    assert upper == 2 * 10**300


def test_largest_finite_float_uses_arbitrary_precision_covering_scale():
    tracker = HistoryScaleTracker((model(),))
    value = sys.float_info.max
    upper = one_scale(tracker, snapshot((point(100, value),)), 100).upper
    assert type(upper) is int
    assert upper == 2 * 10**308 and upper >= value


def test_smallest_positive_float_remains_nonzero_and_uses_unit_scale():
    value = math.nextafter(0.0, 1.0)
    history = (point(100, value),)
    buckets = bucket_history(history, "decode_rate", now=100, columns=61)
    assert buckets[-1] == value and buckets[-1] > 0
    assert buckets[:-1] == (None,) * 60
    tracker = HistoryScaleTracker((model(),))
    assert one_scale(tracker, snapshot(history), 100).upper == 1


def test_empty_then_first_valid_history_adopts_scale_without_delaying():
    tracker = HistoryScaleTracker((model(),))
    assert one_scale(tracker, snapshot(), 99).upper == 1
    assert one_scale(tracker, snapshot((point(100, 121),)), 100).upper == 200


def test_new_peak_increases_immediately_and_old_returned_scale_stays_frozen():
    tracker = HistoryScaleTracker((model(),))
    original = one_scale(tracker, snapshot((point(100, 23),)), 100)
    raised = one_scale(tracker, snapshot((point(100, 23), point(101, 121))), 101)
    assert original == HistoryScale("chat", "decode_rate", 50)
    assert raised == HistoryScale("chat", "decode_rate", 200)


def test_latest_low_value_cannot_lower_scale_while_old_peak_remains_visible():
    tracker = HistoryScaleTracker((model(),))
    assert one_scale(tracker, snapshot((point(0, 121),)), 0).upper == 200
    data = snapshot((point(0, 121), point(1, 23)))
    assert one_scale(tracker, data, 6).upper == 200
    assert one_scale(tracker, data, 60).upper == 200


def test_five_second_lowering_starts_when_visible_peak_falls_not_from_frame_count():
    tracker = HistoryScaleTracker((model(),))
    one_scale(tracker, snapshot((point(0, 121),)), 0)
    low = snapshot((point(61, 23),))
    for now in (61, 61, 61 + 1 / 30, 62, 65.9, 66 - 1e-9):
        assert one_scale(tracker, low, now).upper == 200
    assert one_scale(tracker, low, 66).upper == 50
    assert one_scale(tracker, low, 66).upper == 50


def test_lower_targets_can_change_without_restarting_five_second_timer():
    tracker = HistoryScaleTracker((model(),))
    one_scale(tracker, snapshot((point(0, 121),)), 0)
    low = (point(60.5, 3), point(61, 23))
    assert one_scale(tracker, snapshot(low), 61).upper == 200
    # A later failure in the same bucket hides 23, leaving the valid value 3.
    lower = (*low, HistoryPoint(61.1, None), point(62, 3))
    assert one_scale(tracker, snapshot(lower), 62).upper == 200
    raised_but_still_low = (*lower, point(64, 8))
    assert one_scale(tracker, snapshot(raised_but_still_low), 64).upper == 200
    assert one_scale(tracker, snapshot(raised_but_still_low), 66).upper == 10


@pytest.mark.parametrize("reset_value,reset_upper", ((121, 200), (900, 1000)))
def test_equal_or_higher_target_clears_pending_lowering(reset_value, reset_upper):
    tracker = HistoryScaleTracker((model(),))
    one_scale(tracker, snapshot((point(0, 121),)), 0)
    assert one_scale(tracker, snapshot((point(61, 23),)), 61).upper == 200
    assert one_scale(tracker, snapshot((point(61, 23), point(64, reset_value))), 64).upper == reset_upper
    low = snapshot((point(125, 23),))
    assert one_scale(tracker, low, 125).upper == reset_upper
    assert one_scale(tracker, low, 129.999).upper == reset_upper
    assert one_scale(tracker, low, 130).upper == 50


def test_unknown_buckets_clear_pending_lowering_without_turning_into_zero():
    tracker = HistoryScaleTracker((model(),))
    one_scale(tracker, snapshot((point(0, 121),)), 0)
    low = (point(61, 23),)
    assert one_scale(tracker, snapshot(low), 61).upper == 200
    unknown = (*low, HistoryPoint(61.1, None))
    assert one_scale(tracker, snapshot(unknown), 63).upper == 200
    recovered = snapshot((*unknown, point(64, 23)))
    assert one_scale(tracker, recovered, 64).upper == 200
    assert one_scale(tracker, recovered, 68.999).upper == 200
    assert one_scale(tracker, recovered, 69).upper == 50


@pytest.mark.parametrize("history,expected", (((point(61, 0),), 1), ((), 200)))
def test_observed_zero_can_lower_scale_but_empty_history_cannot(history, expected):
    tracker = HistoryScaleTracker((model(),))
    one_scale(tracker, snapshot((point(0, 121),)), 0)
    assert one_scale(tracker, snapshot(history), 61).upper == 200
    assert one_scale(tracker, snapshot(history), 66).upper == expected


def test_gap_hidden_spike_and_latest_metric_do_not_influence_display_scale():
    tracker = HistoryScaleTracker((model(),))
    history = (point(70.1, 1e300), HistoryPoint(70.2, None), point(100, 23))
    assert one_scale(tracker, snapshot(history, latest=1e300, stale=True), 100).upper == 50


def test_every_configured_model_updates_independently_in_configuration_order():
    models = (model("pool", ModelType.EMBEDDING), model(), model("rank", ModelType.RERANKER))
    tracker = HistoryScaleTracker(models)
    objects = (
        ObjectSnapshot(ObjectKey("vllm", "rank"), history=(point(100, 0.1, "rate"),)),
        ObjectSnapshot(ObjectKey("vllm", "chat"), history=(point(100, 121),)),
        ObjectSnapshot(ObjectKey("vllm", "pool"), history=(HistoryPoint(100, (
            Metric("rate", 3, "seq/s"), Metric("queue_seconds", 1e300, "s"),
        )),)),
        ObjectSnapshot(ObjectKey("gpu", "chat"), history=(point(100, 1e300),)),
        ObjectSnapshot(ObjectKey("vllm", "unconfigured"), history=(point(100, 1e300),)),
    )
    data = StateSnapshot(objects, 44)
    before = deepcopy((models, data))
    expected = (HistoryScale("pool", "rate", 5), HistoryScale("chat", "decode_rate", 200),
                HistoryScale("rank", "rate", 1))
    assert tracker.update(data, now=100, columns=61) == expected
    assert tracker.update(data, now=100, columns=61) == expected
    missing = StateSnapshot((ObjectSnapshot(ObjectKey("vllm", "pool"), history=(point(101, 8, "rate"),)),))
    assert tracker.update(missing, now=101, columns=61) == (
        HistoryScale("pool", "rate", 10), expected[1], expected[2])
    assert (models, data) == before


def test_one_models_rising_target_does_not_reset_another_models_lowering_timer():
    models = (model(), model("pool", ModelType.EMBEDDING))
    tracker = HistoryScaleTracker(models)

    def two_histories(chat, pool):
        return StateSnapshot((ObjectSnapshot(ObjectKey("vllm", "chat"), history=chat),
                              ObjectSnapshot(ObjectKey("vllm", "pool"), history=pool)))

    tracker.update(two_histories((point(0, 121),), (point(0, 3, "rate"),)), now=0, columns=61)
    low_chat, low_pool = (point(61, 23),), (point(61, 1, "rate"),)
    assert tracker.update(two_histories(low_chat, low_pool), now=61, columns=61) == (
        HistoryScale("chat", "decode_rate", 200), HistoryScale("pool", "rate", 5))
    pool_rises = (*low_pool, point(64, 8, "rate"))
    assert tracker.update(two_histories(low_chat, pool_rises), now=64, columns=61) == (
        HistoryScale("chat", "decode_rate", 200), HistoryScale("pool", "rate", 10))
    assert tracker.update(two_histories(low_chat, pool_rises), now=66, columns=61) == (
        HistoryScale("chat", "decode_rate", 50), HistoryScale("pool", "rate", 10))


def test_pending_lowering_survives_width_changes_without_rebuilding_session():
    tracker = HistoryScaleTracker((model(),))
    one_scale(tracker, snapshot((point(0, 121),)), 0)
    low = snapshot((point(61, 23),))
    assert one_scale(tracker, low, 61, 61).upper == 200
    assert one_scale(tracker, low, 63, 121).upper == 200
    assert one_scale(tracker, low, 65, 76).upper == 200
    assert one_scale(tracker, low, 66, 61).upper == 50


def test_separate_tracker_instances_do_not_share_scale_or_countdown():
    first, second = HistoryScaleTracker((model(),)), HistoryScaleTracker((model(),))
    one_scale(first, snapshot((point(0, 121),)), 0)
    low = snapshot((point(61, 23),))
    assert one_scale(first, low, 61).upper == 200
    assert one_scale(second, low, 61).upper == 50
    assert one_scale(first, low, 65).upper == 200


@pytest.mark.parametrize("invalid", (
    {"now": -1, "columns": 61}, {"now": math.nan, "columns": 61},
    {"now": math.inf, "columns": 61}, {"now": True, "columns": 61},
    {"now": "100", "columns": 61}, {"now": 100, "columns": 1},
    {"now": 100, "columns": True}, {"now": 100, "columns": 2.0},
    {"now": 100, "columns": "61"},
))
def test_tracker_rejects_invalid_parameters_even_for_empty_configuration(invalid):
    tracker = HistoryScaleTracker(())
    with pytest.raises(ValueError):
        tracker.update(StateSnapshot(()), **invalid)
    assert tracker.update(StateSnapshot(()), now=0, columns=2) == ()


@pytest.mark.parametrize("invalid", (
    {"now": 60, "columns": 61}, {"now": 66, "columns": 1},
    {"now": math.nan, "columns": 61},
), ids=("time-reversal", "invalid-width-at-deadline", "invalid-clock"))
def test_invalid_update_is_atomic_and_does_not_advance_or_reset_lowering(invalid):
    tracker = HistoryScaleTracker((model(),))
    one_scale(tracker, snapshot((point(0, 121),)), 0)
    low = snapshot((point(61, 23),))
    assert one_scale(tracker, low, 61).upper == 200
    # An invalid update also contains a peak which must never alter the state.
    with pytest.raises(ValueError):
        tracker.update(snapshot((point(61, 900),)), **invalid)
    assert one_scale(tracker, low, 65.9).upper == 200
    assert one_scale(tracker, low, 66).upper == 50


def test_empty_configuration_has_no_scales_but_enforces_monotonic_updates():
    tracker = HistoryScaleTracker(())
    assert tracker.update(snapshot((point(100, 1e300),)), now=100, columns=61) == ()
    assert tracker.update(StateSnapshot(()), now=100, columns=61) == ()
    with pytest.raises(ValueError):
        tracker.update(StateSnapshot(()), now=99, columns=61)


def test_history_and_scale_operations_do_not_access_files_processes_or_async_tasks(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("History presentation must remain local and free of IO")

    data, models = snapshot((point(100, 23),)), (model(),)
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(Path, "open", forbidden)
        patch.setattr(subprocess, "Popen", forbidden)
        patch.setattr(asyncio, "create_task", forbidden)
        tracker = HistoryScaleTracker(models)
        assert bucket_history(data.objects[0].history, "decode_rate", now=100, columns=61)[-1] == 23
        assert tracker.update(data, now=100, columns=61) == (HistoryScale("chat", "decode_rate", 50),)
