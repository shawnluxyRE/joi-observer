"""Offline public-wire contracts: fixtures are independent of codec internals."""

import copy
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import struct
import sys

import pytest

from joi_observer.config import AppConfig, ContainerConfig, LogConfig, ModelConfig, ModelType
from joi_observer.data.models import HistoryPoint, Metric, ObjectKey, ObjectSnapshot, StateSnapshot
from joi_observer.ipc.protocol import (
    FRAME_HEADER_BYTES, ContainerDisplay, DisplayMetadata, ModelDisplay, ProtocolError,
    SnapshotEnvelope, build_metadata, decode_envelope, encode_envelope,
)


def wire(payload):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return struct.pack(">Q", len(body)) + body


def payload():
    return {
        "protocol_version": 1, "instance_id": "instance-a", "config_revision": "config-a",
        "sequence": 1, "published_at": 60.0,
        "metadata": {"hostname": "host-label", "system": "Ubuntu 24.04",
                     "mount_points": [], "containers": [{"id": "worker"}],
                     "models": [{"id": "chat", "type": "chat", "name": "列表名称",
                                 "served_model_name": "served/title", "gpu_ids": ["GPU-a"],
                                 "explicit_port": None, "effective_port": 443}]},
        "snapshot": {"revision": 7, "objects": [
            {"key": {"collector": "docker", "object_id": "worker"},
             "metrics": [{"name": "state", "value": "Exited", "unit": "", "applicable": True}],
             "stale": False, "sampled_at": 60.0, "history": []},
            {"key": {"collector": "vllm", "object_id": "chat"},
             "metrics": [{"name": "running", "value": {"integer": "0"}, "unit": "seq", "applicable": True},
                         {"name": "total", "value": {"integer": "9007199254740993"}, "unit": "seq", "applicable": True},
                         {"name": "rate", "value": None, "unit": "seq/s", "applicable": False}],
             "stale": True, "sampled_at": 60.0,
             "history": [{"sampled_at": 0.0, "metrics": None},
                         {"sampled_at": 60.0, "metrics": None}]},
        ]},
    }


def envelope():
    return SnapshotEnvelope(
        "instance-a", "config-a", 1, 60.0,
        DisplayMetadata("host-label", "Ubuntu 24.04", containers=(ContainerDisplay("worker"),),
                        models=(ModelDisplay("chat", ModelType.CHAT, "列表名称", "served/title",
                                             ("GPU-a",), None, 443),)),
        StateSnapshot((
            ObjectSnapshot(ObjectKey("docker", "worker"), (Metric("state", "Exited"),), False, 60.0),
            ObjectSnapshot(ObjectKey("vllm", "chat"),
                           (Metric("running", 0, "seq"), Metric("total", 9007199254740993, "seq"),
                            Metric("rate", None, "seq/s", False)), True, 60.0,
                           (HistoryPoint(0.0, None), HistoryPoint(60.0, None))),
        ), 7),
    )


def test_encode_matches_independent_whitelist_without_losing_values():
    original = envelope()
    before = copy.deepcopy(original)
    result = encode_envelope(original)
    assert struct.unpack(">Q", result[:FRAME_HEADER_BYTES])[0] == len(result) - FRAME_HEADER_BYTES
    assert json.loads(result[FRAME_HEADER_BYTES:]) == payload()
    assert original == before


def test_decode_preserves_units_unknown_zero_na_stale_gaps_and_large_integer():
    actual = decode_envelope(wire(payload()))
    assert actual == envelope()
    assert actual.snapshot.objects[1].metrics[1].value == 9007199254740993
    assert isinstance(actual.metadata.models, tuple)
    assert isinstance(actual.snapshot.objects[1].history, tuple)
    with pytest.raises(FrozenInstanceError):
        actual.metadata.models[0].name = "changed"


