from tools.test.run_data_supply_optimization_loop_test_context import *


def test_run_data_supply_optimization_loop_stops_after_idle_rounds(monkeypatch, tmp_path: Path):
    reports = [
        {
            "before": {"missing_field_counts": {"latitude": 3}},
            "after": {"missing_field_counts": {"latitude": 2}},
            "detail_archive_fetch": {"fetched_count": 1, "blocked_count": 0, "failed_count": 0},
            "archived_detail_backfill": {"updated_records": 0},
            "recent_coordinate_backfill": {"updated_count": 0},
            "detail_replay_preparation": {"prepared_count": 0},
        },
        {
            "before": {"missing_field_counts": {"latitude": 2}},
            "after": {"missing_field_counts": {"latitude": 2}},
            "detail_archive_fetch": {"fetched_count": 0, "blocked_count": 1, "failed_count": 0},
            "archived_detail_backfill": {"updated_records": 0},
            "recent_coordinate_backfill": {"updated_count": 0},
            "detail_replay_preparation": {"prepared_count": 0},
        },
        {
            "before": {"missing_field_counts": {"latitude": 2}},
            "after": {"missing_field_counts": {"latitude": 2}},
            "detail_archive_fetch": {"fetched_count": 0, "blocked_count": 1, "failed_count": 0},
            "archived_detail_backfill": {"updated_records": 0},
            "recent_coordinate_backfill": {"updated_count": 0},
            "detail_replay_preparation": {"prepared_count": 0},
        },
    ]
    state = {"index": 0}

    def _fake_maintenance(**kwargs):
        report = reports[min(state["index"], len(reports) - 1)]
        state["index"] += 1
        return report

    monkeypatch.setattr(loop_module, "run_recent_enrich_maintenance", _fake_maintenance)

    result = run_data_supply_optimization_loop(
        data_root=tmp_path / "datas",
        window_days=7,
        archive_limit=10,
        sample_limit=5,
        replay_limit=5,
        fetch_limit=2,
        fetch_timeout=9,
        max_rounds=5,
        idle_stop_rounds=2,
        sleep_seconds=0.0,
        dry_run=True,
        extract_risk=False,
        fetch_archives=True,
        prepare_replay=False,
    )

    assert result["terminate_reason"] == "idle_stop"
    assert result["round_count"] == 3
    assert result["total_progress"]["fetched_count"] == 1
    assert result["total_progress"]["blocked_count"] == 2


def test_run_data_supply_optimization_loop_accumulates_progress(monkeypatch, tmp_path: Path):
    def _fake_maintenance(**kwargs):
        return {
            "before_stage": {"detail_enriched": 10, "analysis_ready": 20, "analysis_blockers": {"price_anchor": 4, "detail_stage": 2}},
            "before": {"missing_field_counts": {"latitude": 4, "longitude": 4}},
            "after_stage": {"detail_enriched": 12, "analysis_ready": 23, "analysis_blockers": {"price_anchor": 2, "detail_stage": 1}},
            "after": {"missing_field_counts": {"latitude": 2, "longitude": 3}},
            "detail_archive_fetch": {"fetched_count": 2, "blocked_count": 0, "failed_count": 1},
            "archived_detail_backfill": {"updated_records": 1},
            "recent_coordinate_backfill": {"updated_count": 1},
            "detail_replay_preparation": {"prepared_count": 3},
        }

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
        extract_risk=True,
        fetch_archives=True,
        prepare_replay=True,
    )

    assert result["terminate_reason"] == "max_rounds_reached"
    assert result["total_progress"]["fetched_count"] == 2
    assert result["total_progress"]["archived_updated_count"] == 1
    assert result["total_progress"]["coordinate_updated_count"] == 1
    assert result["total_progress"]["replay_prepared_count"] == 3
    assert result["total_progress"]["missing_reduction_total"] == 3
    assert result["total_progress"]["detail_enriched_delta"] == 2
    assert result["total_progress"]["analysis_ready_delta"] == 3
    assert result["total_progress"]["analysis_blocker_reduction_total"] == 3
    assert result["total_progress"]["action_effectiveness"]["detail_archive_fetch"]["productive_rounds"] == 1
    assert result["total_progress"]["action_effectiveness"]["archived_detail_backfill"]["productive_rounds"] == 1
    assert result["total_progress"]["action_effectiveness"]["recent_coordinate_backfill"]["productive_rounds"] == 1
    assert result["total_progress"]["action_effectiveness"]["detail_replay_preparation"]["productive_rounds"] == 1


