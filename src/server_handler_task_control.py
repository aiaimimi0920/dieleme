from __future__ import annotations

import logging

from .server_context import *  # noqa: F401,F403

logger = logging.getLogger(__name__)

def _post_recent_detail_replay(self):
    self._submit_maintenance_job('recent_detail_replay', 'AVM_RECENT_DETAIL_REPLAY_FAILED')

def _get_pipeline_status(self, parsed, request_path, query):
    try:
        self.send_json(AVM_PIPELINE.status())
    except Exception as e:
        self.send_error_json(status=500, code='AVM_PIPELINE_STATUS_FAILED', message='pipeline 状态查询失败', details={'error': str(e)})

def _get_merge_check(self, parsed, request_path, query):
    try:
        self.send_json(AVM_PIPELINE.verify_merge_completeness())
    except Exception as e:
        self.send_error_json(status=500, code='AVM_MERGE_CHECK_FAILED', message='merge completeness 校验失败', details={'error': str(e)})

def _get_item(self, parsed, request_path, query):
    runtime_index = _collection_runtime_index()
    query = urlparse(self.path).query
    params = parse_qs(query)
    item_id = params.get('id', [''])[0].strip()
    if not item_id:
        self.send_error_json(status=400, code='AVM_INVALID_ID', message='id is required')
        return
    lookup_failed = False
    if item_id and DB_REPOSITORY.enabled:
        try:
            db_item = DB_REPOSITORY.get_flat_item(item_id)
            if db_item:
                self.send_json(db_item)
                return
        except Exception:
            lookup_failed = True
            logger.exception("/api/get_item database lookup failed item=%s", item_id)
    get_seen = getattr(runtime_index, "get_seen", None)
    if get_seen is not None:
        runtime_entry = get_seen(item_id)
    else:
        with runtime_index.lock:
            runtime_entry = runtime_index.seen_ids.get(item_id)
    if runtime_entry is not None:
        self.send_json(runtime_entry['data'])
    elif lookup_failed:
        self.send_error_json(status=503, code='AVM_ITEM_LOOKUP_UNAVAILABLE', message='Item storage is unavailable')
    else:
        self.send_error_json(status=404, code='AVM_DETAIL_ITEM_NOT_FOUND', message='Item not found', details={'id': item_id})

def _post_seed_next_task(self):
    accepted, payload = _read_json_body(self)
    if not accepted:
        return
    session_id = payload.get('session_id', 'default')
    if not isinstance(session_id, str) or not session_id.strip() or len(session_id) > 128:
        self.send_error_json(status=400, code='AVM_INVALID_SESSION_ID', message='Invalid collection session ID', details={})
        return
    try:
        self.send_json(_seed_collection_service().next_task(session_id, paused=_collection_scope_effectively_paused('seed')))
    except Exception as e:
        self.send_error_json(status=500, code='AVM_SEED_NEXT_TASK_FAILED', message='种子任务分发失败', details={'error': str(e)})

def _post_detail_tasks(self):
    runtime_index = _collection_runtime_index()
    legacy_pending = globals().get("PENDING_TASKS")
    if isinstance(legacy_pending, list) and legacy_pending is not runtime_index.pending_tasks:
        runtime_index.pending_tasks = legacy_pending
    legacy_dispatched = globals().get("DISPATCHED_TASKS")
    if isinstance(legacy_dispatched, dict) and legacy_dispatched is not runtime_index.dispatched_tasks:
        runtime_index.dispatched_tasks = legacy_dispatched
    accepted, _payload = _read_json_body(self)
    if not accepted:
        return
    if _collection_scope_effectively_paused('detail'):
        self.send_json({'tasks': []})
        return
    batch_size = 300
    if _prefer_db_task_reads():
        try:
            result = _detail_collection_service().batch_tasks(dispatched_tasks=runtime_index.dispatched_tasks, cooldown_seconds=DISPATCH_COOLDOWN_SECONDS, batch_size=batch_size, mark_dispatched=runtime_index.mark_dispatched, get_dispatched=runtime_index.get_dispatched, prune_dispatched=runtime_index.prune_dispatched)
        except Exception as e:
            self.send_error_json(status=500, code='AVM_DETAIL_BATCH_TASKS_FAILED', message='详情批量任务分发失败', details={'error': str(e)})
            return
        self.send_json({'tasks': result['tasks'], 'total': result['total'], 'done': result['done']})
        if len(result['tasks']) > 0:
            logger.info("Dispatched detail tasks count=%s batch_limit=%s pending=%s", len(result['tasks']), batch_size, result['pending'])
        else:
            logger.debug("Returned zero detail tasks")
        return
    with DATA_LOCK:
        tasks, total_count, done_count, pending_count = runtime_index.claim_pending_batch(
            _utc_now(), DISPATCH_COOLDOWN_SECONDS, batch_size
        )
    self.send_json({'tasks': tasks, 'total': total_count, 'done': done_count})
    logger.info("Dispatched detail tasks count=%s batch_limit=%s pending=%s", len(tasks), batch_size, pending_count)

