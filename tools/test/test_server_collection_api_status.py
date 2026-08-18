from __future__ import annotations

import json
from pathlib import Path
import threading
import time
import urllib.request

import pytest


def test_build_solver_request_normalizes_taobao_punish_target() -> None:
    from src import server

    request = server._build_solver_request(
        {
            "target_url": (
                "https://sf.taobao.com//list/200782003__2.htm/_____tmd_____/punish"
                "?x5secdata=secret"
                "&location_code=310120"
                "&st_param=4"
                "&auction_start_seg=-1"
                "&page=14"
                "&x5step=1"
            )
        }
    )

    assert request["target_url"] == (
        "https://sf.taobao.com/list/200782003__2.htm"
        "?location_code=310120"
        "&st_param=4"
        "&auction_start_seg=-1"
        "&page=14"
        "&__captcha_solver_bg=1"
    )


def test_collection_api_lightweight_status_uses_seed_queue_counts(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def seed_queue_counts(self):
            return {
                "seed_scan_job_pending": 1,
                "seed_scan_job_completed": 2,
                "seed_item_pending_detail": 4,
                "seed_item_in_progress": 1,
                "seed_item_detail_completed": 3,
                "seed_item_detail_failed": 2,
                "seed_item_detail_blocked": 1,
                "seed_occurrence_total": 12,
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server, "PAUSED", False)

    payload = server._collection_api_lightweight_status_payload()

    assert payload["collection_api_lightweight"] is True
    assert payload["capabilities"]["manual_captcha_report_v1"] is True
    assert payload["paused"] is False
    assert payload["total_ids"] == 11
    assert payload["captured_count"] == 3
    assert payload["ai_finalized_count"] == 3
    assert payload["sniff_queue_count"] == 1
    assert payload["sniff_done_count"] == 2
    assert payload["seed_scan_job_pending"] == 1
    assert payload["seed_scan_job_in_progress"] == 0
    assert payload["seed_scan_job_completed"] == 2
    assert payload["seed_scan_job_blocked"] == 0
    assert payload["seed_scan_progress_pending"] == 0
    assert payload["seed_scan_progress_in_progress"] == 0
    assert payload["seed_scan_progress_exhausted"] == 0
    assert payload["seed_scan_progress_blocked"] == 0
    assert payload["collection_stage"]["seed_queue"]["seed_occurrence_total"] == 12


def test_build_info_payload_uses_non_secret_deployment_identity(monkeypatch) -> None:
    from src import server

    monkeypatch.setenv("FAPAI_BUILD_VERSION", "20260811-01")
    monkeypatch.setenv("FAPAI_BUILD_COMMIT", "abc123")
    monkeypatch.setenv("FAPAI_BUILD_TIME", "2026-08-11T12:00:00Z")
    monkeypatch.setenv("FAPAI_SOURCE_DIGEST", "sha256:test")

    assert server._build_info_payload() == {
        "version": "20260811-01",
        "commit": "abc123",
        "built_at": "2026-08-11T12:00:00Z",
        "source_digest": "sha256:test",
    }


def test_collection_api_lightweight_status_separates_raw_capture_from_ai_finalized(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def seed_queue_counts(self):
            return {
                "seed_scan_job_pending": 1,
                "seed_scan_job_completed": 2,
                "seed_item_pending_detail": 4,
                "seed_item_in_progress": 1,
                "seed_item_raw_detail_captured": 5,
                "seed_item_detail_completed": 3,
                "seed_item_detail_failed": 2,
                "seed_item_detail_blocked": 1,
                "seed_occurrence_total": 16,
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server, "PAUSED", False)

    payload = server._collection_api_lightweight_status_payload()

    assert payload["total_ids"] == 16
    assert payload["captured_count"] == 8
    assert payload["ai_finalized_count"] == 3
    assert payload["db_processed_ids"] == 3
    assert payload["db_detail_captured_ids"] == 8
    assert payload["collection_stage"]["detail_stage"]["raw_archived"] == 5
    assert payload["collection_stage"]["detail_stage"]["archived"] == 8
    assert payload["collection_stage"]["detail_stage"]["ai_finalized"] == 3


def test_collection_api_lightweight_status_exposes_analysis_only_status_fields(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def seed_queue_counts(self):
            return {
                "seed_item_pending_detail": 4,
                "seed_item_in_progress": 1,
                "seed_item_raw_detail_captured": 5,
                "seed_item_analysis_in_progress": 2,
                "seed_item_analysis_failed": 1,
                "seed_item_analysis_blocked": 1,
                "seed_item_detail_completed": 3,
                "seed_item_detail_failed": 2,
                "seed_item_detail_blocked": 1,
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server, "PAUSED", False)

    payload = server._collection_api_lightweight_status_payload()
    detail_stage = payload["collection_stage"]["detail_stage"]

    assert payload["raw_capture_pending_count"] == 5
    assert payload["raw_captured_count"] == 5
    assert payload["analysis_ready_count"] == 6
    assert payload["analysis_in_progress_count"] == 2
    assert payload["analysis_pending_count"] == 8
    assert payload["analysis_blocked_count"] == 1
    assert payload["analysis_finalized_count"] == 3
    assert payload["detail_failed_count"] == 2
    assert payload["detail_blocked_count"] == 1
    assert detail_stage["raw_pending"] == 4
    assert detail_stage["raw_in_progress"] == 1
    assert detail_stage["raw_failed"] == 2
    assert detail_stage["raw_blocked"] == 1
    assert detail_stage["analysis_ready"] == 6
    assert detail_stage["analysis_backlog"] == 8
    assert detail_stage["analysis_finalized"] == 3


def test_solver_force_unlock_flag_path_uses_persistent_state_dir(monkeypatch, tmp_path) -> None:
    from src import server

    state_dir = tmp_path / "solver-state"
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(state_dir))
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {"node_id": "pc2"})

    assert Path(server._solver_force_unlock_flag_path()) == state_dir / "force_unlock.flag"
    assert server._write_solver_manual_required_flag(1234.0) is None
    payload = json.loads((state_dir / "force_unlock.flag").read_text(encoding="utf-8"))
    assert payload["last_request"]["node_id"] == "pc2"


def test_collection_api_lightweight_status_surfaces_manual_required_solver_state(monkeypatch, tmp_path) -> None:
    from src import server

    class FakeRepository:
        enabled = False

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "SOLVER_RUNNING", True)
    monkeypatch.setattr(server, "SOLVER_START_TIME", time.time() - 5)
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    payload = server._collection_api_lightweight_status_payload()

    assert payload["captcha_solver"]["running"] is True
    assert payload["captcha_solver"]["manual_required"] is True
    assert payload["captcha_solver"]["force_unlock_flag_exists"] is True
    assert payload["captcha_solver"]["elapsed_seconds"] >= 5


def test_collection_api_lightweight_status_treats_force_unlock_flag_as_durable_manual_required(monkeypatch, tmp_path) -> None:
    from src import server

    class FakeRepository:
        enabled = False

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    payload = server._collection_api_lightweight_status_payload()

    assert payload["paused"] is True
    assert payload["captcha_solver"]["manual_required"] is True
    assert payload["captcha_solver"]["force_unlock_flag_exists"] is True


def test_collection_api_lightweight_status_does_not_pause_for_transient_solver_run(monkeypatch, tmp_path) -> None:
    from src import server

    class FakeRepository:
        enabled = False

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "captcha_solver", raising=False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", True)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "running")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_START_TIME", time.time() - 3)

    payload = server._collection_api_lightweight_status_payload()

    assert payload["paused"] is False
    assert payload["captcha_solver"]["running"] is True
    assert payload["captcha_solver"]["manual_required"] is False
    assert payload["captcha_solver"]["paused"] is False


def test_collection_api_lightweight_status_preserves_operator_pause_during_solver_run(monkeypatch, tmp_path) -> None:
    from src import server

    class FakeRepository:
        enabled = False

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "operator", raising=False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", True)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "running")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_START_TIME", time.time() - 3)

    payload = server._collection_api_lightweight_status_payload()

    assert payload["paused"] is True
    assert payload["captcha_solver"]["running"] is True
    assert payload["captcha_solver"]["manual_required"] is False
    assert payload["captcha_solver"]["paused"] is True


def test_collection_observer_page_contains_three_collection_modules() -> None:
    from src import server

    html = server._collection_observer_page_html()

    assert "FapaiFang 采集观察台" in html
    if "商品链接采集" in html:
        assert "商品详情页采集" in html
        assert "商品详情页 AI 分析" in html
        assert "/api/collection/overview" in html
        assert "/api/collection/items" in html
    else:
        assert '<div id="app"></div>' in html
        assert "/assets/index-" in html


