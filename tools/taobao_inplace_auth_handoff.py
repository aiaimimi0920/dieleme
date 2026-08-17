from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import browserless_seed_probe, taobao_login_health


DETAIL_URL_RE = re.compile(r"https://sf-item\.taobao\.com/sf_item/(\d+)\.htm", re.IGNORECASE)
LIST_URL_RE = re.compile(r"https://sf\.taobao\.com/list/", re.IGNORECASE)
DEFAULT_LIST_SAMPLES = (
    "https://sf.taobao.com/list/50025969__2.htm",
    "https://sf.taobao.com/list/200782003__1.htm",
)


def _canonical_detail_url(url: str) -> str:
    match = DETAIL_URL_RE.search(str(url or ""))
    if match is None:
        return ""
    return f"https://sf-item.taobao.com/sf_item/{match.group(1)}.htm"


def _healthy_open_taobao_page(cdp_endpoint: str) -> dict[str, str]:
    # Inspect the already-open page through CDP. This deliberately does not
    # create, navigate, refresh, or close a browser target.
    for target in taobao_login_health.list_cdp_targets(cdp_endpoint):
        if str(target.get("type") or "") != "page":
            continue
        websocket_url = str(target.get("webSocketDebuggerUrl") or "").strip()
        if not websocket_url:
            continue
        try:
            evaluated = taobao_login_health.evaluate_cdp_expression(
                websocket_url,
                "JSON.stringify({html: document.documentElement.outerHTML, url: location.href})",
            )
            value = evaluated.get("result", {}).get("result", {}).get("value", "")
            snapshot = json.loads(value) if isinstance(value, str) else value
            html = str(snapshot.get("html") or "") if isinstance(snapshot, dict) else ""
            final_url = (
                str(snapshot.get("url") or target.get("url") or "")
                if isinstance(snapshot, dict)
                else str(target.get("url") or "")
            )
        except Exception:
            continue
        canonical_url = _canonical_detail_url(final_url)
        summary = browserless_seed_probe.summarize_list_page(html, final_url=final_url)
        if summary.get("body_has_challenge") or summary.get("body_has_login"):
            continue
        if canonical_url and len(str(html or "")) >= 1000:
            return {"kind": "detail", "html": html, "url": canonical_url}
        if LIST_URL_RE.search(final_url) and summary.get("has_script") is True:
            return {"kind": "list", "html": html, "url": str(final_url)}
    raise RuntimeError("No healthy open Taobao detail page is available in the PC1 browser.")


def _healthy_open_detail_page(cdp_endpoint: str) -> tuple[str, str]:
    page = _healthy_open_taobao_page(cdp_endpoint)
    if page.get("kind") != "detail":
        raise RuntimeError("No healthy open Taobao detail page is available in the PC1 browser.")
    return str(page.get("html") or ""), str(page.get("url") or "")


def _validate_cookie_http(
    cookies: list[dict[str, Any]],
    detail_url: str,
    *,
    user_agent: str,
    allow_list_only: bool = False,
) -> dict[str, Any]:
    session = browserless_seed_probe.build_session_from_playwright_cookies(cookies)
    list_healthy = 0
    for sample_url in DEFAULT_LIST_SAMPLES:
        summary = browserless_seed_probe.probe_seed_page(
            sample_url,
            cookies=cookies,
            session=session,
            timeout=30,
            user_agent=user_agent,
        )
        classification = taobao_login_health.classify_taobao_health(
            "",
            final_url=str(summary.get("final_url") or sample_url),
            list_summary=summary,
            payload_present=summary.get("has_script") is True,
        )
        if classification.get("healthy") is True:
            list_healthy += 1

    detail_http_healthy = False
    if detail_url:
        detail_response = session.get(
            detail_url,
            headers=browserless_seed_probe.build_navigation_headers(
                target_url=detail_url,
                user_agent=user_agent,
                referer_url="https://sf.taobao.com/",
            ),
            timeout=45,
            allow_redirects=True,
        )
        detail_summary = browserless_seed_probe.summarize_list_page(
            detail_response.text,
            final_url=detail_response.url,
        )
        detail_http_healthy = (
            detail_response.status_code < 400
            and not detail_summary.get("body_has_challenge")
            and not detail_summary.get("body_has_login")
        )
    list_only_mode = bool(allow_list_only and not detail_url)
    return {
        "list_healthy_samples": list_healthy,
        "detail_http_healthy": detail_http_healthy,
        "healthy": list_healthy > 0 and (detail_http_healthy or list_only_mode),
        "list_only_mode": list_only_mode,
    }


def complete_inplace_auth(*, cdp_endpoint: str, output_path: Path, allow_list_only: bool = False) -> dict[str, Any]:
    if allow_list_only:
        page = _healthy_open_taobao_page(cdp_endpoint)
        page_kind = str(page.get("kind") or "")
        detail_url = str(page.get("url") or "") if page_kind == "detail" else ""
    else:
        _html, detail_url = _healthy_open_detail_page(cdp_endpoint)
        page_kind = "detail"
    cookies = browserless_seed_probe.export_cdp_cookies(
        cdp_endpoint,
        origins=(
            "https://sf.taobao.com",
            "https://sf-item.taobao.com",
            "https://login.taobao.com",
        ),
    )
    if not cookies:
        raise RuntimeError("The PC1 browser did not expose any Taobao cookies.")
    user_agent = browserless_seed_probe.resolve_cdp_user_agent(cdp_endpoint)
    validator = _validate_cookie_http
    if len(inspect.signature(validator).parameters) <= 2:
        health = validator(cookies, detail_url)
    else:
        health = validator(
            cookies,
            detail_url,
            user_agent=user_agent,
            allow_list_only=allow_list_only,
        )
    if health.get("healthy") is not True:
        raise RuntimeError("The current detail page is open, but reusable list/detail Cookie health is not ready.")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_fd, candidate_name = tempfile.mkstemp(
        prefix="taobao-cookies.inplace-candidate.",
        suffix=".json",
        dir=str(output_path.parent),
    )
    os.close(candidate_fd)
    candidate_path = Path(candidate_name)
    try:
        browserless_seed_probe.write_cookie_snapshot(cookies, candidate_path)
        os.replace(candidate_path, output_path)
    finally:
        candidate_path.unlink(missing_ok=True)

    result = {
        "ok": True,
        "browser_process_preserved": True,
        "open_detail_dom_healthy": page_kind == "detail",
        "detail_http_healthy": health["detail_http_healthy"],
        "list_healthy_samples": health["list_healthy_samples"],
        "official_snapshot_promoted": True,
    }
    if health.get("list_only_mode") is True:
        result["open_list_dom_healthy"] = True
        result["list_only_mode"] = True
    return result


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Complete PC1 Taobao auth without restarting or navigating Chrome.")
    parser.add_argument("--cdp-endpoint", required=True)
    parser.add_argument("--output-path", type=Path, required=True)
    parser.add_argument("--allow-list-only", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        result = complete_inplace_auth(
            cdp_endpoint=args.cdp_endpoint,
            output_path=args.output_path,
            allow_list_only=bool(args.allow_list_only),
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "official_snapshot_promoted": False,
                    "error_type": type(exc).__name__,
                },
                ensure_ascii=False,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
