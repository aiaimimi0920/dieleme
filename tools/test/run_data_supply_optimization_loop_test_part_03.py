from tools.test.run_data_supply_optimization_loop_test_context import *


def test_run_data_supply_optimization_loop_continues_after_receipt_ready_for_reentry(monkeypatch, tmp_path: Path):
    reports = [
        {
            "before_stage": {"analysis_blockers": {"location_precision": 1}},
            "before": {
                "missing_field_counts": {"latitude": 1},
                "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            },
            "after_stage": {"analysis_blockers": {"location_precision": 1}},
            "after": {
                "missing_field_counts": {"latitude": 1},
                "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            },
            "detail_archive_fetch": {"skipped": True, "fetched_count": 0, "blocked_count": 0, "failed_count": 0},
            "archived_detail_backfill": {"skipped": True, "updated_records": 0},
            "recent_coordinate_backfill": {"skipped": True, "updated_count": 0},
            "detail_replay_preparation": {"skipped": True, "prepared_count": 0},
            "manual_review_backlog_summary": {
                "top_human_actions": ["manual_location_review"],
                "human_action_queues": {"manual_location_review": {"count": 1, "reentry_ready_signal": "location_artifacts_complete"}},
            },
            "manual_review_receipt_summary": {
                "matched_ready_signals": ["location_artifacts_complete"],
                "top_matched_ready_signal": "location_artifacts_complete",
                "top_receipt_status": "ready_for_reentry",
            },
            "manual_review_reentry_application_summary": {
                "reentry_applied": False,
                "applied_ready_signals": [],
                "top_applied_ready_signal": None,
                "top_applied_action": None,
            },
            "operator_overview": {
                "handoff_lifecycle_state": "receipt_ready_for_reentry",
                "handoff_waiting_for_human_receipt": False,
                "scheduler_pause_recommended": False,
                "should_resume_automation": True,
                "resume_on_ready_signal": "location_artifacts_complete",
                "resume_action": "infer_location_or_coordinate_backfill",
                "matched_ready_signals": ["location_artifacts_complete"],
                "top_matched_ready_signal": "location_artifacts_complete",
                "auto_retry_policy": {"policy": "continue_immediately", "auto_retry_allowed": True},
            },
        },
        {
            "before_stage": {"analysis_blockers": {"location_precision": 1}},
            "before": {"missing_field_counts": {"latitude": 1}},
            "after_stage": {"analysis_blockers": {"location_precision": 0}},
            "after": {"missing_field_counts": {"latitude": 0}},
            "detail_archive_fetch": {"skipped": True, "fetched_count": 0, "blocked_count": 0, "failed_count": 0},
            "archived_detail_backfill": {"skipped": True, "updated_records": 0},
            "recent_coordinate_backfill": {"updated_count": 1},
            "detail_replay_preparation": {"skipped": True, "prepared_count": 0},
            "manual_review_reentry_application_summary": {
                "reentry_applied": True,
                "reentry_confirmed": True,
                "applied_ready_signals": ["location_artifacts_complete"],
                "top_applied_ready_signal": "location_artifacts_complete",
                "top_applied_action": "recent_coordinate_backfill",
                "confirmed_ready_signals": ["location_artifacts_complete"],
                "top_confirmed_ready_signal": "location_artifacts_complete",
            },
            "operator_overview": {
                "handoff_lifecycle_state": "reentry_confirmed",
                "handoff_waiting_for_human_receipt": False,
                "scheduler_pause_recommended": False,
                "should_resume_automation": True,
                "matched_ready_signals": ["location_artifacts_complete"],
                "top_matched_ready_signal": "location_artifacts_complete",
                "auto_retry_policy": {"policy": "continue_immediately", "auto_retry_allowed": True},
            },
        },
    ]
    state = {"index": 0}

    def _fake_stage_snapshot():
        return {"analysis_blockers": {"location_precision": 1}}

    def _fake_gap_report(*args, **kwargs):
        return {"missing_field_counts": {"latitude": 1}, "detail_archive_present_count": 0}

    def _fake_maintenance(**kwargs):
        report = reports[min(state["index"], len(reports) - 1)]
        state["index"] += 1
        return report

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
        max_rounds=2,
        idle_stop_rounds=1,
        sleep_seconds=0.0,
        dry_run=True,
        extract_risk=False,
        fetch_archives=False,
        prepare_replay=False,
    )

    assert result["round_count"] == 2
    assert result["rounds"][0]["report"]["operator_overview"]["handoff_lifecycle_state"] == "receipt_ready_for_reentry"
    assert result["rounds"][1]["progress"]["coordinate_updated_count"] == 1
    assert result["total_progress"]["reentry_applied_rounds"] == 1
    assert result["total_progress"]["applied_ready_signal_counts"]["location_artifacts_complete"] == 1
    assert result["total_progress"]["top_reentry_applied_signal"] == "location_artifacts_complete"
    assert result["total_progress"]["reentry_confirmed_rounds"] == 1
    assert result["total_progress"]["confirmed_ready_signal_counts"]["location_artifacts_complete"] == 1
    assert result["total_progress"]["top_reentry_confirmed_signal"] == "location_artifacts_complete"


def test_run_data_supply_optimization_loop_continues_after_reentry_confirmed(monkeypatch, tmp_path: Path):
    reports = [
        {
            "before_stage": {"analysis_blockers": {"location_precision": 0}},
            "before": {"missing_field_counts": {"latitude": 0}},
            "after_stage": {"analysis_blockers": {"location_precision": 0}},
            "after": {"missing_field_counts": {"latitude": 0}},
            "detail_archive_fetch": {"skipped": True, "fetched_count": 0, "blocked_count": 0, "failed_count": 0},
            "archived_detail_backfill": {"skipped": True, "updated_records": 0},
            "recent_coordinate_backfill": {"updated_count": 0},
            "detail_replay_preparation": {"skipped": True, "prepared_count": 0},
            "manual_review_reentry_application_summary": {
                "reentry_applied": True,
                "reentry_confirmed": True,
                "applied_ready_signals": ["location_artifacts_complete"],
                "top_applied_ready_signal": "location_artifacts_complete",
                "top_applied_action": "recent_coordinate_backfill",
                "confirmed_ready_signals": ["location_artifacts_complete"],
                "top_confirmed_ready_signal": "location_artifacts_complete",
            },
            "operator_overview": {
                "handoff_lifecycle_state": "reentry_confirmed",
                "handoff_waiting_for_human_receipt": False,
                "scheduler_pause_recommended": False,
                "should_resume_automation": True,
                "matched_ready_signals": ["location_artifacts_complete"],
                "top_matched_ready_signal": "location_artifacts_complete",
                "auto_retry_policy": {"policy": "continue_immediately", "auto_retry_allowed": True},
            },
        },
        {
            "before_stage": {"analysis_blockers": {"location_precision": 0}},
            "before": {"missing_field_counts": {"latitude": 0}},
            "after_stage": {"analysis_blockers": {"location_precision": 0}},
            "after": {"missing_field_counts": {"latitude": 0}},
            "detail_archive_fetch": {"skipped": True, "fetched_count": 0, "blocked_count": 0, "failed_count": 0},
            "archived_detail_backfill": {"skipped": True, "updated_records": 0},
            "recent_coordinate_backfill": {"updated_count": 1},
            "detail_replay_preparation": {"skipped": True, "prepared_count": 0},
        },
    ]
    state = {"index": 0}

    def _fake_stage_snapshot():
        return {"analysis_blockers": {}}

    def _fake_gap_report(*args, **kwargs):
        return {"missing_field_counts": {"latitude": 0}, "detail_archive_present_count": 0}

    def _fake_maintenance(**kwargs):
        report = reports[min(state["index"], len(reports) - 1)]
        state["index"] += 1
        return report

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
        max_rounds=2,
        idle_stop_rounds=1,
        sleep_seconds=0.0,
        dry_run=True,
        extract_risk=False,
        fetch_archives=False,
        prepare_replay=False,
    )

    assert result["round_count"] == 2
    assert result["rounds"][0]["report"]["operator_overview"]["handoff_lifecycle_state"] == "reentry_confirmed"
    assert result["rounds"][1]["progress"]["coordinate_updated_count"] == 1


