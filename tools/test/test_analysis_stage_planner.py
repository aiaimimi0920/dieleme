from tools.analysis_stage_planner import (
    load_optimization_loop_progress_snapshot,
    load_manual_review_receipt_snapshot,
    load_recent_gap_audit_snapshot,
    recommend_analysis_stage_actions,
    summarize_manual_review_receipt_snapshot,
    summarize_manual_review_reentry_application_summary,
    summarize_manual_review_backlog,
    summarize_operator_overview,
    summarize_scheduler_feedback_snapshot,
    summarize_recoverability_snapshot,
    summarize_action_effectiveness_snapshot,
    summarize_operator_action_surface,
)


def test_recommend_analysis_stage_actions_prioritizes_detail_and_price_blockers():
    plan = recommend_analysis_stage_actions(
        {
            "analysis_blockers": {
                "detail_stage": 5,
                "price_anchor": 3,
                "location_precision": 2,
            }
        }
    )

    assert plan["fetch_archives"] is True
    assert plan["prepare_replay"] is True
    assert plan["coordinate_focus"] is True
    assert plan["suggest_infer_location"] is True
    assert plan["priority_actions"][:3] == ["fetch_archives", "prepare_replay", "coordinate_backfill"]


def test_recommend_analysis_stage_actions_preserves_explicit_fetch_and_replay_flags():
    plan = recommend_analysis_stage_actions(
        {"analysis_blockers": {}},
        fetch_archives=True,
        prepare_replay=True,
    )

    assert plan["fetch_archives"] is True
    assert plan["prepare_replay"] is True
    assert plan["priority_actions"][:2] == ["fetch_archives", "prepare_replay"]


def test_recommend_analysis_stage_actions_uses_gap_report_for_archived_and_coordinate_steps():
    plan = recommend_analysis_stage_actions(
        {
            "analysis_blockers": {
                "detail_stage": 0,
                "price_anchor": 0,
                "location_precision": 0,
            }
        },
        gap_report={
            "detail_archive_present_count": 2,
            "missing_field_counts": {
                "latitude": 3,
                "longitude": 1,
                "is_occupied": 2,
            },
        },
    )

    assert plan["run_archived_backfill"] is True
    assert plan["run_coordinate_backfill"] is True
    assert plan["suggest_extract_risk"] is True
    assert "archived_detail_backfill" in plan["priority_actions"]
    assert "coordinate_backfill" in plan["priority_actions"]


def test_recommend_analysis_stage_actions_deprioritizes_low_yield_coordinate_backfill():
    plan = recommend_analysis_stage_actions(
        {"analysis_blockers": {"location_precision": 3}},
        gap_report={"missing_field_counts": {"latitude": 4, "longitude": 2}},
        action_effectiveness={
            "recent_coordinate_backfill": {
                "executed_rounds": 2,
                "productive_rounds": 0,
            }
        },
    )

    assert plan["coordinate_focus"] is True
    assert plan["run_coordinate_backfill"] is False
    assert plan["suggest_infer_location"] is True
    assert "coordinate_backfill" not in plan["priority_actions"]
    assert "coordinate_backfill" in plan["deprioritized_actions"]


def test_recommend_analysis_stage_actions_deprioritizes_low_yield_fetch_but_keeps_replay():
    plan = recommend_analysis_stage_actions(
        {"analysis_blockers": {"detail_stage": 4, "price_anchor": 2}},
        action_effectiveness={
            "detail_archive_fetch": {
                "executed_rounds": 2,
                "productive_rounds": 0,
            }
        },
    )

    assert plan["fetch_archives"] is False
    assert plan["prepare_replay"] is True
    assert "fetch_archives" not in plan["priority_actions"]
    assert "fetch_archives" in plan["deprioritized_actions"]
    assert "detail_archive_fetch_low_yield" in plan["feedback_hints"]
    assert "prepare_replay" in plan["next_best_alternative_actions"]
    assert plan["operator_summary"]["primary_action"] == "prepare_replay"
    assert plan["fallback_routes"]["fetch_archives"] == "prepare_replay"


def test_recommend_analysis_stage_actions_reopens_risk_path_when_receipt_signal_is_ready():
    plan = recommend_analysis_stage_actions(
        {"analysis_blockers": {}},
        gap_report={
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            "samples": [
                {
                    "item_id": "mr-risk-1",
                    "title": "风险样本",
                    "historical_unrecoverable": True,
                    "analysis_missing_fields": [],
                    "missing_fields": [],
                }
            ],
        },
        manual_review_receipt_summary={
            "top_receipt_status": "ready_for_reentry",
            "matched_ready_signals": ["risk_facts_complete"],
            "top_matched_ready_signal": "risk_facts_complete",
        },
    )

    assert plan["suggest_extract_risk"] is True
    assert "manual_receipt_risk_ready" in plan["feedback_hints"]
    assert "extract_risk" in plan["priority_actions"]


def test_recommend_analysis_stage_actions_reopens_replay_when_detail_receipt_signal_is_ready():
    plan = recommend_analysis_stage_actions(
        {"analysis_blockers": {}},
        manual_review_receipt_summary={
            "top_receipt_status": "ready_for_reentry",
            "matched_ready_signals": ["detail_artifacts_complete"],
            "top_matched_ready_signal": "detail_artifacts_complete",
        },
    )

    assert plan["prepare_replay"] is True
    assert "manual_receipt_detail_ready" in plan["feedback_hints"]
    assert "prepare_replay" in plan["priority_actions"]


