from __future__ import annotations

import logging

from .server_context import *  # noqa: F401,F403

logger = logging.getLogger(__name__)

def _run_analysis_screen(payload):
    runtime_index = _collection_runtime_index()
    items = payload.get('items', [])
    threshold = payload.get('margin_threshold')
    try:
        if threshold is None:
            threshold = get_effective_alert_threshold(DEFAULT_MARGIN_THRESHOLD)
        else:
            threshold = float(threshold)
    except Exception:
        threshold = get_effective_alert_threshold(DEFAULT_MARGIN_THRESHOLD)
    results = []
    for raw in items:
        if isinstance(raw, dict):
            item_id = str(raw.get('id', '')).strip()
        else:
            item_id = str(raw).strip()
        if not item_id:
            continue
        with runtime_index.lock:
            entry = runtime_index.seen_ids.get(item_id)
        if entry is None and DB_REPOSITORY.enabled:
            try:
                db_item = DB_REPOSITORY.get_flat_item(item_id)
            except Exception as db_screen_error:
                logger.exception('[DB] screen item lookup failed item=%s', item_id)
                db_item = None
            if db_item and entry is None:
                entry = {'data': db_item}
        source_data = dict(entry.get('data', {})) if entry else {}
        if isinstance(raw, dict):
            source_data.update(raw)
        try:
            prediction = AVM_SERVICE.predict_by_item_data(source_data)
        except Exception:
            prediction = {}
        if prediction.get('predicted_price') is not None:
            source_data['predicted_price'] = prediction.get('predicted_price')
            source_data['predicted_unit_price'] = prediction.get('predicted_unit_price')
            source_data['prediction'] = prediction
        result = build_avm_result(item_id, source_data)
        if prediction:
            result['prediction'] = prediction
            result['risk_validation'] = dict(prediction.get('risk_validation') or {})
            result['manual_review_recommended'] = bool(prediction.get('manual_review_recommended'))
            result['manual_review_reasons'] = list(prediction.get('manual_review_reasons') or [])
        else:
            result['risk_validation'] = {}
            result['manual_review_recommended'] = False
            result['manual_review_reasons'] = []
        result['alert_blockers'] = build_alert_blockers(margin=result.get('margin'), threshold=threshold, is_malignant_risk=bool(result.get('is_malignant_risk')), payload=prediction)
        result['meets_alert_threshold'] = len(result['alert_blockers']) == 0
        results.append(result)
    results.sort(key=lambda x: x.get('margin') if x.get('margin') is not None else -999, reverse=True)
    alerts = []
    now = _utc_now().strftime('%Y-%m-%d %H:%M:%S')
    for result in results:
        if result['meets_alert_threshold']:
            alert = dict(result)
            alert['created_at'] = now
            alert['margin_threshold'] = threshold
            alerts.append(alert)
    write_avm_alerts(alerts)
    summary = summarize_screen_results(results)
    return {'model_version': AVM_SERVICE.model_version(), 'margin_formula': '(predicted_price - starting_price) / predicted_price', 'margin_threshold': threshold, 'total': len(results), 'alerts_written': len(alerts), 'summary': summary, 'results': results}

def _post_analysis_screen(self):
    if not _require_control_plane(self):
        return
    accepted, payload = _read_json_body(self)
    if not accepted:
        return
    execution_mode = _read_execution_mode(self, payload)
    if execution_mode is None:
        return
    items = payload.get('items', [])
    if not isinstance(items, list):
        self.send_error_json(status=400, code='AVM_INVALID_SCREEN_ITEMS', message='items 必须为数组', details={'invalid_fields': ['items']})
        return
    screen_payload = dict(payload)
    screen_payload.pop('execution_mode', None)
    if execution_mode == 'async':
        def work():
            return _run_analysis_screen(screen_payload)

        self._enqueue_collection_job(
            'avm_screen',
            work,
            'AVM_SCREEN_ASYNC_FAILED',
            response_extra={'execution_mode': 'async'},
        )
        return
    try:
        self.send_json(_run_analysis_screen(screen_payload))
    except Exception as e:
        self.send_error_json(status=500, code='AVM_SCREEN_FAILED', message='批量筛选执行失败', details={'error': str(e)})

