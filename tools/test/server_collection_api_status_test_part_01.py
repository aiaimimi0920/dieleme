from tools.test.server_collection_api_status_test_context import *  # noqa: F401,F403


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

def test_real_taobao_solver_targets_are_forced_to_manual_only(monkeypatch) -> None:
    from src import server

    monkeypatch.delenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", raising=False)

    assert server._solver_target_requires_manual_only(
        {"target_url": "https://sf.taobao.com/list/50025969__2.htm"}
    ) is True
    assert server._solver_target_requires_manual_only(
        {"target_url": "https://sf-item.taobao.com/sf_item/570192626894.htm"}
    ) is True
    assert server._solver_target_requires_manual_only(
        {"target_url": "https://contest.local/mock-slider"}
    ) is False

def test_real_taobao_solver_targets_allow_explicit_auto_opt_in(monkeypatch) -> None:
    from src import server

    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")

    assert server._solver_target_requires_manual_only(
        {"target_url": "https://sf.taobao.com/list/50025969__2.htm"}
    ) is False

def test_runtime_status_keeps_taobao_manual_only_after_challenge_memory_resets(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.delenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", raising=False)
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(tmp_path / "missing.flag"))
    monkeypatch.setattr(server, "SOLVER_MANUAL_ONLY", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_PENDING_TOKEN", None)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm",
        },
    )

    status = server._captcha_solver_runtime_status()

    assert status["manual_only"] is True
    assert status["execution_mode"] == "manual"
    assert status["request_owner"] == "pc2"
    assert status["node_solver_expected"] is False

def test_runtime_status_delegates_taobao_when_auto_solver_is_explicitly_enabled(monkeypatch, tmp_path) -> None:
    from src import server

    monkeypatch.setenv("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", "1")
    monkeypatch.setenv("FAPAI_SOLVER_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(tmp_path / "missing.flag"))
    monkeypatch.setattr(server, "SOLVER_MANUAL_ONLY", False)
    monkeypatch.setattr(server, "SOLVER_RUNNING", False)
    monkeypatch.setattr(server, "SOLVER_PENDING_TOKEN", None)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_REQUEST",
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm",
        },
    )

    status = server._captcha_solver_runtime_status()

    assert status["manual_only"] is False
    assert status["execution_mode"] == "delegated_node"
    assert status["request_owner"] == "pc2"
    assert status["node_solver_expected"] is True
    assert status["real_taobao_auto_solver_enabled"] is True

def test_recent_auth_completion_suppresses_same_node_delayed_captcha_report(monkeypatch) -> None:
    from src import server

    completed_request = {
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9223",
        "target_url": "https://sf.taobao.com/list/50025969__2.htm?__captcha_solver_bg=1",
    }
    monkeypatch.setattr(server, "SOLVER_LAST_AUTH_COMPLETED_TIME", 100.0)
    monkeypatch.setattr(server, "SOLVER_LAST_AUTH_COMPLETED_REQUEST", completed_request)
    monkeypatch.setattr(server, "SOLVER_AUTH_REPORT_GRACE_SECONDS", 90.0)

    delayed = {
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9223",
        "url": "https://sf.taobao.com/list/other.htm",
    }

    assert server._solver_report_is_recent_auth_duplicate(delayed, now=150.0) is True
    assert server._solver_report_is_recent_auth_duplicate(delayed, now=191.0) is False

def test_recent_auth_completion_does_not_suppress_a_different_node_report(monkeypatch) -> None:
    from src import server

    monkeypatch.setattr(server, "SOLVER_LAST_AUTH_COMPLETED_TIME", 100.0)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_AUTH_COMPLETED_REQUEST",
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9223",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm",
        },
    )
    monkeypatch.setattr(server, "SOLVER_AUTH_REPORT_GRACE_SECONDS", 90.0)

    assert server._solver_report_is_recent_auth_duplicate(
        {
            "node_id": "pc3",
            "cdp_endpoint": "http://192.168.15.105:9223",
            "target_url": "https://sf.taobao.com/list/other.htm",
        },
        now=150.0,
    ) is False
    assert server._solver_report_is_recent_auth_duplicate(
        {
            "node_id": "pc3",
            "cdp_endpoint": "http://192.168.15.105:9223",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm",
        },
        now=150.0,
    ) is False

