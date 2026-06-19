from __future__ import annotations

import json

from tools import taobao_cookie_profile_diff


def test_main_emits_safe_cookie_profile_diff_report(monkeypatch, capsys) -> None:
    cookies_by_endpoint = {
        "http://127.0.0.1:9239": [
            {"name": "cookie2", "value": "healthy-cookie2", "domain": ".taobao.com", "path": "/"},
            {"name": "tfstk", "value": "healthy-tfstk", "domain": ".taobao.com", "path": "/"},
        ],
        "http://127.0.0.1:9236": [
            {"name": "cookie2", "value": "blocked-cookie2", "domain": ".taobao.com", "path": "/"},
            {"name": "XSRF-TOKEN", "value": "blocked-xsrf", "domain": "login.taobao.com", "path": "/"},
        ],
    }

    health_by_endpoint = {
        "http://127.0.0.1:9239": {
            "status": "healthy_list_payload",
            "healthy": True,
            "final_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
            "probe_transport": "cookie_http",
            "cookie_summary": {
                "shape_fingerprint": "shape-healthy",
                "value_fingerprint": "value-healthy",
            },
        },
        "http://127.0.0.1:9236": {
            "status": "punish_page",
            "healthy": False,
            "final_url": "https://login.taobao.com/havanaone/login/login.htm?uuid=abc",
            "probe_transport": "cookie_http",
            "cookie_summary": {
                "shape_fingerprint": "shape-blocked",
                "value_fingerprint": "value-blocked",
            },
        },
    }

    monkeypatch.setattr(
        taobao_cookie_profile_diff.browserless_seed_probe,
        "export_cdp_cookies",
        lambda endpoint: cookies_by_endpoint[endpoint],
    )
    monkeypatch.setattr(
        taobao_cookie_profile_diff.taobao_login_health,
        "check_taobao_health",
        lambda **kwargs: health_by_endpoint[kwargs["cdp_endpoint"]],
    )

    exit_code = taobao_cookie_profile_diff.main(
        [
            "--left-cdp-endpoint",
            "http://127.0.0.1:9239",
            "--right-cdp-endpoint",
            "http://127.0.0.1:9236",
            "--left-label",
            "healthy-profile",
            "--right-label",
            "blocked-profile",
            "--check-url",
            "https://sf.taobao.com/list/50025969__2.htm?page=1",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["left"]["label"] == "healthy-profile"
    assert payload["left"]["health"]["status"] == "healthy_list_payload"
    assert payload["right"]["label"] == "blocked-profile"
    assert payload["right"]["health"]["status"] == "punish_page"
    assert payload["diff"]["added_names_on_right"] == ["XSRF-TOKEN"]
    assert payload["diff"]["removed_names_on_right"] == ["tfstk"]
    assert payload["diff"]["added_keys_on_right"] == ["XSRF-TOKEN|login.taobao.com|/"]
    assert payload["diff"]["removed_keys_on_right"] == ["tfstk|.taobao.com|/"]
