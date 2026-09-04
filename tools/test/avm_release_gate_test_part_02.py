from tools.test.avm_release_gate_test_context import *


def test_release_gate_analysis_readiness_can_surface_manual_review_fallback(monkeypatch, tmp_path: Path):
    data_root = tmp_path / "datas"
    _write_month(
        data_root,
        "2025-01",
        [
            {
                "id": "1002",
                "url": "https://x/1002",
                "成交价格": "100万",
                "起拍价格": "90万",
                "建筑面积": "100㎡",
                "交易时间": "2025-01-01 10:00:00",
                "城市": "上海市",
                "区": "浦东新区",
            }
        ],
    )

    monkeypatch.setattr(
        gate_module,
        "load_action_effectiveness_snapshot",
        lambda path=None: {
            "detail_replay_preparation": {
                "executed_rounds": 2,
                "productive_rounds": 0,
            }
        },
    )

    report = generate_release_gate_report(
        data_root=data_root,
        eval_report_path=tmp_path / "eval_report.json",
        gate_report_path=tmp_path / "gate_report.json",
        window_days=7,
        min_sample_size=1,
        smoke_sample_size=1,
    )

    recommended = report["analysis_readiness"]["recommended_actions"]
    assert recommended["manual_review_candidate"] is True
    assert recommended["fallback_routes"]["prepare_replay"] == "manual_review"
    operator_summary = report["analysis_readiness"]["operator_action_summary"]
    assert operator_summary["manual_review_candidates"] == ["manual_review"]