def test_recommend_analysis_stage_actions_reopens_analysis_ready_recheck_when_price_receipt_signal_is_ready():
    plan = recommend_analysis_stage_actions(
        {"analysis_blockers": {}},
        manual_review_receipt_summary={
            "top_receipt_status": "ready_for_reentry",
            "matched_ready_signals": ["price_anchor_complete"],
            "top_matched_ready_signal": "price_anchor_complete",
        },
    )

    assert plan["suggest_analysis_ready_recheck"] is True
    assert "manual_receipt_price_ready" in plan["feedback_hints"]
    assert "analysis_ready_recheck" in plan["priority_actions"]


def test_recommend_analysis_stage_actions_reopens_stage_state_reconcile_when_status_receipt_signal_is_ready():
    plan = recommend_analysis_stage_actions(
        {"analysis_blockers": {}},
        manual_review_receipt_summary={
            "top_receipt_status": "ready_for_reentry",
            "matched_ready_signals": ["status_reconciled"],
            "top_matched_ready_signal": "status_reconciled",
        },
    )

    assert plan["suggest_stage_state_reconcile"] is True
    assert "manual_receipt_status_ready" in plan["feedback_hints"]
    assert "stage_state_reconcile" in plan["priority_actions"]


def test_recommend_analysis_stage_actions_deprioritizes_low_yield_replay():
    plan = recommend_analysis_stage_actions(
        {"analysis_blockers": {"detail_stage": 4}},
        action_effectiveness={
            "detail_replay_preparation": {
                "executed_rounds": 2,
                "productive_rounds": 0,
            }
        },
    )

    assert plan["prepare_replay"] is False
    assert "prepare_replay" not in plan["priority_actions"]
    assert "prepare_replay" in plan["deprioritized_actions"]
    assert "detail_replay_preparation_low_yield" in plan["feedback_hints"]
    assert "manual_review" in plan["next_best_alternative_actions"]
    assert plan["manual_review_candidate"] is True
    assert plan["fallback_routes"]["prepare_replay"] == "manual_review"


def test_recommend_analysis_stage_actions_deprioritizes_low_yield_archived_backfill():
    plan = recommend_analysis_stage_actions(
        {"analysis_blockers": {"price_anchor": 2}},
        gap_report={
            "detail_archive_present_count": 4,
            "missing_field_counts": {
                "latitude": 2,
                "is_occupied": 2,
            },
        },
        action_effectiveness={
            "archived_detail_backfill": {
                "executed_rounds": 2,
                "productive_rounds": 0,
            }
        },
    )

    assert plan["run_archived_backfill"] is False
    assert "archived_detail_backfill" not in plan["priority_actions"]
    assert "archived_detail_backfill" in plan["deprioritized_actions"]
    assert "archived_detail_backfill_low_yield" in plan["feedback_hints"]
    assert plan["deprioritized_reason_map"]["archived_detail_backfill"] == "archived_detail_backfill_low_yield"


def test_recommend_analysis_stage_actions_exposes_alternative_actions_for_coordinate_low_yield():
    plan = recommend_analysis_stage_actions(
        {"analysis_blockers": {"location_precision": 3}},
        gap_report={"missing_field_counts": {"latitude": 4, "longitude": 2}},
        action_effectiveness={
            "recent_coordinate_backfill": {
                "executed_rounds": 2,
                "productive_rounds": 0,
            }
        },
    )

    assert "infer_location" in plan["next_best_alternative_actions"]
    assert "coordinate_backfill" in plan["deprioritized_actions"]
    assert plan["operator_summary"]["primary_action"] == "infer_location"


def test_recommend_analysis_stage_actions_marks_historical_unrecoverable_gaps_for_manual_review():
    plan = recommend_analysis_stage_actions(
        {"analysis_blockers": {"detail_stage": 3, "price_anchor": 2}},
        gap_report={
            "detail_archive_present_count": 0,
            "missing_field_counts": {"latitude": 2, "longitude": 2},
            "recoverability_counts": {
                "future_fixable": 0,
                "historical_unrecoverable": 2,
                "archive_backfill_candidate": 0,
                "replay_candidate": 0,
                "coordinate_infer_candidate": 0,
            },
        },
    )

    assert plan["fetch_archives"] is False
    assert plan["prepare_replay"] is False
    assert plan["run_coordinate_backfill"] is False
    assert plan["manual_review_candidate"] is True
    assert "historical_unrecoverable_gap" in plan["feedback_hints"]
    assert "manual_review" in plan["next_best_alternative_actions"]


def test_summarize_action_effectiveness_snapshot_groups_low_yield_and_productive_actions():
    summary = summarize_action_effectiveness_snapshot(
        {
            "detail_archive_fetch": {
                "recommended_rounds": 2,
                "executed_rounds": 2,
                "productive_rounds": 0,
            },
            "archived_detail_backfill": {
                "recommended_rounds": 1,
                "executed_rounds": 1,
                "productive_rounds": 1,
            },
        }
    )

    assert summary["low_yield_actions"] == ["detail_archive_fetch"]
    assert summary["productive_actions"] == ["archived_detail_backfill"]
    assert summary["action_count"] == 2
    assert summary["top_low_yield_action"] == "detail_archive_fetch"
    assert summary["top_productive_action"] == "archived_detail_backfill"
    assert summary["top_low_yield_actions"] == ["detail_archive_fetch"]
    assert summary["top_productive_actions"] == ["archived_detail_backfill"]


