"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.taobao_health_context import *


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


__all__ = (
    '_auth_page_lock',
    '_is_login_or_challenge_url',
    'evaluate_cdp_expression',
    'detach_attached_cdp_browser',
    'read_page_content_with_retries',
    'cdp_response_bool_value',
    'open_page_via_cdp_http',
    'open_page_via_cdp',
)
