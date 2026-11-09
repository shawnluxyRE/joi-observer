"""Public window contracts; deterministic offline data, no vLLM/HTTP dependency."""

from dataclasses import FrozenInstanceError
import math

import pytest

from joi_observer.data.vllm_window import (
    EngineCounter,
    LatencyInterval,
    counter_rate,
    weighted_latency,
)


def counters(*values):
    return tuple(EngineCounter(str(index), value) for index, value in enumerate(values))


@pytest.mark.parametrize("before,after,expected", [(20, 220, 100), (500, 1500, 500), (3, 9, 3)])
def test_token_or_completed_sequence_delta_uses_actual_two_seconds(before, after, expected):
    assert counter_rate(counters(before), counters(after), elapsed=2) == expected


def test_no_completed_units_is_valid_zero():
    assert counter_rate(counters(99), counters(99), elapsed=1.7) == 0


def test_integer_counter_precision_is_kept_before_subtraction():
    assert counter_rate(counters(2**60), counters(2**60 + 6), elapsed=2) == 3


def test_unrepresentable_rate_is_rejected_instead_of_returning_infinity():
    with pytest.raises(ValueError):
        counter_rate(counters(0), counters(10**400), elapsed=1)


@pytest.mark.parametrize("previous,current,continuous", [
    (None, counters(100), True),
    ((), (), True),
    ((), counters(100), True),
    (counters(100), (), True),
    (counters(1), counters(10), False),
    (counters(100), counters(10), True),
    (counters(100, 10), counters(10, 1000), True),
    (counters(1), counters(2, 3), True),
    (counters(1, 2), counters(3), True),
    ((EngineCounter("old", 1),), (EngineCounter("new", 2),), True),
])
def test_unknown_discontinuous_reset_or_changed_engines_do_not_create_rate(previous, current, continuous):
    assert counter_rate(previous, current, elapsed=2, continuous=continuous) is None


def test_multi_engine_input_order_does_not_change_identity():
    before = (EngineCounter("a", 10), EngineCounter("b", 100))
    after = (EngineCounter("b", 104), EngineCounter("a", 12))
    assert counter_rate(before, after, elapsed=2) == 3


@pytest.mark.parametrize("elapsed", [0, -1, math.nan, math.inf, True, "2"])
def test_invalid_elapsed_is_rejected(elapsed):
    with pytest.raises(ValueError):
        counter_rate(counters(1), counters(2), elapsed=elapsed)


@pytest.mark.parametrize("invalid", [
    (EngineCounter("a", -1),),
    (EngineCounter("a", True),),
    (EngineCounter("a", 1.5),),
    (EngineCounter("a", math.inf),),
    (EngineCounter("", 1),),
    (EngineCounter("a\n", 1),),
    (EngineCounter("a", 1), EngineCounter("a", 2)),
    [EngineCounter("a", 1)],
    (None,),
])
@pytest.mark.parametrize("side", ["previous", "current"])
def test_all_counter_inputs_are_validated_even_without_a_comparable_interval(invalid, side):
    with pytest.raises(ValueError):
        counter_rate(invalid if side == "previous" else None,
                     invalid if side == "current" else counters(1), elapsed=2)


def test_continuity_flag_is_boolean():
    with pytest.raises(ValueError):
        counter_rate(counters(1), counters(2), elapsed=2, continuous=1)


def test_weighted_observations_are_not_an_average_of_per_interval_means():
    # Two observations totalling 4s, then one observation of 5s: 9 / 3 = 3s.
    intervals = (LatencyInterval(0, 2, 4, 2), LatencyInterval(2, 3, 5, 1))
    assert weighted_latency(intervals, now=3) == 3


def test_queue_latency_uses_its_own_observation_count():
    ttft = (LatencyInterval(0, 2, 4, 2), LatencyInterval(2, 3, 5, 1))
    queue = (LatencyInterval(0, 2, 1, 4), LatencyInterval(2, 3, 2, 2))
    assert weighted_latency(ttft, now=3) == 3
    assert weighted_latency(queue, now=3) == 0.5