def test_summarize_operator_action_surface_exposes_compact_operator_summary():
    action_effectiveness_summary = summarize_action_effectiveness_snapshot(
        {
            "detail_archive_fetch": {
                "recommended_rounds": 2,
                "executed_rounds": 2,
                "productive_rounds": 0,
            },
            "archived_detail_backfill": {
                "recommended_rounds": 1,
                "executed_rounds": 1,
                "productive_rounds": 1,
            },
        }
    )

    summary = summarize_operator_action_surface(
        {
            "operator_summary": {
                "primary_action": "prepare_replay",
                "next_best_alternative_actions": ["prepare_replay", "infer_location", "extract_risk"],
                "top_alternative_action": "prepare_replay",
                "deprioritized_actions": ["fetch_archives"],
                "feedback_hints": ["detail_archive_fetch_low_yield"],
                "manual_review_candidate": True,
            }
        },
        action_effectiveness_summary,
    )

    assert summary["primary_action"] == "prepare_replay"
    assert summary["top_alternative_actions"] == ["prepare_replay", "infer_location", "extract_risk"]
    assert summary["manual_review_candidates"] == ["manual_review"]
    assert summary["top_low_yield_actions"] == ["detail_archive_fetch"]
    assert summary["top_productive_actions"] == ["archived_detail_backfill"]


def test_load_recent_gap_audit_snapshot_and_recoverability_summary(tmp_path):
    report_path = tmp_path / "recent_gap_audit.json"
    report_path.write_text(
        """{
  "recoverability_counts": {
    "future_fixable": 3,
    "historical_unrecoverable": 2,
    "archive_backfill_candidate": 1,
    "replay_candidate": 1,
    "coordinate_infer_candidate": 2
  }
}""",
        encoding="utf-8",
    )

    gap_report = load_recent_gap_audit_snapshot(report_path)
    summary = summarize_recoverability_snapshot(gap_report)

    assert gap_report["recoverability_counts"]["future_fixable"] == 3
    assert summary["future_fixable"] == 3
    assert summary["historical_unrecoverable"] == 2
    assert summary["top_recoverable_actions"] == ["infer_location", "archived_detail_backfill", "prepare_replay"]
    assert summary["top_manual_review_reason"] is None


def test_summarize_operator_action_surface_can_include_recoverability_summary():
    action_effectiveness_summary = summarize_action_effectiveness_snapshot({})
    recoverability_summary = summarize_recoverability_snapshot(
        {
            "recoverability_counts": {
                "future_fixable": 0,
                "historical_unrecoverable": 2,
                "archive_backfill_candidate": 0,
                "replay_candidate": 0,
                "coordinate_infer_candidate": 0,
            }
        }
    )

    summary = summarize_operator_action_surface(
        {
            "operator_summary": {
                "primary_action": None,
                "next_best_alternative_actions": ["manual_review"],
                "top_alternative_actions": ["manual_review"],
                "top_alternative_action": "manual_review",
                "deprioritized_actions": ["fetch_archives"],
                "feedback_hints": ["historical_unrecoverable_gap"],
                "manual_review_candidate": True,
                "manual_review_candidates": ["manual_review"],
            }
        },
        action_effectiveness_summary,
        recoverability_summary,
    )

    assert summary["manual_review_candidates"] == ["manual_review"]
    assert summary["manual_review_required"] is True
    assert summary["recoverability_summary"]["historical_unrecoverable"] == 2
    assert summary["top_manual_review_reason"] == "historical_unrecoverable_gap"


def test_load_optimization_loop_progress_snapshot_and_scheduler_feedback_summary(tmp_path):
    report_path = tmp_path / "data_supply_optimization_loop.json"
    report_path.write_text(
        """{
  "total_progress": {
    "manual_review_candidate_rounds": 2,
    "manual_review_reasons": {
      "historical_unrecoverable_gap": 2
    },
    "top_manual_review_reason": "historical_unrecoverable_gap",
    "human_action_counts": {
      "manual_location_review": 4,
      "manual_price_anchor_review": 1
    },
    "fallback_usage": {
      "fetch_archives": {
        "prepare_replay": 3
      }
    }
  }
}""",
        encoding="utf-8",
    )

    progress = load_optimization_loop_progress_snapshot(report_path)
    summary = summarize_scheduler_feedback_snapshot(progress)

    assert progress["manual_review_candidate_rounds"] == 2
    assert summary["manual_review_candidate_rounds"] == 2
    assert summary["top_manual_review_reason"] == "historical_unrecoverable_gap"
    assert summary["top_fallback_routes"] == ["fetch_archives->prepare_replay"]
    assert summary["top_human_actions"] == ["manual_location_review", "manual_price_anchor_review"]