def test_collection_observer_overview_wraps_lightweight_status(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def seed_queue_counts(self):
            return {
                "seed_occurrence_total": 12,
                "seed_item_pending_detail": 4,
                "seed_item_raw_detail_captured": 5,
                "seed_item_detail_completed": 3,
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server, "PAUSED", False)

    payload = server._collection_observer_overview_payload()

    assert payload["ok"] is True
    assert payload["modules"]["links"]["total"] == 12
    assert payload["modules"]["details"]["captured"] == 8
    assert payload["modules"]["analysis"]["finalized"] == 3


def test_pc1_auth_auto_resume_state_summary_reads_shared_state(tmp_path, monkeypatch) -> None:
    from src import server

    data_root = tmp_path / "datas"
    data_root.mkdir(parents=True, exist_ok=True)
    state_path = tmp_path / "secrets" / "pc1-auth-auto-resume-state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps(
            {
                "mode": "pc1_auth_auto_resume_watch",
                "status": "completed",
                "started_at": "2026-08-12T01:00:00Z",
                "completed_at": "2026-08-12T01:03:30Z",
                "poll_seconds": 5,
                "max_wait_seconds": 1800,
                "api_base": "http://192.168.15.200:8001/api",
                "cdp_endpoint": "http://127.0.0.1:9225",
            }
        ),
        encoding="utf-8",
    )

    summary = server._pc1_auth_auto_resume_state_summary(Path(data_root))

    assert summary["available"] is True
    assert summary["mode"] == "pc1_auth_auto_resume_watch"
    assert summary["status"] == "completed"
    assert summary["poll_seconds"] == 5
    assert summary["max_wait_seconds"] == 1800
    assert summary["wait_elapsed_seconds"] == 210
    assert summary["api_base"] == "http://192.168.15.200:8001/api"
    assert summary["cdp_endpoint"] == "http://127.0.0.1:9225"


