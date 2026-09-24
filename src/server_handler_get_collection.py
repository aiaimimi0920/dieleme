from __future__ import annotations

import logging

from .server_context import *  # noqa: F401,F403

logger = logging.getLogger(__name__)

def _get_collection_index(self, parsed, request_path, query):
    body = _collection_observer_page_html().encode('utf-8')
    self.send_response(200)
    self.send_header('Content-Type', 'text/html; charset=utf-8')
    self.send_header('Content-Length', str(len(body)))
    self.end_headers()
    self.wfile.write(body)

def _get_collection_asset(self, parsed, request_path, query):
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

def _get_collection_overview(self, parsed, request_path, query):
    try:
        self.send_json(_collection_observer_overview_payload())
    except Exception as e:
        self.send_error_json(status=500, code='COLLECTION_OBSERVER_OVERVIEW_FAILED', message='collection observer overview 读取失败', details={'error': str(e)})

def _get_collection_items(self, parsed, request_path, query):
    try:
        self.send_json(_collection_observer_items_payload(query))
    except Exception as e:
        self.send_error_json(status=500, code='COLLECTION_OBSERVER_ITEMS_FAILED', message='collection observer item 列表读取失败', details={'error': str(e)})

def _get_collection_regions(self, parsed, request_path, query):
    try:
        self.send_json(_collection_observer_regions_payload(query))
    except Exception as e:
        self.send_error_json(status=500, code='COLLECTION_OBSERVER_REGIONS_FAILED', message='collection observer 地区状态读取失败', details={'error': str(e)})

def _get_collection_item(self, parsed, request_path, query):
    try:
        if request_path.startswith('/api/collection/items/'):
            query = dict(query)
            query['item_id'] = [unquote(request_path.rsplit('/', 1)[-1])]
        item_id = str((query.get('item_id') or [''])[0] or '').strip()
        if not item_id:
            self.send_error_json(status=400, code='AVM_INVALID_ID', message='item_id is required')
            return
        observer_detail = getattr(DB_REPOSITORY, 'collection_observer_item_detail', None)
        if not DB_REPOSITORY.enabled or not callable(observer_detail):
            self.send_error_json(status=503, code='COLLECTION_OBSERVER_UNAVAILABLE', message='Observer storage is unavailable')
            return
        payload = _collection_observer_item_payload(query)
        if payload.get('found') is False:
            self.send_error_json(status=404, code='AVM_DETAIL_ITEM_NOT_FOUND', message='Item not found', details={'id': item_id})
            return
        self.send_json(payload)
    except Exception as e:
        self.send_error_json(status=500, code='COLLECTION_OBSERVER_ITEM_FAILED', message='collection observer item 详情读取失败', details={'error': str(e)})

def _get_manual_review_receipts(self, parsed, request_path, query):
    try:
        active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
        payload = list_manual_review_receipts(_manual_review_receipt_store_path(active_data_root), repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None)
        control_plane_runtime = _manual_review_control_plane_runtime_summary(active_data_root)
        self.send_json({'receipt_count': len(payload.get('receipts') or []), 'receipts': list(payload.get('receipts') or []), **control_plane_runtime})
    except Exception as e:
        self.send_error_json(status=500, code='AVM_MANUAL_REVIEW_RECEIPTS_READ_FAILED', message='manual review receipts 读取失败', details={'error': str(e)})