def _get_api_not_found(self, parsed, request_path, query):
    self.send_error_json(status=404, code='AVM_ENDPOINT_NOT_FOUND', message='未找到接口', details={'path': request_path})

def _server_get_fallback(self, parsed, request_path, query):
    self.send_response(404)
    self.end_headers()

def _post_seed_progress(self):
    (accepted, data) = _read_json_body(self)
    if not accepted:
        return
    try:
        url = data.get('url')
        task_key = data.get('task_key')
        has_next = data.get('has_next', True)
        is_empty = data.get('is_empty', False)
        page_num = data.get('page_num', 1)
        total_pages = data.get('total_pages')
        zero_bid_detected = data.get('zero_bid_detected', False)
        log_msg = f'[SNIFF REPORT] Page {page_num} | Next: {has_next} | Empty: {is_empty} | TotalPages: {total_pages}'
        if zero_bid_detected:
            log_msg += ' | [ZERO-BID EARLY TERMINATION]'
        logger.info("%s | URL: %s", log_msg, url)
        if url or task_key:
            self.send_json(_seed_collection_service().report_progress(data))
        else:
            self.send_error_json(status=400, code='AVM_SEED_PROGRESS_MISSING_URL', message='缺少 URL 或 task_key', details={'required_any': ['url', 'task_key']})
    except ValueError as e:
        logger.warning("Invalid report_sniff_status payload: %s", e)
        self.send_error_json(status=400, code='AVM_SEED_PROGRESS_INVALID', message='种子进度参数无效', details={'error': str(e)})
    except Exception as e:
        logger.exception("Error in report_sniff_status")
        self.send_error_json(status=500, code='AVM_SEED_PROGRESS_FAILED', message='种子进度回报失败', details={'error': str(e)})

def _post_region_reset_links(self):
    if not _require_control_plane(self):
        return
    (accepted, payload) = _read_json_body(self)
    if not accepted:
        return
    try:
        result = _collection_observer_reset_region_links_payload(payload)
    except Exception as e:
        self.send_error_json(status=500, code='COLLECTION_OBSERVER_REGION_RESET_FAILED', message='地区链接采集重置失败', details={'error': str(e)})
        return
    status = 200 if result.get('ok') else 400
    if status != 200:
        self.send_error_json(status=status, code='COLLECTION_OBSERVER_REGION_RESET_REJECTED', message='地区链接采集重置请求被拒绝', details=result)
        return
    self.send_json(result)

def _post_item_reanalyze(self):
    if not _require_control_plane(self):
        return
    (accepted, payload) = _read_json_body(self)
    if not accepted:
        return
    try:
        result = _collection_observer_reanalysis_payload(payload)
    except Exception as e:
        self.send_error_json(status=500, code='COLLECTION_OBSERVER_REANALYZE_FAILED', message='AI 再分析入队失败', details={'error': str(e)})
        return
    status = 200 if result.get('ok') else 400
    if status != 200:
        self.send_error_json(status=status, code='COLLECTION_OBSERVER_REANALYZE_REJECTED', message='AI 再分析请求被拒绝', details=result)
        return
    self.send_json(result)

def _post_item_manual_update(self):
    if not _require_control_plane(self):
        return
    (accepted, payload) = _read_json_body(self)
    if not accepted:
        return
    try:
        result = _collection_observer_manual_update_payload(payload)
    except Exception as e:
        self.send_error_json(status=500, code='COLLECTION_OBSERVER_MANUAL_UPDATE_FAILED', message='手动更新标准化数据失败', details={'error': str(e)})
        return
    status = 200 if result.get('ok') else 400
    if status != 200:
        self.send_error_json(status=status, code='COLLECTION_OBSERVER_MANUAL_UPDATE_REJECTED', message='手动更新标准化数据请求被拒绝', details=result)
        return
    self.send_json(result)

def _post_collection_control(self):
    if not _require_control_plane(self):
        return
    accepted, _payload = _read_json_body(self)
    if not accepted:
        return
    action = 'pause' if urlparse(self.path).path.endswith('/pause') else 'resume'
    try:
        result = _collection_observer_runtime_control_payload(action)
    except Exception as e:
        self.send_error_json(status=500, code='COLLECTION_OBSERVER_RUNTIME_CONTROL_FAILED', message='采集运行状态切换失败', details={'error': str(e), 'action': action})
        return
    status = 200 if result.get('ok') else 400
    if status != 200:
        self.send_error_json(status=status, code='COLLECTION_OBSERVER_RUNTIME_CONTROL_REJECTED', message='采集运行状态切换请求被拒绝', details=result)
        return
    self.send_json(result)

