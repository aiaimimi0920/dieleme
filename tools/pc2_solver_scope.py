from __future__ import annotations
from tools.pc2_solver_context import *  # noqa: F401,F403
from tools.pc2_solver_transport import *  # noqa: F401,F403


def _solver_scope_statuses(solver_status):
    if not isinstance(solver_status, dict):
        return {}
    scopes = solver_status.get("scopes") or solver_status.get("collection_scopes")
    return dict(scopes) if isinstance(scopes, dict) else {}

def select_solver_scope_status(solver_status, preferred_challenge_id=None):
    """Project aggregate NAS state onto one stable scoped challenge."""
    if not isinstance(solver_status, dict):
        return {}
    candidates = []
    for scope, scoped_status in _solver_scope_statuses(solver_status).items():
        if not isinstance(scoped_status, dict):
            continue
        challenge_id = str(scoped_status.get("challenge_id") or "").strip()
        if not challenge_id:
            continue
        first_seen = float(scoped_status.get("first_seen_epoch") or 0)
        candidates.append((str(scope), challenge_id, first_seen, scoped_status))
    if not candidates:
        return dict(solver_status)

    preferred = str(preferred_challenge_id or "").strip()
    selected = next((item for item in candidates if item[1] == preferred), None)
    if selected is None:
        selected = min(
            candidates,
            key=lambda item: (item[2] if item[2] > 0 else float("inf"), item[0]),
        )
    scope, challenge_id, _first_seen, scoped_status = selected
    scoped_request = scoped_status.get("last_request")
    projected = dict(solver_status)
    projected.update(
        {
            "scope": scope,
            "challenge_id": challenge_id,
            "paused": bool(scoped_status.get("paused")),
            "manual_required": bool(scoped_status.get("manual_required")),
            "manual_only": bool(scoped_status.get("manual_only")),
            "last_status": scoped_status.get("last_status") or projected.get("last_status"),
            "last_failure_reason": scoped_status.get("last_failure_reason"),
            "last_request": dict(scoped_request) if isinstance(scoped_request, dict) else {},
        }
    )
    return projected

def notify_force_reset(api_base, scope, challenge_id):
    try:
        payload = post_json(
            _force_reset_url(api_base),
            {
                "source": "pc2_local_solver",
                "scope": scope,
                "challenge_id": challenge_id,
            },
            timeout=10,
        )
        return payload if isinstance(payload, dict) else {"ok": False, "payload": payload}
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}

def _challenge_scope_for_url(url):
    value = str(url or "").strip()
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    host = str(parsed.hostname or "").strip().lower()
    path = str(parsed.path or "/").lower()
    while "//" in path:
        path = path.replace("//", "/")
    if host == "sf-item.taobao.com" or "/sf_item/" in path:
        return "detail"
    if host == "sf.taobao.com" and "/list/" in path:
        return "seed"
    return ""

def close_challenge_pages_for_scope(cdp_endpoint, scope):
    """Close all CDP collection/challenge tabs for one scope after force reset."""
    normalized = str(scope or "").strip().lower()
    if normalized not in {"seed", "detail"}:
        return {"attempted": False, "closed": 0, "reason": "invalid_scope"}
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
    except Exception as exc:
        return {"attempted": True, "closed": 0, "error": repr(exc)}
    closed = []
    closer = CaptchaSolver(cdp_endpoint=cdp_endpoint)
    for tab in tabs if isinstance(tabs, list) else []:
        if not isinstance(tab, dict) or tab.get("type") != "page":
            continue
        target_id = str(tab.get("id") or "").strip()
        target_url = str(tab.get("url") or "").strip()
        if not target_id or target_url.lower() == "about:blank":
            continue
        if _challenge_scope_for_url(target_url) != normalized:
            continue
        try:
            if closer._close_cdp_target(target_id):
                closed.append(target_id)
        except Exception:
            continue
    return {"attempted": True, "closed": len(closed), "target_ids": closed, "scope": normalized}

