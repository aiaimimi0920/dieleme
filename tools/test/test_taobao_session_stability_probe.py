from __future__ import annotations

import json

from tools import taobao_session_stability_probe


def test_build_stability_summary_detects_status_flips_without_cookie_fingerprint_changes() -> None:
    summary = taobao_session_stability_probe.build_stability_summary(
        [
            {
                "status": "healthy_list_payload",
                "healthy": True,
                "probe_transport": "cookie_http",
                "final_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "cookie_summary": {
                    "shape_fingerprint": "shape-1",
                    "value_fingerprint": "value-1",
                },
            },
            {
                "status": "punish_page",
                "healthy": False,
                "probe_transport": "cookie_http",
                "final_url": "https://login.taobao.com/havanaone/login/login.htm?uuid=abc",
                "cookie_summary": {
                    "shape_fingerprint": "shape-1",
                    "value_fingerprint": "value-1",
                },
            },
        ]
    )

    assert summary["attempt_count"] == 2
    assert summary["status_changed"] is True
    assert summary["healthy_changed"] is True
    assert summary["probe_transport_changed"] is False
    assert summary["cookie_shape_changed"] is False
    assert summary["cookie_value_changed"] is False
    assert summary["distinct_status_count"] == 2
    assert summary["suspected_driver"] == "non_cookie_state_or_server_risk_state"


def test_build_stability_summary_detects_server_risk_token_rotation_without_cookie_change() -> None:
    summary = taobao_session_stability_probe.build_stability_summary(
        [
            {
                "status": "punish_page",
                "healthy": False,
                "probe_transport": "cookie_http",
                "final_url": "https://login.taobao.com/havanaone/login/login.htm?uuid=abc",
                "cookie_summary": {
                    "shape_fingerprint": "shape-1",
                    "value_fingerprint": "value-1",
                },
            },
            {
                "status": "punish_page",
                "healthy": False,
                "probe_transport": "cookie_http",
                "final_url": "https://login.taobao.com/havanaone/login/login.htm?uuid=def",
                "cookie_summary": {
                    "shape_fingerprint": "shape-1",
                    "value_fingerprint": "value-1",
                },
            },
        ]
    )

    assert summary["status_changed"] is False
    assert summary["cookie_value_changed"] is False
    assert summary["final_url_changed"] is True
    assert summary["final_host_changed"] is False
    assert summary["final_path_changed"] is False
    assert summary["final_url_query_changed"] is True
    assert summary["suspected_driver"] == "server_risk_tokens_rotating_without_cookie_change"


def test_main_emits_repeated_stability_report(monkeypatch, capsys) -> None:
    calls: list[str] = []

    def _check_taobao_health(**kwargs):
        calls.append(str(kwargs["check_url"]))
        attempt = len(calls)
        if attempt == 1:
            return {
                "status": "healthy_list_payload",
                "healthy": True,
                "probe_transport": "cookie_http",
                "final_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "cookie_summary": {
                    "shape_fingerprint": "shape-1",
                    "value_fingerprint": "value-1",
                },
            }
        return {
            "status": "punish_page",
            "healthy": False,
            "probe_transport": "cookie_http",
            "final_url": "https://login.taobao.com/havanaone/login/login.htm?uuid=abc",
            "cookie_summary": {
                "shape_fingerprint": "shape-1",
                "value_fingerprint": "value-1",
            },
        }

    monkeypatch.setattr(taobao_session_stability_probe.taobao_login_health, "check_taobao_health", _check_taobao_health)
    monkeypatch.setattr(taobao_session_stability_probe.time, "sleep", lambda _seconds: None)

    exit_code = taobao_session_stability_probe.main(
        [
            "--cdp-endpoint",
            "http://127.0.0.1:9223",
            "--check-url",
            "https://sf.taobao.com/list/50025969__2.htm?page=1",
            "--attempts",
            "2",
            "--interval-seconds",
            "0",
        ]
    )

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert calls == [
        "https://sf.taobao.com/list/50025969__2.htm?page=1",
        "https://sf.taobao.com/list/50025969__2.htm?page=1",
    ]
    assert output["summary"]["status_changed"] is True
    assert output["summary"]["cookie_value_changed"] is False
    assert output["summary"]["suspected_driver"] == "non_cookie_state_or_server_risk_state"
    assert len(output["attempts"]) == 2
