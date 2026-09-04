"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_release_gate_context import *


def _find_sample_records(data_root: Path, limit: int) -> List[dict[str, Any]]:
    return load_sample_analysis_ready_rows(data_root, limit, prefer_db=True)


def _load_manual_review_receipt_snapshot_for_gate(data_root: Path, repo) -> dict[str, Any]:
    receipt_path = data_root / "avm" / "manual_review_receipts.json"
    try:
        return load_manual_review_receipt_snapshot(
            receipt_path,
            repository=repo if repo.enabled else None,
        )
    except TypeError:
        return load_manual_review_receipt_snapshot(receipt_path)


def _analysis_readiness_context(data_root: Path, window_days: int = 7) -> dict[str, Any]:
    repo = create_repository_from_env()
    action_effectiveness = load_action_effectiveness_snapshot()
    scheduler_progress = load_optimization_loop_progress_snapshot()
    action_effectiveness_summary = summarize_action_effectiveness_snapshot(action_effectiveness)
    scheduler_feedback_summary = summarize_scheduler_feedback_snapshot(scheduler_progress)
    recent_gap_report = build_recent_gap_audit(data_root, window_days, sample_limit=20)
    recoverability_summary = summarize_recoverability_snapshot(recent_gap_report)
    manual_review_backlog_summary = summarize_manual_review_backlog(recent_gap_report)
    manual_review_receipt_summary = summarize_manual_review_receipt_snapshot(
        _load_manual_review_receipt_snapshot_for_gate(data_root, repo),
        manual_review_backlog_summary,
    )
    default_manual_review_reentry_application_summary = summarize_manual_review_reentry_application_summary(
        manual_review_receipt_summary,
        {},
        recent_gap_report,
        recent_gap_report,
        {"analysis_blockers": {}},
        {"analysis_blockers": {}},
    )
    default_recommended_actions = recommend_analysis_stage_actions(
        {"analysis_blockers": {}},
        gap_report=recent_gap_report,
        action_effectiveness=action_effectiveness,
        manual_review_receipt_summary=manual_review_receipt_summary,
    )
    default_operator_action_summary = summarize_operator_action_surface(
        default_recommended_actions,
        action_effectiveness_summary,
        recoverability_summary,
    )
    default_operator_action_summary["manual_review_backlog_summary"] = manual_review_backlog_summary
    default_operator_action_summary["manual_review_receipt_summary"] = manual_review_receipt_summary
    default_operator_action_summary["manual_review_reentry_application_summary"] = default_manual_review_reentry_application_summary
    default_operator_overview = summarize_operator_overview(
        default_operator_action_summary,
        scheduler_feedback_summary,
    )
    manual_review_receipt_jobs_summary = summarize_manual_review_receipt_jobs_snapshot(
        load_manual_review_receipt_jobs(
            data_root / "avm" / "manual_review_receipt_jobs.json",
            repository=repo if repo.enabled else None,
        )
    )
    manual_review_receipt_operations_summary = summarize_manual_review_receipt_operations_snapshot(
        load_manual_review_receipt_operations(
            data_root / "avm" / "manual_review_receipt_operations.jsonl",
            limit=200,
            repository=repo if repo.enabled else None,
        )
    )
    manual_review_control_plane_storage = describe_manual_review_control_plane_storage(
        data_root,
        repository=repo if repo.enabled else None,
    )
    manual_review_control_plane_backup = describe_manual_review_control_plane_backup(
        data_root,
        repository=repo if repo.enabled else None,
    )
    manual_review_control_plane_backup_repairs_summary = summarize_manual_review_control_plane_backup_repairs(
        load_manual_review_control_plane_backup_repairs(data_root)
    )
    manual_review_control_plane_integrity = summarize_manual_review_control_plane_integrity(
        manual_review_control_plane_storage,
        manual_review_control_plane_backup,
        manual_review_control_plane_backup_repairs_summary,
    )
    record_manual_review_control_plane_integrity(data_root, manual_review_control_plane_integrity)
    manual_review_control_plane_integrity_history_summary = summarize_manual_review_control_plane_integrity_history(
        load_manual_review_control_plane_integrity_history(data_root)
    )
    manual_review_control_plane_stability = summarize_manual_review_control_plane_stability(
        manual_review_control_plane_integrity,
        manual_review_control_plane_integrity_history_summary,
    )
    manual_review_control_plane_guidance = summarize_manual_review_control_plane_guidance(
        manual_review_control_plane_integrity,
        manual_review_control_plane_stability,
        manual_review_control_plane_backup_repairs_summary,
    )
    if not repo.enabled or not hasattr(repo, "analysis_readiness_snapshot"):
        return {
            "ready": 0,
            "not_ready": 0,
            "invalid": 0,
            "blockers": {},
            "recommended_actions": default_recommended_actions,
            "action_effectiveness_summary": action_effectiveness_summary,
            "recoverability_summary": recoverability_summary,
            "manual_review_backlog_summary": manual_review_backlog_summary,
            "manual_review_receipt_summary": manual_review_receipt_summary,
            "manual_review_reentry_application_summary": default_manual_review_reentry_application_summary,
            "manual_review_receipt_jobs_summary": manual_review_receipt_jobs_summary,
            "manual_review_receipt_operations_summary": manual_review_receipt_operations_summary,
            "manual_review_control_plane_storage": manual_review_control_plane_storage,
            "manual_review_control_plane_backup": manual_review_control_plane_backup,
            "manual_review_control_plane_backup_repairs_summary": manual_review_control_plane_backup_repairs_summary,
            "manual_review_control_plane_integrity": manual_review_control_plane_integrity,
            "manual_review_control_plane_integrity_history_summary": manual_review_control_plane_integrity_history_summary,
            "manual_review_control_plane_stability": manual_review_control_plane_stability,
            "manual_review_control_plane_guidance": manual_review_control_plane_guidance,
            "scheduler_feedback_summary": scheduler_feedback_summary,
            "operator_action_summary": default_operator_action_summary,
            "operator_overview": default_operator_overview,
        }
    try:
        snapshot = repo.analysis_readiness_snapshot()
        snapshot["recommended_actions"] = recommend_analysis_stage_actions(
            {"analysis_blockers": snapshot.get("blockers", {})},
            gap_report=recent_gap_report,
            action_effectiveness=action_effectiveness,
            manual_review_receipt_summary=manual_review_receipt_summary,
        )
        snapshot["action_effectiveness_summary"] = action_effectiveness_summary
        snapshot["recoverability_summary"] = recoverability_summary
        snapshot["manual_review_backlog_summary"] = manual_review_backlog_summary
        snapshot["manual_review_receipt_summary"] = manual_review_receipt_summary
        snapshot["manual_review_receipt_jobs_summary"] = manual_review_receipt_jobs_summary
        snapshot["manual_review_receipt_operations_summary"] = manual_review_receipt_operations_summary
        snapshot["manual_review_control_plane_storage"] = manual_review_control_plane_storage
        snapshot["manual_review_control_plane_backup"] = manual_review_control_plane_backup
        snapshot["manual_review_control_plane_backup_repairs_summary"] = manual_review_control_plane_backup_repairs_summary
        snapshot["manual_review_control_plane_integrity"] = manual_review_control_plane_integrity
        snapshot["manual_review_control_plane_integrity_history_summary"] = manual_review_control_plane_integrity_history_summary
        snapshot["manual_review_control_plane_stability"] = manual_review_control_plane_stability
        snapshot["manual_review_control_plane_guidance"] = manual_review_control_plane_guidance
        snapshot["manual_review_reentry_application_summary"] = summarize_manual_review_reentry_application_summary(
            manual_review_receipt_summary,
            {},
            recent_gap_report,
            recent_gap_report,
            {"analysis_blockers": snapshot.get("blockers", {})},
            {"analysis_blockers": snapshot.get("blockers", {})},
        )
        snapshot["scheduler_feedback_summary"] = scheduler_feedback_summary
        snapshot["operator_action_summary"] = summarize_operator_action_surface(
            snapshot["recommended_actions"],
            action_effectiveness_summary,
            recoverability_summary,
        )
        snapshot["operator_action_summary"]["manual_review_backlog_summary"] = manual_review_backlog_summary
        snapshot["operator_action_summary"]["manual_review_receipt_summary"] = manual_review_receipt_summary
        snapshot["operator_action_summary"]["manual_review_reentry_application_summary"] = snapshot["manual_review_reentry_application_summary"]
        snapshot["operator_overview"] = summarize_operator_overview(
            snapshot["operator_action_summary"],
            scheduler_feedback_summary,
        )
        return snapshot
    except Exception:
        return {
            "ready": 0,
            "not_ready": 0,
            "invalid": 0,
            "blockers": {},
            "recommended_actions": default_recommended_actions,
            "action_effectiveness_summary": action_effectiveness_summary,
            "recoverability_summary": recoverability_summary,
            "manual_review_backlog_summary": manual_review_backlog_summary,
            "manual_review_receipt_summary": manual_review_receipt_summary,
            "manual_review_receipt_jobs_summary": manual_review_receipt_jobs_summary,
            "manual_review_receipt_operations_summary": manual_review_receipt_operations_summary,
            "manual_review_control_plane_storage": manual_review_control_plane_storage,
            "manual_review_control_plane_backup": manual_review_control_plane_backup,
            "manual_review_control_plane_backup_repairs_summary": manual_review_control_plane_backup_repairs_summary,
            "manual_review_control_plane_integrity": manual_review_control_plane_integrity,
            "manual_review_control_plane_integrity_history_summary": manual_review_control_plane_integrity_history_summary,
            "manual_review_control_plane_stability": manual_review_control_plane_stability,
            "manual_review_control_plane_guidance": manual_review_control_plane_guidance,
            "scheduler_feedback_summary": scheduler_feedback_summary,
            "operator_action_summary": default_operator_action_summary,
            "operator_overview": default_operator_overview,
        }



__all__ = (
    "_find_sample_records",
    "_load_manual_review_receipt_snapshot_for_gate",
    "_analysis_readiness_context",
)