@pytest.mark.parametrize("port_url,explicit,effective", [
    ("http://example.invalid", None, 80),
    ("https://example.invalid", None, 443),
    ("https://example.invalid:8123", 8123, 8123),
])
def test_metadata_projects_all_ordered_identity_fields_without_source_secrets(port_url, explicit, effective):
    config = AppConfig(
        mount_points=("/", "/data"), containers=(ContainerConfig("visible-id", "private-target"),),
        models=(ModelConfig("second", ModelType.CHAT, "same", port_url, ("GPU-b",), "served-b"),
                ModelConfig("first", ModelType.EMBEDDING, "same", port_url, ("0",))),
        logging=LogConfig(directory=Path("/private/logs")),
    )
    result = build_metadata(config, hostname="host-label", system="Ubuntu 24.04")
    assert result == DisplayMetadata(
        "host-label", "Ubuntu 24.04", ("/", "/data"), (ContainerDisplay("visible-id"),),
        (ModelDisplay("second", ModelType.CHAT, "same", "served-b", ("GPU-b",), explicit, effective),
         ModelDisplay("first", ModelType.EMBEDDING, "same", "same", ("0",), explicit, effective)),
    )
    assert all(secret not in repr(result) for secret in ("private-target", "example.invalid", "/private/logs"))
    assert not hasattr(result, "sample_interval")
    assert not hasattr(result.models[0], "base_url")


def test_empty_configuration_has_complete_empty_metadata():
    result = build_metadata(AppConfig(mount_points=()), hostname="host", system="Ubuntu 24.04")
    assert result == DisplayMetadata("host", "Ubuntu 24.04")


@pytest.mark.parametrize("frame", [
    b"", b"\x00\x00", struct.pack(">Q", 0),
    struct.pack(">Q", 2**64 - 1),
    struct.pack(">Q", 2) + b"{", struct.pack(">Q", 1) + b"{}",
    struct.pack(">Q", 1) + b"\xff", struct.pack(">Q", 1) + b"{",
    struct.pack(">Q", 1) + b"[",
    pytest.param(struct.pack(">Q", 4000) + b"{" * 2000 + b"}" * 2000, id="deeply-nested"),
])
def test_invalid_complete_frame_is_a_safe_protocol_error(frame):
    with pytest.raises(ProtocolError) as error:
        decode_envelope(frame)
    assert str(error.value) == "Invalid snapshot protocol data."


@pytest.mark.parametrize("path,value", [
    (("protocol_version",), 2), (("sequence",), 0), (("sequence",), True),
    (("published_at",), float("nan")), (("published_at",), -1),
    (("snapshot", "revision"), True), (("metadata", "models", 0, "type"), "unknown"),
    (("metadata", "models", 0, "id"), "other"),
    (("metadata", "models", 0, "served_model_name"), ""),
    (("metadata", "models", 0, "explicit_port"), 65536),
    (("snapshot", "objects", 1, "stale"), 1),
    (("snapshot", "objects", 1, "metrics", 0, "name"), "raw_response"),
    (("snapshot", "objects", 1, "metrics", 0, "value"), True),
    (("snapshot", "objects", 1, "metrics", 0, "value"), float("inf")),
    (("snapshot", "objects", 1, "metrics", 2, "value"), {"integer": "0"}),
    (("snapshot", "objects", 1, "history", 0, "sampled_at"), -0.1),
    (("snapshot", "objects", 1, "history", 1, "sampled_at"), 60.1),
])
def test_malformed_nested_fields_are_rejected(path, value):
    data = payload()
    target = data
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ProtocolError):
        decode_envelope(wire(data))


@pytest.mark.parametrize("path", [(), ("metadata",), ("metadata", "models", 0),
                                  ("snapshot",), ("snapshot", "objects", 1),
                                  ("snapshot", "objects", 1, "metrics", 0)])
def test_unrecognized_fields_cannot_smuggle_raw_errors_or_config(path):
    data = payload()
    target = data
    for part in path:
        target = target[part]
    target["raw_error"] = "secret-token-do-not-echo"
    with pytest.raises(ProtocolError) as caught:
        decode_envelope(wire(data))
    assert "secret-token" not in str(caught.value)


@pytest.mark.parametrize("path", [("metadata", "models"), ("snapshot", "objects"),
                                  ("snapshot", "objects", 1, "metrics")])
def test_duplicate_identities_and_fields_are_not_silently_collapsed(path):
    data = payload()
    target = data
    for part in path:
        target = target[part]
    target.append(copy.deepcopy(target[0]))
    with pytest.raises(ProtocolError):
        decode_envelope(wire(data))


def test_duplicate_json_keys_rejected_before_object_construction():
    body = json.dumps(payload()).replace('"sequence": 1', '"sequence": 1, "sequence": 2').encode()
    with pytest.raises(ProtocolError):
        decode_envelope(struct.pack(">Q", len(body)) + body)


def test_history_point_limit_is_independent_of_frame_size():
    data = payload()
    data["snapshot"]["objects"][1]["history"] = [
        {"sampled_at": i / 20, "metrics": None} for i in range(603)
    ]
    with pytest.raises(ProtocolError):
        decode_envelope(wire(data))


