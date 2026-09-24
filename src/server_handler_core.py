from __future__ import annotations

import logging

from .server_context import *  # noqa: F401,F403
from .solver_execution_state import SolverExecution

logger = logging.getLogger(__name__)

def _write_json_response(self, status, payload):
    try:
        raw = json.dumps(payload).encode('utf-8')
        self.send_response(status)
        _apply_cors_headers(self)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(raw)))
        if status == 405:
            self.send_header('Allow', 'POST')
        self.end_headers()
        self.wfile.write(raw)
    except Exception as error:
        if _is_client_disconnect_error(error):
            return
        raise

def send_json(self, data):
    if urlparse(self.path).path == '/api/status' and isinstance(data, dict):
        authorized, _error = _verify_node_auth_token(self.headers)
        if not authorized and 'auth_recovery' in data:
            data = {**data, 'auth_recovery': _public_auth_recovery_snapshot(data['auth_recovery'])}
    _write_json_response(self, 200, data)

def _redact_error_details(status, code, details):
    import logging
    import uuid

    """5xx bodies carry an error_id instead of exception text unless details exposure is enabled."""
    details = dict(details or {})
    if int(status) < 500 or _env_flag('FAPAI_EXPOSE_ERROR_DETAILS', '0'):
        return details
    error_text = details.pop('error', None)
    if error_text is None:
        return details
    error_id = uuid.uuid4().hex[:16]
    logging.getLogger(__name__).error('%s error_id=%s: %s', code, error_id, error_text)
    details['error_id'] = error_id
    return details

def send_error_json(self, status, code, message, details=None):
    payload = {'error': {'code': code, 'message': message, 'details': _redact_error_details(status, code, details)}}
    _write_json_response(self, status, payload)

def send_invalid_request_body(self, payload):
    self.send_error_json(status=400, code='AVM_INVALID_REQUEST_BODY', message='请求体必须是 JSON 对象', details={'expected_type': 'object', 'received_type': _json_payload_type_name(payload)})

def update_file(self, file_path, item_id, new_data):
    update_file_global(file_path, item_id, new_data)

def _solver_execution_is_current(execution: SolverExecution) -> bool:
    with RUNTIME.lock:
        return RUNTIME.solver.owns(execution) and RUNTIME.solver.started_at == execution.started_at

def _solver_execution_resumed(execution: SolverExecution) -> bool:
    with RUNTIME.lock:
        return RUNTIME.recovery.snapshot().resume_epoch != execution.resume_epoch

def _solver_execution_cancelled(execution: SolverExecution) -> bool:
    with RUNTIME.lock:
        return (
            not _solver_execution_is_current(execution)
            or execution.cancelled.is_set()
            or _solver_execution_resumed(execution)
            or RUNTIME.recovery.snapshot().cancel_epoch != execution.cancel_epoch
        )

def _wait_for_solver_manual_poll(execution: SolverExecution, deadline: float) -> bool:
    end = min(deadline, time.monotonic() + 2)
    while time.monotonic() < end:
        with RUNTIME.lock:
            if not _solver_execution_is_current(execution) or _solver_execution_resumed(execution):
                return False
        if execution.superseded.wait(min(0.1, max(0.0, end - time.monotonic()))):
            return False
    return time.monotonic() < deadline

