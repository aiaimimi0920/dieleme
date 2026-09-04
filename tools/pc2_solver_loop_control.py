from __future__ import annotations

from tools.pc2_solver_context import *  # noqa: F401,F403
from tools.pc2_solver_transport import *  # noqa: F401,F403
from tools.pc2_solver_scope import *  # noqa: F401,F403
from tools.pc2_solver_auth import *  # noqa: F401,F403
from tools.pc2_solver_fallback import *  # noqa: F401,F403
from tools.pc2_solver_auth_pending import *  # noqa: F401,F403
from tools.pc2_solver_cdp import *  # noqa: F401,F403
from tools.pc2_solver_execution import *  # noqa: F401,F403


def process_pending_control_actions(
    *,
    api_base_url: str,
    cdp_endpoint: str,
    expected_node_id: str | None,
    poll_seconds: float,
    last_probe_target: dict[str, Any] | None,
    last_auth_confirmed_at: float,
) -> dict[str, Any]:
    if nas_auth_recovery_client_enabled():
        auth_recovery = process_nas_auth_recovery_once(
            api_base_url,
            cdp_endpoint,
            expected_node_id or os.environ.get("FAPAI_NODE_ID", "pc2"),
            AUTH_RECOVERY_SNAPSHOT_PATH,
            AUTH_RECOVERY_MARKER_PATH,
            AUTH_RECOVERY_TOKEN_PATH,
        )
        recovery_action = str(auth_recovery.get("action") or "")
        if recovery_action not in {"idle", "ignored", "waiting_for_collection_progress"}:
            log_event({"kind": "nas_auth_recovery", **auth_recovery})
        if recovery_action == "restart_requested":
            write_solver_heartbeat(
                "auth_recovery_restart",
                recovery_id=auth_recovery.get("recovery_id"),
            )
            raise SystemExit(75)

    pending_confirmation = _retry_pending_auth_confirmation(api_base_url)
    if pending_confirmation.get("confirmed"):
        last_auth_confirmed_at = time.time()
        local_solver_loop._probe_counter = 0
        log_event(
            {
                "kind": "auth_complete_confirmed",
                "result": pending_confirmation.get("result"),
            }
        )
        time.sleep(0)
        return {
            "handled": True,
            "last_probe_target": last_probe_target,
            "last_auth_confirmed_at": last_auth_confirmed_at,
        }
    if pending_confirmation.get("pending"):
        if pending_confirmation.get("attempted"):
            log_event(
                {
                    "kind": "auth_complete_retry_pending",
                    "next_retry_at": pending_confirmation.get("next_retry_at"),
                    "result": pending_confirmation.get("result"),
                }
            )
        time.sleep(poll_seconds)
        return {
            "handled": True,
            "last_probe_target": last_probe_target,
            "last_auth_confirmed_at": last_auth_confirmed_at,
        }

    pending_resume = _retry_pending_collection_resume(api_base_url)
    if pending_resume.get("confirmed"):
        cleanup_target = resolve_stale_challenge_probe_target_after_resume(
            cdp_endpoint,
            last_probe_target,
            pending_resume,
        )
        cleanup = close_stale_challenge_probe_target(cdp_endpoint, cleanup_target)
        last_probe_target = None
        last_auth_confirmed_at = time.time()
        local_solver_loop._probe_counter = 0
        log_event(
            {
                "kind": "collection_resume_confirmed",
                "result": pending_resume.get("result"),
                "challenge_target_cleanup": cleanup,
            }
        )
        time.sleep(0)
        return {
            "handled": True,
            "last_probe_target": last_probe_target,
            "last_auth_confirmed_at": last_auth_confirmed_at,
        }
    if pending_resume.get("pending"):
        if pending_resume.get("attempted"):
            log_event(
                {
                    "kind": "collection_resume_pending",
                    "request_id": pending_resume.get("state", {}).get("collection_resume_request_id"),
                    "next_retry_at": pending_resume.get("next_retry_at"),
                    "result": pending_resume.get("result"),
                }
            )
        time.sleep(poll_seconds)
        return {
            "handled": True,
            "last_probe_target": last_probe_target,
            "last_auth_confirmed_at": last_auth_confirmed_at,
        }
    return {
        "handled": False,
        "last_probe_target": last_probe_target,
        "last_auth_confirmed_at": last_auth_confirmed_at,
    }


def reset_forced_solver_scopes(
    api_base_url: str,
    cdp_endpoint: str,
    solver_status: dict[str, Any],
    expected_node_id: str | None,
) -> dict[str, Any]:
    force_reset_done = False
    for scope, scoped_status in _solver_scope_statuses(solver_status).items():
        if not isinstance(scoped_status, dict) or not scoped_status.get("force_reset_required"):
            continue
        scoped_request = scoped_status.get("last_request")
        if isinstance(scoped_request, dict) and not node_owns_last_request(
            {"last_request": scoped_request, "running": True},
            cdp_endpoint,
            expected_node_id,
        ):
            continue
        cleanup = close_challenge_pages_for_scope(cdp_endpoint, scope)
        reset_result = notify_force_reset(
            api_base_url,
            scope,
            scoped_status.get("challenge_id"),
        )
        log_event(
            {
                "kind": "scoped_challenge_force_reset",
                "scope": scope,
                "challenge_id": scoped_status.get("challenge_id"),
                "reset": reset_result,
                "cleanup": cleanup,
            }
        )
        force_reset_done = force_reset_done or bool(reset_result.get("force_reset"))
    return read_solver_status(api_base_url) if force_reset_done else solver_status


__all__ = ("process_pending_control_actions", "reset_forced_solver_scopes")
