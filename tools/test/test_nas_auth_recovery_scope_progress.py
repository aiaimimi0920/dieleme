from __future__ import annotations

import pytest

from src.nas_auth_recovery import NasAuthRecoveryCoordinator


@pytest.mark.parametrize("blocked_scopes", [("seed",), ("detail",), ("seed", "detail"), ()])
def test_global_handoff_does_not_finish_while_any_collection_scope_is_blocked(tmp_path, blocked_scopes):
    coordinator = NasAuthRecoveryCoordinator(tmp_path / "recovery.json", stall_seconds=1, cooldown_seconds=0)
    coordinator.sample(100, 20, now=100)
    requested = coordinator.sample(100, 20, now=102, blocked_scopes=("seed", "detail"))
    recovery_id = requested["active"]["recovery_id"]
    assert coordinator.claim("pc1", recovery_id, "pc1", now=103)["ok"]

    result = coordinator.sample(101, 20, now=104, blocked_scopes=blocked_scopes)

    if blocked_scopes:
        assert result["active"]["recovery_id"] == recovery_id
        assert result["active"]["status"] == "pc1_claimed"
        assert result["last_result"] is None
    else:
        assert result["active"] is None
        assert result["last_result"]["status"] == "succeeded"
