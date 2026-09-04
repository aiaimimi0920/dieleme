"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.manual_review_control_plane_context import *


def _append_manual_review_control_plane_backup_repair(
    data_root: Path,
    *,
    reason: str,
    source_counts: dict[str, int],
    backup_counts_before: dict[str, int],
) -> dict[str, Any]:
    event = {
        "repair_id": str(uuid4()),
        "reason": str(reason or "").strip(),
        "repaired_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_receipt_count": int(source_counts.get("receipt_count", 0) or 0),
        "source_job_count": int(source_counts.get("job_count", 0) or 0),
        "source_operation_count": int(source_counts.get("operation_count", 0) or 0),
        "backup_receipt_count_before": int(backup_counts_before.get("receipt_count", 0) or 0),
        "backup_job_count_before": int(backup_counts_before.get("job_count", 0) or 0),
        "backup_operation_count_before": int(backup_counts_before.get("operation_count", 0) or 0),
    }
    path = _backup_repair_log_path(data_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return event


def summarize_manual_review_control_plane_backup_repairs(repairs: list[dict[str, Any]] | None) -> dict[str, Any]:
    normalized = [dict(item) for item in repairs or [] if isinstance(item, dict)]
    last_repair = normalized[-1] if normalized else None
    reason_counts: dict[str, int] = {}
    for item in normalized:
        reason = str(item.get("reason") or "").strip()
        if not reason:
            continue
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
    top_reason = None
    if reason_counts:
        top_reason = sorted(reason_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return {
        "repair_count": len(normalized),
        "repair_reason_counts": reason_counts,
        "last_repair_at": last_repair.get("repaired_at") if last_repair else None,
        "last_repair_reason": last_repair.get("reason") if last_repair else None,
        "top_repair_reason": top_reason,
    }


def record_manual_review_control_plane_integrity(
    data_root: Path,
    integrity: dict[str, Any] | None,
) -> dict[str, Any]:
    integrity = dict(integrity or {})
    event = {
        "integrity_id": str(uuid4()),
        "recorded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "integrity_status": str(integrity.get("integrity_status") or "unknown"),
        "attention_required": bool(integrity.get("attention_required")),
        "follow_up_recommended": bool(integrity.get("follow_up_recommended")),
        "repository_enabled": bool(integrity.get("repository_enabled")),
        "state_source": str(integrity.get("state_source") or ""),
        "backup_state": str(integrity.get("backup_state") or ""),
        "backup_reason": str(integrity.get("backup_reason") or ""),
        "repair_count": int(integrity.get("repair_count", 0) or 0),
        "last_repair_reason": integrity.get("last_repair_reason"),
        "top_repair_reason": integrity.get("top_repair_reason"),
    }
    path = _integrity_history_log_path(data_root)
    history = load_manual_review_control_plane_integrity_history(data_root)
    last = history[-1] if history else None
    if last:
        comparable_keys = (
            "integrity_status",
            "attention_required",
            "follow_up_recommended",
            "repository_enabled",
            "state_source",
            "backup_state",
            "backup_reason",
            "repair_count",
            "last_repair_reason",
            "top_repair_reason",
        )
        if all(last.get(key) == event.get(key) for key in comparable_keys):
            return {"recorded": False, "event": dict(last)}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")
    return {"recorded": True, "event": event}


def summarize_manual_review_control_plane_integrity_history(history: list[dict[str, Any]] | None) -> dict[str, Any]:
    normalized = [dict(item) for item in history or [] if isinstance(item, dict)]
    last = normalized[-1] if normalized else None
    status_counts: dict[str, int] = {}
    for item in normalized:
        status = str(item.get("integrity_status") or "").strip()
        if not status:
            continue
        status_counts[status] = status_counts.get(status, 0) + 1
    top_status = None
    if status_counts:
        top_status = sorted(status_counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return {
        "transition_count": len(normalized),
        "status_counts": status_counts,
        "last_recorded_at": last.get("recorded_at") if last else None,
        "last_integrity_status": last.get("integrity_status") if last else None,
        "top_integrity_status": top_status,
    }


def summarize_manual_review_control_plane_integrity(
    storage: dict[str, Any] | None,
    backup: dict[str, Any] | None,
    repairs_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    storage = dict(storage or {})
    backup = dict(backup or {})
    repairs_summary = dict(repairs_summary or {})
    repository_enabled = bool(storage.get("repository_enabled"))
    state_source = str(storage.get("state_source") or "")
    backup_state = str(backup.get("backup_state") or "")
    backup_reason = str(backup.get("backup_reason") or "")
    repair_count = int(repairs_summary.get("repair_count", 0) or 0)
    last_repair_reason = repairs_summary.get("last_repair_reason")
    top_repair_reason = repairs_summary.get("top_repair_reason")

    integrity_status = "unknown"
    attention_required = False
    follow_up_recommended = False

    if not repository_enabled and backup_state == "runtime_json":
        integrity_status = "healthy_json_runtime"
    elif repository_enabled and backup_state == "in_sync":
        if backup_reason.startswith("repaired_") or repair_count > 0:
            integrity_status = "repaired_recently"
            follow_up_recommended = True
        else:
            integrity_status = "healthy_repository"
    elif repository_enabled and backup_state == "missing_backup":
        integrity_status = "degraded_missing_backup"
        attention_required = True
        follow_up_recommended = True
    elif repository_enabled and backup_state == "count_mismatch":
        integrity_status = "degraded_count_mismatch"
        attention_required = True
        follow_up_recommended = True

    return {
        "integrity_status": integrity_status,
        "attention_required": attention_required,
        "follow_up_recommended": follow_up_recommended,
        "repository_enabled": repository_enabled,
        "state_source": state_source,
        "backup_state": backup_state,
        "backup_reason": backup_reason,
        "repair_count": repair_count,
        "last_repair_reason": last_repair_reason,
        "top_repair_reason": top_repair_reason,
    }


def summarize_manual_review_control_plane_stability(
    integrity: dict[str, Any] | None,
    integrity_history_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    integrity = dict(integrity or {})
    history = dict(integrity_history_summary or {})
    integrity_status = str(integrity.get("integrity_status") or "unknown")
    attention_required = bool(integrity.get("attention_required"))
    follow_up_recommended = bool(integrity.get("follow_up_recommended"))
    transition_count = int(history.get("transition_count", 0) or 0)
    last_integrity_status = history.get("last_integrity_status")
    top_integrity_status = history.get("top_integrity_status")

    stability_status = "unknown_stability"
    if integrity_status == "healthy_json_runtime":
        stability_status = "stable_json_runtime"
    elif integrity_status == "healthy_repository":
        stability_status = "stable_repository"
    elif integrity_status == "repaired_recently":
        stability_status = "watch_repaired_repository"
    elif integrity_status.startswith("degraded_"):
        stability_status = "unstable_repository"

    return {
        "stability_status": stability_status,
        "attention_required": attention_required,
        "follow_up_recommended": follow_up_recommended,
        "transition_count": transition_count,
        "last_integrity_status": last_integrity_status,
        "top_integrity_status": top_integrity_status,
    }


def summarize_manual_review_control_plane_guidance(
    integrity: dict[str, Any] | None,
    stability: dict[str, Any] | None,
    repairs_summary: dict[str, Any] | None,
) -> dict[str, Any]:
    integrity = dict(integrity or {})
    stability = dict(stability or {})
    repairs_summary = dict(repairs_summary or {})
    integrity_status = str(integrity.get("integrity_status") or "unknown")
    stability_status = str(stability.get("stability_status") or "unknown_stability")
    last_repair_reason = repairs_summary.get("last_repair_reason")

    guidance_status = "unknown_guidance"
    requires_operator_action = False
    priority = "info"
    recommended_actions: list[str] = []

    if stability_status in {"stable_json_runtime", "stable_repository"}:
        guidance_status = "no_action_required"
        recommended_actions = ["continue_monitoring_status_surfaces"]
    elif stability_status == "watch_repaired_repository":
        guidance_status = "monitor_recent_repair"
        priority = "warning"
        recommended_actions = [
            "review_backup_repairs_history",
            "monitor_backend_status",
        ]
    elif integrity_status == "degraded_missing_backup":
        guidance_status = "repair_backup_immediately"
        requires_operator_action = True
        priority = "critical"
        recommended_actions = [
            "inspect_backup_export_path",
            "run_control_plane_backup_export",
            "verify_backend_status_again",
        ]
    elif integrity_status == "degraded_count_mismatch":
        guidance_status = "investigate_backup_mismatch"
        requires_operator_action = True
        priority = "critical"
        recommended_actions = [
            "compare_repository_and_backup_counts",
            "review_backup_repairs_history",
            "verify_backend_status_again",
        ]
    else:
        recommended_actions = ["review_control_plane_status"]

    return {
        "guidance_status": guidance_status,
        "requires_operator_action": requires_operator_action,
        "priority": priority,
        "recommended_actions": recommended_actions,
        "top_guidance_reason": last_repair_reason or integrity_status,
    }


__all__ = (
    '_append_manual_review_control_plane_backup_repair',
    'summarize_manual_review_control_plane_backup_repairs',
    'record_manual_review_control_plane_integrity',
    'summarize_manual_review_control_plane_integrity_history',
    'summarize_manual_review_control_plane_integrity',
    'summarize_manual_review_control_plane_stability',
    'summarize_manual_review_control_plane_guidance',
)
