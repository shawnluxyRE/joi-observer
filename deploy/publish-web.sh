#!/usr/bin/env bash
set -euo pipefail

release_repo="$(git -C "$(dirname -- "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
release_commit="$(git -C "$release_repo" rev-parse --verify 'HEAD^{commit}')"
image_tag="joi-observer-web:$release_commit"
web_dir=/etc/joi-observer/web
install -d -m 0755 "$web_dir/releases"

# Keep publication and cleanup in the same critical section.
exec 9> "$web_dir/publish.lock"
if ! flock -n 9; then
  printf '另一个 Web 发布正在运行，请稍后重试。\n' >&2
  exit 1
fi

is_release_dir() {
  local name="${1#"$web_dir/releases/"}"
  [[ "$1" == "$web_dir/releases/"* && ! -L "$1" && -d "$1" &&
    "$name" =~ ^([0-9a-f]{40}|[0-9a-f]{64})\.[[:alnum:]]{8}$ ]]
}

cleanup_old_images() {
  local current_image="$1" directory recorded_id image_ids old_image tags tag foreign_tag
  local -A candidates=()
  if ! image_ids="$(docker image ls --quiet --no-trunc)"; then
    printf '无法列出本地镜像，跳过旧镜像清理。\n' >&2
    return
  fi
  while IFS= read -r old_image; do
    if [[ "$old_image" =~ ^sha256:[0-9a-f]{64}$ ]]; then
      candidates["$old_image"]=1
    fi
  done <<< "$image_ids"
  unset 'candidates[$current_image]'
  for directory in "$web_dir/releases/"*; do
    is_release_dir "$directory" || continue
    [[ -f "$directory/image.id" && ! -L "$directory/image.id" ]] || continue
    recorded_id="$(cat -- "$directory/image.id")" || continue
    [[ "$recorded_id" =~ ^sha256:[0-9a-f]{64}$ ]] || continue
    [[ -n "${candidates[$recorded_id]+x}" ]] || continue
    unset 'candidates[$recorded_id]'  # Repeated release records are checked only once.
    if ! tags="$(docker image inspect --format '{{range .RepoTags}}{{println .}}{{end}}' "$recorded_id")"; then
      printf '无法检查旧 Web 镜像 %s 的标签，保留该镜像。\n' "$recorded_id" >&2
      continue
    fi
    foreign_tag=false
    while IFS= read -r tag; do
      if [[ -n "$tag" && ! "$tag" =~ ^joi-observer-web:([0-9a-f]{40}|[0-9a-f]{64})$ ]]; then
        foreign_tag=true
      fi
    done <<< "$tags"
    if [[ "$foreign_tag" == true ]]; then
      printf '保留带有非发行标签的旧 Web 镜像 %s\n' "$recorded_id"
      continue
    fi
    # Docker checks container references; never force deletion or prune globally.
    if ! docker image rm "$recorded_id"; then
      printf '旧 Web 镜像 %s 未能删除，已保留；本次发布仍成功。\n' "$recorded_id" >&2
    fi
  done
}

# Site settings are entered once and reused for upgrades.
if [[ ! -f "$web_dir/.env" ]]; then
  read -r -p "Web 监听的宿主内网 IPv4 地址：" web_bind
  read -r -p "宿主发布端口 [8090]：" web_port
  reader_gid="$(getent group joi-observer-readers | cut -d: -f3)"
  : "${web_bind:?请填写宿主内网 IPv4 地址}" "${reader_gid:?请先创建宿主读者组}"
  printf 'JOI_WEB_BIND=%s\nJOI_WEB_PORT=%s\nJOI_READERS_GID=%s\n' \
    "$web_bind" "${web_port:-8090}" "$reader_gid" > "$web_dir/.env"
fi

release_dir="$(mktemp -d "$web_dir/releases/$release_commit.XXXXXXXX")"
printf 'Web 候选发行目录：%s\n' "$release_dir"
git -C "$release_repo" archive --format=tar "$release_commit" -- \
  README.md pyproject.toml uv.lock ':(glob)src/joi_observer/**/*.py' \
  src/joi_observer/examples/config.yaml \
  src/joi_observer/web/static/{index.html,dashboard.css,dashboard.js} deploy/Dockerfile.web | \
  docker buildx build --load -f deploy/Dockerfile.web -t "$image_tag" -
image_id="$(docker image inspect --format '{{.Id}}' "$image_tag")"
if [[ ! "$image_id" =~ ^sha256:[0-9a-f]{64}$ ]]; then
  printf '构建结果未返回有效的镜像 ID，停止发布。\n' >&2
  exit 1
fi
printf '%s\n' "$image_id" > "$release_dir/image.id"
git -C "$release_repo" show "${release_commit}:tests/web_image_artifact.py" > "$release_dir/check_web.py"

# Pin the built image so retrying the same commit cannot redirect prior recovery.
git -C "$release_repo" show "${release_commit}:deploy/compose.yaml" | \
  env -u JOI_WEB_BIND -u JOI_WEB_PORT -u JOI_READERS_GID JOI_WEB_IMAGE="$image_id" \
    docker compose -p joi-observer --env-file "$web_dir/.env" -f - config --format json \
    > "$release_dir/compose.json"
compose=(docker compose -p joi-observer -f "$release_dir/compose.json")
"${compose[@]}" up -d --pull never --no-build --force-recreate web
web_container="$("${compose[@]}" ps -q web)"
test -n "$web_container"
docker inspect "$web_container" | \
  python3 -I "$release_dir/check_web.py" deployment "$image_id" "$release_dir/compose.json"
"${compose[@]}" exec -T web python3 -I - runtime < "$release_dir/check_web.py"

# An interrupted or failed release leaves current pointing to the last verified one.
ln -s "$release_dir" "$release_dir/as-current"
mv -Tf "$release_dir/as-current" "$web_dir/current"
# Retire any previous-version pointer left by an older publication policy.
if [[ -L "$web_dir/previous" ]]; then
  rm -- "$web_dir/previous"
fi
printf '已发布 Web 镜像 %s (%s)\n' "$image_tag" "$image_id"
cleanup_old_images "$image_id"
