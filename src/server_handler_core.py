from __future__ import annotations

from .server_context import *  # noqa: F401,F403

def send_json(self, data):
    try:
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))
    except Exception as error:
        if _is_client_disconnect_error(error):
            return
        raise

def send_error_json(self, status, code, message, details=None):
    payload = {'error': {'code': code, 'message': message, 'details': details or {}}}
    try:
        self.send_response(status)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode('utf-8'))
    except Exception as error:
        if _is_client_disconnect_error(error):
            return
        raise

def send_invalid_request_body(self, payload):
    self.send_error_json(status=400, code='AVM_INVALID_REQUEST_BODY', message='请求体必须是 JSON 对象', details={'expected_type': 'object', 'received_type': _json_payload_type_name(payload)})

def update_file(self, file_path, item_id, new_data):
    update_file_global(file_path, item_id, new_data)

def run_solver(self, solver_request=None, submission_token=None):
    """Run the captcha solver in background with server-level retry."""
    global SOLVER_RUNNING, SOLVER_START_TIME, SOLVER_LAST_STATUS, SOLVER_LAST_FAILURE_REASON
    global SOLVER_LAST_FINISHED_TIME, SOLVER_LAST_REQUEST, SOLVER_MANUAL_RESUME_EPOCH
    global SOLVER_CANCEL_EPOCH, COLLECTION_PAUSE_REASON, SOLVER_MANUAL_REQUIRED_EPOCH
    if 'SOLVER_RUNNING' not in globals():
        SOLVER_RUNNING = False
        SOLVER_START_TIME = 0
    solver_scope = _challenge_scope_for_request(solver_request)
    solver_status_snapshot = _captcha_solver_runtime_status()
    scoped_snapshot = _solver_scope_runtime_status(solver_scope) if solver_scope in CHALLENGE_SCOPES else {}
    if solver_scope in CHALLENGE_SCOPES and scoped_snapshot.get('challenge_id'):
        scope_requires_manual = bool(scoped_snapshot.get('manual_required'))
    elif solver_scope in CHALLENGE_SCOPES:
        latest_scope = _challenge_scope_for_request(SOLVER_LAST_REQUEST)
        scope_requires_manual = bool(solver_status_snapshot.get('manual_required') if latest_scope not in CHALLENGE_SCOPES or latest_scope == solver_scope else False)
    else:
        scope_requires_manual = bool(solver_status_snapshot.get('manual_required'))
    if scope_requires_manual:
        already_authenticated = False
        try:
            probe_solver = _build_solver_for_request(solver_request)
            preflight = probe_solver._preflight_current_challenge()
            already_authenticated = bool(preflight.get('already_authenticated'))
        except Exception as error:
            print(f'[SOLVER] Stale auth-lock preflight failed: {error}')
        if already_authenticated:
            print('\x1b[92m[SOLVER] Page already authenticated; clearing stale captcha auth lock.\x1b[0m')
            _clear_auth_lock_after_solver_success(scope=solver_scope or None)
            _release_solver_submission(submission_token)
            return
        _release_solver_submission(submission_token)
        print('\x1b[93m[SOLVER] Manual verification already required. Skipping solver run.\x1b[0m')
        return
    (activated, activation_reason, activation_value) = _activate_solver_submission(solver_request, submission_token)
    if not activated:
        if activation_reason == 'solver_running':
            print(f'\x1b[93m[SOLVER] Solver already running for {int(activation_value)}s. Skipping duplicate submission.\x1b[0m')
        else:
            print(f'[SOLVER] Skipping {activation_reason} solver submission.')
        return
    SERVER_MAX_ATTEMPTS = 2
    solver_started_at = activation_value
    try:
        if not PAUSED or COLLECTION_PAUSE_REASON is None:
            _set_collection_pause_state(True, 'captcha_solver', scope=solver_scope or None)
        worker_quiesce_seconds = _solver_worker_quiesce_seconds()
        if worker_quiesce_seconds > 0:
            print(f'[SOLVER] Waiting {worker_quiesce_seconds}s for node workers to release the shared CDP browser.')
            time.sleep(worker_quiesce_seconds)
        if not _wait_for_solver_cdp_ready(solver_request):
            print('[SOLVER] Deferring solve attempt because the node CDP browser is unavailable.')
            _mark_solver_manual_required(scope=solver_scope or None)
            SOLVER_LAST_FAILURE_REASON = 'cdp_unavailable'
            return
        print('\x1b[93m[SOLVER] Starting solver...\x1b[0m')
        active_solver = _build_solver_for_request(solver_request)
        try:
            active_solver.cancel_checker = lambda : SOLVER_MANUAL_RESUME_EPOCH >= solver_started_at or SOLVER_CANCEL_EPOCH >= solver_started_at
        except Exception:
            pass
        if solver_request:
            print(f"[SOLVER] Using request-scoped solver cdp_endpoint={solver_request.get('cdp_endpoint')!r} target_url_set={bool(solver_request.get('target_url'))}")
        success = False
        for server_attempt in range(SERVER_MAX_ATTEMPTS):
            if server_attempt > 0:
                print(f'\x1b[93m[SOLVER] Server retry {server_attempt + 1}/{SERVER_MAX_ATTEMPTS} after delay...\x1b[0m')
                time.sleep(3)
            success = active_solver.solve()
            if success:
                break
            if getattr(active_solver, 'last_failure_reason', None) in {'manual_required', 'cancelled'}:
                print('[SOLVER] Manual-required/cancelled failure detected; skipping server retry.')
                break
        if success:
            print('\x1b[92m[SOLVER] ✅ Captcha Solved! Resuming system...\x1b[0m')
            _clear_auth_lock_after_solver_success(scope=solver_scope or None)
        else:
            SOLVER_LAST_FAILURE_REASON = getattr(active_solver, 'last_failure_reason', None) or 'solve_failed'
            if SOLVER_MANUAL_RESUME_EPOCH >= solver_started_at:
                print('[SOLVER] Manual resume happened after this solver started; suppressing stale failure pause.')
                SOLVER_LAST_STATUS = 'resumed'
                SOLVER_LAST_FAILURE_REASON = None
                _set_collection_pause_state(False, scope=solver_scope or None)
                SOLVER_RUNNING = False
                SOLVER_LAST_FINISHED_TIME = time.time()
                return
            if SOLVER_CANCEL_EPOCH >= solver_started_at and _captcha_solver_runtime_status().get('manual_required'):
                print('[SOLVER] Solver cancel requested after manual_required was marked; leaving collection paused for operator verification.')
                SOLVER_LAST_STATUS = 'manual_required'
                SOLVER_LAST_FAILURE_REASON = 'manual_required'
                SOLVER_RUNNING = False
                SOLVER_LAST_FINISHED_TIME = time.time()
                return
            if SOLVER_LAST_FAILURE_REASON == 'manual_required':
                SOLVER_LAST_STATUS = 'manual_required'
            else:
                SOLVER_LAST_STATUS = 'failed'
            print('\x1b[91m[SOLVER] ❌ All solve attempts failed. System remains PAUSED.\x1b[0m')
            print("\x1b[91m[SOLVER] Manual intervention required. Please solve in Edge, then click 'Resume' or delete 'force_unlock.flag'.\x1b[0m")
            flag_error = _mark_solver_manual_required(scope=solver_scope or None)
            flag_path = _solver_force_unlock_flag_path()
            if flag_error:
                print(f'[SOLVER] Failed to write force unlock flag: {flag_error}')
            SOLVER_RUNNING = False
            SOLVER_LAST_FINISHED_TIME = time.time()

            def _current_solver_scope_manual_required() -> bool:
                if solver_scope not in CHALLENGE_SCOPES:
                    return bool(_captcha_solver_runtime_status().get('manual_required'))
                scoped_status = _solver_scope_runtime_status(solver_scope)
                if scoped_status.get('challenge_id'):
                    return bool(scoped_status.get('manual_required'))
                latest_scope = _challenge_scope_for_request(SOLVER_LAST_REQUEST)
                if latest_scope in CHALLENGE_SCOPES and latest_scope != solver_scope:
                    return False
                return bool(_captcha_solver_runtime_status().get('manual_required'))
            while _current_solver_scope_manual_required():
                if not os.path.exists(flag_path):
                    print('\x1b[92m[SOLVER] 🟢 Force unlock flag removed! Auto-resuming system...\x1b[0m')
                    _set_collection_pause_state(False, scope=solver_scope or None)
                    _clear_solver_manual_required_state()
                    challenge_state_error = _clear_solver_challenge_state(solver_scope or None)
                    if challenge_state_error:
                        print(f'[SOLVER] Failed to clear persisted challenge state after force unlock: {challenge_state_error}')
                    break
                try:
                    preflight = active_solver._preflight_current_challenge()
                except Exception as error:
                    preflight = {}
                    print(f'[SOLVER] Auth-lock recovery preflight failed: {error}')
                if preflight.get('already_authenticated'):
                    print('\x1b[92m[SOLVER] 🟢 Page authenticated while waiting; clearing captcha auth lock.\x1b[0m')
                    _clear_auth_lock_after_solver_success(scope=solver_scope or None)
                    break
                time.sleep(2)
    except Exception as e:
        SOLVER_LAST_STATUS = 'error'
        SOLVER_LAST_FAILURE_REASON = str(e)
        print(f'[SOLVER] Error: {e}')
        import traceback
        traceback.print_exc()
    finally:
        finished_at = time.time()
        is_current_solver_run = solver_started_at <= 0 or not SOLVER_START_TIME or float(SOLVER_START_TIME) == float(solver_started_at)
        if is_current_solver_run:
            SOLVER_RUNNING = False
            SOLVER_LAST_FINISHED_TIME = finished_at
        else:
            print('[SOLVER] A newer solver run is active; not clearing its running state.')
        started_for_log = solver_started_at or SOLVER_START_TIME
        elapsed = max(finished_at - started_for_log, 0) if started_for_log > 0 else 0
        print(f'[SOLVER] Finished. Total time: {elapsed:.1f}s')

def log_message(self, format, *args):
    return

__all__ = ["send_json", "send_error_json", "send_invalid_request_body", "update_file", "run_solver", "log_message"]
