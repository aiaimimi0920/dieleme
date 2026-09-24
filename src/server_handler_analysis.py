from __future__ import annotations

import logging

from .server_context import *  # noqa: F401,F403

logger = logging.getLogger(__name__)

def _post_manual_review_receipt(self):
    from uuid import uuid4

    if not _require_control_plane(self):
        return
    (accepted, payload) = _read_json_body(self)
    if not accepted:
        return
    (valid, error_payload) = _validate_manual_review_receipt_payload(payload if isinstance(payload, dict) else {})
    if not valid:
        self.send_error_json(status=400, code=error_payload['code'], message=error_payload['message'], details=error_payload.get('details', {}))
        return
    active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
    try:
        mode = str(payload.get('mode', 'sync') or 'sync').lower()
        maintenance_job_id = uuid4().hex if mode == 'async' else None
        work = _prepare_manual_review_receipt_submission(
            active_data_root,
            payload,
            mode,
            maintenance_job_id=maintenance_job_id,
        )
    except Exception as e:
        self.send_error_json(status=500, code='AVM_MANUAL_REVIEW_RECEIPT_UPSERT_FAILED', message='Unable to prepare manual review receipt', details={'error': str(e)})
        return
    if mode == 'sync':
        self._enqueue_collection_job('manual_review_receipt', work, 'AVM_MANUAL_REVIEW_RECEIPT_MAINTENANCE_FAILED')
        return
    # Keep the legacy 200 response for explicit ``mode: async`` callers while
    # routing the actual receipt write and maintenance through the same durable
    # CollectionJobManager used by every other long-running entry point.
    self._enqueue_collection_job(
        'manual_review_receipt',
        work,
        'AVM_MANUAL_REVIEW_RECEIPT_ASYNC_FAILED',
        job_id=maintenance_job_id,
        response_status=200,
        response_extra={
            **getattr(work, 'preview', {}),
            'status': 'ok',
            'execution_mode': 'async',
            'maintenance_triggered': True,
            'maintenance_job_id': maintenance_job_id,
            'maintenance_job_status': 'queued',
            'manual_review_control_plane_storage': _manual_review_control_plane_storage(active_data_root),
            'manual_review_control_plane_backup': _manual_review_control_plane_backup(active_data_root),
        },
    )