def test_finite_weighted_result_survives_intermediate_sum_overflow():
    intervals = (LatencyInterval(0, 1, 1e308, 2), LatencyInterval(1, 2, 1e308, 2))
    assert weighted_latency(intervals, now=2) == pytest.approx(5e307)


@pytest.mark.parametrize("intervals", [(), (LatencyInterval(0, 2, 0, 0),)])
def test_no_latency_observations_is_unavailable(intervals):
    assert weighted_latency(intervals, now=2) is None


def test_observed_zero_latency_is_zero():
    assert weighted_latency((LatencyInterval(0, 2, 0, 3),), now=2) == 0


def test_window_keeps_only_complete_intervals_including_exact_boundary():
    intervals = (
        LatencyInterval(0, 2, 999, 1),     # straddles the left boundary at 1
        LatencyInterval(2, 4, 4, 2),
        LatencyInterval(59, 61, 5, 1),
        LatencyInterval(61, 63, 999, 1),   # not yet complete at now=61
    )
    assert weighted_latency(intervals, now=61) == 3
    exact = (LatencyInterval(1, 3, 6, 2),)
    assert weighted_latency(exact, now=61) == 3


def test_elapsed_window_expires_values_without_new_samples():
    samples = (LatencyInterval(0, 2, 6, 2),)
    assert weighted_latency(samples, now=2) == 3
    assert weighted_latency(samples, now=62.1) is None


def test_gaps_are_neither_zero_latency_nor_fabricated_observations():
    intervals = (LatencyInterval(0, 2, 4, 2), LatencyInterval(50, 52, 5, 1))
    assert weighted_latency(intervals, now=52) == 3


def test_configurable_window_and_arguments_remain_unchanged():
    intervals = (LatencyInterval(0, 2, 4, 2), LatencyInterval(4, 6, 5, 1))
    assert weighted_latency(intervals, now=6, window_seconds=2) == 5
    assert intervals == (LatencyInterval(0, 2, 4, 2), LatencyInterval(4, 6, 5, 1))


@pytest.mark.parametrize("intervals", [
    (LatencyInterval(2, 1, 1, 1),),
    (LatencyInterval(1, 1, 1, 1),),
    (LatencyInterval(-1, 1, 1, 1),),
    (LatencyInterval(0, math.inf, 1, 1),),
    (LatencyInterval(True, 2, 1, 1),),
    (LatencyInterval(0, 1, math.nan, 1),),
    (LatencyInterval(0, 1, -1, 1),),
    (LatencyInterval(0, 1, True, 1),),
    (LatencyInterval(0, 1, 1, -1),),
    (LatencyInterval(0, 1, 1, True),),
    (LatencyInterval(0, 1, 1, 1.5),),
    (LatencyInterval(0, 1, 1, 0),),
    (LatencyInterval(0, 2, 1, 1), LatencyInterval(1, 3, 1, 1)),
    (LatencyInterval(2, 3, 1, 1), LatencyInterval(0, 1, 1, 1)),
    [LatencyInterval(0, 1, 1, 1)],
    (None,),
])
def test_invalid_intervals_are_rejected_even_when_outside_window(intervals):
    with pytest.raises(ValueError):
        weighted_latency(intervals, now=1000)


@pytest.mark.parametrize("now,window", [(-1, 60), (math.inf, 60), (math.nan, 60),
                                         (True, 60), (1, 0), (1, -1), (1, math.inf),
                                         (1, math.nan), (1, True)])
def test_invalid_window_parameters_are_rejected(now, window):
    with pytest.raises(ValueError):
        weighted_latency((), now=now, window_seconds=window)


@pytest.mark.parametrize("record,attribute,value", [
    (EngineCounter("a", 1), "value", 2),
    (LatencyInterval(0, 1, 2, 1), "total_seconds", 3),
])
def test_observation_records_are_immutable(record, attribute, value):
    with pytest.raises(FrozenInstanceError):
        setattr(record, attribute, value)
