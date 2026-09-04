from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def _run_auth_cookie_snapshot_retry(
    payload: dict[str, Any],
    completion_id: str | None,
    *,
    finalize_auth: bool = False,
    expected_challenge_id: str | None = None,
    completion_request: dict[str, Any] | None = None,
) -> None:
    max_attempts = _auth_cookie_snapshot_retry_attempts()
    base_backoff = _auth_cookie_snapshot_retry_backoff_seconds()
    last_result: dict[str, Any] = {"refreshed": False, "reason": "not_started"}

    for attempt in range(1, max_attempts + 1):
        _set_auth_cookie_snapshot_state(
            status="running",
            completion_id=completion_id,
            attempts=attempt,
            max_attempts=max_attempts,
            refreshed=False,
            retry_queued=False,
            next_retry_at_epoch=None,
            last_started_at_epoch=time.time(),
        )
        try:
            refreshed = _refresh_auth_cookie_snapshot(payload)
            last_result = dict(refreshed) if isinstance(refreshed, dict) else {
                "refreshed": False,
                "reason": "invalid_refresh_result",
            }
        except Exception as error:
            last_result = {"refreshed": False, "error": repr(error)}

        if last_result.get("refreshed") is True:
            auth_finalization = None
            if finalize_auth:
                auth_finalization = _finalize_auth_completion_after_cookie_snapshot(
                    completion_id,
                    expected_challenge_id=expected_challenge_id,
                    completion_request=completion_request,
                )
                last_result["auth_finalization"] = auth_finalization
            _set_auth_cookie_snapshot_state(
                status="completed",
                completion_id=completion_id,
                attempts=attempt,
                max_attempts=max_attempts,
                refreshed=True,
                retry_queued=False,
                next_retry_at_epoch=None,
                last_finished_at_epoch=time.time(),
                auth_state_confirmed=bool(
                    auth_finalization and auth_finalization.get("auth_state_confirmed") is True
                ),
                result=last_result,
            )
            return
        if last_result.get("reason") == "disabled_by_request":
            _set_auth_cookie_snapshot_state(
                status="skipped",
                completion_id=completion_id,
                attempts=attempt,
                max_attempts=max_attempts,
                refreshed=False,
                retry_queued=False,
                next_retry_at_epoch=None,
                last_finished_at_epoch=time.time(),
                result=last_result,
            )
            return
        if attempt < max_attempts:
            delay = min(base_backoff * (2 ** (attempt - 1)), 300.0)
            _set_auth_cookie_snapshot_state(
                status="pending",
                completion_id=completion_id,
                attempts=attempt,
                max_attempts=max_attempts,
                refreshed=False,
                retry_queued=True,
                next_retry_at_epoch=time.time() + delay,
                result=last_result,
            )
            if delay > 0:
                time.sleep(delay)

    _set_auth_cookie_snapshot_state(
        status="failed",
        completion_id=completion_id,
        attempts=max_attempts,
        max_attempts=max_attempts,
        refreshed=False,
        retry_queued=False,
        next_retry_at_epoch=None,
        last_finished_at_epoch=time.time(),
        result=last_result,
    )

def _schedule_auth_cookie_snapshot_refresh(
    payload: dict[str, Any],
    completion_id: str | None,
    *,
    finalize_auth: bool = False,
    expected_challenge_id: str | None = None,
    completion_request: dict[str, Any] | None = None,
) -> dict[str, Any]:
    global AUTH_COOKIE_SNAPSHOT_THREAD

    if not _payload_flag(payload, "refresh_cookie_snapshot", True):
        return _set_auth_cookie_snapshot_state(
            status="skipped",
            completion_id=completion_id,
            attempts=0,
            max_attempts=0,
            refreshed=False,
            retry_queued=False,
            next_retry_at_epoch=None,
            result={"refreshed": False, "reason": "disabled_by_request"},
        )

    with AUTH_COOKIE_SNAPSHOT_LOCK:
        current = dict(AUTH_COOKIE_SNAPSHOT_STATE)
        if AUTH_COOKIE_SNAPSHOT_THREAD is not None and AUTH_COOKIE_SNAPSHOT_THREAD.is_alive():
            current["retry_queued"] = True
            current["reason"] = "refresh_already_running"
            return current
        if completion_id and current.get("completion_id") == completion_id and current.get("status") == "completed":
            return current
        AUTH_COOKIE_SNAPSHOT_STATE.clear()
        AUTH_COOKIE_SNAPSHOT_STATE.update(
            {
                "status": "pending",
                "completion_id": completion_id,
                "attempts": 0,
                "max_attempts": _auth_cookie_snapshot_retry_attempts(),
                "refreshed": False,
                "retry_queued": True,
                "next_retry_at_epoch": time.time(),
                "auth_finalize_requested": bool(finalize_auth),
                "expected_challenge_id": expected_challenge_id,
            }
        )
        thread = threading.Thread(
            target=_run_auth_cookie_snapshot_retry,
            args=(dict(payload), completion_id),
            kwargs={
                "finalize_auth": bool(finalize_auth),
                "expected_challenge_id": expected_challenge_id,
                "completion_request": dict(completion_request or {}),
            },
            name="auth-cookie-snapshot-refresh",
            daemon=True,
        )
        AUTH_COOKIE_SNAPSHOT_THREAD = thread
        scheduled = dict(AUTH_COOKIE_SNAPSHOT_STATE)
        thread.start()
        return scheduled

