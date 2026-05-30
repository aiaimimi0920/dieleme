from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import browserless_seed_probe

DEFAULT_API_BASE = "http://127.0.0.1:8001/api"


def classify_probe_summary(summary: dict[str, Any]) -> dict[str, str | None]:
    if summary.get("body_has_login"):
        return {"decision": "browser_fallback_required", "reason": "login_required"}
    if summary.get("body_has_challenge") or summary.get("body_has_punish") or summary.get("body_has_captcha"):
        return {"decision": "browser_fallback_required", "reason": "challenge_detected"}
    if not summary.get("has_script"):
        return {"decision": "browser_fallback_required", "reason": "missing_list_payload"}
    return {"decision": "browserless_success", "reason": None}


def build_progress_payload(source_page_url: str, *, item_count: int | None) -> dict[str, Any]:
    parsed = urlparse(source_page_url)
    page_values = parse_qs(parsed.query).get("page", ["1"])
    try:
        page_num = int(page_values[0])
    except ValueError:
        page_num = 1
    has_items = bool(item_count)
    return {
        "url": source_page_url,
        "has_next": has_items,
        "is_empty": not has_items,
        "page_num": page_num,
        "zero_bid_detected": False,
    }


def submit_seed_results(
    *,
    api_base: str,
    batch_payload: dict[str, Any],
    progress_payload: dict[str, Any],
    api_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    http = api_session or requests.Session()
    batch_response = http.post(
        f"{api_base.rstrip('/')}/collection/seeds/batch",
        json=batch_payload,
        timeout=timeout,
    )
    progress_response = http.post(
        f"{api_base.rstrip('/')}/collection/seeds/report_progress",
        json=progress_payload,
        timeout=timeout,
    )
    return {
        "batch": batch_response.json(),
        "progress": progress_response.json(),
    }


def run_hybrid_collection(
    url: str,
    *,
    cookies: Iterable[dict[str, Any]],
    browserless_session: requests.Session | Any | None = None,
    submit: bool = False,
    api_base: str = DEFAULT_API_BASE,
    api_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    http = browserless_session or browserless_seed_probe.build_session_from_playwright_cookies(cookies)
    response = http.get(
        url,
        headers={
            "User-Agent": browserless_seed_probe.DEFAULT_USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://sf.taobao.com/",
        },
        timeout=timeout,
        allow_redirects=True,
    )
    summary = browserless_seed_probe.summarize_list_page(response.text, final_url=response.url)
    summary.update({"status": response.status_code, "final_url": response.url})
    decision = classify_probe_summary(summary)
    result: dict[str, Any] = {
        "decision": decision["decision"],
        "reason": decision["reason"],
        "probe_summary": summary,
    }
    if decision["decision"] != "browserless_success":
        return result

    payload = browserless_seed_probe.extract_list_payload(response.text)
    batch_payload = browserless_seed_probe.build_userscript_like_batch_payload(
        payload or {"data": []},
        source_page_url=response.url,
    )
    progress_payload = build_progress_payload(response.url, item_count=summary.get("item_count"))
    result["batch_payload"] = batch_payload
    result["progress_payload"] = progress_payload
    if submit:
        result["submit_result"] = submit_seed_results(
            api_base=api_base,
            batch_payload=batch_payload,
            progress_payload=progress_payload,
            api_session=api_session,
            timeout=timeout,
        )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run hybrid seed collection: browserless first, browser fallback on challenge/login.")
    parser.add_argument("--cdp-endpoint", default=browserless_seed_probe.DEFAULT_CDP_ENDPOINT)
    parser.add_argument("--url", default=browserless_seed_probe.DEFAULT_TARGET_URL)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    args = parser.parse_args(argv)

    cookies = browserless_seed_probe.export_cdp_cookies(args.cdp_endpoint)
    result = run_hybrid_collection(
        args.url,
        cookies=cookies,
        submit=args.submit,
        api_base=args.api_base,
    )
    result["cookie_count"] = len(cookies)
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
