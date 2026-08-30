from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from tools import pc2_linux_healthcheck


REPO_ROOT = Path(__file__).resolve().parents[2]
OPS_ROOT = REPO_ROOT / "ops" / "pc2-linux"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_linux_compose_has_expected_decoupled_topology() -> None:
    compose = _read(OPS_ROOT / "compose.yaml")

    expected_services = (
        "pc2-browser-solver",
        "pc2-seed-1",
        "pc2-detail-1",
        "pc2-detail-2",
        "pc2-detail-3",
        "pc2-analysis-1",
        "pc2-analysis-2",
        "pc2-analysis-3",
        "pc2-analysis-4",
    )
    for service in expected_services:
        assert f"  {service}:" in compose
    analysis_section = compose.split("  pc2-analysis-1:", 1)[1]
    assert "condition: service_healthy" not in analysis_section
    assert "FAPAI_DETAIL_ANALYSIS_ONLY: \"1\"" in analysis_section
    assert "deepseek" not in compose.lower(), "model secrets and routing belong in runtime.env"


def test_linux_compose_preserves_solver_retry_contract() -> None:
    compose = _read(OPS_ROOT / "compose.yaml")
    env_example = _read(OPS_ROOT / "env.example")

    assert "FAPAI_SOLVER_COOLDOWN_FAIL_THRESHOLD:-10" in compose
    assert "FAPAI_SOLVER_COOLDOWN_SECONDS:-180" in compose
    assert "FAPAI_SLIDER_RETRY_INTERVAL_SECONDS:-5" in compose
    assert "FAPAI_SOLVER_MANUAL_FALLBACK_ENABLED: \"0\"" in compose
    assert "FAPAI_SOLVER_ENABLE_HEADED_PLAYWRIGHT: \"0\"" in compose
    assert "FAPAI_LOCAL_SOLVER_EXECUTION_TIMEOUT_SECONDS:-180" in compose
    assert "FAPAI_LOCAL_SOLVER_TERMINATE_GRACE_SECONDS:-5" in compose
    assert "FAPAI_LOCAL_SOLVER_WATCHDOG_STALE_SECONDS:-300" in compose
    assert "FAPAI_LOCAL_SOLVER_WATCHDOG_STARTUP_GRACE_SECONDS:-180" in compose
    assert "FAPAI_LOCAL_SOLVER_WATCHDOG_POLL_SECONDS:-30" in compose
    assert "FAPAI_NAS_AUTH_RECOVERY_CLIENT_ENABLED:-1" in compose
    assert "FAPAI_NAS_AUTH_RECOVERY_MARKER_PATH" in compose
    assert "FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE: /data/secrets/nas-auth-recovery.token" in compose
    assert "FAPAI_LOCAL_SOLVER_EXECUTION_TIMEOUT_SECONDS=180" in env_example
    assert "FAPAI_LOCAL_SOLVER_TERMINATE_GRACE_SECONDS=5" in env_example
    assert "FAPAI_LOCAL_SOLVER_WATCHDOG_STALE_SECONDS=300" in env_example
    assert "FAPAI_NAS_AUTH_RECOVERY_CLIENT_ENABLED=1" in env_example
    assert "FAPAI_NAS_AUTH_RECOVERY_SNAPSHOT_PATH: /app/.codex-temp/bridge-control/pc2-auth-snapshot.json" in compose
    assert "FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED: \"1\"" in compose
    assert compose.count("${FAPAI_HOST_DATA_GID:-1000}") == 2
    browser_section = compose.split("  pc2-browser-solver:", 1)[1].split(
        "  pc2-seed-1:", 1
    )[0]
    assert "FAPAI_CDP_ALLOWED_CLIENT_CIDRS" in browser_section
    assert "192.168.15.200/32" in browser_section
    secrets_mount = browser_section.split(
        "source: ${FAPAI_DATA_ROOT:?set FAPAI_DATA_ROOT}/secrets", 1
    )[1].split("- type: bind", 1)[0]
    assert "read_only: true" in secrets_mount


def test_linux_runtime_files_do_not_reference_windows_paths() -> None:
    runtime_files = (
        OPS_ROOT / "Dockerfile.browser",
        OPS_ROOT / "compose.yaml",
        OPS_ROOT / "start-browser-solver.sh",
        OPS_ROOT / "deploy.sh",
    )
    for path in runtime_files:
        text = _read(path).lower()
        assert "c:\\" not in text
        assert "powershell" not in text
        assert "schtasks" not in text


def test_browser_image_keeps_solver_and_os_mouse_in_one_display() -> None:
    dockerfile = _read(OPS_ROOT / "Dockerfile.browser")
    start_script = _read(OPS_ROOT / "start-browser-solver.sh")

    for package in (
        "xvfb",
        "fluxbox",
        "tigervnc-scraping-server",
        "tigervnc-tools",
        "xdotool",
        "novnc",
        "gnome-screenshot",
        "Pillow==11.3.0",
    ):
        assert package in dockerfile
    assert 'export DISPLAY="$display"' in start_script
    assert 'export XAUTHORITY="$xauthority"' in start_script
    assert 'touch "$XAUTHORITY"' in start_script
    assert "tools/pc2_local_solver.py" in start_script
    assert "--remote-debugging-port=9223" in start_script
    assert "tools/cdp_host_relay.py" in start_script
    assert "COPY tools/cdp_host_relay.py /app/tools/cdp_host_relay.py" in dockerfile
    assert "COPY tools/pc2_solver_watchdog.py /app/tools/pc2_solver_watchdog.py" in dockerfile
    assert "--upstream-host 127.0.0.1" in start_script
    assert "--upstream-port 9223" in start_script
    assert "--allow-cidr" in start_script
    assert "FAPAI_CDP_ALLOWED_CLIENT_CIDRS" in start_script
    assert 'FAPAI_CDP_PUBLIC_PORT:-9224' in start_script
    assert "tools/pc2_solver_watchdog.py" in start_script
    assert 'FAPAI_LOCAL_SOLVER_WATCHDOG_STALE_SECONDS:-300' in start_script
    assert "EXPOSE 6080 9224" in dockerfile
    assert '[[ ! -r "$vnc_password_file" || ! -s "$vnc_password_file" ]]' in start_script
    assert 'tigervncpasswd -f >"$vnc_auth_file"' in start_script
    assert "x0tigervncserver" in start_script
    assert "-SecurityTypes VncAuth" in start_script
    assert 'rm -f "$display_lock" "$display_socket"' in start_script


