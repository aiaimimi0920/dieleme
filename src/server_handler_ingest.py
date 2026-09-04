from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def _server_post_branch_23(self):
    global PAUSED, LAST_REQUEST_TIME
    content_length = int(self.headers.get('Content-Length', 0))
    post_data = self.rfile.read(content_length) if content_length > 0 else b'{}'
    try:
        payload = json.loads(post_data.decode('utf-8')) if post_data else {}
    except Exception:
        self.send_error_json(status=400, code='AVM_INVALID_JSON', message='请求体不是合法 JSON', details={})
        return
    if not isinstance(payload, dict):
        self.send_error_json(status=400, code='AVM_INVALID_REQUEST_BODY', message='请求体必须是 JSON 对象', details={'expected_type': 'object', 'received_type': _json_payload_type_name(payload)})
        return
    items = payload.get('items', [])
    if not isinstance(items, list):
        self.send_error_json(status=400, code='AVM_INVALID_SCREEN_ITEMS', message='items 必须为数组', details={'invalid_fields': ['items']})
        return
    threshold = payload.get('margin_threshold')
    try:
        if threshold is None:
            threshold = get_effective_alert_threshold(DEFAULT_MARGIN_THRESHOLD)
        else:
            threshold = float(threshold)
    except Exception:
        threshold = get_effective_alert_threshold(DEFAULT_MARGIN_THRESHOLD)
    try:
        results = []
        for raw in items:
            if isinstance(raw, dict):
                item_id = str(raw.get('id', '')).strip()
            else:
                item_id = str(raw).strip()
            if not item_id:
                continue
            with DATA_LOCK:
                entry = SEEN_IDS.get(item_id)
            if entry is None and DB_REPOSITORY.enabled:
                try:
                    db_item = DB_REPOSITORY.get_flat_item(item_id)
                except Exception as db_screen_error:
                    print(f'[DB] screen item lookup failed item={item_id}: {db_screen_error}')
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
        now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        for result in results:
            if result['meets_alert_threshold']:
                alert = dict(result)
                alert['created_at'] = now
                alert['margin_threshold'] = threshold
                alerts.append(alert)
        write_avm_alerts(alerts)
        summary = summarize_screen_results(results)
        self.send_json({'model_version': AVM_SERVICE.model_version(), 'margin_formula': '(predicted_price - starting_price) / predicted_price', 'margin_threshold': threshold, 'total': len(results), 'alerts_written': len(alerts), 'summary': summary, 'results': results})
    except Exception as e:
        self.send_error_json(status=500, code='AVM_SCREEN_FAILED', message='批量筛选执行失败', details={'error': str(e)})