def test_summarize_manual_review_backlog_extracts_candidate_samples():
    summary = summarize_manual_review_backlog(
        {
            "recoverability_counts": {
                "historical_unrecoverable": 2,
            },
            "samples": [
                {
                    "item_id": "mr-1",
                    "title": "样本1",
                    "historical_unrecoverable": True,
                    "analysis_missing_fields": ["detail_stage", "price_anchor"],
                    "missing_fields": ["latitude", "longitude"],
                },
                {
                    "item_id": "mr-2",
                    "title": "样本2",
                    "historical_unrecoverable": True,
                    "analysis_missing_fields": ["location_precision"],
                    "missing_fields": ["is_occupied"],
                },
                {
                    "item_id": "skip-1",
                    "title": "可恢复样本",
                    "historical_unrecoverable": False,
                },
            ],
        }
    )

    assert summary["candidate_count"] == 2
    assert summary["sample_item_ids"] == ["mr-1", "mr-2"]
    assert summary["sample_titles"] == ["样本1", "样本2"]
    assert summary["reason_buckets"]["manual_location_review"] == 2
    assert summary["reason_buckets"]["manual_price_anchor_review"] == 1
    assert summary["reason_buckets"]["manual_detail_capture_review"] == 1
    assert summary["reason_buckets"]["manual_risk_review"] == 1
    assert summary["top_human_actions"][0] == "manual_location_review"
    assert "full_address" in summary["top_human_action_instructions"][0]
    assert summary["human_action_queues"]["manual_location_review"]["sample_item_ids"] == ["mr-1", "mr-2"]
    assert summary["human_action_queues"]["manual_location_review"]["count"] == 2
    assert summary["human_action_queues"]["manual_location_review"]["expected_reentry_path"] == "infer_location_or_coordinate_backfill"
    assert summary["human_action_queues"]["manual_location_review"]["priority_rank"] == 0
    assert summary["human_action_queues"]["manual_location_review"]["priority_label"] == "high"
    assert summary["human_action_queues"]["manual_location_review"]["suggested_handoff_priority"] == "P0"
    assert "full_address" in summary["human_action_queues"]["manual_location_review"]["queue_level_checklist"][0]
    assert "重新打开" in summary["human_action_queues"]["manual_location_review"]["suggested_handoff_priority_reason"]
    assert "latitude/longitude" in summary["human_action_queues"]["manual_location_review"]["queue_level_completion_criteria"][0]
    assert "coordinate_backfill" in summary["human_action_queues"]["manual_location_review"]["reentry_validation_checklist"][0]
    assert "full_address" in summary["human_action_queues"]["manual_location_review"]["handoff_artifact_fields"]
    assert "坐标" in summary["human_action_queues"]["manual_location_review"]["required_human_evidence"][0]
    assert "location blocker" in summary["human_action_queues"]["manual_location_review"]["reentry_blockers_if_incomplete"][0]
    assert "核对结论" in summary["human_action_queues"]["manual_location_review"]["required_human_resolution_notes"][0]
    assert summary["human_action_queues"]["manual_location_review"]["reentry_ready_signal"] == "location_artifacts_complete"
    assert "full_address" in summary["human_action_queues"]["manual_location_review"]["handoff_completion_payload"]["required_fields"]
    assert "位置相关样本" in summary["human_action_queues"]["manual_location_review"]["queue_level_instruction"]
    assert summary["human_action_queues"]["manual_location_review"]["sample_summaries"][0]["item_id"] == "mr-1"
    assert summary["top_human_reentry_paths"][0] == "infer_location_or_coordinate_backfill"


def test_summarize_operator_overview_flattens_operator_surface_and_scheduler_feedback():
    overview = summarize_operator_overview(
        {
            "primary_action": "prepare_replay",
            "top_alternative_actions": ["prepare_replay", "manual_review"],
            "manual_review_required": True,
            "top_manual_review_reason": "historical_unrecoverable_gap",
            "manual_review_backlog_summary": {
                "top_human_actions": ["manual_location_review", "manual_price_anchor_review"],
                "top_human_action_instructions": [
                    "优先核对 full_address/community_name/business_area，并补 latitude/longitude 或位置层级。",
                    "优先补 transaction_price/starting_price/evaluation_price 等价格锚点，并确认单位。",
                ],
                "sample_item_ids": ["mr-1", "mr-2"],
            },
            "recoverability_summary": {
                "future_fixable": 0,
                "historical_unrecoverable": 2,
                "top_recoverable_actions": [],
            },
            "top_low_yield_actions": ["detail_archive_fetch"],
        },
        {
            "manual_review_candidate_rounds": 2,
            "top_fallback_routes": ["fetch_archives->prepare_replay"],
        },
    )

    assert overview["primary_action"] == "prepare_replay"
    assert overview["manual_review_required"] is True
    assert overview["top_manual_review_reason"] == "historical_unrecoverable_gap"
    assert overview["manual_review_candidate_rounds"] == 2
    assert overview["top_fallback_routes"] == ["fetch_archives->prepare_replay"]
    assert overview["handoff_lifecycle_state"] == "awaiting_human_receipt_hard_stop"
    assert overview["pending_ready_signals"] == ["location_artifacts_complete"]
    assert overview["top_pending_ready_signal"] == "location_artifacts_complete"
    assert overview["handoff_waiting_for_human_receipt"] is True
    assert overview["scheduler_pause_recommended"] is True
    assert overview["resume_on_ready_signal"] == "location_artifacts_complete"
    assert overview["resume_action"] == "infer_location_or_coordinate_backfill"
    assert overview["top_human_actions"] == ["manual_location_review", "manual_price_anchor_review"]
    assert "full_address" in overview["top_human_action_instructions"][0]
    assert overview["manual_review_sample_item_ids"] == ["mr-1", "mr-2"]
    assert overview["handoff_mode"] == "manual_required_hard_stop"
    assert overview["top_human_action_queue"]["action"] == "manual_location_review"
    assert overview["top_human_action_queue"]["expected_reentry_path"] == "infer_location_or_coordinate_backfill"
    assert overview["top_human_action_queue"]["priority_rank"] == 0
    assert overview["top_human_action_queue"]["priority_label"] == "high"
    assert overview["top_human_action_queue"]["suggested_handoff_priority"] == "P0"
    assert "full_address" in overview["top_human_action_queue"]["queue_level_checklist"][0]
    assert "重新打开" in overview["top_human_action_queue"]["suggested_handoff_priority_reason"]
    assert "latitude/longitude" in overview["top_human_action_queue"]["queue_level_completion_criteria"][0]
    assert "coordinate_backfill" in overview["top_human_action_queue"]["reentry_validation_checklist"][0]
    assert "full_address" in overview["top_human_action_queue"]["handoff_artifact_fields"]
    assert "坐标" in overview["top_human_action_queue"]["required_human_evidence"][0]
    assert "location blocker" in overview["top_human_action_queue"]["reentry_blockers_if_incomplete"][0]
    assert "核对结论" in overview["top_human_action_queue"]["required_human_resolution_notes"][0]
    assert overview["top_human_action_queue"]["reentry_ready_signal"] == "location_artifacts_complete"
    assert "full_address" in overview["top_human_action_queue"]["handoff_completion_payload"]["required_fields"]
    assert "位置相关样本" in overview["top_human_action_queue"]["queue_level_instruction"]
    assert overview["top_human_action_queue"]["sample_summaries"][0]["item_id"] == "mr-1"
    assert overview["auto_retry_policy"]["policy"] == "human_fix_required_before_retry"
    assert overview["auto_retry_policy"]["auto_retry_allowed"] is False
    assert overview["auto_retry_policy"]["requires_human_fix_before_retry"] is True


