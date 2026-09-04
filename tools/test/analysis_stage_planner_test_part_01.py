from tools.test.analysis_stage_planner_test_context import *


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