def test_release_gate_analysis_readiness_can_surface_recoverability_summary(monkeypatch, tmp_path: Path):
    data_root = tmp_path / "datas"
    _write_month(
        data_root,
        "2025-01",
        [
            {
                "id": "1003",
                "url": "https://x/1003",
                "成交价格": "100万",
                "起拍价格": "90万",
                "建筑面积": "100㎡",
                "交易时间": "2025-01-01 10:00:00",
                "城市": "上海市",
                "区": "浦东新区",
            }
        ],
    )

    monkeypatch.setattr(
        gate_module,
        "build_recent_gap_audit",
        lambda data_root, window_days, sample_limit: {
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
    monkeypatch.setattr(
        gate_module,
        "load_optimization_loop_progress_snapshot",
        lambda path=None: {
            "manual_review_candidate_rounds": 2,
            "manual_review_reasons": {"historical_unrecoverable_gap": 2},
            "top_manual_review_reason": "historical_unrecoverable_gap",
            "human_action_counts": {"manual_location_review": 4, "manual_price_anchor_review": 1},
            "retry_policy_counts": {"human_fix_required_before_retry": 2},
            "top_retry_policy": "human_fix_required_before_retry",
            "handoff_lifecycle_counts": {"awaiting_human_receipt_hard_stop": 2},
            "top_handoff_lifecycle_state": "awaiting_human_receipt_hard_stop",
            "pending_ready_signal_counts": {"location_artifacts_complete": 2},
            "top_pending_ready_signal": "location_artifacts_complete",
            "invalid_receipt_reason_counts": {"missing_required_fields": 2},
            "top_invalid_receipt_reason": "missing_required_fields",
            "fallback_usage": {"fetch_archives": {"prepare_replay": 3}},
        },
    )

    report = generate_release_gate_report(
        data_root=data_root,
        eval_report_path=tmp_path / "eval_report.json",
        gate_report_path=tmp_path / "gate_report.json",
        window_days=7,
        min_sample_size=1,
        smoke_sample_size=1,
    )

    recoverability = report["analysis_readiness"]["recoverability_summary"]
    assert recoverability["future_fixable"] == 0
    assert recoverability["historical_unrecoverable"] == 2
    operator_summary = report["analysis_readiness"]["operator_action_summary"]
    assert operator_summary["top_manual_review_reason"] == "historical_unrecoverable_gap"
    assert operator_summary["manual_review_required"] is True
    scheduler_summary = report["analysis_readiness"]["scheduler_feedback_summary"]
    assert scheduler_summary["manual_review_candidate_rounds"] == 2
    assert scheduler_summary["top_fallback_routes"] == ["fetch_archives->prepare_replay"]
    assert scheduler_summary["top_human_actions"] == ["manual_location_review", "manual_price_anchor_review"]
    assert scheduler_summary["top_retry_policy"] == "human_fix_required_before_retry"
    assert scheduler_summary["top_handoff_lifecycle_state"] == "awaiting_human_receipt_hard_stop"
    assert scheduler_summary["top_pending_ready_signal"] == "location_artifacts_complete"
    assert scheduler_summary["top_invalid_receipt_reason"] == "missing_required_fields"
    backlog_summary = report["analysis_readiness"]["manual_review_backlog_summary"]
    assert backlog_summary["candidate_count"] == 2
    assert backlog_summary["sample_item_ids"] == ["mr-1", "mr-2"]
    assert backlog_summary["top_human_actions"][0] == "manual_location_review"
    assert "full_address" in backlog_summary["top_human_action_instructions"][0]
    assert backlog_summary["human_action_queues"]["manual_location_review"]["count"] == 2
    assert backlog_summary["human_action_queues"]["manual_location_review"]["expected_reentry_path"] == "infer_location_or_coordinate_backfill"
    assert backlog_summary["human_action_queues"]["manual_location_review"]["priority_label"] == "high"
    assert backlog_summary["human_action_queues"]["manual_location_review"]["suggested_handoff_priority"] == "P0"
    assert "full_address" in backlog_summary["human_action_queues"]["manual_location_review"]["queue_level_checklist"][0]
    assert "重新打开" in backlog_summary["human_action_queues"]["manual_location_review"]["suggested_handoff_priority_reason"]
    assert "latitude/longitude" in backlog_summary["human_action_queues"]["manual_location_review"]["queue_level_completion_criteria"][0]
    assert "coordinate_backfill" in backlog_summary["human_action_queues"]["manual_location_review"]["reentry_validation_checklist"][0]
    assert "full_address" in backlog_summary["human_action_queues"]["manual_location_review"]["handoff_artifact_fields"]
    assert "坐标" in backlog_summary["human_action_queues"]["manual_location_review"]["required_human_evidence"][0]
    assert "location blocker" in backlog_summary["human_action_queues"]["manual_location_review"]["reentry_blockers_if_incomplete"][0]
    assert "核对结论" in backlog_summary["human_action_queues"]["manual_location_review"]["required_human_resolution_notes"][0]
    assert backlog_summary["human_action_queues"]["manual_location_review"]["reentry_ready_signal"] == "location_artifacts_complete"
    assert "full_address" in backlog_summary["human_action_queues"]["manual_location_review"]["handoff_completion_payload"]["required_fields"]
    overview = report["analysis_readiness"]["operator_overview"]
    assert overview["manual_review_required"] is True
    assert overview["top_manual_review_reason"] == "historical_unrecoverable_gap"
    assert overview["top_human_actions"][0] == "manual_location_review"
    assert "full_address" in overview["top_human_action_instructions"][0]
    assert overview["handoff_mode"] == "manual_required_hard_stop"
    assert overview["handoff_lifecycle_state"] == "awaiting_human_receipt_hard_stop"
    assert overview["auto_retry_policy"]["policy"] == "human_fix_required_before_retry"
    assert overview["top_pending_ready_signal"] == "location_artifacts_complete"
    assert overview["top_human_action_queue"]["expected_reentry_path"] == "infer_location_or_coordinate_backfill"
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
    assert report["analysis_readiness"]["scheduler_feedback_summary"]["top_handoff_mode"] == "manual_required_hard_stop"


def test_release_gate_analysis_readiness_can_surface_receipt_ready_state(monkeypatch, tmp_path: Path):
    data_root = tmp_path / "datas"
    _write_month(
        data_root,
        "2025-01",
        [
            {
                "id": "1004",
                "url": "https://x/1004",
                "成交价格": "100万",
                "建筑面积": "100㎡",
                "交易时间": "2025-01-01 10:00:00",
                "城市": "上海市",
                "区": "浦东新区",
            }
        ],
    )

    monkeypatch.setattr(
        gate_module,
        "build_recent_gap_audit",
        lambda data_root, window_days, sample_limit: {
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            "samples": [
                {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": ["location_precision"], "missing_fields": ["latitude"]},
            ],
        },
    )
    monkeypatch.setattr(gate_module, "load_action_effectiveness_snapshot", lambda path=None: {})
    monkeypatch.setattr(gate_module, "load_optimization_loop_progress_snapshot", lambda path=None: {})
    (data_root / "avm").mkdir(parents=True, exist_ok=True)
    (data_root / "avm" / "manual_review_receipt_jobs.json").write_text(
        json.dumps(
            {
                "jobs": [
                    {
                        "job_id": "job-1",
                        "status": "completed",
                        "receipt_key": {
                            "action": "manual_location_review",
                            "ready_signal": "location_artifacts_complete",
                        },
                        "created_at": "2026-05-14T20:00:00",
                        "finished_at": "2026-05-14T20:00:01",
                    }
                ],
                "queue": [],
                "running_job_id": None,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (data_root / "avm" / "manual_review_receipt_operations.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "operation_id": "op-1",
                        "operation": "created",
                        "action": "manual_location_review",
                        "ready_signal": "location_artifacts_complete",
                        "status": "ready_for_reentry",
                        "payload_fingerprint": "fp-1",
                        "source": "operator_api",
                        "execution_mode": "async",
                        "requested_at": "2026-05-14 20:00:00",
                        "maintenance_job_id": "job-1",
                    },
                    ensure_ascii=False,
                )
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        gate_module,
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

    report = generate_release_gate_report(
        data_root=data_root,
        eval_report_path=tmp_path / "eval_report.json",
        gate_report_path=tmp_path / "gate_report.json",
        window_days=7,
        min_sample_size=1,
        smoke_sample_size=1,
    )

    receipt_summary = report["analysis_readiness"]["manual_review_receipt_summary"]
    assert receipt_summary["top_matched_ready_signal"] == "location_artifacts_complete"
    assert receipt_summary["top_receipt_status"] == "ready_for_reentry"
    assert report["analysis_readiness"]["recommended_actions"]["run_coordinate_backfill"] is True
    reentry_summary = report["analysis_readiness"]["manual_review_reentry_application_summary"]
    assert reentry_summary["reentry_applied"] is False
    overview = report["analysis_readiness"]["operator_overview"]
    assert overview["handoff_lifecycle_state"] == "receipt_ready_for_reentry"
    assert overview["should_resume_automation"] is True
    assert overview["matched_ready_signals"] == ["location_artifacts_complete"]
    jobs_summary = report["analysis_readiness"]["manual_review_receipt_jobs_summary"]
    assert jobs_summary["last_job_status"] == "completed"
    assert jobs_summary["last_job_receipt_key"]["action"] == "manual_location_review"
    operations_summary = report["analysis_readiness"]["manual_review_receipt_operations_summary"]
    assert operations_summary["last_operation_type"] == "created"
    assert operations_summary["last_operation_receipt_key"]["action"] == "manual_location_review"
    storage_summary = report["analysis_readiness"]["manual_review_control_plane_storage"]
    assert storage_summary["state_source"] == "json_fallback"
    assert storage_summary["repository_enabled"] is False
    backup_summary = report["analysis_readiness"]["manual_review_control_plane_backup"]
    assert backup_summary["backup_state"] == "runtime_json"
    assert backup_summary["repository_enabled"] is False
    repairs_summary = report["analysis_readiness"]["manual_review_control_plane_backup_repairs_summary"]
    assert repairs_summary["repair_count"] == 0
    integrity = report["analysis_readiness"]["manual_review_control_plane_integrity"]
    assert integrity["integrity_status"] == "healthy_json_runtime"
    assert integrity["attention_required"] is False
    stability = report["analysis_readiness"]["manual_review_control_plane_stability"]
    assert stability["stability_status"] == "stable_json_runtime"
    assert stability["attention_required"] is False
    guidance = report["analysis_readiness"]["manual_review_control_plane_guidance"]
    assert guidance["guidance_status"] == "no_action_required"
    assert guidance["requires_operator_action"] is False
    integrity_history_summary = report["analysis_readiness"]["manual_review_control_plane_integrity_history_summary"]
    assert integrity_history_summary["transition_count"] >= 1
    assert integrity_history_summary["last_integrity_status"] == "healthy_json_runtime"


def test_release_gate_analysis_readiness_can_surface_incomplete_receipt_state(monkeypatch, tmp_path: Path):
    data_root = tmp_path / "datas"
    _write_month(
        data_root,
        "2025-01",
        [
            {
                "id": "1005",
                "url": "https://x/1005",
                "成交价格": "100万",
                "建筑面积": "100㎡",
                "交易时间": "2025-01-01 10:00:00",
                "城市": "上海市",
                "区": "浦东新区",
            }
        ],
    )

    monkeypatch.setattr(
        gate_module,
        "build_recent_gap_audit",
        lambda data_root, window_days, sample_limit: {
            "recoverability_counts": {"future_fixable": 1, "historical_unrecoverable": 1},
            "samples": [
                {"item_id": "mr-1", "title": "样本1", "historical_unrecoverable": True, "analysis_missing_fields": ["location_precision"], "missing_fields": ["latitude"]},
            ],
        },
    )
    monkeypatch.setattr(gate_module, "load_action_effectiveness_snapshot", lambda path=None: {})
    monkeypatch.setattr(gate_module, "load_optimization_loop_progress_snapshot", lambda path=None: {})
    monkeypatch.setattr(
        gate_module,
        "load_manual_review_receipt_snapshot",
        lambda path=None: {
            "receipts": [
                {
                    "action": "manual_location_review",
                    "ready_signal": "location_artifacts_complete",
                    "status": "ready_for_reentry",
                    "payload": {"full_address": "A"},
                }
            ]
        },
    )

    report = generate_release_gate_report(
        data_root=data_root,
        eval_report_path=tmp_path / "eval_report.json",
        gate_report_path=tmp_path / "gate_report.json",
        window_days=7,
        min_sample_size=1,
        smoke_sample_size=1,
    )

    receipt_summary = report["analysis_readiness"]["manual_review_receipt_summary"]
    assert receipt_summary["top_receipt_status"] == "receipt_incomplete"
    assert receipt_summary["invalid_receipt_count"] == 1
    assert receipt_summary["top_invalid_receipt_reason"] == "missing_required_fields"
    assert receipt_summary["top_receipt_fix_actions"] == ["complete_required_fields"]
    overview = report["analysis_readiness"]["operator_overview"]
    assert overview["handoff_lifecycle_state"] == "awaiting_valid_receipt"
    assert overview["should_resume_automation"] is False
    assert overview["top_invalid_receipt_reason"] == "missing_required_fields"
    assert overview["top_receipt_fix_actions"] == ["complete_required_fields"]
