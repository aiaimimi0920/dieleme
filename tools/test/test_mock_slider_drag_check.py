from __future__ import annotations


def test_local_mock_slider_drag_reaches_success() -> None:
    from tools.mock_slider_drag_check import run_mock_slider_drag_check

    summary = run_mock_slider_drag_check(headless=True)

    assert summary["success"] is True
    assert summary["final_ratio"] >= 0.98
    assert summary["event_counts"]["mouse_down"] >= 1
    assert summary["event_counts"]["mouse_move"] >= 5
    assert summary["event_counts"]["mouse_up"] >= 1
    assert summary["target"] == "local_mock_slider"
