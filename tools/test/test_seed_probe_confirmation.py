"""List access and the coordinator's stage receipt must both permit resuming."""
from types import SimpleNamespace

import pytest

from tools import browserless_seed_probe, seed_collector
from tools.pc2_seed_auth_probe import seed_payload_authenticated

BASE = "https://sf.taobao.com/list/50025969__2.htm"
TARGET = BASE + "?location_code=510302&st_param=5&page=18"
EMPTY_LIST = '<script id="sf-item-list-data">{"data":[]}</script>'
CONFIRMED = {"ok": True, "auth_state_confirmed": True, "scope": "seed", "scope_paused": False}


def pause_state(request=None):
    return {"paused": True, "scope": "seed", "reason": "captcha_solver_manual_required",
            "captcha_solver": {"manual_required": True, "challenge_id": "seed-challenge",
                               "last_request": request or {"target_url": TARGET}}}


def run_probe(tmp_path, monkeypatch, receipt, *, html=EMPTY_LIST, final_url=TARGET, method="http_cookie"):
    config = seed_collector.SeedCollectorConfig(
        job_key="seed-test", province="", city="", district="", location_code="510302",
        category="50025969", sort_specs=(), max_page=20, cdp_endpoint="http://browser.test:9224",
        output_dir=tmp_path, worker_id="seed-test", api_base_url="http://api.test/api")
    claims, completions = [], []
    repository = SimpleNamespace(seed_queue_counts=lambda: {},
                                 claim_seed_scan_page=lambda *a, **kw: claims.append(kw))
    monkeypatch.setattr(seed_collector, "_collection_pause_state_with_retry", lambda _: pause_state())
    monkeypatch.setattr(seed_collector, "resolve_runtime_user_agent", lambda _: "test-agent")
    monkeypatch.setattr(seed_collector, "fetch_list_page", lambda *a, **kw: (html, final_url, 200, method))
    monkeypatch.setattr(seed_collector, "_notify_auth_probe_passed",
                        lambda *a, **kw: completions.append(a) or receipt)
    result = seed_collector.run_seed_collector_once(
        config, repository=repository, http_session=object(),
        browserless_seed_probe=browserless_seed_probe, ensure_jobs=False)
    return result, claims, completions


@pytest.mark.parametrize("receipt", [
    {"ok": False, "stale_challenge": True},
    {"ok": True, "auth_state_confirmed": False, "auth_confirmation_pending": True},
    {**CONFIRMED, "scope": "detail"},
    {**CONFIRMED, "scope_paused": True},
    {**CONFIRMED, "scope_manual_required": True},
    {"ok": True},
])
def test_worker_does_not_claim_after_rejected_or_pending_completion(tmp_path, monkeypatch, receipt):
    result, claims, completions = run_probe(tmp_path, monkeypatch, receipt)
    assert result["decision"] == "seed_collection_paused"
    assert result["auth_probe"]["authenticated"] is False
    assert completions and not claims


@pytest.mark.parametrize("html, final_url", [
    ("<html>Service unavailable</html>", TARGET),
    ('<script id="sf-item-list-data">{}</script>', TARGET),
    (EMPTY_LIST + "请完成验证", TARGET),
    (EMPTY_LIST, BASE),
    (EMPTY_LIST, TARGET.replace("page=18", "page=19")),
    (EMPTY_LIST, "https://login.taobao.com/"),
])
def test_http_probe_requires_list_payload_and_current_target(tmp_path, monkeypatch, html, final_url):
    result, claims, completions = run_probe(tmp_path, monkeypatch, CONFIRMED, html=html, final_url=final_url)
    assert result["decision"] == "seed_collection_paused"
    assert not claims and not completions


def test_empty_list_can_resume_seed_while_detail_is_paused(tmp_path, monkeypatch):
    reordered = BASE + "?page=18&location_code=510302&st_param=5&__captcha_solver_bg=1"
    result, claims, completions = run_probe(tmp_path, monkeypatch, {**CONFIRMED, "paused": True}, final_url=reordered)
    assert result["decision"] == "seed_scan_queue_empty"
    assert result["auth_probe"]["authenticated"] is True
    assert len(claims) == len(completions) == 1
    assert seed_payload_authenticated(EMPTY_LIST, reordered, TARGET)


def test_probe_uses_original_challenge_target_and_never_invents_one():
    state = pause_state({"target_url": "https://login.taobao.com/", "challenge_target_url": TARGET})
    assert seed_collector._pause_state_seed_probe_target_url(state, allow_default=True) == TARGET + "&__captcha_solver_bg=1"
    assert seed_collector._pause_state_seed_probe_target_url(
        pause_state({"target_url": "https://login.taobao.com/"}), allow_default=True) == ""