def test_run_data_supply_optimization_loop_terminates_on_awaiting_valid_receipt(monkeypatch, tmp_path: Path):
    def _fake_stage_snapshot():
        return {"analysis_blockers": {"location_precision": 1}}

    def _fake_gap_report(*args, **kwargs):
        return {
            "missing_field_counts": {"latitude": 1},
            "detail_archive_present_count": 0,
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
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
            "manual_review_backlog_summary": {
                "top_human_actions": ["manual_location_review"],
                "human_action_queues": {"manual_location_review": {"count": 1, "reentry_ready_signal": "location_artifacts_complete"}},
            },
            "manual_review_receipt_summary": {
                "top_receipt_status": "receipt_incomplete",
                "invalid_receipt_count": 1,
                "top_invalid_receipt_reason": "missing_required_fields",
            },
            "operator_overview": {
                "handoff_lifecycle_state": "awaiting_valid_receipt",
                "handoff_waiting_for_human_receipt": True,
                "scheduler_pause_recommended": True,
                "should_resume_automation": False,
                "top_invalid_receipt_reason": "missing_required_fields",
                "auto_retry_policy": {"policy": "human_fix_required_before_retry", "auto_retry_allowed": False},
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

    assert result["terminate_reason"] == "awaiting_valid_receipt"
    assert result["total_progress"]["invalid_receipt_reason_counts"]["missing_required_fields"] == 1
    assert result["total_progress"]["top_invalid_receipt_reason"] == "missing_required_fields"