def test_collection_observer_overview_exposes_challenge_metrics_and_auth_watcher(tmp_path, monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def seed_queue_counts(self):
            return {
                "seed_occurrence_total": 12,
                "seed_item_pending_detail": 4,
                "seed_item_raw_detail_captured": 5,
                "seed_item_detail_completed": 3,
            }

    data_root = tmp_path / "datas"
    avm_root = data_root / "avm"
    avm_root.mkdir(parents=True, exist_ok=True)
    (avm_root / "hybrid_seed_collection_runtime.json").write_text(
        json.dumps(
            {
                "decision_counts": {
                    "browserless_success": 3,
                    "browser_fallback_required": 2,
                },
                "reason_counts": {
                    "challenge_detected": 2,
                },
                "last_reason": "challenge_detected",
                "last_decision": "browser_fallback_required",
                "top_fallback_reason": "challenge_detected",
                "last_probe_summary": {
                    "body_has_challenge": True,
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (avm_root / "hybrid_seed_collection_runtime_history.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "decision_counts": {"browserless_success": 1},
                        "reason_counts": {},
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "decision_counts": {"browser_fallback_required": 1},
                        "reason_counts": {"challenge_detected": 1},
                    },
                    ensure_ascii=False,
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    watcher_path = tmp_path / "secrets" / "pc1-auth-auto-resume-state.json"
    watcher_path.parent.mkdir(parents=True, exist_ok=True)
    watcher_path.write_text(
        json.dumps(
            {
                "mode": "pc1_auth_auto_resume_watch",
                "status": "watching",
                "started_at": "2026-08-12T01:00:00Z",
                "poll_seconds": 5,
                "max_wait_seconds": 1800,
                "last_error": "cookie export returned non-zero exit code",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "AVM_SERVICE", type("FakeService", (), {"data_dir": str(data_root)})())

    payload = server._collection_observer_overview_payload()

    assert payload["challenge_metrics"]["available"] is True
    assert payload["challenge_metrics"]["current_challenge_detected_count"] == 2
    assert payload["challenge_metrics"]["current_browserless_attempt_count"] == 5
    assert payload["challenge_metrics"]["current_challenge_hit_rate"] == 0.4
    assert payload["challenge_metrics"]["recent_challenge_detected_count"] == 1
    assert payload["challenge_metrics"]["recent_browserless_attempt_count"] == 2
    assert payload["challenge_metrics"]["recent_challenge_hit_rate"] == 0.5
    assert payload["challenge_metrics"]["last_probe_body_has_challenge"] is True
    assert payload["auth_watcher"]["available"] is True
    assert payload["auth_watcher"]["status"] == "watching"
    assert payload["auth_watcher"]["poll_seconds"] == 5
    assert payload["auth_watcher"]["max_wait_seconds"] == 1800
    assert payload["auth_watcher"]["last_error"] == "cookie export returned non-zero exit code"


def test_collection_observer_items_payload_uses_repository(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True
        seen_location_code = None

        def collection_observer_items(self, *, stage, limit, offset, location_code=None):
            self.seen_location_code = location_code
            return {
                "stage": stage,
                "limit": limit,
                "offset": offset,
                "location_code": location_code,
                "total": 1,
                "items": [{"item_id": "1001", "title": "测试房产"}],
            }

    fake = FakeRepository()
    monkeypatch.setattr(server, "DB_REPOSITORY", fake)

    payload = server._collection_observer_items_payload(
        {"stage": ["analysis"], "limit": ["5"], "offset": ["10"], "location_code": ["440115"]}
    )

    assert payload["stage"] == "analysis"
    assert payload["limit"] == 5
    assert payload["offset"] == 10
    assert payload["location_code"] == "440115"
    assert fake.seen_location_code == "440115"
    assert payload["items"][0]["item_id"] == "1001"


def test_collection_observer_regions_payload_uses_repository(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def collection_observer_regions(self, *, stage):
            return {
                "ok": True,
                "stage": stage,
                "regions": [
                    {
                        "location_code": "440115",
                        "label": "广州市 南沙区",
                        "completed": True,
                        "status_label": "收集完成",
                    }
                ],
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())

    payload = server._collection_observer_regions_payload({"stage": ["details"]})

    assert payload["ok"] is True
    assert payload["stage"] == "details"
    assert payload["regions"][0]["location_code"] == "440115"
    assert payload["regions"][0]["completed"] is True
    assert payload["db_mode"] is True


def test_collection_observer_reset_region_links_payload_uses_repository(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def reset_seed_link_region(self, location_code):
            return {"ok": True, "location_code": location_code, "reset": {"jobs": 1, "progress": 2}}

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())

    payload = server._collection_observer_reset_region_links_payload({"location_code": "440115"})

    assert payload["ok"] is True
    assert payload["location_code"] == "440115"
    assert payload["reset"]["progress"] == 2
    assert payload["db_mode"] is True


def test_collection_observer_item_payload_loads_one_item(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def collection_observer_item_detail(self, item_id, *, max_chars):
            return {
                "item": {"item_id": item_id, "title": "测试房产"},
                "max_chars": max_chars,
                "artifacts": {"final_json": {"json": {"community_name": "测试小区"}}},
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())

    payload = server._collection_observer_item_payload({"item_id": ["1001"], "max_chars": ["123"]})

    assert payload["item"]["item_id"] == "1001"
    assert payload["max_chars"] == 123
    assert payload["artifacts"]["final_json"]["json"]["community_name"] == "测试小区"


def test_collection_observer_reanalysis_payload_uses_repository(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def requeue_seed_detail_analysis(self, item_id, *, reason):
            return {
                "ok": True,
                "item_id": item_id,
                "status": "raw_detail_captured",
                "reason": reason,
                "analysis_attempt_count": 3,
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())

    payload = server._collection_observer_reanalysis_payload({"item_id": "1001"})

    assert payload["ok"] is True
    assert payload["item_id"] == "1001"
    assert payload["status"] == "raw_detail_captured"
    assert payload["analysis_attempt_count"] == 3


def test_collection_observer_manual_update_payload_uses_repository(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def manual_update_flat_item(self, item_id, updates):
            return {
                "ok": True,
                "item_id": item_id,
                "updated_fields": sorted(updates),
                "flat_item": {"item_id": item_id, **updates},
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())

    payload = server._collection_observer_manual_update_payload(
        {"item_id": "1001", "updates": {"title": "手动标题", "transaction_price": "123"}}
    )

    assert payload["ok"] is True
    assert payload["item_id"] == "1001"
    assert payload["updated_fields"] == ["title", "transaction_price"]
    assert payload["flat_item"]["title"] == "手动标题"


def test_collection_observer_runtime_control_can_pause_and_resume(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)

    paused = server._collection_observer_runtime_control_payload("pause")

    assert paused["ok"] is True
    assert paused["runtime_state"] == "暂停中"
    assert server.PAUSED is True

    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", True)
    monkeypatch.setattr(server, "SOLVER_START_TIME", time.time() - 300)
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    resumed = server._collection_observer_runtime_control_payload("resume")

    assert resumed["ok"] is True
    assert resumed["runtime_state"] == "运行中"
    assert server.PAUSED is False
    assert not (tmp_path / "force_unlock.flag").exists()
    assert server.SOLVER_LAST_STATUS == "resumed"
    assert server.SOLVER_LAST_FAILURE_REASON is None
    assert server.SOLVER_RUNNING is False
    assert resumed["captcha_solver"]["running"] is False


def test_collection_api_lightweight_status_keeps_running_when_manual_required_only_targets_detail_and_seed_work_remains(
    monkeypatch,
) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def seed_queue_counts(self):
            return {
                "seed_scan_job_pending": 9,
                "seed_scan_job_in_progress": 1,
                "seed_scan_job_completed": 2,
                "seed_scan_progress_pending": 20,
                "seed_scan_progress_in_progress": 1,
                "seed_scan_progress_exhausted": 0,
                "seed_scan_progress_blocked": 0,
                "seed_item_pending_detail": 30,
                "seed_item_in_progress": 0,
                "seed_item_raw_detail_captured": 5,
                "seed_item_analysis_in_progress": 0,
                "seed_item_analysis_failed": 0,
                "seed_item_analysis_blocked": 0,
                "seed_item_detail_completed": 10,
                "seed_item_detail_failed": 0,
                "seed_item_detail_blocked": 0,
                "seed_occurrence_total": 200,
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {"target_url": "https://sf-item.taobao.com/sf_item/647559663666.htm?__captcha_solver_bg=1"},
    )
    monkeypatch.setattr(server, "SOLVER_MANUAL_REQUIRED_EPOCH", 1000.0, raising=False)
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_LAST_EPOCH", 1000.0, raising=False)
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 1000.0)

    payload = server._collection_api_lightweight_status_payload()

    assert payload["paused"] is True
    assert payload["captcha_solver"]["manual_required"] is True
    assert payload["runtime_state"] == "运行中"


def test_collection_api_lightweight_status_reports_pending_auth_when_manual_required_targets_seed_stage(
    monkeypatch,
) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def seed_queue_counts(self):
            return {
                "seed_scan_job_pending": 9,
                "seed_scan_job_in_progress": 1,
                "seed_scan_job_completed": 2,
                "seed_scan_progress_pending": 20,
                "seed_scan_progress_in_progress": 1,
                "seed_scan_progress_exhausted": 0,
                "seed_scan_progress_blocked": 0,
                "seed_item_pending_detail": 30,
                "seed_item_in_progress": 0,
                "seed_item_raw_detail_captured": 5,
                "seed_item_analysis_in_progress": 0,
                "seed_item_analysis_failed": 0,
                "seed_item_analysis_blocked": 0,
                "seed_item_detail_completed": 10,
                "seed_item_detail_failed": 0,
                "seed_item_detail_blocked": 0,
                "seed_occurrence_total": 200,
            }

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {"target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115&__captcha_solver_bg=1"},
    )
    monkeypatch.setattr(server, "SOLVER_MANUAL_REQUIRED_EPOCH", 1000.0, raising=False)
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_LAST_EPOCH", 1000.0, raising=False)
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 1000.0)

    payload = server._collection_api_lightweight_status_payload()

    assert payload["runtime_state"] == "待认证"


def test_collection_observer_auth_complete_clears_pause_and_marks_manual_auth(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        server,
        "_schedule_auth_cookie_snapshot_refresh",
        lambda _payload, _completion_id: {"status": "skipped", "refreshed": False, "retry_queued": False},
    )
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "SOLVER_RUNNING", True)
    monkeypatch.setattr(server, "SOLVER_START_TIME", time.time() - 10)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "running")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {"target_url": "https://contest.local/auth"})
    monkeypatch.setattr(server, "SOLVER_MANUAL_RESUME_EPOCH", 0)
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    payload = server._collection_observer_auth_complete_payload({"source": "desktop"})

    assert payload["ok"] is True
    assert payload["action"] == "auth_complete"
    assert payload["auth_state_confirmed"] is True
    assert payload["runtime_state"] == "运行中"
    assert payload["manual_auth_completed"] is True
    assert server.PAUSED is False
    assert server.SOLVER_LAST_STATUS == "manual_auth_completed"
    assert server.SOLVER_LAST_FAILURE_REASON is None
    assert server.SOLVER_RUNNING is False
    assert payload["captcha_solver"]["running"] is False
    assert server.SOLVER_MANUAL_RESUME_EPOCH > 0
    assert not (tmp_path / "force_unlock.flag").exists()


def test_collection_observer_auth_complete_schedules_cookie_snapshot_without_blocking_resume(monkeypatch, tmp_path) -> None:
    from src import server

    calls: list[dict[str, object]] = []

    def fake_schedule(payload: dict[str, object], completion_id: str | None) -> dict[str, object]:
        calls.append({**dict(payload), "scheduled_completion_id": completion_id})
        return {
            "status": "pending",
            "refreshed": False,
            "retry_queued": True,
            "completion_id": completion_id,
        }

    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_schedule_auth_cookie_snapshot_refresh", fake_schedule)
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    payload = server._collection_observer_auth_complete_payload(
        {"source": "desktop", "completion_id": "desktop-completion-1"}
    )

    assert calls == [
        {
            "source": "desktop",
            "completion_id": "desktop-completion-1",
            "scheduled_completion_id": "desktop-completion-1",
        }
    ]
    assert payload["ok"] is True
    assert payload["paused"] is False
    assert payload["captcha_solver"]["manual_required"] is False
    assert payload["auth_state_confirmed"] is True
    assert payload["cookie_snapshot"]["status"] == "pending"
    assert payload["cookie_snapshot"]["retry_queued"] is True
    assert server.SOLVER_LAST_STATUS == "manual_auth_completed"
    assert not (tmp_path / "force_unlock.flag").exists()


def test_collection_observer_auth_complete_keeps_resume_when_cookie_refresh_fails(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        server,
        "_schedule_auth_cookie_snapshot_refresh",
        lambda _payload, completion_id: {
            "status": "failed",
            "completion_id": completion_id,
            "refreshed": False,
            "retry_queued": False,
            "result": {"error": "cdp unavailable"},
        },
    )
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")

    payload = server._collection_observer_auth_complete_payload({"source": "desktop"})

    assert payload["ok"] is True
    assert payload["auth_state_confirmed"] is True
    assert payload["paused"] is False
    assert payload["cookie_snapshot"]["refreshed"] is False
    assert "cdp unavailable" in payload["cookie_snapshot"]["result"]["error"]
    assert server.SOLVER_LAST_STATUS == "manual_auth_completed"


def test_collection_observer_auth_complete_is_idempotent_for_repeated_completion_id(monkeypatch, tmp_path) -> None:
    from src import server

    completion_id = "pc2-completion-idempotent"
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "AUTH_COMPLETION_CONFIRMATIONS", {})
    monkeypatch.setattr(
        server,
        "_schedule_auth_cookie_snapshot_refresh",
        lambda _payload, current_id: {
            "status": "pending",
            "completion_id": current_id,
            "refreshed": False,
            "retry_queued": True,
        },
    )
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    first = server._collection_observer_auth_complete_payload(
        {"source": "pc2_local_solver", "completion_id": completion_id}
    )
    server.AUTH_COMPLETION_CONFIRMATIONS.clear()
    second = server._collection_observer_auth_complete_payload(
        {"source": "pc2_local_solver", "completion_id": completion_id}
    )

    assert first["ok"] is True
    assert first["auth_state_confirmed"] is True
    assert first["idempotent"] is False
    assert second["ok"] is True
    assert second["auth_state_confirmed"] is True
    assert second["idempotent"] is True
    assert second["completion_id"] == completion_id
    assert second["captcha_solver"]["manual_required"] is False
    assert second["captcha_solver"]["force_unlock_flag_exists"] is False


def test_repeated_old_completion_id_does_not_clear_a_new_manual_required_state(monkeypatch, tmp_path) -> None:
    from src import server

    completion_id = "pc2-old-completion"
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "AUTH_COMPLETION_CONFIRMATIONS", {})
    monkeypatch.setattr(
        server,
        "_schedule_auth_cookie_snapshot_refresh",
        lambda _payload, current_id: {
            "status": "completed",
            "completion_id": current_id,
            "refreshed": True,
            "retry_queued": False,
        },
    )
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("first challenge", encoding="utf-8")

    first = server._collection_observer_auth_complete_payload(
        {"source": "pc2_local_solver", "completion_id": completion_id}
    )
    assert first["auth_state_confirmed"] is True

    server.AUTH_COMPLETION_CONFIRMATIONS.clear()
    server.PAUSED = True
    server.COLLECTION_PAUSE_REASON = "manual_required"
    server.SOLVER_LAST_STATUS = "manual_required"
    server.SOLVER_LAST_FAILURE_REASON = "manual_required"
    flag_path.write_text("new challenge", encoding="utf-8")

    stale = server._collection_observer_auth_complete_payload(
        {"source": "pc2_local_solver", "completion_id": completion_id}
    )

    assert stale["ok"] is False
    assert stale["auth_state_confirmed"] is False
    assert "stale" in stale["error"]
    assert flag_path.exists()
    assert server.PAUSED is True
    assert server.SOLVER_LAST_STATUS == "manual_required"


def test_collection_observer_auth_complete_rejects_unconfirmed_cleanup(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_clear_solver_manual_required_pause", lambda: "file is busy")
    monkeypatch.setattr(
        server,
        "_schedule_auth_cookie_snapshot_refresh",
        lambda _payload, completion_id: {
            "status": "pending",
            "completion_id": completion_id,
            "refreshed": False,
            "retry_queued": True,
        },
    )
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    payload = server._collection_observer_auth_complete_payload(
        {"source": "pc2_local_solver", "completion_id": "pc2-unconfirmed"}
    )

    assert payload["ok"] is False
    assert payload["auth_state_confirmed"] is False
    assert payload["captcha_solver"]["manual_required"] is True
    assert payload["captcha_solver"]["force_unlock_flag_exists"] is True
    assert "file is busy" in payload["error"]


def test_pc2_auth_complete_requires_completion_id(monkeypatch) -> None:
    from src import server

    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "captcha_solver")
    monkeypatch.setattr(server, "SOLVER_CHALLENGE_ID", "challenge-current")

    payload = server._collection_observer_auth_complete_payload(
        {
            "source": "pc2_local_solver",
            "challenge_id": "challenge-current",
        }
    )

    assert payload["ok"] is False
    assert payload["auth_state_confirmed"] is False
    assert payload["paused"] is True
    assert "completion_id is required" in payload["error"]


def test_resume_after_cooldown_only_clears_collection_auth_pause(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.delenv("FAPAI_SOLVER_STATE_DIR", raising=False)
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "AUTH_COMPLETION_CONFIRMATIONS", {})
    monkeypatch.setattr(server, "SOLVER_CHALLENGE_ID", None)
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    payload = server._collection_observer_resume_after_cooldown_payload(
        {"source": "pc2_local_solver", "resume_request_id": "pc2-resume-1"}
    )

    assert payload["ok"] is True
    assert payload["action"] == "resume_after_cooldown"
    assert payload["resume_request_id"] == "pc2-resume-1"
    assert payload["auth_state_confirmed"] is True
    assert payload["manual_auth_completed"] is False
    assert payload["paused"] is False
    assert payload["captcha_solver"]["manual_required"] is False
    assert payload["captcha_solver"]["force_unlock_flag_exists"] is False
    assert payload["cookie_snapshot"]["status"] == "skipped"
    assert server.SOLVER_LAST_STATUS == "resumed_after_cooldown"
    assert not (tmp_path / "force_unlock.flag").exists()


def test_resume_after_cooldown_is_idempotent_for_same_request_id(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.delenv("FAPAI_SOLVER_STATE_DIR", raising=False)
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "AUTH_COMPLETION_CONFIRMATIONS", {})
    monkeypatch.setattr(server, "SOLVER_CHALLENGE_ID", None)
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")
    request = {"source": "pc2_local_solver", "resume_request_id": "pc2-resume-repeat"}

    first = server._collection_observer_resume_after_cooldown_payload(request)
    server.AUTH_COMPLETION_CONFIRMATIONS.clear()
    second = server._collection_observer_resume_after_cooldown_payload(request)

    assert first["ok"] is True
    assert first["idempotent"] is False
    assert second["ok"] is True
    assert second["idempotent"] is True
    assert second["manual_auth_completed"] is False


@pytest.mark.parametrize("action", ["auth_complete", "resume_after_cooldown"])
def test_old_pc2_request_cannot_clear_new_challenge(monkeypatch, tmp_path, action) -> None:
    from src import server

    monkeypatch.delenv("FAPAI_SOLVER_STATE_DIR", raising=False)
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "AUTH_COMPLETION_CONFIRMATIONS", {})
    monkeypatch.setattr(server, "SOLVER_CHALLENGE_ID", "challenge-b")
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("new challenge", encoding="utf-8")

    if action == "auth_complete":
        payload = server._collection_observer_auth_complete_payload(
            {
                "source": "pc2_local_solver",
                "completion_id": "old-completion",
                "challenge_id": "challenge-a",
            }
        )
    else:
        payload = server._collection_observer_resume_after_cooldown_payload(
            {
                "source": "pc2_local_solver",
                "resume_request_id": "old-resume",
                "challenge_id": "challenge-a",
            }
        )

    assert payload["ok"] is False
    assert payload["stale_challenge"] is True
    assert payload["challenge_id"] == "challenge-b"
    assert server.PAUSED is True
    assert server.SOLVER_LAST_STATUS == "manual_required"
    assert server.SOLVER_LAST_FAILURE_REASON == "manual_required"
    assert flag_path.exists()


def test_solver_challenge_id_survives_api_process_restart(monkeypatch, tmp_path) -> None:
    from src import server

    request = {
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9224",
        "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    }
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "SOLVER_CHALLENGE_ID", None)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", dict(request))
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", None)

    challenge_id = server._begin_solver_challenge()
    state_path = tmp_path / "solver-challenge-state.json"
    persisted = json.loads(state_path.read_text(encoding="utf-8"))

    assert persisted["challenge_id"] == challenge_id
    assert persisted["last_request"] == request

    server.SOLVER_CHALLENGE_ID = None
    server.SOLVER_LAST_REQUEST = dict(request)
    server.PAUSED = False
    server.COLLECTION_PAUSE_REASON = None

    assert server._begin_solver_challenge() == challenge_id
    assert server._restore_solver_challenge_state() is True
    assert server.SOLVER_CHALLENGE_ID == challenge_id
    assert server.SOLVER_LAST_REQUEST == request
    assert server.PAUSED is True
    assert server.COLLECTION_PAUSE_REASON == "captcha_solver"


def test_different_solver_request_starts_new_persisted_challenge(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "SOLVER_CHALLENGE_ID", None)
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", None)
    monkeypatch.setattr(server.time, "time_ns", lambda: 1001)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/first.htm",
        },
    )
    first_id = server._begin_solver_challenge()

    server.SOLVER_CHALLENGE_ID = None
    server.PAUSED = False
    server.COLLECTION_PAUSE_REASON = None
    server.SOLVER_LAST_REQUEST = {
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9224",
        "target_url": "https://sf.taobao.com/list/second.htm",
    }
    monkeypatch.setattr(server.time, "time_ns", lambda: 1002)

    second_id = server._begin_solver_challenge()

    assert first_id == "captcha-1001"
    assert second_id == "captcha-1002"
    persisted = json.loads((tmp_path / "solver-challenge-state.json").read_text(encoding="utf-8"))
    assert persisted["challenge_id"] == second_id


def test_paused_challenge_changes_only_when_node_owner_changes(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "SOLVER_CHALLENGE_ID", None)
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", None)
    monkeypatch.setattr(server.time, "time_ns", lambda: 2001)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/first.htm",
        },
    )
    first_id = server._begin_solver_challenge()
    server.PAUSED = True
    server.COLLECTION_PAUSE_REASON = "captcha_solver"

    server.SOLVER_LAST_REQUEST = {
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9224",
        "target_url": "https://sf.taobao.com/list/second.htm",
    }
    assert server._begin_solver_challenge() == first_id

    server.SOLVER_LAST_REQUEST = {
        "node_id": "pc3",
        "cdp_endpoint": "http://192.168.15.105:9224",
        "target_url": "https://sf.taobao.com/list/second.htm",
    }
    monkeypatch.setattr(server.time, "time_ns", lambda: 2002)

    assert server._begin_solver_challenge() == "captcha-2002"