def _post_captcha_report(self):
    (accepted, payload) = _read_json_body(self)
    if not accepted:
        return
    solver_request = _build_solver_request(payload)
    challenge_scope = _challenge_scope_for_request(solver_request)
    stale_challenge_id = _solver_report_stale_challenge_id(payload)
    if stale_challenge_id:
        logger.warning('[SOLVER] captcha report ignored; stale challenge id %r does not match the active challenge.', stale_challenge_id)
        self.send_json({'status': 'stale_challenge', 'challenge_id': RUNTIME.recovery.snapshot().challenge_id, 'captcha_solver': _captcha_solver_runtime_status()})
        return
    if _solver_report_predates_auth_completion(payload):
        logger.info('[SOLVER] captcha report ignored; it was created before the same node completed auth.')
        self.send_json({'status': 'stale_auth_report', 'captcha_solver': _captcha_solver_runtime_status()})
        return
    force_reset_suppression = _solver_force_reset_report_suppression(solver_request)
    if force_reset_suppression is not None:
        retry_after = max(0.0, float(force_reset_suppression['grace_seconds']) - float(force_reset_suppression['age_seconds']))
        logger.info('[SOLVER] report_captcha ignored after scoped force reset; scope=%s (%.0fs grace remaining).', force_reset_suppression['scope'], retry_after)
        self.send_json({'status': 'recent_force_reset', 'reason': force_reset_suppression['reason'], 'scope': force_reset_suppression['scope'], 'retry_after_seconds': int(math.ceil(retry_after)), 'captcha_solver': _captcha_solver_runtime_status()})
        return
    auth_report_suppression = _solver_auth_report_suppression(solver_request)
    if auth_report_suppression is not None:
        retry_after = max(0.0, float(auth_report_suppression['grace_seconds']) - float(auth_report_suppression['age_seconds']))
        logger.info('[SOLVER] report_captcha ignored after recent auth; reason=%s captured_since_auth=%s (%.0fs grace remaining).', auth_report_suppression['reason'], auth_report_suppression['captured_since_auth'], retry_after)
        self.send_json({'status': 'recent_auth_complete', 'reason': auth_report_suppression['reason'], 'captured_since_auth': auth_report_suppression['captured_since_auth'], 'retry_after_seconds': int(math.ceil(retry_after)), 'captcha_solver': _captcha_solver_runtime_status()})
        return
    if _payload_flag(payload, 'node_solver_blocked', False):
        self.send_json(_node_solver_blocked_report_payload(payload))
        return
    manual_only = urlparse(self.path).path == '/api/report_manual_captcha' or _payload_manual_only(payload) or _solver_target_requires_manual_only(solver_request)
    if manual_only:
        self.send_json(_manual_only_captcha_report_payload(payload))
        return
    if solver_request:
        _refresh_solver_last_request(solver_request)
    force_retry = _payload_force_solver_retry(payload)
    solver_status = _captcha_solver_runtime_status()
    scope_status = _solver_scope_runtime_status(challenge_scope) if challenge_scope in CHALLENGE_SCOPES else solver_status
    if scope_status.get('manual_required'):
        if force_retry:
            solver_was_running = bool(solver_status.get('running'))
            clear_error = _clear_solver_manual_required_pause(preserve_running_state=solver_was_running, scope=challenge_scope or None)
            if clear_error:
                self.send_error_json(status=500, code='AVM_CAPTCHA_SOLVER_FORCE_RETRY_FAILED', message='清除验证码人工认证锁失败', details={'error': clear_error})
                return
            solver_status = _captcha_solver_runtime_status()
            scope_status = _solver_scope_runtime_status(challenge_scope) if challenge_scope in CHALLENGE_SCOPES else solver_status
            logger.info('[SOLVER] report_captcha force retry cleared manual verification state.')
            if solver_was_running and RUNTIME.solver.snapshot().running:
                self.send_json({'status': 'resuming', 'captcha_solver': solver_status})
                return
        else:
            logger.warning('[SOLVER] report_captcha ignored; manual verification is already required.')
            self.send_json({'status': 'manual_required', 'captcha_solver': solver_status})
            return
    if scope_status.get('manual_required'):
        logger.warning('[SOLVER] report_captcha ignored; manual verification is already required.')
        self.send_json({'status': 'manual_required', 'captcha_solver': solver_status})
        return
    if solver_status.get('queued'):
        logger.info('[SOLVER] report_captcha ignored; solver submission is already queued.')
        self.send_json({'status': 'already_running', 'elapsed_seconds': 0, 'captcha_solver': solver_status})
        return
    execution = RUNTIME.solver.snapshot()
    if execution.running:
        elapsed = max(int(time.time() - (execution.started_at or 0)), 0)
        max_runtime_seconds = _solver_max_runtime_seconds()
        if elapsed < max_runtime_seconds:
            logger.info('[SOLVER] report_captcha ignored; solver already running for %ss.', elapsed)
            self.send_json({'status': 'already_running', 'elapsed_seconds': elapsed, 'captcha_solver': solver_status})
            return
        logger.warning('[SOLVER] report_captcha ignored; solver still running after %ss. Configured limit is %ss; marking manual verification required instead of starting a parallel solver.', elapsed, max_runtime_seconds)
        flag_error = _mark_solver_manual_required(scope=challenge_scope or None)
        response_payload = {'status': 'manual_required', 'elapsed_seconds': elapsed, 'captcha_solver': _captcha_solver_runtime_status()}
        if flag_error:
            response_payload['flag_error'] = flag_error
        self.send_json(response_payload)
        return
    solver_cdp = str(solver_request.get('cdp_endpoint') or '').strip()
    if solver_cdp and _solver_cdp_endpoint_is_remote(solver_cdp):
        node_id = str(solver_request.get('node_id') or '').strip()
        _begin_solver_challenge(solver_request)
        logger.info('[SOLVER] Remote CDP endpoint %s detected (node=%s); deferring to node-local solver. Pausing collection; node solver will clear when solved.', solver_cdp, node_id or 'unknown')
        _set_collection_pause_state(True, 'captcha_solver', scope=challenge_scope or None)
        self.send_json({'status': 'deferred_to_node_solver', 'captcha_solver': _captcha_solver_runtime_status()})
        return
    logger.info('CAPTCHA REPORTED! Triggering Solver...')
    _begin_solver_challenge(solver_request)
    try:
        queued = _submit_solver_request(solver_request)
    except Exception as e:
        self.send_error_json(status=500, code='AVM_CAPTCHA_SOLVER_QUEUE_FAILED', message='验证码求解任务入队失败', details={'error': str(e)})
        return
    if not queued:
        self.send_json({'status': 'already_running', 'elapsed_seconds': 0, 'captcha_solver': _captcha_solver_runtime_status()})
        return
    self.send_json({'status': 'solving'})

