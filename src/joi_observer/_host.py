"""Startup-only local presentation labels; no network lookup."""

from pathlib import Path
import re

from joi_observer.tui.layout import HostInfo


_OS_RELEASE_PATHS = (Path("/etc/os-release"), Path("/usr/lib/os-release"))
_OS_RELEASE_LINE = re.compile(
    r"""^(?P<name>[a-zA-Z0-9_]+)=(?P<quote>["']?)(?P<value>.*)(?P=quote)$"""
)
_OS_RELEASE_UNESCAPE = re.compile(r"""\\([\\$"'`])""")


def _local_release_fields() -> dict[str, str]:
    """Parse only fields actually supplied by the first readable os-release.

    Keep the standard os-release quoting and five special-character escapes,
    but do not inject platform.freedesktop_os_release's synthetic Linux names.
    Read one file once; never merge missing fields with a lower-priority file
    or expand variables/commands. Invalid encoding makes this metadata unknown.
    """
    for path in _OS_RELEASE_PATHS:
        try:
            fields: dict[str, str] = {}
            with path.open(encoding="utf-8") as source:
                for line in source:
                    match = _OS_RELEASE_LINE.match(line)
                    if match and match["name"] in {"PRETTY_NAME", "NAME", "VERSION_ID"}:
                        fields[match["name"]] = _OS_RELEASE_UNESCAPE.sub(r"\1", match["value"])
            return fields
        except OSError:
            continue
        except UnicodeError:
            return {}
    return {}


def local_host_info() -> HostInfo:
    """Read local distribution metadata once; the device label is user-defined.

    This is a startup presentation label, not hardware discovery. A missing or
    unreadable os-release must not prevent monitoring or substitute a kernel
    version for the requested Ubuntu distribution version.
    """
    release = _local_release_fields()
    system = release.get("PRETTY_NAME", "").strip()
    if not system:
        name = release.get("NAME", "").strip() or "Ubuntu"
        version = release.get("VERSION_ID", "").strip() or "—"
        system = f"{name} {version}"
    return HostInfo("H3C R5300 G6", system)