def test_challenge_cleanup_failure_keeps_runtime_paused(monkeypatch, tmp_path) -> None:
    from src import server

    class UnremovableChallengeState:
        def unlink(self, *, missing_ok: bool = False) -> None:
            raise OSError("challenge state is busy")

    monkeypatch.delenv("FAPAI_SOLVER_STATE_DIR", raising=False)
    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "SOLVER_CHALLENGE_ID", "challenge-current")
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "captcha_solver")
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "_solver_challenge_state_path", lambda: UnremovableChallengeState())

    error = server._clear_solver_manual_required_pause()

    assert "challenge state is busy" in str(error)
    assert server.SOLVER_CHALLENGE_ID == "challenge-current"
    assert server.PAUSED is True
    assert server.COLLECTION_PAUSE_REASON == "captcha_solver"
    assert server.SOLVER_LAST_STATUS == "manual_required"


def test_resume_after_cooldown_clears_persisted_challenge_state(monkeypatch, tmp_path) -> None:
    from src import server

    request = {
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9224",
        "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    }
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "AUTH_COMPLETION_CONFIRMATIONS", {})
    monkeypatch.setattr(server, "SOLVER_CHALLENGE_ID", None)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", dict(request))
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", None)
    challenge_id = server._begin_solver_challenge()
    server.PAUSED = True
    server.COLLECTION_PAUSE_REASON = "captcha_solver"

    payload = server._collection_observer_resume_after_cooldown_payload(
        {
            "source": "pc2_local_solver",
            "resume_request_id": "pc2-resume-persisted-challenge",
            "challenge_id": challenge_id,
        }
    )

    assert payload["ok"] is True
    assert payload["auth_state_confirmed"] is True
    assert server.SOLVER_CHALLENGE_ID is None
    assert not (tmp_path / "solver-challenge-state.json").exists()


