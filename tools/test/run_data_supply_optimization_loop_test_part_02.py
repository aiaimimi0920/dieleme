from tools.test.run_data_supply_optimization_loop_test_context import *


def test_run_data_supply_optimization_loop_accumulates_fallback_usage(monkeypatch, tmp_path: Path):
    def _fake_stage_snapshot():
        return {"analysis_blockers": {"detail_stage": 2, "price_anchor": 1}}

    def _fake_gap_report(*args, **kwargs):
        return {"missing_field_counts": {}, "detail_archive_present_count": 0}

    def _fake_maintenance(**kwargs):
        return {
            "before_stage": {"analysis_blockers": {"detail_stage": 2, "price_anchor": 1}},
            "before": {"missing_field_counts": {}},
            "after_stage": {"analysis_blockers": {"detail_stage": 1}},
            "after": {"missing_field_counts": {}},
            "detail_archive_fetch": {"skipped": True, "fetched_count": 0},
            "archived_detail_backfill": {"skipped": True, "updated_records": 0},
            "recent_coordinate_backfill": {"skipped": True, "updated_count": 0},
            "detail_replay_preparation": {"prepared_count": 1},
            "recommended_actions": {
                "fetch_archives": False,
                "prepare_replay": True,
                "deprioritized_actions": ["fetch_archives"],
                "deprioritized_reason_map": {"fetch_archives": "detail_archive_fetch_low_yield"},
                "fallback_routes": {"fetch_archives": "prepare_replay"},
                "operator_summary": {
                    "primary_action": "prepare_replay",
                    "next_best_alternative_actions": ["prepare_replay"],
                    "top_alternative_action": "prepare_replay",
                    "deprioritized_actions": ["fetch_archives"],
                    "feedback_hints": ["detail_archive_fetch_low_yield"],
                    "manual_review_candidate": False,
                },
            },
            "action_feedback": {
                "detail_archive_fetch": {"recommended": False, "executed": False, "produced_work": False},
                "archived_detail_backfill": {"recommended": False, "executed": False, "produced_work": False},
                "recent_coordinate_backfill": {"recommended": False, "executed": False, "produced_work": False},
                "detail_replay_preparation": {"recommended": True, "executed": True, "produced_work": True},
            },
            "fallback_routes_used": {"fetch_archives": "prepare_replay"},
            "skip_reasons": {"detail_archive_fetch": "deprioritized:detail_archive_fetch_low_yield"},
        }

    monkeypatch.setattr(loop_module, "get_collection_stage_snapshot", _fake_stage_snapshot)
    monkeypatch.setattr(loop_module, "build_recent_gap_audit", _fake_gap_report)
    monkeypatch.setattr(loop_module, "run_recent_enrich_maintenance", _fake_maintenance)

    result = run_data_supply_optimization_loop(
        data_root=tmp_path / "datas",
        window_days=7,
        archive_limit=10,
        sample_limit=5,
        replay_limit=5,
        fetch_limit=2,
        fetch_timeout=9,
        max_rounds=1,
        idle_stop_rounds=2,
        sleep_seconds=0.0,
        dry_run=True,
        extract_risk=False,
        fetch_archives=False,
        prepare_replay=False,
    )

    assert result["rounds"][0]["fallback_routes_used"]["fetch_archives"] == "prepare_replay"
    assert result["total_progress"]["fallback_usage"]["fetch_archives"]["prepare_replay"] == 1


