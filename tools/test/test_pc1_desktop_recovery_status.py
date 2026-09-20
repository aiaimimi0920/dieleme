"""Keep PC2 receipt stages distinct from collection recovery and local polling."""
import pytest

from tools.pc1_desktop_recovery import recovery_phase


@pytest.mark.parametrize(("status", "code"), [
    ("requested", "existing_recovery"), ("pc1_claimed", "existing_recovery"),
    ("snapshot_ready", "pc2_receiving"), ("pc2_claimed", "pc2_importing"),
    ("restarting", "pc2_restarting"), ("verifying", "pc2_verifying"),
])
def test_receipt_stages_are_explicit_but_not_success(status, code):
    snapshot = {"active": {"recovery_id": "fixture", "status": status}}
    assert recovery_phase(snapshot, "fixture") == {
        "phase": "pending_pc2", "code": code, "recovery_id": "fixture",
    }


@pytest.mark.parametrize(("reason", "code"), [
    ("snapshot_ready_timeout", "pc2_receive_timeout"),
    ("pc2_claimed_timeout", "pc2_import_timeout"),
    ("restarting_timeout", "pc2_restart_timeout"),
    ("verifying_timeout", "pc2_progress_timeout"),
    ("operator_pause_active", "operator_pause_active"),
    ("unknown-secret-error", "recovery_finished"),
])
def test_terminal_failure_preserves_safe_stage_without_echoing_unknown_errors(reason, code):
    snapshot = {"last_result": {"recovery_id": "fixture", "status": "failed", "reason": reason}}
    assert recovery_phase(snapshot, "fixture") == {
        "phase": "failed", "code": code, "recovery_id": "fixture",
    }


def test_unknown_active_state_does_not_create_an_unbounded_receiving_state():
    snapshot = {"active": {"recovery_id": "fixture", "status": "future-state"}}
    assert recovery_phase(snapshot, "fixture")["phase"] == "unavailable"


def test_only_matching_completed_recovery_is_success():
    snapshot = {"last_result": {"recovery_id": "fixture", "status": "succeeded"}}
    assert recovery_phase(snapshot, "fixture")["phase"] == "succeeded"
    assert recovery_phase(snapshot, "another")["phase"] == "failed"
