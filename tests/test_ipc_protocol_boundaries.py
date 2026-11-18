"""Additional protocol boundaries, independent of transport or worker choices."""

from dataclasses import replace
import copy
import json
import struct
import sys

import pytest

from joi_observer.data.models import HistoryPoint, Metric, ObjectKey, ObjectSnapshot, StateSnapshot
from joi_observer.ipc.protocol import ProtocolError, decode_envelope, encode_envelope
from test_ipc_protocol import envelope, payload, wire


@pytest.mark.parametrize("path", [
    (), ("metadata",), ("metadata", "models", 0), ("snapshot",),
    ("snapshot", "objects", 0), ("snapshot", "objects", 0, "key"),
    ("snapshot", "objects", 0, "metrics", 0),
    ("snapshot", "objects", 1, "history", 0),
])
def test_required_fields_are_not_inferred_from_other_layers(path):
    data = payload()
    value = data
    for part in path:
        value = value[part]
    value.pop(next(iter(value)))
    with pytest.raises(ProtocolError):
        decode_envelope(wire(data))


@pytest.mark.parametrize("change", [
    lambda data: data["snapshot"]["objects"].pop(),
    lambda data: data["metadata"]["containers"].clear(),
    lambda data: data["metadata"]["mount_points"].append("/unmatched"),
    lambda data: data["snapshot"]["objects"][0]["metrics"][0].update(value="private raw error"),
    lambda data: data["snapshot"]["objects"][1]["metrics"][0].update(unit="request/s"),
    lambda data: data["snapshot"]["objects"][1]["metrics"][2].update(applicable=True),
    lambda data: data["metadata"]["models"][0].update(effective_port=True),
    lambda data: data["snapshot"]["objects"][1].update(sampled_at=61.0),
    lambda data: data["snapshot"]["objects"][1]["history"].reverse(),
    lambda data: data["snapshot"]["objects"][1]["history"].append(
        copy.deepcopy(data["snapshot"]["objects"][1]["history"][-1])),
])
def test_inconsistent_identity_units_applicability_or_history_are_rejected(change):
    data = payload()
    change(data)
    with pytest.raises(ProtocolError):
        decode_envelope(wire(data))


def test_sixty_second_history_endpoints_are_inclusive_without_modifying_values():
    original = envelope()
    item = replace(original.snapshot.objects[1], sampled_at=160.0,
                   history=(HistoryPoint(100.0, None), HistoryPoint(160.0, None)))
    original = replace(original, published_at=160.0,
                       snapshot=replace(original.snapshot, objects=(original.snapshot.objects[0], item)))
    assert decode_envelope(encode_envelope(original)) == original
    expired = replace(item, history=(HistoryPoint(99.999999, None),))
    with pytest.raises(ProtocolError):
        encode_envelope(replace(original, snapshot=StateSnapshot((original.snapshot.objects[0], expired))))


@pytest.mark.parametrize("invalid", [
    replace(envelope(), published_at=float("inf")),
    replace(envelope(), sequence=True),
    replace(envelope(), protocol_version=2),
    replace(envelope(), snapshot=replace(envelope().snapshot, revision=-1)),
    replace(envelope(), metadata=replace(envelope().metadata, containers=[])),
    replace(envelope(), snapshot=replace(envelope().snapshot, objects=(
        ObjectSnapshot(ObjectKey("host", "cpu"), (Metric("raw_response", "secret"),)),
    ))),
])
def test_encoder_enforces_the_same_contract_as_received_frames(invalid):
    with pytest.raises(ProtocolError) as error:
        encode_envelope(invalid)
    assert "secret" not in str(error.value)


def test_extreme_structural_counters_remain_json_integers_without_global_changes():
    original = replace(envelope(), sequence=10**5000,
                       snapshot=replace(envelope().snapshot, revision=10**5000))
    before = sys.get_int_max_str_digits()
    frame = encode_envelope(original)
    assert b'"sequence":1' + b"0" * 5000 in frame
    assert decode_envelope(frame) == original
    assert sys.get_int_max_str_digits() == before


@pytest.mark.parametrize("field", ["hostname", "served_model_name", "collector", "unit", "integer"])
def test_duplicate_keys_are_rejected_at_nested_json_levels(field):
    # Build the duplicate as text: a dict fixture would erase it before the
    # decoder sees the wire and would not exercise its object-pairs hook.
    data = payload()
    body = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    marker = json.dumps(field) + ":"
    assert marker in body
    body = body.replace(marker, marker + '"private-duplicate-value",' + marker, 1).encode()
    with pytest.raises(ProtocolError) as error:
        decode_envelope(struct.pack(">Q", len(body)) + body)
    assert str(error.value) == "Invalid snapshot protocol data."


@pytest.mark.parametrize("path", [
    ("published_at",),
    ("snapshot", "objects", 1, "sampled_at"),
    ("snapshot", "objects", 1, "history", 0, "sampled_at"),
])
@pytest.mark.parametrize("invalid", [float("inf"), float("-inf"), True, 10**1000])
def test_all_time_domains_reject_nonfinite_or_inexact_numeric_types_safely(path, invalid):
    data = payload()
    target = data
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = invalid
    with pytest.raises(ProtocolError) as error:
        decode_envelope(wire(data))
    assert str(error.value) == "Invalid snapshot protocol data."


@pytest.mark.parametrize("invalid", [0, {"integer": "-0"}, {"integer": "01"}, {"integer": "+1"}])
def test_history_integer_values_obey_the_same_canonical_tag_contract(invalid):
    data = payload()
    data["snapshot"]["objects"][1]["history"] = [{
        "sampled_at": 60.0,
        "metrics": [{"name": "running", "value": invalid, "unit": "seq", "applicable": True}],
    }]
    with pytest.raises(ProtocolError):
        decode_envelope(wire(data))


def test_legal_dense_history_preserves_all_602_points_in_deeply_immutable_tuples():
    data = payload()
    data["snapshot"]["objects"][1]["history"] = [{
        "sampled_at": index * 60.0 / 601,
        "metrics": [{"name": "running", "value": {"integer": "7"}, "unit": "seq", "applicable": True}],
    } for index in range(602)]
    decoded = decode_envelope(wire(data))
    points = decoded.snapshot.objects[1].history
    assert type(points) is tuple and len(points) == 602
    assert points[0].sampled_at == 0.0 and points[-1].sampled_at == 60.0
    assert all(type(point.metrics) is tuple and point.metrics[0].value == 7 for point in points)
    assert decode_envelope(encode_envelope(decoded)) == decoded