@pytest.mark.parametrize("value", [0, 42, {"integer": ""}, {"integer": "+1"},
                                  {"integer": "01"}, {"integer": "-0"},
                                  {"integer": "1.0"}, {"integer": "１"},
                                  {"integer": " 1"}, {"integer": 1},
                                  {"integer": "1", "other": "secret"}])
def test_integer_value_requires_one_canonical_decimal_tag(value):
    data = payload()
    data["snapshot"]["objects"][1]["metrics"][0]["value"] = value
    with pytest.raises(ProtocolError):
        decode_envelope(wire(data))


@pytest.mark.parametrize("exponent", [5000, 10000])
def test_existing_extreme_integer_values_roundtrip_without_global_limit_change(exponent):
    number = 10**exponent
    original = envelope()
    item = original.snapshot.objects[1]
    item = replace(item, metrics=(Metric("running", number, "seq"),))
    original = replace(original, snapshot=replace(original.snapshot, objects=(
        original.snapshot.objects[0], item)))
    before = sys.get_int_max_str_digits()
    frame = encode_envelope(original)
    assert sys.get_int_max_str_digits() == before
    encoded = json.loads(frame[FRAME_HEADER_BYTES:])
    assert encoded["snapshot"]["objects"][1]["metrics"][0]["value"] == {
        "integer": "1" + "0" * exponent}
    decoded = decode_envelope(frame)
    assert decoded == original
    assert decoded.snapshot.objects[1].metrics[0].value == number
    assert sys.get_int_max_str_digits() == before


def large_snapshot_fixture(model_count=256):
    """Independent legal one-second samples; size comes from object count."""
    metrics = (
        Metric("running", 0, "seq"), Metric("waiting", 0, "seq"), Metric("total", 0, "seq"),
        Metric("decode_rate", 1.25, "tok/s"), Metric("prefill_rate", 2.5, "tok/s"),
        Metric("rate", None, "seq/s", False), Metric("ttft_seconds", 0.1, "s"),
        Metric("queue_seconds", 0.2, "s"), Metric("latency_seconds", None, "s", False),
        Metric("kv_cache_percent", 50.0, "%"),
    )
    wire_metrics = [
        {"name": metric.name,
         "value": {"integer": "0"} if type(metric.value) is int else metric.value,
         "unit": metric.unit, "applicable": metric.applicable}
        for metric in metrics
    ]
    models, wire_models, objects, wire_objects = [], [], [], []
    for index in range(model_count):
        identifier = f"model-{index}"
        models.append(ModelDisplay(identifier, ModelType.CHAT, "Model", "served/model"))
        wire_models.append({"id": identifier, "type": "chat", "name": "Model",
                            "served_model_name": "served/model", "gpu_ids": [],
                            "explicit_port": None, "effective_port": 80})
        objects.append(ObjectSnapshot(ObjectKey("vllm", identifier), metrics, False, 60.0,
                                      tuple(HistoryPoint(float(second), metrics)
                                            for second in range(61))))
        wire_objects.append({"key": {"collector": "vllm", "object_id": identifier},
                             "metrics": wire_metrics, "stale": False, "sampled_at": 60.0,
                             "history": [{"sampled_at": float(second), "metrics": wire_metrics}
                                         for second in range(61)]})
    expected = SnapshotEnvelope("large-instance", "large-config", 1, 60.0,
                                DisplayMetadata("Host", "Ubuntu 24.04", models=tuple(models)),
                                StateSnapshot(tuple(objects), 1))
    data = {"protocol_version": 1, "instance_id": "large-instance", "config_revision": "large-config",
            "sequence": 1, "published_at": 60.0,
            "metadata": {"hostname": "Host", "system": "Ubuntu 24.04", "mount_points": [],
                         "containers": [], "models": wire_models},
            "snapshot": {"revision": 1, "objects": wire_objects}}
    return expected, data


def test_complete_snapshot_larger_than_old_limit_encodes_and_decodes_without_truncation():
    expected, data = large_snapshot_fixture()
    independent_frame = wire(data)
    assert len(independent_frame) - FRAME_HEADER_BYTES > 8 * 1024 * 1024
    assert decode_envelope(independent_frame) == expected
    encoded = encode_envelope(expected)
    assert json.loads(encoded[FRAME_HEADER_BYTES:]) == data
