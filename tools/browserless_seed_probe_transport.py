"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.browserless_seed_probe_context import *


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


def cdp_endpoint_is_healthy(cdp_endpoint: str, *, timeout_seconds: float = 3.0) -> bool:
    normalized = str(cdp_endpoint or "").strip().rstrip("/")
    if not normalized:
        return False
    if normalized.startswith(("ws://", "wss://")):
        return True
    session = requests.Session()
    session.trust_env = False
    for path, expected_type in (("/json/version", dict), ("/json/list", list)):
        try:
            response = session.get(f"{normalized}{path}", timeout=timeout_seconds)
            response.raise_for_status()
            if isinstance(response.json(), expected_type):
                return True
        except Exception:
            continue
    return False


def _cdp_reconnect_attempts() -> int:
    raw = os.environ.get("FAPAI_CDP_RECONNECT_ATTEMPTS", str(DEFAULT_CDP_RECONNECT_ATTEMPTS))
    try:
        value = int(str(raw or "").strip())
    except ValueError:
        value = DEFAULT_CDP_RECONNECT_ATTEMPTS
    return max(1, min(value, 10))


def _cdp_reconnect_backoff_seconds() -> float:
    raw = os.environ.get("FAPAI_CDP_RECONNECT_BACKOFF_SECONDS", str(DEFAULT_CDP_RECONNECT_BACKOFF_SECONDS))
    try:
        value = float(str(raw or "").strip())
    except ValueError:
        value = DEFAULT_CDP_RECONNECT_BACKOFF_SECONDS
    return max(0.0, min(value, 30.0))


def export_cdp_cookies(cdp_endpoint: str, origins: Iterable[str] = DEFAULT_COOKIE_ORIGINS) -> list[dict[str, Any]]:
    origin_list = tuple(origins)
    attempts = _cdp_reconnect_attempts()
    backoff = _cdp_reconnect_backoff_seconds()
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        if attempt > 1 and not cdp_endpoint_is_healthy(cdp_endpoint):
            last_error = RuntimeError(f"CDP health check failed before reconnect attempt {attempt}")
            if attempt < attempts and backoff > 0:
                time.sleep(backoff * attempt)
            continue
        try:
            return _export_cdp_cookies_via_websocket(cdp_endpoint, origin_list)
        except Exception as error:
            last_error = error
        try:
            return _export_cdp_cookies_via_playwright(cdp_endpoint, origin_list)
        except Exception as error:
            last_error = error
        if attempt < attempts and backoff > 0:
            time.sleep(backoff * attempt)
    raise RuntimeError(
        f"CDP cookie export unavailable after {attempts} bounded attempts for {cdp_endpoint}"
    ) from last_error


def _cdp_websocket_cache_path() -> Path | None:
    explicit = str(os.environ.get("FAPAI_CDP_WEBSOCKET_CACHE_PATH") or "").strip()
    if explicit:
        return Path(explicit)
    snapshot_path = str(os.environ.get("FAPAI_COOKIE_SNAPSHOT") or "").strip()
    if snapshot_path:
        snapshot = Path(snapshot_path)
        return snapshot.with_name("cdp-websocket-cache.json")
    return None


def rewrite_cdp_websocket_url(cdp_endpoint: str, websocket_url: str) -> str:
    """Replace Chromium's loopback WebSocket authority with the reachable CDP authority."""
    normalized_websocket = str(websocket_url or "").strip()
    if not normalized_websocket.startswith(("ws://", "wss://")):
        return normalized_websocket
    try:
        endpoint = urlsplit(str(cdp_endpoint or "").strip())
        websocket = urlsplit(normalized_websocket)
    except ValueError:
        return normalized_websocket
    if endpoint.scheme not in {"http", "https"} or not endpoint.netloc:
        return normalized_websocket
    if str(websocket.hostname or "").lower() not in {"127.0.0.1", "localhost", "0.0.0.0", "::1"}:
        return normalized_websocket
    return urlunsplit(
        (
            websocket.scheme,
            endpoint.netloc,
            websocket.path,
            websocket.query,
            websocket.fragment,
        )
    )


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
    if not websocket_url.startswith(("ws://", "wss://")):
        return ""
    return rewrite_cdp_websocket_url(cdp_endpoint, websocket_url)


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
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        # Worker cookie snapshots are intentionally mounted read-only. The CDP
        # cache improves reconnects but must never make a live endpoint unusable.
        return


def _resolve_cdp_websocket_for_cookie_export(session: requests.Session, cdp_endpoint: str) -> str:
    base = str(cdp_endpoint or "").rstrip("/")
    try:
        payload = session.get(f"{base}/json/version", timeout=10).json()
        websocket_url = rewrite_cdp_websocket_url(
            cdp_endpoint,
            str((payload or {}).get("webSocketDebuggerUrl") or "").strip(),
        )
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
            websocket_url = rewrite_cdp_websocket_url(
                cdp_endpoint,
                str(target.get("webSocketDebuggerUrl") or "").strip(),
            )
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
    websocket_url = rewrite_cdp_websocket_url(
        cdp_endpoint,
        str(payload.get("webSocketDebuggerUrl") or "").strip(),
    )
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


__all__ = (
    "_export_cdp_cookies_via_playwright",
    "filter_cdp_cookies_to_origins",
    "_export_cdp_cookies_via_websocket",
    "cdp_endpoint_is_healthy",
    "_cdp_reconnect_attempts",
    "_cdp_reconnect_backoff_seconds",
    "export_cdp_cookies",
    "_cdp_websocket_cache_path",
    "rewrite_cdp_websocket_url",
    "_load_cached_cdp_websocket",
    "_write_cached_cdp_websocket",
    "_resolve_cdp_websocket_for_cookie_export",
    "_resolve_cdp_endpoint",
    "resolve_cdp_user_agent",
)