def _prepare_manual_review_receipt_submission(
    active_data_root,
    payload,
    mode,
    *,
    maintenance_job_id=None,
):
    from copy import deepcopy
    from src.collection_jobs import CollectionJobFailure

    receipt = {'action': payload['action'], 'ready_signal': payload['ready_signal'], 'status': payload['status'], 'payload': deepcopy(payload.get('payload') or {})}
    for key in ('resolution_notes', 'source'):
        if isinstance(payload.get(key), str) and payload[key].strip():
            receipt[key] = payload[key].strip()
    maintenance_options = _normalize_manual_review_maintenance_options(payload.get('maintenance'))
    repository = DB_REPOSITORY if DB_REPOSITORY.enabled else None
    store_path = _manual_review_receipt_store_path(active_data_root)
    operations_path = _manual_review_receipt_operations_path(active_data_root)
    upsert = upsert_manual_review_receipt
    append_operation = append_manual_review_receipt_operation
    maintenance = run_recent_enrich_maintenance
    load_context = _manual_review_receipt_context
    summaries = {
        'manual_review_receipt_jobs_summary': _manual_review_receipt_jobs_summary,
        'manual_review_control_plane_storage': _manual_review_control_plane_storage,
        'manual_review_control_plane_backup': _manual_review_control_plane_backup,
        'manual_review_control_plane_backup_repairs_summary': _manual_review_control_plane_backup_repairs_summary,
        'manual_review_control_plane_integrity': _manual_review_control_plane_integrity,
        'manual_review_control_plane_integrity_history_summary': _manual_review_control_plane_integrity_history_summary,
        'manual_review_control_plane_stability': _manual_review_control_plane_stability,
        'manual_review_control_plane_guidance': _manual_review_control_plane_guidance,
    }
    preview = {
        'status': 'ok',
        'operation': 'created',
        'receipt': dict(receipt),
    }
    try:
        existing = list_manual_review_receipts(store_path, repository=repository)
        if any(
            str(item.get('action') or '').strip() == receipt['action']
            and str(item.get('ready_signal') or '').strip() == receipt['ready_signal']
            for item in existing.get('receipts') or []
        ):
            preview['operation'] = 'updated'
    except Exception:
        # The durable worker remains the source of truth. A preview failure
        # must not turn an otherwise valid queue submission into a write.
        pass
    failure_code = (
        'AVM_MANUAL_REVIEW_RECEIPT_SYNC_FINALIZE_FAILED'
        if mode == 'sync'
        else 'AVM_MANUAL_REVIEW_RECEIPT_ASYNC_FINALIZE_FAILED'
    )

    def run():
        try:
            operation_result = upsert(store_path, receipt, repository=repository)
            context = load_context(active_data_root)
            response = {
                'status': 'ok', 'operation': operation_result['operation'], 'execution_mode': mode,
                'maintenance_triggered': False, 'receipt': operation_result['receipt'],
                **{key: context[key] for key in (*summaries, 'manual_review_receipt_summary', 'operator_overview')},
            }
        except Exception as error:
            raise CollectionJobFailure('AVM_MANUAL_REVIEW_RECEIPT_UPSERT_FAILED') from error
        try:
            report = maintenance(data_root=active_data_root, repository=repository, **maintenance_options)
        except Exception as error:
            raise CollectionJobFailure('AVM_MANUAL_REVIEW_RECEIPT_MAINTENANCE_FAILED') from error
        try:
            operation_options = {}
            response['maintenance_report'] = report
            for key in ('manual_review_receipt_summary', 'operator_overview'):
                response[key] = report.get(key, context[key])
            if maintenance_job_id:
                operation_options['maintenance_job_id'] = maintenance_job_id
                response['maintenance_job_id'] = maintenance_job_id
                response['maintenance_job_status'] = 'completed'
            append_operation(operations_path, operation=operation_result['operation'], receipt=operation_result['receipt'], execution_mode=mode, repository=repository, **operation_options)
            response['maintenance_triggered'] = True
            response.update({key: reader(active_data_root) for key, reader in summaries.items()})
        except Exception as error:
            raise CollectionJobFailure(failure_code) from error
        return response

    run.preview = preview
    return run

def _resolve_pipeline_data_dir(requested):
    """Only the configured data root (or a directory inside it) may drive the pipeline."""
    active_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR)).resolve()
    if requested in (None, ''):
        return str(active_root)
    try:
        candidate = Path(str(requested)).resolve()
        candidate.relative_to(active_root)
    except (OSError, ValueError, TypeError):
        return None
    return str(candidate)

def _post_analysis_run(self):
    if not _require_control_plane(self):
        return
    (accepted, payload) = _read_json_body(self)
    if not accepted:
        return
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
    data_dir = _resolve_pipeline_data_dir(payload.get('data_dir'))
    if data_dir is None:
        invalid_fields.append('data_dir')
    if invalid_fields:
        self.send_error_json(status=400, code='AVM_INVALID_PIPELINE_CONFIG', message='pipeline 配置参数无效', details={'invalid_fields': invalid_fields})
        return
    config = AVMPipelineConfig(data_dir=data_dir, alerts_threshold=alerts_threshold, alerts_limit=alerts_limit)
    self._submit_pipeline_job(config, 'AVM_PIPELINE_RUN_FAILED')

def _read_execution_mode(self, payload):
    raw_execution_mode = payload.get('execution_mode', 'sync')
    if not isinstance(raw_execution_mode, str) or raw_execution_mode.strip().lower() not in {'sync', 'async'}:
        self.send_error_json(
            status=400,
            code='AVM_INVALID_EXECUTION_MODE',
            message="execution_mode must be 'sync' or 'async'",
            details={'allowed': ['sync', 'async']},
        )
        return None
    return raw_execution_mode.strip().lower()

