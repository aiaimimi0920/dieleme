from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import websocket

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.internal_api_http import post_json

DEFAULT_CDP_ENDPOINT = os.environ.get("FAPAI_CDP_ENDPOINT") or os.environ.get("LIVE_BATCH_SMOKE_CDP") or "http://127.0.0.1:9223"
DEFAULT_CHECK_URL = "https://sf.taobao.com/list/50025969__2.htm"
DEFAULT_WAIT_SECONDS = 180
DEFAULT_POLL_SECONDS = 5
DEFAULT_API_BASE_URL = os.environ.get("FAPAI_API_BASE_URL", "http://127.0.0.1:8001/api")
DEFAULT_CDP_CONNECT_TIMEOUT_MS = 120000
DEFAULT_CDP_PAGE_TARGET_LIMIT = 12
DEFAULT_CDP_WEBSOCKET_TIMEOUT_SECONDS = 20
AUTH_PAGE_REUSE_WINDOW_SECONDS = max(
    1.0,
    float(os.environ.get("FAPAI_AUTH_PAGE_REUSE_WINDOW_SECONDS", "300")),
)

# Multiple watchdog/worker processes can notice the same login redirect at the
# same time.  Serialise the find-or-create operation per CDP endpoint so two
# callers cannot both observe "no login tab" and create competing tabs.  The
# browser-side launcher has an equivalent process mutex; this lock closes the
# race for in-process health probes and Playwright fallbacks.
_AUTH_PAGE_LOCKS: dict[str, threading.Lock] = {}
_AUTH_PAGE_LOCKS_GUARD = threading.Lock()

