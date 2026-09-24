"""Reject unsafe installation configuration before replacing app or config bytes."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows installer")
ROOT = Path(__file__).resolve().parents[2]


def powershell(script, *arguments):
    env = {**os.environ, "FAPAI_DESKTOP_PYTHON_PATH": sys.executable}
    env.pop("FAPAI_COLLECTOR_API_BASE", None)
    return subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-File",
            str(ROOT / "scripts" / script),
            *map(str, arguments),
        ],
        capture_output=True,
        text=True,
        timeout=20,
        env=env,
        check=False,
    )


@pytest.mark.parametrize(
    "origin",
    [
        "http://198.51.100.42:8001",
        "http://localhost.evil.example",
        "https://user:secret@crow.example",
        "https://crow.example/api/../",
    ],
)
def test_writer_rejects_unsafe_api_and_preserves_previous_configuration(
    tmp_path, origin
):
    config = tmp_path / "crow-desktop.runtime.json"
    original = b'{"version":1,"environment":{"FAPAI_COLLECTOR_API_BASE":"https://old.example"}}'
    config.write_bytes(original)
    result = powershell(
        "write-collector-desktop-runtime-config.ps1",
        "-InstallRoot",
        tmp_path,
        "-DataRoot",
        tmp_path / "data",
        "-ApiBase",
        origin,
    )
    assert result.returncode != 0
    assert config.read_bytes() == original
    assert not list(tmp_path.glob(".desktop-config-*"))


@pytest.mark.parametrize(
    "origin",
    ["https://crow.example:8443/api", "http://127.0.0.1:18001", "http://[::1]:18001"],
)
def test_writer_keeps_explicit_secure_origin_and_ca_on_reconfiguration(
    tmp_path, origin
):
    common = ("-InstallRoot", tmp_path, "-DataRoot", tmp_path / "data")
    ca_file = tmp_path / "api-ca.pem"
    ca_file.write_text(
        "Synthetic CA path fixture; no TLS connection.\n", encoding="utf-8"
    )
    first = powershell(
        "write-collector-desktop-runtime-config.ps1",
        *common,
        "-ApiBase",
        origin,
        "-ApiCaFile",
        ca_file,
    )
    assert first.returncode == 0, first.stderr
    config = tmp_path / "crow-desktop.runtime.json"
    before = json.loads(config.read_text(encoding="utf-8"))["environment"]
    second = powershell("write-collector-desktop-runtime-config.ps1", *common)
    assert second.returncode == 0, second.stderr
    after = json.loads(config.read_text(encoding="utf-8"))["environment"]
    assert after["FAPAI_COLLECTOR_API_BASE"] == before["FAPAI_COLLECTOR_API_BASE"]
    assert after["FAPAI_API_CA_FILE"] == str(tmp_path / "api-ca.pem")


def test_writer_rejects_missing_ca_and_preserves_previous_configuration(tmp_path):
    config = tmp_path / "crow-desktop.runtime.json"
    original = b'{"version":1,"environment":{"FAPAI_COLLECTOR_API_BASE":"https://old.example"}}'
    config.write_bytes(original)
    result = powershell(
        "write-collector-desktop-runtime-config.ps1",
        "-InstallRoot",
        tmp_path,
        "-DataRoot",
        tmp_path / "data",
        "-ApiBase",
        "https://crow.example",
        "-ApiCaFile",
        tmp_path / "missing-ca.pem",
    )
    assert result.returncode != 0
    assert "Collection API CA file is unavailable" in result.stderr
    assert config.read_bytes() == original
    assert not list(tmp_path.glob(".desktop-config-*"))


@pytest.mark.parametrize("corrupt", [False, True])
def test_deployment_rejects_unsafe_config_before_build_or_activation(tmp_path, corrupt):
    config = tmp_path / "crow-desktop.runtime.json"
    original = b"broken" if corrupt else b'{"version":1,"environment":{}}'
    config.write_bytes(original)
    executable = tmp_path / "fapaifang_collector_desktop.exe"
    executable.write_bytes(b"existing application must not be changed")
    build = tmp_path / "not-built"
    result = powershell(
        "deploy-collector-desktop-local.ps1",
        "-InstallRoot",
        tmp_path,
        "-BuildTargetRoot",
        build,
        "-ApiBase",
        "http://198.51.100.42:8001",
        "-SkipBuild",
        "-SkipLaunch",
        "-SkipShortcut",
    )
    assert result.returncode != 0
    assert ("configuration is invalid" if corrupt else "require HTTPS") in result.stderr
    assert config.read_bytes() == original
    assert executable.read_bytes() == b"existing application must not be changed"
    assert not (tmp_path / "backup").exists()
    assert not build.exists()
