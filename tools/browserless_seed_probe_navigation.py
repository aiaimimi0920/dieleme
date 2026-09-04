"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.browserless_seed_probe_context import *


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
                "url": normalize_seed_item_url(item.get("itemUrl")),
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


__all__ = (
    "_site_boundary",
    "build_navigation_headers",
    "build_session_from_playwright_cookies",
    "extract_list_payload",
    "_looks_like_login_page",
    "summarize_list_page",
    "_format_local_datetime",
    "build_userscript_like_batch_payload",
    "probe_seed_page",
)