def test_browser_enables_webgl_in_the_xvfb_runtime() -> None:
    start_script = _read(OPS_ROOT / "start-browser-solver.sh")

    for flag in (
        "--ignore-gpu-blocklist",
        "--enable-webgl",
        "--enable-unsafe-swiftshader",
        "--use-gl=angle",
        "--use-angle=swiftshader",
    ):
        assert flag in start_script


def test_browser_healthcheck_does_not_trigger_rfb_authentication() -> None:
    healthcheck = _read(REPO_ROOT / "tools" / "pc2_linux_healthcheck.py")

    assert 'port: int = 5900' in healthcheck
    assert 'Path("/proc/net/tcp")' in healthcheck
    assert "_check_rfb_listener()" in healthcheck
    assert "invalid RFB banner" not in healthcheck
    assert '_process_exists("x0tigervncserver")' in healthcheck
    assert '_process_exists("websockify")' in healthcheck
    assert '_process_exists("tools/pc2_solver_watchdog.py")' in healthcheck
    assert "_check_solver_heartbeat()" in healthcheck


def test_rfb_listener_check_reads_proc_without_connecting(tmp_path: Path) -> None:
    proc_net_tcp = tmp_path / "tcp"
    proc_net_tcp.write_text(
        "  sl  local_address rem_address   st\n"
        "   0: 0100007F:170C 00000000:0000 0A\n",
        encoding="ascii",
    )

    pc2_linux_healthcheck._check_rfb_listener(proc_net_paths=(proc_net_tcp,))

    proc_net_tcp.write_text(
        "  sl  local_address rem_address   st\n"
        "   0: 0100007F:170C 00000000:0000 01\n",
        encoding="ascii",
    )
    with pytest.raises(RuntimeError, match="RFB server is not listening"):
        pc2_linux_healthcheck._check_rfb_listener(proc_net_paths=(proc_net_tcp,))


def test_browser_healthcheck_is_directly_executable() -> None:
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "tools" / "pc2_linux_healthcheck.py"), "--help"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_linux_compose_uses_compatibility_cdp_relay() -> None:
    compose = _read(OPS_ROOT / "compose.yaml")

    assert "http://pc2-browser-solver:9224" in compose
    assert "http://192.168.15.104:9224" in compose
    assert 'FAPAI_CDP_PUBLIC_PORT: "9224"' in compose
    assert ':9224:9224"' in compose
    assert ":9223:9223" not in compose


def test_deploy_script_has_identity_gate_and_rollback_links() -> None:
    deploy = _read(OPS_ROOT / "deploy.sh")

    assert '[[ "$(hostname -s)" == "pc2" ]]' in deploy
    assert "192\\.168\\.15\\.104" in deploy
    assert "^PROFILE=pc2$" in deploy
    assert "^EXPECTED_BOOT_MODE=uefi$" in deploy
    assert 'sudo -n true' in deploy
    assert '"$app_root/current"' in deploy
    assert '"$app_root/previous"' in deploy
    assert "wait_for_health" in deploy
    assert "--skip-build" in deploy
    assert 'docker image inspect "$app_image"' in deploy
    assert 'docker image inspect "$browser_image"' in deploy
    assert "--browser-only" in deploy
    assert "wait_for_browser_health" in deploy
    assert "up -d --no-deps pc2-browser-solver" in deploy
    assert "Dockerfile.auth-recovery" in deploy
    assert "docker system prune" not in deploy
    assert "rm -rf" not in deploy


def test_pc2_auth_recovery_browser_hotfix_only_overlays_recovery_client() -> None:
    dockerfile = _read(OPS_ROOT / "Dockerfile.auth-recovery")

    copy_lines = [line.strip() for line in dockerfile.splitlines() if line.startswith("COPY ")]
    assert copy_lines == [
        "COPY tools/internal_api_http.py /app/tools/internal_api_http.py",
        "COPY tools/pc2_auth_recovery.py /app/tools/pc2_auth_recovery.py",
        "COPY tools/pc2_local_solver.py /app/tools/pc2_local_solver.py",
    ]


def test_shell_scripts_pass_bash_syntax_check() -> None:
    bash_executable = shutil.which("bash")
    git_executable = shutil.which("git")
    if git_executable:
        git_bash = Path(git_executable).resolve().parents[1] / "bin" / "bash.exe"
        if git_bash.is_file():
            bash_executable = str(git_bash)
    assert bash_executable, "bash is required for the PC2 deployment contract test"
    for path in (OPS_ROOT / "deploy.sh", OPS_ROOT / "start-browser-solver.sh"):
        result = subprocess.run(
            [bash_executable, "-n"],
            check=False,
            capture_output=True,
            input=_read(path).encode("utf-8"),
        )
        assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
