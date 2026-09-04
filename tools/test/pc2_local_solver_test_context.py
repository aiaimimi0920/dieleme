from __future__ import annotations

import json

import pytest

from tools import pc2_local_solver

def _confirmed_auth_payload(completion_id: str) -> dict[str, object]:
    return {
        "ok": True,
        "auth_state_confirmed": True,
        "completion_id": completion_id,
        "paused": False,
        "captcha_solver": {
            "manual_required": False,
            "force_unlock_flag_exists": False,
            "paused": False,
        },
    }

def _confirmed_resume_payload(
    request_id: str,
    *,
    target_url: str | None = None,
) -> dict[str, object]:
    captcha_solver: dict[str, object] = {
        "manual_required": False,
        "force_unlock_flag_exists": False,
        "paused": False,
    }
    if target_url:
        captcha_solver["last_request"] = {"target_url": target_url}
    return {
        "ok": True,
        "action": "resume_after_cooldown",
        "auth_state_confirmed": True,
        "resume_request_id": request_id,
        "paused": False,
        "captcha_solver": captcha_solver,
    }

__all__ = [name for name in globals() if not name.startswith("__")]
