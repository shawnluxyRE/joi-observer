"""Pure parsing and controlled failures for local hardware collectors.

These helpers never read files, launch processes, write state, or expose raw
driver responses in failures.  IO ownership remains with each collector.
"""

from __future__ import annotations

import csv
import io
import math
import posixpath
import re

from joi_observer.data.models import Metric
from joi_observer.error_log import ErrorKind, Failure


PARSE = Failure(ErrorKind.PARSE, "response.invalid", "Invalid collection response.")
UNAVAILABLE = Failure(ErrorKind.UNAVAILABLE, "source.unavailable", "Data source is unavailable.")
NOT_FOUND = Failure(ErrorKind.NOT_FOUND, "object.not_found", "Configured object was not found.")
_UNSUPPORTED = frozenset(("N/A", "[N/A]", "[Not Supported]"))
_UUID = re.compile(r"GPU-[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\Z")
_ESCAPES = {"040": " ", "011": "\t", "012": "\n", "134": "\\"}


def io_failure(error: OSError, *, command: bool = False) -> Failure:
    """Normalize only expected OS errors; never include their original text."""
    if isinstance(error, TimeoutError):
        return Failure(ErrorKind.TIMEOUT, "collection.timeout", "Collection timed out.")
    if isinstance(error, PermissionError):
        return Failure(ErrorKind.PERMISSION, "access.denied", "Permission denied.")
    if isinstance(error, FileNotFoundError) and not command:
        return NOT_FOUND
    return UNAVAILABLE


def unsigned_integer(text: str) -> int:
    if re.fullmatch(r"[0-9]+", text) is None:
        raise ValueError("Invalid nonnegative integer.")
    return int(text)


def gpu_uuid(text: str) -> str:
    if _UUID.fullmatch(text) is None:
        raise ValueError("Invalid GPU UUID.")
    return text


def csv_rows(text: str, columns: int) -> list[list[str]]:
    if not text.strip():
        return []
    try:
        rows = [[cell.strip() for cell in row] for row in
                csv.reader(io.StringIO(text), skipinitialspace=True, strict=True)
                if row]
    except csv.Error:
        raise ValueError("Invalid CSV response.") from None
    if any(len(row) != columns for row in rows):
        raise ValueError("Invalid CSV column count.")
    return rows


def cpu_ticks(text: str) -> tuple[int, ...]:
    rows = [line.split() for line in text.splitlines() if line.split()[:1] == ["cpu"]]
    if len(rows) != 1 or len(rows[0]) < 9:
        raise ValueError("Invalid aggregate CPU counters.")
    return tuple(unsigned_integer(value) for value in rows[0][1:9])


def memory_metrics(text: str) -> tuple[Metric, ...]:
    values: dict[str, int] = {}
    for line in text.splitlines():
        key, separator, tail = line.partition(":")
        if key not in ("MemTotal", "MemAvailable"):
            continue
        fields = tail.split()
        if not separator or key in values or len(fields) != 2 or fields[1] != "kB":
            raise ValueError("Invalid memory counters.")
        values[key] = unsigned_integer(fields[0]) * 1024
    if set(values) != {"MemTotal", "MemAvailable"}:
        raise ValueError("Missing memory counters.")
    total, available = values["MemTotal"], values["MemAvailable"]
    if total <= 0 or available > total:
        raise ValueError("Invalid memory capacity.")
    used = total - available
    return (Metric("ram_used_bytes", used, "B"), Metric("ram_total_bytes", total, "B"),
            Metric("ram_percent", 100 * used / total, "%"))


def _unescape_mount(text: str) -> str:
    def replace(match: re.Match[str]) -> str:
        code = match.group(1)
        if code not in _ESCAPES:
            raise ValueError("Invalid mount escape.")
        return _ESCAPES[code]
    # Decode once: a literal backslash followed by 040 must stay literal.
    return re.sub(r"\\(.{0,3})", replace, text)


def normalized_mount(path: str) -> str:
    if not path.startswith("/") or "\x00" in path:
        raise ValueError("Invalid absolute mount path.")
    return posixpath.normpath("/" + path.lstrip("/"))


def matching_mounts(text: str, path: str) -> list[tuple[int, str, str, str]]:
    """Return exact identities, keeping duplicates so callers reject ambiguity."""
    target = normalized_mount(path)
    matches = []
    for line in text.splitlines():
        if not line:
            continue
        before, separator, after = line.partition(" - ")
        fields = before.split()
        if not separator or len(fields) < 6 or len(after.split()) < 3:
            raise ValueError("Invalid mountinfo record.")
        mount_id = unsigned_integer(fields[0])
        unsigned_integer(fields[1])
        if re.fullmatch(r"[0-9]+:[0-9]+", fields[2]) is None:
            raise ValueError("Invalid mount device identity.")
        root = _unescape_mount(fields[3])
        # Root is an opaque mount identity, not the path we query. Kernel nsfs
        # mounts legitimately use e.g. net:[4026532238] here.
        mount = normalized_mount(_unescape_mount(fields[4]))
        if mount == target:
            matches.append((mount_id, fields[2], root, mount))
    return matches


def _gpu_number(text: str, *, maximum: float | None = None, positive: bool = False) -> float | None:
    if text in _UNSUPPORTED:
        return None
    if re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", text) is None:
        raise ValueError("Invalid GPU numeric format.")
    value = float(text)
    if not math.isfinite(value) or (value <= 0 if positive else value < 0):
        raise ValueError("Invalid GPU measurement.")
    if maximum is not None and value > maximum:
        raise ValueError("Out-of-range GPU measurement.")
    return value


def gpu_metrics(row: list[str], uuid: str) -> tuple[tuple[Metric, ...], Failure | None]:
    """Validate identity first; omit only damaged independent fields thereafter."""
    index = unsigned_integer(row[0])
    if gpu_uuid(row[1]) != uuid:
        raise ValueError("Unexpected GPU identity.")
    metrics: dict[str, Metric] = {"index": Metric("index", index)}
    damaged = False
    if row[2] in _UNSUPPORTED:
        metrics["name"] = Metric("name", None)
    elif (row[2] and not (row[2].startswith("[") and row[2].endswith("]"))
          and all(character.isprintable() for character in row[2])):
        metrics["name"] = Metric("name", row[2])
    else:
        damaged = True
    for name, raw, unit, maximum in (
        ("utilization_percent", row[3], "%", 100),
        ("temperature_c", row[6], "°C", None),
        ("power_w", row[7], "W", None),
    ):
        try:
            metrics[name] = Metric(name, _gpu_number(raw, maximum=maximum), unit)
        except ValueError:
            damaged = True
    try:
        used = _gpu_number(row[4])
        total = _gpu_number(row[5], positive=True)
        if used is not None and total is not None and used > total:
            raise ValueError("Invalid GPU capacity pair.")
        for name, amount in (("memory_used_bytes", used), ("memory_total_bytes", total)):
            value = None if amount is None else amount * 1024 * 1024
            if value is not None and not math.isfinite(value):
                raise ValueError("Invalid GPU byte capacity.")
            byte_count = None if value is None else int(value)
            if name == "memory_total_bytes" and byte_count == 0:
                raise ValueError("GPU total capacity must contain at least one byte.")
            metrics[name] = Metric(name, byte_count, "B")
    except ValueError:
        damaged = True
        metrics.pop("memory_used_bytes", None)
        metrics.pop("memory_total_bytes", None)
    order = ("index", "name", "utilization_percent", "memory_used_bytes", "memory_total_bytes",
             "temperature_c", "power_w")
    return tuple(metrics[name] for name in order if name in metrics), PARSE if damaged else None