def _post_auth_recovery_transition(self):
    (authorized, auth_error) = _nas_auth_recovery_authorized(self.headers)
    if not authorized:
        self.send_error_json(status=403, code='COLLECTION_AUTH_RECOVERY_FORBIDDEN', message='跨设备认证恢复凭据无效', details={'error': auth_error})
        return
    (accepted, payload) = _read_json_body(self)
    if not accepted:
        return
    if urlparse(self.path).path.endswith('/heartbeat'):
        if payload.get('protocol_version') != 2 or payload.get('node_id') != 'pc2':
            self.send_error_json(status=400, code='COLLECTION_AUTH_RECOVERY_REJECTED', message='PC2 protocol version 2 is required')
            return
        NAS_AUTH_RECOVERY.register_stage_auth_pc2()
        self.send_json({'ok': True})
        return
    recovery_id = str(payload.get('recovery_id') or '').strip()
    if not recovery_id:
        result = {'ok': False, 'error': 'recovery_id is required'}
    elif urlparse(self.path).path.endswith('/claim'):
        role = str(payload.get('role') or '').strip().lower()
        node_id = str(payload.get('node_id') or '').strip().lower()
        if (role, node_id) not in {('pc1', 'pc1'), ('pc2', 'pc2')}:
            result = {'ok': False, 'error': 'role and node_id must identify pc1 or pc2'}
        else:
            result = NAS_AUTH_RECOVERY.claim(role, recovery_id, node_id)
    elif urlparse(self.path).path.endswith('/snapshot_ready'):
        try:
            result = NAS_AUTH_RECOVERY.snapshot_ready(recovery_id, sha256=str(payload.get('sha256') or ''), cookie_count=int(payload.get('cookie_count') or 0), created_at_epoch=float(payload.get('created_at_epoch') or time.time()))
        except (TypeError, ValueError) as error:
            result = {'ok': False, 'error': str(error)}
    elif urlparse(self.path).path.endswith('/pc2_restarting'):
        result = NAS_AUTH_RECOVERY.pc2_restarting(recovery_id)
    else:
        result = _nas_auth_recovery_result(payload)
    if not result.get('ok'):
        self.send_error_json(status=409 if result.get('stale_recovery') else 400, code='COLLECTION_AUTH_RECOVERY_REJECTED', message='跨设备认证恢复请求被拒绝', details=result)
        return
    self.send_json(result)

def _post_auth_force_reset(self):
    if not _require_node_auth(self):
        return
    (accepted, payload) = _read_json_body(self)
    if not accepted:
        return
    result = _force_reset_solver_scope(payload.get('scope'), payload.get('challenge_id'))
    status = 200 if result.get('ok') or result.get('stale_challenge') else 409
    if status != 200:
        self.send_error_json(status=status, code='COLLECTION_CHALLENGE_FORCE_RESET_REJECTED', message='验证码尚未达到保底重置时间或状态不匹配', details=result)
        return
    self.send_json(result)

def _post_auth_complete(self):
    if not _require_node_auth(self):
        return
    (accepted, payload) = _read_json_body(self)
    if not accepted:
        return
    if ((payload.get('cdp_endpoint') and not _cdp_endpoint_permitted(payload['cdp_endpoint']))
            or (payload.get('cookie_snapshot_path') and not _resolve_auth_cookie_snapshot_path(payload))):
        self.send_error_json(status=400, code='COLLECTION_AUTH_TARGET_REJECTED', message='Untrusted authentication target', details={})
        return
    try:
        result = _collection_observer_auth_complete_payload(payload)
    except Exception as e:
        self.send_error_json(status=500, code='COLLECTION_OBSERVER_AUTH_COMPLETE_FAILED', message='人工认证完成通知失败', details={'error': str(e)})
        return
    status = 200 if result.get('ok') or result.get('stale_challenge') else 400
    if status != 200:
        self.send_error_json(status=status, code='COLLECTION_OBSERVER_AUTH_COMPLETE_REJECTED', message='人工认证完成通知被拒绝', details=result)
        return
    self.send_json(result)

def _post_auth_resume_after_cooldown(self):
    if not _require_node_auth(self):
        return
    (accepted, payload) = _read_json_body(self)
    if not accepted:
        return
    try:
        result = _collection_observer_resume_after_cooldown_payload(payload)
    except Exception as e:
        self.send_error_json(status=500, code='COLLECTION_OBSERVER_AUTH_RESUME_FAILED', message='冷却后恢复采集失败', details={'error': str(e)})
        return
    status = 200 if result.get('ok') or result.get('stale_challenge') else 400
    if status != 200:
        self.send_error_json(status=status, code='COLLECTION_OBSERVER_AUTH_RESUME_REJECTED', message='冷却后恢复采集请求被拒绝', details=result)
        return
    self.send_json(result)

__all__ = ["_post_recent_detail_replay", "_get_pipeline_status", "_get_merge_check", "_get_item", "_post_seed_next_task", "_post_detail_tasks", "_get_api_not_found", "_server_get_fallback", "_post_seed_progress", "_post_region_reset_links", "_post_item_reanalyze", "_post_item_manual_update", "_post_collection_control", "_post_auth_recovery_transition", "_post_auth_force_reset", "_post_auth_complete", "_post_auth_resume_after_cooldown"]
