#!/usr/bin/env bash
set -euo pipefail

app_root="/srv/apps/fapaifang-worker"
data_root="/srv/data/fapaifang-worker"
shared_root="$app_root/shared"
runtime_env="$shared_root/runtime.env"
vnc_password_file="$shared_root/vnc-password"
project_name="fapaifang-pc2"
expected_ip="192.168.15.104"
release_dir=""
release_id=""
mode="deploy"
dry_run=0
skip_build=0

usage() {
  cat <<'EOF'
Usage:
  deploy.sh --release-dir PATH --release-id ID [--dry-run] [--skip-build]
  deploy.sh --rollback

The runtime environment and VNC password must already exist at:
  /srv/apps/fapaifang-worker/shared/runtime.env
  /srv/apps/fapaifang-worker/shared/vnc-password
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --release-dir)
      release_dir="${2:-}"
      shift 2
      ;;
    --release-id)
      release_id="${2:-}"
      shift 2
      ;;
    --dry-run)
      dry_run=1
      shift
      ;;
    --skip-build)
      skip_build=1
      shift
      ;;
    --rollback)
      mode="rollback"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

verify_identity() {
  [[ "$(hostname -s)" == "pc2" ]] || {
    echo "Refusing deployment: hostname is not pc2." >&2
    return 1
  }
  ip -o -4 addr show scope global | awk '{print $4}' | grep -Eq '^192\.168\.15\.104/' || {
    echo "Refusing deployment: expected PC2 address $expected_ip is missing." >&2
    return 1
  }
  [[ -r /etc/pc2-install-profile ]] || {
    echo "Refusing deployment: /etc/pc2-install-profile is missing." >&2
    return 1
  }
  grep -Eq '^PROFILE=pc2$' /etc/pc2-install-profile || {
    echo "Refusing deployment: install profile is not pc2." >&2
    return 1
  }
  grep -Eq '^EXPECTED_BOOT_MODE=uefi$' /etc/pc2-install-profile || {
    echo "Refusing deployment: PC2 boot-mode contract is not uefi." >&2
    return 1
  }
  sudo -n true
  docker version >/dev/null
  docker compose version >/dev/null
}

verify_runtime_inputs() {
  [[ -f "$runtime_env" && -s "$runtime_env" ]] || {
    echo "Runtime environment is missing: $runtime_env" >&2
    return 1
  }
  [[ -f "$vnc_password_file" && -s "$vnc_password_file" ]] || {
    echo "VNC password file is missing: $vnc_password_file" >&2
    return 1
  }
  local key
  for key in FAPAI_WORKER_DB_URL OPENAI_API_KEY; do
    grep -Eq "^${key}=.+" "$runtime_env" || {
      echo "Runtime environment is missing required key: $key" >&2
      return 1
    }
  done
  if grep -Eq '(^|=)(replace-me|changeme)([[:space:]]|$)' "$runtime_env"; then
    echo "Runtime environment still contains a placeholder value." >&2
    return 1
  fi
}

compose_for() {
  local target_release="$1"
  shift
  docker compose \
    --project-name "$project_name" \
    --env-file "$runtime_env" \
    --env-file "$target_release/.release.env" \
    --file "$target_release/ops/pc2-linux/compose.yaml" \
    "$@"
}

wait_for_health() {
  local deadline=$((SECONDS + 600))
  local containers=(
    fapaifang-pc2-browser-solver
    fapaifang-pc2-seed-1
    fapaifang-pc2-detail-1
    fapaifang-pc2-detail-2
    fapaifang-pc2-detail-3
    fapaifang-pc2-analysis-1
    fapaifang-pc2-analysis-2
    fapaifang-pc2-analysis-3
    fapaifang-pc2-analysis-4
  )
  local name state
  while (( SECONDS < deadline )); do
    local all_healthy=1
    for name in "${containers[@]}"; do
      state="$(docker inspect --format '{{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$name" 2>/dev/null || true)"
      if [[ "$state" != "running healthy" ]]; then
        all_healthy=0
        break
      fi
    done
    if (( all_healthy )); then
      return 0
    fi
    sleep 5
  done
  echo "PC2 services did not all become healthy within 600 seconds." >&2
  return 1
}

validate_release_tree() {
  local target_release="$1"
  [[ -f "$target_release/Dockerfile" ]]
  [[ -f "$target_release/ops/pc2-linux/Dockerfile.browser" ]]
  [[ -f "$target_release/ops/pc2-linux/compose.yaml" ]]
  [[ -f "$target_release/tools/pc2_linux_healthcheck.py" ]]
  bash -n "$target_release/ops/pc2-linux/start-browser-solver.sh"
  compose_for "$target_release" config --quiet
}

write_release_metadata() {
  local target_release="$1"
  local app_image="$2"
  local browser_image="$3"
  local app_image_id browser_image_id
  app_image_id="$(docker image inspect --format '{{.Id}}' "$app_image")"
  browser_image_id="$(docker image inspect --format '{{.Id}}' "$browser_image")"
  umask 022
  cat >"$target_release/.release.env" <<EOF
FAPAI_IMAGE=$app_image
FAPAI_BROWSER_IMAGE=$browser_image
EOF
  cat >"$target_release/release-manifest.txt" <<EOF
release_id=$release_id
app_image=$app_image
app_image_id=$app_image_id
browser_image=$browser_image
browser_image_id=$browser_image_id
compose_project=$project_name
compose_services=9
EOF
}

