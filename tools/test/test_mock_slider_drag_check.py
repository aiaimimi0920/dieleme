from __future__ import annotations

import pytest


@pytest.mark.parametrize(
    ("scenario", "target"),
    [
        ("default", "local_mock_slider"),
        ("strict_success_text", "local_mock_slider_strict_success_text"),
        ("wide_delay", "local_mock_slider_wide_delay"),
        ("teardown_only", "local_mock_slider_teardown_only"),
    ],
)
def test_local_mock_slider_drag_reaches_success(scenario: str, target: str) -> None:
    from tools.mock_slider_drag_check import run_mock_slider_drag_check

    summary = run_mock_slider_drag_check(headless=True, scenario=scenario)

    assert summary["success"] is True
    assert summary["final_ratio"] >= 0.98
    assert summary["event_counts"]["mouse_down"] >= 1
    assert summary["event_counts"]["mouse_move"] >= 5
    assert summary["event_counts"]["mouse_up"] >= 1
    assert summary["target"] == target
    assert summary["scenario"] == scenario
    assert summary["resolved_as_expected"] is True


def test_local_mock_slider_drag_handles_expected_explicit_failure() -> None:
    from tools.mock_slider_drag_check import run_mock_slider_drag_check

    summary = run_mock_slider_drag_check(headless=True, scenario="explicit_fail")

    assert summary["success"] is False
    assert summary["failure"] is True
    assert summary["resolution"] == "failure"
    assert summary["status_text"] == "验证失败，点击框体重试(error:KzCFR9)"
    assert summary["resolved_as_expected"] is True


def test_local_mock_slider_drag_handles_retry_then_success_first_drag_failure() -> None:
    from tools.mock_slider_drag_check import run_mock_slider_drag_check

    summary = run_mock_slider_drag_check(headless=True, scenario="retry_then_success")

    assert summary["success"] is False
    assert summary["failure"] is True
    assert summary["resolution"] == "failure"
    assert summary["status_text"] == "验证失败，点击框体重试(error:KzCFR9)"
    assert summary["resolved_as_expected"] is True


def test_local_mock_slider_drag_handles_expected_near_miss_failure() -> None:
    from tools.mock_slider_drag_check import run_mock_slider_drag_check

    summary = run_mock_slider_drag_check(headless=True, scenario="near_miss")

    assert summary["success"] is False
    assert summary["failure"] is True
    assert summary["resolution"] == "failure"
    assert summary["status_text"] == "拖动未达标，请重新拖动"
    assert summary["resolved_as_expected"] is True