def _post_client_log(self):
    (accepted, data) = _read_json_body(self)
    if not accepted:
        return
    msg = str(data.get('msg', ''))[:4000]
    is_error = data.get('isError', False)
    prefix = '[Client Error]' if is_error else '[Client Log]'
    (logger.error if is_error else logger.info)('%s %s', prefix, msg)
    self.send_json({'status': 'ok'})

_UPLOAD_ITEM_ID_PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,128}$')

def _resolve_upload_target(item_id, filename):
    """Return (save_dir, file_path) inside downloads/<item_id>, or None when the request escapes it."""
    if not _UPLOAD_ITEM_ID_PATTERN.fullmatch(str(item_id or '')):
        return None
    base_name = str(filename or '').strip()
    if (not base_name or base_name in ('.', '..')
            or any(character in base_name for character in '/\\:\x00')
            or base_name.endswith(('.', ' '))):
        return None
    downloads_root = Path(DATA_DIR, 'downloads').resolve()
    save_dir = downloads_root / str(item_id)
    file_path = (save_dir / base_name).resolve()
    try:
        save_dir.resolve().relative_to(downloads_root)
        file_path.relative_to(save_dir.resolve())
    except ValueError:
        return None
    return (str(save_dir), str(file_path))

def _post_upload(self):
    try:
        params = parse_qs(urlparse(self.path).query)
        item_id = params.get('id', [''])[0]
        filename = params.get('name', [''])[0]
        try:
            content_length = int(str(self.headers.get('Content-Length') or '0').strip())
        except ValueError:
            content_length = -1
        if content_length <= 0 or self.headers.get('Transfer-Encoding'):
            self.close_connection = True
            self.send_error_json(status=400, code='AVM_INVALID_UPLOAD_REQUEST', message='Invalid upload framing', details={})
            return
        if content_length > UPLOAD_MAX_BYTES:
            self.close_connection = True
            self.send_error_json(status=413, code='AVM_REQUEST_BODY_TOO_LARGE', message='请求体超过大小上限', details={'max_bytes': UPLOAD_MAX_BYTES, 'content_length': content_length})
            return
        target = _resolve_upload_target(item_id, filename) if item_id and filename else None
        if target is None:
            if content_length > 0:
                self.rfile.read(content_length)
            self.send_error_json(status=400, code='AVM_INVALID_UPLOAD_REQUEST', message='上传参数无效', details={'required': ['id', 'name']})
            return
        (save_dir, file_path) = target
        file_data = self.rfile.read(content_length)
        if len(file_data) != content_length:
            self.close_connection = True
            self.send_error_json(status=400, code='AVM_INVALID_UPLOAD_REQUEST', message='Incomplete upload', details={})
            return
        os.makedirs(save_dir, exist_ok=True)
        with open(file_path, 'xb') as f:
            f.write(file_data)
        logger.info('Saved file: %s (%s bytes)', os.path.basename(file_path), content_length)
        self.send_json({'status': 'saved'})
    except FileExistsError:
        self.send_error_json(status=409, code='AVM_UPLOAD_EXISTS', message='Existing archive is preserved', details={})
    except Exception as e:
        logger.exception('Upload failed')
        self.send_error_json(status=500, code='AVM_UPLOAD_FAILED', message='文件上传失败', details={'error': str(e)})

