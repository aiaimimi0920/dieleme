#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
env_file="$repo_root/env.nas.local"
compose_file="$repo_root/docker-compose.nas-central.yml"
build_mode="full"
dry_run=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env-file)
      env_file="$2"
      shift 2
      ;;
    --hotfix)
      build_mode="hotfix"
      shift
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

cd "$repo_root"
[[ -f "$env_file" ]] || { echo "Missing NAS environment file: $env_file" >&2; exit 1; }
command -v docker >/dev/null
command -v curl >/dev/null
command -v python3 >/dev/null
docker compose version >/dev/null

set -a
# shellcheck disable=SC1090
source "$env_file"
set +a

: "${FAPAI_NAS_DATA_ROOT:?FAPAI_NAS_DATA_ROOT must be set}"
postgres_container="${FAPAI_POSTGRES_CONTAINER:-fapaifang-postgres}"
postgres_db="${FAPAI_POSTGRES_DB:-fapaifang}"
postgres_user="${FAPAI_POSTGRES_USER:-fapaifang}"
postgres_password="${FAPAI_POSTGRES_PASSWORD:-fapaifang}"
api_container="${FAPAI_API_CONTAINER:-fapaifang-api}"
api_port="${FAPAI_API_HOST_PORT:-8001}"

version="$(date -u +%Y%m%d-%H%M%S)"
commit="$(git rev-parse --short=12 HEAD 2>/dev/null || printf unknown)"
built_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
source_digest="$({
  sha256sum \
    Dockerfile \
    Dockerfile.nas-hotfix \
    docker-compose.nas-central.yml \
    src/server.py \
    src/captcha_solver.py \
    tools/browserless_seed_probe.py \
    tools/taobao_login_health.py
} | sha256sum | awk '{print $1}')"

export FAPAI_BUILD_VERSION="$version"
export FAPAI_BUILD_COMMIT="$commit"
export FAPAI_BUILD_TIME="$built_at"
export FAPAI_SOURCE_DIGEST="$source_digest"
export FAPAI_DOCKERFILE="Dockerfile"

docker inspect "$postgres_container" >/dev/null
docker inspect "$api_container" >/dev/null
previous_image="$(docker inspect --format '{{.Image}}' "$api_container")"
rollback_tag="fapaifang-collector:rollback-$version"

echo "Deployment identity: version=$version commit=$commit source_digest=$source_digest"
echo "Build mode: $build_mode"
echo "Rollback image tag: $rollback_tag"

if [[ "$dry_run" -eq 1 ]]; then
  echo "Dry run complete; no backup, build, or restart was performed."
  exit 0
fi

backup_dir="$FAPAI_NAS_DATA_ROOT/backups/postgres"
mkdir -p "$backup_dir"
container_dump="/tmp/fapaifang-$version.dump"
host_dump="$backup_dir/fapaifang-$version.dump"

cleanup_dump() {
  docker exec "$postgres_container" rm -f "$container_dump" >/dev/null 2>&1 || true
}
trap cleanup_dump EXIT

docker exec \
  -e "PGPASSWORD=$postgres_password" \
  "$postgres_container" \
  pg_dump -U "$postgres_user" -d "$postgres_db" -Fc -f "$container_dump"
docker exec \
  -e "PGPASSWORD=$postgres_password" \
  "$postgres_container" \
  pg_restore -l "$container_dump" >/dev/null
docker cp "$postgres_container:$container_dump" "$host_dump" >/dev/null
[[ "$(wc -c < "$host_dump")" -ge 1024 ]] || { echo "Database backup is unexpectedly small." >&2; exit 1; }
echo "Verified database backup: $host_dump"

docker image tag "$previous_image" "$rollback_tag"
if [[ "$build_mode" == "hotfix" ]]; then
  export FAPAI_DOCKERFILE="Dockerfile.nas-hotfix"
  export FAPAI_BASE_IMAGE="$previous_image"
fi

rollback() {
  echo "Health gate failed; restoring $rollback_tag" >&2
  FAPAI_IMAGE="$rollback_tag" docker compose \
    --env-file "$env_file" \
    -f "$compose_file" \
    up -d --no-deps --no-build fapaifang-api
}

docker compose --env-file "$env_file" -f "$compose_file" build fapaifang-api
docker compose --env-file "$env_file" -f "$compose_file" up -d --no-deps fapaifang-api

health_url="http://127.0.0.1:$api_port/api/status"
healthy=0
for _ in $(seq 1 60); do
  if payload="$(curl -fsS --max-time 5 "$health_url" 2>/dev/null)"; then
    if EXPECTED_VERSION="$version" EXPECTED_DIGEST="$source_digest" PAYLOAD="$payload" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["PAYLOAD"])
build = payload.get("build_info") or {}
if build.get("version") != os.environ["EXPECTED_VERSION"]:
    raise SystemExit(1)
if build.get("source_digest") != os.environ["EXPECTED_DIGEST"]:
    raise SystemExit(1)
if not payload.get("db_mode"):
    raise SystemExit(1)
PY
    then
      healthy=1
      break
    fi
  fi
  sleep 2
done

if [[ "$healthy" -ne 1 ]]; then
  rollback
  exit 1
fi

docker exec "$postgres_container" pg_isready -U "$postgres_user" -d "$postgres_db" >/dev/null
curl -fsS --max-time 10 "http://127.0.0.1:$api_port/api/collection/overview" >/dev/null
echo "NAS API deployment passed build identity, database, and collection overview health gates."
