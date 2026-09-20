"""Challenge redirects must not erase the identity of the blocked list task."""
from types import SimpleNamespace

import pytest

from tools import live_batch_smoke as collector

TARGET = "https://sf.taobao.com/list/200782003__2.htm?location_code=510302&st_param=3&auction_start_seg=-1&page=50"
REDIRECT = "https://sf.taobao.com/list/200782003__2.htm/_____tmd_____/punish?x5secdata=test"
HTML = "<html><body>_____tmd_____/punish</body></html>"


@pytest.mark.parametrize("browser_fallback", [False, True])
def test_list_challenge_reports_original_region_sort_and_page(monkeypatch, browser_fallback):
    reports = []
    monkeypatch.setenv("FAPAI_LIST_BROWSER_FALLBACK", "1" if browser_fallback else "0")
    monkeypatch.setattr(collector, "request_captcha_solver", lambda endpoint, target, **kw: reports.append(target))
    monkeypatch.setattr(collector, "fetch_browser_list_page", lambda *_: (HTML, REDIRECT))
    monkeypatch.setattr(collector, "list_browser_recovery_max_attempts", lambda: 1)
    response = SimpleNamespace(text=HTML, url=REDIRECT, status_code=200, raise_for_status=lambda: None)
    http = SimpleNamespace(get=lambda *a, **kw: response)
    html, final_url, _, _ = collector.fetch_list_page(
        http, cdp_endpoint="http://127.0.0.1:9223", target_url=TARGET,
        user_agent="test", solver_enabled=True, api_base_url="http://fixture/api")
    assert html == HTML and final_url == REDIRECT
    assert reports == [TARGET]
