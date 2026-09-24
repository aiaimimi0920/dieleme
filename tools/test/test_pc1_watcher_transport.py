"""Exercise the real PC1 PowerShell/stdio/TLS boundary without opening a browser."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tools.pc1_desktop_recovery import RecoveryError
from tools.pc1_recovery_request import execute
from tools.test import test_collection_control_https as tls_fixtures

control = tls_fixtures.control
ROOT = Path(__file__).resolve().parents[2]
WINDOWS = pytest.mark.skipif(sys.platform != "win32", reason="PowerShell watcher")


def run_process(arguments, root, *, payload=None):
    env = {
        key: value for key, value in os.environ.items() if not key.startswith("FAPAI_")
    }
    env["FAPAI_DESKTOP_PYTHON_PATH"] = sys.executable
    return subprocess.run(
        arguments,
        input=None if payload is None else json.dumps(payload),
        text=True,
        capture_output=True,
        cwd=root,
        env=env,
        timeout=35,
        check=False,
    )


def bridge(payload, root):
    return run_process(
        [sys.executable, "-I", str(ROOT / "tools/pc1_recovery_request.py")],
        root,
        payload=payload,
    )


def request_config(control):
    origin, ca, _, root = control
    token = root / "pc1 recovery.token"
    token.write_text("synthetic-pc1-token-" + "r" * 32, encoding="utf-8")
    return {
        "api_base": origin,
        "ca_file": str(ca),
        "data_root": str(root),
        "token_path": str(token),
        "action": "status",
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"api_base": "http://198.51.100.42:8001"},
        {"api_base": ""},
        {"action": "../../other"},
        {"action": "claim", "body": []},
        {"action": "status", "body": {"side_effect": True}},
        {"headers": {"X-Fapai-Recovery-Token": "untrusted"}},
    ],
)
def test_invalid_request_is_rejected_before_reading_credentials(monkeypatch, overrides):
    monkeypatch.setattr(
        Path, "read_text", lambda *_, **__: pytest.fail("credential read")
    )
    with pytest.raises(RecoveryError):
        execute(
            {
                "api_base": "https://crow.example",
                "action": "status",
                "data_root": ".",
                **overrides,
            }
        )


def test_stdio_bridge_preserves_metadata_and_reloads_rotated_token(
    control, monkeypatch
):
    payload = request_config(control)
    received = []

    def dispatch(_root, method, path, headers, body):
        received.append((method, path, headers.get("X-Fapai-Recovery-Token"), body))
        return {"ready": True} if path == "/api/status" else {"ok": True}

    monkeypatch.setattr("tools.collection_control_https.dispatch", dispatch)
    root = Path(payload["data_root"])
    token = Path(payload["token_path"])
    first_token = token.read_text(encoding="utf-8")
    assert bridge(payload, root).returncode == 0
    token.write_text("rotated-pc1-fixture-" + "s" * 32, encoding="utf-8")
    body = {"recovery_id": "fixture", "sha256": "a" * 64, "cookie_count": 2}
    result = bridge({**payload, "action": "snapshot_ready", "body": body}, root)
    assert result.returncode == 0, result.stderr
    status = bridge({**payload, "action": "public_status"}, root)
    assert status.returncode == 0 and json.loads(status.stdout) == {"ready": True}
    assert received == [
        ("GET", "/api/collection/auth/recovery", first_token, {}),
        (
            "POST",
            "/api/collection/auth/recovery/snapshot_ready",
            token.read_text(encoding="utf-8"),
            body,
        ),
        ("GET", "/api/status", token.read_text(encoding="utf-8"), {}),
    ]
    assert first_token not in result.stdout + result.stderr


def test_stdio_bridge_rejects_untrusted_tls_and_redirects(control, monkeypatch):
    payload = request_config(control)
    root = Path(payload["data_root"])
    received = []

    def redirect(handler):
        received.append(handler.path)
        handler.send_response(302)
        handler.send_header("Location", payload["api_base"] + "/api/leaked")
        handler.send_header("Content-Length", "0")
        handler.end_headers()

    monkeypatch.setattr("tools.collection_control_https.Handler.do_GET", redirect)
    result = bridge({**payload, "ca_file": ""}, root)
    assert (
        result.returncode == 1
        and json.loads(result.stdout)["code"] == "api_unavailable"
    )
    assert received == []
    result = bridge(payload, root)
    assert (
        result.returncode == 1
        and json.loads(result.stdout)["code"] == "redirect_refused"
    )
    assert received == ["/api/collection/auth/recovery"]


@WINDOWS
def test_watcher_tls_roundtrip_exits_without_opening_auth_browser(control, monkeypatch):
    payload = request_config(control)
    received = []

    def dispatch(_root, method, path, headers, body):
        received.append((method, path, headers.get("X-Fapai-Recovery-Token")))
        return {"ok": True, "auth_recovery": {"active": None}}

    monkeypatch.setattr("tools.collection_control_https.dispatch", dispatch)
    root = Path(payload["data_root"])
    result = run_process(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(ROOT / "scripts/watch-pc1-nas-auth-recovery.ps1"),
            "-ApiBase",
            payload["api_base"],
            "-DataRoot",
            str(root),
            "-TokenPath",
            payload["token_path"],
            "-ApiCaFile",
            payload["ca_file"],
            "-BrowserPath",
            str(root / "browser-must-not-start.exe"),
        ],
        root,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert received == [
        (
            "GET",
            "/api/collection/auth/recovery",
            Path(payload["token_path"]).read_text(encoding="utf-8"),
        )
    ]
    assert not (root / "runtime/pc1-nas-auth-recovery-state.json").exists()


@WINDOWS
@pytest.mark.parametrize(
    "script",
    ["watch-pc1-nas-auth-recovery.ps1", "register-pc1-nas-auth-recovery-task.ps1"],
)
def test_pc1_scripts_reject_remote_plaintext_before_python_or_scheduler(
    tmp_path, script
):
    target = str(ROOT / "scripts" / script).replace("'", "''")
    command = (
        "function Register-ScheduledTask { throw 'SchedulerReached' }; "
        f"& '{target}' -ApiBase 'http://198.51.100.42:8001' -Python 'missing-python.exe'"
    )
    result = run_process(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        tmp_path,
    )
    assert result.returncode != 0
    assert "require HTTPS" in result.stderr
    assert "SchedulerReached" not in result.stderr
    assert "missing-python.exe" not in result.stderr
