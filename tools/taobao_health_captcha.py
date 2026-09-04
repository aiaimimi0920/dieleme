"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.taobao_health_context import *


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


__all__ = (
    '_captcha_solver_route',
    '_captcha_solver_scope',
    'queue_captcha_task_via_cdp',
)
