"""Public engine payload families: shared load, disjoint type-specific fields."""

from dataclasses import FrozenInstanceError, replace

import pytest

from joi_observer.data.vllm import (EngineSample, ChatEngineSample, PoolingEngineSample,
                                  CounterSample, LatencySample)


QUEUE = LatencySample(2, 4, 10)


@pytest.mark.parametrize("cls", [EngineSample, ChatEngineSample, PoolingEngineSample])
def test_common_load_fields_are_shared_without_type_specific_data(cls):
    sample = cls("engine-1", running=3, waiting=7, queue=QUEUE)
    assert isinstance(sample, EngineSample)
    assert (sample.engine_id, sample.running, sample.waiting, sample.queue) == ("engine-1", 3, 7, QUEUE)


def test_chat_payload_has_no_pooling_members():
    sample = ChatEngineSample("0", kv_cache_fraction=0.25, prompt_tokens=CounterSample(1000),
                              generation_tokens=CounterSample(200), ttft=LatencySample(4, 2))
    assert sample.generation_tokens.value == 200 and sample.ttft.observations == 2
    assert not hasattr(sample, "completed_sequences") and not hasattr(sample, "latency")


def test_pooling_payload_has_no_chat_members():
    sample = PoolingEngineSample("0", completed_sequences=CounterSample(6), latency=LatencySample(9, 3))
    assert sample.completed_sequences.value == 6 and sample.latency.total_seconds == 9
    assert all(not hasattr(sample, name) for name in
               ("kv_cache_fraction", "prompt_tokens", "generation_tokens", "ttft"))


@pytest.mark.parametrize("cls,foreign", [
    (EngineSample, {"generation_tokens": CounterSample(1)}),
    (EngineSample, {"completed_sequences": CounterSample(1)}),
    (ChatEngineSample, {"completed_sequences": CounterSample(1)}),
    (ChatEngineSample, {"latency": LatencySample(1, 1)}),
    (PoolingEngineSample, {"kv_cache_fraction": 0.5}),
    (PoolingEngineSample, {"prompt_tokens": CounterSample(1)}),
    (PoolingEngineSample, {"generation_tokens": CounterSample(1)}),
    (PoolingEngineSample, {"ttft": LatencySample(1, 1)}),
])
def test_inapplicable_payload_cannot_be_supplied_to_constructor(cls, foreign):
    with pytest.raises(TypeError):
        cls("0", **foreign)


@pytest.mark.parametrize("sample,field", [
    (ChatEngineSample("0", generation_tokens=CounterSample(1)), "generation_tokens"),
    (PoolingEngineSample("0", completed_sequences=CounterSample(1)), "completed_sequences"),
])
def test_partial_payload_remains_frozen_and_keeps_its_concrete_family(sample, field):
    with pytest.raises(FrozenInstanceError):
        sample.running = 1
    partial = replace(sample, **{field: None})
    assert type(partial) is type(sample)
    assert getattr(partial, field) is None and getattr(sample, field) == CounterSample(1)
