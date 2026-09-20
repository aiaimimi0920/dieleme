import json
from pathlib import Path
import subprocess
import sys

import pytest

from tools import pc1_desktop_auth as desktop
from tools.desktop_runtime_config import ALLOWED_KEYS, CONFIG_NAME, load_runtime_environment
from tools.pc1_desktop_recovery import RecoveryClient, RecoveryError


def write_config(root, values):
    (root / CONFIG_NAME).write_text(json.dumps({"version": 1, "environment": values}), encoding="utf-8")


def test_direct_bundle_loads_non_secret_paths_without_launcher_environment(tmp_path):
    write_config(tmp_path, {"FAPAI_DATA_ROOT_HOST": "shared", "FAPAI_AUTH_LOCAL_CDP_PORT": "9227"})
    environment = load_runtime_environment(tmp_path, {})
    assert environment["FAPAI_DATA_ROOT_HOST"] == str(tmp_path / "shared")
    assert environment["FAPAI_AUTH_LOCAL_CDP_PORT"] == "9227"
    assert load_runtime_environment(tmp_path, {"FAPAI_DATA_ROOT_HOST": "explicit"})["FAPAI_DATA_ROOT_HOST"] == "explicit"


def test_no_config_keeps_project_local_fallback_and_never_searches_parent(tmp_path):
    write_config(tmp_path, {"FAPAI_DATA_ROOT_HOST": "other-install"})
    bundle = tmp_path / "child"
    bundle.mkdir()
    assert load_runtime_environment(bundle, {}) == {}


@pytest.mark.parametrize("raw", [
    "not JSON", json.dumps({"version": 2, "environment": {}}),
    json.dumps({"version": 1, "environment": {"OPENAI_API_KEY": "never persist secrets"}}),
    json.dumps({"version": 1, "environment": {"FAPAI_AUTH_LOCAL_CDP_PORT": "1"}}),
    json.dumps({"version": 1, "environment": {"FAPAI_DATA_ROOT_HOST": "bad\npath"}}),
    " " * 16385,
])
def test_invalid_configuration_fails_closed_without_echoing_values(tmp_path, raw):
    (tmp_path / CONFIG_NAME).write_text(raw, encoding="utf-8")
    with pytest.raises(RecoveryError, match="^runtime_config_invalid$"):
        load_runtime_environment(tmp_path, {})


def test_main_direct_launch_uses_configured_token_and_cookie_paths(tmp_path, monkeypatch, capsys):
    for key in ALLOWED_KEYS | {"FAPAI_API_BASE_URL"}:
        monkeypatch.delenv(key, raising=False)
    token = tmp_path / "credential.token"
    token.write_text("synthetic-test-token-00001", encoding="utf-8")
    write_config(tmp_path, {
        "FAPAI_COLLECTOR_API_BASE": "http://127.0.0.1:18001",
        "FAPAI_DATA_ROOT_HOST": "shared", "FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE": str(token),
        "FAPAI_COOKIE_SNAPSHOT": "shared/custom-cookie.json", "FAPAI_AUTH_LOCAL_CDP_PORT": "9227",
    })
    monkeypatch.setattr(desktop, "ROOT", tmp_path)
    def complete(client, **kwargs):
        assert client.url == "http://127.0.0.1:18001/api/collection/auth/recovery"
        assert client.headers["X-Fapai-Recovery-Token"] == "synthetic-test-token-00001"
        assert kwargs["endpoint"] == "http://127.0.0.1:9227"
        assert kwargs["output_path"] == tmp_path / "shared" / "custom-cookie.json"
        return {"phase": "pending_pc2"}
    monkeypatch.setattr(desktop, "complete_challenge", complete)
    assert desktop.main(["--action", "complete", "--api-base", "http://127.0.0.1:18001"]) == 0
    output = capsys.readouterr().out
    assert '"phase": "pending_pc2"' in output
    assert "synthetic-test-token" not in output
    with pytest.raises(RecoveryError, match="api_not_configured"):
        RecoveryClient("https://untrusted.invalid", tmp_path, environment=load_runtime_environment(tmp_path, {}))


def test_open_uses_persisted_browser_profile_without_mutating_process_env(tmp_path, monkeypatch, capsys):
    for key in ALLOWED_KEYS:
        monkeypatch.delenv(key, raising=False)
    write_config(tmp_path, {"FAPAI_AUTH_BROWSER_PROFILE_DIR": "human-profile", "FAPAI_AUTH_LOCAL_CDP_PORT": "9333"})
    monkeypatch.setattr(desktop, "ROOT", tmp_path)
    def open_page(url, endpoint, port, data_root, *, environment):
        assert environment["FAPAI_AUTH_BROWSER_PROFILE_DIR"] == str(tmp_path / "human-profile")
        assert port == 9333 and data_root == tmp_path / "FPFData"
        return {"phase": "ready_for_human"}
    monkeypatch.setattr(desktop, "open_challenge", open_page)
    assert desktop.main(["--action", "open", "--api-base", "http://127.0.0.1"]) == 0
    assert '"phase": "ready_for_human"' in capsys.readouterr().out


@pytest.mark.skipif(sys.platform != "win32", reason="Windows installer")
def test_config_writer_round_trip_utf8_and_no_secret_values(tmp_path):
    script = Path(__file__).resolve().parents[2] / "scripts" / "write-collector-desktop-runtime-config.ps1"
    args = ["powershell.exe", "-NoProfile", "-NonInteractive", "-File", str(script),
            "-InstallRoot", str(tmp_path), "-DataRoot", str(tmp_path / "shared"),
            "-AuthBrowserProfileDir", str(tmp_path / "profile")]
    for _ in range(2):
        result = subprocess.run(args, capture_output=True, timeout=20)
        assert result.returncode == 0, result.stderr.decode(errors="replace")
        raw = (tmp_path / CONFIG_NAME).read_bytes()
        assert not raw.startswith(b"\xef\xbb\xbf")
        environment = load_runtime_environment(tmp_path, {})
        assert environment["FAPAI_DATA_ROOT_HOST"] == str(tmp_path / "shared")
        assert environment["FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE"].endswith("nas-auth-recovery.token")
    assert not list(tmp_path.glob(".desktop-config-*.tmp"))