def _prefer_db_task_reads() -> bool:
    return DB_REPOSITORY.enabled and _runtime_env_flag("FAPAI_DB_PREFER_RUNTIME_INDEX", True)

def _db_pending_task_candidates(limit=100):
    if not _prefer_db_task_reads():
        return []
    try:
        return DB_REPOSITORY.iter_pending_task_items(limit=limit)
    except Exception as error:
        print(f"[DB] Pending task query failed: {error}")
    return []

def _db_counts_snapshot():
    if not DB_REPOSITORY.enabled:
        return {
            "db_total_ids": 0,
            "db_processed_ids": 0,
            "db_pending_ids": 0,
            "db_detail_captured_ids": 0,
        }
    try:
        return DB_REPOSITORY.counts_snapshot()
    except Exception:
        return {
            "db_total_ids": DB_REPOSITORY.count_listings(),
            "db_processed_ids": DB_REPOSITORY.count_processed_listings(),
            "db_pending_ids": DB_REPOSITORY.count_pending_task_items(),
            "db_detail_captured_ids": DB_REPOSITORY.count_detail_captured_items(),
        }

def _db_data_supply_snapshot(hours: int = 24):
    if not DB_REPOSITORY.enabled or not hasattr(DB_REPOSITORY, "event_type_counts"):
        return {
            "detail_archive_fetch_recent": {},
            "maintenance_writeback_recent": {},
            "stage_transition_recent": {},
        }
    fetch_counts = DB_REPOSITORY.event_type_counts(
        (
            "detail_archive_fetched",
            "detail_archive_fetch_blocked",
            "detail_archive_fetch_failed",
        ),
        hours=hours,
    )
    maintenance_counts = DB_REPOSITORY.event_type_counts(
        (
            "detail_replay_prepared",
            "recent_coordinate_backfill",
            "archived_detail_backfill",
        ),
        hours=hours,
    )
    stage_transition_counts = DB_REPOSITORY.event_type_counts(
        (
            "seed_stage_transition",
            "detail_stage_transition",
            "analysis_stage_transition",
            "analysis_ready_transition",
        ),
        hours=hours,
    )
    return {
        "detail_archive_fetch_recent": fetch_counts,
        "maintenance_writeback_recent": maintenance_counts,
        "stage_transition_recent": stage_transition_counts,
    }

def _collection_api_lightweight_status_enabled() -> bool:
    return _runtime_env_flag("FAPAI_COLLECTION_API_LIGHTWEIGHT_STATUS", False)

def _build_info_payload() -> dict[str, str]:
    return {
        "version": str(os.getenv("FAPAI_BUILD_VERSION") or "development"),
        "commit": str(os.getenv("FAPAI_BUILD_COMMIT") or "unknown"),
        "built_at": str(os.getenv("FAPAI_BUILD_TIME") or "unknown"),
        "source_digest": str(os.getenv("FAPAI_SOURCE_DIGEST") or "unknown"),
    }

def _empty_seed_queue_counts() -> dict[str, Any]:
    return {
        "seed_scan_job_pending": 0,
        "seed_scan_job_in_progress": 0,
        "seed_scan_job_completed": 0,
        "seed_scan_job_blocked": 0,
        "seed_scan_progress_pending": 0,
        "seed_scan_progress_in_progress": 0,
        "seed_scan_progress_exhausted": 0,
        "seed_scan_progress_blocked": 0,
        "seed_item_pending_detail": 0,
        "seed_item_in_progress": 0,
        "seed_item_raw_detail_captured": 0,
        "seed_item_analysis_in_progress": 0,
        "seed_item_analysis_failed": 0,
        "seed_item_analysis_blocked": 0,
        "seed_item_detail_completed": 0,
        "seed_item_detail_failed": 0,
        "seed_item_detail_blocked": 0,
        "seed_occurrence_total": 0,
    }