def _post_detail_update_item(self):
    runtime_index = _collection_runtime_index()
    (accepted, data) = _read_json_body(self)
    if not accepted:
        return
    try:
        item_id = str(data.get('id') or '').strip()
        if not item_id:
            self.send_error_json(status=400, code='AVM_INVALID_ID', message='id is required')
            return
        force_status = 'failed_timeout' if data.get('status') == 'failed_timeout' else None
        result = _detail_collection_service().apply_working_item_patch(item_id=item_id, patch_data=data, event_type='update_item', get_working_item=_get_working_item, apply_flat_override_patch=_apply_flat_override_patch, reset_structured_sections_for_resync=_reset_structured_sections_for_resync, update_file_global=update_file_global, persist_item_to_db=persist_item_to_db, evict_runtime_item=_evict_runtime_item, prefer_db_task_reads=_prefer_db_task_reads, pending_tasks=runtime_index.pending_tasks, remove_pending=runtime_index.remove_pending, force_status=force_status)
        if result['status'] == 'ok':
            if force_status == 'failed_timeout':
                logger.info('Item %s TIMED OUT.', item_id)
            self.send_json({'status': 'updated'})
        elif result['status'] == 'id_not_found':
            self.send_error_json(status=404, code='AVM_DETAIL_ITEM_NOT_FOUND', message='Item not found', details={'id': item_id})
        else:
            self.send_error_json(status=500, code='AVM_DETAIL_UPDATE_ITEM_FAILED', message='Unexpected update result')
    except Exception as e:
        self.send_error_json(status=500, code='AVM_DETAIL_UPDATE_ITEM_FAILED', message='条目更新失败', details={'error': str(e)})

def _post_detail_next_visit(self):
    runtime_index = _collection_runtime_index()
    accepted, _payload = _read_json_body(self)
    if not accepted:
        return
    legacy_entries = None
    if not _prefer_db_task_reads():
        with runtime_index.lock:
            legacy_entries = list(runtime_index.seen_ids.items())
    try:
        result = _detail_collection_service().next_visit_task(
            dispatched_tasks=runtime_index.dispatched_tasks,
            cooldown_seconds=DISPATCH_COOLDOWN_SECONDS,
            legacy_entries=legacy_entries,
            dispatch_lock=runtime_index.lock,
        )
    except Exception as e:
        self.send_error_json(status=500, code='AVM_NEXT_VISIT_TASK_FAILED', message='下一条访问任务分发失败', details={'error': str(e)})
        return
    self.send_json(result)

def _post_detail_html(self):
    runtime_index = _collection_runtime_index()
    (accepted, data) = _read_json_body(self, max_bytes=REQUEST_BODY_HTML_MAX_BYTES)
    if not accepted:
        return
    try:
        item_id = str(data.get('id') or '').strip()
        if not item_id:
            self.send_error_json(status=400, code='AVM_INVALID_ID', message='id is required')
            return
        html_content = data.get('html', '')
        status = data.get('status')
        result = _detail_collection_service().submit_html(item_id=item_id, html_content=html_content, status=status, get_working_item=_get_working_item, apply_flat_override_patch=_apply_flat_override_patch, reset_structured_sections_for_resync=_reset_structured_sections_for_resync, update_file_global=update_file_global, persist_item_to_db=persist_item_to_db, evict_runtime_item=_evict_runtime_item, submit_task=submit_task, prefer_db_task_reads=_prefer_db_task_reads, pending_tasks=runtime_index.pending_tasks, remove_pending=runtime_index.remove_pending)
        if result.get('status') == 'id_not_found':
            self.send_error_json(status=404, code='AVM_DETAIL_ITEM_NOT_FOUND', message='Item not found', details={'id': item_id})
            return
        self.send_json(result)
    except Exception as e:
        logger.exception('Error saving HTML content')
        self.send_error_json(status=500, code='AVM_DETAIL_ANALYZE_HTML_FAILED', message='HTML 分析结果提交失败', details={'error': str(e)})

def _server_post_fallback(self):
    request_path = urlparse(self.path).path
    if request_path.startswith('/api/'):
        _send_guard_error(self, {
            'status': 404, 'code': 'AVM_ENDPOINT_NOT_FOUND',
            'message': '未找到接口', 'details': {'path': request_path},
        })
    else:
        self.send_response(404)
        self.end_headers()

__all__ = ["_UPLOAD_ITEM_ID_PATTERN", "_resolve_upload_target", "_run_analysis_screen", "_post_analysis_screen", "_post_captcha_report", "_post_client_log", "_post_upload", "_post_detail_update_item", "_post_detail_next_visit", "_post_detail_html", "_server_post_fallback"]