def _get_manual_review_jobs(self, parsed, request_path, query):
    try:
        active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
        collection_manager = self.server.collection_jobs(active_data_root)
        snapshot = _manual_review_receipt_jobs_snapshot(active_data_root, collection_manager)
        jobs = list(snapshot.get('jobs') or [])
        running_job = next((dict(job) for job in jobs if job.get('job_id') == snapshot.get('running_job_id')), None)
        queued_jobs = [dict(job) for job in jobs if job.get('status') == 'queued']
        control_plane_runtime = _manual_review_control_plane_runtime_summary(active_data_root)
        job_id = str((query.get('job_id') or [None])[0] or '').strip()
        if job_id:
            job = next((job for job in jobs if job.get('job_id') == job_id), None)
            receipt_context = _manual_review_receipt_context(active_data_root)
            self.send_json({'job_count': len(jobs), 'job': job, 'running_job': running_job, 'queued_jobs': queued_jobs, 'manual_review_receipt_summary': receipt_context['manual_review_receipt_summary'], 'operator_overview': receipt_context['operator_overview'], **control_plane_runtime})
        else:
            self.send_json({'job_count': len(jobs), 'jobs': jobs, 'running_job': running_job, 'queued_jobs': queued_jobs, **control_plane_runtime})
    except Exception as e:
        self.send_error_json(status=500, code='AVM_MANUAL_REVIEW_RECEIPT_JOBS_READ_FAILED', message='manual review receipt jobs 读取失败', details={'error': str(e)})

def _get_manual_review_operations(self, parsed, request_path, query):
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

def _get_manual_review_control_status(self, parsed, request_path, query):
    try:
        active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
        context = _manual_review_receipt_context(active_data_root)
        self.send_json({'manual_review_receipt_summary': context['manual_review_receipt_summary'], 'manual_review_receipt_jobs_summary': context['manual_review_receipt_jobs_summary'], 'manual_review_receipt_operations_summary': context['manual_review_receipt_operations_summary'], 'manual_review_control_plane_storage': context['manual_review_control_plane_storage'], 'manual_review_control_plane_backup': context['manual_review_control_plane_backup'], 'manual_review_control_plane_backup_repairs_summary': context['manual_review_control_plane_backup_repairs_summary'], 'manual_review_control_plane_integrity': context['manual_review_control_plane_integrity'], 'manual_review_control_plane_integrity_history_summary': context['manual_review_control_plane_integrity_history_summary'], 'manual_review_control_plane_stability': context['manual_review_control_plane_stability'], 'manual_review_control_plane_guidance': context['manual_review_control_plane_guidance']})
    except Exception as e:
        self.send_error_json(status=500, code='AVM_MANUAL_REVIEW_CONTROL_PLANE_STATUS_FAILED', message='manual review control plane 状态读取失败', details={'error': str(e)})

def _get_manual_review_backup_repairs(self, parsed, request_path, query):
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

def _get_manual_review_integrity_history(self, parsed, request_path, query):
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

def _get_auth_recovery(self, parsed, request_path, query):
    (authorized, auth_error) = _nas_auth_recovery_authorized(self.headers)
    if not authorized:
        self.send_error_json(status=403, code='COLLECTION_AUTH_RECOVERY_FORBIDDEN', message='跨设备认证恢复凭据无效', details={'error': auth_error})
        return
    self.send_json({'ok': True, 'auth_recovery': NAS_AUTH_RECOVERY.snapshot()})

def _get_auth_recovery_snapshot(self, parsed, request_path, query):
    from .auth_recovery_codes import SNAPSHOT_AVAILABLE_STATUSES

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
    if status not in SNAPSHOT_AVAILABLE_STATUSES or not expected_sha256:
        self.send_error_json(status=409, code='COLLECTION_AUTH_RECOVERY_SNAPSHOT_NOT_READY', message='认证快照尚未就绪')
        return
    snapshot_path = Path(_resolve_auth_cookie_snapshot_path({'node_id': 'pc2'}))
    if active.get('manual_request_id'):
        from tools.manual_auth_snapshot import snapshot_path as manual_snapshot_path
        snapshot_path = manual_snapshot_path(snapshot_path, recovery_id, expected_sha256)
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