def test_run_data_supply_optimization_loop_stops_when_no_recoverable_candidates_remain(monkeypatch, tmp_path: Path):
    def _fake_stage_snapshot():
        return {"analysis_blockers": {"detail_stage": 2, "price_anchor": 1}}

    def _fake_gap_report(*args, **kwargs):
        return {
            "missing_field_counts": {"latitude": 2, "longitude": 2},
            "detail_archive_present_count": 0,
            "recoverability_counts": {
                "future_fixable": 0,
                "historical_unrecoverable": 2,
                "archive_backfill_candidate": 0,
                "replay_candidate": 0,
                "coordinate_infer_candidate": 0,
            },
        }

    def _fake_maintenance(**kwargs):
        return {
            "before_stage": {"analysis_blockers": {"detail_stage": 2, "price_anchor": 1}},
            "before": _fake_gap_report(),
            "after_stage": {"analysis_blockers": {"detail_stage": 2, "price_anchor": 1}},
            "after": _fake_gap_report(),
            "detail_archive_fetch": {"skipped": True, "fetched_count": 0, "blocked_count": 0, "failed_count": 0},
            "archived_detail_backfill": {"skipped": True, "updated_records": 0},
            "recent_coordinate_backfill": {"skipped": True, "updated_count": 0},
            "detail_replay_preparation": {"skipped": True, "prepared_count": 0},
            "recommended_actions": {
                "manual_review_candidate": True,
                "feedback_hints": ["historical_unrecoverable_gap"],
                "deprioritized_actions": [],
                "fallback_routes": {},
                "operator_summary": {
                    "primary_action": None,
                    "next_best_alternative_actions": ["manual_review"],
                    "top_alternative_actions": ["manual_review"],
                    "top_alternative_action": "manual_review",
                    "deprioritized_actions": [],
                    "feedback_hints": ["historical_unrecoverable_gap"],
                    "manual_review_candidate": True,
                    "manual_review_candidates": ["manual_review"],
                },
            },
            "action_feedback": {
                "detail_archive_fetch": {"recommended": False, "executed": False, "produced_work": False},
                "archived_detail_backfill": {"recommended": False, "executed": False, "produced_work": False},
                "recent_coordinate_backfill": {"recommended": False, "executed": False, "produced_work": False},
                "detail_replay_preparation": {"recommended": False, "executed": False, "produced_work": False},
            },
            "fallback_routes_used": {},
            "skip_reasons": {
                "detail_archive_fetch": "not_recommended",
                "archived_detail_backfill": "not_recommended",
                "recent_coordinate_backfill": "not_recommended",
                "detail_replay_preparation": "not_recommended",
            },
            "manual_review_backlog_summary": {
                "top_human_actions": ["manual_location_review"],
                "human_action_queues": {
                    "manual_location_review": {
                        "count": 2,
                        "instruction": "优先核对 full_address/community_name/business_area，并补 latitude/longitude 或位置层级。",
                        "expected_reentry_path": "infer_location_or_coordinate_backfill",
                        "sample_item_ids": ["mr-1", "mr-2"],
                    }
                },
            },
            "operator_overview": {
                "manual_review_required": True,
                "top_manual_review_reason": "historical_unrecoverable_gap",
                "handoff_mode": "manual_required_hard_stop",
                "handoff_lifecycle_state": "awaiting_human_receipt_hard_stop",
                "pending_ready_signals": ["location_artifacts_complete"],
                "top_pending_ready_signal": "location_artifacts_complete",
                "top_human_actions": ["manual_location_review"],
                "auto_retry_policy": {
                    "policy": "human_fix_required_before_retry",
                    "auto_retry_allowed": False,
                    "requires_human_fix_before_retry": True,
                },
            },
        }

    monkeypatch.setattr(loop_module, "get_collection_stage_snapshot", _fake_stage_snapshot)
    monkeypatch.setattr(loop_module, "build_recent_gap_audit", _fake_gap_report)
    monkeypatch.setattr(loop_module, "run_recent_enrich_maintenance", _fake_maintenance)

    result = run_data_supply_optimization_loop(
        data_root=tmp_path / "datas",
        window_days=7,
        archive_limit=10,
        sample_limit=5,
        replay_limit=5,
        fetch_limit=2,
        fetch_timeout=9,
        max_rounds=3,
        idle_stop_rounds=2,
        sleep_seconds=0.0,
        dry_run=True,
        extract_risk=False,
        fetch_archives=False,
        prepare_replay=False,
    )

    assert result["terminate_reason"] == "no_recoverable_candidates"
    assert result["round_count"] == 1
    assert result["total_progress"]["manual_review_candidate_rounds"] == 1
    assert result["total_progress"]["manual_review_reasons"]["historical_unrecoverable_gap"] == 1
    assert result["total_progress"]["top_manual_review_reason"] == "historical_unrecoverable_gap"
    assert result["total_progress"]["handoff_mode_counts"]["manual_required_hard_stop"] == 1
    assert result["total_progress"]["top_handoff_mode"] == "manual_required_hard_stop"
    assert result["total_progress"]["human_action_counts"]["manual_location_review"] == 2
    assert result["total_progress"]["top_human_actions"] == ["manual_location_review"]
    assert result["total_progress"]["retry_policy_counts"]["human_fix_required_before_retry"] == 1
    assert result["total_progress"]["top_retry_policy"] == "human_fix_required_before_retry"
    assert result["total_progress"]["handoff_lifecycle_counts"]["awaiting_human_receipt_hard_stop"] == 1
    assert result["total_progress"]["top_handoff_lifecycle_state"] == "awaiting_human_receipt_hard_stop"
    assert result["total_progress"]["pending_ready_signal_counts"]["location_artifacts_complete"] == 1
    assert result["total_progress"]["top_pending_ready_signal"] == "location_artifacts_complete"