def run_solver(self, solver_request=None, submission_token=None):
    """Run the captcha solver in background with server-level retry."""
    with RUNTIME.lock:
        preflight_execution = RUNTIME.solver.current
        preflight_pending = RUNTIME.solver.pending_token
    solver_scope = _challenge_scope_for_request(solver_request)
    solver_status_snapshot = _captcha_solver_runtime_status()
    scoped_snapshot = _solver_scope_runtime_status(solver_scope) if solver_scope in CHALLENGE_SCOPES else {}
    if solver_scope in CHALLENGE_SCOPES and scoped_snapshot.get('challenge_id'):
        scope_requires_manual = bool(scoped_snapshot.get('manual_required'))
    elif solver_scope in CHALLENGE_SCOPES:
        latest_scope = _challenge_scope_for_request(RUNTIME.recovery.snapshot().last_request)
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
            import logging

            logging.getLogger(__name__).exception('[SOLVER] Stale auth-lock preflight failed')
        if already_authenticated:
            with RUNTIME.lock:
                if RUNTIME.solver.current is preflight_execution and RUNTIME.solver.pending_token is preflight_pending:
                    logger.info('[SOLVER] Page already authenticated; clearing stale captcha auth lock.')
                    _clear_auth_lock_after_solver_success(scope=solver_scope or None)
            _release_solver_submission(submission_token)
            return
        _release_solver_submission(submission_token)
        logger.warning('[SOLVER] Manual verification already required. Skipping solver run.')
        return
    with RUNTIME.lock:
        (activated, activation_reason, activation_value) = _activate_solver_submission(solver_request, submission_token)
        execution = RUNTIME.solver.current
    if not activated:
        if activation_reason == 'solver_running':
            logger.info('[SOLVER] Solver already running for %ss. Skipping duplicate submission.', int(activation_value))
        else:
            logger.info('[SOLVER] Skipping %s solver submission.', activation_reason)
        return
    SERVER_MAX_ATTEMPTS = 2
    solver_started_at = activation_value
    solver_deadline = time.monotonic() + _solver_max_runtime_seconds()

    def wait_for_window(seconds):
        end = min(solver_deadline, time.monotonic() + seconds)
        while time.monotonic() < end:
            if _solver_execution_cancelled(execution):
                return False
            execution.cancelled.wait(min(0.1, max(0.0, end - time.monotonic())))
        return time.monotonic() < solver_deadline

    try:
        with RUNTIME.lock:
            if _solver_execution_cancelled(execution):
                return
            control = RUNTIME.control.snapshot()
            if not control.paused or control.reason is None:
                _set_collection_pause_state(True, 'captcha_solver', scope=solver_scope or None)
        worker_quiesce_seconds = _solver_worker_quiesce_seconds()
        if worker_quiesce_seconds > 0:
            logger.info('[SOLVER] Waiting %ss for node workers to release the shared CDP browser.', worker_quiesce_seconds)
            if not wait_for_window(worker_quiesce_seconds):
                with RUNTIME.lock:
                    if not _solver_execution_cancelled(execution):
                        _mark_solver_manual_required(scope=solver_scope or None)
                        RUNTIME.solver.record_outcome('manual_required', 'deadline_exceeded', execution=execution)
                return
        if not _wait_for_solver_cdp_ready(solver_request, deadline=solver_deadline,
                                         cancel_checker=lambda: _solver_execution_cancelled(execution)):
            with RUNTIME.lock:
                if _solver_execution_cancelled(execution):
                    return
                logger.warning('[SOLVER] Deferring solve attempt because the node CDP browser is unavailable.')
                _mark_solver_manual_required(scope=solver_scope or None)
                failure_reason = 'deadline_exceeded' if time.monotonic() >= solver_deadline else 'cdp_unavailable'
                RUNTIME.solver.record_outcome('manual_required', failure_reason, execution=execution)
            return
        logger.info('[SOLVER] Starting solver...')
        active_solver = _build_solver_for_request(solver_request)
        active_solver.solve_deadline = solver_deadline
        try:
            active_solver.cancel_checker = lambda: _solver_execution_cancelled(execution)
        except Exception:
            pass
        if solver_request:
            logger.info('[SOLVER] Using request-scoped solver cdp_endpoint=%r target_url_set=%s', solver_request.get('cdp_endpoint'), bool(solver_request.get('target_url')))
        success = False
        for server_attempt in range(SERVER_MAX_ATTEMPTS):
            if _solver_execution_cancelled(execution):
                break
            if time.monotonic() >= solver_deadline:
                active_solver.last_failure_reason = 'deadline_exceeded'
                break
            if server_attempt > 0:
                logger.info('[SOLVER] Server retry %s/%s after delay...', server_attempt + 1, SERVER_MAX_ATTEMPTS)
                if not wait_for_window(3):
                    active_solver.last_failure_reason = 'deadline_exceeded' if time.monotonic() >= solver_deadline else 'cancelled'
                    break
            success = active_solver.solve()
            if success:
                break
            if getattr(active_solver, 'last_failure_reason', None) in {'manual_required', 'cancelled', 'deadline_exceeded'}:
                logger.warning('[SOLVER] Manual-required/cancelled failure detected; skipping server retry.')
                break
        with RUNTIME.lock:
            if not _solver_execution_is_current(execution):
                return
            if _solver_execution_resumed(execution):
                logger.info('[SOLVER] Manual resume happened after this solver started; suppressing stale failure pause.')
                RUNTIME.solver.record_outcome('resumed', execution=execution)
                _set_collection_pause_state(False, scope=solver_scope or None)
                return
            if _solver_execution_cancelled(execution):
                return
            if success:
                logger.info('[SOLVER] Captcha solved; resuming system.')
                _clear_auth_lock_after_solver_success(scope=solver_scope or None)
                return
            failure_reason = getattr(active_solver, 'last_failure_reason', None) or 'solve_failed'
            failure_status = 'manual_required' if failure_reason == 'manual_required' else 'failed'
            RUNTIME.solver.record_outcome(failure_status, failure_reason, execution=execution)
            logger.error('[SOLVER] All solve attempts failed. System remains paused.')
            logger.warning("[SOLVER] Manual intervention required. Please solve in Edge, then click 'Resume' or delete 'force_unlock.flag'.")
            flag_error = _mark_solver_manual_required(scope=solver_scope or None)
            flag_path = _solver_force_unlock_flag_path()
            if flag_error:
                logger.error('[SOLVER] Failed to write force unlock flag: %s', flag_error)
            RUNTIME.solver.finish(execution, time.time())

        if not success:
            def _current_solver_scope_manual_required() -> bool:
                if solver_scope not in CHALLENGE_SCOPES:
                    return bool(_captcha_solver_runtime_status().get('manual_required'))
                scoped_status = _solver_scope_runtime_status(solver_scope)
                if scoped_status.get('challenge_id'):
                    return bool(scoped_status.get('manual_required'))
                latest_scope = _challenge_scope_for_request(RUNTIME.recovery.snapshot().last_request)
                if latest_scope in CHALLENGE_SCOPES and latest_scope != solver_scope:
                    return False
                return bool(_captcha_solver_runtime_status().get('manual_required'))
            while _current_solver_scope_manual_required():
                if time.monotonic() >= solver_deadline:
                    # Persisted manual-required state is monitored by the runtime, not this expired worker.
                    break
                with RUNTIME.lock:
                    if not _solver_execution_is_current(execution) or _solver_execution_resumed(execution):
                        break
                    if not os.path.exists(flag_path):
                        logger.info('[SOLVER] Force unlock flag removed; auto-resuming system.')
                        _set_collection_pause_state(False, scope=solver_scope or None)
                        _clear_solver_manual_required_state()
                        challenge_state_error = _clear_solver_challenge_state(solver_scope or None)
                        if challenge_state_error:
                            logger.error('[SOLVER] Failed to clear persisted challenge state after force unlock: %s', challenge_state_error)
                        break
                try:
                    preflight = active_solver._preflight_current_challenge()
                except Exception as error:
                    preflight = {}
                    logger.warning('[SOLVER] Auth-lock recovery preflight failed: %s', error)
                if preflight.get('already_authenticated'):
                    with RUNTIME.lock:
                        if _solver_execution_is_current(execution) and not _solver_execution_resumed(execution):
                            logger.info('[SOLVER] Page authenticated while waiting; clearing captcha auth lock.')
                            _clear_auth_lock_after_solver_success(scope=solver_scope or None)
                    break
                if not _wait_for_solver_manual_poll(execution, solver_deadline):
                    break
    except Exception as e:
        with RUNTIME.lock:
            if not _solver_execution_cancelled(execution):
                RUNTIME.solver.record_outcome('error', str(e), execution=execution)
        logger.exception('[SOLVER] Error: %s', e)
    finally:
        finished_at = time.time()
        with RUNTIME.lock:
            is_current_solver_run = RUNTIME.solver.finish(execution, finished_at)
        if not is_current_solver_run:
            logger.info('[SOLVER] Run was cleared or superseded; leaving current state unchanged.')
        started_for_log = solver_started_at
        elapsed = max(finished_at - started_for_log, 0) if started_for_log > 0 else 0
        logger.info('[SOLVER] Finished. Total time: %.1fs', elapsed)

def log_message(self, format, *args):
    return

__all__ = ["_write_json_response", "_redact_error_details", "send_json", "send_error_json", "send_invalid_request_body", "update_file", "_solver_execution_is_current", "_solver_execution_resumed", "_solver_execution_cancelled", "_wait_for_solver_manual_poll", "run_solver", "log_message"]
