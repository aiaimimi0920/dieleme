"""Protected, metadata-only client for an explicitly configured NAS auth endpoint."""
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request


class RecoveryError(RuntimeError):
    pass


def api_origin(value):
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise RecoveryError("invalid_api")
    if parsed.query or parsed.fragment or parsed.path.rstrip("/") not in {"", "/api"}:
        raise RecoveryError("invalid_api")
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RecoveryError("redirect_refused")


class RecoveryClient:
    def __init__(self, api_base, data_root, *, environment=None):
        environment = os.environ if environment is None else environment
        configured = environment.get("FAPAI_COLLECTOR_API_BASE") or environment.get("FAPAI_API_BASE_URL") or "http://192.168.15.200:8001"
        if api_origin(api_base) != api_origin(configured):
            raise RecoveryError("api_not_configured")
        self.url = api_origin(api_base) + "/api/collection/auth/recovery"
        token_path = Path(environment.get("FAPAI_NAS_AUTH_RECOVERY_TOKEN_FILE") or data_root / "secrets" / "nas-auth-recovery.token")
        try:
            token = token_path.read_text(encoding="utf-8").strip()
        except OSError as error:
            raise RecoveryError("token_unavailable") from error
        if not 16 <= len(token) <= 4096 or any(char.isspace() for char in token):
            raise RecoveryError("token_unavailable")
        self.headers = {"X-Fapai-Recovery-Token": token, "Content-Type": "application/json"}
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def call(self, path="", body=None):
        request = urllib.request.Request(self.url + path, headers=self.headers,
                                        data=None if body is None else json.dumps(body).encode())
        try:
            with self.opener.open(request, timeout=20) as response:
                raw = response.read(65537)
            if len(raw) > 65536:
                raise RecoveryError("invalid_response")
            value = json.loads(raw)
        except urllib.error.HTTPError as error:
            raise RecoveryError({403: "token_rejected", 404: "api_upgrade_required", 409: "challenge_changed",
                                 412: "pc2_stage_upgrade_required", 423: "handoff_busy"}.get(error.code, "api_unavailable")) from error
        except (OSError, ValueError, urllib.error.URLError) as error:
            raise RecoveryError("api_unavailable") from error
        if not isinstance(value, dict) or value.get("ok") is not True:
            raise RecoveryError("request_rejected")
        return value


def recovery_phase(snapshot, recovery_id, *, scope=""):
    active = snapshot.get("active") or {}
    last = snapshot.get("last_result") or {}
    matched = active if active.get("recovery_id") == recovery_id else last
    if scope and matched.get("scope") != scope:
        return {"phase": "failed", "code": "challenge_changed", "recovery_id": recovery_id}
    if active.get("recovery_id") == recovery_id:
        stages = {
            "requested": "existing_recovery", "pc1_claimed": "existing_recovery",
            "snapshot_ready": "pc2_receiving", "pc2_claimed": "pc2_importing",
            "restarting": "pc2_restarting", "verifying": "pc2_verifying",
        }
        code = stages.get(active.get("status"))
        if scope and active.get("status") == "restarting":
            code = "pc2_stage_verifying"
        if code is None:
            return {"phase": "unavailable", "code": "invalid_response", "recovery_id": recovery_id}
        return {"phase": "pending_pc2", "recovery_id": recovery_id,
                "code": code}
    if last.get("recovery_id") == recovery_id:
        failures = {
            "snapshot_ready_timeout": "pc2_receive_timeout",
            "pc2_claimed_timeout": "pc2_import_timeout",
            "restarting_timeout": "pc2_restart_timeout",
            "verifying_timeout": "pc2_progress_timeout",
            "operator_pause_active": "operator_pause_active",
            "stage_probe_failed": "stage_probe_failed",
            "stage_probe_unavailable": "stage_probe_unavailable",
            "challenge_changed": "challenge_changed",
        }
        code = "recovery_finished" if last.get("status") == "succeeded" else failures.get(last.get("reason"), "recovery_finished")
        return {"phase": "succeeded" if last.get("status") == "succeeded" else "failed",
                "recovery_id": recovery_id, "code": code}
    return {"phase": "failed", "code": "challenge_changed", "recovery_id": recovery_id}