def test_recent_auth_with_detail_progress_suppresses_same_node_report_for_three_minutes(monkeypatch) -> None:
    from src import server

    monkeypatch.setattr(server, "SOLVER_LAST_AUTH_COMPLETED_TIME", 100.0)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_AUTH_COMPLETED_REQUEST",
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9223",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm",
        },
    )
    monkeypatch.setattr(server, "SOLVER_LAST_AUTH_DETAIL_CAPTURED_COUNT", 10)
    monkeypatch.setattr(server, "SOLVER_AUTH_REPORT_GRACE_SECONDS", 90.0)
    monkeypatch.setattr(server, "SOLVER_DETAIL_PROGRESS_GRACE_SECONDS", 180.0)
    monkeypatch.setattr(server, "SOLVER_DETAIL_PROGRESS_GRACE_MIN_ITEMS", 1)
    monkeypatch.setattr(server, "_solver_detail_captured_count", lambda: 11)

    report = server._solver_auth_report_suppression(
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9223",
            "url": "https://sf.taobao.com/list/other.htm",
        },
        now=220.0,
    )

    assert report is not None
    assert report["reason"] == "recent_detail_progress"
    assert report["captured_since_auth"] == 1
    assert server._solver_report_is_recent_auth_duplicate(
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9223",
            "url": "https://sf.taobao.com/list/other.htm",
        },
        now=280.0,
    ) is True
    assert server._solver_report_is_recent_auth_duplicate(
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9223",
            "url": "https://sf.taobao.com/list/other.htm",
        },
        now=281.0,
    ) is False

def test_recent_auth_without_detail_progress_does_not_extend_grace(monkeypatch) -> None:
    from src import server

    monkeypatch.setattr(server, "SOLVER_LAST_AUTH_COMPLETED_TIME", 100.0)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_AUTH_COMPLETED_REQUEST",
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9223",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm",
        },
    )
    monkeypatch.setattr(server, "SOLVER_LAST_AUTH_DETAIL_CAPTURED_COUNT", 10)
    monkeypatch.setattr(server, "SOLVER_AUTH_REPORT_GRACE_SECONDS", 90.0)
    monkeypatch.setattr(server, "SOLVER_DETAIL_PROGRESS_GRACE_SECONDS", 180.0)
    monkeypatch.setattr(server, "_solver_detail_captured_count", lambda: 10)

    assert server._solver_auth_report_suppression(
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9223",
            "url": "https://sf.taobao.com/list/other.htm",
        },
        now=220.0,
    ) is None

def test_recent_force_reset_suppresses_only_same_scope_and_node(monkeypatch) -> None:
    from src import server

    monkeypatch.setattr(server, "SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS", 180.0)
    monkeypatch.setattr(
        server,
        "SOLVER_SCOPE_FORCE_RESET_RECOVERIES",
        {"seed": {}, "detail": {}},
    )
    server._remember_solver_force_reset_recovery(
        "seed",
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm",
        },
        now=100.0,
    )

    same_scope = server._solver_force_reset_report_suppression(
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/other.htm",
        },
        now=200.0,
    )

    assert same_scope is not None
    assert same_scope["reason"] == "recent_force_reset"
    assert same_scope["scope"] == "seed"
    assert server._solver_force_reset_report_suppression(
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf-item.taobao.com/sf_item/1.htm",
        },
        now=200.0,
    ) is None
    assert server._solver_force_reset_report_suppression(
        {
            "node_id": "pc3",
            "cdp_endpoint": "http://192.168.15.105:9224",
            "target_url": "https://sf.taobao.com/list/other.htm",
        },
        now=200.0,
    ) is None
    assert server._solver_force_reset_report_suppression(
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9224",
            "target_url": "https://sf.taobao.com/list/other.htm",
        },
        now=281.0,
    ) is None

