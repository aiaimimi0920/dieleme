from __future__ import annotations
from tools.pc2_solver_context import *  # noqa: F401,F403


def _env_flag(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return bool(default)
    return raw.strip().lower() not in {"0", "false", "no", "off"}

def real_taobao_auto_solver_enabled():
    return _env_flag("FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED", False)

def nas_auth_recovery_client_enabled():
    return _env_flag("FAPAI_NAS_AUTH_RECOVERY_CLIENT_ENABLED", False)

def _status_url(api_base: str) -> str:
    return api_base.rstrip("/") + "/status"

def _auth_complete_url(api_base: str) -> str:
    return api_base.rstrip("/") + "/collection/auth/complete"

def _resume_after_cooldown_url(api_base: str) -> str:
    return api_base.rstrip("/") + "/collection/auth/resume_after_cooldown"

def _manual_captcha_report_url(api_base: str) -> str:
    return api_base.rstrip("/") + "/report_manual_captcha"

def _captcha_report_url(api_base: str) -> str:
    return api_base.rstrip("/") + "/report_captcha"

def _force_reset_url(api_base: str) -> str:
    return api_base.rstrip("/") + "/collection/auth/force_reset"

def log_event(event):
    event["ts"] = datetime.datetime.now().isoformat(timespec="seconds")
    line = json.dumps(event, ensure_ascii=False)
    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        print(line.encode("utf-8", errors="replace").decode("utf-8", errors="replace"), flush=True)

def write_solver_heartbeat(phase, **details):
    payload = {
        "pid": os.getpid(),
        "updated_at_epoch": time.time(),
        "phase": str(phase or "unknown"),
        **details,
    }
    temporary_path = SOLVER_HEARTBEAT_PATH.with_name(
        f"{SOLVER_HEARTBEAT_PATH.name}.{os.getpid()}.tmp"
    )
    try:
        SOLVER_HEARTBEAT_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary_path, SOLVER_HEARTBEAT_PATH)
        return True
    except Exception as exc:
        try:
            temporary_path.unlink(missing_ok=True)
        except Exception:
            pass
        log_event({"kind": "local_solver_heartbeat_write_error", "error": repr(exc)})
        return False

def read_solver_status(api_base):
    try:
        payload = fetch_json(_status_url(api_base), timeout=10)
        if not isinstance(payload, dict): return {"error": "non_dict_status_response"}
        solver = payload.get("captcha_solver")
        return dict(solver) if isinstance(solver, dict) else {}
    except Exception as exc: return {"error": repr(exc)}

__all__ = ('_env_flag', 'real_taobao_auto_solver_enabled', 'nas_auth_recovery_client_enabled', '_status_url', '_auth_complete_url', '_resume_after_cooldown_url', '_manual_captcha_report_url', '_captcha_report_url', '_force_reset_url', 'log_event', 'write_solver_heartbeat', 'read_solver_status')