def _post_analysis_evaluate(self):
    (accepted, payload) = _read_json_body(self)
    if not accepted:
        return
    execution_mode = _read_execution_mode(self, payload)
    if execution_mode is None:
        return
    subject = payload.get('subject') if isinstance(payload.get('subject'), dict) else {}
    if not subject:
        self.send_error_json(status=400, code='AVM_INVALID_SUBJECT', message='缺少 subject 对象', details={'required': ['subject']})
        return
    if subject.get('area_sqm') in (None, ''):
        self.send_error_json(status=400, code='AVM_MISSING_AREA', message='subject.area_sqm 为必填', details={'required': ['subject.area_sqm']})
        return
    evaluation_payload = dict(payload)
    evaluation_payload.pop('execution_mode', None)
    service = AVM_SERVICE
    if execution_mode == 'async':
        def work():
            return service.evaluate_request(evaluation_payload)

        response_extra = {'execution_mode': 'async'}
        if 'request_id' in evaluation_payload:
            response_extra['request_id'] = evaluation_payload['request_id']
        self._enqueue_collection_job(
            'avm_evaluate',
            work,
            'AVM_EVALUATE_ASYNC_FAILED',
            response_extra=response_extra,
        )
        return
    try:
        result = service.evaluate_request(evaluation_payload)
    except Exception as e:
        logger.exception('[AVM] Evaluate failed')
        self.send_error_json(status=500, code='AVM_EVALUATE_FAILED', message='评估失败', details={'error': str(e)})
        return
    self.send_json(result)

def _post_detail_maintenance(self):
    self._submit_maintenance_job('recent_enrich_maintenance', 'AVM_RECENT_ENRICH_MAINTENANCE_FAILED')

def _post_fetch_missing_detail_archives(self):
    self._submit_maintenance_job('fetch_missing_detail_archives', 'AVM_FETCH_MISSING_DETAIL_ARCHIVES_FAILED')

def _post_archive_detail_replay(self):
    self._submit_maintenance_job('archive_detail_replay', 'AVM_ARCHIVE_DETAIL_REPLAY_FAILED')

def _post_start_all_subtasks(self):
    if not _require_control_plane(self):
        return
    accepted, _payload = _read_json_body(self)
    if not accepted:
        return
    self._submit_pipeline_job(AVMPipelineConfig(data_dir=_resolve_pipeline_data_dir(None)), 'AVM_START_ALL_SUBTASKS_FAILED')

def _post_run_all_subtasks_sync(self):
    if not _require_control_plane(self):
        return
    accepted, _payload = _read_json_body(self)
    if not accepted:
        return
    self._submit_pipeline_job(AVMPipelineConfig(data_dir=_resolve_pipeline_data_dir(None)), 'AVM_RUN_ALL_SUBTASKS_SYNC_FAILED')

def _post_save_locations(self):
    from src.archive_json_io import read_records, write_records

    if not _require_control_plane(self):
        return
    (accepted, data) = _read_json_body(self)
    if not accepted:
        return
    try:
        new_locations = data.get('locations', [])
        loc_file = os.path.join(DATA_DIR, 'collected_locations.json')
        with RUNTIME.file_lock:
            existing_locs = {item['code']: item['name'] for item in read_records(loc_file)}
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
                write_records(loc_file, final_list, indent=2)
                logger.info('Saved %s locations. Total unique: %s', len(new_locations), len(final_list))
        self.send_json({'status': 'ok', 'count': len(new_locations)})
    except Exception as e:
        logger.exception('Error saving locations')
        self.send_error_json(status=500, code='AVM_SAVE_LOCATIONS_FAILED', message='行政区划保存失败', details={'error': str(e)})

def _post_area_result(self):
    (accepted, data) = _read_json_body(self)
    if not accepted:
        return
    try:
        runtime_index = _collection_runtime_index()
        item_id = str(data.get('id'))
        result = _detail_collection_service().apply_working_item_patch(item_id=item_id, patch_data=data, event_type='area_result', get_working_item=_get_working_item, apply_flat_override_patch=_apply_flat_override_patch, reset_structured_sections_for_resync=_reset_structured_sections_for_resync, update_file_global=update_file_global, persist_item_to_db=persist_item_to_db, evict_runtime_item=_evict_runtime_item, prefer_db_task_reads=_prefer_db_task_reads, pending_tasks=runtime_index.pending_tasks, remove_pending=runtime_index.remove_pending, mark_processed=True)
        if result['status'] == 'ok':
            logger.info('[AREA RESULT] Updated %s | Area: %s', item_id, data.get('建筑面积', 0))
            self.send_json(result)
        else:
            logger.warning('[AREA RESULT] Item %s not found in index', item_id)
            self.send_error_json(status=404, code='AVM_DETAIL_ITEM_NOT_FOUND', message='未找到目标条目', details={'id': item_id})
    except Exception as e:
        logger.exception('Error processing area result')
        self.send_error_json(status=500, code='AVM_DETAIL_AREA_RESULT_FAILED', message='面积结果回写失败', details={'error': str(e)})

