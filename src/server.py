from __future__ import annotations

import importlib
import logging
from pathlib import Path
import sys
import threading
import types

logger = logging.getLogger(__name__)


if __package__:
    _PACKAGE = __package__
else:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    _PACKAGE = "src"
_CONTEXT = importlib.import_module(f"{_PACKAGE}.server_context")
_CORE_MODULES = (
    "server_request_guard",
    "server_solver_scope",
    "server_auth_recovery",
    "server_desktop_auth",
    "server_solver_state",
    "server_solver_dispatch",
    "server_auth_cookie",
    "server_collection_status",
    "server_collection_control",
    "server_engine_control",
    "server_collection_settings",
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
        _value = globals()[_name]
        if not isinstance(_value, types.FunctionType):
            continue
        _value = _rebind_function(_value)
        globals()[_name] = _value
        setattr(_CONTEXT, _name, _value)

# Keep the historical patch points used by maintenance scripts and tests while
# the runtime state remains owned by the structured RuntimeState object.
PENDING_TASKS = RUNTIME.collection.pending_tasks
DISPATCHED_TASKS = RUNTIME.collection.dispatched_tasks
DATA_LOCK = threading.RLock()


_route_definitions = importlib.import_module(f"{_PACKAGE}.server_routes")
_route_access = importlib.import_module(f"{_PACKAGE}.server_route_access")
ROUTES = _route_definitions.build_routes(
    {
        **_route_definitions.GET_GROUPS,
        '_get_collection_settings': (_settings_schema.PREFIX,),
        '_get_manual_review_receipts': tuple(MANUAL_REVIEW_RECEIPT_ENDPOINTS),
        '_get_manual_review_jobs': tuple(MANUAL_REVIEW_RECEIPT_JOB_ENDPOINTS),
        '_get_manual_review_operations': tuple(MANUAL_REVIEW_RECEIPT_OPERATION_ENDPOINTS),
        '_get_manual_review_control_status': tuple(MANUAL_REVIEW_CONTROL_PLANE_STATUS_ENDPOINTS),
        '_get_manual_review_backup_repairs': tuple(MANUAL_REVIEW_CONTROL_PLANE_BACKUP_REPAIR_ENDPOINTS),
        '_get_manual_review_integrity_history': tuple(MANUAL_REVIEW_CONTROL_PLANE_INTEGRITY_HISTORY_ENDPOINTS),
    },
    {
        **_route_definitions.POST_GROUPS,
        '_post_manual_review_receipt': tuple(MANUAL_REVIEW_RECEIPT_ENDPOINTS),
        '_post_engine_control': tuple(_engine_control.ROUTES),
        '_post_collection_settings': tuple(_settings_schema.ROLES),
    },
)


class DataHandler(http.server.SimpleHTTPRequestHandler):
    timeout = 30

    def do_HEAD(self):
        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        _apply_cors_headers(self)
        self.send_header('Access-Control-Allow-Methods', 'POST, GET, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, X-FAPAI-Control-Token, X-Fapai-Recovery-Token, X-FAPAI-Collection-Token')
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        request_path = parsed.path
        query = parse_qs(parsed.query)
        if request_path in _route_definitions.RETIRED_GET_ROUTES:
            self.send_error_json(status=405, code='API_METHOD_NOT_ALLOWED', message='This operation requires an authenticated POST', details={'method': 'POST', 'path': _route_definitions.RETIRED_GET_ROUTES[request_path]})
            return
        handler = ROUTES.get(('GET', request_path))
        if handler is not None:
            return getattr(self, handler)(parsed, request_path, query)
        if request_path.startswith('/collection/') or request_path.startswith('/assets/'):
            return self._get_collection_asset(parsed, request_path, query)
        if request_path.startswith('/api/collection/items/'):
            return self._get_collection_item(parsed, request_path, query)
        if request_path.startswith('/api/'):
            return self._get_api_not_found(parsed, request_path, query)
        return self._server_get_fallback(parsed, request_path, query)

    def do_POST(self):
        request_path = urlparse(self.path).path
        handler = ROUTES.get(('POST', request_path))
        if handler is not None:
            if not self._authorize_write(handler, request_path):
                return
            return getattr(self, handler)()
        return self._server_post_fallback()

    def _authorize_write(self, handler, request_path):
        access = _route_access.required_access('POST', handler)
        if access == 'worker':
            return _require_collection_worker(self)
        if access == 'node':
            return _require_node_auth(self)
        if access == 'recovery':
            authorized, _error = _nas_auth_recovery_authorized(self.headers)
            if not authorized:
                _send_guard_error(self, {'status': 403, 'code': 'COLLECTION_AUTH_RECOVERY_FORBIDDEN', 'message': 'Authentication recovery authorization rejected', 'details': {}})
            return authorized
        if access in {'engine', 'settings'}:
            role = _settings_schema.ROLES.get(request_path) if access == 'settings' else ('operator' if request_path == _engine_control.PREFIX else 'agent')
            try:
                _engine_control.authorize(self.headers, role)
            except _engine_control.RestartError as error:
                code = 'SETTINGS_REJECTED' if access == 'settings' else 'ENGINE_RESTART_REJECTED'
                _send_guard_error(self, {'status': error.status, 'code': code, 'message': str(error), 'details': {}})
                return False
            return True
        return _require_control_plane(self)

    def _post_collection_start(self):
        if not _require_control_plane(self):
            return
        accepted, _payload = _read_json_body(self)
        if accepted:
            self.send_json(_collection_operator_start())

    def _post_desktop_auth_request(self):
        return _server_desktop_auth_request(self)

    def _get_collection_settings(self, parsed, request_path, query):
        return _server_collection_settings(self, read=True)

    def _post_engine_control(self):
        return _server_engine_control(self)

    def _post_collection_settings(self):
        return _server_collection_settings(self)

    def _enqueue_collection_job(
        self,
        operation,
        work,
        failure_code,
        *,
        job_id=None,
        response_status=202,
        response_extra=None,
    ):
        from src.collection_jobs import JobQueueFull

        active_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
        try:
            job = self.server.collection_jobs(active_root).submit(
                operation,
                work,
                failure_code,
                job_id=job_id,
            )
        except JobQueueFull:
            self.send_error_json(status=503, code='COLLECTION_JOB_QUEUE_FULL', message='Collection operation queue is unavailable')
            return
        except Exception as error:
            self.send_error_json(status=503, code='COLLECTION_JOB_SUBMISSION_FAILED', message='Unable to persist collection job', details={'error': str(error)})
            return
        response = {
            'status': 'accepted', 'job_id': job['job_id'], 'job_status': job['status'],
            'status_url': '/api/collection/jobs?id=' + job['job_id'],
        }
        if response_extra:
            response.update(dict(response_extra))
        _write_json_response(self, response_status, response)

    def _submit_maintenance_job(self, operation, failure_code):
        from src.collection_maintenance_jobs import prepare_maintenance

        if not _require_control_plane(self):
            return
        accepted, payload = _read_json_body(self)
        if not accepted:
            return
        active_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
        try:
            work = prepare_maintenance(operation, payload, active_root, _detail_collection_service(active_root), load_data)
        except Exception as error:
            self.send_error_json(status=500, code=failure_code, message='Unable to prepare collection operation', details={'error': str(error)})
            return
        self._enqueue_collection_job(operation, work, failure_code)

    def _submit_pipeline_job(self, config, failure_code):
        pipeline = AVM_PIPELINE

        def run():
            result = pipeline.run(async_mode=False, config=config)
            if result.get('status') != 'completed':
                raise RuntimeError('Pipeline did not complete this request; inspect the pipeline log')
            return result

        self._enqueue_collection_job('pipeline', run, failure_code)

    def _get_collection_job(self, parsed, request_path, query):
        if not _require_control_plane(self):
            return
        job_id = query.get('id', [''])[0]
        if re.fullmatch(r'[a-f0-9]{32}', job_id) is None:
            self.send_error_json(status=400, code='COLLECTION_JOB_INVALID_ID', message='A valid collection job ID is required')
            return
        active_root = Path(getattr(AVM_SERVICE, 'data_dir', DATA_DIR))
        try:
            job = self.server.collection_jobs(active_root).get(job_id)
        except Exception as error:
            self.send_error_json(status=503, code='COLLECTION_JOB_STATE_UNAVAILABLE', message='Collection job receipt is unavailable', details={'error': str(error)})
            return
        if job is None:
            self.send_error_json(status=404, code='COLLECTION_JOB_NOT_FOUND', message='Collection job was not found')
            return
        self.send_json(job)

    def do_DELETE(self):
        request_path = urlparse(self.path).path
        if request_path in MANUAL_REVIEW_RECEIPT_ENDPOINTS:
            if not _require_control_plane(self):
                return
            (accepted, payload) = _read_json_body(self)
            if not accepted:
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
        if request_path.startswith('/api/'):
            self.send_error_json(status=404, code='AVM_ENDPOINT_NOT_FOUND', message='未找到接口', details={'path': request_path})
        else:
            self.send_response(404)
            self.end_headers()

    def _source_contract_end(self):
        return None


_method_names = set(ROUTES.values()) | {
    '_get_collection_asset', '_get_api_not_found', '_server_get_fallback', '_server_post_fallback',
    'send_json', 'send_error_json', 'send_invalid_request_body', 'update_file', 'run_solver', 'log_message',
}
for _method_name in sorted(_method_names):
    if _method_name in DataHandler.__dict__:
        continue
    _method = globals()[_method_name]
    _method.__qualname__ = f"DataHandler.{_method_name}"
    setattr(DataHandler, _method_name, _method)


from src.collection_http_server import CollectionHTTPServer, tls_context_from_env


class ReusableTCPServer(CollectionHTTPServer):
    allow_reuse_address = True


if __name__ == '__main__':
    _listener_tls = tls_context_from_env(os.environ)
    print(f'Starting Data Receiver on port {PORT}...')
    print(f'Serving Pending Tasks from: {os.path.abspath(DATA_DIR)}')
    initialize_runtime()
    AVM_CONFIG_MANAGER.load_on_startup()
    AVM_CONFIG_MANAGER.start_hot_reload_watcher()
    print(f'[AVM-CONFIG] Active config: {AVM_CONFIG_MANAGER.get_config()}')
    import threading
    threading.Thread(target=background_file_processor, daemon=True).start()
    threading.Thread(target=auto_tuner_thread, daemon=True).start()
    try:
        with ReusableTCPServer(('', PORT), DataHandler, tls=_listener_tls) as httpd:
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
