from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def _server_post_branch_10(self):
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
    (token_valid, token_error) = _verify_control_plane_token(self.headers)
    if not token_valid:
        self.send_error_json(status=403, code=token_error['code'], message=token_error['message'], details=token_error.get('details', {}))
        return
    (valid, error_payload) = _validate_manual_review_receipt_payload(payload if isinstance(payload, dict) else {})
    if not valid:
        self.send_error_json(status=400, code=error_payload['code'], message=error_payload['message'], details=error_payload.get('details', {}))
        return
    active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
    try:
        store_path = _manual_review_receipt_store_path(active_data_root)
        receipt = {'action': payload['action'], 'ready_signal': payload['ready_signal'], 'status': payload['status'], 'payload': dict(payload.get('payload') or {})}
        if isinstance(payload.get('resolution_notes'), str) and payload.get('resolution_notes', '').strip():
            receipt['resolution_notes'] = payload['resolution_notes'].strip()
        if isinstance(payload.get('source'), str) and payload.get('source', '').strip():
            receipt['source'] = payload['source'].strip()
        operation_result = upsert_manual_review_receipt(store_path, receipt, repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None)
        context = _manual_review_receipt_context(active_data_root)
        mode = str(payload.get('mode', 'sync') or 'sync').lower()
        maintenance_options = _normalize_manual_review_maintenance_options(payload.get('maintenance'))
    except Exception as e:
        self.send_error_json(status=500, code='AVM_MANUAL_REVIEW_RECEIPT_UPSERT_FAILED', message='manual review receipt 写入失败', details={'error': str(e)})
        return
    response = {'status': 'ok', 'operation': operation_result['operation'], 'execution_mode': mode, 'maintenance_triggered': False, 'receipt': operation_result['receipt'], 'manual_review_receipt_summary': context['manual_review_receipt_summary'], 'manual_review_receipt_jobs_summary': context['manual_review_receipt_jobs_summary'], 'manual_review_control_plane_storage': context['manual_review_control_plane_storage'], 'manual_review_control_plane_backup': context['manual_review_control_plane_backup'], 'manual_review_control_plane_backup_repairs_summary': context['manual_review_control_plane_backup_repairs_summary'], 'manual_review_control_plane_integrity': context['manual_review_control_plane_integrity'], 'manual_review_control_plane_integrity_history_summary': context['manual_review_control_plane_integrity_history_summary'], 'manual_review_control_plane_stability': context['manual_review_control_plane_stability'], 'manual_review_control_plane_guidance': context['manual_review_control_plane_guidance'], 'operator_overview': context['operator_overview']}
    if mode == 'sync':
        try:
            maintenance_report = _run_manual_review_receipt_maintenance(active_data_root, maintenance_options)
        except Exception as e:
            self.send_error_json(status=500, code='AVM_MANUAL_REVIEW_RECEIPT_MAINTENANCE_FAILED', message='receipt 提交后 maintenance 执行失败', details={'error': str(e)})
            return
        try:
            append_manual_review_receipt_operation(_manual_review_receipt_operations_path(active_data_root), operation=operation_result['operation'], receipt=operation_result['receipt'], execution_mode='sync', repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None)
            response['maintenance_triggered'] = True
            response['maintenance_report'] = maintenance_report
            response['manual_review_receipt_summary'] = maintenance_report.get('manual_review_receipt_summary', context['manual_review_receipt_summary'])
            response['operator_overview'] = maintenance_report.get('operator_overview', context['operator_overview'])
            response['manual_review_receipt_jobs_summary'] = _manual_review_receipt_jobs_summary(active_data_root)
            response['manual_review_control_plane_storage'] = _manual_review_control_plane_storage(active_data_root)
            response['manual_review_control_plane_backup'] = _manual_review_control_plane_backup(active_data_root)
            response['manual_review_control_plane_backup_repairs_summary'] = _manual_review_control_plane_backup_repairs_summary(active_data_root)
            response['manual_review_control_plane_integrity'] = _manual_review_control_plane_integrity(active_data_root)
            response['manual_review_control_plane_integrity_history_summary'] = _manual_review_control_plane_integrity_history_summary(active_data_root)
            response['manual_review_control_plane_stability'] = _manual_review_control_plane_stability(active_data_root)
            response['manual_review_control_plane_guidance'] = _manual_review_control_plane_guidance(active_data_root)
        except Exception as e:
            self.send_error_json(status=500, code='AVM_MANUAL_REVIEW_RECEIPT_SYNC_FINALIZE_FAILED', message='manual review receipt 同步 maintenance 收尾失败', details={'error': str(e)})
            return
    else:
        try:
            manager = _get_manual_review_maintenance_manager(active_data_root)
            job = manager.enqueue(receipt_key={'action': operation_result['receipt']['action'], 'ready_signal': operation_result['receipt']['ready_signal']}, maintenance_options=maintenance_options)
            append_manual_review_receipt_operation(_manual_review_receipt_operations_path(active_data_root), operation=operation_result['operation'], receipt=operation_result['receipt'], execution_mode='async', maintenance_job_id=job['job_id'], repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None)
            response['maintenance_triggered'] = True
            response['maintenance_job_id'] = job['job_id']
            response['maintenance_job_status'] = job['status']
            response['manual_review_receipt_jobs_summary'] = _manual_review_receipt_jobs_summary(active_data_root)
            response['manual_review_control_plane_storage'] = _manual_review_control_plane_storage(active_data_root)
            response['manual_review_control_plane_backup'] = _manual_review_control_plane_backup(active_data_root)
            response['manual_review_control_plane_backup_repairs_summary'] = _manual_review_control_plane_backup_repairs_summary(active_data_root)
            response['manual_review_control_plane_integrity'] = _manual_review_control_plane_integrity(active_data_root)
            response['manual_review_control_plane_integrity_history_summary'] = _manual_review_control_plane_integrity_history_summary(active_data_root)
            response['manual_review_control_plane_stability'] = _manual_review_control_plane_stability(active_data_root)
            response['manual_review_control_plane_guidance'] = _manual_review_control_plane_guidance(active_data_root)
        except Exception as e:
            self.send_error_json(status=500, code='AVM_MANUAL_REVIEW_RECEIPT_ENQUEUE_FAILED', message='manual review receipt 异步 maintenance 入队失败', details={'error': str(e)})
            return
    self.send_json(response)