def _server_post_branch_24(self):
    global PAUSED, LAST_REQUEST_TIME
    content_length = int(self.headers['Content-Length']) if self.headers.get('Content-Length') else 0
    try:
        payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
    except Exception:
        self.send_error_json(status=400, code='AVM_INVALID_JSON', message='请求体不是合法 JSON', details={})
        return
    if not isinstance(payload, dict):
        self.send_invalid_request_body(payload)
        return
    solver_request = _build_solver_request(payload)
    challenge_scope = _challenge_scope_for_request(solver_request)
    stale_challenge_id = _solver_report_stale_challenge_id(payload)
    if stale_challenge_id:
        print(f'[SOLVER] captcha report ignored; stale challenge id {stale_challenge_id!r} does not match the active challenge.')
        self.send_json({'status': 'stale_challenge', 'challenge_id': SOLVER_CHALLENGE_ID, 'captcha_solver': _captcha_solver_runtime_status()})
        return
    if _solver_report_predates_auth_completion(payload):
        print('[SOLVER] captcha report ignored; it was created before the same node completed auth.')
        self.send_json({'status': 'stale_auth_report', 'captcha_solver': _captcha_solver_runtime_status()})
        return
    force_reset_suppression = _solver_force_reset_report_suppression(solver_request)
    if force_reset_suppression is not None:
        retry_after = max(0.0, float(force_reset_suppression['grace_seconds']) - float(force_reset_suppression['age_seconds']))
        print(f"[SOLVER] report_captcha ignored after scoped force reset; scope={force_reset_suppression['scope']} ({retry_after:.0f}s grace remaining).")
        self.send_json({'status': 'recent_force_reset', 'reason': force_reset_suppression['reason'], 'scope': force_reset_suppression['scope'], 'retry_after_seconds': int(math.ceil(retry_after)), 'captcha_solver': _captcha_solver_runtime_status()})
        return
    auth_report_suppression = _solver_auth_report_suppression(solver_request)
    if auth_report_suppression is not None:
        retry_after = max(0.0, float(auth_report_suppression['grace_seconds']) - float(auth_report_suppression['age_seconds']))
        print(f"[SOLVER] report_captcha ignored after recent auth; reason={auth_report_suppression['reason']} captured_since_auth={auth_report_suppression['captured_since_auth']} ({retry_after:.0f}s grace remaining).")
        self.send_json({'status': 'recent_auth_complete', 'reason': auth_report_suppression['reason'], 'captured_since_auth': auth_report_suppression['captured_since_auth'], 'retry_after_seconds': int(math.ceil(retry_after)), 'captcha_solver': _captcha_solver_runtime_status()})
        return
    if _payload_flag(payload, 'node_solver_blocked', False):
        self.send_json(_node_solver_blocked_report_payload(payload))
        return
    manual_only = self.path == '/api/report_manual_captcha' or _payload_manual_only(payload) or _solver_target_requires_manual_only(solver_request)
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
            print('[SOLVER] report_captcha force retry cleared manual verification state.')
            if solver_was_running and SOLVER_RUNNING:
                self.send_json({'status': 'resuming', 'captcha_solver': solver_status})
                return
        else:
            print('[SOLVER] report_captcha ignored; manual verification is already required.')
            self.send_json({'status': 'manual_required', 'captcha_solver': solver_status})
            return
    if scope_status.get('manual_required'):
        print('[SOLVER] report_captcha ignored; manual verification is already required.')
        self.send_json({'status': 'manual_required', 'captcha_solver': solver_status})
        return
    if solver_status.get('queued'):
        print('[SOLVER] report_captcha ignored; solver submission is already queued.')
        self.send_json({'status': 'already_running', 'elapsed_seconds': 0, 'captcha_solver': solver_status})
        return
    if SOLVER_RUNNING:
        elapsed = max(int(time.time() - SOLVER_START_TIME), 0)
        max_runtime_seconds = _solver_max_runtime_seconds()
        if elapsed < max_runtime_seconds:
            print(f'[SOLVER] report_captcha ignored; solver already running for {elapsed}s.')
            self.send_json({'status': 'already_running', 'elapsed_seconds': elapsed, 'captcha_solver': solver_status})
            return
        print(f'[SOLVER] report_captcha ignored; solver still running after {elapsed}s. Configured limit is {max_runtime_seconds}s; marking manual verification required instead of starting a parallel solver.')
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
        print(f"[SOLVER] Remote CDP endpoint {solver_cdp} detected (node={node_id or 'unknown'}); deferring to node-local solver. Pausing collection; node solver will clear when solved.")
        _set_collection_pause_state(True, 'captcha_solver', scope=challenge_scope or None)
        self.send_json({'status': 'deferred_to_node_solver', 'captcha_solver': _captcha_solver_runtime_status()})
        return
    print('CAPTCHA REPORTED! Triggering Solver...')
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

def _server_post_branch_25(self):
    global PAUSED, LAST_REQUEST_TIME
    content_length = int(self.headers['Content-Length'])
    post_data = self.rfile.read(content_length)
    try:
        data = json.loads(post_data.decode('utf-8'))
        if not isinstance(data, dict):
            self.send_invalid_request_body(data)
            return
        msg = data.get('msg', '')
        is_error = data.get('isError', False)
        prefix = '[Client Error]' if is_error else '[Client Log]'
        print(f'{prefix} {msg}')
        self.send_json({'status': 'ok'})
    except Exception:
        self.send_error_json(status=400, code='AVM_INVALID_JSON', message='请求体不是合法 JSON', details={})

def _server_post_branch_26(self):
    global PAUSED, LAST_REQUEST_TIME
    try:
        query = urlparse(self.path).query
        params = parse_qs(query)
        item_id = params.get('id', [''])[0]
        filename = params.get('name', [''])[0]
        content_length = int(self.headers['Content-Length']) if self.headers.get('Content-Length') else 0
        if not item_id or not filename:
            if content_length > 0:
                self.rfile.read(content_length)
            self.send_error_json(status=400, code='AVM_INVALID_UPLOAD_REQUEST', message='缺少上传参数', details={'required': ['id', 'name']})
            return
        filename = unquote(filename)
        filename = filename.replace('\\', '')
        save_dir = os.path.join(DATA_DIR, 'downloads', item_id)
        os.makedirs(save_dir, exist_ok=True)
        file_path = os.path.join(save_dir, filename)
        file_data = self.rfile.read(content_length)
        with open(file_path, 'wb') as f:
            f.write(file_data)
        print(f'Saved file: {filename} ({content_length} bytes)')
        self.send_json({'status': 'saved'})
    except Exception as e:
        print(f'Upload failed: {e}')
        self.send_error_json(status=500, code='AVM_UPLOAD_FAILED', message='文件上传失败', details={'error': str(e)})

