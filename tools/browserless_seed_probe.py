from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from html import unescape
from pathlib import Path
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import urlparse

import requests
import websocket

try:
    from playwright.sync_api import sync_playwright
except ModuleNotFoundError:
    sync_playwright = None

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
DEFAULT_ACCEPT_LANGUAGE = "zh-CN,zh;q=0.9,en;q=0.8"
DEFAULT_NAVIGATION_ACCEPT = (
    "text/html,application/xhtml+xml,application/xml;q=0.9,"
    "image/avif,image/webp,image/apng,*/*;q=0.8"
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
    if sync_playwright is None:
        raise RuntimeError("Playwright is not installed; raw CDP websocket cookie export must be available.")
    resolved_endpoint = _resolve_cdp_endpoint(cdp_endpoint)
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(resolved_endpoint, timeout=DEFAULT_CDP_CONNECT_TIMEOUT_MS)
        if not browser.contexts:
            return []
        return browser.contexts[0].cookies(list(origins))


def filter_cdp_cookies_to_origins(cookies: Iterable[dict[str, Any]], origins: Iterable[str]) -> list[dict[str, Any]]:
    hosts = [urlparse(origin).hostname or "" for origin in origins]
    filtered = []
    for cookie in cookies:
        domain = str(cookie.get("domain") or "").lstrip(".")
        if any(domain == host or host.endswith(domain) or domain.endswith(host) for host in hosts if host):
            filtered.append(cookie)
    return filtered


def _export_cdp_cookies_via_websocket(cdp_endpoint: str, origins: Iterable[str]) -> list[dict[str, Any]]:
    session = requests.Session()
    session.trust_env = False
    websocket_url = _resolve_cdp_websocket_for_cookie_export(session, cdp_endpoint)
    ws = websocket.create_connection(websocket_url, timeout=20)
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


def _cdp_websocket_cache_path() -> Path | None:
    explicit = str(os.environ.get("FAPAI_CDP_WEBSOCKET_CACHE_PATH") or "").strip()
    if explicit:
        return Path(explicit)
    snapshot_path = str(os.environ.get("FAPAI_COOKIE_SNAPSHOT") or "").strip()
    if snapshot_path:
        snapshot = Path(snapshot_path)
        return snapshot.with_name("cdp-websocket-cache.json")
    return None


def _load_cached_cdp_websocket(cdp_endpoint: str) -> str:
    cache_path = _cdp_websocket_cache_path()
    if cache_path is None or not cache_path.exists():
        return ""
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except Exception:
        return ""
    if not isinstance(payload, dict):
        return ""
    websocket_url = str(payload.get(str(cdp_endpoint or "").rstrip("/")) or "").strip()
    return websocket_url if websocket_url.startswith(("ws://", "wss://")) else ""


def _write_cached_cdp_websocket(cdp_endpoint: str, websocket_url: str) -> None:
    normalized_endpoint = str(cdp_endpoint or "").rstrip("/")
    normalized_websocket = str(websocket_url or "").strip()
    if not normalized_endpoint or not normalized_websocket.startswith(("ws://", "wss://")):
        return
    cache_path = _cdp_websocket_cache_path()
    if cache_path is None:
        return
    payload: dict[str, str] = {}
    if cache_path.exists():
        try:
            existing = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(existing, dict):
                payload = {str(key): str(value) for key, value in existing.items()}
        except Exception:
            payload = {}
    payload[normalized_endpoint] = normalized_websocket
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _resolve_cdp_websocket_for_cookie_export(session: requests.Session, cdp_endpoint: str) -> str:
    base = str(cdp_endpoint or "").rstrip("/")
    try:
        payload = session.get(f"{base}/json/version", timeout=10).json()
        websocket_url = str((payload or {}).get("webSocketDebuggerUrl") or "").strip()
        if websocket_url:
            _write_cached_cdp_websocket(cdp_endpoint, websocket_url)
            return websocket_url
    except Exception:
        pass
    try:
        targets = session.get(f"{base}/json", timeout=10).json()
    except Exception:
        targets = None
    if isinstance(targets, list):
        for target in targets:
            if not isinstance(target, dict):
                continue
            websocket_url = str(target.get("webSocketDebuggerUrl") or "").strip()
            if websocket_url:
                _write_cached_cdp_websocket(cdp_endpoint, websocket_url)
                return websocket_url
    cached_websocket = _load_cached_cdp_websocket(cdp_endpoint)
    if cached_websocket:
        return cached_websocket
    raise RuntimeError(f"cdp websocket target unavailable for {cdp_endpoint}")


def _resolve_cdp_endpoint(cdp_endpoint: str) -> str:
    normalized = str(cdp_endpoint or "").strip()
    if not normalized or normalized.startswith(("ws://", "wss://")):
        return normalized
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(f"{normalized.rstrip('/')}/json/version", timeout=10)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return _load_cached_cdp_websocket(cdp_endpoint) or normalized
    if not isinstance(payload, dict):
        return _load_cached_cdp_websocket(cdp_endpoint) or normalized
    websocket_url = str(payload.get("webSocketDebuggerUrl") or "").strip()
    if websocket_url:
        _write_cached_cdp_websocket(cdp_endpoint, websocket_url)
        return websocket_url
    return _load_cached_cdp_websocket(cdp_endpoint) or normalized


def resolve_cdp_user_agent(cdp_endpoint: str, *, default: str = DEFAULT_USER_AGENT) -> str:
    normalized = str(cdp_endpoint or "").strip()
    if not normalized or normalized.startswith(("ws://", "wss://")):
        return default
    session = requests.Session()
    session.trust_env = False
    try:
        response = session.get(f"{normalized.rstrip('/')}/json/version", timeout=10)
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return default
    if not isinstance(payload, dict):
        return default
    candidate = str(payload.get("User-Agent") or payload.get("userAgent") or "").strip()
    return candidate or default


def _site_boundary(target_url: str, referer_url: str) -> str:
    target_host = str(urlparse(target_url).hostname or "").lower()
    referer_host = str(urlparse(referer_url).hostname or "").lower()
    if not referer_host:
        return "none"
    if target_host == referer_host:
        return "same-origin"
    target_parts = target_host.split(".")
    referer_parts = referer_host.split(".")
    if len(target_parts) >= 2 and len(referer_parts) >= 2:
        if ".".join(target_parts[-2:]) == ".".join(referer_parts[-2:]):
            return "same-site"
    return "cross-site"


def build_navigation_headers(
    *,
    target_url: str,
    user_agent: str,
    referer_url: str,
    accept_language: str = DEFAULT_ACCEPT_LANGUAGE,
) -> dict[str, str]:
    headers = {
        "User-Agent": str(user_agent or DEFAULT_USER_AGENT),
        "Accept": DEFAULT_NAVIGATION_ACCEPT,
        "Accept-Language": str(accept_language or DEFAULT_ACCEPT_LANGUAGE),
        "Cache-Control": "max-age=0",
        "Pragma": "no-cache",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": _site_boundary(target_url, referer_url),
        "Sec-Fetch-User": "?1",
    }
    if str(referer_url or "").strip():
        headers["Referer"] = str(referer_url)
    return headers


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
    lowered_final_url = str(final_url or "").lower()
    payload = extract_list_payload(text)
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data if isinstance(data, list) else []
    body_has_punish = (
        "_____tmd_____/punish" in text
        or "x5secdata=" in text
        or "_____tmd_____/punish" in lowered_final_url
        or "x5secdata=" in lowered_final_url
    )
    strong_captcha_markers = (
        "RGV587_ERROR",
        "请完成验证",
        "安全验证",
        "霸下通用 web 页面-验证码",
        "滑动验证",
        "人机验证",
        "异常流量",
        "访问受限",
    )
    body_has_captcha = any(marker in text for marker in strong_captcha_markers) or (
        payload is None and "验证码" in text
    )
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
    user_agent: str | None = None,
    referer_url: str = "https://sf.taobao.com/",
) -> dict[str, Any]:
    http = session or build_session_from_playwright_cookies(cookies)
    response = http.get(
        url,
        headers=build_navigation_headers(
            target_url=url,
            user_agent=str(user_agent or DEFAULT_USER_AGENT),
            referer_url=referer_url,
        ),
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