def test_summarize_operator_overview_marks_retryable_retry_policy():
    overview = summarize_operator_overview(
        {
            "primary_action": "prepare_replay",
            "manual_review_required": True,
            "top_manual_review_reason": "historical_unrecoverable_gap",
            "manual_review_backlog_summary": {
                "top_human_actions": ["manual_location_review"],
                "top_human_action_instructions": [
                    "优先核对 full_address/community_name/business_area，并补 latitude/longitude 或位置层级。",
                ],
                "sample_item_ids": ["mr-1"],
            },
            "recoverability_summary": {
                "future_fixable": 2,
                "historical_unrecoverable": 1,
                "top_recoverable_actions": ["prepare_replay"],
            },
        },
        {},
    )

    assert overview["handoff_mode"] == "manual_required_retryable"
    assert overview["auto_retry_policy"]["policy"] == "delayed_retry_with_human_review"
    assert overview["auto_retry_policy"]["auto_retry_allowed"] is True
    assert overview["auto_retry_policy"]["requires_human_fix_before_retry"] is False
    assert overview["handoff_lifecycle_state"] == "awaiting_human_receipt_retryable"
    assert overview["top_pending_ready_signal"] == "location_artifacts_complete"
    assert overview["handoff_waiting_for_human_receipt"] is True
    assert overview["scheduler_pause_recommended"] is True
    assert overview["resume_action"] == "infer_location_or_coordinate_backfill"


def test_load_manual_review_receipt_snapshot_reads_receipts(tmp_path):
    report_path = tmp_path / "manual_review_receipts.json"
    report_path.write_text(
        '{"receipts":[{"action":"manual_location_review","ready_signal":"location_artifacts_complete","status":"ready_for_reentry"}]}',
        encoding="utf-8",
    )

    payload = load_manual_review_receipt_snapshot(report_path)

    assert payload["receipts"][0]["ready_signal"] == "location_artifacts_complete"


def test_summarize_manual_review_receipt_snapshot_surfaces_matched_ready_signals():
    backlog_summary = {
        "top_human_actions": ["manual_location_review"],
        "human_action_queues": {
            "manual_location_review": {
                "reentry_ready_signal": "location_artifacts_complete",
            }
        },
    }

    summary = summarize_manual_review_receipt_snapshot(
        {
            "receipts": [
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {
                        "full_address": "A",
                        "community_name": "B",
                        "business_area": "C",
                        "latitude": 1.0,
                        "longitude": 2.0,
                    },
                }
            ]
        },
        backlog_summary,
    )

    assert summary["receipt_count"] == 1
    assert summary["valid_receipt_count"] == 1
    assert summary["matched_ready_signals"] == ["location_artifacts_complete"]
    assert summary["top_matched_ready_signal"] == "location_artifacts_complete"
    assert summary["top_receipt_status"] == "ready_for_reentry"


def test_summarize_manual_review_receipt_snapshot_flags_incomplete_payload():
    backlog_summary = {
        "top_human_actions": ["manual_location_review"],
        "human_action_queues": {
            "manual_location_review": {
                "reentry_ready_signal": "location_artifacts_complete",
                "handoff_completion_payload": {
                    "required_fields": ["full_address", "community_name", "business_area", "latitude", "longitude"],
                },
            }
        },
    }

    summary = summarize_manual_review_receipt_snapshot(
        {
            "receipts": [
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                }
            ]
        },
        backlog_summary,
    )

    assert summary["top_receipt_status"] == "receipt_incomplete"
    assert summary["invalid_receipt_count"] == 1
    assert summary["top_invalid_receipt_reason"] == "missing_required_fields"
    assert summary["top_receipt_fix_actions"] == ["complete_required_fields"]
    assert "required fields" in summary["receipt_validation_repair_hints"][0]


