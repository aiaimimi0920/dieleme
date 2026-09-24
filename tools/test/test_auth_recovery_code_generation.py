"""Code generation drift must fail without changing the reviewed contract."""

import sys

import pytest

from scripts import generate_auth_recovery_codes as generator
from src.auth_recovery_codes import FAILURE_CODES, MESSAGES, TIMEOUT_REASONS
from tools.pc1_desktop_recovery import recovery_phase


def test_checked_in_contract_matches_registry():
    assert generator.OUTPUT.read_text(encoding="utf-8") == generator.render_contract()
    assert set(TIMEOUT_REASONS.values()) <= set(FAILURE_CODES)
    assert set(FAILURE_CODES.values()) <= set(MESSAGES)


def test_check_mode_detects_drift_without_overwriting_file(tmp_path, monkeypatch):
    target = tmp_path / "contract.ts"
    target.write_text(generator.render_contract(), encoding="utf-8")
    monkeypatch.setattr(generator, "OUTPUT", target)
    monkeypatch.setattr(sys, "argv", ["generate_auth_recovery_codes.py", "--check"])
    assert generator.main() == 0
    changed = target.read_bytes() + b"// deliberate drift\n"
    target.write_bytes(changed)
    assert generator.main() == 1
    assert target.read_bytes() == changed


@pytest.mark.parametrize("value", [[], {}, None, "unknown-private-diagnostic"])
def test_unknown_wire_codes_never_become_success_or_echo_diagnostics(value):
    active = {"active": {"recovery_id": "test", "status": value}}
    assert recovery_phase(active, "test")["phase"] == "unavailable"
    failed = {
        "last_result": {"recovery_id": "test", "status": "failed", "reason": value}
    }
    assert recovery_phase(failed, "test") == {
        "phase": "failed",
        "code": "recovery_finished",
        "recovery_id": "test",
    }