def _get_status(self, parsed, request_path, query):
    runtime_index = _collection_runtime_index()
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
            now = _utc_now()
            with runtime_index.lock:
                dispatched_tasks = dict(runtime_index.dispatched_tasks)
            for candidate in _db_pending_task_candidates(limit=100):
                if len(next_batch) >= 10:
                    break
                tid = candidate['id']
                last_time = _as_utc_timestamp(dispatched_tasks.get(tid))
                if not last_time or (now - last_time).total_seconds() >= DISPATCH_COOLDOWN_SECONDS:
                    next_batch.append(tid)
        else:
            with runtime_index.lock:
                total_ids = len(runtime_index.seen_ids)
                captured_ids = set()
                for (tid, entry) in runtime_index.seen_ids.items():
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
                now = _utc_now()
                for tid in runtime_index.pending_tasks[:100]:
                    if len(next_batch) >= 10:
                        break
                    last_time = _as_utc_timestamp(runtime_index.dispatched_tasks.get(tid))
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
        runtime_snapshot = _collection_runtime_snapshot()
        self.send_json({'paused': runtime_snapshot['paused'], 'total_ids': total_ids, 'captured_count': captured_count, 'ai_finalized_count': ai_finalized_count, 'db_mode': _prefer_db_task_reads(), 'db_total_ids': db_total_ids, 'db_processed_ids': db_processed_ids, 'db_pending_ids': db_pending_ids, 'db_detail_captured_ids': db_detail_captured_ids, 'sniff_queue_count': status_info.get('pending_locations', 0), 'sniff_done_count': status_info.get('done_locations', 0), 'next_batch_preview': next_batch, 'api_success_rate': api_metrics.get('success_rate', 0.0), 'api_avg_response_time_ms': api_metrics.get('avg_response_time_ms', 0.0), 'api_total_calls': api_metrics.get('total_calls', 0), 'api_success_calls': api_metrics.get('success_calls', 0), 'captcha_solver': runtime_snapshot['captcha_solver'], 'auth_recovery': runtime_snapshot['auth_recovery'], 'collection_scopes': runtime_snapshot['collection_scopes'], 'data_supply_recent_24h': _db_data_supply_snapshot(24) if DB_REPOSITORY.enabled else {}, 'avm': avm_status, 'collection_stage': collection_stage_snapshot})
    except Exception as e:
        self.send_error_json(status=500, code='AVM_STATUS_FAILED', message='状态概览生成失败', details={'error': str(e)})

def _post_detail_next_task(self):
    runtime_index = _collection_runtime_index()
    accepted, _payload = _read_json_body(self)
    if not accepted:
        return
    if _prefer_db_task_reads():
        try:
            next_task = _detail_collection_service().next_task(
                dispatched_tasks=runtime_index.dispatched_tasks,
                cooldown_seconds=DISPATCH_COOLDOWN_SECONDS,
                dispatch_lock=runtime_index.lock,
                mark_dispatched=runtime_index.mark_dispatched,
            )
        except Exception as e:
            self.send_error_json(status=500, code='AVM_DETAIL_NEXT_TASK_FAILED', message='详情任务分发失败', details={'error': str(e)})
            return
        if next_task:
            self.send_json(next_task)
        else:
            self.send_json({})
        return
    else:
        now = _utc_now()
        next_task = None
        with runtime_index.lock:
            runtime_index.prune_unavailable_pending()
            check_candidates = list(runtime_index.pending_tasks)
            for tid in check_candidates:
                last_time = _as_utc_timestamp(runtime_index.dispatched_tasks.get(tid))
                if last_time and (now - last_time).total_seconds() < DISPATCH_COOLDOWN_SECONDS:
                    continue
                if tid in runtime_index.seen_ids:
                    item = runtime_index.seen_ids[tid]['data']
                    next_task = {'url': item.get('url')}
                    runtime_index.mark_dispatched(tid, now)
                    break
    if next_task:
        self.send_json(next_task)
    else:
        self.send_json({})

def _get_analysis_prediction(self, parsed, request_path, query):
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
        logger.exception("AVM prediction failed item=%s", item_id)
        self.send_error_json(status=500, code='AVM_PREDICT_FAILED', message='估值失败', details={'error': str(e), 'id': str(item_id)})

def _get_analysis_health(self, parsed, request_path, query):
    try:
        uptime_sec = max(0, int(time.time() - _runtime_started_at()))
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

def _get_collection_template(self, parsed, request_path, query):
    from src.avm.collection_template import get_collection_template
    try:
        self.send_json(get_collection_template())
    except Exception as e:
        self.send_error_json(status=500, code='AVM_COLLECTION_TEMPLATE_FAILED', message='collection template 生成失败', details={'error': str(e)})

