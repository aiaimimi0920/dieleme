from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def _server_get_branch_23(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    parsed_url = urlparse(self.path)
    params = parse_qs(parsed_url.query)
    try:
        window_days = int(params.get('window_days', ['7'])[0] or '7')
    except ValueError:
        window_days = 7
    if window_days < 0:
        window_days = 7
    try:
        limit = int(params.get('limit', ['100'])[0] or '100')
    except ValueError:
        limit = 100
    if limit < 0:
        limit = 0
    dry_run = str(params.get('dry_run', ['true'])[0] or 'true').lower() not in {'0', 'false', 'no'}
    active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
    active_avm_dir = active_data_root / 'avm'
    try:
        output = _detail_collection_service(active_data_root).prepare_replay(window_days=window_days, limit=limit, dry_run=dry_run)
        (active_avm_dir / 'recent_detail_replay.json').parent.mkdir(parents=True, exist_ok=True)
        (active_avm_dir / 'recent_detail_replay.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
        if not dry_run and output.get('prepared_count'):
            load_data(active_data_root)
    except Exception as e:
        self.send_error_json(status=500, code='AVM_RECENT_DETAIL_REPLAY_FAILED', message='recent detail replay 准备失败', details={'error': str(e)})
        return
    self.send_json(output)

def _server_get_branch_24(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    parsed_url = urlparse(self.path)
    params = parse_qs(parsed_url.query)
    try:
        limit = int(params.get('limit', ['20'])[0] or '20')
    except ValueError:
        limit = 20
    if limit < 0:
        limit = 0
    try:
        timeout = int(params.get('timeout', ['15'])[0] or '15')
    except ValueError:
        timeout = 15
    if timeout < 0:
        timeout = 15
    extract_risk = str(params.get('extract_risk', ['false'])[0] or 'false').lower() not in {'0', 'false', 'no'}
    dry_run = str(params.get('dry_run', ['true'])[0] or 'true').lower() not in {'0', 'false', 'no'}
    active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
    active_avm_dir = active_data_root / 'avm'
    try:
        output = _detail_collection_service(active_data_root).fetch_missing_archives(limit=limit, timeout=timeout, extract_risk=extract_risk, dry_run=dry_run)
        (active_avm_dir / 'fetch_missing_detail_archives.json').parent.mkdir(parents=True, exist_ok=True)
        (active_avm_dir / 'fetch_missing_detail_archives.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
        if not dry_run and output.get('fetched_count'):
            load_data(active_data_root)
    except Exception as e:
        self.send_error_json(status=500, code='AVM_FETCH_MISSING_DETAIL_ARCHIVES_FAILED', message='缺失详情归档抓取失败', details={'error': str(e)})
        return
    self.send_json(output)

def _server_get_branch_25(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    parsed_url = urlparse(self.path)
    params = parse_qs(parsed_url.query)
    try:
        window_days = int(params.get('window_days', ['30'])[0] or '30')
    except ValueError:
        window_days = 30
    if window_days < 0:
        window_days = 30
    try:
        limit = int(params.get('limit', ['500'])[0] or '500')
    except ValueError:
        limit = 500
    if limit < 0:
        limit = 0
    dry_run = str(params.get('dry_run', ['true'])[0] or 'true').lower() not in {'0', 'false', 'no'}
    active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
    active_avm_dir = active_data_root / 'avm'
    try:
        output = _detail_collection_service(active_data_root).prepare_replay(window_days=window_days, limit=limit, dry_run=dry_run)
        (active_avm_dir / 'archive_detail_replay.json').parent.mkdir(parents=True, exist_ok=True)
        (active_avm_dir / 'archive_detail_replay.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
        if not dry_run and output.get('prepared_count'):
            load_data(active_data_root)
    except Exception as e:
        self.send_error_json(status=500, code='AVM_ARCHIVE_DETAIL_REPLAY_FAILED', message='archive detail replay 准备失败', details={'error': str(e)})
        return
    self.send_json(output)

def _server_get_branch_26(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    try:
        self.send_json(AVM_PIPELINE.status())
    except Exception as e:
        self.send_error_json(status=500, code='AVM_PIPELINE_STATUS_FAILED', message='pipeline 状态查询失败', details={'error': str(e)})

def _server_get_branch_27(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    try:
        self.send_json(AVM_PIPELINE.verify_merge_completeness())
    except Exception as e:
        self.send_error_json(status=500, code='AVM_MERGE_CHECK_FAILED', message='merge completeness 校验失败', details={'error': str(e)})

def _server_get_branch_28(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    query = urlparse(self.path).query
    params = parse_qs(query)
    item_id = params.get('id', [''])[0]
    if item_id and DB_REPOSITORY.enabled:
        try:
            db_item = DB_REPOSITORY.get_flat_item(item_id)
            if db_item:
                self.send_json(db_item)
                return
        except Exception as db_get_error:
            print(f'[DB] /api/get_item DB lookup failed for {item_id}: {db_get_error}')
    if item_id and item_id in SEEN_IDS:
        self.send_json(SEEN_IDS[item_id]['data'])
    else:
        self.send_json({})

def _server_get_branch_29(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    parsed_url = urlparse(self.path)
    params = parse_qs(parsed_url.query)
    session_id = params.get('session_id', ['default'])[0]
    try:
        self.send_json(_seed_collection_service().next_task(session_id, paused=_collection_scope_effectively_paused('seed')))
    except Exception as e:
        self.send_error_json(status=500, code='AVM_SEED_NEXT_TASK_FAILED', message='种子任务分发失败', details={'error': str(e)})

def _server_get_branch_30(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    if _collection_scope_effectively_paused('detail'):
        self.send_json({'tasks': []})
        return
    batch_size = 300
    if _prefer_db_task_reads():
        try:
            result = _detail_collection_service().batch_tasks(dispatched_tasks=DISPATCHED_TASKS, cooldown_seconds=DISPATCH_COOLDOWN_SECONDS, batch_size=batch_size)
        except Exception as e:
            self.send_error_json(status=500, code='AVM_DETAIL_BATCH_TASKS_FAILED', message='详情批量任务分发失败', details={'error': str(e)})
            return
        self.send_json({'tasks': result['tasks'], 'total': result['total'], 'done': result['done']})
        if len(result['tasks']) > 0:
            print(f"Dispatched {len(result['tasks'])} tasks (Batch Limit: {batch_size}). Pending: {result['pending']}")
        else:
            print(f'[DEBUG] Returned 0 tasks. Candidates=0')
        return
    else:
        tasks = []
        now = datetime.datetime.now()
        active_pending = []
        for tid in list(PENDING_TASKS):
            if tid in SEEN_IDS:
                item = SEEN_IDS[tid].get('data')
                if item and item.get('is_processed'):
                    continue
            active_pending.append(tid)
        PENDING_TASKS[:] = active_pending
        pending_count = len(PENDING_TASKS)
        total_count = len(SEEN_IDS)
        done_count = total_count - pending_count
        print(f'[DEBUG] /get_tasks: PENDING={pending_count}, TOTAL={total_count}, DONE={done_count}')
        candidates = []
        skipped_cooldown = 0
        for tid in PENDING_TASKS:
            last_time = DISPATCHED_TASKS.get(tid)
            if last_time:
                if (now - last_time).total_seconds() < DISPATCH_COOLDOWN_SECONDS:
                    skipped_cooldown += 1
                    continue
            candidates.append(tid)
    print(f'[DEBUG] Candidates after cooldown filter: {len(candidates)} (Skipped {skipped_cooldown} due to cooldown)')
    for candidate in candidates[:batch_size]:
        if _prefer_db_task_reads():
            item_id = candidate['id']
            tasks.append({'id': item_id, 'url': candidate.get('url')})
            DISPATCHED_TASKS[item_id] = now
        else:
            item_id = candidate
            if item_id in SEEN_IDS:
                item = SEEN_IDS[item_id]['data']
                if item.get('is_processed'):
                    continue
                tasks.append({'id': item_id, 'url': item.get('url')})
                DISPATCHED_TASKS[item_id] = now
    self.send_json({'tasks': tasks, 'total': total_count, 'done': done_count})
    if len(tasks) > 0:
        print(f'Dispatched {len(tasks)} tasks (Batch Limit: {batch_size}). Pending: {pending_count}')
    else:
        print(f'[DEBUG] Returned 0 tasks. Candidates={len(candidates)}')

def _server_get_branch_31(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    _set_collection_pause_state(False)
    _clear_solver_running_state()
    _clear_solver_manual_required_state()
    flag_path = _solver_force_unlock_flag_path()
    if os.path.exists(flag_path):
        try:
            os.remove(flag_path)
        except:
            pass
    challenge_state_error = _clear_solver_challenge_state()
    if challenge_state_error:
        print(f'[SOLVER] Failed to clear persisted challenge state on API resume: {challenge_state_error}')
    print('System RESUMED (via API).')
    self.send_json({'status': 'resumed'})

def _server_get_branch_32(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    self.send_error_json(status=404, code='AVM_ENDPOINT_NOT_FOUND', message='未找到接口', details={'path': request_path})

def _server_get_fallback(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    self.send_response(404)
    self.end_headers()

def _server_post_branch_01(self):
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
        url = data.get('url')
        has_next = data.get('has_next', True)
        is_empty = data.get('is_empty', False)
        page_num = data.get('page_num', 1)
        total_pages = data.get('total_pages')
        zero_bid_detected = data.get('zero_bid_detected', False)
        log_msg = f'[SNIFF REPORT] Page {page_num} | Next: {has_next} | Empty: {is_empty} | TotalPages: {total_pages}'
        if zero_bid_detected:
            log_msg += ' | [ZERO-BID EARLY TERMINATION]'
        print(log_msg + f' | URL: {url}')
        if url:
            self.send_json(_seed_collection_service().report_progress(data))
        else:
            self.send_error_json(status=400, code='AVM_SEED_PROGRESS_MISSING_URL', message='缺少 URL', details={'required': ['url']})
    except Exception as e:
        print(f'Error in report_sniff_status: {e}')
        self.send_error_json(status=500, code='AVM_SEED_PROGRESS_FAILED', message='种子进度回报失败', details={'error': str(e)})

def _server_post_branch_02(self):
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

def _server_post_branch_03(self):
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

def _server_post_branch_04(self):
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

def _server_post_branch_05(self):
    global PAUSED, LAST_REQUEST_TIME
    action = 'pause' if self.path.endswith('/pause') else 'resume'
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

def _server_post_branch_06(self):
    global PAUSED, LAST_REQUEST_TIME
    (authorized, auth_error) = _nas_auth_recovery_authorized(self.headers)
    if not authorized:
        self.send_error_json(status=403, code='COLLECTION_AUTH_RECOVERY_FORBIDDEN', message='跨设备认证恢复凭据无效', details={'error': auth_error})
        return
    content_length = int(self.headers.get('Content-Length') or 0)
    try:
        payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
    except Exception:
        self.send_error_json(status=400, code='AVM_INVALID_JSON', message='请求体不是合法 JSON', details={})
        return
    if not isinstance(payload, dict):
        self.send_invalid_request_body(payload)
        return
    recovery_id = str(payload.get('recovery_id') or '').strip()
    if not recovery_id:
        result = {'ok': False, 'error': 'recovery_id is required'}
    elif self.path.endswith('/claim'):
        role = str(payload.get('role') or '').strip().lower()
        node_id = str(payload.get('node_id') or '').strip().lower()
        if (role, node_id) not in {('pc1', 'pc1'), ('pc2', 'pc2')}:
            result = {'ok': False, 'error': 'role and node_id must identify pc1 or pc2'}
        else:
            result = NAS_AUTH_RECOVERY.claim(role, recovery_id, node_id)
    elif self.path.endswith('/snapshot_ready'):
        try:
            result = NAS_AUTH_RECOVERY.snapshot_ready(recovery_id, sha256=str(payload.get('sha256') or ''), cookie_count=int(payload.get('cookie_count') or 0), created_at_epoch=float(payload.get('created_at_epoch') or time.time()))
        except (TypeError, ValueError) as error:
            result = {'ok': False, 'error': str(error)}
    elif self.path.endswith('/pc2_restarting'):
        result = NAS_AUTH_RECOVERY.pc2_restarting(recovery_id)
    else:
        result = _nas_auth_recovery_result(payload)
    if not result.get('ok'):
        self.send_error_json(status=409 if result.get('stale_recovery') else 400, code='COLLECTION_AUTH_RECOVERY_REJECTED', message='跨设备认证恢复请求被拒绝', details=result)
        return
    self.send_json(result)

def _server_post_branch_07(self):
    global PAUSED, LAST_REQUEST_TIME
    content_length = int(self.headers.get('Content-Length') or 0)
    try:
        payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
    except Exception:
        self.send_error_json(status=400, code='AVM_INVALID_JSON', message='请求体不是合法 JSON', details={})
        return
    if not isinstance(payload, dict):
        self.send_invalid_request_body(payload)
        return
    result = _force_reset_solver_scope(payload.get('scope'), payload.get('challenge_id'))
    status = 200 if result.get('ok') or result.get('stale_challenge') else 409
    if status != 200:
        self.send_error_json(status=status, code='COLLECTION_CHALLENGE_FORCE_RESET_REJECTED', message='验证码尚未达到保底重置时间或状态不匹配', details=result)
        return
    self.send_json(result)

def _server_post_branch_08(self):
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

def _server_post_branch_09(self):
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

__all__ = ["_server_get_branch_23", "_server_get_branch_24", "_server_get_branch_25", "_server_get_branch_26", "_server_get_branch_27", "_server_get_branch_28", "_server_get_branch_29", "_server_get_branch_30", "_server_get_branch_31", "_server_get_branch_32", "_server_get_fallback", "_server_post_branch_01", "_server_post_branch_02", "_server_post_branch_03", "_server_post_branch_04", "_server_post_branch_05", "_server_post_branch_06", "_server_post_branch_07", "_server_post_branch_08", "_server_post_branch_09"]
