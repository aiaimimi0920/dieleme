from __future__ import annotations

from pathlib import Path

from .server_context import (
    DATA_DIR,
    DB_REPOSITORY,
    describe_manual_review_control_plane_backup,
    describe_manual_review_control_plane_storage,
    load_action_effectiveness_snapshot,
    load_manual_review_control_plane_backup_repairs,
    load_manual_review_receipt_jobs,
    load_manual_review_receipt_operations,
    load_optimization_loop_progress_snapshot,
    load_recent_gap_audit_snapshot,
    recommend_analysis_stage_actions,
    record_manual_review_control_plane_integrity,
    summarize_action_effectiveness_snapshot,
    summarize_manual_review_backlog,
    summarize_manual_review_control_plane_backup_repairs,
    summarize_manual_review_control_plane_integrity,
    summarize_manual_review_receipt_jobs_snapshot,
    summarize_manual_review_receipt_operations_snapshot,
    summarize_manual_review_receipt_snapshot,
    summarize_manual_review_reentry_application_summary,
    summarize_operator_action_surface,
    summarize_operator_overview,
    summarize_recoverability_snapshot,
    summarize_scheduler_feedback_snapshot,
)

def _db_collection_stage_snapshot():
    action_effectiveness = load_action_effectiveness_snapshot(Path(DATA_DIR) / "avm" / "data_supply_optimization_loop.json")
    scheduler_progress = load_optimization_loop_progress_snapshot(Path(DATA_DIR) / "avm" / "data_supply_optimization_loop.json")
    action_effectiveness_summary = summarize_action_effectiveness_snapshot(action_effectiveness)
    scheduler_feedback_summary = summarize_scheduler_feedback_snapshot(scheduler_progress)
    recent_gap_report = load_recent_gap_audit_snapshot(Path(DATA_DIR) / "avm" / "recent_gap_audit.json")
    recoverability_summary = summarize_recoverability_snapshot(recent_gap_report)
    manual_review_backlog_summary = summarize_manual_review_backlog(recent_gap_report)
    manual_review_receipt_summary = summarize_manual_review_receipt_snapshot(
        _load_manual_review_receipt_snapshot_for_runtime(Path(DATA_DIR)),
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
    hybrid_collection_runtime_summary = _hybrid_collection_runtime_summary(Path(DATA_DIR))
    hybrid_collection_runtime_history_summary = _hybrid_collection_runtime_history_summary(Path(DATA_DIR))
    hybrid_collection_action_hint_trend_summary = _hybrid_collection_action_hint_trend_summary(Path(DATA_DIR))
    hybrid_collection_operator_final_guidance_trend_summary = _hybrid_collection_operator_final_guidance_trend_summary(Path(DATA_DIR))
    hybrid_collection_operator_final_guidance_stability_summary = _hybrid_collection_operator_final_guidance_stability_summary(
        hybrid_collection_operator_final_guidance_trend_summary,
    )
    hybrid_collection_operator_intervention_trend_summary = _hybrid_collection_operator_intervention_trend_summary(Path(DATA_DIR))
    hybrid_collection_mode_switch_event_summary = _hybrid_collection_mode_switch_event_summary(Path(DATA_DIR))
    hybrid_collection_recovery_policy_event_summary = _hybrid_collection_recovery_policy_event_summary(Path(DATA_DIR))
    hybrid_collection_operator_escalation_event_summary = _hybrid_collection_operator_escalation_event_summary(Path(DATA_DIR))
    hybrid_collection_operator_escalation_event_trend_summary = _hybrid_collection_operator_escalation_event_trend_summary(Path(DATA_DIR))
    hybrid_collection_operator_escalation_event_stability_summary = _hybrid_collection_operator_escalation_event_stability_summary(
        hybrid_collection_operator_escalation_event_trend_summary,
    )
    hybrid_collection_operator_escalation_recovery_event_summary = _hybrid_collection_operator_escalation_recovery_event_summary(Path(DATA_DIR))
    hybrid_collection_operator_intervention_event_summary = _hybrid_collection_operator_intervention_event_summary(Path(DATA_DIR))
    hybrid_collection_unresolved_escalation_window_summary = _hybrid_collection_unresolved_escalation_window_summary(
        hybrid_collection_operator_escalation_event_summary,
        hybrid_collection_operator_escalation_recovery_event_summary,
    )
    hybrid_collection_recovery_latency_summary = _hybrid_collection_recovery_latency_summary(Path(DATA_DIR))
    hybrid_collection_escalation_priority_mix_trend_summary = _hybrid_collection_escalation_priority_mix_trend_summary(Path(DATA_DIR))
    hybrid_collection_escalation_resolution_trend_summary = _hybrid_collection_escalation_resolution_trend_summary(
        hybrid_collection_operator_escalation_event_summary,
        hybrid_collection_operator_escalation_recovery_event_summary,
        hybrid_collection_unresolved_escalation_window_summary,
    )
    hybrid_collection_strategy_guidance = _hybrid_collection_strategy_guidance(
        hybrid_collection_runtime_summary,
        hybrid_collection_runtime_history_summary,
    )
    hybrid_collection_recovery_policy = _hybrid_collection_recovery_policy(
        Path(DATA_DIR),
        hybrid_collection_runtime_summary,
        hybrid_collection_runtime_history_summary,
        hybrid_collection_strategy_guidance,
        hybrid_collection_mode_switch_event_summary,
        hybrid_collection_recovery_policy_event_summary,
    )
    hybrid_collection_lifecycle_state_summary = _hybrid_collection_lifecycle_state_summary(
        hybrid_collection_runtime_summary,
        hybrid_collection_recovery_policy,
        hybrid_collection_unresolved_escalation_window_summary,
        hybrid_collection_escalation_priority_mix_trend_summary,
    )
    hybrid_collection_action_hint_consistency_summary = _hybrid_collection_action_hint_consistency_summary(
        hybrid_collection_runtime_summary,
        hybrid_collection_lifecycle_state_summary,
    )
    hybrid_collection_operator_intervention_policy_summary = _hybrid_collection_operator_intervention_policy_summary(
        hybrid_collection_lifecycle_state_summary,
        hybrid_collection_action_hint_consistency_summary,
        hybrid_collection_escalation_resolution_trend_summary,
        hybrid_collection_recovery_latency_summary,
    )
    hybrid_collection_operator_intervention_stability_summary = _hybrid_collection_operator_intervention_stability_summary(
        hybrid_collection_operator_intervention_trend_summary,
    )
    hybrid_collection_operator_final_guidance_summary = _hybrid_collection_operator_final_guidance_summary(
        hybrid_collection_operator_intervention_policy_summary,
        hybrid_collection_operator_intervention_stability_summary,
    )
    hybrid_collection_operator_digest_summary = _hybrid_collection_operator_digest_summary(
        hybrid_collection_operator_intervention_policy_summary,
        hybrid_collection_operator_intervention_stability_summary,
        hybrid_collection_operator_final_guidance_summary,
        hybrid_collection_operator_final_guidance_stability_summary,
    )
    hybrid_collection_operator_digest_trend_summary = _hybrid_collection_operator_digest_trend_summary(Path(DATA_DIR))
    hybrid_collection_operator_digest_stability_summary = _hybrid_collection_operator_digest_stability_summary(
        hybrid_collection_operator_digest_trend_summary,
    )
    default_operator_overview = summarize_operator_overview(
        default_operator_action_summary,
        scheduler_feedback_summary,
    )
    default_operator_overview.update(_hybrid_collection_operator_overview_fields(hybrid_collection_runtime_summary))
    default_operator_overview.update(_hybrid_collection_operator_history_overview_fields(hybrid_collection_runtime_history_summary))
    default_operator_overview.update(_hybrid_collection_operator_action_hint_trend_overview_fields(hybrid_collection_action_hint_trend_summary))
    default_operator_overview.update(_hybrid_collection_operator_final_guidance_trend_overview_fields(hybrid_collection_operator_final_guidance_trend_summary))
    default_operator_overview.update(_hybrid_collection_operator_final_guidance_stability_overview_fields(hybrid_collection_operator_final_guidance_stability_summary))
    default_operator_overview.update(_hybrid_collection_operator_digest_trend_overview_fields(hybrid_collection_operator_digest_trend_summary))
    default_operator_overview.update(_hybrid_collection_operator_digest_stability_overview_fields(hybrid_collection_operator_digest_stability_summary))
    default_operator_overview.update(_hybrid_collection_operator_intervention_trend_overview_fields(hybrid_collection_operator_intervention_trend_summary))
    default_operator_overview.update(_hybrid_collection_operator_guidance_overview_fields(hybrid_collection_strategy_guidance))
    default_operator_overview.update(_hybrid_collection_operator_mode_switch_overview_fields(hybrid_collection_mode_switch_event_summary))
    default_operator_overview.update(_hybrid_collection_operator_recovery_policy_overview_fields(hybrid_collection_recovery_policy))
    default_operator_overview.update(_hybrid_collection_operator_recovery_policy_event_overview_fields(hybrid_collection_recovery_policy_event_summary))
    default_operator_overview.update(_hybrid_collection_operator_escalation_event_overview_fields(hybrid_collection_operator_escalation_event_summary))
    default_operator_overview.update(_hybrid_collection_operator_escalation_event_trend_overview_fields(hybrid_collection_operator_escalation_event_trend_summary))
    default_operator_overview.update(_hybrid_collection_operator_escalation_event_stability_overview_fields(hybrid_collection_operator_escalation_event_stability_summary))
    default_operator_overview.update(_hybrid_collection_operator_escalation_recovery_event_overview_fields(hybrid_collection_operator_escalation_recovery_event_summary))
    default_operator_overview.update(_hybrid_collection_operator_intervention_event_overview_fields(hybrid_collection_operator_intervention_event_summary))
    default_operator_overview.update(_hybrid_collection_operator_unresolved_escalation_window_overview_fields(hybrid_collection_unresolved_escalation_window_summary))
    default_operator_overview.update(_hybrid_collection_operator_lifecycle_state_overview_fields(hybrid_collection_lifecycle_state_summary))
    default_operator_overview.update(_hybrid_collection_operator_action_hint_consistency_overview_fields(hybrid_collection_action_hint_consistency_summary))
    default_operator_overview.update(_hybrid_collection_operator_intervention_stability_overview_fields(hybrid_collection_operator_intervention_stability_summary))
    default_operator_overview.update(_hybrid_collection_operator_intervention_policy_overview_fields(hybrid_collection_operator_intervention_policy_summary))
    default_operator_overview.update(_hybrid_collection_operator_final_guidance_overview_fields(hybrid_collection_operator_final_guidance_summary))
    default_operator_overview.update(_hybrid_collection_operator_digest_overview_fields(hybrid_collection_operator_digest_summary))
    default_operator_overview.update(_hybrid_collection_operator_recovery_latency_overview_fields(hybrid_collection_recovery_latency_summary))
    default_operator_overview.update(_hybrid_collection_operator_escalation_priority_mix_trend_overview_fields(hybrid_collection_escalation_priority_mix_trend_summary))
    default_operator_overview.update(_hybrid_collection_operator_escalation_resolution_trend_overview_fields(hybrid_collection_escalation_resolution_trend_summary))
    manual_review_receipt_jobs_summary = _manual_review_receipt_jobs_summary(Path(DATA_DIR))
    manual_review_receipt_operations_summary = _manual_review_receipt_operations_summary(Path(DATA_DIR))
    control_plane_runtime = _manual_review_control_plane_runtime_summary(Path(DATA_DIR))
    if not DB_REPOSITORY.enabled:
        return {
            "seed_stage": {},
            "detail_stage": {},
            "analysis_stage": {},
            "analysis_blockers": {},
            "recommended_actions": default_recommended_actions,
            "action_effectiveness_summary": action_effectiveness_summary,
            "recoverability_summary": recoverability_summary,
            "manual_review_backlog_summary": manual_review_backlog_summary,
            "manual_review_receipt_summary": manual_review_receipt_summary,
            "manual_review_reentry_application_summary": default_manual_review_reentry_application_summary,
            "manual_review_receipt_jobs_summary": manual_review_receipt_jobs_summary,
            "manual_review_receipt_operations_summary": manual_review_receipt_operations_summary,
            **control_plane_runtime,
            "scheduler_feedback_summary": scheduler_feedback_summary,
            "operator_action_summary": default_operator_action_summary,
            "operator_overview": default_operator_overview,
            "hybrid_collection_runtime_summary": hybrid_collection_runtime_summary,
            "hybrid_collection_runtime_history_summary": hybrid_collection_runtime_history_summary,
            "hybrid_collection_action_hint_trend_summary": hybrid_collection_action_hint_trend_summary,
            "hybrid_collection_operator_final_guidance_trend_summary": hybrid_collection_operator_final_guidance_trend_summary,
            "hybrid_collection_operator_final_guidance_stability_summary": hybrid_collection_operator_final_guidance_stability_summary,
            "hybrid_collection_operator_digest_trend_summary": hybrid_collection_operator_digest_trend_summary,
            "hybrid_collection_operator_digest_stability_summary": hybrid_collection_operator_digest_stability_summary,
            "hybrid_collection_operator_intervention_trend_summary": hybrid_collection_operator_intervention_trend_summary,
            "hybrid_collection_strategy_guidance": hybrid_collection_strategy_guidance,
            "hybrid_collection_mode_switch_event_summary": hybrid_collection_mode_switch_event_summary,
            "hybrid_collection_recovery_policy": hybrid_collection_recovery_policy,
            "hybrid_collection_recovery_policy_event_summary": hybrid_collection_recovery_policy_event_summary,
            "hybrid_collection_operator_escalation_event_summary": hybrid_collection_operator_escalation_event_summary,
            "hybrid_collection_operator_escalation_event_trend_summary": hybrid_collection_operator_escalation_event_trend_summary,
            "hybrid_collection_operator_escalation_event_stability_summary": hybrid_collection_operator_escalation_event_stability_summary,
            "hybrid_collection_operator_escalation_recovery_event_summary": hybrid_collection_operator_escalation_recovery_event_summary,
            "hybrid_collection_operator_intervention_event_summary": hybrid_collection_operator_intervention_event_summary,
            "hybrid_collection_unresolved_escalation_window_summary": hybrid_collection_unresolved_escalation_window_summary,
            "hybrid_collection_lifecycle_state_summary": hybrid_collection_lifecycle_state_summary,
            "hybrid_collection_action_hint_consistency_summary": hybrid_collection_action_hint_consistency_summary,
            "hybrid_collection_operator_intervention_stability_summary": hybrid_collection_operator_intervention_stability_summary,
            "hybrid_collection_operator_intervention_policy_summary": hybrid_collection_operator_intervention_policy_summary,
            "hybrid_collection_operator_final_guidance_summary": hybrid_collection_operator_final_guidance_summary,
            "hybrid_collection_operator_digest_summary": hybrid_collection_operator_digest_summary,
            "hybrid_collection_recovery_latency_summary": hybrid_collection_recovery_latency_summary,
            "hybrid_collection_escalation_priority_mix_trend_summary": hybrid_collection_escalation_priority_mix_trend_summary,
            "hybrid_collection_escalation_resolution_trend_summary": hybrid_collection_escalation_resolution_trend_summary,
            "search_tasks": {},
        }
    try:
        stage_counts = DB_REPOSITORY.stage_status_counts() if hasattr(DB_REPOSITORY, "stage_status_counts") else {}
        search_counts = DB_REPOSITORY.search_task_counts() if hasattr(DB_REPOSITORY, "search_task_counts") else {}
        readiness_snapshot = (
            DB_REPOSITORY.analysis_readiness_snapshot()
            if hasattr(DB_REPOSITORY, "analysis_readiness_snapshot")
            else {}
        )
    except Exception:
        stage_counts = {}
        search_counts = {}
        readiness_snapshot = {}
    recommended_actions = recommend_analysis_stage_actions(
        {"analysis_blockers": readiness_snapshot.get("blockers", {})},
        gap_report=recent_gap_report,
        action_effectiveness=action_effectiveness,
        manual_review_receipt_summary=manual_review_receipt_summary,
    )
    manual_review_reentry_application_summary = summarize_manual_review_reentry_application_summary(
        manual_review_receipt_summary,
        {},
        recent_gap_report,
        recent_gap_report,
        {"analysis_blockers": readiness_snapshot.get("blockers", {})},
        {"analysis_blockers": readiness_snapshot.get("blockers", {})},
    )
    operator_action_summary = summarize_operator_action_surface(
        recommended_actions,
        action_effectiveness_summary,
        recoverability_summary,
    )
    operator_action_summary["manual_review_backlog_summary"] = manual_review_backlog_summary
    operator_action_summary["manual_review_receipt_summary"] = manual_review_receipt_summary
    operator_action_summary["manual_review_reentry_application_summary"] = manual_review_reentry_application_summary
    operator_overview = summarize_operator_overview(
        operator_action_summary,
        scheduler_feedback_summary,
    )
    operator_overview.update(_hybrid_collection_operator_overview_fields(hybrid_collection_runtime_summary))
    operator_overview.update(_hybrid_collection_operator_history_overview_fields(hybrid_collection_runtime_history_summary))
    operator_overview.update(_hybrid_collection_operator_action_hint_trend_overview_fields(hybrid_collection_action_hint_trend_summary))
    operator_overview.update(_hybrid_collection_operator_final_guidance_trend_overview_fields(hybrid_collection_operator_final_guidance_trend_summary))
    operator_overview.update(_hybrid_collection_operator_final_guidance_stability_overview_fields(hybrid_collection_operator_final_guidance_stability_summary))
    operator_overview.update(_hybrid_collection_operator_digest_trend_overview_fields(hybrid_collection_operator_digest_trend_summary))
    operator_overview.update(_hybrid_collection_operator_digest_stability_overview_fields(hybrid_collection_operator_digest_stability_summary))
    operator_overview.update(_hybrid_collection_operator_intervention_trend_overview_fields(hybrid_collection_operator_intervention_trend_summary))
    operator_overview.update(_hybrid_collection_operator_guidance_overview_fields(hybrid_collection_strategy_guidance))
    operator_overview.update(_hybrid_collection_operator_mode_switch_overview_fields(hybrid_collection_mode_switch_event_summary))
    operator_overview.update(_hybrid_collection_operator_recovery_policy_overview_fields(hybrid_collection_recovery_policy))
    operator_overview.update(_hybrid_collection_operator_recovery_policy_event_overview_fields(hybrid_collection_recovery_policy_event_summary))
    operator_overview.update(_hybrid_collection_operator_escalation_event_overview_fields(hybrid_collection_operator_escalation_event_summary))
    operator_overview.update(_hybrid_collection_operator_escalation_event_trend_overview_fields(hybrid_collection_operator_escalation_event_trend_summary))
    operator_overview.update(_hybrid_collection_operator_escalation_event_stability_overview_fields(hybrid_collection_operator_escalation_event_stability_summary))
    operator_overview.update(_hybrid_collection_operator_escalation_recovery_event_overview_fields(hybrid_collection_operator_escalation_recovery_event_summary))
    operator_overview.update(_hybrid_collection_operator_intervention_event_overview_fields(hybrid_collection_operator_intervention_event_summary))
    operator_overview.update(_hybrid_collection_operator_unresolved_escalation_window_overview_fields(hybrid_collection_unresolved_escalation_window_summary))
    operator_overview.update(_hybrid_collection_operator_lifecycle_state_overview_fields(hybrid_collection_lifecycle_state_summary))
    operator_overview.update(_hybrid_collection_operator_action_hint_consistency_overview_fields(hybrid_collection_action_hint_consistency_summary))
    operator_overview.update(_hybrid_collection_operator_intervention_stability_overview_fields(hybrid_collection_operator_intervention_stability_summary))
    operator_overview.update(_hybrid_collection_operator_intervention_policy_overview_fields(hybrid_collection_operator_intervention_policy_summary))
    operator_overview.update(_hybrid_collection_operator_final_guidance_overview_fields(hybrid_collection_operator_final_guidance_summary))
    operator_overview.update(_hybrid_collection_operator_digest_overview_fields(hybrid_collection_operator_digest_summary))
    operator_overview.update(_hybrid_collection_operator_recovery_latency_overview_fields(hybrid_collection_recovery_latency_summary))
    operator_overview.update(_hybrid_collection_operator_escalation_priority_mix_trend_overview_fields(hybrid_collection_escalation_priority_mix_trend_summary))
    operator_overview.update(_hybrid_collection_operator_escalation_resolution_trend_overview_fields(hybrid_collection_escalation_resolution_trend_summary))
    return {
        "seed_stage": {"stored": stage_counts.get("seed_stored", 0)},
        "detail_stage": {
            "pending": stage_counts.get("detail_pending", 0),
            "archived": stage_counts.get("detail_archived", 0),
            "enriched": stage_counts.get("detail_enriched", 0),
            "blocked": stage_counts.get("detail_blocked", 0),
            "failed": stage_counts.get("detail_failed", 0),
            "replay_requested": stage_counts.get("detail_replay_requested", 0),
        },
        "analysis_stage": {
            "ready": stage_counts.get("analysis_ready", 0),
            "not_ready": stage_counts.get("analysis_not_ready", 0),
            "invalid": stage_counts.get("analysis_invalid", 0),
        },
        "analysis_blockers": readiness_snapshot.get("blockers", {}),
        "recommended_actions": recommended_actions,
        "action_effectiveness_summary": action_effectiveness_summary,
        "recoverability_summary": recoverability_summary,
        "manual_review_backlog_summary": manual_review_backlog_summary,
        "manual_review_receipt_summary": manual_review_receipt_summary,
        "manual_review_reentry_application_summary": manual_review_reentry_application_summary,
        "manual_review_receipt_jobs_summary": manual_review_receipt_jobs_summary,
        "manual_review_receipt_operations_summary": manual_review_receipt_operations_summary,
        **control_plane_runtime,
        "scheduler_feedback_summary": scheduler_feedback_summary,
        "operator_action_summary": operator_action_summary,
        "operator_overview": operator_overview,
        "hybrid_collection_runtime_summary": hybrid_collection_runtime_summary,
        "hybrid_collection_runtime_history_summary": hybrid_collection_runtime_history_summary,
        "hybrid_collection_action_hint_trend_summary": hybrid_collection_action_hint_trend_summary,
        "hybrid_collection_operator_final_guidance_trend_summary": hybrid_collection_operator_final_guidance_trend_summary,
        "hybrid_collection_operator_final_guidance_stability_summary": hybrid_collection_operator_final_guidance_stability_summary,
        "hybrid_collection_operator_digest_trend_summary": hybrid_collection_operator_digest_trend_summary,
        "hybrid_collection_operator_digest_stability_summary": hybrid_collection_operator_digest_stability_summary,
        "hybrid_collection_operator_intervention_trend_summary": hybrid_collection_operator_intervention_trend_summary,
        "hybrid_collection_strategy_guidance": hybrid_collection_strategy_guidance,
        "hybrid_collection_mode_switch_event_summary": hybrid_collection_mode_switch_event_summary,
        "hybrid_collection_recovery_policy": hybrid_collection_recovery_policy,
        "hybrid_collection_recovery_policy_event_summary": hybrid_collection_recovery_policy_event_summary,
        "hybrid_collection_operator_escalation_event_summary": hybrid_collection_operator_escalation_event_summary,
        "hybrid_collection_operator_escalation_event_trend_summary": hybrid_collection_operator_escalation_event_trend_summary,
        "hybrid_collection_operator_escalation_event_stability_summary": hybrid_collection_operator_escalation_event_stability_summary,
        "hybrid_collection_operator_escalation_recovery_event_summary": hybrid_collection_operator_escalation_recovery_event_summary,
        "hybrid_collection_operator_intervention_event_summary": hybrid_collection_operator_intervention_event_summary,
        "hybrid_collection_unresolved_escalation_window_summary": hybrid_collection_unresolved_escalation_window_summary,
        "hybrid_collection_lifecycle_state_summary": hybrid_collection_lifecycle_state_summary,
        "hybrid_collection_action_hint_consistency_summary": hybrid_collection_action_hint_consistency_summary,
        "hybrid_collection_operator_intervention_stability_summary": hybrid_collection_operator_intervention_stability_summary,
        "hybrid_collection_operator_intervention_policy_summary": hybrid_collection_operator_intervention_policy_summary,
        "hybrid_collection_operator_final_guidance_summary": hybrid_collection_operator_final_guidance_summary,
        "hybrid_collection_operator_digest_summary": hybrid_collection_operator_digest_summary,
        "hybrid_collection_recovery_latency_summary": hybrid_collection_recovery_latency_summary,
        "hybrid_collection_escalation_priority_mix_trend_summary": hybrid_collection_escalation_priority_mix_trend_summary,
        "hybrid_collection_escalation_resolution_trend_summary": hybrid_collection_escalation_resolution_trend_summary,
        "search_tasks": search_counts,
    }

MANUAL_REVIEW_RECEIPT_ENDPOINTS = (
    "/api/avm/manual_review_receipts",
    "/api/analysis/manual_review_receipts",
)

MANUAL_REVIEW_RECEIPT_JOB_ENDPOINTS = (
    "/api/avm/manual_review_receipt_jobs",
    "/api/analysis/manual_review_receipt_jobs",
)

MANUAL_REVIEW_RECEIPT_OPERATION_ENDPOINTS = (
    "/api/avm/manual_review_receipt_operations",
    "/api/analysis/manual_review_receipt_operations",
)

MANUAL_REVIEW_CONTROL_PLANE_STATUS_ENDPOINTS = (
    "/api/avm/manual_review_control_plane_status",
    "/api/analysis/manual_review_control_plane_status",
)

MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIR_ENDPOINTS = (
    "/api/avm/manual_review_control_plane_backup_repairs",
    "/api/analysis/manual_review_control_plane_backup_repairs",
)

MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_ENDPOINTS = (
    "/api/avm/manual_review_control_plane_integrity_history",
    "/api/analysis/manual_review_control_plane_integrity_history",
)

def _manual_review_receipt_store_path(data_root: Path) -> Path:
    return data_root / "avm" / "manual_review_receipts.json"

def _manual_review_receipt_operations_path(data_root: Path) -> Path:
    return data_root / "avm" / "manual_review_receipt_operations.jsonl"

def _manual_review_receipt_jobs_path(data_root: Path) -> Path:
    return data_root / "avm" / "manual_review_receipt_jobs.json"

def _normalize_manual_review_maintenance_options(payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    return {
        "window_days": int(payload.get("window_days", 7) or 7),
        "archive_limit": int(payload.get("archive_limit", 200) or 200),
        "sample_limit": int(payload.get("sample_limit", 20) or 20),
        "replay_limit": int(payload.get("replay_limit", 100) or 100),
        "fetch_limit": int(payload.get("fetch_limit", 20) or 20),
        "fetch_timeout": int(payload.get("fetch_timeout", 15) or 15),
        "reconcile_limit": int(payload.get("reconcile_limit", 200) or 200),
        "dry_run": bool(payload.get("dry_run", False)),
        "extract_risk": bool(payload.get("extract_risk", False)),
        "prepare_replay": bool(payload.get("prepare_replay", False)),
        "fetch_archives": bool(payload.get("fetch_archives", False)),
    }

def _manual_review_receipt_jobs_snapshot(data_root: Path, collection_manager=None) -> dict[str, Any]:
    from src.manual_review_job_view import merge_job_snapshot, persisted_receipts

    legacy = (
        DB_REPOSITORY.manual_review_receipt_jobs_snapshot()
        if DB_REPOSITORY.enabled
        else load_manual_review_receipt_jobs(_manual_review_receipt_jobs_path(data_root))
    )
    receipts = (
        collection_manager.list(operation="manual_review_receipt")
        if collection_manager is not None
        else persisted_receipts(data_root)
    )
    return merge_job_snapshot(legacy, receipts)

def _manual_review_receipt_jobs_summary(data_root: Path) -> dict[str, Any]:
    snapshot = _manual_review_receipt_jobs_snapshot(data_root)
    return summarize_manual_review_receipt_jobs_snapshot(snapshot)

def _manual_review_receipt_operations_summary(data_root: Path) -> dict[str, Any]:
    operations = load_manual_review_receipt_operations(
        _manual_review_receipt_operations_path(data_root),
        limit=200,
        repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
    )
    return summarize_manual_review_receipt_operations_snapshot(operations)

def _manual_review_control_plane_storage(data_root: Path) -> dict[str, Any]:
    return describe_manual_review_control_plane_storage(
        data_root,
        repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
    )

def _manual_review_control_plane_backup(data_root: Path) -> dict[str, Any]:
    return describe_manual_review_control_plane_backup(
        data_root,
        repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None,
    )

def _manual_review_control_plane_backup_repairs_summary(data_root: Path) -> dict[str, Any]:
    return summarize_manual_review_control_plane_backup_repairs(
        load_manual_review_control_plane_backup_repairs(data_root)
    )

def _manual_review_control_plane_integrity(data_root: Path) -> dict[str, Any]:
    integrity = summarize_manual_review_control_plane_integrity(
        _manual_review_control_plane_storage(data_root),
        _manual_review_control_plane_backup(data_root),
        _manual_review_control_plane_backup_repairs_summary(data_root),
    )
    record_manual_review_control_plane_integrity(data_root, integrity)
    return integrity

__all__ = ["_db_collection_stage_snapshot", "MANUAL_REVIEW_RECEIPT_ENDPOINTS", "MANUAL_REVIEW_RECEIPT_JOB_ENDPOINTS", "MANUAL_REVIEW_RECEIPT_OPERATION_ENDPOINTS", "MANUAL_REVIEW_CONTROL_PLANE_STATUS_ENDPOINTS", "MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIR_ENDPOINTS", "MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_ENDPOINTS", "_manual_review_receipt_store_path", "_manual_review_receipt_operations_path", "_manual_review_receipt_jobs_path", "_normalize_manual_review_maintenance_options", "_manual_review_receipt_jobs_snapshot", "_manual_review_receipt_jobs_summary", "_manual_review_receipt_operations_summary", "_manual_review_control_plane_storage", "_manual_review_control_plane_backup", "_manual_review_control_plane_backup_repairs_summary", "_manual_review_control_plane_integrity"]
