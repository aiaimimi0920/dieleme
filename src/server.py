from __future__ import annotations

import importlib
from pathlib import Path
import sys
import types


if __package__:
    _PACKAGE = __package__
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    _PACKAGE = "src"
_CONTEXT = importlib.import_module(f"{_PACKAGE}.server_context")
_CORE_MODULES = (
    "server_solver_scope",
    "server_auth_recovery",
    "server_solver_state",
    "server_solver_dispatch",
    "server_auth_cookie",
    "server_collection_status",
    "server_collection_control",
    "server_collection_console",
    "server_manual_review",
    "server_hybrid_runtime",
    "server_hybrid_history",
    "server_hybrid_events",
    "server_hybrid_escalation",
    "server_hybrid_lifecycle",
    "server_hybrid_operator_summary",
    "server_hybrid_policy",
    "server_hybrid_context",
    "server_collection_operations",
    "server_data_runtime",
    "server_auto_tuning",
)
_HANDLER_MODULES = (
    "server_handler_get_collection",
    "server_handler_task_control",
    "server_handler_analysis",
    "server_handler_ingest",
    "server_handler_core",
)
_IMPLEMENTATION_MODULES = _CORE_MODULES + _HANDLER_MODULES


def _publish_module(module):
    names = list(getattr(module, "__all__", ()))
    for name in names:
        value = getattr(module, name)
        globals()[name] = value
        setattr(_CONTEXT, name, value)
        if name not in _CONTEXT.__all__:
            _CONTEXT.__all__.append(name)


_publish_module(_CONTEXT)
for _module_name in _CORE_MODULES:
    _publish_module(importlib.import_module(f"{_PACKAGE}.{_module_name}"))


def _rebind_function(function):
    rebound = types.FunctionType(
        function.__code__,
        globals(),
        name=function.__name__,
        argdefs=function.__defaults__,
        closure=function.__closure__,
    )
    rebound.__kwdefaults__ = function.__kwdefaults__
    rebound.__annotations__ = dict(function.__annotations__)
    rebound.__dict__.update(function.__dict__)
    rebound.__doc__ = function.__doc__
    rebound.__module__ = __name__
    rebound.__qualname__ = function.__qualname__
    return rebound


_IMPLEMENTATION_NAMES = {f"{_PACKAGE}.server_context"} | {
    f"{_PACKAGE}.{name}" for name in _IMPLEMENTATION_MODULES
}
for _name, _value in list(globals().items()):
    if isinstance(_value, types.FunctionType) and _value.__module__ in _IMPLEMENTATION_NAMES:
        _value = _rebind_function(_value)
        globals()[_name] = _value
        setattr(_CONTEXT, _name, _value)

for _module_name in _HANDLER_MODULES:
    _module = importlib.import_module(f"{_PACKAGE}.{_module_name}")
    _publish_module(_module)
    for _name in _module.__all__:
        _value = _rebind_function(globals()[_name])
        globals()[_name] = _value
        setattr(_CONTEXT, _name, _value)


