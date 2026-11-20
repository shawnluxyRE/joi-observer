#!/usr/bin/env bash
set -euo pipefail

release_repo="$(git -C "$(dirname -- "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)"
release_commit="$(git -C "$release_repo" rev-parse --verify 'HEAD^{commit}')"
image_tag="joi-observer-web:$release_commit"
web_dir=/etc/joi-observer/web
install -d -m 0755 "$web_dir/releases"

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
printf '已发布 Web 镜像 %s (%s)\n' "$image_tag" "$image_id"
