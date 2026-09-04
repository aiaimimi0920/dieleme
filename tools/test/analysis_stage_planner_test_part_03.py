from tools.test.analysis_stage_planner_test_context import *


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