def _post_drift_report(self):
    from tools.check_feature_drift import generate_drift_report
    accepted, payload = _read_json_body(self)
    if not accepted:
        return
    try:
        window_days = int(payload.get('window_days', 30))
    except (TypeError, ValueError):
        window_days = 30
    if window_days < 0:
        window_days = 30
    active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
    active_avm_dir = active_data_root / 'avm'
    def run():
        return generate_drift_report(archive_dir=active_data_root / 'archive', output_path=active_avm_dir / 'drift_alerts.json', window_days=window_days)

    self._enqueue_collection_job('drift_report', run, 'AVM_DRIFT_FAILED')

def _post_release_gate(self):
    from src.collection_jobs import CollectionJobFailure
    from tools.avm_release_gate import generate_release_gate_report
    accepted, payload = _read_json_body(self)
    if not accepted:
        return
    try:
        window_days = int(payload.get('window_days', 7))
    except (TypeError, ValueError):
        window_days = 7
    if window_days < 0:
        window_days = 7
    try:
        min_sample_size = int(payload.get('min_sample_size', 1000))
    except (TypeError, ValueError):
        min_sample_size = 1000
    if min_sample_size < 0:
        min_sample_size = 1000
    try:
        smoke_sample_size = int(payload.get('smoke_sample_size', 0))
    except (TypeError, ValueError):
        smoke_sample_size = 0
    if smoke_sample_size < 0:
        smoke_sample_size = 0
    active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
    active_avm_dir = active_data_root / 'avm'
    summarize = _avm_operator_eval_summary

    def run():
        output = generate_release_gate_report(data_root=active_data_root, eval_report_path=active_avm_dir / 'eval_report.json', gate_report_path=active_avm_dir / 'release_gate.json', window_days=window_days, min_sample_size=min_sample_size, smoke_sample_size=smoke_sample_size)
        if isinstance(output, dict):
            try:
                output = {**output, **summarize(active_data_root, gate_report_override=output)}
            except Exception as error:
                raise CollectionJobFailure('AVM_RELEASE_GATE_SUMMARY_FAILED') from error
        return output

    self._enqueue_collection_job('release_gate_report', run, 'AVM_RELEASE_GATE_FAILED')

def _post_recent_gap_audit(self):
    from src.archive_json_io import write_json
    from tools.audit_recent_avm_gaps import build_recent_gap_audit
    accepted, payload = _read_json_body(self)
    if not accepted:
        return
    try:
        window_days = int(payload.get('window_days', 7))
    except (TypeError, ValueError):
        window_days = 7
    if window_days < 0:
        window_days = 7
    try:
        sample_limit = int(payload.get('sample_limit', 20))
    except (TypeError, ValueError):
        sample_limit = 20
    if sample_limit < 0:
        sample_limit = 20
    active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
    active_avm_dir = active_data_root / 'avm'
    def run():
        output = build_recent_gap_audit(data_root=active_data_root, window_days=window_days, sample_limit=sample_limit)
        active_avm_dir.mkdir(parents=True, exist_ok=True)
        write_json(active_avm_dir / 'recent_gap_audit.json', output, indent=2)
        return output

    self._enqueue_collection_job('recent_gap_audit', run, 'AVM_RECENT_GAP_AUDIT_FAILED')

__all__ = ["_get_collection_index", "_get_collection_asset", "_get_collection_overview", "_get_collection_items", "_get_collection_regions", "_get_collection_item", "_get_manual_review_receipts", "_get_manual_review_jobs", "_get_manual_review_operations", "_get_manual_review_control_status", "_get_manual_review_backup_repairs", "_get_manual_review_integrity_history", "_get_auth_recovery", "_get_auth_recovery_snapshot", "_get_status", "_post_detail_next_task", "_get_analysis_prediction", "_get_analysis_health", "_get_collection_template", "_post_drift_report", "_post_release_gate", "_post_recent_gap_audit"]
