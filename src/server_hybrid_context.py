from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def _hybrid_collection_operator_escalation_event_trend_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_source_change_count = _coerce_optional_int(summary.get("recent_source_change_count")) or 0
    if recent_source_change_count < 0:
        recent_source_change_count = 0
    return {
        "hybrid_collection_current_operator_escalation_source": _coerce_optional_text(
            summary.get("current_operator_escalation_source")
        ),
        "hybrid_collection_previous_operator_escalation_source": _coerce_optional_text(
            summary.get("previous_distinct_operator_escalation_source")
        ),
        "hybrid_collection_operator_escalation_source_change_count": recent_source_change_count,
        "hybrid_collection_operator_escalation_source_last_changed_at": _coerce_optional_text(
            summary.get("last_source_change_at")
        ),
    }

def _hybrid_collection_operator_escalation_event_stability_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "hybrid_collection_operator_escalation_source_stability_status": _coerce_optional_text(
            summary.get("stability_status")
        ),
        "hybrid_collection_operator_escalation_source_stability_severity": _coerce_optional_text(
            summary.get("stability_severity")
        ),
        "hybrid_collection_operator_escalation_source_stability_explanation": _coerce_optional_text(
            summary.get("operator_readable_explanation")
        ),
    }

def _hybrid_collection_operator_escalation_recovery_event_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_recovery_count = _coerce_optional_int(summary.get("recent_recovery_count")) or 0
    if recent_recovery_count < 0:
        recent_recovery_count = 0
    return {
        "hybrid_collection_recent_operator_escalation_recovery_count": recent_recovery_count,
        "hybrid_collection_last_operator_escalation_recovery_policy_status": _coerce_optional_text(
            summary.get("last_to_policy_status")
        ),
    }

def _hybrid_collection_operator_unresolved_escalation_window_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    window_open = _coerce_optional_bool(summary.get("window_open")) is True
    duration_seconds = _coerce_optional_int(summary.get("current_window_duration_seconds"))
    if duration_seconds is not None and duration_seconds < 0:
        duration_seconds = None
    duration_minutes = _coerce_optional_float(summary.get("current_window_duration_minutes"))
    if duration_minutes is not None and duration_minutes < 0:
        duration_minutes = None
    return {
        "hybrid_collection_unresolved_escalation_window_open": window_open,
        "hybrid_collection_unresolved_escalation_policy_status": (
            _coerce_optional_text(summary.get("last_escalation_policy_status"))
            if window_open
            else _coerce_optional_text(summary.get("last_recovery_to_policy_status"))
        ),
        "hybrid_collection_unresolved_escalation_last_event_at": (
            _coerce_optional_text(summary.get("last_escalation_at"))
            if window_open
            else _coerce_optional_text(summary.get("last_recovery_at"))
        ),
        "hybrid_collection_unresolved_escalation_duration_seconds": duration_seconds,
        "hybrid_collection_unresolved_escalation_duration_minutes": duration_minutes,
    }

def _hybrid_collection_operator_lifecycle_state_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    active_high_priority_unresolved_count = _coerce_optional_int(summary.get("active_high_priority_unresolved_count"))
    if active_high_priority_unresolved_count is None or active_high_priority_unresolved_count < 0:
        active_high_priority_unresolved_count = 0
    return {
        "hybrid_collection_lifecycle_state": _coerce_optional_text(summary.get("lifecycle_state")),
        "hybrid_collection_lifecycle_reason": _coerce_optional_text(summary.get("lifecycle_reason")),
        "hybrid_collection_lifecycle_follow_up": _coerce_optional_text(summary.get("recommended_follow_up")),
        "hybrid_collection_lifecycle_suggested_mode": _coerce_optional_text(summary.get("suggested_mode")),
        "hybrid_collection_lifecycle_action_hint": _coerce_optional_text(summary.get("operator_action_hint")),
        "hybrid_collection_lifecycle_priority_hint": _coerce_optional_text(summary.get("priority_hint")),
        "hybrid_collection_lifecycle_active_unresolved_priority": _coerce_optional_text(
            summary.get("active_unresolved_priority")
        ),
        "hybrid_collection_lifecycle_active_high_priority_unresolved_count": active_high_priority_unresolved_count,
    }