def test_force_reset_records_scoped_report_grace(monkeypatch, tmp_path) -> None:
    from src import server

    request = {
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9224",
        "target_url": "https://sf.taobao.com/list/50025969__2.htm",
    }
    monkeypatch.setattr(
        server,
        "_solver_scope_runtime_status",
        lambda _scope: {
            "challenge_id": "seed-stuck",
            "challenge_age_seconds": 901.0,
            "last_request": request,
        },
    )
    monkeypatch.setattr(server, "CHALLENGE_FORCE_RESET_SECONDS", 900.0)
    monkeypatch.setattr(server, "_clear_solver_challenge_state", lambda _scope: None)
    monkeypatch.setattr(server, "_set_collection_pause_state", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(server, "_solver_scope_manual_flag_path", lambda _scope: str(tmp_path / "scope.flag"))
    monkeypatch.setattr(server, "_solver_force_unlock_flag_path", lambda: str(tmp_path / "global.flag"))
    monkeypatch.setattr(server, "_read_solver_scope_state", lambda _scope: {})
    monkeypatch.setattr(server, "_collection_effectively_paused", lambda: False)
    monkeypatch.setattr(server, "_captcha_solver_runtime_status", lambda: {})
    remembered = []
    monkeypatch.setattr(
        server,
        "_remember_solver_force_reset_recovery",
        lambda scope, payload: remembered.append((scope, dict(payload))),
    )

    result = server._force_reset_solver_scope("seed", "seed-stuck")

    assert result["force_reset"] is True
    assert result["report_grace_seconds"] == server.SOLVER_FORCE_RESET_REPORT_GRACE_SECONDS
    assert remembered == [("seed", request)]

def test_report_created_before_auth_completion_is_stale_for_same_node(monkeypatch) -> None:
    from src import server

    monkeypatch.setattr(server, "SOLVER_LAST_AUTH_COMPLETED_TIME", 1_787_170_100.0)
    monkeypatch.setattr(
        server,
        "SOLVER_LAST_AUTH_COMPLETED_REQUEST",
        {
            "node_id": "pc2",
            "cdp_endpoint": "http://192.168.15.104:9223",
            "target_url": "https://sf.taobao.com/list/50025969__2.htm",
        },
    )

    stale = {
        "node_id": "pc2",
        "cdp_endpoint": "http://192.168.15.104:9223",
        "url": "https://sf.taobao.com/list/other.htm",
        "timestamp": 1_787_170_099_000,
        "manual_only": True,
    }
    fresh = {**stale, "timestamp": 1_787_170_101_000}
    other_node = {**stale, "node_id": "pc3", "cdp_endpoint": "http://192.168.15.105:9223"}
    other_node_same_target = {
        **stale,
        "node_id": "pc3",
        "cdp_endpoint": "http://192.168.15.105:9223",
        "url": "https://sf.taobao.com/list/50025969__2.htm",
    }

    assert server._solver_report_predates_auth_completion(stale) is True
    assert server._solver_report_predates_auth_completion(fresh) is False
    assert server._solver_report_predates_auth_completion(other_node) is False
    assert server._solver_report_predates_auth_completion(other_node_same_target) is False

def test_report_with_old_challenge_id_is_rejected_after_challenge_changes(monkeypatch) -> None:
    from src import server

    monkeypatch.setattr(server, "SOLVER_CHALLENGE_ID", "challenge-current")

    assert server._solver_report_stale_challenge_id({"challenge_id": "challenge-old"}) == "challenge-old"
    assert server._solver_report_stale_challenge_id({"challenge_id": "challenge-current"}) is None
    assert server._solver_report_stale_challenge_id({}) is None

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
    monkeypatch.setattr(server, "_solver_force_unlock_flag_exists", lambda: False)

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