def test_summarize_manual_review_receipt_snapshot_flags_ready_signal_mismatch():
    backlog_summary = {
        "top_human_actions": ["manual_location_review"],
        "human_action_queues": {
            "manual_location_review": {
                "reentry_ready_signal": "location_artifacts_complete",
                "handoff_completion_payload": {
                    "required_fields": ["full_address", "community_name", "business_area", "latitude", "longitude"],
                },
            }
        },
    }

    summary = summarize_manual_review_receipt_snapshot(
        {
            "receipts": [
                {
                    "action": "manual_location_review",
                    "ready_signal": "wrong_signal",
                    "status": "ready_for_reentry",
                    "payload": {
                        "full_address": "A",
                        "community_name": "B",
                        "business_area": "C",
                        "latitude": 1.0,
                        "longitude": 2.0,
                    },
                }
            ]
        },
        backlog_summary,
    )

    assert summary["top_receipt_status"] == "receipt_incomplete"
    assert summary["top_invalid_receipt_reason"] == "ready_signal_mismatch"


def test_summarize_manual_review_receipt_snapshot_flags_unknown_action():
    backlog_summary = {
        "top_human_actions": ["manual_location_review"],
        "human_action_queues": {
            "manual_location_review": {
                "reentry_ready_signal": "location_artifacts_complete",
            }
        },
    }

    summary = summarize_manual_review_receipt_snapshot(
        {
            "receipts": [
                {
                    "action": "manual_unknown_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                }
            ]
        },
        backlog_summary,
    )

    assert summary["top_receipt_status"] == "receipt_incomplete"
    assert summary["top_invalid_receipt_reason"] == "unknown_action"


def test_summarize_manual_review_receipt_snapshot_flags_receipt_action_not_waiting():
    backlog_summary = {
        "top_human_actions": ["manual_location_review"],
        "human_action_queues": {
            "manual_location_review": {
                "reentry_ready_signal": "location_artifacts_complete",
            }
        },
    }

    summary = summarize_manual_review_receipt_snapshot(
        {
            "receipts": [
                {
                    "action": "manual_price_anchor_review",
                    "ready_signal": "price_anchor_complete",
                    "status": "ready_for_reentry",
                    "payload": {
                        "transaction_price": 1000000,
                        "starting_price": 800000,
                        "evaluation_price": 1200000,
                    },
                }
            ]
        },
        backlog_summary,
    )

    assert summary["top_receipt_status"] == "receipt_incomplete"
    assert summary["top_invalid_receipt_reason"] == "receipt_action_not_waiting"


def test_summarize_manual_review_receipt_snapshot_flags_unsupported_receipt_status():
    backlog_summary = {
        "top_human_actions": ["manual_location_review"],
        "human_action_queues": {
            "manual_location_review": {
                "reentry_ready_signal": "location_artifacts_complete",
                "handoff_completion_payload": {
                    "required_fields": ["full_address", "community_name", "business_area", "latitude", "longitude"],
                },
            }
        },
    }

    summary = summarize_manual_review_receipt_snapshot(
        {
            "receipts": [
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "weird_status",
                    "payload": {
                        "full_address": "A",
                        "community_name": "B",
                        "business_area": "C",
                        "latitude": 1.0,
                        "longitude": 2.0,
                    },
                }
            ]
        },
        backlog_summary,
    )

    assert summary["top_receipt_status"] == "receipt_incomplete"
    assert summary["top_invalid_receipt_reason"] == "unsupported_receipt_status"


def test_summarize_manual_review_receipt_snapshot_flags_malformed_payload():
    backlog_summary = {
        "top_human_actions": ["manual_location_review"],
        "human_action_queues": {
            "manual_location_review": {
                "reentry_ready_signal": "location_artifacts_complete",
                "handoff_completion_payload": {
                    "required_fields": ["full_address", "community_name", "business_area", "latitude", "longitude"],
                },
            }
        },
    }

    summary = summarize_manual_review_receipt_snapshot(
        {
            "receipts": [
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": "not-a-dict",
                }
            ]
        },
        backlog_summary,
    )

    assert summary["top_receipt_status"] == "receipt_incomplete"
    assert summary["top_invalid_receipt_reason"] == "malformed_payload"


def test_summarize_manual_review_receipt_snapshot_flags_duplicate_ready_signal():
    backlog_summary = {
        "top_human_actions": ["manual_location_review"],
        "human_action_queues": {
            "manual_location_review": {
                "reentry_ready_signal": "location_artifacts_complete",
                "handoff_completion_payload": {
                    "required_fields": ["full_address", "community_name", "business_area", "latitude", "longitude"],
                },
            }
        },
    }

    summary = summarize_manual_review_receipt_snapshot(
        {
            "receipts": [
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {
                        "full_address": "A",
                        "community_name": "B",
                        "business_area": "C",
                        "latitude": 1.0,
                        "longitude": 2.0,
                    },
                },
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {
                        "full_address": "A2",
                        "community_name": "B2",
                        "business_area": "C2",
                        "latitude": 3.0,
                        "longitude": 4.0,
                    },
                },
            ]
        },
        backlog_summary,
    )

    assert summary["valid_receipt_count"] == 1
    assert summary["invalid_receipt_count"] == 1
    assert summary["top_invalid_receipt_reason"] == "duplicate_ready_signal"


