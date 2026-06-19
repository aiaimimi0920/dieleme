from __future__ import annotations

import argparse
import hashlib
import json
import re
from html import unescape
from pathlib import Path
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import urlparse

import requests
from playwright.sync_api import sync_playwright
import websocket

DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9223"
DEFAULT_TARGET_URL = (
    "https://sf.taobao.com/list/50025969__2.htm"
    "?location_code=110101&st_param=2&auction_start_seg=-1&page=1"
)
DEFAULT_COOKIE_ORIGINS = ("https://sf.taobao.com", "https://login.taobao.com")
DEFAULT_CDP_CONNECT_TIMEOUT_MS = 20_000
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
)

_SCRIPT_RE = re.compile(
    r"<script[^>]+id=['\"]sf-item-list-data['\"][^>]*>(.*?)</script>",
    re.IGNORECASE | re.DOTALL,
)
_SENSITIVE_INLINE_PATTERNS = (
    re.compile(r"x5secdata\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
    re.compile(r"cookie2\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
    re.compile(r"sgcookie\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
    re.compile(r"_tb_token_\s*=\s*[^&\s\"'<>]+", re.IGNORECASE),
)


def redact_taobao_sensitive_text(value: str) -> str:
    redacted = value
    for pattern in _SENSITIVE_INLINE_PATTERNS:
        redacted = pattern.sub("taobao_security_value=<redacted>", redacted)
    return redacted


def _export_cdp_cookies_via_playwright(cdp_endpoint: str, origins: Iterable[str]) -> list[dict[str, Any]]:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_endpoint, timeout=DEFAULT_CDP_CONNECT_TIMEOUT_MS)
        try:
            if not browser.contexts:
                return []
            return browser.contexts[0].cookies(list(origins))
        finally:
            browser.close()


def filter_cdp_cookies_to_origins(cookies: Iterable[dict[str, Any]], origins: Iterable[str]) -> list[dict[str, Any]]:
    hosts = [urlparse(origin).hostname or "" for origin in origins]
    filtered = []
    for cookie in cookies:
        domain = str(cookie.get("domain") or "").lstrip(".")
        if any(domain == host or host.endswith(domain) or domain.endswith(host) for host in hosts if host):
            filtered.append(cookie)
    return filtered


def _export_cdp_cookies_via_websocket(cdp_endpoint: str, origins: Iterable[str]) -> list[dict[str, Any]]:
    version = requests.get(f"{cdp_endpoint.rstrip('/')}/json/version", timeout=10).json()
    ws = websocket.create_connection(version["webSocketDebuggerUrl"], timeout=20)
    try:
        ws.send(json.dumps({"id": 1, "method": "Storage.getCookies"}))
        response = json.loads(ws.recv())
    finally:
        ws.close()
    cookies = response.get("result", {}).get("cookies", [])
    return filter_cdp_cookies_to_origins(cookies, origins)


def export_cdp_cookies(cdp_endpoint: str, origins: Iterable[str] = DEFAULT_COOKIE_ORIGINS) -> list[dict[str, Any]]:
    origin_list = tuple(origins)
    try:
        return _export_cdp_cookies_via_websocket(cdp_endpoint, origin_list)
    except Exception:
        return _export_cdp_cookies_via_playwright(cdp_endpoint, origin_list)


def build_session_from_playwright_cookies(cookies: Iterable[dict[str, Any]]) -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    for cookie in cookies:
        session.cookies.set(
            str(cookie["name"]),
            str(cookie["value"]),
            domain=cookie.get("domain"),
            path=cookie.get("path", "/"),
        )
    return session


def extract_list_payload(html: str) -> dict[str, Any] | None:
    match = _SCRIPT_RE.search(html)
    if not match:
        return None
    return json.loads(unescape(match.group(1).strip()))


def _looks_like_login_page(text: str, final_url: str) -> bool:
    if "login.taobao.com" in final_url:
        return True
    strong_markers = ("扫码登录", "账户登录", "密码登录", "短信登录", "忘记密码")
    return any(marker in text for marker in strong_markers)


def summarize_list_page(html: str, *, final_url: str) -> dict[str, Any]:
    text = html or ""
    payload = extract_list_payload(text)
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data if isinstance(data, list) else []
    body_has_punish = "_____tmd_____/punish" in text or "x5secdata=" in text
    body_has_captcha = any(marker in text for marker in ("验证码", "RGV587_ERROR", "请完成验证", "安全验证"))
    body_snippet = redact_taobao_sensitive_text(text[:260].replace("\n", " ")[:260])
    return {
        "has_script": payload is not None,
        "item_count": len(items) if payload is not None else None,
        "first_ids": [item.get("id") for item in items[:5]],
        "first_urls": [item.get("itemUrl") or item.get("url") for item in items[:5]],
        "body_has_login": _looks_like_login_page(text, final_url),
        "body_has_captcha": body_has_captcha,
        "body_has_punish": body_has_punish,
        "body_has_challenge": body_has_captcha or body_has_punish,
        "body_snippet": body_snippet,
    }


def _format_local_datetime(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if abs(timestamp) >= 10**11:
            timestamp /= 1000.0
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")
    text = str(value).strip()
    if not text:
        return ""
    try:
        numeric = float(text)
    except ValueError:
        numeric = None
    if numeric is not None:
        if abs(numeric) >= 10**11:
            numeric /= 1000.0
        return datetime.fromtimestamp(numeric).strftime("%Y-%m-%d %H:%M:%S")
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, pattern).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return text


def build_userscript_like_batch_payload(payload: dict[str, Any], *, source_page_url: str) -> dict[str, Any]:
    raw_items = payload.get("data") if isinstance(payload.get("data"), list) else []
    items = []
    for item in raw_items:
        status = str(item.get("status", "")).lower()
        bid_count = item.get("bidCount", 0) or 0
        if status != "done" or bid_count < 1:
            continue
        latitude = item.get("latitude", item.get("lat"))
        longitude = item.get("longitude", item.get("lng"))
        items.append(
            {
                "id": item.get("id"),
                "title": item.get("title"),
                "currentPrice": item.get("currentPrice"),
                "initialPrice": item.get("initialPrice"),
                "auction_date": _format_local_datetime(item.get("end")),
                "auction_start_time": _format_local_datetime(item.get("startTime")),
                "end": item.get("end"),
                "url": f"https:{item.get('itemUrl')}" if item.get("itemUrl") else "",
                "status": item.get("status"),
                "bidCount": bid_count,
                "bidderCount": item.get("bidUserNumber", item.get("bidderCount")),
                "applyCount": item.get("applyCount"),
                "watchCount": item.get("watchCount", item.get("pv")),
                "remindCount": item.get("remindCount", item.get("reminderCount")),
                "viewCount": item.get("viewCount", item.get("pv")),
                "location": item.get("itemAddress") or item.get("address") or item.get("location"),
                "full_address": item.get("itemAddress") or item.get("address") or item.get("location"),
                "district": item.get("district"),
                "city": item.get("city"),
                "latitude": latitude,
                "longitude": longitude,
                "coordinate_source": "list" if latitude is not None and longitude is not None else None,
                "auction_round": item.get("auctionRound", item.get("round")),
                "housing_type": item.get("housingType") or item.get("categoryName"),
                "deposit": item.get("deposit"),
                "is_processed": False,
            }
        )
    return {
        "items": items,
        "raw_payload": raw_items,
        "source_page_url": source_page_url,
    }


def probe_seed_page(
    url: str,
    *,
    cookies: Iterable[dict[str, Any]],
    session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    http = session or build_session_from_playwright_cookies(cookies)
    response = http.get(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Referer": "https://sf.taobao.com/",
        },
        timeout=timeout,
        allow_redirects=True,
    )
    summary = summarize_list_page(response.text, final_url=response.url)
    summary.update(
        {
            "status": response.status_code,
            "final_url": response.url,
        }
    )
    return summary


def write_cookie_snapshot(cookies: Iterable[dict[str, Any]], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(list(cookies), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_cookie_snapshot(output_path: str | Path) -> list[dict[str, Any]]:
    payload = json.loads(Path(output_path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("Cookie snapshot must be a JSON list.")
    return payload


def _normalize_cookie_expiry(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric <= 0:
        return None
    if abs(numeric) >= 10**11:
        numeric /= 1000.0
    return numeric


def _cookie_shape_fingerprint(cookies: Iterable[dict[str, Any]]) -> str:
    normalized = [
        {
            "name": str(cookie.get("name") or ""),
            "domain": str(cookie.get("domain") or ""),
            "path": str(cookie.get("path") or "/"),
            "secure": bool(cookie.get("secure")),
            "httpOnly": bool(cookie.get("httpOnly")),
            "session": _normalize_cookie_expiry(cookie.get("expires")) is None,
        }
        for cookie in cookies
    ]
    payload = json.dumps(sorted(normalized, key=lambda item: (item["domain"], item["name"], item["path"])), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _cookie_value_fingerprint(cookies: Iterable[dict[str, Any]]) -> str:
    normalized = [
        {
            "name": str(cookie.get("name") or ""),
            "domain": str(cookie.get("domain") or ""),
            "path": str(cookie.get("path") or "/"),
            "value": str(cookie.get("value") or ""),
        }
        for cookie in cookies
    ]
    payload = json.dumps(sorted(normalized, key=lambda item: (item["domain"], item["name"], item["path"])), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _cookie_key(cookie: dict[str, Any]) -> str:
    return f"{str(cookie.get('name') or '')}|{str(cookie.get('domain') or '')}|{str(cookie.get('path') or '/')}"


def summarize_cookie_snapshot(cookies: Iterable[dict[str, Any]]) -> dict[str, Any]:
    cookie_list = list(cookies)
    persistent_expiries = [
        normalized_expiry
        for normalized_expiry in (_normalize_cookie_expiry(cookie.get("expires")) for cookie in cookie_list)
        if normalized_expiry is not None
    ]
    return {
        "count": len(cookie_list),
        "domains": sorted({str(cookie.get("domain") or "") for cookie in cookie_list if str(cookie.get("domain") or "")}),
        "names": sorted({str(cookie.get("name") or "") for cookie in cookie_list if str(cookie.get("name") or "")}),
        "secure_count": sum(1 for cookie in cookie_list if bool(cookie.get("secure"))),
        "http_only_count": sum(1 for cookie in cookie_list if bool(cookie.get("httpOnly"))),
        "session_count": len(cookie_list) - len(persistent_expiries),
        "persistent_count": len(persistent_expiries),
        "earliest_expiry": _format_local_datetime(min(persistent_expiries)) if persistent_expiries else None,
        "latest_expiry": _format_local_datetime(max(persistent_expiries)) if persistent_expiries else None,
        "shape_fingerprint": _cookie_shape_fingerprint(cookie_list),
        "value_fingerprint": _cookie_value_fingerprint(cookie_list),
    }


def diff_cookie_snapshots(
    left_cookies: Iterable[dict[str, Any]],
    right_cookies: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    left_list = list(left_cookies)
    right_list = list(right_cookies)
    left_summary = summarize_cookie_snapshot(left_list)
    right_summary = summarize_cookie_snapshot(right_list)

    left_domains = set(left_summary["domains"])
    right_domains = set(right_summary["domains"])
    left_names = set(left_summary["names"])
    right_names = set(right_summary["names"])
    left_keys = {_cookie_key(cookie) for cookie in left_list}
    right_keys = {_cookie_key(cookie) for cookie in right_list}

    return {
        "added_domains": sorted(right_domains - left_domains),
        "removed_domains": sorted(left_domains - right_domains),
        "added_names": sorted(right_names - left_names),
        "removed_names": sorted(left_names - right_names),
        "added_keys": sorted(right_keys - left_keys),
        "removed_keys": sorted(left_keys - right_keys),
        "shared_key_count": len(left_keys & right_keys),
        "shape_fingerprint_equal": left_summary["shape_fingerprint"] == right_summary["shape_fingerprint"],
        "value_fingerprint_equal": left_summary["value_fingerprint"] == right_summary["value_fingerprint"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe browserless Taobao seed collection using an attached CDP session.")
    parser.add_argument("--cdp-endpoint", default=DEFAULT_CDP_ENDPOINT)
    parser.add_argument("--url", default=DEFAULT_TARGET_URL)
    parser.add_argument("--write-cookie-snapshot", default=None)
    parser.add_argument("--emit-batch-payload", action="store_true")
    args = parser.parse_args(argv)

    cookies = export_cdp_cookies(args.cdp_endpoint)
    if args.write_cookie_snapshot:
        write_cookie_snapshot(cookies, args.write_cookie_snapshot)

    summary = probe_seed_page(args.url, cookies=cookies)
    summary["cookie_count"] = len(cookies)
    if args.emit_batch_payload:
        session = build_session_from_playwright_cookies(cookies)
        response = session.get(
            args.url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": "https://sf.taobao.com/",
            },
            timeout=30,
            allow_redirects=True,
        )
        payload = extract_list_payload(response.text)
        if payload is not None:
            summary["batch_payload"] = build_userscript_like_batch_payload(
                payload,
                source_page_url=response.url,
            )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
