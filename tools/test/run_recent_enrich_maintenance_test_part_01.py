from tools.test.run_recent_enrich_maintenance_test_context import *


def test_run_recent_enrich_maintenance_reports_before_and_after(tmp_path: Path):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    detail_dir = data_root / "html_archive" / "2026" / "2026-03-05"
    archive_dir.mkdir(parents=True, exist_ok=True)
    detail_dir.mkdir(parents=True, exist_ok=True)

    detail_file = detail_dir / "item-1001.html"
    detail_file.write_text(
        '<html><script>var center=[121.5001,31.2002];</script></html>',
        encoding="utf-8",
    )
    data_file = archive_dir / "2026-03-05.json"
    data_file.write_text(
        json.dumps(
            [
                {
                    "id": 1001,
                    "交易时间": "2026-03-05 10:00:00",
                    "成交价格": "100万",
                    "起拍价格": "80万",
                    "建筑面积": "100㎡",
                    "城市": "上海市",
                    "区": "浦东新区",
                    "detail_captured": True,
                    "detail_archive_path": "html_archive/2026/2026-03-05/item-1001.html",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = run_recent_enrich_maintenance(
        data_root=data_root,
        window_days=7,
        archive_limit=10,
        sample_limit=5,
        dry_run=False,
        extract_risk=False,
    )

    assert report["before"]["missing_field_counts"]["latitude"] >= 1
    assert report["archived_detail_backfill"]["updated_records"] == 1
    assert report["after"]["missing_field_counts"].get("latitude", 0) == 0
    assert "analysis_blockers" in report["before_stage"]
    assert "analysis_blockers" in report["after_stage"]
    assert "recommended_actions" in report
    assert "next_recommended_actions" in report
    assert "action_feedback" in report
    assert report["action_feedback"]["archived_detail_backfill"]["executed"] is True
    assert report["action_feedback"]["archived_detail_backfill"]["produced_work"] is True


def test_recent_gap_audit_ignores_root_non_dated_json(tmp_path: Path):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (data_root / "mock_data.json").write_text(
        json.dumps([{"id": "mock-1", "detail_captured": True}], ensure_ascii=False),
        encoding="utf-8",
    )
    (archive_dir / "2026-03-05.json").write_text(
        json.dumps(
            [
                {
                    "id": "real-1",
                    "交易时间": "2026-03-05 10:00:00",
                    "成交价格": "100万",
                    "起拍价格": "80万",
                    "建筑面积": "100㎡",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_recent_gap_audit(data_root, window_days=7, sample_limit=5)

    assert report["record_count"] == 1


def test_run_recent_enrich_maintenance_can_include_fetch_archives_step(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "2026-03-05.json").write_text(
        json.dumps(
            [
                {
                    "id": "x-1",
                    "交易时间": "2026-03-05 10:00:00",
                    "成交价格": "100万",
                    "起拍价格": "80万",
                    "建筑面积": "100㎡",
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        maintenance_module,
        "fetch_missing_detail_archives",
        lambda **kwargs: {
            "limit": kwargs["limit"],
            "timeout": kwargs["timeout"],
            "dry_run": kwargs["dry_run"],
            "candidate_count": 2,
            "fetched_count": 1,
            "failed_count": 0,
            "touched_files": 1,
            "samples": [{"item_id": "x-1"}],
        },
    )

    report = run_recent_enrich_maintenance(
        data_root=data_root,
        window_days=7,
        archive_limit=10,
        sample_limit=5,
        fetch_limit=2,
        fetch_timeout=9,
        dry_run=True,
        fetch_archives=True,
    )

    assert report["detail_archive_fetch"]["candidate_count"] == 2
    assert report["detail_archive_fetch"]["fetched_count"] == 1
    assert report["detail_archive_fetch"]["timeout"] == 9


def test_recent_gap_audit_reports_analysis_blockers(tmp_path: Path):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "2026-03-05.json").write_text(
        json.dumps(
            [
                {
                    "id": "gap-1",
                    "交易时间": "2026-03-05 10:00:00",
                    "成交价格": "",
                    "起拍价格": "",
                    "建筑面积": "",
                    "城市": "上海市",
                    "区": "浦东新区",
                    "detail_captured": False,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_recent_gap_audit(data_root, window_days=7, sample_limit=5)

    assert report["analysis_missing_field_counts"]["area_sqm"] == 1
    assert report["analysis_missing_field_counts"]["price_anchor"] == 1
    assert report["analysis_missing_field_counts"]["detail_stage"] == 1


def test_recent_gap_audit_reports_recoverability_counts(tmp_path: Path):
    data_root = tmp_path / "datas"
    archive_dir = data_root / "archive" / "2026"
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / "2026-03-05.json").write_text(
        json.dumps(
            [
                {
                    "id": "recoverable-1",
                    "交易时间": "2026-03-05 10:00:00",
                    "成交价格": "100万",
                    "起拍价格": "80万",
                    "建筑面积": "100㎡",
                    "url": "https://example.com/item/recoverable-1",
                    "detail_captured": True,
                },
                {
                    "id": "unrecoverable-1",
                    "交易时间": "2026-03-05 10:00:00",
                    "成交价格": "",
                    "起拍价格": "",
                    "建筑面积": "",
                    "detail_captured": False,
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    report = build_recent_gap_audit(data_root, window_days=7, sample_limit=5)

    assert report["recoverability_counts"]["future_fixable"] >= 1
    assert report["recoverability_counts"]["replay_candidate"] >= 1
    assert report["recoverability_counts"]["historical_unrecoverable"] >= 1


def test_get_collection_stage_snapshot_reads_repo_stage_counts_and_blockers(monkeypatch):
    class _FakeRepo:
        enabled = True

        def stage_status_counts(self):
            return {"analysis_ready": 3, "detail_enriched": 4}

        def analysis_readiness_snapshot(self):
            return {"blockers": {"price_anchor": 2}}

    monkeypatch.setattr(maintenance_module, "create_repository_from_env", lambda: _FakeRepo())

    snapshot = get_collection_stage_snapshot()

    assert snapshot["analysis_ready"] == 3
    assert snapshot["detail_enriched"] == 4
    assert snapshot["analysis_blockers"]["price_anchor"] == 2


def test_run_recent_enrich_maintenance_emits_recommended_actions_from_stage_snapshots(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "datas"
    data_root.mkdir(parents=True, exist_ok=True)

    snapshots = [
        {"analysis_blockers": {"detail_stage": 3, "price_anchor": 1, "location_precision": 2}},
        {"analysis_blockers": {"location_precision": 1}},
    ]
    state = {"index": 0}

    def _fake_stage_snapshot():
        value = snapshots[min(state["index"], len(snapshots) - 1)]
        state["index"] += 1
        return value

    monkeypatch.setattr(maintenance_module, "get_collection_stage_snapshot", _fake_stage_snapshot)
    monkeypatch.setattr(maintenance_module, "build_recent_gap_audit", lambda *args, **kwargs: {"missing_field_counts": {}})
    monkeypatch.setattr(maintenance_module, "fetch_missing_detail_archives", lambda **kwargs: {"fetched_count": 0, "blocked_count": 0, "failed_count": 0})
    monkeypatch.setattr(maintenance_module, "backfill_archived_details", lambda **kwargs: {"updated_records": 0})
    monkeypatch.setattr(maintenance_module, "backfill_recent_coordinates", lambda **kwargs: {"updated_count": 0})
    monkeypatch.setattr(maintenance_module, "prepare_recent_detail_replay", lambda **kwargs: {"prepared_count": 0})

    report = run_recent_enrich_maintenance(
        data_root=data_root,
        window_days=7,
        archive_limit=10,
        sample_limit=5,
        dry_run=True,
        extract_risk=False,
    )

    assert report["recommended_actions"]["fetch_archives"] is True
    assert report["recommended_actions"]["prepare_replay"] is True
    assert report["recommended_actions"]["coordinate_focus"] is True
    assert report["next_recommended_actions"]["fetch_archives"] is False
    assert report["next_recommended_actions"]["coordinate_focus"] is True


def test_run_recent_enrich_maintenance_skips_irrelevant_steps_when_not_recommended(tmp_path: Path, monkeypatch):
    data_root = tmp_path / "datas"
    data_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(maintenance_module, "get_collection_stage_snapshot", lambda: {"analysis_blockers": {}})
    monkeypatch.setattr(maintenance_module, "build_recent_gap_audit", lambda *args, **kwargs: {"missing_field_counts": {}, "detail_archive_present_count": 0})

    fetch_called = {"value": False}
    archive_called = {"value": False}
    coordinate_called = {"value": False}
    replay_called = {"value": False}

    def _fetch(**kwargs):
        fetch_called["value"] = True
        return {"fetched_count": 0}

    def _archive(**kwargs):
        archive_called["value"] = True
        return {"updated_records": 0}

    def _coordinate(**kwargs):
        coordinate_called["value"] = True
        return {"updated_count": 0}

    def _replay(**kwargs):
        replay_called["value"] = True
        return {"prepared_count": 0}

    monkeypatch.setattr(maintenance_module, "fetch_missing_detail_archives", _fetch)
    monkeypatch.setattr(maintenance_module, "backfill_archived_details", _archive)
    monkeypatch.setattr(maintenance_module, "backfill_recent_coordinates", _coordinate)
    monkeypatch.setattr(maintenance_module, "prepare_recent_detail_replay", _replay)

    report = run_recent_enrich_maintenance(
        data_root=data_root,
        window_days=7,
        archive_limit=10,
        sample_limit=5,
        dry_run=False,
        extract_risk=False,
    )

    assert fetch_called["value"] is False
    assert archive_called["value"] is False
    assert coordinate_called["value"] is False
    assert replay_called["value"] is False
    assert report["detail_archive_fetch"]["skipped"] is True
    assert report["archived_detail_backfill"]["skipped"] is True
    assert report["recent_coordinate_backfill"]["skipped"] is True
    assert report["detail_replay_preparation"]["skipped"] is True
    assert report["action_feedback"]["detail_archive_fetch"]["executed"] is False
    assert report["action_feedback"]["archived_detail_backfill"]["executed"] is False
    assert report["action_feedback"]["recent_coordinate_backfill"]["executed"] is False
    assert report["action_feedback"]["detail_replay_preparation"]["executed"] is False


def test_run_recent_enrich_maintenance_executes_analysis_ready_recheck_when_price_receipt_is_ready(tmp_path: Path, monkeypatch):
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
                    "item_id": "mr-price-1",
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
    called = {}

    def _recheck(**kwargs):
        called["mode"] = kwargs["mode"]
        return {
            "mode": kwargs["mode"],
            "candidate_count": 1,
            "scanned_count": 1,
            "updated_count": 1,
            "analysis_stage_transition_count": 1,
            "analysis_ready_transition_count": 1,
            "detail_stage_transition_count": 0,
            "samples": [{"item_id": "mr-price-1"}],
            "skipped": False,
        }

    monkeypatch.setattr(maintenance_module, "run_analysis_stage_reconcile", _recheck)

    report = run_recent_enrich_maintenance(
        data_root=data_root,
        window_days=7,
        archive_limit=10,
        sample_limit=5,
        dry_run=False,
        extract_risk=False,
    )

    assert called["mode"] == "analysis_ready_recheck"
    assert report["recommended_actions"]["suggest_analysis_ready_recheck"] is True
    assert report["analysis_ready_recheck"]["updated_count"] == 1
    assert report["action_feedback"]["analysis_ready_recheck"]["executed"] is True
    assert report["action_feedback"]["analysis_ready_recheck"]["produced_work"] is True