def test_run_data_supply_optimization_loop_plans_round_actions_from_analysis_blockers(monkeypatch, tmp_path: Path):
    maintenance_calls = []

    def _fake_stage_snapshot():
        return {
            "analysis_blockers": {
                "detail_stage": 4,
                "price_anchor": 2,
                "location_precision": 1,
            }
        }

    def _fake_maintenance(**kwargs):
        maintenance_calls.append(kwargs)
        return {
            "before_stage": {"detail_enriched": 5, "analysis_ready": 8, "analysis_blockers": {"detail_stage": 4, "price_anchor": 2, "location_precision": 1}},
            "before": {"missing_field_counts": {"latitude": 3}},
            "after_stage": {"detail_enriched": 6, "analysis_ready": 9, "analysis_blockers": {"detail_stage": 2, "price_anchor": 1, "location_precision": 1}},
            "after": {"missing_field_counts": {"latitude": 2}},
            "detail_archive_fetch": {"fetched_count": 1, "blocked_count": 0, "failed_count": 0},
            "archived_detail_backfill": {"updated_records": 1},
            "recent_coordinate_backfill": {"updated_count": 0},
            "detail_replay_preparation": {"prepared_count": 1},
        }

    monkeypatch.setattr(loop_module, "get_collection_stage_snapshot", _fake_stage_snapshot)
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

    assert maintenance_calls[0]["fetch_archives"] is True
    assert maintenance_calls[0]["prepare_replay"] is True
    assert result["rounds"][0]["plan"]["fetch_archives"] is True
    assert result["rounds"][0]["plan"]["prepare_replay"] is True
    assert result["rounds"][0]["plan"]["analysis_blockers"]["detail_stage"] == 4
    assert result["rounds"][0]["plan"]["suggest_infer_location"] is True
    assert result["rounds"][0]["action_feedback"]["detail_archive_fetch"]["executed"] is True


def test_run_data_supply_optimization_loop_plans_round_actions_from_ready_receipt(monkeypatch, tmp_path: Path):
    maintenance_calls = []

    def _fake_stage_snapshot():
        return {"analysis_blockers": {}}

    def _fake_gap_report(*args, **kwargs):
        return {
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            "samples": [
                {
                    "item_id": "mr-1",
                    "title": "样本1",
                    "historical_unrecoverable": True,
                    "analysis_missing_fields": ["location_precision"],
                    "missing_fields": ["latitude"],
                }
            ],
        }

    def _fake_receipt_snapshot(path=None):
        return {
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
        }

    def _fake_maintenance(**kwargs):
        maintenance_calls.append(kwargs)
        return {
            "before_stage": {"analysis_blockers": {}},
            "before": _fake_gap_report(),
            "after_stage": {"analysis_blockers": {}},
            "after": _fake_gap_report(),
            "detail_archive_fetch": {"skipped": True, "fetched_count": 0, "blocked_count": 0, "failed_count": 0},
            "archived_detail_backfill": {"skipped": True, "updated_records": 0},
            "recent_coordinate_backfill": {"updated_count": 0},
            "detail_replay_preparation": {"skipped": True, "prepared_count": 0},
        }

    monkeypatch.setattr(loop_module, "get_collection_stage_snapshot", _fake_stage_snapshot)
    monkeypatch.setattr(loop_module, "build_recent_gap_audit", _fake_gap_report)
    monkeypatch.setattr(loop_module, "load_manual_review_receipt_snapshot", _fake_receipt_snapshot)
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

    assert maintenance_calls[0]["fetch_archives"] is False
    assert maintenance_calls[0]["prepare_replay"] is False
    assert result["rounds"][0]["plan"]["run_coordinate_backfill"] is True
    assert result["rounds"][0]["plan"]["suggest_infer_location"] is True
    assert "manual_receipt_location_ready" in result["rounds"][0]["plan"]["feedback_hints"]