def compact_active_challenge_pages(cdp_endpoint, solver_status):
    """Keep at most one active challenge page for each independent scope."""
    try:
        tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
    except Exception as exc:
        return {"attempted": True, "closed": 0, "error": repr(exc), "scopes": {}}
    if not isinstance(tabs, list):
        return {"attempted": True, "closed": 0, "error": "invalid_cdp_tab_list", "scopes": {}}

    results = {}
    total_closed = 0
    for scope, scoped_status in _solver_scope_statuses(solver_status).items():
        if scope not in {"seed", "detail"} or not isinstance(scoped_status, dict):
            continue
        if not str(scoped_status.get("challenge_id") or "").strip():
            continue
        target_url = solver_request_target_url(scoped_status.get("last_request"))
        if not target_url:
            continue
        solver = CaptchaSolver(cdp_endpoint=cdp_endpoint, target_url=target_url)
        pruning = solver._prune_duplicate_challenge_tabs(tabs)
        results[scope] = pruning
        closed = int(pruning.get("closed") or 0)
        total_closed += closed
        if closed:
            try:
                refreshed_tabs = fetch_json(f"{cdp_endpoint.rstrip('/')}/json/list", timeout=5)
                if isinstance(refreshed_tabs, list):
                    tabs = refreshed_tabs
            except Exception:
                pass
    return {"attempted": True, "closed": total_closed, "scopes": results}

def check_cdp_healthy(cdp_endpoint):
    endpoint = cdp_endpoint.rstrip("/")
    for p in ("/json/list", "/json/version"):
        try:
            resp = fetch_json(f"{endpoint}{p}", timeout=5)
            if resp is not None: return True
        except Exception: continue
    return False

def cdp_endpoint_matches_local(reported_cdp, local_cdp):
    if not reported_cdp or not local_cdp: return False
    reported = reported_cdp.lower().strip().rstrip("/")
    local = local_cdp.lower().strip().rstrip("/")
    if reported == local: return True
    for loopback in ("127.0.0.1", "localhost", "0.0.0.0", "::1"):
        if loopback in reported and loopback in local: return True
        if loopback in reported and "host.docker.internal" in local: return True
        if loopback in reported and "192.168.65.254" in local: return True
    return False

def node_owns_last_request(solver_status, local_cdp_endpoint, expected_node_id=None):
    last_request = solver_status.get("last_request")
    if not isinstance(last_request, dict): return False
    node_id = str(last_request.get("node_id") or "").strip().lower()
    if expected_node_id:
        if node_id == expected_node_id.strip().lower(): return True
    reported_cdp = str(last_request.get("cdp_endpoint") or "").strip()
    if reported_cdp and cdp_endpoint_matches_local(reported_cdp, local_cdp_endpoint): return True
    return False

def solver_status_requires_manual_only(solver_status):
    if not isinstance(solver_status, dict):
        return False
    if solver_status.get("manual_only") is True:
        return True
    last_request = solver_status.get("last_request")
    if not isinstance(last_request, dict):
        return False
    target_url = str(last_request.get("target_url") or last_request.get("url") or "").strip()
    try:
        hostname = str(urlsplit(target_url).hostname or "").strip().lower()
    except ValueError:
        return False
    is_taobao = hostname == "taobao.com" or hostname.endswith(".taobao.com")
    return bool(is_taobao and not real_taobao_auto_solver_enabled())

def manual_challenge_registration_needed(solver_status):
    return bool(
        solver_status_requires_manual_only(solver_status)
        and not (
            solver_status.get("manual_required") is True
            and str(solver_status.get("challenge_id") or "").strip()
        )
    )

def canonical_manual_challenge_target(value):
    target_url = str(value or "").strip()
    try:
        parsed = urlsplit(target_url)
    except ValueError:
        return ""
    hostname = str(parsed.hostname or "").strip().lower()
    if not hostname or not (hostname == "taobao.com" or hostname.endswith(".taobao.com")):
        return ""
    path = parsed.path.split("/_____tmd_____/punish", 1)[0]
    while "//" in path:
        path = path.replace("//", "/")
    return urlunsplit((parsed.scheme or "https", parsed.netloc, path or "/", "", ""))