def _hybrid_collection_operator_action_hint_consistency_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "hybrid_collection_action_hint_consistency_status": _coerce_optional_text(summary.get("consistency_status")),
        "hybrid_collection_action_hint_hints_match": _coerce_optional_bool(summary.get("hints_match")) is True,
        "hybrid_collection_action_hint_drift_reason": _coerce_optional_text(summary.get("drift_reason")),
        "hybrid_collection_action_hint_consistency_severity": _coerce_optional_text(
            summary.get("consistency_severity")
        ),
        "hybrid_collection_action_hint_severity_reason": _coerce_optional_text(summary.get("severity_reason")),
        "hybrid_collection_action_hint_source_preference": _coerce_optional_text(
            summary.get("hint_source_preference")
        ),
        "hybrid_collection_action_hint_source_detail": _coerce_optional_text(
            summary.get("preferred_hint_source_detail")
        ),
        "hybrid_collection_action_hint_explanation": _coerce_optional_text(
            summary.get("preferred_hint_explanation")
        ),
        "hybrid_collection_preferred_action_hint": _coerce_optional_text(summary.get("preferred_operator_action_hint")),
    }

def _hybrid_collection_operator_recovery_latency_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    latency_seconds = _coerce_optional_int(summary.get("last_recovery_latency_seconds"))
    if latency_seconds is not None and latency_seconds < 0:
        latency_seconds = None
    latency_minutes = _coerce_optional_float(summary.get("last_recovery_latency_minutes"))
    if latency_minutes is not None and latency_minutes < 0:
        latency_minutes = None
    return {
        "hybrid_collection_last_recovery_latency_seconds": latency_seconds,
        "hybrid_collection_last_recovery_latency_minutes": latency_minutes,
        "hybrid_collection_last_recovery_latency_from_policy_status": _coerce_optional_text(
            summary.get("last_recovery_from_policy_status")
        ),
        "hybrid_collection_last_recovery_latency_to_policy_status": _coerce_optional_text(
            summary.get("last_recovery_to_policy_status")
        ),
    }

def _hybrid_collection_operator_escalation_resolution_trend_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_resolved_count = _coerce_optional_int(summary.get("recent_resolved_count")) or 0
    if recent_resolved_count < 0:
        recent_resolved_count = 0
    recent_unresolved_count = _coerce_optional_int(summary.get("recent_unresolved_count")) or 0
    if recent_unresolved_count < 0:
        recent_unresolved_count = 0
    recent_resolution_rate = _coerce_optional_float(summary.get("recent_resolution_rate")) or 0.0
    if recent_resolution_rate < 0:
        recent_resolution_rate = 0.0
    elif recent_resolution_rate > 1:
        recent_resolution_rate = 1.0
    return {
        "hybrid_collection_recent_escalation_resolved_count": recent_resolved_count,
        "hybrid_collection_recent_escalation_unresolved_count": recent_unresolved_count,
        "hybrid_collection_recent_escalation_resolution_rate": recent_resolution_rate,
    }

def _hybrid_collection_operator_escalation_priority_mix_trend_overview_fields(summary: dict[str, Any]) -> dict[str, Any]:
    recent_high_priority_escalation_count = (
        _coerce_optional_int(summary.get("recent_high_priority_escalation_count")) or 0
    )
    if recent_high_priority_escalation_count < 0:
        recent_high_priority_escalation_count = 0
    recent_high_priority_resolved_count = _coerce_optional_int(summary.get("recent_high_priority_resolved_count")) or 0
    if recent_high_priority_resolved_count < 0:
        recent_high_priority_resolved_count = 0
    recent_high_priority_unresolved_count = (
        _coerce_optional_int(summary.get("recent_high_priority_unresolved_count")) or 0
    )
    if recent_high_priority_unresolved_count < 0:
        recent_high_priority_unresolved_count = 0
    return {
        "hybrid_collection_recent_high_priority_escalation_count": recent_high_priority_escalation_count,
        "hybrid_collection_recent_high_priority_resolved_count": recent_high_priority_resolved_count,
        "hybrid_collection_recent_high_priority_unresolved_count": recent_high_priority_unresolved_count,
        "hybrid_collection_top_recent_escalation_priority": _coerce_optional_text(
            summary.get("top_recent_escalation_priority")
        ),
        "hybrid_collection_top_recent_unresolved_priority": _coerce_optional_text(
            summary.get("top_recent_unresolved_priority")
        ),
    }