def test_summarize_manual_review_receipt_snapshot_flags_duplicate_payload_for_same_action():
    backlog_summary = {
        "top_human_actions": ["manual_location_review"],
        "human_action_queues": {
            "manual_location_review": {
                "reentry_ready_signal": "location_artifacts_complete",
                "handoff_completion_payload": {
                    "required_fields": ["full_address", "community_name", "business_area", "latitude", "longitude"],
                },
            }
        },
    }

    payload = {
        "full_address": "A",
        "community_name": "B",
        "business_area": "C",
        "latitude": 1.0,
        "longitude": 2.0,
    }
    summary = summarize_manual_review_receipt_snapshot(
        {
            "receipts": [
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": payload,
                },
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": dict(payload),
                },
            ]
        },
        backlog_summary,
    )

    assert summary["valid_receipt_count"] == 1
    assert summary["invalid_receipt_count"] == 1
    assert summary["top_invalid_receipt_reason"] == "duplicate_payload_for_same_action"


def test_summarize_manual_review_receipt_snapshot_flags_late_receipt_for_closed_queue():
    summary = summarize_manual_review_receipt_snapshot(
        {
            "receipts": [
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {
                        "full_address": "A",
                        "community_name": "B",
                        "business_area": "C",
                        "latitude": 1.0,
                        "longitude": 2.0,
                    },
                }
            ]
        },
        {"top_human_actions": [], "human_action_queues": {}},
    )

    assert summary["top_receipt_status"] == "receipt_incomplete"
    assert summary["top_invalid_receipt_reason"] == "late_receipt_for_closed_queue"


def test_summarize_manual_review_receipt_snapshot_flags_stale_receipt_for_recovered_item():
    summary = summarize_manual_review_receipt_snapshot(
        {
            "receipts": [
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "reentered_auto_pipeline",
                    "payload": {
                        "full_address": "A",
                        "community_name": "B",
                        "business_area": "C",
                        "latitude": 1.0,
                        "longitude": 2.0,
                    },
                }
            ]
        },
        {"top_human_actions": [], "human_action_queues": {}},
    )

    assert summary["top_receipt_status"] == "receipt_incomplete"
    assert summary["top_invalid_receipt_reason"] == "stale_receipt_for_recovered_item"


def test_summarize_operator_overview_transitions_to_receipt_ready_for_reentry():
    overview = summarize_operator_overview(
        {
            "primary_action": "infer_location_or_coordinate_backfill",
            "manual_review_required": True,
            "top_manual_review_reason": "historical_unrecoverable_gap",
            "manual_review_backlog_summary": {
                "top_human_actions": ["manual_location_review"],
                "top_human_action_instructions": [
                    "优先核对 full_address/community_name/business_area，并补 latitude/longitude 或位置层级。",
                ],
                "sample_item_ids": ["mr-1"],
            },
            "manual_review_receipt_summary": {
                "matched_ready_signals": ["location_artifacts_complete"],
                "top_matched_ready_signal": "location_artifacts_complete",
                "top_receipt_status": "ready_for_reentry",
            },
            "recoverability_summary": {
                "future_fixable": 1,
                "historical_unrecoverable": 1,
                "top_recoverable_actions": ["infer_location"],
            },
        },
        {},
    )

    assert overview["handoff_lifecycle_state"] == "receipt_ready_for_reentry"
    assert overview["handoff_waiting_for_human_receipt"] is False
    assert overview["scheduler_pause_recommended"] is False
    assert overview["should_resume_automation"] is True
    assert overview["matched_ready_signals"] == ["location_artifacts_complete"]
    assert overview["top_matched_ready_signal"] == "location_artifacts_complete"


def test_summarize_operator_overview_transitions_to_awaiting_valid_receipt():
    overview = summarize_operator_overview(
        {
            "primary_action": "infer_location_or_coordinate_backfill",
            "manual_review_required": True,
            "top_manual_review_reason": "historical_unrecoverable_gap",
            "manual_review_backlog_summary": {
                "top_human_actions": ["manual_location_review"],
                "top_human_action_instructions": [
                    "优先核对 full_address/community_name/business_area，并补 latitude/longitude 或位置层级。",
                ],
                "sample_item_ids": ["mr-1"],
            },
            "manual_review_receipt_summary": {
                "matched_ready_signals": [],
                "top_receipt_status": "receipt_incomplete",
                "invalid_receipt_count": 1,
                "top_invalid_receipt_reason": "missing_required_fields",
                "top_receipt_fix_actions": ["complete_required_fields"],
                "receipt_validation_repair_hints": [
                    "Complete the required fields for the active handoff queue before resubmitting the receipt.",
                ],
            },
            "recoverability_summary": {
                "future_fixable": 1,
                "historical_unrecoverable": 1,
                "top_recoverable_actions": ["infer_location"],
            },
        },
        {},
    )

    assert overview["handoff_lifecycle_state"] == "awaiting_valid_receipt"
    assert overview["handoff_waiting_for_human_receipt"] is True
    assert overview["scheduler_pause_recommended"] is True
    assert overview["should_resume_automation"] is False
    assert overview["top_invalid_receipt_reason"] == "missing_required_fields"
    assert overview["top_receipt_fix_actions"] == ["complete_required_fields"]
    assert "required fields" in overview["receipt_validation_repair_hints"][0]