restore_release() {
  local prior_release="$1"
  if [[ -n "$prior_release" && -d "$prior_release" && -f "$prior_release/.release.env" ]]; then
    echo "Restoring previous PC2 release: $prior_release" >&2
    compose_for "$prior_release" up -d --remove-orphans
    wait_for_health
    sudo -n ln -sfn "$prior_release" "$app_root/current"
    return 0
  fi
  return 1
}

deploy_release() {
  [[ -n "$release_dir" && -n "$release_id" ]] || {
    echo "--release-dir and --release-id are required." >&2
    usage >&2
    return 2
  }
  release_dir="$(readlink -f "$release_dir")"
  [[ -d "$release_dir" ]] || {
    echo "Release directory does not exist: $release_dir" >&2
    return 1
  }
  [[ "$release_id" =~ ^[0-9A-Za-z._-]+$ ]] || {
    echo "Release ID contains unsupported characters." >&2
    return 1
  }

  local expected_release="$app_root/releases/$release_id"
  [[ "$release_dir" == "$expected_release" ]] || {
    echo "Release must be staged at $expected_release" >&2
    return 1
  }

  if (( dry_run )); then
    echo "Dry run passed identity and path checks for $expected_release."
    return 0
  fi

  verify_runtime_inputs
  local prior_release=""
  if [[ -L "$app_root/current" ]]; then
    prior_release="$(readlink -f "$app_root/current")"
  fi

  local app_image="fapaifang-worker:$release_id"
  local browser_image="fapaifang-browser:$release_id"
  local source_digest build_time build_commit
  source_digest="$(find "$release_dir" -type f ! -name '.release.env' ! -name 'release-manifest.txt' -print0 | sort -z | xargs -0 sha256sum | sha256sum | awk '{print $1}')"
  build_time="$(date --iso-8601=seconds)"
  build_commit="$(git -C "$release_dir" rev-parse HEAD 2>/dev/null || printf 'working-tree')"

  if (( skip_build )); then
    docker image inspect "$app_image" >/dev/null
    docker image inspect "$browser_image" >/dev/null
    echo "Using preloaded PC2 release images for $release_id."
  else
    docker build \
      --build-arg "FAPAI_BUILD_VERSION=$release_id" \
      --build-arg "FAPAI_BUILD_COMMIT=$build_commit" \
      --build-arg "FAPAI_BUILD_TIME=$build_time" \
      --build-arg "FAPAI_SOURCE_DIGEST=$source_digest" \
      --tag "$app_image" \
      --file "$release_dir/Dockerfile" \
      "$release_dir"
    docker build \
      --build-arg "FAPAI_BASE_IMAGE=$app_image" \
      --tag "$browser_image" \
      --file "$release_dir/ops/pc2-linux/Dockerfile.browser" \
      "$release_dir"
  fi
  write_release_metadata "$release_dir" "$app_image" "$browser_image"
  validate_release_tree "$release_dir"

  if compose_for "$release_dir" up -d --remove-orphans && wait_for_health; then
    if [[ -n "$prior_release" && "$prior_release" != "$release_dir" ]]; then
      sudo -n ln -sfn "$prior_release" "$app_root/previous"
    fi
    sudo -n ln -sfn "$release_dir" "$app_root/current"
    compose_for "$release_dir" ps
    echo "PC2 release is healthy: $release_id"
    return 0
  fi

  echo "PC2 release failed health validation." >&2
  compose_for "$release_dir" ps >&2 || true
  if restore_release "$prior_release"; then
    echo "Previous release restored after failed deployment." >&2
  else
    echo "No healthy previous release was available; failed containers were left for diagnosis." >&2
  fi
  return 1
}

rollback_release() {
  verify_runtime_inputs
  [[ -L "$app_root/current" && -L "$app_root/previous" ]] || {
    echo "Rollback requires both current and previous release links." >&2
    return 1
  }
  local current_release previous_release
  current_release="$(readlink -f "$app_root/current")"
  previous_release="$(readlink -f "$app_root/previous")"
  [[ -d "$previous_release" && -f "$previous_release/.release.env" ]] || {
    echo "Previous release is not deployable: $previous_release" >&2
    return 1
  }
  validate_release_tree "$previous_release"
  compose_for "$previous_release" up -d --remove-orphans
  wait_for_health
  sudo -n ln -sfn "$previous_release" "$app_root/current"
  sudo -n ln -sfn "$current_release" "$app_root/previous"
  compose_for "$previous_release" ps
  echo "Rollback completed: $(basename "$previous_release")"
}

verify_identity

if (( dry_run )) && [[ "$mode" == "rollback" ]]; then
  echo "--dry-run cannot be combined with --rollback." >&2
  exit 2
fi

if [[ "$mode" == "rollback" ]]; then
  rollback_release
else
  deploy_release
fi