def test_run_data_supply_optimization_loop_passes_action_effectiveness_into_later_rounds(monkeypatch, tmp_path: Path):
    maintenance_calls = []
    stage_snapshots = [
        {"analysis_blockers": {"location_precision": 2}},
        {"analysis_blockers": {"location_precision": 2}},
    ]
    gap_reports = [
        {"missing_field_counts": {"latitude": 3, "longitude": 1}, "detail_archive_present_count": 0},
        {"missing_field_counts": {"latitude": 3, "longitude": 1}, "detail_archive_present_count": 0},
    ]
    state = {"index": 0}

    def _fake_stage_snapshot():
        return stage_snapshots[min(state["index"], len(stage_snapshots) - 1)]

    def _fake_gap_report(*args, **kwargs):
        return gap_reports[min(state["index"], len(gap_reports) - 1)]

    def _fake_maintenance(**kwargs):
        maintenance_calls.append(kwargs)
        state["index"] += 1
        return {
            "before_stage": {"detail_enriched": 5, "analysis_ready": 8, "analysis_blockers": {"location_precision": 2}},
            "recommended_actions": kwargs.get("action_effectiveness", {}),
            "before": {"missing_field_counts": {"latitude": 3}},
            "after_stage": {"detail_enriched": 5, "analysis_ready": 8, "analysis_blockers": {"location_precision": 2}},
            "after": {"missing_field_counts": {"latitude": 3}},
            "detail_archive_fetch": {"skipped": True, "fetched_count": 0},
            "archived_detail_backfill": {"skipped": True, "updated_records": 0},
            "recent_coordinate_backfill": {"updated_count": 0},
            "detail_replay_preparation": {"skipped": True, "prepared_count": 0},
            "action_feedback": {
                "detail_archive_fetch": {"recommended": False, "executed": False, "produced_work": False},
                "archived_detail_backfill": {"recommended": False, "executed": False, "produced_work": False},
                "recent_coordinate_backfill": {"recommended": True, "executed": True, "produced_work": False},
                "detail_replay_preparation": {"recommended": False, "executed": False, "produced_work": False},
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
        max_rounds=2,
        idle_stop_rounds=2,
        sleep_seconds=0.0,
        dry_run=True,
        extract_risk=False,
        fetch_archives=False,
        prepare_replay=False,
    )

    assert maintenance_calls[0]["action_effectiveness"] == {}
    assert maintenance_calls[1]["action_effectiveness"]["recent_coordinate_backfill"]["executed_rounds"] == 1
    assert maintenance_calls[1]["action_effectiveness"]["recent_coordinate_backfill"]["productive_rounds"] == 0
    assert result["rounds"][1]["plan"]["run_coordinate_backfill"] is True


def test_run_data_supply_optimization_loop_tracks_analysis_side_reconcile_actions(monkeypatch, tmp_path: Path):
    def _fake_stage_snapshot():
        return {"analysis_blockers": {}}

    def _fake_gap_report(*args, **kwargs):
        return {"missing_field_counts": {}, "detail_archive_present_count": 0}

    def _fake_maintenance(**kwargs):
        return {
            "recommended_actions": {
                "fetch_archives": False,
                "run_archived_backfill": False,
                "run_coordinate_backfill": False,
                "prepare_replay": False,
                "suggest_analysis_ready_recheck": True,
                "suggest_stage_state_reconcile": False,
            },
            "before_stage": {"analysis_ready": 0, "analysis_blockers": {"price_anchor": 1}},
            "before": {"missing_field_counts": {}},
            "after_stage": {"analysis_ready": 1, "analysis_blockers": {"price_anchor": 0}},
            "after": {"missing_field_counts": {}},
            "detail_archive_fetch": {"skipped": True, "fetched_count": 0, "blocked_count": 0, "failed_count": 0},
            "archived_detail_backfill": {"skipped": True, "updated_records": 0},
            "recent_coordinate_backfill": {"skipped": True, "updated_count": 0},
            "detail_replay_preparation": {"skipped": True, "prepared_count": 0},
            "analysis_ready_recheck": {"skipped": False, "updated_count": 1},
            "stage_state_reconcile": {"skipped": True, "updated_count": 0},
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

    assert result["rounds"][0]["action_feedback"]["analysis_ready_recheck"]["executed"] is True
    assert result["rounds"][0]["action_feedback"]["analysis_ready_recheck"]["produced_work"] is True
    assert result["total_progress"]["action_effectiveness"]["analysis_ready_recheck"]["productive_rounds"] == 1
