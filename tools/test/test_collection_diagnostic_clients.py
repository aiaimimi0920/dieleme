"""Diagnostics must use current write contracts without contacting an installation."""

import runpy
from pathlib import Path

import pytest

from tools import internal_api_http


@pytest.mark.parametrize("script", ["check_server.py", "unpause_check.py"])
def test_diagnostics_use_authenticated_post_claims(monkeypatch, tmp_path, script):
    calls = []
    operator = tmp_path / "operator.token"
    operator.write_text("o" * 48, encoding="utf-8")
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text("test-ca", encoding="utf-8")
    monkeypatch.setenv("FAPAI_API_BASE_URL", "https://diagnostic.test/api")
    monkeypatch.setenv("FAPAI_API_CA_FILE", str(ca_file))
    monkeypatch.setenv("FAPAI_ENGINE_OPERATOR_TOKEN_FILE", str(operator))
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    def get(url, **options):
        assert url == "https://diagnostic.test/api/status"
        return {"paused": False}

    def post(url, body, **options):
        calls.append((url, body, options))
        return {"ok": True, "tasks": []}

    monkeypatch.setattr(internal_api_http, "fetch_json", get)
    monkeypatch.setattr(internal_api_http, "post_json", post)
    root = Path(__file__).resolve().parents[2]
    runpy.run_path(str(root / script), run_name="__main__")
    assert calls[-1][0] == "https://diagnostic.test/api/get_tasks"
    if script == "unpause_check.py":
        assert len(calls) == 2
        assert calls[0][0].endswith("/collection/control/resume")
        assert calls[0][2]["headers"] == {"X-FAPAI-Control-Token": "o" * 48}
    else:
        assert len(calls) == 1


def test_unpause_without_operator_never_sends_write(monkeypatch, tmp_path):
    ca_file = tmp_path / "ca.pem"
    ca_file.write_text("test-ca", encoding="utf-8")
    monkeypatch.setenv("FAPAI_API_BASE_URL", "https://diagnostic.test/api")
    monkeypatch.setenv("FAPAI_API_CA_FILE", str(ca_file))
    monkeypatch.delenv("FAPAI_ENGINE_OPERATOR_TOKEN_FILE", raising=False)
    monkeypatch.setattr(
        internal_api_http, "post_json", lambda *args, **kwargs: pytest.fail("write")
    )
    runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "unpause_check.py"),
        run_name="__main__",
    )