def _server_post_branch_11(self):
    global PAUSED, LAST_REQUEST_TIME
    content_length = int(self.headers['Content-Length']) if self.headers.get('Content-Length') else 0
    payload = {}
    if content_length > 0:
        try:
            payload = json.loads(self.rfile.read(content_length).decode('utf-8'))
        except Exception:
            self.send_error_json(status=400, code='AVM_INVALID_JSON', message='请求体不是合法 JSON', details={})
            return
    if not isinstance(payload, dict):
        self.send_error_json(status=400, code='AVM_INVALID_REQUEST_BODY', message='请求体必须是 JSON 对象', details={'expected_type': 'object', 'received_type': _json_payload_type_name(payload)})
        return
    mode = str(payload.get('mode', 'async')).lower()
    invalid_fields = []
    try:
        alerts_threshold = float(payload.get('alerts_threshold', 0.15))
    except (TypeError, ValueError):
        alerts_threshold = None
        invalid_fields.append('alerts_threshold')
    try:
        alerts_limit = int(payload.get('alerts_limit', 500))
    except (TypeError, ValueError):
        alerts_limit = None
        invalid_fields.append('alerts_limit')
    if invalid_fields:
        self.send_error_json(status=400, code='AVM_INVALID_PIPELINE_CONFIG', message='pipeline 配置参数无效', details={'invalid_fields': invalid_fields})
        return
    config = AVMPipelineConfig(data_dir=payload.get('data_dir', DATA_DIR), alerts_threshold=alerts_threshold, alerts_limit=alerts_limit)
    try:
        result = AVM_PIPELINE.run(async_mode=mode != 'sync', config=config)
    except Exception as e:
        self.send_error_json(status=500, code='AVM_PIPELINE_RUN_FAILED', message='pipeline 执行失败', details={'error': str(e)})
        return
    self.send_json(result)

def _server_post_branch_12(self):
    global PAUSED, LAST_REQUEST_TIME
    content_length = int(self.headers['Content-Length']) if self.headers.get('Content-Length') else 0
    try:
        payload = json.loads(self.rfile.read(content_length).decode('utf-8')) if content_length > 0 else {}
    except Exception:
        self.send_error_json(status=400, code='AVM_INVALID_JSON', message='请求体不是合法 JSON', details={})
        return
    if not isinstance(payload, dict):
        self.send_error_json(status=400, code='AVM_INVALID_REQUEST_BODY', message='请求体必须是 JSON 对象', details={'expected_type': 'object', 'received_type': _json_payload_type_name(payload)})
        return
    subject = payload.get('subject') if isinstance(payload.get('subject'), dict) else {}
    if not subject:
        self.send_error_json(status=400, code='AVM_INVALID_SUBJECT', message='缺少 subject 对象', details={'required': ['subject']})
        return
    if subject.get('area_sqm') in (None, ''):
        self.send_error_json(status=400, code='AVM_MISSING_AREA', message='subject.area_sqm 为必填', details={'required': ['subject.area_sqm']})
        return
    try:
        result = AVM_SERVICE.evaluate_request(payload)
    except Exception as e:
        print(f'[AVM] Evaluate failed: {e}')
        self.send_error_json(status=500, code='AVM_EVALUATE_FAILED', message='评估失败', details={'error': str(e)})
        return
    self.send_json(result)