def test_summarize_operator_overview_transitions_to_reentered_auto_pipeline():
    overview = summarize_operator_overview(
        {
            "primary_action": "infer_location_or_coordinate_backfill",
            "manual_review_required": False,
            "manual_review_backlog_summary": {"top_human_actions": []},
            "manual_review_receipt_summary": {
                "matched_ready_signals": ["location_artifacts_complete"],
                "top_matched_ready_signal": "location_artifacts_complete",
                "top_receipt_status": "reentered_auto_pipeline",
            },
            "recoverability_summary": {
                "future_fixable": 1,
                "historical_unrecoverable": 0,
                "top_recoverable_actions": ["infer_location"],
            },
        },
        {},
    )

    assert overview["handoff_lifecycle_state"] == "reentered_auto_pipeline"
    assert overview["handoff_waiting_for_human_receipt"] is False
    assert overview["should_resume_automation"] is True


def test_summarize_manual_review_reentry_application_summary_marks_applied():
    summary = summarize_manual_review_reentry_application_summary(
        {
            "top_receipt_status": "ready_for_reentry",
            "matched_ready_signals": ["location_artifacts_complete"],
            "top_matched_ready_signal": "location_artifacts_complete",
        },
        {
            "recent_coordinate_backfill": {"produced_work": True},
            "detail_archive_fetch": {"produced_work": False},
        },
        {"missing_field_counts": {"latitude": 1}},
        {"missing_field_counts": {"latitude": 0}},
        {"analysis_blockers": {"location_precision": 1}},
        {"analysis_blockers": {"location_precision": 0}},
    )

    assert summary["reentry_applied"] is True
    assert summary["top_applied_ready_signal"] == "location_artifacts_complete"
    assert summary["top_applied_action"] == "recent_coordinate_backfill"


def test_summarize_manual_review_reentry_application_summary_marks_confirmed():
    summary = summarize_manual_review_reentry_application_summary(
        {
            "top_receipt_status": "ready_for_reentry",
            "matched_ready_signals": ["location_artifacts_complete"],
            "top_matched_ready_signal": "location_artifacts_complete",
        },
        {
            "recent_coordinate_backfill": {"produced_work": True},
        },
        {"missing_field_counts": {"latitude": 1}},
        {"missing_field_counts": {"latitude": 0}},
        {"analysis_blockers": {"location_precision": 1}, "analysis_ready": 0},
        {"analysis_blockers": {"location_precision": 0}, "analysis_ready": 1},
    )

    assert summary["reentry_applied"] is True
    assert summary["reentry_confirmed"] is True
    assert summary["top_confirmed_ready_signal"] == "location_artifacts_complete"


def test_summarize_operator_overview_transitions_to_reentry_applied():
    overview = summarize_operator_overview(
        {
            "primary_action": "infer_location_or_coordinate_backfill",
            "manual_review_required": True,
            "manual_review_backlog_summary": {
                "top_human_actions": ["manual_location_review"],
                "top_human_action_instructions": [
                    "优先核对 full_address/community_name/business_area，并补 latitude/longitude 或位置层级。",
                ],
            },
            "manual_review_receipt_summary": {
                "matched_ready_signals": ["location_artifacts_complete"],
                "top_matched_ready_signal": "location_artifacts_complete",
                "top_receipt_status": "ready_for_reentry",
            },
            "manual_review_reentry_application_summary": {
                "reentry_applied": True,
                "applied_ready_signals": ["location_artifacts_complete"],
                "top_applied_ready_signal": "location_artifacts_complete",
                "top_applied_action": "recent_coordinate_backfill",
            },
            "recoverability_summary": {
                "future_fixable": 1,
                "historical_unrecoverable": 1,
                "top_recoverable_actions": ["infer_location"],
            },
        },
        {},
    )

    assert overview["handoff_lifecycle_state"] == "reentry_applied"
    assert overview["reentry_applied"] is True
    assert overview["top_applied_ready_signal"] == "location_artifacts_complete"
    assert overview["top_applied_action"] == "recent_coordinate_backfill"
    assert overview["should_resume_automation"] is True


def test_summarize_operator_overview_transitions_to_reentry_confirmed():
    overview = summarize_operator_overview(
        {
            "primary_action": "infer_location_or_coordinate_backfill",
            "manual_review_required": False,
            "manual_review_backlog_summary": {"top_human_actions": ["manual_location_review"]},
            "manual_review_receipt_summary": {
                "matched_ready_signals": ["location_artifacts_complete"],
                "top_matched_ready_signal": "location_artifacts_complete",
                "top_receipt_status": "ready_for_reentry",
            },
            "manual_review_reentry_application_summary": {
                "reentry_applied": True,
                "reentry_confirmed": True,
                "applied_ready_signals": ["location_artifacts_complete"],
                "top_applied_ready_signal": "location_artifacts_complete",
                "applied_actions": ["recent_coordinate_backfill"],
                "top_applied_action": "recent_coordinate_backfill",
                "confirmed_ready_signals": ["location_artifacts_complete"],
                "top_confirmed_ready_signal": "location_artifacts_complete",
            },
            "recoverability_summary": {
                "future_fixable": 1,
                "historical_unrecoverable": 0,
                "top_recoverable_actions": ["infer_location"],
            },
        },
        {},
    )

    assert overview["handoff_lifecycle_state"] == "reentry_confirmed"
    assert overview["reentry_confirmed"] is True
    assert overview["top_confirmed_ready_signal"] == "location_artifacts_complete"
