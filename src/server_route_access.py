"""Fail-closed authorization policy for the source-neutral HTTP dispatcher."""

from typing import Literal

Access = Literal[
    "public", "worker", "operator", "node", "recovery", "engine", "settings"
]

WORKER_HANDLERS = frozenset(
    {
        "_post_seed_progress",
        "_post_seed_batch",
        "_post_seed_next_task",
        "_post_detail_tasks",
        "_post_detail_next_task",
        "_post_detail_next_visit",
        "_post_detail_update_item",
        "_post_detail_html",
        "_post_captcha_report",
        "_post_client_log",
        "_post_upload",
        "_post_area_result",
        "_post_infer_location",
    }
)
NODE_HANDLERS = frozenset(
    {
        "_post_auth_complete",
        "_post_auth_force_reset",
        "_post_auth_resume_after_cooldown",
    }
)
RECOVERY_HANDLERS = frozenset(
    {"_post_desktop_auth_request", "_post_auth_recovery_transition"}
)


def required_access(method: str, handler: str) -> Access:
    if method == "GET":
        return "public"
    if method != "POST":
        return "operator"
    if handler in WORKER_HANDLERS:
        return "worker"
    if handler in NODE_HANDLERS:
        return "node"
    if handler in RECOVERY_HANDLERS:
        return "recovery"
    if handler == "_post_engine_control":
        return "engine"
    if handler == "_post_collection_settings":
        return "settings"
    # New write handlers never silently acquire unauthenticated access.
    return "operator"
