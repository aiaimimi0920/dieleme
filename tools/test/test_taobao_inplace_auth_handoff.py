from __future__ import annotations

from pathlib import Path

import pytest

from tools import taobao_inplace_auth_handoff


def _evaluated_page(html: str, url: str) -> dict[str, object]:
    import json

    return {
        "result": {
            "result": {
                "value": json.dumps({"html": html, "url": url}),
            }
        }
    }


def test_healthy_open_detail_page_inspects_existing_targets_without_navigation(monkeypatch) -> None:
    challenge_html = "<html>安全验证" + ("x" * 1200) + "</html>"
    healthy_html = "<html><body>法拍房详情" + ("x" * 1200) + "</body></html>"
    targets = [
        {"type": "page", "webSocketDebuggerUrl": "ws://challenge"},
        {"type": "page", "webSocketDebuggerUrl": "ws://healthy"},
    ]
    pages = {
        "ws://challenge": _evaluated_page(
            challenge_html,
            "https://sf-item.taobao.com/sf_item/111111111111.htm",
        ),
        "ws://healthy": _evaluated_page(
            healthy_html,
            "https://sf-item.taobao.com/sf_item/222222222222.htm?tracking=removed",
        ),
    }
    monkeypatch.setattr(taobao_inplace_auth_handoff.taobao_login_health, "list_cdp_targets", lambda _endpoint: targets)
    monkeypatch.setattr(
        taobao_inplace_auth_handoff.taobao_login_health,
        "evaluate_cdp_expression",
        lambda websocket_url, _expression: pages[websocket_url],
    )

    html, detail_url = taobao_inplace_auth_handoff._healthy_open_detail_page("http://127.0.0.1:9225")

    assert html == healthy_html
    assert detail_url == "https://sf-item.taobao.com/sf_item/222222222222.htm"


def test_complete_inplace_auth_promotes_snapshot_only_after_list_and_detail_health(monkeypatch, tmp_path: Path) -> None:
    output_path = tmp_path / "taobao-cookies.json"
    output_path.write_text("old-snapshot", encoding="utf-8")
    monkeypatch.setattr(
        taobao_inplace_auth_handoff,
        "_healthy_open_detail_page",
        lambda _endpoint: ("healthy html", "https://sf-item.taobao.com/sf_item/222222222222.htm"),
    )
    monkeypatch.setattr(
        taobao_inplace_auth_handoff.browserless_seed_probe,
        "export_cdp_cookies",
        lambda _endpoint, origins: [{"name": "session", "value": "redacted"}],
    )
    monkeypatch.setattr(
        taobao_inplace_auth_handoff,
        "_validate_cookie_http",
        lambda _cookies, _detail_url: {
            "healthy": True,
            "list_healthy_samples": 1,
            "detail_http_healthy": True,
        },
    )
    monkeypatch.setattr(
        taobao_inplace_auth_handoff.browserless_seed_probe,
        "write_cookie_snapshot",
        lambda _cookies, candidate: candidate.write_text("new-snapshot", encoding="utf-8"),
    )

    result = taobao_inplace_auth_handoff.complete_inplace_auth(
        cdp_endpoint="http://127.0.0.1:9225",
        output_path=output_path,
    )

    assert output_path.read_text(encoding="utf-8") == "new-snapshot"
    assert result == {
        "ok": True,
        "browser_process_preserved": True,
        "open_detail_dom_healthy": True,
        "detail_http_healthy": True,
        "list_healthy_samples": 1,
        "official_snapshot_promoted": True,
    }


def test_complete_inplace_auth_can_promote_snapshot_from_healthy_open_list_page(monkeypatch, tmp_path: Path) -> None:
    output_path = tmp_path / "taobao-cookies.json"
    output_path.write_text("old-snapshot", encoding="utf-8")
    monkeypatch.setattr(
        taobao_inplace_auth_handoff,
        "_healthy_open_taobao_page",
        lambda _endpoint: {
            "kind": "list",
            "html": "<html><script id='sf-item-list-data'>{}</script>" + ("x" * 1200) + "</html>",
            "url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
        },
    )
    monkeypatch.setattr(
        taobao_inplace_auth_handoff.browserless_seed_probe,
        "export_cdp_cookies",
        lambda _endpoint, origins: [{"name": "session", "value": "redacted"}],
    )
    monkeypatch.setattr(
        taobao_inplace_auth_handoff.browserless_seed_probe,
        "resolve_cdp_user_agent",
        lambda _endpoint: "real-ua",
    )
    monkeypatch.setattr(
        taobao_inplace_auth_handoff,
        "_validate_cookie_http",
        lambda _cookies, _detail_url, *, user_agent, allow_list_only: {
            "healthy": True,
            "list_healthy_samples": 2,
            "detail_http_healthy": False,
            "list_only_mode": allow_list_only and user_agent == "real-ua",
        },
    )
    monkeypatch.setattr(
        taobao_inplace_auth_handoff.browserless_seed_probe,
        "write_cookie_snapshot",
        lambda _cookies, candidate: candidate.write_text("new-snapshot", encoding="utf-8"),
    )

    result = taobao_inplace_auth_handoff.complete_inplace_auth(
        cdp_endpoint="http://127.0.0.1:9225",
        output_path=output_path,
        allow_list_only=True,
    )

    assert output_path.read_text(encoding="utf-8") == "new-snapshot"
    assert result == {
        "ok": True,
        "browser_process_preserved": True,
        "open_detail_dom_healthy": False,
        "detail_http_healthy": False,
        "list_healthy_samples": 2,
        "official_snapshot_promoted": True,
        "open_list_dom_healthy": True,
        "list_only_mode": True,
    }


def test_complete_inplace_auth_preserves_official_snapshot_when_cookie_reuse_fails(monkeypatch, tmp_path: Path) -> None:
    output_path = tmp_path / "taobao-cookies.json"
    output_path.write_text("old-snapshot", encoding="utf-8")
    monkeypatch.setattr(
        taobao_inplace_auth_handoff,
        "_healthy_open_detail_page",
        lambda _endpoint: ("healthy html", "https://sf-item.taobao.com/sf_item/222222222222.htm"),
    )
    monkeypatch.setattr(
        taobao_inplace_auth_handoff.browserless_seed_probe,
        "export_cdp_cookies",
        lambda _endpoint, origins: [{"name": "session", "value": "redacted"}],
    )
    monkeypatch.setattr(
        taobao_inplace_auth_handoff,
        "_validate_cookie_http",
        lambda _cookies, _detail_url: {
            "healthy": False,
            "list_healthy_samples": 1,
            "detail_http_healthy": False,
        },
    )

    with pytest.raises(RuntimeError, match="reusable list/detail Cookie health"):
        taobao_inplace_auth_handoff.complete_inplace_auth(
            cdp_endpoint="http://127.0.0.1:9225",
            output_path=output_path,
        )

    assert output_path.read_text(encoding="utf-8") == "old-snapshot"
    assert not list(tmp_path.glob("taobao-cookies.inplace-candidate.*.json"))


def test_inplace_auth_helper_has_no_browser_navigation_or_close_calls() -> None:
    source = Path(taobao_inplace_auth_handoff.__file__).read_text(encoding="utf-8")

    assert "/json/new" not in source
    assert "/json/close" not in source
    assert ".goto(" not in source
    assert ".reload(" not in source
    assert "live_batch_smoke" not in source
    assert "--allow-list-only" in source