def test_run_data_supply_optimization_loop_terminates_on_handoff_hard_stop(monkeypatch, tmp_path: Path):
    def _fake_stage_snapshot():
        return {"analysis_blockers": {"detail_stage": 1}}

    def _fake_gap_report(*args, **kwargs):
        return {
            "missing_field_counts": {"latitude": 1},
            "detail_archive_present_count": 0,
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
        }

    def _fake_maintenance(**kwargs):
        return {
            "before_stage": {"analysis_blockers": {"detail_stage": 1}},
            "before": _fake_gap_report(),
            "after_stage": {"analysis_blockers": {"detail_stage": 1}},
            "after": _fake_gap_report(),
            "detail_archive_fetch": {"skipped": True, "fetched_count": 0, "blocked_count": 0, "failed_count": 0},
            "archived_detail_backfill": {"skipped": True, "updated_records": 0},
            "recent_coordinate_backfill": {"skipped": True, "updated_count": 0},
            "detail_replay_preparation": {"skipped": True, "prepared_count": 0},
            "operator_overview": {
                "manual_review_required": True,
                "top_manual_review_reason": "historical_unrecoverable_gap",
                "handoff_mode": "manual_required_hard_stop",
                "handoff_lifecycle_state": "awaiting_human_receipt_hard_stop",
                "pending_ready_signals": ["location_artifacts_complete"],
                "top_pending_ready_signal": "location_artifacts_complete",
                "handoff_waiting_for_human_receipt": True,
                "scheduler_pause_recommended": True,
                "resume_on_ready_signal": "location_artifacts_complete",
                "resume_action": "infer_location_or_coordinate_backfill",
                "auto_retry_policy": {
                    "policy": "human_fix_required_before_retry",
                    "auto_retry_allowed": False,
                    "requires_human_fix_before_retry": True,
                },
            },
            "manual_review_backlog_summary": {
                "top_human_actions": ["manual_location_review"],
                "human_action_queues": {
                    "manual_location_review": {
                        "count": 1,
                        "reentry_ready_signal": "location_artifacts_complete",
                    }
                },
            },
        }

    monkeypatch.setattr(loop_module, "get_collection_stage_snapshot", _fake_stage_snapshot)
    monkeypatch.setattr(loop_module, "build_recent_gap_audit", _fake_gap_report)
    monkeypatch.setattr(loop_module, "run_recent_enrich_maintenance", _fake_maintenance)

    result = run_data_supply_optimization_loop(
        data_root=tmp_path / "datas",
        window_days=7,
        archive_limit=10,
        sample_limit=5,
        replay_limit=5,
        fetch_limit=2,
        fetch_timeout=9,
        max_rounds=3,
        idle_stop_rounds=2,
        sleep_seconds=0.0,
        dry_run=True,
        extract_risk=False,
        fetch_archives=False,
        prepare_replay=False,
    )

    assert result["terminate_reason"] == "awaiting_human_receipt_hard_stop"
    assert result["round_count"] == 1


def test_run_data_supply_optimization_loop_terminates_on_handoff_retryable_wait(monkeypatch, tmp_path: Path):
    def _fake_stage_snapshot():
        return {"analysis_blockers": {"location_precision": 1}}

    def _fake_gap_report(*args, **kwargs):
        return {
            "missing_field_counts": {"latitude": 1},
            "detail_archive_present_count": 0,
            "recoverability_counts": {"future_fixable": 2, "historical_unrecoverable": 1},
        }

    def _fake_maintenance(**kwargs):
        return {
            "before_stage": {"analysis_blockers": {"location_precision": 1}},
            "before": _fake_gap_report(),
            "after_stage": {"analysis_blockers": {"location_precision": 1}},
            "after": _fake_gap_report(),
            "detail_archive_fetch": {"skipped": True, "fetched_count": 0, "blocked_count": 0, "failed_count": 0},
            "archived_detail_backfill": {"skipped": True, "updated_records": 0},
            "recent_coordinate_backfill": {"skipped": True, "updated_count": 0},
            "detail_replay_preparation": {"skipped": True, "prepared_count": 0},
            "operator_overview": {
                "manual_review_required": True,
                "top_manual_review_reason": "historical_unrecoverable_gap",
                "handoff_mode": "manual_required_retryable",
                "handoff_lifecycle_state": "awaiting_human_receipt_retryable",
                "pending_ready_signals": ["location_artifacts_complete"],
                "top_pending_ready_signal": "location_artifacts_complete",
                "handoff_waiting_for_human_receipt": True,
                "scheduler_pause_recommended": True,
                "resume_on_ready_signal": "location_artifacts_complete",
                "resume_action": "infer_location_or_coordinate_backfill",
                "auto_retry_policy": {
                    "policy": "delayed_retry_with_human_review",
                    "auto_retry_allowed": True,
                    "requires_human_fix_before_retry": False,
                },
            },
            "manual_review_backlog_summary": {
                "top_human_actions": ["manual_location_review"],
                "human_action_queues": {
                    "manual_location_review": {
                        "count": 1,
                        "reentry_ready_signal": "location_artifacts_complete",
                    }
                },
            },
        }

    monkeypatch.setattr(loop_module, "get_collection_stage_snapshot", _fake_stage_snapshot)
    monkeypatch.setattr(loop_module, "build_recent_gap_audit", _fake_gap_report)
    monkeypatch.setattr(loop_module, "run_recent_enrich_maintenance", _fake_maintenance)

    result = run_data_supply_optimization_loop(
        data_root=tmp_path / "datas",
        window_days=7,
        archive_limit=10,
        sample_limit=5,
        replay_limit=5,
        fetch_limit=2,
        fetch_timeout=9,
        max_rounds=3,
        idle_stop_rounds=2,
        sleep_seconds=0.0,
        dry_run=True,
        extract_risk=False,
        fetch_archives=False,
        prepare_replay=False,
    )

    assert result["terminate_reason"] == "awaiting_human_receipt_retryable"
    assert result["round_count"] == 1