def _post_infer_location(self):
    (accepted, data) = _read_json_body(self)
    if not accepted:
        return
    execution_mode = _read_execution_mode(self, data)
    if execution_mode is None:
        return
    try:
        address = data.get('address', '')
        title = data.get('title', '')
        item_id = data.get('id')
        logger.info('[Infer Location] Request for: %s | %s', address, title)
        service = _detail_collection_service()
        chat_with_glm = llm_helper.chat_with_glm
        log_prediction_event = llm_helper.log_prediction_event
        if execution_mode == 'async':
            def work():
                return service.infer_location(
                    address=address,
                    title=title,
                    item_id=item_id,
                    chat_with_glm=chat_with_glm,
                    log_prediction_event=log_prediction_event,
                )

            response_extra = {'execution_mode': 'async'}
            if 'id' in data:
                response_extra['item_id'] = item_id
            self._enqueue_collection_job(
                'infer_location',
                work,
                'AVM_DETAIL_INFER_LOCATION_ASYNC_FAILED',
                response_extra=response_extra,
            )
            return
        result = service.infer_location(address=address, title=title, item_id=item_id, chat_with_glm=chat_with_glm, log_prediction_event=log_prediction_event)
        self.send_json(result)
    except Exception as e:
        logger.exception('Error in infer_location')
        self.send_error_json(status=500, code='AVM_DETAIL_INFER_LOCATION_FAILED', message='位置推断失败', details={'error': str(e)})

def _post_approve_area(self):
    (accepted, data) = _read_json_body(self)
    if not accepted:
        return
    try:
        runtime_index = _collection_runtime_index()
        item_id = str(data.get('id'))
        result = _detail_collection_service().apply_working_item_patch(item_id=item_id, patch_data=data, event_type='manual_approve_area', get_working_item=_get_working_item, apply_flat_override_patch=_apply_flat_override_patch, reset_structured_sections_for_resync=_reset_structured_sections_for_resync, update_file_global=update_file_global, persist_item_to_db=persist_item_to_db, evict_runtime_item=_evict_runtime_item, prefer_db_task_reads=_prefer_db_task_reads, pending_tasks=runtime_index.pending_tasks, remove_pending=runtime_index.remove_pending, mark_processed=True, force_status='done')
        if result['status'] == 'ok':
            logger.info('[APPROVE AREA] Manually Approved %s | Area: %s', item_id, data.get('建筑面积', 0))
            self.send_json(result)
        else:
            logger.warning('[APPROVE AREA] Item %s not found in index', item_id)
            self.send_error_json(status=404, code='AVM_DETAIL_ITEM_NOT_FOUND', message='未找到目标条目', details={'id': item_id})
    except Exception as e:
        logger.exception('Error processing area approval')
        self.send_error_json(status=500, code='AVM_DETAIL_APPROVE_AREA_FAILED', message='面积人工确认失败', details={'error': str(e)})

def _post_seed_batch(self):
    (accepted, data) = _read_json_body(self)
    if not accepted:
        return
    mode = str(data.get('mode', 'sync') or 'sync').lower()
    if mode == 'async':
        if not _require_control_plane(self):
            return
        submission_data = {key: value for key, value in data.items() if key != 'mode'}

        def run():
            return handle_seed_batch_submission(submission_data)

        self._enqueue_collection_job(
            'seed_batch',
            run,
            'AVM_SEED_BATCH_ASYNC_FAILED',
            response_extra={'execution_mode': 'async'},
        )
        return
    try:
        self.send_json(handle_seed_batch_submission(data))
    except Exception as e:
        logger.exception('Error processing save')
        self.send_error_json(status=500, code='AVM_SEED_BATCH_FAILED', message='种子批量提交失败', details={'error': str(e)})

__all__ = ["_resolve_pipeline_data_dir", "_read_execution_mode", "_post_manual_review_receipt", "_prepare_manual_review_receipt_submission", "_post_analysis_run", "_post_analysis_evaluate", "_post_detail_maintenance", "_post_fetch_missing_detail_archives", "_post_archive_detail_replay", "_post_start_all_subtasks", "_post_run_all_subtasks_sync", "_post_save_locations", "_post_area_result", "_post_infer_location", "_post_approve_area", "_post_seed_batch"]
