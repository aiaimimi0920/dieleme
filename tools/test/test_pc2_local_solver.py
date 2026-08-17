from __future__ import annotations

from tools import pc2_local_solver


def test_manual_fallback_is_disabled_by_default(monkeypatch) -> None:
    monkeypatch.delenv("FAPAI_SOLVER_MANUAL_FALLBACK_ENABLED", raising=False)

    assert pc2_local_solver.manual_fallback_enabled() is False
    assert pc2_local_solver._manual_fallback_latch_active(
        {"manual_pushed": True},
        manual_required=True,
    ) is False


def test_manual_fallback_latch_requires_explicit_enable(monkeypatch) -> None:
    monkeypatch.setenv("FAPAI_SOLVER_MANUAL_FALLBACK_ENABLED", "1")

    assert pc2_local_solver.manual_fallback_enabled() is True
    assert pc2_local_solver._manual_fallback_latch_active(
        {"manual_pushed": True},
        manual_required=True,
    ) is True
    assert pc2_local_solver._manual_fallback_latch_active(
        {"manual_pushed": True},
        manual_required=False,
    ) is False
