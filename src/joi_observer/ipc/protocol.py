"""Frozen presentation payloads and the local stream's versioned wire contract.

Only the explicit fields below and the public StateSnapshot tree cross this
boundary. Configuration, collection results, exceptions and accumulator state
are never serialized.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
import struct
from urllib.parse import urlsplit

from joi_observer.config import AppConfig, ModelType
from joi_observer.data.models import HistoryPoint, Metric, ObjectKey, ObjectSnapshot, StateSnapshot


PROTOCOL_VERSION = 1
FRAME_HEADER_BYTES = 8
IO_CHUNK_BYTES = 64 * 1024
HEARTBEAT_INTERVAL = 1.0
FRAME_TIMEOUT = 5.0


class ProtocolError(ValueError):
    """Invalid or incompatible data; its message must be fixed/safe.

    Do not include payload text, config values, raw exceptions or source errors.
    A receiver terminates this connection on any protocol error without retrying.
    """


@dataclass(frozen=True)
class ModelDisplay:
    """Ordered model identity and display fields, with no collection endpoint.

    id/type/name/gpu_ids retain their validated config meaning. served_model_name
    is the effective nonempty detail title (configured value, otherwise name).
    explicit_port is None when the source URL omitted a port; effective_port is
    the explicit value or 80/443 for HTTP/HTTPS. The list and detail preserve their
    distinct existing port presentation without exposing a URL to clients.
    """

    id: str
    type: ModelType
    name: str
    served_model_name: str
    gpu_ids: tuple[str, ...] = ()
    explicit_port: int | None = None
    effective_port: int = 80


@dataclass(frozen=True)
class ContainerDisplay:
    """Configured stable id, also the Docker display label; no daemon target."""

    id: str


@dataclass(frozen=True)
class DisplayMetadata:
    """The active service's immutable presentation metadata in config order.

    hostname/system are the host's existing presentation labels. mount_points
    contains only the selected (at most three) display paths. Models and
    containers retain every configured object, including hidden/failed ones.
    Empty tuples are valid. No sampling parameters, credentials, log path or
    Docker target name belong here. GPU discovery order remains in snapshot.
    """

    hostname: str
    system: str
    mount_points: tuple[str, ...] = ()
    containers: tuple[ContainerDisplay, ...] = ()
    models: tuple[ModelDisplay, ...] = ()


@dataclass(frozen=True)
class SnapshotEnvelope:
    """One indivisible full snapshot and its effective presentation metadata.

    instance_id and config_revision are opaque nonempty startup identifiers;
    both stay fixed for the connection and both change on service restart.
    sequence starts at one and increases on each publication, even without a
    state revision change; slow readers may skip sequences. published_at uses
    host monotonic seconds, as do all sample/history timestamps. Snapshot's
    own revision remains the state update counter and may be unchanged.

    The client validates this complete value before replacing its cached value.
    A changed instance/config id or metadata value on an open connection is
    fatal, not a signal to merge data or reconnect. published_at and state
    revision cannot decrease. Historical data is never appended client-side.
    """

    instance_id: str
    config_revision: str
    sequence: int
    published_at: float
    metadata: DisplayMetadata
    snapshot: StateSnapshot
    protocol_version: int = PROTOCOL_VERSION


def build_metadata(config: AppConfig, *, hostname: str, system: str) -> DisplayMetadata:
    """Project a validated startup config onto the explicit display whitelist.

    Preserve identities, full order, GPU associations and mount selection;
    resolve served_model_name fallback and port presentation once. Never mutate
    config, read files, probe endpoints or infer labels from successful samples.
    Same-name models with different ids remain separate even before any sample.
    """
    try:
        models = []
        for model in config.models:
            origin = urlsplit(model.base_url)
            port = origin.port
            models.append(ModelDisplay(
                model.id, model.type, model.name, model.served_model_name or model.name,
                model.gpu_ids, port, port or (443 if origin.scheme == "https" else 80),
            ))
        metadata = DisplayMetadata(
            hostname, system, config.mount_points,
            tuple(ContainerDisplay(item.id) for item in config.containers), tuple(models),
        )
        _validate_metadata(metadata)
        return metadata
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise ProtocolError(_INVALID) from None


def encode_envelope(envelope: SnapshotEnvelope) -> bytes:
    """Validate one full frame: 8-byte unsigned big-endian length + UTF-8 JSON.

    Length counts only the body; zero is invalid. The header's representable
    range is a wire-format bound, not a fixed business snapshot-size limit or
    a capacity promise. Complete snapshots larger than 8 MiB are valid. The
    transport writes the returned value in blocks at most IO_CHUNK_BYTES each;
    these blocks are not separate messages and do not split the history window.
    Emit only the documented nested whitelist; do not serialize arbitrary
    dataclass attributes with a general object serializer. Invalid values,
    unknown object/metric fields or an unrepresentable length raise ProtocolError.
    Finite numeric values, integer precision, None, N/A, stale and history gaps
    retain the StateSnapshot meaning. No I/O, sampling or source mutation.

    Every integer Metric.value, including zero, uses {"integer":"decimal"};
    float/string/None values retain their JSON types. Decimal text is canonical
    ASCII: optional minus, no leading zero or plus, and no negative zero. Use
    bounded digit-group conversion for very large integers, never a global
    sys.set_int_max_str_digits change. Header fields, sequence and revision
    remain ordinary JSON integers within their declared scalar domains.
    """
    try:
        _validate_envelope(envelope)
        payload = {
            "protocol_version": envelope.protocol_version,
            "instance_id": envelope.instance_id, "config_revision": envelope.config_revision,
            "sequence": envelope.sequence, "published_at": envelope.published_at,
            "metadata": _metadata_payload(envelope.metadata),
            "snapshot": {"revision": envelope.snapshot.revision,
                         "objects": [_object_payload(item) for item in envelope.snapshot.objects]},
        }
        body = _json_text(payload).encode("utf-8")
        return struct.pack(">Q", len(body)) + body
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError, struct.error):
        raise ProtocolError(_INVALID) from None


def decode_envelope(frame: bytes) -> SnapshotEnvelope:
    """Decode exactly one complete frame into a deeply immutable value.

    Reject zero or mismatched lengths, truncation, trailing bytes, invalid UTF-8,
    duplicate/unknown/missing JSON fields, unsupported versions, invalid types,
    bool-as-number, nonfinite values, duplicate ids/keys/metrics and inconsistent
    metadata identities. Validate chronological history within the inclusive
    last 60 seconds (at most 602 points/object); preserve missing points as None.
    Decode canonical Metric.value integer tags exactly, including values with
    10001 decimal digits; reject raw integer values, noncanonical decimal text,
    additional tag keys and any other object in that slot. Parse tag text using
    bounded digit groups without changing the interpreter's integer limit.
    No fixed complete-body size limit is imposed by this codec. Do not accept pickle,
    dynamic classes, commands, arbitrary config or raw errors. ProtocolError
    is the sole malformed-input exception and contains no received data.

    Stateless checks happen here. Sequence monotonicity and invariant service
    identifiers across frames are checked by the receiving client. This pure
    function neither reads a stream nor changes any cached snapshot.
    """
    try:
        if type(frame) is not bytes or len(frame) < FRAME_HEADER_BYTES:
            _invalid()
        length = struct.unpack(">Q", frame[:FRAME_HEADER_BYTES])[0]
        if not length or length != len(frame) - FRAME_HEADER_BYTES:
            _invalid()
        payload = json.loads(
            frame[FRAME_HEADER_BYTES:].decode("utf-8"),
            object_pairs_hook=_unique_fields, parse_constant=_invalid_constant,
            parse_int=_parse_json_integer,
        )
        result = _envelope_from_payload(payload)
        _validate_envelope(result)
        return result
    except (AttributeError, TypeError, ValueError, OverflowError, RecursionError, struct.error):
        raise ProtocolError(_INVALID) from None


_INVALID = "Invalid snapshot protocol data."
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_GPU_UUID = re.compile(r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
_DECIMAL = re.compile(r"(?:0|-[1-9][0-9]*|[1-9][0-9]*)\Z")
_DOCKER_STATES = frozenset(("Created", "Running", "Paused", "Restarting", "Removing", "Exited", "Dead"))
_METRICS = {
    "cpu": {"cpu_percent": "%"},
    "ram": {"ram_used_bytes": "B", "ram_total_bytes": "B", "ram_percent": "%"},
    "gpu_inventory": {"device_count": ""},
    "gpu": {"index": "", "name": "", "utilization_percent": "%", "memory_used_bytes": "B",
            "memory_total_bytes": "B", "temperature_c": "°C", "power_w": "W"},
    "storage": {"used_bytes": "B", "total_bytes": "B", "used_percent": "%"},
    "docker": {"state": ""},
    "vllm": {"running": "seq", "waiting": "seq", "total": "seq", "decode_rate": "tok/s",
             "prefill_rate": "tok/s", "rate": "seq/s", "ttft_seconds": "s", "queue_seconds": "s",
             "latency_seconds": "s", "kv_cache_percent": "%"},
}


def _invalid() -> None:
    raise ProtocolError(_INVALID)


def _invalid_constant(_value: str) -> None:
    _invalid()


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            _invalid()
        result[key] = value
    return result


def _fields(value: object, names: str) -> dict:
    if type(value) is not dict or value.keys() != set(names.split()):
        _invalid()
    return value


def _array(value: object) -> list:
    if type(value) is not list:
        _invalid()
    return value


def _text(value: object, *, empty: bool = False, maximum: int | None = None) -> None:
    if (type(value) is not str or (not empty and not value)
            or not value.isprintable() and value != "" or maximum is not None and len(value) > maximum):
        _invalid()


def _name(value: object) -> None:
    _text(value, maximum=128)
    if value != value.strip():
        _invalid()


def _identity(value: object) -> None:
    if type(value) is not str or not _ID.fullmatch(value):
        _invalid()


def _integer(value: object, minimum: int = 0, maximum: int | None = None) -> None:
    if type(value) is not int or value < minimum or maximum is not None and value > maximum:
        _invalid()


def _time(value: object) -> None:
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        _invalid()


def _tuple(value: object) -> None:
    if type(value) is not tuple:
        _invalid()


def _validate_metadata(metadata: DisplayMetadata) -> None:
    if type(metadata) is not DisplayMetadata:
        _invalid()
    _text(metadata.hostname)
    _text(metadata.system)
    _tuple(metadata.mount_points)
    _tuple(metadata.containers)
    _tuple(metadata.models)
    if len(metadata.mount_points) > 3:
        _invalid()
    for path in metadata.mount_points:
        _text(path)
        if not path.startswith("/") or path != path.strip() or ".." in path.split("/"):
            _invalid()
    if len(set(metadata.mount_points)) != len(metadata.mount_points):
        _invalid()
    container_ids, model_ids = set(), set()
    for container in metadata.containers:
        if type(container) is not ContainerDisplay:
            _invalid()
        _identity(container.id)
        if container.id in container_ids:
            _invalid()
        container_ids.add(container.id)
    for model in metadata.models:
        if type(model) is not ModelDisplay or type(model.type) is not ModelType:
            _invalid()
        _identity(model.id)
        _name(model.name)
        _name(model.served_model_name)
        _tuple(model.gpu_ids)
        for gpu_id in model.gpu_ids:
            _name(gpu_id)
            if any(char.isspace() for char in gpu_id):
                _invalid()
        if len(set(model.gpu_ids)) != len(model.gpu_ids) or model.id in model_ids:
            _invalid()
        model_ids.add(model.id)
        if model.explicit_port is not None:
            _integer(model.explicit_port, 1, 65535)
        _integer(model.effective_port, 1, 65535)
        if (model.explicit_port is not None and model.effective_port != model.explicit_port
                or model.explicit_port is None and model.effective_port not in (80, 443)):
            _invalid()


def _metric_group(key: ObjectKey) -> str:
    if type(key) is not ObjectKey:
        _invalid()
    _text(key.object_id, maximum=128)
    if key.collector == "host" and key.object_id in ("cpu", "ram"):
        return key.object_id
    if key.collector == "gpu_inventory" and key.object_id == "local":
        return key.collector
    if key.collector == "gpu" and _GPU_UUID.fullmatch(key.object_id):
        return key.collector
    if key.collector in ("storage", "docker", "vllm"):
        return key.collector
    _invalid()


def _validate_metrics(metrics: tuple[Metric, ...], group: str, model_type: ModelType | None) -> None:
    _tuple(metrics)
    seen = set()
    for metric in metrics:
        if type(metric) is not Metric or type(metric.name) is not str:
            _invalid()
        if metric.name not in _METRICS[group] or metric.name in seen:
            _invalid()
        seen.add(metric.name)
        if metric.unit != _METRICS[group][metric.name] or type(metric.applicable) is not bool:
            _invalid()
        applicable = True
        if group == "vllm":
            unavailable = (("rate", "latency_seconds") if model_type is ModelType.CHAT else
                           ("decode_rate", "prefill_rate", "ttft_seconds", "kv_cache_percent"))
            applicable = metric.name not in unavailable
        if metric.applicable is not applicable or not applicable and metric.value is not None:
            _invalid()
        value = metric.value
        if value is None:
            continue
        if group == "gpu" and metric.name == "name":
            _text(value)
        elif group == "docker":
            if type(value) is not str or value not in _DOCKER_STATES:
                _invalid()
        elif type(value) not in (int, float) or type(value) is float and not math.isfinite(value):
            _invalid()


def _validate_envelope(envelope: SnapshotEnvelope) -> None:
    if type(envelope) is not SnapshotEnvelope or type(envelope.snapshot) is not StateSnapshot:
        _invalid()
    _integer(envelope.protocol_version, PROTOCOL_VERSION, PROTOCOL_VERSION)
    _text(envelope.instance_id)
    _text(envelope.config_revision)
    _integer(envelope.sequence, 1)
    _time(envelope.published_at)
    _integer(envelope.snapshot.revision)
    _validate_metadata(envelope.metadata)
    _tuple(envelope.snapshot.objects)
    models = {model.id: model.type for model in envelope.metadata.models}
    expected = {
        "storage": tuple(f"mount-{index}" for index in range(len(envelope.metadata.mount_points))),
        "docker": tuple(item.id for item in envelope.metadata.containers),
        "vllm": tuple(models),
    }
    actual = {name: [] for name in expected}
    seen = set()
    for item in envelope.snapshot.objects:
        if type(item) is not ObjectSnapshot:
            _invalid()
        group = _metric_group(item.key)
        if item.key in seen or type(item.stale) is not bool:
            _invalid()
        seen.add(item.key)
        if group in expected:
            if item.key.object_id not in expected[group]:
                _invalid()
            actual[group].append(item.key.object_id)
        model_type = models.get(item.key.object_id) if group == "vllm" else None
        _validate_metrics(item.metrics, group, model_type)
        if item.sampled_at is not None:
            _time(item.sampled_at)
            if item.sampled_at > envelope.published_at:
                _invalid()
        _tuple(item.history)
        if len(item.history) > 602:
            _invalid()
        previous = None
        for point in item.history:
            if type(point) is not HistoryPoint:
                _invalid()
            _time(point.sampled_at)
            if (not envelope.published_at - 60 <= point.sampled_at <= envelope.published_at
                    or previous is not None and point.sampled_at <= previous):
                _invalid()
            previous = point.sampled_at
            if point.metrics is not None:
                _validate_metrics(point.metrics, group, model_type)
    if any(tuple(actual[group]) != ordered for group, ordered in expected.items()):
        _invalid()


def _decimal(value: int) -> str:
    """Convert integer digits in small groups without interpreter-global changes."""
    if value == 0:
        return "0"
    negative = value < 0
    value = abs(value)
    groups = []
    while value:
        value, remainder = divmod(value, 1_000_000_000)
        groups.append(remainder)
    return ("-" if negative else "") + str(groups[-1]) + "".join(
        f"{group:09d}" for group in reversed(groups[:-1]))


def _parse_decimal(value: str) -> int:
    if type(value) is not str or not _DECIMAL.fullmatch(value):
        _invalid()
    return _parse_json_integer(value)


def _parse_json_integer(value: str) -> int:
    # The JSON parser validates its own integer grammar. Canonical decimal-tag
    # validation above is deliberately separate (JSON itself permits -0).
    negative = value.startswith("-")
    digits = value[1:] if negative else value
    result = 0
    for offset in range(0, len(digits), 9):
        group = digits[offset:offset + 9]
        result = result * 10 ** len(group) + int(group)
    return -result if negative else result


def _json_text(value: object) -> str:
    """Serialize only our explicit primitive tree, including unbounded counters."""
    try:
        # Integer metric values are already decimal tags. The C encoder handles
        # ordinary publications efficiently; only unusually large structural
        # counters need the digit-group fallback below.
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except ValueError:
        return _json_tree_text(value)


def _json_tree_text(value: object) -> str:
    if type(value) is dict:
        return "{" + ",".join(json.dumps(key, ensure_ascii=False) + ":" + _json_tree_text(item)
                              for key, item in value.items()) + "}"
    if type(value) is list:
        return "[" + ",".join(_json_tree_text(item) for item in value) + "]"
    if type(value) is int:
        return _decimal(value)
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def _metadata_payload(metadata: DisplayMetadata) -> dict:
    return {
        "hostname": metadata.hostname, "system": metadata.system,
        "mount_points": list(metadata.mount_points),
        "containers": [{"id": item.id} for item in metadata.containers],
        "models": [{"id": item.id, "type": item.type.value, "name": item.name,
                    "served_model_name": item.served_model_name, "gpu_ids": list(item.gpu_ids),
                    "explicit_port": item.explicit_port, "effective_port": item.effective_port}
                   for item in metadata.models],
    }


def _metrics_payload(metrics: tuple[Metric, ...]) -> list:
    return [{"name": item.name,
             "value": {"integer": _decimal(item.value)} if type(item.value) is int else item.value,
             "unit": item.unit, "applicable": item.applicable} for item in metrics]


def _object_payload(item: ObjectSnapshot) -> dict:
    return {
        "key": {"collector": item.key.collector, "object_id": item.key.object_id},
        "metrics": _metrics_payload(item.metrics), "stale": item.stale,
        "sampled_at": item.sampled_at,
        "history": [{"sampled_at": point.sampled_at,
                     "metrics": None if point.metrics is None else _metrics_payload(point.metrics)}
                    for point in item.history],
    }


def _metadata_from_payload(value: object) -> DisplayMetadata:
    value = _fields(value, "hostname system mount_points containers models")
    containers = []
    for item in _array(value["containers"]):
        item = _fields(item, "id")
        containers.append(ContainerDisplay(item["id"]))
    models = []
    for item in _array(value["models"]):
        item = _fields(item, "id type name served_model_name gpu_ids explicit_port effective_port")
        models.append(ModelDisplay(
            item["id"], ModelType(item["type"]), item["name"], item["served_model_name"],
            tuple(_array(item["gpu_ids"])), item["explicit_port"], item["effective_port"],
        ))
    return DisplayMetadata(value["hostname"], value["system"], tuple(_array(value["mount_points"])),
                           tuple(containers), tuple(models))


def _metrics_from_payload(value: object) -> tuple[Metric, ...]:
    metrics = []
    for item in _array(value):
        item = _fields(item, "name value unit applicable")
        number = item["value"]
        if type(number) is int:
            _invalid()
        if type(number) is dict:
            number = _parse_decimal(_fields(number, "integer")["integer"])
        metrics.append(Metric(item["name"], number, item["unit"], item["applicable"]))
    return tuple(metrics)


def _object_from_payload(value: object) -> ObjectSnapshot:
    value = _fields(value, "key metrics stale sampled_at history")
    key = _fields(value["key"], "collector object_id")
    history = []
    for point in _array(value["history"]):
        point = _fields(point, "sampled_at metrics")
        history.append(HistoryPoint(point["sampled_at"], None if point["metrics"] is None else
                                    _metrics_from_payload(point["metrics"])))
    return ObjectSnapshot(ObjectKey(key["collector"], key["object_id"]),
                          _metrics_from_payload(value["metrics"]), value["stale"],
                          value["sampled_at"], tuple(history))


def _envelope_from_payload(value: object) -> SnapshotEnvelope:
    value = _fields(value, "protocol_version instance_id config_revision sequence published_at metadata snapshot")
    snapshot = _fields(value["snapshot"], "revision objects")
    return SnapshotEnvelope(
        value["instance_id"], value["config_revision"], value["sequence"], value["published_at"],
        _metadata_from_payload(value["metadata"]),
        StateSnapshot(tuple(_object_from_payload(item) for item in _array(snapshot["objects"])),
                      snapshot["revision"]), value["protocol_version"],
    )
