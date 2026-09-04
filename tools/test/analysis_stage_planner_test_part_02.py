from tools.test.analysis_stage_planner_test_context import *


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
