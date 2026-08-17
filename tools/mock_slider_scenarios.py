from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HTML = REPO_ROOT / "tools" / "mock_slider.html"
DEFAULT_SCENARIO = "default"

SCENARIOS: dict[str, dict[str, int | float | str]] = {
    "default": {},
    "strict_success_text": {
        "target": "local_mock_slider_strict_success_text",
        "verifyMode": "strict_success_text",
    },
    "narrow_handle": {
        "target": "local_mock_slider_narrow_handle",
        "trackWidth": 360,
        "handleWidth": 44,
        "handleHeight": 44,
        "trackHeight": 52,
        "verifyMode": "strict_success_text",
    },
    "wide_delay": {
        "target": "local_mock_slider_wide_delay",
        "trackWidth": 520,
        "handleWidth": 34,
        "handleHeight": 34,
        "successDelayMs": 900,
        "verifyMode": "strict_success_text",
    },
    "tight_threshold": {
        "target": "local_mock_slider_tight_threshold",
        "trackWidth": 460,
        "handleWidth": 40,
        "handleHeight": 40,
        "successDelayMs": 250,
        "successThreshold": 0.995,
        "verifyMode": "strict_success_text",
    },
    "teardown_only": {
        "target": "local_mock_slider_teardown_only",
        "trackWidth": 420,
        "handleWidth": 38,
        "handleHeight": 38,
        "successDelayMs": 200,
        "verifyMode": "teardown_only",
        "teardownOnSuccess": "1",
    },
    "explicit_fail": {
        "target": "local_mock_slider_explicit_fail",
        "trackWidth": 420,
        "handleWidth": 38,
        "handleHeight": 38,
        "successDelayMs": 120,
        "verifyMode": "explicit_fail",
    },
    "retry_then_success": {
        "target": "local_mock_slider_retry_then_success",
        "trackWidth": 420,
        "handleWidth": 38,
        "handleHeight": 38,
        "successDelayMs": 120,
        "verifyMode": "retry_then_success",
        "retryResetOnClick": "1",
        "failuresBeforeSuccess": 1,
    },
    "near_miss": {
        "target": "local_mock_slider_near_miss",
        "trackWidth": 420,
        "handleWidth": 38,
        "handleHeight": 38,
        "successDelayMs": 120,
        "verifyMode": "near_miss",
        "failureText": "拖动未达标，请重新拖动",
    },
}

SCENARIO_EXPECTATIONS: dict[str, dict[str, str | bool]] = {
    "default": {"harness_resolution": "success", "solver_success": True, "solver_reason": "OK"},
    "strict_success_text": {"harness_resolution": "success", "solver_success": True, "solver_reason": "OK"},
    "narrow_handle": {"harness_resolution": "success", "solver_success": True, "solver_reason": "OK"},
    "wide_delay": {"harness_resolution": "success", "solver_success": True, "solver_reason": "OK"},
    "tight_threshold": {"harness_resolution": "success", "solver_success": True, "solver_reason": "OK"},
    "teardown_only": {"harness_resolution": "success", "solver_success": True, "solver_reason": "OK"},
    "explicit_fail": {"harness_resolution": "failure", "solver_success": False, "solver_reason": "manual_required"},
    "retry_then_success": {"harness_resolution": "failure", "solver_success": True, "solver_reason": "OK"},
    "near_miss": {"harness_resolution": "failure", "solver_success": False, "solver_reason": "max_attempts_exceeded"},
}


def build_mock_slider_url(
    *,
    html_path: str | Path = DEFAULT_HTML,
    scenario: str = DEFAULT_SCENARIO,
    extra_params: dict[str, int | float | str] | None = None,
) -> str:
    html = Path(html_path)
    if not html.exists():
        raise FileNotFoundError(f"mock slider page not found: {html}")
    if scenario not in SCENARIOS:
        available = ", ".join(sorted(SCENARIOS))
        raise KeyError(f"unknown mock slider scenario: {scenario} (available: {available})")
    params: dict[str, int | float | str] = dict(SCENARIOS[scenario])
    if extra_params:
        params.update(extra_params)
    query = urlencode([(key, str(value)) for key, value in params.items()])
    base_url = html.resolve().as_uri()
    return f"{base_url}?{query}" if query else base_url


def get_scenario_expectation(scenario: str) -> dict[str, str | bool]:
    if scenario not in SCENARIO_EXPECTATIONS:
        available = ", ".join(sorted(SCENARIO_EXPECTATIONS))
        raise KeyError(f"unknown mock slider expectation for scenario: {scenario} (available: {available})")
    return dict(SCENARIO_EXPECTATIONS[scenario])