def notify_manual_challenge(api_base, solver_status, expected_node_id=None):
    last_request = solver_status.get("last_request") if isinstance(solver_status, dict) else None
    if not isinstance(last_request, dict):
        return {"ok": False, "error": "missing_last_request"}
    target_url = canonical_manual_challenge_target(
        last_request.get("target_url") or last_request.get("url")
    )
    if not target_url:
        return {"ok": False, "error": "missing_safe_target_url"}
    payload = {
        "target_url": target_url,
        "url": target_url,
        "node_id": str(expected_node_id or last_request.get("node_id") or "").strip(),
        "cdp_endpoint": str(last_request.get("cdp_endpoint") or "").strip(),
        "manual_only": True,
        "timestamp": int(time.time() * 1000),
    }
    scope = str(solver_status.get("scope") or "").strip()
    if scope:
        payload["scope"] = scope
    try:
        response = post_json(_manual_captcha_report_url(api_base), payload, timeout=10)
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}
    return dict(response) if isinstance(response, dict) else {"ok": False, "error": "non_dict_response"}

def notify_solver_blocked(api_base, solver_status, fallback_state, expected_node_id=None):
    last_request = solver_status.get("last_request") if isinstance(solver_status, dict) else None
    if not isinstance(last_request, dict):
        return {"ok": False, "error": "missing_last_request"}
    target_url = canonical_manual_challenge_target(
        last_request.get("target_url") or last_request.get("url")
    )
    if not target_url:
        return {"ok": False, "error": "missing_safe_target_url"}
    payload = {
        "target_url": target_url,
        "url": target_url,
        "node_id": str(expected_node_id or last_request.get("node_id") or "").strip(),
        "cdp_endpoint": str(last_request.get("cdp_endpoint") or "").strip(),
        "challenge_id": str(solver_status.get("challenge_id") or "").strip() or None,
        "node_solver_blocked": True,
        "node_solver_blocked_reason": str(
            fallback_state.get("solver_cooldown_reason") or "repeated_solver_failures"
        ).strip(),
        "node_solver_blocked_attempts": int(
            fallback_state.get("slider_attempts", fallback_state.get("consecutive_failures", 0)) or 0
        ),
        "timestamp": int(time.time() * 1000),
    }
    scope = str(solver_status.get("scope") or fallback_state.get("scope") or "").strip()
    if scope:
        payload["scope"] = scope
    try:
        response = post_json(_captcha_report_url(api_base), payload, timeout=10)
    except Exception as exc:
        return {"ok": False, "error": repr(exc)}
    return dict(response) if isinstance(response, dict) else {"ok": False, "error": "non_dict_response"}

def node_solver_execution_block_reason(solver_status, local_cdp_endpoint, expected_node_id=None):
    """Fail closed unless this node is the sole eligible challenge executor."""
    if not isinstance(solver_status, dict) or solver_status.get("error"):
        return "status_unavailable"
    if solver_status_requires_manual_only(solver_status):
        return "manual_only"
    if solver_status.get("running") is True:
        return "nas_solver_running"
    if not node_owns_last_request(solver_status, local_cdp_endpoint, expected_node_id):
        return "request_owned_elsewhere"
    return None

__all__ = ('_solver_scope_statuses', 'select_solver_scope_status', 'notify_force_reset', '_challenge_scope_for_url', 'close_challenge_pages_for_scope', 'compact_active_challenge_pages', 'check_cdp_healthy', 'cdp_endpoint_matches_local', 'node_owns_last_request', 'solver_status_requires_manual_only', 'manual_challenge_registration_needed', 'canonical_manual_challenge_target', 'notify_manual_challenge', 'notify_solver_blocked', 'node_solver_execution_block_reason')
