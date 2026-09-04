from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def _server_get_branch_01(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    body = _collection_observer_page_html().encode('utf-8')
    self.send_response(200)
    self.send_header('Content-Type', 'text/html; charset=utf-8')
    self.send_header('Content-Length', str(len(body)))
    self.end_headers()
    self.wfile.write(body)

def _server_get_branch_02(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    asset = _collection_observer_static_asset(request_path)
    if asset is None:
        self.send_error_json(status=404, code='COLLECTION_STATIC_ASSET_NOT_FOUND', message='collection console 静态资源不存在', details={'path': request_path})
        return
    (body, content_type) = asset
    self.send_response(200)
    self.send_header('Content-Type', content_type)
    self.send_header('Content-Length', str(len(body)))
    self.end_headers()
    self.wfile.write(body)

def _server_get_branch_03(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    try:
        self.send_json(_collection_observer_overview_payload())
    except Exception as e:
        self.send_error_json(status=500, code='COLLECTION_OBSERVER_OVERVIEW_FAILED', message='collection observer overview 读取失败', details={'error': str(e)})

def _server_get_branch_04(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    try:
        self.send_json(_collection_observer_items_payload(query))
    except Exception as e:
        self.send_error_json(status=500, code='COLLECTION_OBSERVER_ITEMS_FAILED', message='collection observer item 列表读取失败', details={'error': str(e)})

def _server_get_branch_05(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    try:
        self.send_json(_collection_observer_regions_payload(query))
    except Exception as e:
        self.send_error_json(status=500, code='COLLECTION_OBSERVER_REGIONS_FAILED', message='collection observer 地区状态读取失败', details={'error': str(e)})

def _server_get_branch_06(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    try:
        if request_path.startswith('/api/collection/items/'):
            query = dict(query)
            query['item_id'] = [unquote(request_path.rsplit('/', 1)[-1])]
        self.send_json(_collection_observer_item_payload(query))
    except Exception as e:
        self.send_error_json(status=500, code='COLLECTION_OBSERVER_ITEM_FAILED', message='collection observer item 详情读取失败', details={'error': str(e)})

def _server_get_branch_07(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    try:
        active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
        payload = list_manual_review_receipts(_manual_review_receipt_store_path(active_data_root), repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None)
        control_plane_runtime = _manual_review_control_plane_runtime_summary(active_data_root)
        self.send_json({'receipt_count': len(payload.get('receipts') or []), 'receipts': list(payload.get('receipts') or []), **control_plane_runtime})
    except Exception as e:
        self.send_error_json(status=500, code='AVM_MANUAL_REVIEW_RECEIPTS_READ_FAILED', message='manual review receipts 读取失败', details={'error': str(e)})

def _server_get_branch_08(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    try:
        active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
        manager = _get_manual_review_maintenance_manager(active_data_root)
        snapshot = manager.snapshot()
        jobs = list(snapshot.get('jobs') or [])
        running_job = next((dict(job) for job in jobs if job.get('job_id') == snapshot.get('running_job_id')), None)
        queued_jobs = [dict(job) for job in jobs if job.get('status') == 'queued']
        control_plane_runtime = _manual_review_control_plane_runtime_summary(active_data_root)
        job_id = str((query.get('job_id') or [None])[0] or '').strip()
        if job_id:
            job = manager.get_job(job_id)
            self.send_json({'job_count': len(jobs), 'job': job, 'running_job': running_job, 'queued_jobs': queued_jobs, 'manual_review_receipt_summary': _manual_review_receipt_context(active_data_root)['manual_review_receipt_summary'], 'operator_overview': _manual_review_receipt_context(active_data_root)['operator_overview'], **control_plane_runtime})
        else:
            self.send_json({'job_count': len(jobs), 'jobs': jobs, 'running_job': running_job, 'queued_jobs': queued_jobs, **control_plane_runtime})
    except Exception as e:
        self.send_error_json(status=500, code='AVM_MANUAL_REVIEW_RECEIPT_JOBS_READ_FAILED', message='manual review receipt jobs 读取失败', details={'error': str(e)})

def _server_get_branch_09(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    try:
        active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
        action = str((query.get('action') or [None])[0] or '').strip() or None
        ready_signal = str((query.get('ready_signal') or [None])[0] or '').strip() or None
        try:
            limit = int((query.get('limit') or [50])[0] or 50)
        except (TypeError, ValueError):
            limit = 50
        if limit < 0:
            limit = 0
        operations = filter_manual_review_receipt_operations(load_manual_review_receipt_operations(_manual_review_receipt_operations_path(active_data_root), repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None), action=action, ready_signal=ready_signal, limit=limit)
        operations = list(reversed(operations))
        control_plane_runtime = _manual_review_control_plane_runtime_summary(active_data_root)
        self.send_json({'operation_count': len(operations), 'operations': operations, 'applied_filters': {'action': action, 'ready_signal': ready_signal, 'limit': limit}, **control_plane_runtime})
    except Exception as e:
        self.send_error_json(status=500, code='AVM_MANUAL_REVIEW_RECEIPT_OPERATIONS_READ_FAILED', message='manual review receipt operations 读取失败', details={'error': str(e)})

def _server_get_branch_10(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    try:
        active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
        context = _manual_review_receipt_context(active_data_root)
        self.send_json({'manual_review_receipt_summary': context['manual_review_receipt_summary'], 'manual_review_receipt_jobs_summary': context['manual_review_receipt_jobs_summary'], 'manual_review_receipt_operations_summary': context['manual_review_receipt_operations_summary'], 'manual_review_control_plane_storage': context['manual_review_control_plane_storage'], 'manual_review_control_plane_backup': context['manual_review_control_plane_backup'], 'manual_review_control_plane_backup_repairs_summary': context['manual_review_control_plane_backup_repairs_summary'], 'manual_review_control_plane_integrity': context['manual_review_control_plane_integrity'], 'manual_review_control_plane_integrity_history_summary': context['manual_review_control_plane_integrity_history_summary'], 'manual_review_control_plane_stability': context['manual_review_control_plane_stability'], 'manual_review_control_plane_guidance': context['manual_review_control_plane_guidance']})
    except Exception as e:
        self.send_error_json(status=500, code='AVM_MANUAL_REVIEW_CONTROL_PLANE_STATUS_FAILED', message='manual review control plane 状态读取失败', details={'error': str(e)})

def _server_get_branch_11(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    try:
        active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
        try:
            limit = int((query.get('limit') or [50])[0] or 50)
        except (TypeError, ValueError):
            limit = 50
        if limit < 0:
            limit = 0
        repairs = load_manual_review_control_plane_backup_repairs(active_data_root)
        if limit >= 0:
            repairs = [] if limit == 0 else repairs[-limit:]
        repairs = list(reversed(repairs))
        control_plane_runtime = _manual_review_control_plane_runtime_summary(active_data_root)
        self.send_json({'repair_count': len(repairs), 'repairs': repairs, 'applied_filters': {'limit': limit}, **control_plane_runtime})
    except Exception as e:
        self.send_error_json(status=500, code='AVM_MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIRS_FAILED', message='manual review control plane backup repairs 读取失败', details={'error': str(e)})

def _server_get_branch_12(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    try:
        active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
        try:
            limit = int((query.get('limit') or [50])[0] or 50)
        except (TypeError, ValueError):
            limit = 50
        if limit < 0:
            limit = 0
        history = load_manual_review_control_plane_integrity_history(active_data_root)
        if limit >= 0:
            history = [] if limit == 0 else history[-limit:]
        history = list(reversed(history))
        control_plane_runtime = _manual_review_control_plane_runtime_summary(active_data_root)
        self.send_json({'transition_count': len(history), 'history': history, 'applied_filters': {'limit': limit}, **control_plane_runtime})
    except Exception as e:
        self.send_error_json(status=500, code='AVM_MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_FAILED', message='manual review control plane integrity history 读取失败', details={'error': str(e)})

def _server_get_branch_13(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    (authorized, auth_error) = _nas_auth_recovery_authorized(self.headers)
    if not authorized:
        self.send_error_json(status=403, code='COLLECTION_AUTH_RECOVERY_FORBIDDEN', message='跨设备认证恢复凭据无效', details={'error': auth_error})
        return
    self.send_json({'ok': True, 'auth_recovery': NAS_AUTH_RECOVERY.snapshot()})

def _server_get_branch_14(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    (authorized, auth_error) = _nas_auth_recovery_authorized(self.headers)
    if not authorized:
        self.send_error_json(status=403, code='COLLECTION_AUTH_RECOVERY_FORBIDDEN', message='跨设备认证恢复凭据无效', details={'error': auth_error})
        return
    recovery_id = str((query.get('recovery_id') or [''])[0] or '').strip()
    recovery_state = NAS_AUTH_RECOVERY.snapshot()
    active = recovery_state.get('active') if isinstance(recovery_state, dict) else None
    if not recovery_id or not isinstance(active, dict) or str(active.get('recovery_id') or '') != recovery_id:
        self.send_error_json(status=409, code='COLLECTION_AUTH_RECOVERY_NOT_ACTIVE', message='认证恢复任务已变化，请重新拉取状态')
        return
    status = str(active.get('status') or '')
    snapshot = active.get('snapshot') if isinstance(active.get('snapshot'), dict) else {}
    expected_sha256 = str(snapshot.get('sha256') or '').strip().lower()
    if status not in {'snapshot_ready', 'pc2_claimed', 'restarting'} or not expected_sha256:
        self.send_error_json(status=409, code='COLLECTION_AUTH_RECOVERY_SNAPSHOT_NOT_READY', message='认证快照尚未就绪')
        return
    snapshot_path = Path(_resolve_auth_cookie_snapshot_path({'node_id': 'pc2'}))
    try:
        raw_snapshot = snapshot_path.read_bytes()
    except OSError:
        self.send_error_json(status=404, code='COLLECTION_AUTH_RECOVERY_SNAPSHOT_MISSING', message='NAS 认证快照文件不存在')
        return
    if not raw_snapshot or len(raw_snapshot) > 5 * 1024 * 1024:
        self.send_error_json(status=409, code='COLLECTION_AUTH_RECOVERY_SNAPSHOT_INVALID', message='NAS 认证快照大小无效')
        return
    actual_sha256 = hashlib.sha256(raw_snapshot).hexdigest()
    if actual_sha256 != expected_sha256:
        self.send_error_json(status=409, code='COLLECTION_AUTH_RECOVERY_SNAPSHOT_CHANGED', message='NAS 认证快照摘要已变化，请等待 PC1 重新发布')
        return
    self.send_json({'ok': True, 'recovery_id': recovery_id, 'sha256': actual_sha256, 'encoding': 'base64', 'snapshot': base64.b64encode(raw_snapshot).decode('ascii')})

def _server_get_branch_15(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    try:
        if _collection_api_lightweight_status_enabled():
            self.send_json(_collection_api_lightweight_status_payload())
            return
        db_total_ids = None
        db_processed_ids = None
        db_pending_ids = None
        db_detail_captured_ids = None
        if _prefer_db_task_reads():
            counts = _db_counts_snapshot()
            total_ids = counts['db_total_ids']
            ai_finalized_count = counts['db_processed_ids']
            detail_captured_count = counts['db_detail_captured_ids']
            captured_count = max(ai_finalized_count, detail_captured_count)
            db_total_ids = total_ids
            db_processed_ids = ai_finalized_count
            db_pending_ids = counts['db_pending_ids']
            db_detail_captured_ids = detail_captured_count
            next_batch = []
            now = datetime.datetime.now()
            for candidate in _db_pending_task_candidates(limit=100):
                if len(next_batch) >= 10:
                    break
                tid = candidate['id']
                last_time = DISPATCHED_TASKS.get(tid)
                if not last_time or (now - last_time).total_seconds() >= DISPATCH_COOLDOWN_SECONDS:
                    next_batch.append(tid)
        else:
            with DATA_LOCK:
                total_ids = len(SEEN_IDS)
                captured_ids = set()
                for (tid, entry) in SEEN_IDS.items():
                    if entry.get('data', {}).get('is_processed'):
                        captured_ids.add(tid)
                ai_finalized_count = len(captured_ids)
                for f in os.listdir(DATA_DIR):
                    if f.startswith('item-') and (f.endswith('.txt') or f.endswith('.html')):
                        m = re.search('item-(\\d+)', f)
                        if m:
                            captured_ids.add(m.group(1))
                captured_count = len(captured_ids)
                next_batch = []
                now = datetime.datetime.now()
                for tid in PENDING_TASKS[:100]:
                    if len(next_batch) >= 10:
                        break
                    last_time = DISPATCHED_TASKS.get(tid)
                    if not last_time or (now - last_time).total_seconds() >= DISPATCH_COOLDOWN_SECONDS:
                        next_batch.append(tid)
        if _prefer_db_task_reads():
            pass
        if DB_REPOSITORY.enabled:
            search_counts = _seed_collection_service().counts_snapshot()
            status_info = {'pending_locations': search_counts.get('search_pending', 0), 'done_locations': search_counts.get('search_done', 0)}
        else:
            legacy_counts = _seed_collection_service().counts_snapshot()
            status_info = {'pending_locations': legacy_counts.get('search_pending', 0), 'done_locations': legacy_counts.get('search_done', 0)}
        api_metrics = llm_helper.get_api_metrics()
        collection_stage_snapshot = _db_collection_stage_snapshot()
        avm_status = {**AVM_SERVICE.health_snapshot(lightweight=True), **_avm_operator_eval_summary(Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR)))}
        solver_status_snapshot = _captcha_solver_runtime_status()
        self.send_json({'paused': _collection_effectively_paused(), 'total_ids': total_ids, 'captured_count': captured_count, 'ai_finalized_count': ai_finalized_count, 'db_mode': _prefer_db_task_reads(), 'db_total_ids': db_total_ids, 'db_processed_ids': db_processed_ids, 'db_pending_ids': db_pending_ids, 'db_detail_captured_ids': db_detail_captured_ids, 'sniff_queue_count': status_info.get('pending_locations', 0), 'sniff_done_count': status_info.get('done_locations', 0), 'next_batch_preview': next_batch, 'api_success_rate': api_metrics.get('success_rate', 0.0), 'api_avg_response_time_ms': api_metrics.get('avg_response_time_ms', 0.0), 'api_total_calls': api_metrics.get('total_calls', 0), 'api_success_calls': api_metrics.get('success_calls', 0), 'captcha_solver': solver_status_snapshot, 'auth_recovery': NAS_AUTH_RECOVERY.snapshot(), 'collection_scopes': solver_status_snapshot.get('collection_scopes', {}), 'data_supply_recent_24h': _db_data_supply_snapshot(24) if DB_REPOSITORY.enabled else {}, 'avm': avm_status, 'collection_stage': collection_stage_snapshot})
    except Exception as e:
        self.send_error_json(status=500, code='AVM_STATUS_FAILED', message='状态概览生成失败', details={'error': str(e)})

def _server_get_branch_16(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    if _prefer_db_task_reads():
        try:
            next_task = _detail_collection_service().next_task(dispatched_tasks=DISPATCHED_TASKS, cooldown_seconds=DISPATCH_COOLDOWN_SECONDS)
        except Exception as e:
            self.send_error_json(status=500, code='AVM_DETAIL_NEXT_TASK_FAILED', message='详情任务分发失败', details={'error': str(e)})
            return
        if next_task:
            self.send_json(next_task)
        else:
            self.send_json({})
        return
    else:
        now = datetime.datetime.now()
        next_task = None
        with DATA_LOCK:
            PENDING_TASKS[:] = [tid for tid in PENDING_TASKS if tid in SEEN_IDS and (not SEEN_IDS[tid].get('data', {}).get('is_processed'))]
            check_candidates = list(PENDING_TASKS)
            for tid in check_candidates:
                last_time = DISPATCHED_TASKS.get(tid)
                if last_time and (now - last_time).total_seconds() < DISPATCH_COOLDOWN_SECONDS:
                    continue
                if tid in SEEN_IDS:
                    item = SEEN_IDS[tid]['data']
                    next_task = {'url': item.get('url')}
                    DISPATCHED_TASKS[tid] = now
                    break
    if next_task:
        self.send_json(next_task)
    else:
        self.send_json({})

def _server_get_branch_17(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    parsed_url = urlparse(self.path)
    params = parse_qs(parsed_url.query)
    item_id = (params.get('id', [''])[0] or '').strip()
    if not item_id:
        self.send_error_json(status=400, code='AVM_INVALID_ID', message='缺少必填参数 id', details={'required': ['id']})
        return
    try:
        result = AVM_SERVICE.predict_by_item_id(item_id)
        if result.get('error') == 'item_not_found':
            self.send_error_json(status=404, code='AVM_NOT_FOUND', message=f'ID={item_id} 不存在', details={'id': item_id})
            return
        self.send_json(result)
    except Exception as e:
        print(f'[AVM] Predict error: {e}')
        self.send_error_json(status=500, code='AVM_PREDICT_FAILED', message='估值失败', details={'error': str(e), 'id': str(item_id)})

def _server_get_branch_18(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    try:
        uptime_sec = max(0, int(time.time() - AVM_SERVICE_START_TIME))
        service_stats = AVM_SERVICE.health_snapshot(lightweight=True)
        operator_eval_summary = _avm_operator_eval_summary(Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR)))
        db_stats = {'db_mode': DB_REPOSITORY.enabled, 'db_total_ids': None, 'db_processed_ids': None, 'db_pending_ids': None, 'db_detail_captured_ids': None}
        if DB_REPOSITORY.enabled:
            try:
                db_stats.update(_db_counts_snapshot())
            except Exception as db_health_error:
                db_stats['db_error'] = str(db_health_error)
        self.send_json({'status': 'ok', 'service': 'avm', 'uptime_sec': uptime_sec, **service_stats, **operator_eval_summary, **db_stats, 'data_supply_recent_24h': _db_data_supply_snapshot(24) if DB_REPOSITORY.enabled else {}, 'collection_stage': _db_collection_stage_snapshot()})
    except Exception as e:
        self.send_error_json(status=500, code='AVM_HEALTH_FAILED', message='健康概览生成失败', details={'error': str(e)})

def _server_get_branch_19(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    from src.avm.collection_template import get_collection_template
    try:
        self.send_json(get_collection_template())
    except Exception as e:
        self.send_error_json(status=500, code='AVM_COLLECTION_TEMPLATE_FAILED', message='collection template 生成失败', details={'error': str(e)})

def _server_get_branch_20(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    from tools.check_feature_drift import generate_drift_report
    parsed_url = urlparse(self.path)
    params = parse_qs(parsed_url.query)
    try:
        window_days = int(params.get('window_days', ['30'])[0] or '30')
    except ValueError:
        window_days = 30
    if window_days < 0:
        window_days = 30
    active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
    active_avm_dir = active_data_root / 'avm'
    try:
        output = generate_drift_report(archive_dir=active_data_root / 'archive', output_path=active_avm_dir / 'drift_alerts.json', window_days=window_days)
    except Exception as e:
        self.send_error_json(status=500, code='AVM_DRIFT_FAILED', message='漂移报告生成失败', details={'error': str(e)})
        return
    self.send_json(output)

def _server_get_branch_21(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    from tools.avm_release_gate import generate_release_gate_report
    parsed_url = urlparse(self.path)
    params = parse_qs(parsed_url.query)
    try:
        window_days = int(params.get('window_days', ['7'])[0] or '7')
    except ValueError:
        window_days = 7
    if window_days < 0:
        window_days = 7
    try:
        min_sample_size = int(params.get('min_sample_size', ['1000'])[0] or '1000')
    except ValueError:
        min_sample_size = 1000
    if min_sample_size < 0:
        min_sample_size = 1000
    try:
        smoke_sample_size = int(params.get('smoke_sample_size', ['0'])[0] or '0')
    except ValueError:
        smoke_sample_size = 0
    if smoke_sample_size < 0:
        smoke_sample_size = 0
    active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
    active_avm_dir = active_data_root / 'avm'
    try:
        output = generate_release_gate_report(data_root=active_data_root, eval_report_path=active_avm_dir / 'eval_report.json', gate_report_path=active_avm_dir / 'release_gate.json', window_days=window_days, min_sample_size=min_sample_size, smoke_sample_size=smoke_sample_size)
    except Exception as e:
        self.send_error_json(status=500, code='AVM_RELEASE_GATE_FAILED', message='发布门禁报告生成失败', details={'error': str(e)})
        return
    if isinstance(output, dict):
        try:
            output = {**output, **_avm_operator_eval_summary(active_data_root, gate_report_override=output)}
        except Exception as e:
            self.send_error_json(status=500, code='AVM_RELEASE_GATE_SUMMARY_FAILED', message='发布门禁 operator summary 生成失败', details={'error': str(e)})
            return
    self.send_json(output)

def _server_get_branch_22(self, parsed, request_path, query):
    global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
    from tools.audit_recent_avm_gaps import build_recent_gap_audit
    parsed_url = urlparse(self.path)
    params = parse_qs(parsed_url.query)
    try:
        window_days = int(params.get('window_days', ['7'])[0] or '7')
    except ValueError:
        window_days = 7
    if window_days < 0:
        window_days = 7
    try:
        sample_limit = int(params.get('sample_limit', ['20'])[0] or '20')
    except ValueError:
        sample_limit = 20
    if sample_limit < 0:
        sample_limit = 20
    active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
    active_avm_dir = active_data_root / 'avm'
    try:
        output = build_recent_gap_audit(data_root=active_data_root, window_days=window_days, sample_limit=sample_limit)
        (active_avm_dir / 'recent_gap_audit.json').parent.mkdir(parents=True, exist_ok=True)
        (active_avm_dir / 'recent_gap_audit.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    except Exception as e:
        self.send_error_json(status=500, code='AVM_RECENT_GAP_AUDIT_FAILED', message='recent gap 审计失败', details={'error': str(e)})
        return
    self.send_json(output)

__all__ = ["_server_get_branch_01", "_server_get_branch_02", "_server_get_branch_03", "_server_get_branch_04", "_server_get_branch_05", "_server_get_branch_06", "_server_get_branch_07", "_server_get_branch_08", "_server_get_branch_09", "_server_get_branch_10", "_server_get_branch_11", "_server_get_branch_12", "_server_get_branch_13", "_server_get_branch_14", "_server_get_branch_15", "_server_get_branch_16", "_server_get_branch_17", "_server_get_branch_18", "_server_get_branch_19", "_server_get_branch_20", "_server_get_branch_21", "_server_get_branch_22"]
