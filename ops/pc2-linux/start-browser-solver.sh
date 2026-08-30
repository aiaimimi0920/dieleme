#!/usr/bin/env bash
set -euo pipefail

display="${DISPLAY:-:99}"
screen_geometry="${FAPAI_BROWSER_SCREEN_GEOMETRY:-1440x900x24}"
profile_dir="${FAPAI_BROWSER_PROFILE_DIR:-/data/browser-profile}"
start_url="${FAPAI_BROWSER_START_URL:-https://sf.taobao.com/}"
vnc_password_file="${FAPAI_VNC_PASSWORD_FILE:-/run/secrets/pc2_vnc_password}"
cdp_endpoint="${FAPAI_CDP_ENDPOINT:-http://127.0.0.1:9223}"
cdp_public_port="${FAPAI_CDP_PUBLIC_PORT:-9224}"
cdp_allowed_client_cidrs="${FAPAI_CDP_ALLOWED_CLIENT_CIDRS:-127.0.0.0/8,::1/128,172.16.0.0/12,192.168.15.20/32,192.168.15.200/32}"
api_base_url="${FAPAI_API_BASE_URL:-http://192.168.15.200:8001/api}"
node_id="${FAPAI_NODE_ID:-pc2}"
xauthority="${XAUTHORITY:-/tmp/.Xauthority}"
vnc_auth_file="/tmp/tigervnc.passwd"

if [[ ! -r "$vnc_password_file" || ! -s "$vnc_password_file" ]]; then
  echo "PC2 browser VNC password file is missing, unreadable, or empty: $vnc_password_file" >&2
  exit 1
fi

if ! head -n 1 "$vnc_password_file" | tigervncpasswd -f >"$vnc_auth_file"; then
  echo "Unable to create the TigerVNC authentication file" >&2
  exit 1
fi
chmod 0600 "$vnc_auth_file"

mkdir -p "$profile_dir" /data/output /app/.codex-temp/bridge-control
rm -f "$profile_dir/SingletonLock" "$profile_dir/SingletonSocket" "$profile_dir/SingletonCookie"

display_number="${display#:}"
if [[ "$display_number" =~ ^[0-9]+$ ]]; then
  display_lock="/tmp/.X${display_number}-lock"
  display_socket="/tmp/.X11-unix/X${display_number}"
  if [[ -f "$display_lock" ]]; then
    display_pid="$(tr -dc '0-9' <"$display_lock")"
    if [[ -n "$display_pid" && -d "/proc/$display_pid" ]]; then
      echo "X display $display is already owned by process $display_pid" >&2
      exit 1
    fi
  fi
  rm -f "$display_lock" "$display_socket"
fi

export DISPLAY="$display"
export DBUS_SESSION_BUS_ADDRESS=/dev/null
export XAUTHORITY="$xauthority"
touch "$XAUTHORITY"
chmod 0600 "$XAUTHORITY"

pids=()
cleanup() {
  local pid
  for pid in "${pids[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

Xvfb "$display" -screen 0 "$screen_geometry" -nolisten tcp -ac &
pids+=("$!")

for _ in $(seq 1 40); do
  if xdotool getmouselocation >/dev/null 2>&1; then
    break
  fi
  sleep 0.25
done
xdotool getmouselocation >/dev/null 2>&1 || {
  echo "Xvfb did not become ready on $display" >&2
  exit 1
}

fluxbox >/tmp/fluxbox.log 2>&1 &
pids+=("$!")
x0tigervncserver \
  -display "$display" \
  -rfbport 5900 \
  -SecurityTypes VncAuth \
  -PasswordFile "$vnc_auth_file" \
  -AlwaysShared \
  -fg >/tmp/tigervnc.log 2>&1 &
pids+=("$!")
websockify --web=/usr/share/novnc 6080 127.0.0.1:5900 >/tmp/websockify.log 2>&1 &
pids+=("$!")

chromium_executable="$({
  python - <<'PY'
from playwright.sync_api import sync_playwright

with sync_playwright() as playwright:
    print(playwright.chromium.executable_path)
PY
} | tail -n 1)"

if [[ ! -x "$chromium_executable" ]]; then
  echo "Playwright Chromium executable not found: $chromium_executable" >&2
  exit 1