def _collection_api_lightweight_status_payload() -> dict[str, Any]:
    seed_queue_counts = _empty_seed_queue_counts()
    if DB_REPOSITORY.enabled and hasattr(DB_REPOSITORY, "seed_queue_counts"):
        try:
            seed_queue_counts.update(DB_REPOSITORY.seed_queue_counts())
        except Exception as error:
            seed_queue_counts["error"] = str(error)
    elif DB_REPOSITORY.enabled and hasattr(DB_REPOSITORY, "search_task_counts"):
        try:
            search_counts = DB_REPOSITORY.search_task_counts()
            seed_queue_counts["seed_scan_job_pending"] = int(search_counts.get("search_pending", 0) or 0)
            seed_queue_counts["seed_scan_job_in_progress"] = int(search_counts.get("search_in_progress", 0) or 0)
            seed_queue_counts["seed_scan_job_completed"] = int(search_counts.get("search_done", 0) or 0)
            seed_queue_counts["seed_scan_job_blocked"] = int(search_counts.get("search_pruned", 0) or 0)
        except Exception as error:
            seed_queue_counts["error"] = str(error)

    pending_detail = int(seed_queue_counts.get("seed_item_pending_detail", 0) or 0)
    in_progress = int(seed_queue_counts.get("seed_item_in_progress", 0) or 0)
    raw_detail_captured = int(seed_queue_counts.get("seed_item_raw_detail_captured", 0) or 0)
    analysis_in_progress = int(seed_queue_counts.get("seed_item_analysis_in_progress", 0) or 0)
    analysis_failed = int(seed_queue_counts.get("seed_item_analysis_failed", 0) or 0)
    analysis_blocked = int(seed_queue_counts.get("seed_item_analysis_blocked", 0) or 0)
    detail_completed = int(seed_queue_counts.get("seed_item_detail_completed", 0) or 0)
    detail_failed = int(seed_queue_counts.get("seed_item_detail_failed", 0) or 0)
    detail_blocked = int(seed_queue_counts.get("seed_item_detail_blocked", 0) or 0)
    raw_capture_pending = pending_detail + in_progress
    analysis_ready = raw_detail_captured + analysis_failed
    analysis_pending = raw_detail_captured + analysis_in_progress + analysis_failed
    analysis_terminal = analysis_blocked
    captured_items = analysis_pending + analysis_terminal + detail_completed
    total_items = pending_detail + in_progress + captured_items + detail_failed + detail_blocked
    api_metrics = llm_helper.get_api_metrics()
    top_level_seed_queue_counts = {
        key: int(seed_queue_counts.get(key, 0) or 0)
        for key in _empty_seed_queue_counts().keys()
    }
    solver_status_snapshot = _captcha_solver_runtime_status()

    payload = {
        "collection_api_lightweight": True,
        "build_info": _build_info_payload(),
        "capabilities": {
            "manual_captcha_report_v1": True,
            "nas_auth_recovery_v1": True,
        },
        "paused": bool(solver_status_snapshot.get("paused")),
        "total_ids": total_items,
        "captured_count": captured_items,
        "ai_finalized_count": detail_completed,
        "db_mode": DB_REPOSITORY.enabled,
        "db_total_ids": total_items,
        "db_processed_ids": detail_completed,
        "db_pending_ids": pending_detail + in_progress,
        "db_detail_captured_ids": captured_items,
        "db_analysis_pending_ids": analysis_pending,
        "raw_capture_pending_count": raw_capture_pending,
        "raw_captured_count": raw_detail_captured,
        "analysis_ready_count": analysis_ready,
        "analysis_in_progress_count": analysis_in_progress,
        "analysis_failed_count": analysis_failed,
        "analysis_pending_count": analysis_pending,
        "analysis_backlog_count": analysis_pending,
        "analysis_blocked_count": analysis_blocked,
        "analysis_finalized_count": detail_completed,
        "detail_failed_count": detail_failed,
        "detail_blocked_count": detail_blocked,
        "sniff_queue_count": int(seed_queue_counts.get("seed_scan_job_pending", 0) or 0),
        "sniff_done_count": int(seed_queue_counts.get("seed_scan_job_completed", 0) or 0),
        "next_batch_preview": [],
        "api_success_rate": api_metrics.get("success_rate", 0.0),
        "api_avg_response_time_ms": api_metrics.get("avg_response_time_ms", 0.0),
        "api_total_calls": api_metrics.get("total_calls", 0),
        "api_success_calls": api_metrics.get("success_calls", 0),
        **top_level_seed_queue_counts,
        "captcha_solver": solver_status_snapshot,
        "auth_recovery": NAS_AUTH_RECOVERY.snapshot(),
        "collection_scopes": solver_status_snapshot.get("collection_scopes", {}),
        "data_supply_recent_24h": {},
        "avm": {"lightweight_skipped": True},
        "collection_stage": {
            "lightweight": True,
            "seed_queue": seed_queue_counts,
            "seed_stage": {"stored": int(seed_queue_counts.get("seed_occurrence_total", 0) or 0)},
            "detail_stage": {
                "pending": pending_detail,
                "in_progress": in_progress,
                "raw_pending": pending_detail,
                "raw_in_progress": in_progress,
                "raw_archived": raw_detail_captured,
                "raw_captured": raw_detail_captured,
                "raw_failed": detail_failed,
                "raw_blocked": detail_blocked,
                "analysis_ready": analysis_ready,
                "analysis_in_progress": analysis_in_progress,
                "analysis_failed": analysis_failed,
                "analysis_blocked": analysis_blocked,
                "analysis_pending": analysis_pending,
                "analysis_backlog": analysis_pending,
                "archived": captured_items,
                "ai_finalized": detail_completed,
                "analysis_finalized": detail_completed,
                "failed": detail_failed,
                "blocked": detail_blocked,
            },
            "search_tasks": {
                "search_pending": int(seed_queue_counts.get("seed_scan_job_pending", 0) or 0),
                "search_in_progress": int(seed_queue_counts.get("seed_scan_job_in_progress", 0) or 0),
                "search_done": int(seed_queue_counts.get("seed_scan_job_completed", 0) or 0),
                "search_pruned": int(seed_queue_counts.get("seed_scan_job_blocked", 0) or 0),
            },
        },
    }
    payload["runtime_state"] = _collection_runtime_state_label_from_status_payload(payload)
    return payload