class DataHandler(http.server.SimpleHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-FAPAI-Control-Token')
        self.end_headers()

    def do_GET(self):
        global PAUSED, PENDING_TASKS, LAST_REQUEST_TIME
        LAST_REQUEST_TIME = time.time()
        parsed = urlparse(self.path)
        request_path = parsed.path
        query = parse_qs(parsed.query)
        if request_path in ('/collection', '/collection/'):
            return self._server_get_branch_01(parsed, request_path, query)
        elif request_path.startswith('/collection/') or request_path.startswith('/assets/'):
            return self._server_get_branch_02(parsed, request_path, query)
        elif request_path == '/api/collection/overview':
            return self._server_get_branch_03(parsed, request_path, query)
        elif request_path == '/api/collection/items':
            return self._server_get_branch_04(parsed, request_path, query)
        elif request_path == '/api/collection/regions':
            return self._server_get_branch_05(parsed, request_path, query)
        elif request_path == '/api/collection/item' or request_path.startswith('/api/collection/items/'):
            return self._server_get_branch_06(parsed, request_path, query)
        elif request_path in MANUAL_REVIEW_RECEIPT_ENDPOINTS:
            return self._server_get_branch_07(parsed, request_path, query)
        elif request_path in MANUAL_REVIEW_RECEIPT_JOB_ENDPOINTS:
            return self._server_get_branch_08(parsed, request_path, query)
        elif request_path in MANUAL_REVIEW_RECEIPT_OPERATION_ENDPOINTS:
            return self._server_get_branch_09(parsed, request_path, query)
        elif request_path in MANUAL_REVIEW_CONTROL_PLANE_STATUS_ENDPOINTS:
            return self._server_get_branch_10(parsed, request_path, query)
        elif request_path in MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIR_ENDPOINTS:
            return self._server_get_branch_11(parsed, request_path, query)
        elif request_path in MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_ENDPOINTS:
            return self._server_get_branch_12(parsed, request_path, query)
        elif request_path == '/api/collection/auth/recovery':
            return self._server_get_branch_13(parsed, request_path, query)
        elif request_path == '/api/collection/auth/recovery/snapshot':
            return self._server_get_branch_14(parsed, request_path, query)
        elif request_path == '/api/status':
            return self._server_get_branch_15(parsed, request_path, query)
        elif self.path in ('/api/next_task', '/api/collection/details/next_task'):
            return self._server_get_branch_16(parsed, request_path, query)
        elif self.path.startswith('/api/avm/predict') or self.path.startswith('/api/analysis/predict'):
            return self._server_get_branch_17(parsed, request_path, query)
        elif self.path.startswith('/api/avm/health') or self.path.startswith('/api/analysis/health') or self.path.startswith('/api/analysis/status'):
            return self._server_get_branch_18(parsed, request_path, query)
        elif self.path.startswith('/api/avm/collection_template'):
            return self._server_get_branch_19(parsed, request_path, query)
        elif self.path.startswith('/api/avm/drift_status') or self.path.startswith('/api/analysis/drift_status'):
            return self._server_get_branch_20(parsed, request_path, query)
        elif self.path.startswith('/api/avm/release_gate') or self.path.startswith('/api/analysis/release_gate'):
            return self._server_get_branch_21(parsed, request_path, query)
        elif self.path.startswith('/api/avm/recent_gap_audit'):
            return self._server_get_branch_22(parsed, request_path, query)
        elif self.path.startswith('/api/avm/recent_detail_replay') or self.path.startswith('/api/collection/details/prepare_replay'):
            return self._server_get_branch_23(parsed, request_path, query)
        elif self.path.startswith('/api/avm/fetch_missing_detail_archives') or self.path.startswith('/api/collection/details/fetch_missing'):
            return self._server_get_branch_24(parsed, request_path, query)
        elif self.path.startswith('/api/avm/archive_detail_replay'):
            return self._server_get_branch_25(parsed, request_path, query)
        elif self.path.startswith('/api/avm/pipeline_status'):
            return self._server_get_branch_26(parsed, request_path, query)
        elif self.path.startswith('/api/avm/merge_check'):
            return self._server_get_branch_27(parsed, request_path, query)
        elif self.path.startswith('/api/get_item'):
            return self._server_get_branch_28(parsed, request_path, query)
        elif self.path.startswith('/api/get_or_create_sniff_task') or self.path.startswith('/api/collection/seeds/next_task'):
            return self._server_get_branch_29(parsed, request_path, query)
        elif self.path in ('/api/get_tasks', '/api/collection/details/tasks'):
            return self._server_get_branch_30(parsed, request_path, query)
        elif self.path == '/api/resume':
            return self._server_get_branch_31(parsed, request_path, query)
        elif request_path.startswith('/api/'):
            return self._server_get_branch_32(parsed, request_path, query)
        else:
            return self._server_get_fallback(parsed, request_path, query)

    def do_POST(self):
        global PAUSED, LAST_REQUEST_TIME
        LAST_REQUEST_TIME = time.time()
        if self.path in ('/api/report_sniff_status', '/api/collection/seeds/report_progress'):
            return self._server_post_branch_01()
        elif self.path == '/api/collection/region/reset_links':
            return self._server_post_branch_02()
        elif self.path == '/api/collection/item/reanalyze':
            return self._server_post_branch_03()
        elif self.path == '/api/collection/item/manual_update':
            return self._server_post_branch_04()
        elif self.path in ('/api/collection/control/pause', '/api/collection/control/resume'):
            return self._server_post_branch_05()
        elif self.path in {'/api/collection/auth/recovery/claim', '/api/collection/auth/recovery/snapshot_ready', '/api/collection/auth/recovery/pc2_restarting', '/api/collection/auth/recovery/result'}:
            return self._server_post_branch_06()
        elif self.path == '/api/collection/auth/force_reset':
            return self._server_post_branch_07()
        elif self.path == '/api/collection/auth/complete':
            return self._server_post_branch_08()
        elif self.path == '/api/collection/auth/resume_after_cooldown':
            return self._server_post_branch_09()
        elif self.path in MANUAL_REVIEW_RECEIPT_ENDPOINTS:
            return self._server_post_branch_10()
        elif self.path in ('/api/avm/run', '/api/analysis/pipeline/run'):
            return self._server_post_branch_11()
        elif self.path in ('/api/avm/evaluate', '/api/analysis/evaluate'):
            return self._server_post_branch_12()
        elif self.path in ('/api/avm/recent_enrich_maintenance', '/api/collection/details/maintenance'):
            return self._server_post_branch_13()
        elif self.path in ('/api/avm/fetch_missing_detail_archives', '/api/collection/details/fetch_missing'):
            return self._server_post_branch_14()
        elif self.path in ('/api/avm/archive_detail_replay', '/api/collection/details/prepare_replay'):
            return self._server_post_branch_15()
        elif self.path == '/api/avm/start_all_subtasks':
            return self._server_post_branch_16()
        elif self.path == '/api/avm/run_all_subtasks_sync':
            return self._server_post_branch_17()
        elif self.path == '/api/save_locations':
            return self._server_post_branch_18()
        elif self.path in ('/api/area_result', '/api/collection/details/area_result'):
            return self._server_post_branch_19()
        elif self.path in ('/api/infer_location', '/api/collection/details/infer_location'):
            return self._server_post_branch_20()
        elif self.path in ('/api/approve_area', '/api/collection/details/approve_area'):
            return self._server_post_branch_21()
        elif self.path in ('/api/save', '/api/collection/seeds/batch'):
            return self._server_post_branch_22()
        elif self.path == '/api/avm/screen':
            return self._server_post_branch_23()
        elif self.path in ('/api/report_captcha', '/api/report_manual_captcha'):
            return self._server_post_branch_24()
        elif self.path == '/api/log':
            return self._server_post_branch_25()
        elif self.path.startswith('/api/upload'):
            return self._server_post_branch_26()
        elif self.path in ('/api/update_item', '/api/collection/details/update_item'):
            return self._server_post_branch_27()
        elif self.path == '/api/get_next_task':
            return self._server_post_branch_28()
        elif self.path in ('/api/analyze_html', '/api/collection/details/html'):
            return self._server_post_branch_29()
        else:
            return self._server_post_fallback()

    def do_DELETE(self):
        global LAST_REQUEST_TIME
        LAST_REQUEST_TIME = time.time()
        if self.path in MANUAL_REVIEW_RECEIPT_ENDPOINTS:
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
            (valid, error_payload) = _validate_manual_review_receipt_delete_payload(payload if isinstance(payload, dict) else {})
            if not valid:
                self.send_error_json(status=400, code=error_payload['code'], message=error_payload['message'], details=error_payload.get('details', {}))
                return
            active_data_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
            try:
                result = delete_manual_review_receipt(_manual_review_receipt_store_path(active_data_root), action=str(payload['action']), ready_signal=str(payload['ready_signal']), repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None)
                append_manual_review_receipt_operation(_manual_review_receipt_operations_path(active_data_root), operation='deleted', receipt={'action': payload['action'], 'ready_signal': payload['ready_signal'], 'status': '', 'payload': {}}, execution_mode='delete', deleted=bool(result['deleted']), repository=DB_REPOSITORY if DB_REPOSITORY.enabled else None)
                context = _manual_review_receipt_context(active_data_root)
                self.send_json({'status': 'ok', 'deleted': result['deleted'], 'receipt_count': result['receipt_count'], 'manual_review_receipt_summary': context['manual_review_receipt_summary'], 'manual_review_receipt_jobs_summary': context['manual_review_receipt_jobs_summary'], 'manual_review_control_plane_storage': context['manual_review_control_plane_storage'], 'manual_review_control_plane_backup': context['manual_review_control_plane_backup'], 'manual_review_control_plane_backup_repairs_summary': context['manual_review_control_plane_backup_repairs_summary'], 'manual_review_control_plane_integrity': context['manual_review_control_plane_integrity'], 'manual_review_control_plane_integrity_history_summary': context['manual_review_control_plane_integrity_history_summary'], 'manual_review_control_plane_stability': context['manual_review_control_plane_stability'], 'manual_review_control_plane_guidance': context['manual_review_control_plane_guidance'], 'operator_overview': context['operator_overview']})
            except Exception as e:
                self.send_error_json(status=500, code='AVM_MANUAL_REVIEW_RECEIPT_DELETE_FAILED', message='manual review receipt 删除失败', details={'error': str(e)})
            return
        request_path = urlparse(self.path).path
        if request_path.startswith('/api/'):
            self.send_error_json(status=404, code='AVM_ENDPOINT_NOT_FOUND', message='未找到接口', details={'path': request_path})
        else:
            self.send_response(404)
            self.end_headers()

    def _source_contract_end(self):
        return None


for _method_name in ['_server_get_branch_01', '_server_get_branch_02', '_server_get_branch_03', '_server_get_branch_04', '_server_get_branch_05', '_server_get_branch_06', '_server_get_branch_07', '_server_get_branch_08', '_server_get_branch_09', '_server_get_branch_10', '_server_get_branch_11', '_server_get_branch_12', '_server_get_branch_13', '_server_get_branch_14', '_server_get_branch_15', '_server_get_branch_16', '_server_get_branch_17', '_server_get_branch_18', '_server_get_branch_19', '_server_get_branch_20', '_server_get_branch_21', '_server_get_branch_22', '_server_get_branch_23', '_server_get_branch_24', '_server_get_branch_25', '_server_get_branch_26', '_server_get_branch_27', '_server_get_branch_28', '_server_get_branch_29', '_server_get_branch_30', '_server_get_branch_31', '_server_get_branch_32', '_server_get_fallback', '_server_post_branch_01', '_server_post_branch_02', '_server_post_branch_03', '_server_post_branch_04', '_server_post_branch_05', '_server_post_branch_06', '_server_post_branch_07', '_server_post_branch_08', '_server_post_branch_09', '_server_post_branch_10', '_server_post_branch_11', '_server_post_branch_12', '_server_post_branch_13', '_server_post_branch_14', '_server_post_branch_15', '_server_post_branch_16', '_server_post_branch_17', '_server_post_branch_18', '_server_post_branch_19', '_server_post_branch_20', '_server_post_branch_21', '_server_post_branch_22', '_server_post_branch_23', '_server_post_branch_24', '_server_post_branch_25', '_server_post_branch_26', '_server_post_branch_27', '_server_post_branch_28', '_server_post_branch_29', '_server_post_fallback', 'send_json', 'send_error_json', 'send_invalid_request_body', 'update_file', 'run_solver', 'log_message']:
    _method = globals()[_method_name]
    _method.__qualname__ = f"DataHandler.{_method_name}"
    setattr(DataHandler, _method_name, _method)


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


if __name__ == '__main__':
    print(f'Starting Data Receiver on port {PORT}...')
    print(f'Serving Pending Tasks from: {os.path.abspath(DATA_DIR)}')
    initialize_runtime(start_watchdog=True, ensure_browser=True)
    AVM_CONFIG_MANAGER.load_on_startup()
    AVM_CONFIG_MANAGER.start_hot_reload_watcher()
    print(f'[AVM-CONFIG] Active config: {AVM_CONFIG_MANAGER.get_config()}')
    import threading
    threading.Thread(target=background_file_processor, daemon=True).start()
    threading.Thread(target=auto_tuner_thread, daemon=True).start()
    try:
        with ReusableTCPServer(('', PORT), DataHandler) as httpd:
            print('Server running. Press Ctrl+C to stop.')
            try:
                httpd.serve_forever()
            except KeyboardInterrupt:
                print('\nServer stopped by user.')
            except Exception as e:
                print(f'\nServer crashed: {e}')
                import traceback
                traceback.print_exc()
    except OSError as e:
        print(f'Error binding to port {PORT}: {e}')