def _server_post_branch_13(self):
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
    active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
    active_avm_dir = active_data_root / 'avm'
    try:
        result = _detail_collection_service(active_data_root).run_maintenance(window_days=int(payload.get('window_days', 7) or 7), archive_limit=int(payload.get('archive_limit', 200) or 200), sample_limit=int(payload.get('sample_limit', 20) or 20), replay_limit=int(payload.get('replay_limit', 100) or 100), fetch_limit=int(payload.get('fetch_limit', 20) or 20), fetch_timeout=int(payload.get('fetch_timeout', 15) or 15), dry_run=bool(payload.get('dry_run', True)), extract_risk=bool(payload.get('extract_risk', False)), prepare_replay=bool(payload.get('prepare_replay', False)), fetch_archives=bool(payload.get('fetch_archives', False)))
        (active_avm_dir / 'recent_enrich_maintenance.json').parent.mkdir(parents=True, exist_ok=True)
        (active_avm_dir / 'recent_enrich_maintenance.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        if not bool(payload.get('dry_run', True)) and result.get('detail_replay_preparation', {}).get('prepared_count'):
            load_data(active_data_root)
    except Exception as e:
        self.send_error_json(status=500, code='AVM_RECENT_ENRICH_MAINTENANCE_FAILED', message='recent enrich maintenance 执行失败', details={'error': str(e)})
        return
    self.send_json(result)

def _server_post_branch_14(self):
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
    active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
    active_avm_dir = active_data_root / 'avm'
    try:
        result = _detail_collection_service(active_data_root).fetch_missing_archives(limit=int(payload.get('limit', 20) or 20), timeout=int(payload.get('timeout', 15) or 15), extract_risk=bool(payload.get('extract_risk', False)), dry_run=bool(payload.get('dry_run', True)))
        (active_avm_dir / 'fetch_missing_detail_archives.json').parent.mkdir(parents=True, exist_ok=True)
        (active_avm_dir / 'fetch_missing_detail_archives.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        if not bool(payload.get('dry_run', True)) and result.get('fetched_count'):
            load_data(active_data_root)
    except Exception as e:
        self.send_error_json(status=500, code='AVM_FETCH_MISSING_DETAIL_ARCHIVES_FAILED', message='缺失详情归档抓取失败', details={'error': str(e)})
        return
    self.send_json(result)

def _server_post_branch_15(self):
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
    active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
    active_avm_dir = active_data_root / 'avm'
    try:
        result = _detail_collection_service(active_data_root).prepare_replay(window_days=int(payload.get('window_days', 30) or 30), limit=int(payload.get('limit', 500) or 500), dry_run=bool(payload.get('dry_run', True)))
        (active_avm_dir / 'archive_detail_replay.json').parent.mkdir(parents=True, exist_ok=True)
        (active_avm_dir / 'archive_detail_replay.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        if not bool(payload.get('dry_run', True)) and result.get('prepared_count'):
            load_data(active_data_root)
    except Exception as e:
        self.send_error_json(status=500, code='AVM_ARCHIVE_DETAIL_REPLAY_FAILED', message='archive detail replay 执行失败', details={'error': str(e)})
        return
    self.send_json(result)

def _server_post_branch_16(self):
    global PAUSED, LAST_REQUEST_TIME
    try:
        result = AVM_PIPELINE.run(async_mode=True, config=AVMPipelineConfig(data_dir=DATA_DIR))
    except Exception as e:
        self.send_error_json(status=500, code='AVM_START_ALL_SUBTASKS_FAILED', message='启动全部子任务失败', details={'error': str(e)})
        return
    self.send_json(result)

def _server_post_branch_17(self):
    global PAUSED, LAST_REQUEST_TIME
    try:
        result = AVM_PIPELINE.run(async_mode=False, config=AVMPipelineConfig(data_dir=DATA_DIR))
    except Exception as e:
        self.send_error_json(status=500, code='AVM_RUN_ALL_SUBTASKS_SYNC_FAILED', message='同步执行全部子任务失败', details={'error': str(e)})
        return
    self.send_json(result)

def _server_post_branch_18(self):
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
        new_locations = data.get('locations', [])
        loc_file = os.path.join(DATA_DIR, 'collected_locations.json')
        existing_locs = {}
        if os.path.exists(loc_file):
            try:
                with open(loc_file, 'r', encoding='utf-8') as f:
                    existing_locs = {item['code']: item['name'] for item in json.load(f)}
            except:
                pass
        updated = False
        for loc in new_locations:
            code = str(loc.get('code'))
            name = loc.get('name')
            if code and name:
                if code not in existing_locs:
                    existing_locs[code] = name
                    updated = True
        if updated:
            final_list = [{'code': k, 'name': v} for (k, v) in existing_locs.items()]
            with open(loc_file, 'w', encoding='utf-8') as f:
                json.dump(final_list, f, ensure_ascii=False, indent=2)
            print(f'Saved {len(new_locations)} locations. Total unique: {len(final_list)}')
        self.send_json({'status': 'ok', 'count': len(new_locations)})
    except Exception as e:
        print(f'Error saving locations: {e}')
        self.send_error_json(status=500, code='AVM_SAVE_LOCATIONS_FAILED', message='行政区划保存失败', details={'error': str(e)})

def _server_post_branch_19(self):
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
        result = _detail_collection_service().apply_working_item_patch(item_id=item_id, patch_data=data, event_type='area_result', get_working_item=_get_working_item, apply_flat_override_patch=_apply_flat_override_patch, reset_structured_sections_for_resync=_reset_structured_sections_for_resync, update_file_global=update_file_global, persist_item_to_db=persist_item_to_db, evict_runtime_item=_evict_runtime_item, prefer_db_task_reads=_prefer_db_task_reads, pending_tasks=PENDING_TASKS, mark_processed=True)
        if result['status'] == 'ok':
            print(f"[AREA RESULT] Updated {item_id} | Area: {data.get('建筑面积', 0)}")
            self.send_json(result)
        else:
            print(f'[AREA RESULT] Item {item_id} not found in index')
            self.send_error_json(status=404, code='AVM_DETAIL_ITEM_NOT_FOUND', message='未找到目标条目', details={'id': item_id})
    except Exception as e:
        print(f'Error processing area result: {e}')
        self.send_error_json(status=500, code='AVM_DETAIL_AREA_RESULT_FAILED', message='面积结果回写失败', details={'error': str(e)})

def _server_post_branch_20(self):
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
        address = data.get('address', '')
        title = data.get('title', '')
        print(f'[Infer Location] Request for: {address} | {title}')
        result = _detail_collection_service().infer_location(address=address, title=title, item_id=data.get('id'), chat_with_glm=llm_helper.chat_with_glm, log_prediction_event=llm_helper.log_prediction_event)
        self.send_json(result)
    except Exception as e:
        print(f'Error in infer_location: {e}')
        self.send_error_json(status=500, code='AVM_DETAIL_INFER_LOCATION_FAILED', message='位置推断失败', details={'error': str(e)})

def _server_post_branch_21(self):
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
        result = _detail_collection_service().apply_working_item_patch(item_id=item_id, patch_data=data, event_type='manual_approve_area', get_working_item=_get_working_item, apply_flat_override_patch=_apply_flat_override_patch, reset_structured_sections_for_resync=_reset_structured_sections_for_resync, update_file_global=update_file_global, persist_item_to_db=persist_item_to_db, evict_runtime_item=_evict_runtime_item, prefer_db_task_reads=_prefer_db_task_reads, pending_tasks=PENDING_TASKS, mark_processed=True, force_status='done')
        if result['status'] == 'ok':
            print(f"[APPROVE AREA] Manually Approved {item_id} | Area: {data.get('建筑面积', 0)}")
            self.send_json(result)
        else:
            print(f'[APPROVE AREA] Item {item_id} not found in index')
            self.send_error_json(status=404, code='AVM_DETAIL_ITEM_NOT_FOUND', message='未找到目标条目', details={'id': item_id})
    except Exception as e:
        print(f'Error processing area approval: {e}')
        self.send_error_json(status=500, code='AVM_DETAIL_APPROVE_AREA_FAILED', message='面积人工确认失败', details={'error': str(e)})

def _server_post_branch_22(self):
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
        self.send_json(handle_seed_batch_submission(data))
    except Exception as e:
        print(f'Error processing save: {e}')
        self.send_error_json(status=500, code='AVM_SEED_BATCH_FAILED', message='种子批量提交失败', details={'error': str(e)})

__all__ = ["_server_post_branch_10", "_server_post_branch_11", "_server_post_branch_12", "_server_post_branch_13", "_server_post_branch_14", "_server_post_branch_15", "_server_post_branch_16", "_server_post_branch_17", "_server_post_branch_18", "_server_post_branch_19", "_server_post_branch_20", "_server_post_branch_21", "_server_post_branch_22"]