def test_auth_cookie_snapshot_retry_records_failure_then_success(monkeypatch) -> None:
    from src import server

    results: list[object] = [
        RuntimeError("CDP reset"),
        {"refreshed": False, "reason": "cookie_snapshot_candidate_unhealthy"},
        {"refreshed": True, "cookie_count": 5},
    ]

    def fake_refresh(_payload):
        result = results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(server, "AUTH_COOKIE_SNAPSHOT_STATE", {})
    monkeypatch.setattr(server, "_auth_cookie_snapshot_retry_attempts", lambda: 3)
    monkeypatch.setattr(server, "_auth_cookie_snapshot_retry_backoff_seconds", lambda: 0)
    monkeypatch.setattr(server, "_refresh_auth_cookie_snapshot", fake_refresh)

    server._run_auth_cookie_snapshot_retry({}, "pc2-cookie-retry")
    status = server._auth_cookie_snapshot_runtime_status()

    assert status["status"] == "completed"
    assert status["completion_id"] == "pc2-cookie-retry"
    assert status["attempts"] == 3
    assert status["refreshed"] is True
    assert status["result"]["cookie_count"] == 5


def test_auth_cookie_snapshot_retry_stops_after_bounded_attempts(monkeypatch) -> None:
    from src import server

    calls: list[int] = []
    monkeypatch.setattr(server, "AUTH_COOKIE_SNAPSHOT_STATE", {})
    monkeypatch.setattr(server, "_auth_cookie_snapshot_retry_attempts", lambda: 2)
    monkeypatch.setattr(server, "_auth_cookie_snapshot_retry_backoff_seconds", lambda: 0)
    monkeypatch.setattr(
        server,
        "_refresh_auth_cookie_snapshot",
        lambda _payload: calls.append(1) or {"refreshed": False, "reason": "cdp_endpoint_unhealthy"},
    )

    server._run_auth_cookie_snapshot_retry({}, "pc2-cookie-failed")
    status = server._auth_cookie_snapshot_runtime_status()

    assert len(calls) == 2
    assert status["status"] == "failed"
    assert status["attempts"] == 2
    assert status["retry_queued"] is False


def test_refresh_auth_cookie_snapshot_writes_only_after_healthy_probe(monkeypatch, tmp_path) -> None:
    from src import server

    snapshot_path = tmp_path / "taobao-cookies.json"
    cookies = [{"name": "cookie2", "value": "v", "domain": ".taobao.com", "path": "/"}]
    writes: list[tuple[list[dict[str, object]], str]] = []

    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT", str(snapshot_path))
    monkeypatch.setenv("FAPAI_CDP_ENDPOINT", "http://host.docker.internal:9223")
    monkeypatch.setattr(server, "_export_auth_cdp_cookies", lambda endpoint: cookies)
    monkeypatch.setattr(
        server,
        "_summarize_auth_cookies",
        lambda exported: {"count": len(exported), "domains": [".taobao.com"], "shape_fingerprint": "shape", "value_fingerprint": "value"},
    )
    monkeypatch.setattr(
        server,
        "_probe_auth_cookie_snapshot_health",
        lambda exported, sample_urls: {"healthy": True, "healthy_samples": 1, "sample_count": len(sample_urls), "sample_results": []},
    )
    monkeypatch.setattr(server, "_write_auth_cookie_snapshot", lambda exported, path: writes.append((list(exported), str(path))))

    result = server._refresh_auth_cookie_snapshot({"sample_urls": ["https://sf.taobao.com/list/50025969__2.htm"]})

    assert result["refreshed"] is True
    assert result["cookie_count"] == 1
    assert result["health"]["healthy_samples"] == 1
    assert writes == [(cookies, str(snapshot_path))]


def test_refresh_auth_cookie_snapshot_derives_node_scoped_path_when_env_is_missing(monkeypatch, tmp_path) -> None:
    from src import server

    repo_root = tmp_path / "project" / "fapaifang"
    repo_root.mkdir(parents=True)
    shared_root = repo_root.parent / "FPFData"
    shared_root.mkdir()
    cookies = [{"name": "cookie2", "value": "v", "domain": ".taobao.com", "path": "/"}]
    writes: list[tuple[list[dict[str, object]], str]] = []

    monkeypatch.delenv("FAPAI_COOKIE_SNAPSHOT", raising=False)
    monkeypatch.setenv("FAPAI_CDP_ENDPOINT", "http://192.168.15.104:9224")
    monkeypatch.setattr(server, "REPO_ROOT", repo_root)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {"cdp_endpoint": "http://192.168.15.104:9224", "node_id": "pc2"},
    )
    monkeypatch.setattr(server, "_export_auth_cdp_cookies", lambda endpoint: cookies)
    monkeypatch.setattr(
        server,
        "_summarize_auth_cookies",
        lambda exported: {"count": len(exported), "domains": [".taobao.com"], "shape_fingerprint": "shape", "value_fingerprint": "value"},
    )
    monkeypatch.setattr(
        server,
        "_probe_auth_cookie_snapshot_health",
        lambda exported, sample_urls: {"healthy": True, "healthy_samples": 1, "sample_count": len(sample_urls), "sample_results": []},
    )
    monkeypatch.setattr(server, "_write_auth_cookie_snapshot", lambda exported, path: writes.append((list(exported), str(path))))

    result = server._refresh_auth_cookie_snapshot({})

    expected = shared_root / "secrets" / "nodes" / "pc2" / "taobao-cookies.json"
    assert result["refreshed"] is True
    assert result["path"] == str(expected)
    assert writes == [(cookies, str(expected))]


def test_refresh_auth_cookie_snapshot_does_not_overwrite_when_probe_is_unhealthy(monkeypatch, tmp_path) -> None:
    from src import server

    snapshot_path = tmp_path / "taobao-cookies.json"
    cookies = [{"name": "cookie2", "value": "v", "domain": ".taobao.com", "path": "/"}]
    writes: list[object] = []

    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT", str(snapshot_path))
    monkeypatch.setenv("FAPAI_CDP_ENDPOINT", "http://host.docker.internal:9223")
    monkeypatch.setattr(server, "_export_auth_cdp_cookies", lambda endpoint: cookies)
    monkeypatch.setattr(
        server,
        "_summarize_auth_cookies",
        lambda exported: {"count": len(exported), "domains": [".taobao.com"], "shape_fingerprint": "shape", "value_fingerprint": "value"},
    )
    monkeypatch.setattr(
        server,
        "_probe_auth_cookie_snapshot_health",
        lambda _exported, _sample_urls: {
            "healthy": False,
            "healthy_samples": 0,
            "sample_count": 1,
            "sample_results": [{"status": "punish_page", "healthy": False}],
        },
    )
    monkeypatch.setattr(server, "_write_auth_cookie_snapshot", lambda *_args: writes.append(_args))

    result = server._refresh_auth_cookie_snapshot({"sample_urls": ["https://sf.taobao.com/list/50025969__2.htm"]})

    assert result["refreshed"] is False
    assert result["reason"] == "cookie_snapshot_candidate_unhealthy"
    assert result["cookie_count"] == 1
    assert result["health"]["healthy_samples"] == 0
    assert writes == []


