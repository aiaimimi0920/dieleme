from tools.test.run_recent_enrich_maintenance_test_context import *


def test_run_recent_enrich_maintenance_executes_stage_state_reconcile_when_status_receipt_is_ready(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "datas"
    data_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(maintenance_module, "get_collection_stage_snapshot", lambda: {"analysis_blockers": {}})
    monkeypatch.setattr(
        maintenance_module,
        "build_recent_gap_audit",
        lambda *args, **kwargs: {
            "missing_field_counts": {},
            "detail_archive_present_count": 0,
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            "samples": [
                {
                    "item_id": "mr-status-1",
                    "title": "状态样本",
                    "historical_unrecoverable": True,
                    "analysis_missing_fields": ["status"],
                    "missing_fields": [],
                }
            ],
        },
    )
    monkeypatch.setattr(
        maintenance_module,
        "load_manual_review_receipt_snapshot",
        lambda path=None: {
            "receipts": [
                {
                    "action": "manual_status_review",
                    "ready_signal": "status_reconciled",
                    "status": "ready_for_reentry",
                    "payload": {
                        "status": "done",
                        "status_at": "2026-03-05 10:00:00",
                    },
                }
            ]
        },
    )
    monkeypatch.setattr(maintenance_module, "fetch_missing_detail_archives", lambda **kwargs: {"skipped": True, "fetched_count": 0})
    monkeypatch.setattr(maintenance_module, "backfill_archived_details", lambda **kwargs: {"skipped": True, "updated_records": 0})
    monkeypatch.setattr(maintenance_module, "backfill_recent_coordinates", lambda **kwargs: {"skipped": True, "updated_count": 0})
    monkeypatch.setattr(maintenance_module, "prepare_recent_detail_replay", lambda **kwargs: {"skipped": True, "prepared_count": 0})
    called = {}

    def _reconcile(**kwargs):
        called["mode"] = kwargs["mode"]
        return {
            "mode": kwargs["mode"],
            "candidate_count": 1,
            "scanned_count": 1,
            "updated_count": 1,
            "analysis_stage_transition_count": 1,
            "analysis_ready_transition_count": 1,
            "detail_stage_transition_count": 0,
            "samples": [{"item_id": "mr-status-1"}],
            "skipped": False,
        }

    monkeypatch.setattr(maintenance_module, "run_analysis_stage_reconcile", _reconcile)

    report = run_recent_enrich_maintenance(
        data_root=data_root,
        window_days=7,
        archive_limit=10,
        sample_limit=5,
        dry_run=False,
        extract_risk=False,
    )

    assert called["mode"] == "stage_state_reconcile"
    assert report["recommended_actions"]["suggest_stage_state_reconcile"] is True
    assert report["stage_state_reconcile"]["updated_count"] == 1
    assert report["action_feedback"]["stage_state_reconcile"]["executed"] is True
    assert report["action_feedback"]["stage_state_reconcile"]["produced_work"] is True


def test_run_recent_enrich_maintenance_marks_analysis_side_sections_repository_unavailable_when_repo_disabled(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "datas"
    data_root.mkdir(parents=True, exist_ok=True)

    class _DisabledRepo:
        enabled = False

    monkeypatch.setattr(maintenance_module, "create_repository_from_env", lambda: _DisabledRepo())
    monkeypatch.setattr(maintenance_module, "get_collection_stage_snapshot", lambda: {"analysis_blockers": {}})
    monkeypatch.setattr(
        maintenance_module,
        "build_recent_gap_audit",
        lambda *args, **kwargs: {
            "missing_field_counts": {},
            "detail_archive_present_count": 0,
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            "samples": [
                {
                    "item_id": "mr-price-2",
                    "title": "价格样本",
                    "historical_unrecoverable": True,
                    "analysis_missing_fields": ["price_anchor"],
                    "missing_fields": [],
                }
            ],
        },
    )
    monkeypatch.setattr(
        maintenance_module,
        "load_manual_review_receipt_snapshot",
        lambda path=None: {
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
    )
    monkeypatch.setattr(maintenance_module, "fetch_missing_detail_archives", lambda **kwargs: {"skipped": True, "fetched_count": 0})
    monkeypatch.setattr(maintenance_module, "backfill_archived_details", lambda **kwargs: {"skipped": True, "updated_records": 0})
    monkeypatch.setattr(maintenance_module, "backfill_recent_coordinates", lambda **kwargs: {"skipped": True, "updated_count": 0})
    monkeypatch.setattr(maintenance_module, "prepare_recent_detail_replay", lambda **kwargs: {"skipped": True, "prepared_count": 0})

    report = run_recent_enrich_maintenance(
        data_root=data_root,
        window_days=7,
        archive_limit=10,
        sample_limit=5,
        dry_run=False,
        extract_risk=False,
    )

    assert report["recommended_actions"]["suggest_analysis_ready_recheck"] is True
    assert report["analysis_ready_recheck"]["skipped"] is True
    assert report["analysis_ready_recheck"]["skip_reason"] == "repository_unavailable"


def test_run_recent_enrich_maintenance_uses_action_effectiveness_to_deprioritize_coordinate_backfill(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "datas"
    data_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(maintenance_module, "get_collection_stage_snapshot", lambda: {"analysis_blockers": {"location_precision": 2}})
    monkeypatch.setattr(
        maintenance_module,
        "build_recent_gap_audit",
        lambda *args, **kwargs: {
            "missing_field_counts": {"latitude": 3, "longitude": 1},
            "detail_archive_present_count": 0,
        },
    )
    monkeypatch.setattr(maintenance_module, "fetch_missing_detail_archives", lambda **kwargs: {"skipped": True, "fetched_count": 0})
    monkeypatch.setattr(maintenance_module, "backfill_archived_details", lambda **kwargs: {"skipped": True, "updated_records": 0})
    monkeypatch.setattr(maintenance_module, "prepare_recent_detail_replay", lambda **kwargs: {"skipped": True, "prepared_count": 0})

    coordinate_called = {"value": False}

    def _coordinate(**kwargs):
        coordinate_called["value"] = True
        return {"updated_count": 0}

    monkeypatch.setattr(maintenance_module, "backfill_recent_coordinates", _coordinate)

    report = run_recent_enrich_maintenance(
        data_root=data_root,
        window_days=7,
        archive_limit=10,
        sample_limit=5,
        dry_run=False,
        extract_risk=False,
        action_effectiveness={
            "recent_coordinate_backfill": {
                "executed_rounds": 2,
                "productive_rounds": 0,
            }
        },
    )

    assert coordinate_called["value"] is False
    assert report["recommended_actions"]["coordinate_focus"] is True
    assert report["recommended_actions"]["run_coordinate_backfill"] is False
    assert report["recommended_actions"]["suggest_infer_location"] is True
    assert "coordinate_backfill" in report["recommended_actions"]["deprioritized_actions"]
    assert report["recent_coordinate_backfill"]["skipped"] is True


def test_run_recent_enrich_maintenance_uses_action_effectiveness_to_deprioritize_fetch(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "datas"
    data_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(maintenance_module, "get_collection_stage_snapshot", lambda: {"analysis_blockers": {"detail_stage": 2, "price_anchor": 1}})
    monkeypatch.setattr(
        maintenance_module,
        "build_recent_gap_audit",
        lambda *args, **kwargs: {"missing_field_counts": {}, "detail_archive_present_count": 0},
    )

    fetch_called = {"value": False}
    replay_called = {"value": False}

    def _fetch(**kwargs):
        fetch_called["value"] = True
        return {"fetched_count": 0}

    def _replay(**kwargs):
        replay_called["value"] = True
        return {"prepared_count": 1}

    monkeypatch.setattr(maintenance_module, "fetch_missing_detail_archives", _fetch)
    monkeypatch.setattr(maintenance_module, "backfill_archived_details", lambda **kwargs: {"skipped": True, "updated_records": 0})
    monkeypatch.setattr(maintenance_module, "backfill_recent_coordinates", lambda **kwargs: {"skipped": True, "updated_count": 0})
    monkeypatch.setattr(maintenance_module, "prepare_recent_detail_replay", _replay)

    report = run_recent_enrich_maintenance(
        data_root=data_root,
        window_days=7,
        archive_limit=10,
        sample_limit=5,
        dry_run=False,
        extract_risk=False,
        action_effectiveness={
            "detail_archive_fetch": {
                "executed_rounds": 2,
                "productive_rounds": 0,
            }
        },
    )

    assert fetch_called["value"] is False
    assert replay_called["value"] is True
    assert report["recommended_actions"]["fetch_archives"] is False
    assert report["recommended_actions"]["prepare_replay"] is True
    assert "fetch_archives" in report["recommended_actions"]["deprioritized_actions"]
    assert report["fallback_routes_used"]["fetch_archives"] == "prepare_replay"
    assert report["skip_reasons"]["detail_archive_fetch"] == "deprioritized:detail_archive_fetch_low_yield"
    assert report["operator_action_summary"]["primary_action"] == "prepare_replay"
    assert report["operator_action_summary"]["top_alternative_actions"][0] == "prepare_replay"


def test_run_recent_enrich_maintenance_surfaces_manual_review_for_unrecoverable_gap(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "datas"
    data_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(maintenance_module, "get_collection_stage_snapshot", lambda: {"analysis_blockers": {"detail_stage": 2, "price_anchor": 1}})
    monkeypatch.setattr(
        maintenance_module,
        "build_recent_gap_audit",
        lambda *args, **kwargs: {
            "missing_field_counts": {"latitude": 2, "longitude": 2},
            "detail_archive_present_count": 0,
            "recoverability_counts": {
                "future_fixable": 0,
                "historical_unrecoverable": 2,
                "archive_backfill_candidate": 0,
                "replay_candidate": 0,
                "coordinate_infer_candidate": 0,
            },
            "samples": [
                {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": ["detail_stage"], "missing_fields": ["latitude"]},
                {"item_id": "mr-2", "title": "样本2", "historical_unrecoverable": True, "analysis_missing_fields": ["price_anchor"], "missing_fields": ["is_occupied"]},
            ],
        },
    )
    monkeypatch.setattr(maintenance_module, "fetch_missing_detail_archives", lambda **kwargs: {"skipped": True, "fetched_count": 0})
    monkeypatch.setattr(maintenance_module, "backfill_archived_details", lambda **kwargs: {"skipped": True, "updated_records": 0})
    monkeypatch.setattr(maintenance_module, "backfill_recent_coordinates", lambda **kwargs: {"skipped": True, "updated_count": 0})
    monkeypatch.setattr(maintenance_module, "prepare_recent_detail_replay", lambda **kwargs: {"skipped": True, "prepared_count": 0})

    report = run_recent_enrich_maintenance(
        data_root=data_root,
        window_days=7,
        archive_limit=10,
        sample_limit=5,
        dry_run=False,
        extract_risk=False,
    )

    assert report["recommended_actions"]["manual_review_candidate"] is True
    assert "historical_unrecoverable_gap" in report["recommended_actions"]["feedback_hints"]
    assert report["operator_action_summary"]["manual_review_candidates"] == ["manual_review"]
    assert report["operator_action_summary"]["manual_review_required"] is True
    assert report["recoverability_summary"]["historical_unrecoverable"] == 2
    assert report["next_recoverability_summary"]["historical_unrecoverable"] == 2
    assert report["manual_review_backlog_summary"]["candidate_count"] == 2
    assert report["manual_review_backlog_summary"]["sample_item_ids"] == ["mr-1", "mr-2"]
    assert report["manual_review_backlog_summary"]["top_human_actions"][0] == "manual_location_review"
    assert "full_address" in report["manual_review_backlog_summary"]["top_human_action_instructions"][0]
    assert report["manual_review_backlog_summary"]["human_action_queues"]["manual_location_review"]["count"] == 2
    assert report["manual_review_backlog_summary"]["human_action_queues"]["manual_location_review"]["priority_label"] == "high"
    assert report["manual_review_backlog_summary"]["human_action_queues"]["manual_location_review"]["suggested_handoff_priority"] == "P0"
    assert "full_address" in report["manual_review_backlog_summary"]["human_action_queues"]["manual_location_review"]["queue_level_checklist"][0]
    assert "重新打开" in report["manual_review_backlog_summary"]["human_action_queues"]["manual_location_review"]["suggested_handoff_priority_reason"]
    assert "latitude/longitude" in report["manual_review_backlog_summary"]["human_action_queues"]["manual_location_review"]["queue_level_completion_criteria"][0]
    assert "coordinate_backfill" in report["manual_review_backlog_summary"]["human_action_queues"]["manual_location_review"]["reentry_validation_checklist"][0]
    assert "full_address" in report["manual_review_backlog_summary"]["human_action_queues"]["manual_location_review"]["handoff_artifact_fields"]
    assert "坐标" in report["manual_review_backlog_summary"]["human_action_queues"]["manual_location_review"]["required_human_evidence"][0]
    assert "location blocker" in report["manual_review_backlog_summary"]["human_action_queues"]["manual_location_review"]["reentry_blockers_if_incomplete"][0]
    assert "核对结论" in report["manual_review_backlog_summary"]["human_action_queues"]["manual_location_review"]["required_human_resolution_notes"][0]
    assert report["manual_review_backlog_summary"]["human_action_queues"]["manual_location_review"]["reentry_ready_signal"] == "location_artifacts_complete"
    assert "full_address" in report["manual_review_backlog_summary"]["human_action_queues"]["manual_location_review"]["handoff_completion_payload"]["required_fields"]
    assert report["operator_overview"]["manual_review_required"] is True
    assert report["operator_overview"]["top_human_actions"][0] == "manual_location_review"
    assert "full_address" in report["operator_overview"]["top_human_action_instructions"][0]
    assert report["operator_overview"]["handoff_mode"] == "manual_required_hard_stop"
    assert report["operator_overview"]["top_human_action_queue"]["expected_reentry_path"] == "infer_location_or_coordinate_backfill"
    assert report["operator_overview"]["top_human_action_queue"]["priority_label"] == "high"
    assert report["operator_overview"]["top_human_action_queue"]["suggested_handoff_priority"] == "P0"
    assert "full_address" in report["operator_overview"]["top_human_action_queue"]["queue_level_checklist"][0]
    assert "重新打开" in report["operator_overview"]["top_human_action_queue"]["suggested_handoff_priority_reason"]
    assert "latitude/longitude" in report["operator_overview"]["top_human_action_queue"]["queue_level_completion_criteria"][0]
    assert "coordinate_backfill" in report["operator_overview"]["top_human_action_queue"]["reentry_validation_checklist"][0]
    assert "full_address" in report["operator_overview"]["top_human_action_queue"]["handoff_artifact_fields"]
    assert "坐标" in report["operator_overview"]["top_human_action_queue"]["required_human_evidence"][0]
    assert "location blocker" in report["operator_overview"]["top_human_action_queue"]["reentry_blockers_if_incomplete"][0]
    assert "核对结论" in report["operator_overview"]["top_human_action_queue"]["required_human_resolution_notes"][0]
    assert report["operator_overview"]["top_human_action_queue"]["reentry_ready_signal"] == "location_artifacts_complete"
    assert "full_address" in report["operator_overview"]["top_human_action_queue"]["handoff_completion_payload"]["required_fields"]
    assert report["skip_reasons"]["detail_archive_fetch"] == "deprioritized:no_recoverable_detail_source"


def test_run_recent_enrich_maintenance_marks_reentry_applied_when_receipt_ready_and_progress_occurs(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "datas"
    data_root.mkdir(parents=True, exist_ok=True)

    stage_state = {"index": 0}

    def _fake_stage_snapshot():
        snapshots = [
            {"analysis_blockers": {"location_precision": 1}},
            {"analysis_blockers": {"location_precision": 0}},
        ]
        value = snapshots[min(stage_state["index"], len(snapshots) - 1)]
        stage_state["index"] += 1
        return value

    gap_state = {"index": 0}

    def _fake_gap_report(*args, **kwargs):
        reports = [
            {
                "missing_field_counts": {"latitude": 1},
                "detail_archive_present_count": 0,
                "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
                "samples": [
                    {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": ["location_precision"], "missing_fields": ["latitude"]},
                ],
            },
            {
                "missing_field_counts": {"latitude": 0},
                "detail_archive_present_count": 0,
                "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
                "samples": [
                    {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": [], "missing_fields": []},
                ],
            },
        ]
        value = reports[min(gap_state["index"], len(reports) - 1)]
        gap_state["index"] += 1
        return value

    monkeypatch.setattr(maintenance_module, "get_collection_stage_snapshot", _fake_stage_snapshot)
    monkeypatch.setattr(
        maintenance_module,
        "build_recent_gap_audit",
        _fake_gap_report,
    )
    monkeypatch.setattr(
        maintenance_module,
        "load_manual_review_receipt_snapshot",
        lambda path=None: {
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
    )
    monkeypatch.setattr(maintenance_module, "fetch_missing_detail_archives", lambda **kwargs: {"skipped": True, "fetched_count": 0})
    monkeypatch.setattr(maintenance_module, "backfill_archived_details", lambda **kwargs: {"skipped": True, "updated_records": 0})
    monkeypatch.setattr(maintenance_module, "backfill_recent_coordinates", lambda **kwargs: {"updated_count": 1})
    monkeypatch.setattr(maintenance_module, "prepare_recent_detail_replay", lambda **kwargs: {"skipped": True, "prepared_count": 0})

    report = run_recent_enrich_maintenance(
        data_root=data_root,
        window_days=7,
        archive_limit=10,
        sample_limit=5,
        dry_run=False,
        extract_risk=False,
    )

    assert report["manual_review_reentry_application_summary"]["reentry_applied"] is True
    assert report["operator_overview"]["top_applied_ready_signal"] == "location_artifacts_complete"
    assert report["manual_review_reentry_application_summary"]["reentry_confirmed"] is True
    assert report["operator_overview"]["handoff_lifecycle_state"] == "reentry_confirmed"
    assert report["operator_overview"]["top_confirmed_ready_signal"] == "location_artifacts_complete"