def _server_post_branch_27(self):
    global PAUSED, LAST_REQUEST_TIME
    content_length = int(self.headers['Content-Length'])
    post_data = self.rfile.read(content_length)
    try:
        data = json.loads(post_data.decode('utf-8'))
    except Exception:
        self.send_error_json(status=400, code='AVM_INVALID_JSON', message='请求体不是合法 JSON', details={})
        return
    if not isinstance(data, dict):
        self.send_invalid_request_body(data)
        return
    try:
        item_id = str(data.get('id'))
        force_status = 'failed_timeout' if data.get('status') == 'failed_timeout' else None
        result = _detail_collection_service().apply_working_item_patch(item_id=item_id, patch_data=data, event_type='update_item', get_working_item=_get_working_item, apply_flat_override_patch=_apply_flat_override_patch, reset_structured_sections_for_resync=_reset_structured_sections_for_resync, update_file_global=update_file_global, persist_item_to_db=persist_item_to_db, evict_runtime_item=_evict_runtime_item, prefer_db_task_reads=_prefer_db_task_reads, pending_tasks=PENDING_TASKS, force_status=force_status)
        if result['status'] == 'ok':
            if force_status == 'failed_timeout':
                print(f'Item {item_id} TIMED OUT.')
            self.send_json({'status': 'updated'})
        else:
            self.send_json({'status': 'id_not_found'})
    except Exception as e:
        self.send_error_json(status=500, code='AVM_DETAIL_UPDATE_ITEM_FAILED', message='条目更新失败', details={'error': str(e)})

def _server_post_branch_28(self):
    global PAUSED, LAST_REQUEST_TIME
    legacy_entries = None if _prefer_db_task_reads() else list(SEEN_IDS.items())
    try:
        result = _detail_collection_service().next_visit_task(dispatched_tasks=DISPATCHED_TASKS, cooldown_seconds=DISPATCH_COOLDOWN_SECONDS, legacy_entries=legacy_entries)
    except Exception as e:
        self.send_error_json(status=500, code='AVM_NEXT_VISIT_TASK_FAILED', message='下一条访问任务分发失败', details={'error': str(e)})
        return
    self.send_json(result)

def _server_post_branch_29(self):
    global PAUSED, LAST_REQUEST_TIME
    content_length = int(self.headers['Content-Length'])
    post_data = self.rfile.read(content_length)
    try:
        data = json.loads(post_data.decode('utf-8'))
    except Exception:
        self.send_error_json(status=400, code='AVM_INVALID_JSON', message='请求体不是合法 JSON', details={})
        return
    if not isinstance(data, dict):
        self.send_invalid_request_body(data)
        return
    try:
        item_id = str(data.get('id'))
        html_content = data.get('html', '')
        status = data.get('status')
        result = _detail_collection_service().submit_html(item_id=item_id, html_content=html_content, status=status, get_working_item=_get_working_item, apply_flat_override_patch=_apply_flat_override_patch, reset_structured_sections_for_resync=_reset_structured_sections_for_resync, update_file_global=update_file_global, persist_item_to_db=persist_item_to_db, evict_runtime_item=_evict_runtime_item, submit_task=submit_task, prefer_db_task_reads=_prefer_db_task_reads, pending_tasks=PENDING_TASKS)
        self.send_json(result)
    except Exception as e:
        print(f'Error saving HTML content: {e}')
        self.send_error_json(status=500, code='AVM_DETAIL_ANALYZE_HTML_FAILED', message='HTML 分析结果提交失败', details={'error': str(e)})

def _server_post_fallback(self):
    global PAUSED, LAST_REQUEST_TIME
    request_path = urlparse(self.path).path
    if request_path.startswith('/api/'):
        self.send_error_json(status=404, code='AVM_ENDPOINT_NOT_FOUND', message='未找到接口', details={'path': request_path})
    else:
        self.send_response(404)
        self.end_headers()

__all__ = ["_server_post_branch_23", "_server_post_branch_24", "_server_post_branch_25", "_server_post_branch_26", "_server_post_branch_27", "_server_post_branch_28", "_server_post_branch_29", "_server_post_fallback"]