def test_manual_resume_suppresses_stale_solver_manual_required_result(monkeypatch, tmp_path, capsys) -> None:
    from src import server

    fake_now = [1000.0]

    class FakeSolver:
        last_failure_reason = "manual_required"

        def solve(self):
            fake_now[0] = 1005.0
            server._collection_observer_runtime_control_payload("resume")
            return False

    flag_path = tmp_path / "force_unlock.flag"

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: FakeSolver())
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "time", lambda: fake_now[0])
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "idle")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})
    monkeypatch.setattr(server, "SOLVER_MANUAL_RESUME_EPOCH", 0)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://contest.local/captcha"})

    assert server.PAUSED is False
    assert server.SOLVER_RUNNING is False
    assert server.SOLVER_LAST_STATUS == "resumed"
    assert server.SOLVER_LAST_FAILURE_REASON is None
    assert not flag_path.exists()
    assert "Total time: 5.0s" in capsys.readouterr().out


def test_run_solver_installs_cancel_checker_for_manual_resume(monkeypatch, tmp_path) -> None:
    from src import server

    class FakeSolver:
        last_failure_reason = "cancelled"
        cancel_checker = None

        def solve(self):
            assert self.cancel_checker is not None
            assert self.cancel_checker() is False
            server.SOLVER_MANUAL_RESUME_EPOCH = server.SOLVER_START_TIME + 1
            assert self.cancel_checker() is True
            return False

    fake_solver = FakeSolver()
    flag_path = tmp_path / "force_unlock.flag"

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: fake_solver)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "idle")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})
    monkeypatch.setattr(server, "SOLVER_MANUAL_RESUME_EPOCH", 0)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://contest.local/captcha"})

    assert server.PAUSED is False
    assert server.SOLVER_RUNNING is False
    assert server.SOLVER_LAST_STATUS == "resumed"
    assert server.SOLVER_LAST_FAILURE_REASON is None
    assert not flag_path.exists()


def test_run_solver_waits_for_configured_worker_quiescence(monkeypatch, tmp_path) -> None:
    from src import server

    events: list[object] = []

    class FakeSolver:
        last_failure_reason = None

        def solve(self):
            events.append("solve")
            return True

    def build_solver(_request):
        events.append("build")
        return FakeSolver()

    def wait_for_cdp(_request):
        events.append("cdp_ready")
        return True

    monkeypatch.setenv("FAPAI_SOLVER_WORKER_QUIESCE_SECONDS", "7")
    monkeypatch.setattr(server, "_wait_for_solver_cdp_ready", wait_for_cdp, raising=False)
    monkeypatch.setattr(server, "_build_solver_for_request", build_solver)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(tmp_path / "force_unlock.flag"))
    monkeypatch.setattr(server.time, "sleep", lambda seconds: events.append(("sleep", seconds)))
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "idle")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})
    monkeypatch.setattr(server, "SOLVER_MANUAL_RESUME_EPOCH", 0)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://contest.local/captcha"})

    assert events[:4] == [("sleep", 7), "cdp_ready", "build", "solve"]
    assert server.SOLVER_LAST_STATUS == "solved"


def test_wait_for_solver_cdp_ready_requires_consecutive_healthy_probes(monkeypatch) -> None:
    from src import server

    calls: list[str] = []
    sleep_calls: list[float] = []
    monotonic_values = iter([0.0, 0.0, 1.0, 2.0])

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, _exc_type, _exc, _tb):
            return False

        def read(self):
            return b"[]"

    def fake_urlopen(request, *, timeout):
        calls.append(request.full_url)
        assert timeout == 3
        if len(calls) == 1:
            raise OSError("browser restarting")
        return FakeResponse()

    monkeypatch.setenv("FAPAI_SOLVER_CDP_READY_TIMEOUT_SECONDS", "10")
    monkeypatch.setattr(server, "urlopen", fake_urlopen, raising=False)
    monkeypatch.setattr(server.time, "monotonic", lambda: next(monotonic_values))
    monkeypatch.setattr(server.time, "sleep", lambda seconds: sleep_calls.append(seconds))

    assert server._wait_for_solver_cdp_ready({"cdp_endpoint": "http://192.168.15.104:9224"}) is True
    assert calls == [
        "http://192.168.15.104:9224/json/list",
        "http://192.168.15.104:9224/json/list",
        "http://192.168.15.104:9224/json/list",
    ]
    assert sleep_calls == [2, 2]


def test_mark_manual_required_requests_running_solver_cancel(monkeypatch, tmp_path) -> None:
    from src import server

    fake_now = 1234.0
    flag_path = tmp_path / "force_unlock.flag"

    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "time", lambda: fake_now)
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", True)
    monkeypatch.setattr(server, "SOLVER_CANCEL_EPOCH", 0, raising=False)

    flag_error = server._mark_solver_manual_required()

    assert flag_error is None
    assert server.PAUSED is True
    assert server.SOLVER_CANCEL_EPOCH == fake_now
    assert flag_path.exists()


def test_manual_only_captcha_report_preserves_detail_target_and_disables_auto_retry(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_PENDING_TOKEN", None)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})
    monkeypatch.setattr(server, "SOLVER_MANUAL_ONLY", False, raising=False)

    payload = server._manual_only_captcha_report_payload(
        {
            "target_url": "https://sf-item.taobao.com/sf_item/3001.htm",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "manual_only": True,
        }
    )

    assert payload["status"] == "manual_required"
    assert payload["captcha_solver"]["manual_required"] is True
    assert payload["captcha_solver"]["manual_only"] is True
    assert payload["captcha_solver"]["manual_retry_enabled"] is False
    assert payload["captcha_solver"]["last_request"]["target_url"] == (
        "https://sf-item.taobao.com/sf_item/3001.htm"
    )
    assert flag_path.exists()

    monkeypatch.setattr(server, "SOLVER_MANUAL_ONLY", False)
    assert server._manual_solver_retry_enabled() is False


def test_manual_only_status_survives_restart_from_persisted_flag(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text(
        json.dumps(
            {
                "manual_only": True,
                "last_request": {
                    "node_id": "pc2",
                    "cdp_endpoint": "http://192.168.15.104:9224",
                    "target_url": "https://sf-item.taobao.com/sf_item/3001.htm",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "SOLVER_MANUAL_ONLY", False, raising=False)

    status = server._captcha_solver_runtime_status()

    assert status["manual_required"] is True
    assert status["manual_only"] is True
    assert status["manual_retry_enabled"] is False
    assert status["last_request"]["node_id"] == "pc2"
    assert status["last_request"]["cdp_endpoint"] == "http://192.168.15.104:9224"


def test_solver_cancel_for_manual_required_preserves_manual_pause(monkeypatch, tmp_path) -> None:
    from src import server

    fake_now = [1000.0]
    flag_path = tmp_path / "force_unlock.flag"
    sleep_calls: list[float] = []

    class FakeSolver:
        last_failure_reason = "cancelled"
        cancel_checker = None

        def solve(self):
            fake_now[0] = 1001.0
            server._mark_solver_manual_required()
            return False

    def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        if flag_path.exists():
            flag_path.unlink()

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: FakeSolver())
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "time", lambda: fake_now[0])
    monkeypatch.setattr(server.time, "sleep", fake_sleep)
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "idle")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})
    monkeypatch.setattr(server, "SOLVER_MANUAL_RESUME_EPOCH", 0)
    monkeypatch.setattr(server, "SOLVER_CANCEL_EPOCH", 0, raising=False)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://contest.local/captcha"})

    assert server.PAUSED is True
    assert server.SOLVER_RUNNING is False
    assert server.SOLVER_LAST_STATUS == "manual_required"
    assert server.SOLVER_LAST_FAILURE_REASON == "manual_required"
    assert flag_path.exists()
    assert sleep_calls == []