def _avm_operator_eval_summary(data_root: Path, gate_report_override: dict[str, Any] | None = None) -> dict[str, Any]:
    avm_dir = data_root / "avm"
    gate_report = gate_report_override if isinstance(gate_report_override, dict) else _load_json_snapshot(avm_dir / "release_gate.json")
    evaluation = gate_report.get("evaluation") if isinstance(gate_report.get("evaluation"), dict) else {}
    file_calibration_report = normalize_calibration_targets_payload(_load_json_snapshot(avm_dir / "calibration_targets.json"))
    raw_embedded_calibration_report = (
        evaluation.get("calibration_targets") if isinstance(evaluation.get("calibration_targets"), dict) else {}
    )

    def _merge_calibration_targets(preferred: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
        merged = dict(fallback)
        for key, value in preferred.items():
            if isinstance(value, dict) and isinstance(merged.get(key), dict):
                merged[key] = _merge_calibration_targets(value, merged[key])
            else:
                merged[key] = value
        return merged

    calibration_report = (
        normalize_calibration_targets_payload(_merge_calibration_targets(raw_embedded_calibration_report, file_calibration_report))
        if raw_embedded_calibration_report
        else file_calibration_report
    )
    guidance = calibration_report.get("guidance") if isinstance(calibration_report.get("guidance"), dict) else {}
    top_calibration_target = calibration_report.get("top_calibration_target")
    if not isinstance(top_calibration_target, dict):
        top_calibration_target = None
    top_calibration_target_hint = calibration_report.get("top_calibration_target_hint")
    if not isinstance(top_calibration_target_hint, dict):
        top_calibration_target_hint = None

    def _serialize_patch_preview(preview_payload: dict[str, Any], *, bundle_id: str | None = None) -> dict[str, Any]:
        return {
            "bundle_id": bundle_id,
            "patch_ready": bool(preview_payload.get("changed_key_count") or 0),
            "applied_filter": preview_payload.get("applied_filter"),
            "matched_targets": list(preview_payload.get("matched_targets") or []),
            "changed_key_count": int(preview_payload.get("changed_key_count") or 0),
            "changed_keys": list(preview_payload.get("changed_keys") or []),
            "changed_paths": dict(preview_payload.get("changed_paths") or {}),
            "rollback_patch": dict(preview_payload.get("rollback_patch") or {}),
        }

    calibration_preview_path = avm_dir / "calibration_targets.json"
    config_preview_path = avm_dir / "config.json"

    def _json_file_is_object(path: Path) -> bool:
        try:
            if not path.exists():
                return False
            payload = json.loads(path.read_text(encoding="utf-8"))
            return isinstance(payload, dict)
        except Exception:
            return False

    use_temp_calibration_path = (
        not calibration_preview_path.exists()
        or calibration_report != file_calibration_report
        or not _json_file_is_object(calibration_preview_path)
    )
    use_temp_config_path = config_preview_path.exists() and not _json_file_is_object(config_preview_path)

    def _build_preview_bundle(config_path: Path, calibration_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        preview_payload = apply_avm_calibration_patch(
            config_path=config_path,
            calibration_path=calibration_path,
            write_back=False,
        )
        top_preview_payload = apply_avm_calibration_patch(
            config_path=config_path,
            calibration_path=calibration_path,
            write_back=False,
            target_type=str(top_calibration_target.get("target_type") or "") if isinstance(top_calibration_target, dict) else None,
            target_name=str(top_calibration_target.get("name") or "") if isinstance(top_calibration_target, dict) else None,
        )
        recommended_bundle = top_calibration_target_hint.get("recommended_bundle") if isinstance(top_calibration_target_hint, dict) and isinstance(top_calibration_target_hint.get("recommended_bundle"), dict) else None
        if recommended_bundle is not None:
            recommended_bundle_preview_payload = apply_avm_calibration_patch(
                config_path=config_path,
                calibration_path=calibration_path,
                write_back=False,
                target_types=list(recommended_bundle.get("target_types") or []),
                target_names=list(recommended_bundle.get("target_names") or []),
            )
        else:
            recommended_bundle_preview_payload = {}
        return preview_payload, top_preview_payload, recommended_bundle_preview_payload

    if use_temp_calibration_path or use_temp_config_path:
        with tempfile.TemporaryDirectory() as tmpdir:
            if use_temp_calibration_path:
                temp_calibration_path = Path(tmpdir) / "calibration_targets.json"
                temp_calibration_path.write_text(json.dumps(calibration_report, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                temp_calibration_path = calibration_preview_path
            if use_temp_config_path:
                temp_config_path = Path(tmpdir) / "config.json"
                temp_config_path.write_text(json.dumps(DEFAULT_AVM_CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                temp_config_path = config_preview_path
            preview, top_preview, bundle_preview_payload = _build_preview_bundle(temp_config_path, temp_calibration_path)
    else:
        preview, top_preview, bundle_preview_payload = _build_preview_bundle(config_preview_path, calibration_preview_path)

    recommended_bundle = top_calibration_target_hint.get("recommended_bundle") if isinstance(top_calibration_target_hint, dict) and isinstance(top_calibration_target_hint.get("recommended_bundle"), dict) else None
    if recommended_bundle is not None:
        recommended_bundle_patch_preview = _serialize_patch_preview(
            bundle_preview_payload,
            bundle_id=str(recommended_bundle.get("bundle_id") or ""),
        )
    else:
        recommended_bundle_patch_preview = _serialize_patch_preview({}, bundle_id=None)

    def _bundle_command_summary(top_target_hint_payload: dict | None) -> tuple[str, str, str, str]:
        return summarize_bundle_command_summary(top_target_hint_payload)

    (
        recommended_bundle_preview_command,
        recommended_bundle_write_command,
        recommended_bundle_verify_command,
        recommended_bundle_gate_command,
    ) = _bundle_command_summary(top_calibration_target_hint if isinstance(top_calibration_target_hint, dict) else None)
    recommended_bundle_risk = summarize_patch_risk(recommended_bundle_patch_preview)
    recommended_bundle_next_action = summarize_patch_next_action(recommended_bundle_risk, recommended_bundle_patch_preview)
    next_action_command = summarize_patch_next_action_command(
        recommended_bundle_next_action,
        preview_command=recommended_bundle_preview_command,
        write_command=recommended_bundle_write_command,
    )
    follow_up_command = summarize_patch_follow_up_command(
        recommended_bundle_next_action,
        preview_command=recommended_bundle_preview_command,
        write_command=recommended_bundle_write_command,
        verify_command=recommended_bundle_verify_command,
    )
    command_chain = summarize_patch_command_chain(
        next_action_command=str(next_action_command.get("next_action_command") or ""),
        next_action_command_kind=str(next_action_command.get("next_action_command_kind") or "none"),
        follow_up_command=str(follow_up_command.get("follow_up_command") or ""),
        follow_up_command_kind=str(follow_up_command.get("follow_up_command_kind") or "none"),
        verify_command=recommended_bundle_verify_command,
        gate_command=recommended_bundle_gate_command,
    )
    command_chain = resolve_command_chain_artifacts(command_chain, data_root)
    command_chain = apply_command_chain_next_action_policy(
        command_chain,
        next_action=str(recommended_bundle_next_action.get("next_action") or "no_action_required"),
    )
    return {
        "calibration_guidance": {
            "status": str(guidance.get("status") or "unavailable"),
            "priority": str(guidance.get("priority") or "info"),
            "recommended_actions": list(guidance.get("recommended_actions") or []),
            "top_reason": str(guidance.get("top_reason") or ""),
        },
        "calibration_target_counts": {
            "global_risk": len(calibration_report.get("global_risk_targets") or []),
            "risk_factor": len(calibration_report.get("risk_factor_targets") or []),
            "temporal": len(calibration_report.get("temporal_targets") or []),
            "strategy": len(calibration_report.get("strategy_targets") or []),
        },
        "top_calibration_target": top_calibration_target,
        "top_calibration_target_hint": top_calibration_target_hint,
        "calibration_patch_preview": _serialize_patch_preview(preview),
        "top_calibration_patch_preview": _serialize_patch_preview(top_preview),
        "recommended_bundle_patch_preview": recommended_bundle_patch_preview,
        "recommended_bundle_preview_command": recommended_bundle_preview_command,
        "recommended_bundle_write_command": recommended_bundle_write_command,
        "recommended_bundle_verify_command": recommended_bundle_verify_command,
        "recommended_bundle_gate_command": recommended_bundle_gate_command,
        "recommended_bundle_risk_level": str(recommended_bundle_risk.get("risk_level") or "none"),
        "recommended_bundle_risk_reasons": list(recommended_bundle_risk.get("risk_reasons") or []),
        "recommended_bundle_next_action": str(recommended_bundle_next_action.get("next_action") or "no_action_required"),
        "recommended_bundle_next_action_reasons": list(recommended_bundle_next_action.get("next_action_reasons") or []),
        "recommended_bundle_next_action_command": str(next_action_command.get("next_action_command") or ""),
        "recommended_bundle_next_action_command_kind": str(next_action_command.get("next_action_command_kind") or "none"),
        "recommended_bundle_follow_up_command": str(follow_up_command.get("follow_up_command") or ""),
        "recommended_bundle_follow_up_command_kind": str(follow_up_command.get("follow_up_command_kind") or "none"),
        "recommended_bundle_command_chain": command_chain,
        "coordinate_strategy_watchlist": list(evaluation.get("coordinate_strategy_watchlist") or []),
        "top_coordinate_strategy_group": evaluation.get("top_coordinate_strategy_group"),
    }

def _manual_review_receipt_context(data_root: Path) -> dict:
    avm_dir = data_root / "avm"
    action_effectiveness = load_action_effectiveness_snapshot(avm_dir / "data_supply_optimization_loop.json")
    scheduler_progress = load_optimization_loop_progress_snapshot(avm_dir / "data_supply_optimization_loop.json")
    scheduler_feedback_summary = summarize_scheduler_feedback_snapshot(scheduler_progress)
    recent_gap_report = load_recent_gap_audit_snapshot(avm_dir / "recent_gap_audit.json")
    recoverability_summary = summarize_recoverability_snapshot(recent_gap_report)
    manual_review_backlog_summary = summarize_manual_review_backlog(recent_gap_report)
    manual_review_receipt_summary = summarize_manual_review_receipt_snapshot(
        _load_manual_review_receipt_snapshot_for_runtime(data_root),
        manual_review_backlog_summary,
    )
    manual_review_reentry_application_summary = summarize_manual_review_reentry_application_summary(
        manual_review_receipt_summary,
        {},
        recent_gap_report,
        recent_gap_report,
        {"analysis_blockers": {}},
        {"analysis_blockers": {}},
    )
    recommended_actions = recommend_analysis_stage_actions(
        {"analysis_blockers": {}},
        gap_report=recent_gap_report,
        action_effectiveness=action_effectiveness,
        manual_review_receipt_summary=manual_review_receipt_summary,
    )
    action_effectiveness_summary = summarize_action_effectiveness_snapshot(action_effectiveness)
    operator_action_summary = summarize_operator_action_surface(
        recommended_actions,
        action_effectiveness_summary,
        recoverability_summary,
    )
    operator_action_summary["manual_review_backlog_summary"] = manual_review_backlog_summary
    operator_action_summary["manual_review_receipt_summary"] = manual_review_receipt_summary
    operator_action_summary["manual_review_reentry_application_summary"] = manual_review_reentry_application_summary
    operator_overview = summarize_operator_overview(operator_action_summary, scheduler_feedback_summary)
    manual_review_receipt_jobs_summary = _manual_review_receipt_jobs_summary(data_root)
    manual_review_receipt_operations_summary = _manual_review_receipt_operations_summary(data_root)
    control_plane_runtime = _manual_review_control_plane_runtime_summary(data_root)
    return {
        "recommended_actions": recommended_actions,
        "manual_review_backlog_summary": manual_review_backlog_summary,
        "manual_review_receipt_summary": manual_review_receipt_summary,
        "manual_review_reentry_application_summary": manual_review_reentry_application_summary,
        "manual_review_receipt_jobs_summary": manual_review_receipt_jobs_summary,
        "manual_review_receipt_operations_summary": manual_review_receipt_operations_summary,
        **control_plane_runtime,
        "operator_action_summary": operator_action_summary,
        "operator_overview": operator_overview,
        "scheduler_feedback_summary": scheduler_feedback_summary,
    }

def _validate_manual_review_receipt_payload(payload: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    action = payload.get("action")
    ready_signal = payload.get("ready_signal")
    status = payload.get("status")
    receipt_payload = payload.get("payload")
    mode = str(payload.get("mode", "sync") or "sync").lower()
    if not isinstance(action, str) or not action.strip():
        return False, {"code": "AVM_INVALID_RECEIPT_ACTION", "message": "action 为必填非空字符串", "details": {"required": ["action"]}}
    if not isinstance(ready_signal, str) or not ready_signal.strip():
        return False, {"code": "AVM_INVALID_RECEIPT_SIGNAL", "message": "ready_signal 为必填非空字符串", "details": {"required": ["ready_signal"]}}
    if not isinstance(status, str) or not status.strip():
        return False, {"code": "AVM_INVALID_RECEIPT_STATUS", "message": "status 为必填非空字符串", "details": {"required": ["status"]}}
    if not isinstance(receipt_payload, dict):
        return False, {"code": "AVM_INVALID_RECEIPT_PAYLOAD", "message": "payload 必须是对象", "details": {"required": ["payload"]}}
    if mode not in {"sync", "async"}:
        return False, {"code": "AVM_INVALID_RECEIPT_MODE", "message": "mode 只能是 sync 或 async", "details": {"allowed": ["sync", "async"]}}
    return True, None

def _validate_manual_review_receipt_delete_payload(payload: dict[str, Any]) -> tuple[bool, dict[str, Any] | None]:
    action = payload.get("action")
    ready_signal = payload.get("ready_signal")
    if not isinstance(action, str) or not action.strip():
        return False, {"code": "AVM_INVALID_RECEIPT_ACTION", "message": "action 为必填非空字符串", "details": {"required": ["action"]}}
    if not isinstance(ready_signal, str) or not ready_signal.strip():
        return False, {"code": "AVM_INVALID_RECEIPT_SIGNAL", "message": "ready_signal 为必填非空字符串", "details": {"required": ["ready_signal"]}}
    return True, None

__all__ = ["_hybrid_collection_operator_escalation_event_trend_overview_fields", "_hybrid_collection_operator_escalation_event_stability_overview_fields", "_hybrid_collection_operator_escalation_recovery_event_overview_fields", "_hybrid_collection_operator_unresolved_escalation_window_overview_fields", "_hybrid_collection_operator_lifecycle_state_overview_fields", "_hybrid_collection_operator_action_hint_consistency_overview_fields", "_hybrid_collection_operator_recovery_latency_overview_fields", "_hybrid_collection_operator_escalation_resolution_trend_overview_fields", "_hybrid_collection_operator_escalation_priority_mix_trend_overview_fields", "_avm_operator_eval_summary", "_manual_review_receipt_context", "_validate_manual_review_receipt_payload", "_validate_manual_review_receipt_delete_payload"]
