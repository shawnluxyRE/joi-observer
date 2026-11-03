#!/usr/bin/env bash
# Run manually on the monitored Ubuntu host. Never invoke this in automated tests.
set -u
set -o pipefail
umask 077

usage() {
  printf 'Usage: bash %s [--sudo]\n' "$0"
  printf 'With --sudo, run sudo -v first; only Docker commands use sudo -n.\n'
}

docker_command=(docker --host unix:///var/run/docker.sock)
case "${1:-}" in
  '') ;;
  --sudo) docker_command=(sudo -n docker --host unix:///var/run/docker.sock) ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac
if (( $# > 1 )); then usage >&2; exit 2; fi

for dependency in curl docker python3 mktemp timeout date sleep mkdir mv; do
  if ! command -v "$dependency" >/dev/null 2>&1; then
    printf 'Missing dependency: %s\n' "$dependency" >&2
    exit 2
  fi
done
if [[ "${1:-}" == --sudo ]] && ! command -v sudo >/dev/null 2>&1; then
  printf 'Missing dependency: sudo\n' >&2
  exit 2
fi

# Change these names only if the deployment's container names differ. Do not
# substitute a gateway container or change the fixed loopback HTTP targets.
containers=(flash-next-vllm qwen3-embedding-vllm qwen3-reranker-vllm)
ports=(8000 8001 8002)
for container in "${containers[@]}"; do
  if [[ ! "$container" =~ ^[a-zA-Z0-9][a-zA-Z0-9_.-]*$ ]]; then
    printf 'Invalid container name in containers array.\n' >&2
    exit 2
  fi
done
http_max_bytes=2097152
evidence_dir=$(mktemp -d "${TMPDIR:-/tmp}/joi-vllm-evidence.XXXXXXXX") || exit 2
archive_path="${evidence_dir}.tar.gz"
mkdir -p "$evidence_dir/http" "$evidence_dir/containers" || exit 2
printf 'Evidence directory: %s\n' "$evidence_dir"

python3 -B - "$evidence_dir/run.json" <<'PY'
import datetime
import json
import pathlib
import sys

pathlib.Path(sys.argv[1]).write_text(json.dumps({
    "schema": "joi-observer-vllm-evidence-v1",
    "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "purpose": "Raw, unverified deployment evidence for offline design review",
    "http_targets": ["http://127.0.0.1:8000", "http://127.0.0.1:8001", "http://127.0.0.1:8002"],
    "http_paths": ["/version", "/v1/models", "/metrics"],
    "http_body_limit_bytes": 2097152,
    "metrics_rounds": 2,
    "minimum_pause_between_rounds_seconds": 2,
    "collection_policy": "GET only; no inference, redirects, proxy, environment, arguments, or service logs",
}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
PY
if (( $? != 0 )); then exit 2; fi

fetch_evidence() {
  local port="$1" route="$2" label="$3" extension="$4"
  local request_dir="$evidence_dir/http/$port/$label"
  local exit_code status
  mkdir -p "$request_dir" || return 2
  date -u '+%Y-%m-%dT%H:%M:%S.%NZ' > "$request_dir/started_at_utc.txt"
  # --disable must be curl's first option: never read the user's .curlrc.
  # No --location: redirects remain responses and are never followed.
  curl --disable --request GET --noproxy '*' --proxy '' \
    --proto '=http' --connect-timeout 2 --max-time 8 \
    --max-filesize "$http_max_bytes" --retry 0 \
    --silent --show-error \
    --output "$request_dir/response.partial" \
    --write-out '%{http_code}\n' \
    "http://127.0.0.1:$port/$route" \
    > "$request_dir/http_status.txt" 2> "$request_dir/curl.stderr"
  exit_code=$?
  printf '%s\n' "$exit_code" > "$request_dir/curl_exit_code.txt"
  date -u '+%Y-%m-%dT%H:%M:%S.%NZ' > "$request_dir/finished_at_utc.txt"
  status=$(< "$request_dir/http_status.txt")
  if [[ "$exit_code" == 0 && "$status" == 200 ]]; then
    mv "$request_dir/response.partial" "$request_dir/body.$extension"
    printf 'transport_success_payload_unverified\n' > "$request_dir/result.txt"
  else
    # Failed and truncated bodies never acquire the .prom/.json sample name.
    printf 'request_failed_or_non_200\n' > "$request_dir/result.txt"
  fi
}

for port in "${ports[@]}"; do
  fetch_evidence "$port" version version json
  fetch_evidence "$port" v1/models models json
done
for round in 1 2; do
  for port in "${ports[@]}"; do
    fetch_evidence "$port" metrics "metrics-$round" prom
  done
  if [[ "$round" == 1 ]]; then sleep 2; fi
done

for container in "${containers[@]}"; do
  container_dir="$evidence_dir/containers/$container"
  mkdir -p "$container_dir" || continue
  date -u '+%Y-%m-%dT%H:%M:%S.%NZ' > "$container_dir/started_at_utc.txt"
  # Whitelisted metadata only: no Config.Env, Config.Cmd, Args, or logs.
  timeout --signal=TERM --kill-after=2s 15s "${docker_command[@]}" inspect \
    --format '{"name":{{json .Name}},"configured_image":{{json .Config.Image}},"image_id":{{json .Image}},"status":{{json .State.Status}},"started_at":{{json .State.StartedAt}},"device_requests":{{json .HostConfig.DeviceRequests}},"ports":{{json .NetworkSettings.Ports}}}' \
    "$container" > "$container_dir/inspect.json" 2> "$container_dir/inspect.stderr"
  printf '%s\n' "$?" > "$container_dir/inspect_exit_code.txt"

  timeout --signal=TERM --kill-after=2s 15s "${docker_command[@]}" exec \
    "$container" python3 -B -c \
    'import importlib.metadata as m, json; d=m.distribution("vllm"); print(json.dumps({"version":d.version,"package_path":str(d.locate_file("vllm"))}))' \
    > "$container_dir/package.json" 2> "$container_dir/package.stderr"
  printf '%s\n' "$?" > "$container_dir/package_exit_code.txt"

  # Python reads installed source with the standard library; it does not import
  # vllm, initialize CUDA, write bytecode, or create files in the container.
  timeout --signal=TERM --kill-after=2s 45s "${docker_command[@]}" exec -i \
    "$container" python3 -B - \
    > "$container_dir/sources.partial" 2> "$container_dir/sources.stderr" <<'PY'
import hashlib
import importlib.metadata
import io
import json
import os
import pathlib
import stat
import sys
import tarfile

FILE_LIMIT = 2 * 1024 * 1024
TOTAL_LIMIT = 20 * 1024 * 1024
ENTRY_LIMIT = 4096
DEPTH_LIMIT = 16
directory_scopes = ("v1/metrics", "entrypoints/pooling")
exact_files = (
    "v1/request.py",
    "v1/engine/core.py",
    "v1/engine/output_processor.py",
    "v1/core/sched/scheduler.py",
)
distribution = importlib.metadata.distribution("vllm")
root = pathlib.Path(distribution.locate_file("vllm"))
if root.is_symlink() or not root.is_dir():
    raise RuntimeError("Installed vllm package root is absent or is a symlink")

manifest = {
    "version": distribution.version,
    "package_path": str(root),
    "directory_scopes_python_only": directory_scopes,
    "exact_files": exact_files,
    "limits": {"per_file_bytes": FILE_LIMIT, "total_source_bytes": TOTAL_LIMIT,
               "directory_entries": ENTRY_LIMIT, "depth": DEPTH_LIMIT},
    "captured": [],
    "omitted": [],
}
candidates = set()
entries_seen = 0
enumeration_stopped = False

def relative(path):
    return path.relative_to(root).as_posix()

def omit(path, reason):
    manifest["omitted"].append({"path": relative(path), "reason": reason})

def has_symlink(path):
    current = root
    for part in path.relative_to(root).parts:
        current = current / part
        if current.is_symlink():
            return True
    return False

def visit(directory, depth=0):
    global entries_seen, enumeration_stopped
    if enumeration_stopped:
        return
    if has_symlink(directory):
        omit(directory, "symlink")
        return
    if depth > DEPTH_LIMIT:
        omit(directory, "depth_limit")
        return
    try:
        with os.scandir(directory) as entries:
            for entry in entries:
                entries_seen += 1
                if entries_seen > ENTRY_LIMIT:
                    omit(directory, "directory_entry_limit")
                    enumeration_stopped = True
                    return
                path = pathlib.Path(entry.path)
                if entry.is_symlink():
                    omit(path, "symlink")
                elif entry.is_dir(follow_symlinks=False):
                    if entry.name != "__pycache__":
                        visit(path, depth + 1)
                        if enumeration_stopped:
                            return
                elif entry.is_file(follow_symlinks=False) and path.suffix == ".py":
                    candidates.add(path)
    except OSError as error:
        omit(directory, type(error).__name__)

for scope in directory_scopes:
    visit(root / scope)
for filename in exact_files:
    candidates.add(root / filename)

captured = []
total_bytes = 0
for path in sorted(candidates):
    if has_symlink(path):
        omit(path, "symlink")
        continue
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb") as source:
            metadata = os.fstat(source.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                omit(path, "not_regular_file")
                continue
            if metadata.st_size > FILE_LIMIT:
                omit(path, "per_file_size_limit")
                continue
            payload = source.read(FILE_LIMIT + 1)
    except OSError as error:
        omit(path, type(error).__name__)
        continue
    if len(payload) > FILE_LIMIT:
        omit(path, "per_file_size_limit")
        continue
    if total_bytes + len(payload) > TOTAL_LIMIT:
        omit(path, "total_source_size_limit")
        continue
    total_bytes += len(payload)
    captured.append(("vllm/" + relative(path), payload))
    manifest["captured"].append({"path": relative(path), "bytes": len(payload),
                                 "sha256": hashlib.sha256(payload).hexdigest()})

manifest["total_source_bytes"] = total_bytes
manifest["directory_entries_examined"] = min(entries_seen, ENTRY_LIMIT)
manifest["complete_within_allowlist"] = not manifest["omitted"]
if not captured:
    # This is a collection failure, never an empty successful source snapshot.
    raise RuntimeError("No allowlisted vllm source files could be read")
captured.append(("source-manifest.json", (json.dumps(manifest, ensure_ascii=False, indent=2)
                                         + "\n").encode("utf-8")))
with tarfile.open(fileobj=sys.stdout.buffer, mode="w|gz") as archive:
    for name, payload in captured:
        member = tarfile.TarInfo(name)
        member.size = len(payload)
        member.mode = 0o600
        member.mtime = 0
        archive.addfile(member, io.BytesIO(payload))
PY
  source_exit_code=$?
  printf '%s\n' "$source_exit_code" > "$container_dir/sources_exit_code.txt"
  if [[ "$source_exit_code" == 0 ]]; then
    mv "$container_dir/sources.partial" "$container_dir/sources.tar.gz"
  fi
  date -u '+%Y-%m-%dT%H:%M:%S.%NZ' > "$container_dir/finished_at_utc.txt"
done

python3 -B - "$evidence_dir" "$archive_path" <<'PY'
import pathlib
import sys
import tarfile

root = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
with tarfile.open(destination, "w:gz") as archive:
    archive.add(root, arcname=root.name)
print("Evidence archive: " + str(destination))
print("Read status sidecars and source-manifest.json before treating any payload as evidence.")
PY