def test_manual_required_auto_retry_queues_solver_after_cooldown(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("manual verification required", encoding="utf-8")
    queued: list[dict[str, object]] = []

    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "300")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "_probe_solver_cdp_endpoint", lambda endpoint: True)
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 500.0)
    monkeypatch.setattr(server, "SOLVER_MANUAL_REQUIRED_EPOCH", 500.0, raising=False)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {
            "cdp_endpoint": "http://host.docker.internal:9223",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115",
        },
    )
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_LAST_EPOCH", 500.0, raising=False)
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_ATTEMPTS", 0, raising=False)

    result = server._trigger_manual_solver_retry_if_due(
        now=900.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is True
    assert result["attempt"] == 1
    assert queued == [
        {
            "cdp_endpoint": "http://host.docker.internal:9223",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115",
        }
    ]
    assert server.PAUSED is False
    assert server.SOLVER_LAST_STATUS == "manual_retry_queued"
    assert server.SOLVER_LAST_FAILURE_REASON is None
    assert server.SOLVER_MANUAL_RETRY_LAST_EPOCH == 900.0
    assert not flag_path.exists()


def test_manual_required_auto_retry_delegates_pc2_without_clearing_pause(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("manual verification required", encoding="utf-8")
    queued: list[dict[str, object]] = []
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_MANUAL_REQUIRED_EPOCH", 0, raising=False)
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_LAST_EPOCH", 0, raising=False)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm",
        },
    )

    result = server._trigger_manual_solver_retry_if_due(
        now=1000.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is False
    assert result["reason"] == "delegated_to_node_solver"
    assert queued == []
    assert server.PAUSED is True
    assert server.SOLVER_LAST_STATUS == "manual_required"
    assert server.SOLVER_LAST_FAILURE_REASON == "manual_required"
    assert flag_path.exists()


def test_manual_required_auto_retry_respects_cooldown(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("manual verification required", encoding="utf-8")
    queued: list[dict[str, object]] = []

    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "300")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 500.0)
    monkeypatch.setattr(server, "SOLVER_MANUAL_REQUIRED_EPOCH", 500.0, raising=False)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {"target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115"},
    )
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_LAST_EPOCH", 500.0, raising=False)

    result = server._trigger_manual_solver_retry_if_due(
        now=799.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is False
    assert result["reason"] == "cooldown_active"
    assert result["next_retry_epoch"] == 800.0
    assert queued == []
    assert server.PAUSED is True
    assert flag_path.exists()


def test_manual_required_auto_retry_delegates_remote_pc2_even_when_cdp_is_unreachable(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("manual verification required", encoding="utf-8")
    queued: list[dict[str, object]] = []

    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "300")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "_probe_solver_cdp_endpoint", lambda endpoint: False)
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 500.0)
    monkeypatch.setattr(server, "SOLVER_MANUAL_REQUIRED_EPOCH", 500.0, raising=False)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115",
        },
    )
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_LAST_EPOCH", 500.0, raising=False)
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_ATTEMPTS", 7, raising=False)

    result = server._trigger_manual_solver_retry_if_due(
        now=900.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is False
    assert result["reason"] == "delegated_to_node_solver"
    assert result["solver_request"]["cdp_endpoint"] == "http://192.168.15.104:9224"
    assert queued == []
    # manual_required 状态必须原样保留，不能被清成“可继续采集”
    assert server.PAUSED is True
    assert server.SOLVER_LAST_FAILURE_REASON == "manual_required"
    assert flag_path.exists()
    # PC2 owns the retry clock; the NAS monitor must not consume its cooldown.
    assert server.SOLVER_MANUAL_RETRY_ATTEMPTS == 7
    assert server.SOLVER_MANUAL_RETRY_LAST_EPOCH == 500.0


def test_manual_required_auto_retry_queues_when_cdp_endpoint_is_reachable(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("manual verification required", encoding="utf-8")
    queued: list[dict[str, object]] = []
    probed: list[str] = []

    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "300")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(
        server,
        "_probe_solver_cdp_endpoint",
        lambda endpoint: probed.append(endpoint) is None,
    )
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 500.0)
    monkeypatch.setattr(server, "SOLVER_MANUAL_REQUIRED_EPOCH", 500.0, raising=False)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {
            "cdp_endpoint": "http://host.docker.internal:9223",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115",
        },
    )
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_LAST_EPOCH", 500.0, raising=False)
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_ATTEMPTS", 0, raising=False)

    result = server._trigger_manual_solver_retry_if_due(
        now=900.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is True
    assert result["attempt"] == 1
    assert probed == ["http://host.docker.internal:9223"]
    assert len(queued) == 1
    assert server.PAUSED is False
    assert not flag_path.exists()


def test_probe_solver_cdp_endpoint_reports_unreachable_endpoint_as_unhealthy() -> None:
    from src import server

    # 端口 1 上不会有 CDP 监听，探测必须返回 False 而不是抛异常
    assert server._probe_solver_cdp_endpoint("http://127.0.0.1:1") is False


def test_probe_solver_cdp_endpoint_treats_missing_endpoint_as_healthy() -> None:
    from src import server

    # 没有 cdp_endpoint 的请求（例如纯 target_url 重试）不应被探测拦住
    assert server._probe_solver_cdp_endpoint("") is True


def test_manual_required_auto_retry_uses_default_target_when_last_request_is_missing(
    monkeypatch,
    tmp_path,
) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("legacy manual flag without json", encoding="utf-8")
    queued: list[dict[str, object]] = []

    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT_SAMPLE_URLS", "https://sf.taobao.com/list/50025969__2.htm")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_MANUAL_REQUIRED_EPOCH", 0, raising=False)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_LAST_EPOCH", 0, raising=False)

    result = server._trigger_manual_solver_retry_if_due(
        now=1000.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is True
    assert queued == [
        {
            "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
        }
    ]


def test_manual_required_auto_retry_keeps_pc2_delegated_when_seed_stage_has_remaining_work(
    monkeypatch,
    tmp_path,
) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text("manual verification required", encoding="utf-8")
    queued: list[dict[str, object]] = []

    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS", "0")
    monkeypatch.setenv("FAPAI_COOKIE_SNAPSHOT_SAMPLE_URLS", "https://sf.taobao.com/list/50025969__2.htm")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "_probe_solver_cdp_endpoint", lambda endpoint: True)
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_MANUAL_REQUIRED_EPOCH", 0, raising=False)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {
            "cdp_endpoint": "http://192.168.15.104:9224",
            "node_id": "pc2",
            "target_url": "https://sf-item.taobao.com/sf_item/817695886927.htm?track_id=test&__captcha_solver_bg=1",
        },
    )
    monkeypatch.setattr(server, "SOLVER_MANUAL_RETRY_LAST_EPOCH", 0, raising=False)
    monkeypatch.setattr(
        server,
        "_collection_api_lightweight_status_payload",
        lambda: {
            "seed_scan_job_pending": 10,
            "seed_scan_job_in_progress": 1,
            "seed_scan_progress_pending": 20,
            "seed_scan_progress_in_progress": 0,
        },
    )

    result = server._trigger_manual_solver_retry_if_due(
        now=1000.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is False
    assert result["reason"] == "delegated_to_node_solver"
    assert result["solver_request"] == {
        "cdp_endpoint": "http://192.168.15.104:9224",
        "node_id": "pc2",
        "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    }
    assert queued == []


def test_manual_retry_monitor_marks_running_solver_manual_required_after_timeout(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    queued: list[dict[str, object]] = []

    monkeypatch.setenv("FAPAI_SOLVER_MAX_RUNTIME_SECONDS", "120")
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "time", lambda: 221.0)
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "captcha_solver")
    monkeypatch.setattr(server, "SOLVER_RUNNING", True)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 100.0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "running")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_CANCEL_EPOCH", 0, raising=False)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {"target_url": "https://sf.taobao.com/list/50025969__2.htm"})

    result = server._trigger_manual_solver_retry_if_due(
        now=221.0,
        submit_solver=lambda request: queued.append(dict(request)),
    )

    assert result["queued"] is False
    assert result["reason"] == "running_solver_timed_out"
    assert result["elapsed_seconds"] == 121
    assert queued == []
    assert server.PAUSED is True
    assert server.COLLECTION_PAUSE_REASON == "manual_required"
    assert server.SOLVER_LAST_STATUS == "manual_required"
    assert server.SOLVER_LAST_FAILURE_REASON == "manual_required"
    assert server.SOLVER_CANCEL_EPOCH == 221.0
    assert flag_path.exists()


def test_send_json_ignores_client_disconnect() -> None:
    from src import server

    class BrokenWriter:
        def write(self, _body):
            raise BrokenPipeError("client disconnected")

    handler = object.__new__(server.DataHandler)
    handler.wfile = BrokenWriter()
    handler.send_response = lambda *_args, **_kwargs: None
    handler.send_header = lambda *_args, **_kwargs: None
    handler.end_headers = lambda: None

    handler.send_json({"ok": True})