fi

# Xvfb otherwise leaves WebGL disabled through Chrome's software-GPU blocklist,
# which gives the Taobao NC page a broken browser fingerprint.
"$chromium_executable" \
  --no-sandbox \
  --disable-dev-shm-usage \
  --disable-blink-features=AutomationControlled \
  --ignore-gpu-blocklist \
  --enable-webgl \
  --enable-unsafe-swiftshader \
  --use-gl=angle \
  --use-angle=swiftshader \
  --disable-background-networking \
  --disable-default-apps \
  --disable-features=Translate,OptimizationHints,MediaRouter \
  --disable-session-crashed-bubble \
  --no-default-browser-check \
  --no-first-run \
  --remote-allow-origins='*' \
  --remote-debugging-address=0.0.0.0 \
  --remote-debugging-port=9223 \
  --user-data-dir="$profile_dir" \
  --window-position=0,0 \
  --window-size=1440,900 \
  "$start_url" >/tmp/chromium.log 2>&1 &
pids+=("$!")

python - <<'PY'
import json
import time
from urllib.request import urlopen

for _ in range(120):
    try:
        with urlopen("http://127.0.0.1:9223/json/version", timeout=2) as response:
            payload = json.load(response)
        if payload.get("webSocketDebuggerUrl"):
            raise SystemExit(0)
    except Exception:
        time.sleep(1)
raise SystemExit("Chromium CDP did not become ready on port 9223")
PY

# Chromium binds its DevTools HTTP server to loopback even when
# --remote-debugging-address=0.0.0.0 is supplied. Keep that endpoint private
# and normalize the Host header while relaying HTTP and WebSocket traffic.
relay_allow_args=()
IFS=',' read -r -a configured_cdp_cidrs <<<"$cdp_allowed_client_cidrs"
for cidr in "${configured_cdp_cidrs[@]}"; do
  [[ -n "$cidr" ]] && relay_allow_args+=(--allow-cidr "$cidr")
done
if (( ${#relay_allow_args[@]} == 0 )); then
  echo "FAPAI_CDP_ALLOWED_CLIENT_CIDRS must contain at least one CIDR" >&2
  exit 1
fi
python tools/cdp_host_relay.py \
  --listen-port "$cdp_public_port" \
  --upstream-host 127.0.0.1 \
  --upstream-port 9223 \
  "${relay_allow_args[@]}" &
pids+=("$!")

python - "$cdp_public_port" <<'PY'
import json
import sys
import time
from urllib.request import urlopen

endpoint = f"http://127.0.0.1:{int(sys.argv[1])}/json/version"
for _ in range(40):
    try:
        with urlopen(endpoint, timeout=2) as response:
            payload = json.load(response)
        if payload.get("webSocketDebuggerUrl"):
            raise SystemExit(0)
    except Exception:
        time.sleep(0.25)
raise SystemExit(f"public Chromium CDP relay did not become ready: {endpoint}")
PY

solver_heartbeat_path="${FAPAI_LOCAL_SOLVER_HEARTBEAT_PATH:-/tmp/fapaifang-local-solver-heartbeat.json}"
rm -f "$solver_heartbeat_path"
python tools/pc2_solver_watchdog.py \
  --heartbeat-path "$solver_heartbeat_path" \
  --stale-seconds "${FAPAI_LOCAL_SOLVER_WATCHDOG_STALE_SECONDS:-300}" \
  --startup-grace-seconds "${FAPAI_LOCAL_SOLVER_WATCHDOG_STARTUP_GRACE_SECONDS:-180}" \
  --poll-seconds "${FAPAI_LOCAL_SOLVER_WATCHDOG_POLL_SECONDS:-30}" \
  --parent-pid 1 &
pids+=("$!")

trap - EXIT
exec python tools/pc2_local_solver.py \
  --api-base-url "$api_base_url" \
  --cdp-endpoint "$cdp_endpoint" \
  --poll-seconds "${FAPAI_LOCAL_SOLVER_POLL_SECONDS:-5}" \
  --max-attempts "${FAPAI_LOCAL_SOLVER_MAX_ATTEMPTS:-10}" \
  --node-id "$node_id"