HEALTHY_LIST_PAYLOAD = "healthy_list_payload"
PARTIAL_AVAILABLE = "partial_available"
ALL_SAMPLES_BLOCKED = "all_samples_blocked"
LOGIN_REQUIRED = "login_required"
CHALLENGE_REQUIRED = "challenge_required"
PUNISH_PAGE = "punish_page"
CAPTCHA_PAGE = "captcha_page"
CDP_UNREACHABLE = "cdp_unreachable"
UNKNOWN_BLOCKED = "unknown_blocked"
SENSITIVE_QUERY_KEYS = {
    "x5secdata",
    "x5sec",
    "cookie2",
    "sgcookie",
    "_tb_token_",
}
SENSITIVE_INLINE_PATTERNS = (
    re.compile(r"x5secdata\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
    re.compile(r"cookie2\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
    re.compile(r"sgcookie\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
    re.compile(r"_tb_token_\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
)

FetchPageFunc = Callable[[str, str], tuple[str, str]]
OpenPageFunc = Callable[[str, str], str]
ReportCaptchaFunc = Callable[[str, str, str], Mapping[str, object]]
SleepFunc = Callable[[float], None]

CAPTCHA_REPORT_CDP_ENV_NAMES = (
    "FAPAI_REPORT_CDP_ENDPOINT",
    "FAPAI_SOLVER_CDP_ENDPOINT",
)


def build_login_url(redirect_url: str) -> str:
    return f"https://login.taobao.com/member/login.jhtml?redirectURL={quote(redirect_url, safe='')}"


def build_captcha_solver_target_url(target_url: str) -> str:
    try:
        parsed = urlsplit(target_url)
    except ValueError:
        return target_url
    path = parsed.path
    while "//" in path:
        path = path.replace("//", "/")
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if not any(key == "__captcha_solver_bg" for key, _value in query):
        query.append(("__captcha_solver_bg", "1"))
    return urlunsplit((parsed.scheme, parsed.netloc, path, urlencode(query, doseq=True), parsed.fragment))


def build_captcha_worker_master_url() -> str:
    return "https://sf.taobao.com/?__captcha_worker_master=1"


def report_captcha_via_api(
    api_base_url: str,
    cdp_endpoint: str,
    target_url: str,
    *,
    manual_only: bool = False,
    scope: str | None = None,
) -> Mapping[str, object]:
    endpoint_suffix = "/report_manual_captcha" if manual_only else "/report_captcha"
    endpoint = api_base_url.rstrip("/") + endpoint_suffix
    report_cdp_endpoint = resolve_captcha_report_cdp_endpoint(cdp_endpoint)
    payload: dict[str, object] = {
        "url": target_url,
        "cdp_endpoint": report_cdp_endpoint,
        "timestamp": int(time.time() * 1000),
    }
    node_id = str(os.environ.get("FAPAI_NODE_ID") or "").strip()
    if node_id:
        payload["node_id"] = node_id
    normalized_scope = str(scope or "").strip().lower()
    if normalized_scope in {"seed", "detail"}:
        payload["scope"] = normalized_scope
    if manual_only:
        payload["manual_only"] = True
    try:
        loaded = post_json(endpoint, payload, timeout=10)
    except OSError as exc:
        return {"status": "request_failed", "error": str(exc)}
    return loaded if isinstance(loaded, dict) else {"status": "unknown_response", "raw": loaded}


def resolve_captcha_report_cdp_endpoint(cdp_endpoint: str) -> str:
    for name in CAPTCHA_REPORT_CDP_ENV_NAMES:
        raw = os.environ.get(name)
        if raw and raw.strip():
            return raw.strip()
    return cdp_endpoint


def redact_taobao_sensitive_text(value: str) -> str:
    redacted = value
    for pattern in SENSITIVE_INLINE_PATTERNS:
        redacted = pattern.sub("taobao_security_value=<redacted>", redacted)
    return redacted


def redact_taobao_sensitive_url(url: str) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError:
        return redact_taobao_sensitive_text(url)
    query = urlencode(
        [
            (key, redact_taobao_sensitive_text(value))
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() not in SENSITIVE_QUERY_KEYS
        ],
        doseq=True,
    )
    return redact_taobao_sensitive_text(urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, parsed.fragment)))


def redact_taobao_health_output(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): redact_taobao_health_output(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_taobao_health_output(item) for item in value]
    if isinstance(value, str):
        if value.startswith(("http://", "https://")):
            return redact_taobao_sensitive_url(value)
        return redact_taobao_sensitive_text(value)
    return value


def _operator_host_endpoint(cdp_endpoint: str) -> str:
    return cdp_endpoint.replace("192.168.65.254", "127.0.0.1")


def _helper_command(*, cdp_endpoint: str, check_url: str, wait_seconds: int) -> str:
    return (
        'python tools\\taobao_login_health.py '
        f'--cdp-endpoint "{cdp_endpoint}" '
        f'--check-url "{check_url}" '
        f"--open-login --wait-seconds {wait_seconds}"
    )


def _summary_flag(summary: Mapping[str, object], key: str) -> bool:
    return summary.get(key) is True


def classify_taobao_health(
    html: str,
    *,
    final_url: str,
    list_summary: Mapping[str, object] | None = None,
    payload_present: bool,
) -> dict[str, object]:
    summary = list_summary or {}
    text = html or ""
    lowered_text = text.lower()
    lowered_url = (final_url or "").lower()

    has_login = (
        _summary_flag(summary, "body_has_login")
        or "login.taobao.com" in lowered_url
        or "login.m.taobao.com" in lowered_url
        or "havanaone/login" in lowered_url
    )
    has_punish = (
        _summary_flag(summary, "body_has_punish")
        or "_____tmd_____" in lowered_url
        or "_____tmd_____" in lowered_text
        or "/punish" in lowered_url
        or "/punish" in lowered_text
        or "x5secdata=" in lowered_text
    )
    has_captcha = (
        _summary_flag(summary, "body_has_captcha")
        or (
            not payload_present
            and (
                "captcha" in lowered_text
                or "验证码" in text
                or "霸下通用 web 页面-验证码" in text
            )
        )
    )
    has_challenge = (
        _summary_flag(summary, "body_has_challenge")
        or "challenge" in lowered_url
        or (
            not payload_present
            and (
                "challenge" in lowered_text
                or "anti-bot" in lowered_text
                or "霸下" in text
            )
        )
    )

    if payload_present and not (has_login or has_punish or has_captcha or has_challenge):
        return {
            "status": HEALTHY_LIST_PAYLOAD,
            "healthy": True,
            "action": "none",
            "final_url": final_url,
        }
    if has_punish:
        return {
            "status": PUNISH_PAGE,
            "healthy": False,
            "action": "complete_taobao_security_verification",
            "final_url": final_url,
        }
    if has_captcha:
        return {
            "status": CAPTCHA_PAGE,
            "healthy": False,
            "action": "complete_taobao_security_verification",
            "final_url": final_url,
        }
    if has_challenge:
        return {
            "status": CHALLENGE_REQUIRED,
            "healthy": False,
            "action": "complete_taobao_security_verification",
            "final_url": final_url,
        }
    if has_login:
        return {
            "status": LOGIN_REQUIRED,
            "healthy": False,
            "action": "complete_taobao_login",
            "final_url": final_url,
        }
    return {
        "status": UNKNOWN_BLOCKED,
        "healthy": False,
        "action": "inspect_taobao_session",
        "final_url": final_url,
    }


def build_operator_hint(
    *,
    status: str,
    cdp_endpoint: str,
    check_url: str,
    wait_seconds: int = DEFAULT_WAIT_SECONDS,
) -> dict[str, object]:
    required = status != HEALTHY_LIST_PAYLOAD
    helper_command = _helper_command(cdp_endpoint=cdp_endpoint, check_url=check_url, wait_seconds=wait_seconds)
    host_helper_command = _helper_command(
        cdp_endpoint=_operator_host_endpoint(cdp_endpoint),
        check_url=check_url,
        wait_seconds=wait_seconds,
    )
    return {
        "required": required,
        "status": status,
        "action": "run_taobao_login_health_helper" if required else "none",
        "helper_command": helper_command,
        "host_helper_command": host_helper_command,
        "login_url": build_login_url(check_url),
        "message": (
            "Complete Taobao QR login or official security verification in the Edge CDP browser, "
            "then wait for this helper to report healthy."
            if required
            else "Taobao/SF list page is readable through the current CDP session."
        ),
    }


def _probe_summary_and_payload(html: str, final_url: str) -> tuple[dict[str, object], bool]:
    from tools import browserless_seed_probe

    summary = browserless_seed_probe.summarize_list_page(html, final_url=final_url)
    payload_present = browserless_seed_probe.extract_list_payload(html) is not None
    return dict(summary), payload_present


def _build_taobao_health_result(
    *,
    cdp_endpoint: str,
    check_url: str,
    html: str,
    final_url: str,
) -> dict[str, object]:
    list_summary, payload_present = _probe_summary_and_payload(html, final_url)
    result = classify_taobao_health(
        html,
        final_url=final_url,
        list_summary=list_summary,
        payload_present=payload_present,
    )
    result.update(
        {
            "cdp_endpoint": cdp_endpoint,
            "check_url": check_url,
            "list_summary": list_summary,
        }
    )
    result["operator_hint"] = build_operator_hint(
        status=str(result["status"]),
        cdp_endpoint=cdp_endpoint,
        check_url=check_url,
    )
    return result


def _build_cdp_unreachable_result(*, cdp_endpoint: str, check_url: str, error: str) -> dict[str, object]:
    result: dict[str, object] = {
        "status": CDP_UNREACHABLE,
        "healthy": False,
        "action": "start_or_repair_taobao_cdp_browser",
        "cdp_endpoint": cdp_endpoint,
        "check_url": check_url,
        "error": error,
    }
    result["operator_hint"] = build_operator_hint(
        status=CDP_UNREACHABLE,
        cdp_endpoint=cdp_endpoint,
        check_url=check_url,
    )
    return result


def _build_taobao_health_result_from_summary(
    *,
    cdp_endpoint: str,
    check_url: str,
    final_url: str,
    list_summary: Mapping[str, object],
    payload_present: bool,
    probe_transport: str | None = None,
    cookie_summary: Mapping[str, object] | None = None,
) -> dict[str, object]:
    result = classify_taobao_health(
        "",
        final_url=final_url,
        list_summary=list_summary,
        payload_present=payload_present,
    )
    result.update(
        {
            "cdp_endpoint": cdp_endpoint,
            "check_url": check_url,
            "list_summary": dict(list_summary),
        }
    )
    result["operator_hint"] = build_operator_hint(
        status=str(result["status"]),
        cdp_endpoint=cdp_endpoint,
        check_url=check_url,
    )
    if probe_transport:
        result["probe_transport"] = probe_transport
    if cookie_summary:
        result["cookie_summary"] = dict(cookie_summary)
    return result


def resolve_playwright_cdp_endpoint(cdp_endpoint: str) -> str:
    normalized = str(cdp_endpoint or "").strip()
    try:
        hostname = (urlsplit(normalized).hostname or "").lower()
    except ValueError:
        return normalized
    if hostname in {"127.0.0.1", "localhost", "::1"}:
        return normalized

    from tools import browserless_seed_probe

    return browserless_seed_probe._resolve_cdp_endpoint(normalized)


def fetch_pages_via_cdp(cdp_endpoint: str, urls: Sequence[str]) -> list[tuple[str, str]]:
    from playwright.sync_api import sync_playwright

    results: list[tuple[str, str]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(resolve_playwright_cdp_endpoint(cdp_endpoint), timeout=DEFAULT_CDP_CONNECT_TIMEOUT_MS)
        try:
            if not browser.contexts:
                context = browser.new_context()
            else:
                context = browser.contexts[0]
            for url in urls:
                page = context.new_page()
                try:
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                    except Exception:
                        # Taobao punish/challenge navigations can stay pending; classify current DOM anyway.
                        pass
                    results.append((read_page_content_with_retries(page), page.url))
                finally:
                    try:
                        page.close()
                    except Exception:
                        pass
        finally:
            detach_attached_cdp_browser(browser)
    return results


def fetch_page_via_cdp(cdp_endpoint: str, url: str) -> tuple[str, str]:
    return fetch_pages_via_cdp(cdp_endpoint, (url,))[0]


def fetch_health_samples_via_cdp_cookie_http(cdp_endpoint: str, urls: Sequence[str]) -> list[dict[str, object]]:
    from tools import browserless_seed_probe

    cookies = browserless_seed_probe._export_cdp_cookies_via_websocket(
        cdp_endpoint,
        browserless_seed_probe.DEFAULT_COOKIE_ORIGINS,
    )
    cookie_summary = dict(browserless_seed_probe.summarize_cookie_snapshot(cookies))
    cookie_summary.pop("names", None)
    session = browserless_seed_probe.build_session_from_playwright_cookies(cookies)
    results: list[dict[str, object]] = []
    for url in urls:
        summary = browserless_seed_probe.probe_seed_page(url, cookies=cookies, session=session)
        final_url = str(summary.get("final_url") or url)
        list_summary = {
            "has_script": summary.get("has_script"),
            "item_count": summary.get("item_count"),
            "first_ids": summary.get("first_ids"),
            "first_urls": summary.get("first_urls"),
            "body_has_login": summary.get("body_has_login"),
            "body_has_captcha": summary.get("body_has_captcha"),
            "body_has_punish": summary.get("body_has_punish"),
            "body_has_challenge": summary.get("body_has_challenge"),
            "body_snippet": summary.get("body_snippet"),
        }
        results.append(
            _build_taobao_health_result_from_summary(
                cdp_endpoint=cdp_endpoint,
                check_url=str(url),
                final_url=final_url,
                list_summary=list_summary,
                payload_present=summary.get("has_script") is True,
                probe_transport="cookie_http",
                cookie_summary=cookie_summary,
            )
        )
    return results


def build_cdp_verification_page_matcher(url: str) -> Callable[[str], bool]:
    requested_url = url.lower()
    requested_worker_master = "__captcha_worker_master=1" in requested_url
    requested_solver_target = "__captcha_solver_bg=1" in requested_url
    requested_solver_route = _captcha_solver_route(url) if requested_solver_target else ""
    requested_solver_scope = _captcha_solver_scope(url) if requested_solver_target else ""

    requested_login = (
        "login.taobao.com" in requested_url
        or "login.m.taobao.com" in requested_url
        or "login.tmall.com" in requested_url
        or "havanaone/login" in requested_url
    )

    def is_taobao_verification_page(candidate_url: str) -> bool:
        lowered = candidate_url.lower()
        if requested_worker_master:
            return "__captcha_worker_master=1" in lowered
        if requested_solver_target:
            # Login redirects carry the original solver target inside an
            # encoded query parameter.  They do not themselves retain the
            # ``__captcha_solver_bg`` marker, so recognize the shared login
            # surface before applying list/detail scope matching.  This keeps
            # one operator login tab across both independent challenge scopes.
            if any(
                marker in lowered
                for marker in (
                    "login.taobao.com",
                    "login.m.taobao.com",
                    "login.tmall.com",
                    "havanaone/login",
                )
            ):
                return True
            if "__captcha_solver_bg=1" in lowered or "__captcha_manual_popup=1" in lowered:
                # Solver tabs are scoped by the auction page type.  A
                # detail challenge must never be reused for a list challenge
                # (or vice versa), even though both carry the same marker.
                candidate_scope = _captcha_solver_scope(candidate_url)
                if requested_solver_scope and candidate_scope:
                    return candidate_scope == requested_solver_scope
                return bool(
                    requested_solver_route
                    and _captcha_solver_route(candidate_url) == requested_solver_route
                )
            candidate_is_challenge = any(
                marker in lowered
                for marker in ("/_____tmd_____/punish", "x5secdata=", "x5step=")
            )
            return bool(
                candidate_is_challenge
                and requested_solver_route
                and (
                    (
                        requested_solver_scope
                        and _captcha_solver_scope(candidate_url) == requested_solver_scope
                    )
                    or (
                        not requested_solver_scope
                        and _captcha_solver_route(candidate_url) == requested_solver_route
                    )
                )
            )
        if requested_login:
            return (
                "login.taobao.com" in lowered
                or "login.m.taobao.com" in lowered
                or "login.tmall.com" in lowered
                or "havanaone/login" in lowered
            )
        return any(
            marker in lowered
            for marker in (
                "login.taobao.com",
                "login.m.taobao.com",
                "havanaone/login",
                "__captcha_solver_bg=1",
                "__captcha_manual_popup=1",
                "_____tmd_____",
                "/punish",
                "challenge",
            )
        )

    return is_taobao_verification_page


def _captcha_solver_route(value: str) -> str:
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return ""
    if not parsed.scheme or not parsed.netloc:
        return ""
    path = (parsed.path or "/").split("/_____tmd_____/", 1)[0]
    while "//" in path:
        path = path.replace("//", "/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path or "/", "", ""))


def _captcha_solver_scope(value: str) -> str:
    """Classify Taobao solver pages into the independent list/detail scopes."""
    try:
        parsed = urlsplit(str(value or "").strip())
    except ValueError:
        return ""
    host = (parsed.hostname or "").lower()
    path = (parsed.path or "/").replace("//", "/").lower()
    if host == "sf-item.taobao.com" or "/sf_item/" in path:
        return "detail"
    if host == "sf.taobao.com" and "/list/" in path:
        return "seed"
    if "/punish" in path and "/list/" in path:
        return "seed"
    return ""


def _rewrite_cdp_payload_websockets(cdp_endpoint: str, payload: object) -> object:
    from tools import browserless_seed_probe

    if isinstance(payload, Mapping):
        rewritten = {
            str(key): _rewrite_cdp_payload_websockets(cdp_endpoint, value)
            for key, value in payload.items()
        }
        websocket_url = rewritten.get("webSocketDebuggerUrl")
        if isinstance(websocket_url, str):
            rewritten["webSocketDebuggerUrl"] = browserless_seed_probe.rewrite_cdp_websocket_url(
                cdp_endpoint,
                websocket_url,
            )
        return rewritten
    if isinstance(payload, list):
        return [_rewrite_cdp_payload_websockets(cdp_endpoint, item) for item in payload]
    return payload


def read_cdp_json(cdp_endpoint: str, path: str, *, method: str = "GET", timeout: int = 5) -> object:
    request = Request(cdp_endpoint.rstrip("/") + path, method=method)
    with urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
    if not body.strip():
        return {}
    return _rewrite_cdp_payload_websockets(cdp_endpoint, json.loads(body))


def list_cdp_targets(cdp_endpoint: str) -> list[Mapping[str, object]]:
    targets = read_cdp_json(cdp_endpoint, "/json/list")
    if isinstance(targets, Mapping):
        return [targets]
    if isinstance(targets, list):
        return [target for target in targets if isinstance(target, Mapping)]
    return []


def cdp_page_target_limit() -> int:
    raw_limit = os.environ.get("FAPAI_CDP_MAX_PAGE_TARGETS", str(DEFAULT_CDP_PAGE_TARGET_LIMIT)).strip()
    try:
        limit = int(raw_limit)
    except ValueError:
        return DEFAULT_CDP_PAGE_TARGET_LIMIT
    return limit if limit > 0 else DEFAULT_CDP_PAGE_TARGET_LIMIT


def close_cdp_target(cdp_endpoint: str, target_id: object) -> bool:
    safe_target_id = str(target_id or "").strip()
    if not safe_target_id:
        return False
    request = Request(cdp_endpoint.rstrip("/") + f"/json/close/{quote(safe_target_id, safe='')}", method="GET")
    with urlopen(request, timeout=5) as response:
        response.read()
    return True


def open_cdp_keepalive_tab(cdp_endpoint: str) -> str:
    opened = read_cdp_json(cdp_endpoint, "/json/new?about:blank", method="PUT")
    if isinstance(opened, Mapping):
        return str(opened.get("id") or "")
    return ""


def compact_cdp_pages_if_needed(
    cdp_endpoint: str,
    targets: Sequence[Mapping[str, object]] | None = None,
    *,
    reserve_for_new_page: bool = False,
) -> Mapping[str, object]:
    targets = list(targets) if targets is not None else list_cdp_targets(cdp_endpoint)
    page_targets = [target for target in targets if str(target.get("type") or "") == "page"]
    target_limit = cdp_page_target_limit()
    trigger_count = max(target_limit - 1, 1) if reserve_for_new_page else target_limit
    if len(page_targets) < trigger_count:
        return {"triggered": False, "page_count": len(page_targets), "closed": 0}

    errors: list[str] = []
    keepalive_target_id = ""
    try:
        keepalive_target_id = open_cdp_keepalive_tab(cdp_endpoint)
    except Exception as error:
        errors.append(f"keepalive: {error!r}")
    preserve_target_id = keepalive_target_id or str(page_targets[0].get("id") or "").strip()
    closed = 0
    for target in page_targets:
        if str(target.get("id") or "").strip() == preserve_target_id:
            continue
        if close_cdp_target(cdp_endpoint, target.get("id")):
            closed += 1
    summary: dict[str, object] = {"triggered": True, "page_count": len(page_targets), "closed": closed}
    if keepalive_target_id:
        summary["keepalive_target_id"] = keepalive_target_id
    elif preserve_target_id:
        summary["preserved_target_id"] = preserve_target_id
    if errors:
        summary["errors"] = errors
    return summary


def activate_cdp_target(cdp_endpoint: str, target: Mapping[str, object]) -> None:
    target_id = str(target.get("id") or "")
    if not target_id:
        return
    request = Request(cdp_endpoint.rstrip("/") + f"/json/activate/{quote(target_id, safe='')}", method="GET")
    with urlopen(request, timeout=5) as response:
        response.read()


def find_cdp_target(cdp_endpoint: str, url: str) -> Mapping[str, object] | None:
    is_taobao_verification_page = build_cdp_verification_page_matcher(url)
    for target in list_cdp_targets(cdp_endpoint):
        candidate_url = str(target.get("url") or "")
        if is_taobao_verification_page(candidate_url):
            return target
    return None


@contextlib.contextmanager
def _auth_page_lock(cdp_endpoint: str):
    """Serialize auth-tab reuse across threads *and* helper processes."""
    key = str(cdp_endpoint or "").strip().rstrip("/").lower()
    with _AUTH_PAGE_LOCKS_GUARD:
        lock = _AUTH_PAGE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _AUTH_PAGE_LOCKS[key] = lock
    with lock:
        lock_path = Path(tempfile.gettempdir()) / (
            "fapaifang-auth-page-" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:24] + ".lock"
        )
        handle = None
        process_lock_acquired = False
        try:
            handle = open(lock_path, "a+b")
            handle.seek(0)
            handle.write(b"0")
            handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                # LK_LOCK gives up after roughly ten seconds.  Retry the
                # non-blocking primitive for the full login reuse window so a
                # second watchdog process cannot fall through and create a
                # competing tab while the first one is still probing.
                deadline = time.monotonic() + max(600.0, AUTH_PAGE_REUSE_WINDOW_SECONDS * 2)
                while True:
                    try:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() >= deadline:
                            raise
                        time.sleep(0.1)
                process_lock_acquired = True
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                process_lock_acquired = True
        except Exception:
            # A read-only temp directory should not make the health probe fail;
            # the in-process lock still protects the common case.
            if handle is not None:
                try:
                    handle.close()
                except Exception:
                    pass
                handle = None
        try:
            yield
        finally:
            if handle is not None:
                try:
                    if process_lock_acquired:
                        handle.seek(0)
                        if os.name == "nt":
                            import msvcrt

                            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                        else:
                            import fcntl

                            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except Exception:
                    pass
                finally:
                    try:
                        handle.close()
                    except Exception:
                        pass


def _is_login_or_challenge_url(value: str) -> bool:
    lowered = str(value or "").strip().lower()
    return any(
        marker in lowered
        for marker in (
            "login.taobao.com",
            "login.m.taobao.com",
            "login.tmall.com",
            "havanaone/login",
            "_____tmd_____",
            "x5secdata=",
            "x5step=",
            "/punish",
        )
    )


def evaluate_cdp_expression(websocket_url: str, expression: str) -> Mapping[str, object]:
    ws = websocket.create_connection(
        websocket_url,
        suppress_origin=True,
        timeout=DEFAULT_CDP_WEBSOCKET_TIMEOUT_SECONDS,
    )
    try:
        try:
            ws.settimeout(DEFAULT_CDP_WEBSOCKET_TIMEOUT_SECONDS)
        except Exception:
            pass
        command = {
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expression,
                "awaitPromise": True,
                "returnByValue": True,
            },
        }
        ws.send(json.dumps(command))
        for _attempt in range(10):
            raw = ws.recv()
            message = json.loads(raw)
            if isinstance(message, dict) and message.get("id") == command["id"]:
                return message
        return {"error": "no_matching_cdp_response"}
    finally:
        ws.close()


def detach_attached_cdp_browser(browser: object) -> None:
    """Detach from an externally managed CDP browser without closing the host process."""
    disconnect = getattr(browser, "disconnect", None)
    if callable(disconnect):
        try:
            disconnect()
        except Exception:
            pass


def read_page_content_with_retries(
    page: object,
    *,
    attempts: int = 5,
    wait_timeout_ms: int = 500,
) -> str:
    last_error: Exception | None = None
    for attempt_index in range(max(int(attempts), 1)):
        try:
            content = getattr(page, "content")
            return str(content() or "")
        except Exception as error:
            last_error = error
            if attempt_index >= max(int(attempts), 1) - 1:
                break
            waiter = getattr(page, "wait_for_timeout", None)
            if not callable(waiter):
                break
            try:
                waiter(wait_timeout_ms)
            except Exception:
                break
    if last_error is not None:
        raise last_error
    return ""


def cdp_response_bool_value(response: Mapping[str, object]) -> bool:
    result = response.get("result")
    if not isinstance(result, Mapping):
        return False
    inner = result.get("result")
    if not isinstance(inner, Mapping):
        return False
    return inner.get("value") is True


def queue_captcha_task_via_cdp(cdp_endpoint: str, target_url: str) -> Mapping[str, object]:
    worker_url = build_captcha_worker_master_url()
    existing_solver_target = find_cdp_target(cdp_endpoint, target_url)
    if existing_solver_target is not None:
        activate_cdp_target(cdp_endpoint, existing_solver_target)
        return {
            "status": "existing_solver_target",
            "worker_url": worker_url,
            "target_url": target_url,
        }
    compact_cdp_pages_if_needed(cdp_endpoint, reserve_for_new_page=True)
    worker_target = find_cdp_target(cdp_endpoint, worker_url)
    if worker_target is None:
        opened = read_cdp_json(cdp_endpoint, "/json/new?" + quote(worker_url, safe=""), method="PUT")
        if isinstance(opened, Mapping):
            worker_target = opened
        if worker_target is None or not worker_target.get("webSocketDebuggerUrl"):
            time.sleep(1)
            worker_target = find_cdp_target(cdp_endpoint, worker_url)

    if worker_target is None:
        return {
            "status": "worker_unavailable",
            "worker_url": worker_url,
            "target_url": target_url,
        }

    activate_cdp_target(cdp_endpoint, worker_target)
    websocket_url = str(worker_target.get("webSocketDebuggerUrl") or "")
    if not websocket_url:
        refreshed_target = find_cdp_target(cdp_endpoint, worker_url)
        websocket_url = str(refreshed_target.get("webSocketDebuggerUrl") or "") if refreshed_target else ""
    if not websocket_url:
        return {
            "status": "worker_missing_websocket",
            "worker_url": str(worker_target.get("url") or worker_url),
            "target_url": target_url,
        }

    bridge_check_response = evaluate_cdp_expression(
        websocket_url,
        (
            "Boolean(window.__fapaifangCaptchaWorkerBridgeInstalled"
            " || document.documentElement.getAttribute('data-fapaifang-captcha-worker-bridge') === 'installed'"
            " || document.getElementById('fapaifang-captcha-worker-bridge-marker'))"
        ),
    )
    if not cdp_response_bool_value(bridge_check_response):
        navigate_expression = f"window.location.href = {json.dumps(target_url, ensure_ascii=False)}; true"
        navigate_response = evaluate_cdp_expression(websocket_url, navigate_expression)
        return {
            "status": "worker_navigated_without_bridge",
            "worker_url": str(worker_target.get("url") or worker_url),
            "target_url": target_url,
            "bridge_check_response": bridge_check_response,
            "cdp_response": navigate_response,
        }

    expression = (
        "(() => {"
        "const message = {"
        "source: 'fapaifang-captcha-worker-bridge', "
        "type: 'queue-captcha-task', "
        f"url: {json.dumps(target_url, ensure_ascii=False)}, "
        "timestamp: Date.now()"
        "};"
        "window.postMessage(message, window.location.origin);"
        "return true;"
        "})()"
    )
    response = evaluate_cdp_expression(websocket_url, expression)
    return {
        "status": "queued",
        "worker_url": str(worker_target.get("url") or worker_url),
        "target_url": target_url,
        "bridge_check_response": bridge_check_response,
        "cdp_response": response,
    }


def open_page_via_cdp_http(cdp_endpoint: str, url: str) -> str:
    # Keep a login/challenge tab stable for at least the configured five-minute
    # window.  Existing matching tabs are always preferred even after the
    # window expires; replacing a tab would invalidate an operator's QR/password
    # session and is never necessary for the health check.
    with _auth_page_lock(cdp_endpoint):
        targets = list_cdp_targets(cdp_endpoint)
        target = None
        is_taobao_verification_page = build_cdp_verification_page_matcher(url)
        for candidate in targets:
            candidate_url = str(candidate.get("url") or "")
            if is_taobao_verification_page(candidate_url):
                target = candidate
                break
        if target is not None:
            activate_cdp_target(cdp_endpoint, target)
            return str(target.get("url") or url)

        compact_cdp_pages_if_needed(cdp_endpoint, targets, reserve_for_new_page=True)
        opened = read_cdp_json(cdp_endpoint, "/json/new?" + quote(url, safe=""), method="PUT")
        if isinstance(opened, Mapping):
            opened_url = str(opened.get("url") or "")
            if opened_url:
                return opened_url
        return url


def open_page_via_cdp(cdp_endpoint: str, url: str) -> str:
    try:
        return open_page_via_cdp_http(cdp_endpoint, url)
    except Exception:
        pass

    from playwright.sync_api import sync_playwright

    is_taobao_verification_page = build_cdp_verification_page_matcher(url)

    with _auth_page_lock(cdp_endpoint):
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(resolve_playwright_cdp_endpoint(cdp_endpoint), timeout=DEFAULT_CDP_CONNECT_TIMEOUT_MS)
            try:
                if not browser.contexts:
                    context = browser.new_context()
                else:
                    context = browser.contexts[0]
                for existing_page in getattr(context, "pages", []):
                    if is_taobao_verification_page(str(getattr(existing_page, "url", ""))):
                        try:
                            existing_page.bring_to_front()
                        except Exception:
                            pass
                        return str(existing_page.url)
                page = context.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=10_000)
                except Exception:
                    pass
                try:
                    page.bring_to_front()
                except Exception:
                    pass
                return page.url
            finally:
                detach_attached_cdp_browser(browser)


def check_taobao_health(
    *,
    cdp_endpoint: str = DEFAULT_CDP_ENDPOINT,
    check_url: str = DEFAULT_CHECK_URL,
    open_login: bool = False,
    trigger_captcha_solver: bool = False,
    api_base_url: str = DEFAULT_API_BASE_URL,
    fetch_page_func: FetchPageFunc | None = None,
    open_page_func: OpenPageFunc | None = None,
    report_captcha_func: ReportCaptchaFunc | None = None,
) -> dict[str, object]:
    fetch_page = fetch_page_func or fetch_page_via_cdp
    open_page = open_page_func or open_page_via_cdp
    report_captcha = report_captcha_func or report_captcha_via_api

    if fetch_page_func is None:
        try:
            result = fetch_health_samples_via_cdp_cookie_http(cdp_endpoint, (check_url,))[0]
        except Exception:
            result = None
        else:
            if result.get("healthy") is not True:
                if trigger_captcha_solver and result.get("status") in {PUNISH_PAGE, CAPTCHA_PAGE, CHALLENGE_REQUIRED, UNKNOWN_BLOCKED}:
                    solver_target_url = build_captcha_solver_target_url(str(result.get("final_url") or check_url))
                    if open_page_func is None:
                        try:
                            result["captcha_worker_queue_report"] = dict(queue_captcha_task_via_cdp(cdp_endpoint, solver_target_url))
                        except Exception as exc:
                            result["captcha_worker_queue_report"] = {"status": "queue_failed", "error": str(exc)}
                        result["captcha_worker_url"] = str(
                            result["captcha_worker_queue_report"].get("worker_url")
                            or build_captcha_worker_master_url()
                        )
                    else:
                        result["captcha_worker_url"] = open_page(cdp_endpoint, build_captcha_worker_master_url())
                    opened_url = open_page(cdp_endpoint, solver_target_url)
                    result["opened_url"] = opened_url
                    result["captcha_solver_target_url"] = solver_target_url
                    try:
                        result["captcha_solver_report"] = dict(report_captcha(api_base_url, cdp_endpoint, solver_target_url))
                        result["captcha_solver_triggered"] = True
                    except Exception as exc:
                        result["captcha_solver_triggered"] = False
                        result["captcha_solver_error"] = str(exc)
                elif open_login:
                    opened_url = open_page(cdp_endpoint, build_login_url(check_url))
                    result["opened_url"] = opened_url
            return dict(redact_taobao_health_output(result))

    try:
        html, final_url = fetch_page(cdp_endpoint, check_url)
    except Exception as exc:
        return _build_cdp_unreachable_result(cdp_endpoint=cdp_endpoint, check_url=check_url, error=str(exc))

    result = _build_taobao_health_result(
        cdp_endpoint=cdp_endpoint,
        check_url=check_url,
        html=html,
        final_url=final_url,
    )
    if result.get("healthy") is not True:
        if trigger_captcha_solver and result.get("status") in {PUNISH_PAGE, CAPTCHA_PAGE, CHALLENGE_REQUIRED, UNKNOWN_BLOCKED}:
            solver_target_url = build_captcha_solver_target_url(str(result.get("final_url") or check_url))
            if open_page_func is None:
                try:
                    result["captcha_worker_queue_report"] = dict(queue_captcha_task_via_cdp(cdp_endpoint, solver_target_url))
                except Exception as exc:
                    result["captcha_worker_queue_report"] = {"status": "queue_failed", "error": str(exc)}
                result["captcha_worker_url"] = str(
                    result["captcha_worker_queue_report"].get("worker_url")
                    or build_captcha_worker_master_url()
                )
            else:
                result["captcha_worker_url"] = open_page(cdp_endpoint, build_captcha_worker_master_url())
            opened_url = open_page(cdp_endpoint, solver_target_url)
            result["opened_url"] = opened_url
            result["captcha_solver_target_url"] = solver_target_url
            try:
                result["captcha_solver_report"] = dict(report_captcha(api_base_url, cdp_endpoint, solver_target_url))
                result["captcha_solver_triggered"] = True
            except Exception as exc:
                result["captcha_solver_triggered"] = False
                result["captcha_solver_error"] = str(exc)
        elif open_login:
            opened_url = open_page(cdp_endpoint, build_login_url(check_url))
            result["opened_url"] = opened_url
    return dict(redact_taobao_health_output(result))


def check_taobao_health_samples(
    *,
    cdp_endpoint: str = DEFAULT_CDP_ENDPOINT,
    sample_urls: Sequence[str],
    open_login: bool = False,
    trigger_captcha_solver: bool = False,
    api_base_url: str = DEFAULT_API_BASE_URL,
    fetch_page_func: FetchPageFunc | None = None,
    open_page_func: OpenPageFunc | None = None,
    report_captcha_func: ReportCaptchaFunc | None = None,
) -> dict[str, object]:
    urls = tuple(str(url).strip() for url in sample_urls if str(url).strip())
    if not urls:
        urls = (DEFAULT_CHECK_URL,)

    sample_results: list[dict[str, object]] = []
    if fetch_page_func is None:
        try:
            sample_results = fetch_health_samples_via_cdp_cookie_http(cdp_endpoint, urls)
        except Exception as exc:
            cookie_probe_error = str(exc)
            try:
                page_results = fetch_pages_via_cdp(cdp_endpoint, urls)
            except Exception:
                sample_results = [
                    _build_cdp_unreachable_result(
                        cdp_endpoint=cdp_endpoint,
                        check_url=url,
                        error=cookie_probe_error,
                    )
                    for url in urls
                ]
            else:
                sample_results = [
                    _build_taobao_health_result(
                        cdp_endpoint=cdp_endpoint,
                        check_url=url,
                        html=html,
                        final_url=final_url,
                    )
                    for url, (html, final_url) in zip(urls, page_results)
                ]
    else:
        for url in urls:
            result = check_taobao_health(
                cdp_endpoint=cdp_endpoint,
                check_url=url,
                open_login=False,
                fetch_page_func=fetch_page_func,
                open_page_func=open_page_func,
            )
            sample_results.append(result)

    healthy_samples = sum(1 for result in sample_results if result.get("healthy") is True)
    blocked_samples = len(sample_results) - healthy_samples
    first_blocked = next((result for result in sample_results if result.get("healthy") is not True), None)
    first_actionable_blocked = next(
        (
            result
            for result in sample_results
            if result.get("healthy") is not True and str(result.get("status")) != CDP_UNREACHABLE
        ),
        first_blocked,
    )
    first_status = str(first_actionable_blocked.get("status")) if first_actionable_blocked else HEALTHY_LIST_PAYLOAD
    all_samples_cdp_unreachable = bool(sample_results) and all(
        str(result.get("status")) == CDP_UNREACHABLE for result in sample_results
    )

    if healthy_samples:
        status = PARTIAL_AVAILABLE if blocked_samples else HEALTHY_LIST_PAYLOAD
        action = "none"
        healthy = True
    elif all_samples_cdp_unreachable:
        status = CDP_UNREACHABLE
        action = "start_or_repair_taobao_cdp_browser"
        healthy = False
    else:
        status = ALL_SAMPLES_BLOCKED
        action = "complete_taobao_security_verification"
        healthy = False

    result: dict[str, object] = {
        "status": status,
        "healthy": healthy,
        "action": action,
        "cdp_endpoint": cdp_endpoint,
        "sample_count": len(sample_results),
        "healthy_samples": healthy_samples,
        "blocked_samples": blocked_samples,
        "sample_results": sample_results,
    }
    hint_url = urls[0]
    result["operator_hint"] = build_operator_hint(
        status=first_status if not healthy else status,
        cdp_endpoint=cdp_endpoint,
        check_url=hint_url,
    )
    if not healthy and status != CDP_UNREACHABLE:
        open_page = open_page_func or open_page_via_cdp
        if trigger_captcha_solver:
            report_captcha = report_captcha_func or report_captcha_via_api
            solver_source = first_actionable_blocked or first_blocked
            solver_target_url = build_captcha_solver_target_url(str(solver_source.get("final_url") if solver_source else hint_url))
            if open_page_func is None:
                try:
                    result["captcha_worker_queue_report"] = dict(queue_captcha_task_via_cdp(cdp_endpoint, solver_target_url))
                except Exception as exc:
                    result["captcha_worker_queue_report"] = {"status": "queue_failed", "error": str(exc)}
                result["captcha_worker_url"] = str(
                    result["captcha_worker_queue_report"].get("worker_url")
                    or build_captcha_worker_master_url()
                )
            else:
                result["captcha_worker_url"] = open_page(cdp_endpoint, build_captcha_worker_master_url())
            result["opened_url"] = open_page(cdp_endpoint, solver_target_url)
            result["captcha_solver_target_url"] = solver_target_url
            try:
                result["captcha_solver_report"] = dict(report_captcha(api_base_url, cdp_endpoint, solver_target_url))
                result["captcha_solver_triggered"] = True
            except Exception as exc:
                result["captcha_solver_triggered"] = False
                result["captcha_solver_error"] = str(exc)
        elif open_login:
            result["opened_url"] = open_page(cdp_endpoint, build_login_url(hint_url))
    return dict(redact_taobao_health_output(result))


def wait_for_taobao_health(
    *,
    cdp_endpoint: str,
    check_url: str,
    open_login: bool,
    trigger_captcha_solver: bool,
    api_base_url: str,
    wait_seconds: int,
    poll_seconds: int,
    sleep_func: SleepFunc = time.sleep,
) -> dict[str, object]:
    deadline = time.monotonic() + max(wait_seconds, 0)
    attempts = 0
    opened = False
    while True:
        attempts += 1
        result = check_taobao_health(
            cdp_endpoint=cdp_endpoint,
            check_url=check_url,
            open_login=open_login and not opened,
            trigger_captcha_solver=trigger_captcha_solver,
            api_base_url=api_base_url,
        )
        opened = opened or "opened_url" in result
        result["attempts"] = attempts
        if result.get("healthy") is True:
            return result
        if wait_seconds <= 0 or time.monotonic() >= deadline:
            return result
        sleep_func(max(poll_seconds, 1))


def wait_for_taobao_health_samples(
    *,
    cdp_endpoint: str,
    sample_urls: Sequence[str],
    open_login: bool,
    trigger_captcha_solver: bool,
    api_base_url: str,
    wait_seconds: int,
    poll_seconds: int,
    sleep_func: SleepFunc = time.sleep,
) -> dict[str, object]:
    deadline = time.monotonic() + max(wait_seconds, 0)
    attempts = 0
    opened = False
    urls = tuple(sample_urls)
    while True:
        attempts += 1
        result = check_taobao_health_samples(
            cdp_endpoint=cdp_endpoint,
            sample_urls=urls,
            open_login=open_login and not opened,
            trigger_captcha_solver=trigger_captcha_solver,
            api_base_url=api_base_url,
        )
        opened = opened or "opened_url" in result
        result["attempts"] = attempts
        if result.get("healthy") is True:
            return result
        if wait_seconds <= 0 or time.monotonic() >= deadline:
            return result
        sleep_func(max(poll_seconds, 1))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Check and repair Taobao/SF login health through the existing Edge CDP profile.")
    parser.add_argument("--cdp-endpoint", default=DEFAULT_CDP_ENDPOINT)
    parser.add_argument("--check-url", default=DEFAULT_CHECK_URL)
    parser.add_argument("--sample-url", action="append", default=[])
    parser.add_argument("--open-login", action="store_true")
    parser.add_argument("--trigger-captcha-solver", action="store_true")
    parser.add_argument("--api-base-url", default=DEFAULT_API_BASE_URL)
    parser.add_argument("--wait-seconds", type=int, default=0)
    parser.add_argument("--poll-seconds", type=int, default=DEFAULT_POLL_SECONDS)
    parser.add_argument("--json", action="store_true", help="Accepted for compatibility; output is always JSON.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    sample_urls = tuple(str(url) for url in getattr(args, "sample_url", []) if str(url).strip())
    if sample_urls:
        result = wait_for_taobao_health_samples(
            cdp_endpoint=str(args.cdp_endpoint),
            sample_urls=sample_urls,
            open_login=bool(args.open_login),
            trigger_captcha_solver=bool(args.trigger_captcha_solver),
            api_base_url=str(args.api_base_url),
            wait_seconds=int(args.wait_seconds),
            poll_seconds=int(args.poll_seconds),
        )
    else:
        result = wait_for_taobao_health(
            cdp_endpoint=str(args.cdp_endpoint),
            check_url=str(args.check_url),
            open_login=bool(args.open_login),
            trigger_captcha_solver=bool(args.trigger_captcha_solver),
            api_base_url=str(args.api_base_url),
            wait_seconds=int(args.wait_seconds),
            poll_seconds=int(args.poll_seconds),
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get("healthy") is True:
        return 0
    if result.get("status") == CDP_UNREACHABLE:
        return 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