def test_send_error_json_ignores_client_disconnect() -> None:
    from src import server

    class BrokenWriter:
        def write(self, _body):
            raise ConnectionResetError("connection reset")

    handler = object.__new__(server.DataHandler)
    handler.wfile = BrokenWriter()
    handler.send_response = lambda *_args, **_kwargs: None
    handler.send_header = lambda *_args, **_kwargs: None
    handler.end_headers = lambda: None

    handler.send_error_json(500, "TEST_ERROR", "test", {"x": 1})


def test_run_solver_marks_not_running_while_waiting_for_manual_verification(monkeypatch, tmp_path) -> None:
    from src import server

    class FakeSolver:
        last_failure_reason = "manual_required"

        def solve(self):
            return False

    flag_path = tmp_path / "force_unlock.flag"
    snapshots: list[dict[str, object]] = []

    def fake_sleep(_seconds: float) -> None:
        snapshots.append(server._captcha_solver_runtime_status())
        if flag_path.exists():
            flag_path.unlink()

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: FakeSolver())
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "sleep", fake_sleep)
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "idle")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://contest.local/captcha"})

    assert snapshots
    assert snapshots[0]["manual_required"] is True
    assert snapshots[0]["running"] is False
    assert server.SOLVER_RUNNING is False
    assert server.SOLVER_LAST_STATUS == "resumed"


def test_run_solver_manual_required_flag_preserves_retry_request(monkeypatch, tmp_path) -> None:
    from src import server

    class FakeSolver:
        last_failure_reason = "manual_required"

        def solve(self):
            return False

    flag_path = tmp_path / "force_unlock.flag"
    snapshots: list[dict[str, object]] = []

    def fake_sleep(_seconds: float) -> None:
        snapshots.append(json.loads(flag_path.read_text(encoding="utf-8")))
        flag_path.unlink()

    solver_request = {
        "cdp_endpoint": "http://host.docker.internal:9223",
        "target_url": "https://sf.taobao.com/list/50025969__2.htm?location_code=440115",
    }

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: FakeSolver())
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "sleep", fake_sleep)
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "idle")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})

    handler = object.__new__(server.DataHandler)
    handler.run_solver(solver_request)

    assert snapshots
    assert snapshots[0]["manual_required"] is True
    assert snapshots[0]["last_request"] == solver_request


def test_run_solver_success_clears_manual_auth_lock(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"

    class FakeSolver:
        last_failure_reason = None

        def solve(self):
            flag_path.write_text('{"manual_required": true}', encoding="utf-8")
            return True

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: FakeSolver())
    monkeypatch.setattr(server, "_wait_for_solver_cdp_ready", lambda _request: True)
    monkeypatch.setattr(server, "_solver_worker_quiesce_seconds", lambda: 0)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "idle")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})
    monkeypatch.setattr(server, "SOLVER_MANUAL_ONLY", False)
    monkeypatch.setattr(server, "SOLVER_MANUAL_RESUME_EPOCH", 0)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://contest.local/captcha"})

    assert flag_path.exists() is False
    assert server.PAUSED is False
    assert server.COLLECTION_PAUSE_REASON is None
    assert server.SOLVER_LAST_STATUS == "solved"
    assert server.SOLVER_LAST_FAILURE_REASON is None
    assert server._captcha_solver_runtime_status()["manual_required"] is False


def test_run_solver_clears_stale_lock_when_page_already_authenticated(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"
    flag_path.write_text('{"manual_required": true}', encoding="utf-8")

    class FakeSolver:
        last_failure_reason = None
        solve_called = False

        def _preflight_current_challenge(self):
            return {
                "connected": False,
                "manual_required": False,
                "has_slider": False,
                "already_authenticated": True,
            }

        def solve(self):
            self.solve_called = True
            return False

    fake = FakeSolver()
    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: fake)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})
    monkeypatch.setattr(server, "SOLVER_MANUAL_ONLY", False)
    monkeypatch.setattr(server, "SOLVER_MANUAL_RESUME_EPOCH", 0)
    monkeypatch.setattr(server, "SOLVER_PENDING_TOKEN", None)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://sf.taobao.com/list/1.htm"})

    assert fake.solve_called is False
    assert flag_path.exists() is False
    assert server.PAUSED is False
    assert server.COLLECTION_PAUSE_REASON is None
    assert server.SOLVER_LAST_STATUS == "solved"
    assert server.SOLVER_LAST_FAILURE_REASON is None
    assert server._captcha_solver_runtime_status()["manual_required"] is False


def test_run_solver_wait_clears_lock_when_page_becomes_authenticated(monkeypatch, tmp_path) -> None:
    from src import server

    flag_path = tmp_path / "force_unlock.flag"

    class FakeSolver:
        last_failure_reason = "manual_required"

        def solve(self):
            return False

        def _preflight_current_challenge(self):
            return {
                "connected": False,
                "manual_required": False,
                "has_slider": False,
                "already_authenticated": True,
            }

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: FakeSolver())
    monkeypatch.setattr(server, "_wait_for_solver_cdp_ready", lambda _request: True)
    monkeypatch.setattr(server, "_solver_worker_quiesce_seconds", lambda: 0)
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "COLLECTION_PAUSE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "idle")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})
    monkeypatch.setattr(server, "SOLVER_MANUAL_ONLY", False)
    monkeypatch.setattr(server, "SOLVER_MANUAL_RESUME_EPOCH", 0)
    monkeypatch.setattr(server, "SOLVER_PENDING_TOKEN", None)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://sf.taobao.com/list/1.htm"})

    assert flag_path.exists() is False
    assert server.PAUSED is False
    assert server.COLLECTION_PAUSE_REASON is None
    assert server.SOLVER_LAST_STATUS == "solved"
    assert server._captcha_solver_runtime_status()["manual_required"] is False


def test_stale_manual_solver_wait_does_not_clear_new_solver_state(monkeypatch, tmp_path) -> None:
    from src import server

    fake_now = [1000.0]

    class FakeSolver:
        last_failure_reason = "manual_required"

        def solve(self):
            return False

    flag_path = tmp_path / "force_unlock.flag"

    def fake_sleep(_seconds: float) -> None:
        flag_path.unlink()
        fake_now[0] = 2000.0
        server.SOLVER_RUNNING = True
        server.SOLVER_START_TIME = 2000.0
        server.SOLVER_LAST_STATUS = "running"
        server.SOLVER_LAST_FAILURE_REASON = None
        server._set_collection_pause_state(True, "captcha_solver")

    monkeypatch.setattr(server, "_build_solver_for_request", lambda _request: FakeSolver())
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(flag_path))
    monkeypatch.setattr(server.time, "time", lambda: fake_now[0])
    monkeypatch.setattr(server.time, "sleep", fake_sleep)
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_START_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "idle")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", None)
    monkeypatch.setattr(server, "SOLVER_LAST_FINISHED_TIME", 0)
    monkeypatch.setattr(server, "SOLVER_LAST_REQUEST", {})
    monkeypatch.setattr(server, "SOLVER_MANUAL_RESUME_EPOCH", 0)

    handler = object.__new__(server.DataHandler)
    handler.run_solver({"target_url": "https://contest.local/captcha"})

    assert server.PAUSED is True
    assert server.COLLECTION_PAUSE_REASON == "captcha_solver"
    assert server.SOLVER_RUNNING is True
    assert server.SOLVER_START_TIME == 2000.0
    assert server.SOLVER_LAST_STATUS == "running"


def test_api_status_uses_lightweight_payload_when_collection_api_mode_is_enabled(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def seed_queue_counts(self):
            return {
                "seed_scan_job_pending": 1,
                "seed_scan_job_completed": 2,
                "seed_item_pending_detail": 4,
                "seed_item_in_progress": 1,
                "seed_item_detail_completed": 3,
                "seed_item_detail_failed": 2,
                "seed_item_detail_blocked": 1,
                "seed_occurrence_total": 12,
            }

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("full AVM/database status path should not run in collection API mode")

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "_db_counts_snapshot", fail_if_called)
    monkeypatch.setattr(server, "_db_pending_task_candidates", fail_if_called)
    monkeypatch.setattr(server, "_db_collection_stage_snapshot", fail_if_called)
    monkeypatch.setenv("FAPAI_COLLECTION_API_LIGHTWEIGHT_STATUS", "1")

    httpd = server.ReusableTCPServer(("127.0.0.1", 0), server.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as resp:
            assert resp.status == 200
            payload = json.loads(resp.read().decode("utf-8"))
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert payload["collection_api_lightweight"] is True
    assert payload["total_ids"] == 11
    assert payload["seed_scan_job_pending"] == 1
    assert payload["seed_scan_job_completed"] == 2
    assert payload["seed_scan_progress_pending"] == 0
    assert payload["collection_stage"]["seed_queue"]["seed_occurrence_total"] == 12