def _collection_query_int(query: dict[str, list[str]], key: str, default: int, *, minimum: int, maximum: int) -> int:
    try:
        value = int((query.get(key) or [default])[0])
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))

def _collection_observer_overview_payload() -> dict[str, Any]:
    status = _collection_api_lightweight_status_payload()
    seed_queue = dict((status.get("collection_stage") or {}).get("seed_queue") or {})
    active_data_root = Path(getattr(AVM_SERVICE, "data_dir", DATA_DIR))
    return {
        "ok": True,
        "status": status,
        "runtime_state": status.get("runtime_state"),
        "challenge_metrics": _hybrid_collection_challenge_metrics_summary(active_data_root),
        "auth_watcher": _pc1_auth_auto_resume_state_summary(active_data_root),
        "modules": {
            "links": {
                "label": "商品链接采集",
                "total": int(seed_queue.get("seed_occurrence_total", 0) or 0),
                "unique_items": int(status.get("total_ids", 0) or 0),
            },
            "details": {
                "label": "商品详情页采集",
                "pending": int(status.get("raw_capture_pending_count", 0) or 0),
                "raw_captured": int(status.get("raw_captured_count", 0) or 0),
                "captured": int(status.get("captured_count", 0) or 0),
                "failed": int(status.get("detail_failed_count", 0) or 0),
                "blocked": int(status.get("detail_blocked_count", 0) or 0),
            },
            "analysis": {
                "label": "商品详情页 AI 分析",
                "ready": int(status.get("analysis_ready_count", 0) or 0),
                "pending": int(status.get("analysis_pending_count", 0) or 0),
                "failed": int(status.get("analysis_failed_count", 0) or 0),
                "blocked": int(status.get("analysis_blocked_count", 0) or 0),
                "finalized": int(status.get("analysis_finalized_count", status.get("ai_finalized_count", 0)) or 0),
            },
        },
    }

__all__ = ["_run_auth_cookie_snapshot_retry", "_schedule_auth_cookie_snapshot_refresh", "_prefer_db_task_reads", "_db_pending_task_candidates", "_db_counts_snapshot", "_db_data_supply_snapshot", "_collection_api_lightweight_status_enabled", "_build_info_payload", "_empty_seed_queue_counts", "_collection_api_lightweight_status_payload", "_collection_query_int", "_collection_observer_overview_payload"]
