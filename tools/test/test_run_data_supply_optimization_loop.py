from pathlib import Path

from tools import run_data_supply_optimization_loop as loop_module
from tools.run_data_supply_optimization_loop import run_data_supply_optimization_loop


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
