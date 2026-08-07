from __future__ import annotations

import json
import threading
import time
import urllib.request


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
    assert payload["paused"] is False
    assert payload["total_ids"] == 11
    assert payload["captured_count"] == 3
    assert payload["ai_finalized_count"] == 3
    assert payload["sniff_queue_count"] == 1
    assert payload["sniff_done_count"] == 2
    assert payload["collection_stage"]["seed_queue"]["seed_occurrence_total"] == 12


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

    assert "商品链接采集" in html
    assert "商品详情页采集" in html
    assert "商品详情页 AI 分析" in html
    assert "/api/collection/overview" in html
    assert "/api/collection/items" in html


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


def test_collection_observer_auth_complete_clears_pause_and_marks_manual_auth(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_refresh_auth_cookie_snapshot", lambda _payload: {"refreshed": False, "reason": "disabled"})
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
    assert payload["runtime_state"] == "运行中"
    assert payload["manual_auth_completed"] is True
    assert server.PAUSED is False
    assert server.SOLVER_LAST_STATUS == "manual_auth_completed"
    assert server.SOLVER_LAST_FAILURE_REASON is None
    assert server.SOLVER_RUNNING is False
    assert payload["captcha_solver"]["running"] is False
    assert server.SOLVER_MANUAL_RESUME_EPOCH > 0
    assert not (tmp_path / "force_unlock.flag").exists()


def test_collection_observer_auth_complete_refreshes_cookie_snapshot_before_resuming(monkeypatch, tmp_path) -> None:
    from src import server

    calls: list[dict[str, object]] = []

    def fake_refresh(payload: dict[str, object]) -> dict[str, object]:
        calls.append(dict(payload))
        return {
            "refreshed": True,
            "path": "/data/secrets/taobao-cookies.json",
            "cookie_count": 49,
            "cdp_endpoint": "http://host.docker.internal:9223",
        }

    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_refresh_auth_cookie_snapshot", fake_refresh)
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")
    (tmp_path / "force_unlock.flag").write_text("manual verification required", encoding="utf-8")

    payload = server._collection_observer_auth_complete_payload({"source": "desktop"})

    assert calls == [{"source": "desktop"}]
    assert payload["ok"] is True
    assert payload["paused"] is False
    assert payload["captcha_solver"]["manual_required"] is False
    assert payload["cookie_snapshot"]["refreshed"] is True
    assert payload["cookie_snapshot"]["cookie_count"] == 49
    assert server.SOLVER_LAST_STATUS == "manual_auth_completed"
    assert not (tmp_path / "force_unlock.flag").exists()


def test_collection_observer_auth_complete_keeps_resume_when_cookie_refresh_fails(monkeypatch, tmp_path) -> None:
    from src import server

    def fake_refresh(_payload: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("cdp unavailable")

    monkeypatch.setattr(server, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_refresh_auth_cookie_snapshot", fake_refresh)
    monkeypatch.setattr(server, "PAUSED", True)
    monkeypatch.setattr(server, "SOLVER_LAST_STATUS", "manual_required")
    monkeypatch.setattr(server, "SOLVER_LAST_FAILURE_REASON", "manual_required")

    payload = server._collection_observer_auth_complete_payload({"source": "desktop"})

    assert payload["ok"] is True
    assert payload["paused"] is False
    assert payload["cookie_snapshot"]["refreshed"] is False
    assert "cdp unavailable" in payload["cookie_snapshot"]["error"]
    assert server.SOLVER_LAST_STATUS == "manual_auth_completed"


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


def test_manual_required_auto_retry_skips_when_cdp_endpoint_is_unreachable(monkeypatch, tmp_path) -> None:
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
    assert result["reason"] == "cdp_endpoint_unhealthy"
    assert result["cdp_endpoint"] == "http://192.168.15.104:9224"
    assert queued == []
    # manual_required 状态必须原样保留，不能被清成“可继续采集”
    assert server.PAUSED is True
    assert server.SOLVER_LAST_FAILURE_REASON == "manual_required"
    assert flag_path.exists()
    # 没有真正提交 solver，attempts 不应增加；但要吃掉一个 cooldown 以免每轮轮询都探测
    assert server.SOLVER_MANUAL_RETRY_ATTEMPTS == 7
    assert server.SOLVER_MANUAL_RETRY_LAST_EPOCH == 900.0


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
    assert payload["collection_stage"]["seed_queue"]["seed_occurrence_total"] == 12
