from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.mock_slider_scenarios import DEFAULT_SCENARIO, build_mock_slider_url, get_scenario_expectation

DEFAULT_HTML = REPO_ROOT / "tools" / "mock_slider.html"
FALLBACK_BROWSERS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
)


def _drag_points(start_x: float, start_y: float, distance: float, *, steps: int = 36) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    overshoot = min(max(distance * 0.015, 2.0), 6.0)
    total = distance + overshoot
    for index in range(steps + 1):
        t = index / steps
        eased = t * t * (3 - 2 * t)
        wiggle = math.sin(t * math.pi * 3) * 1.2
        points.append((start_x + total * eased, start_y + wiggle))

    final_x = start_x + distance
    last_x, last_y = points[-1]
    for index in range(1, 5):
        ratio = index / 4
        points.append((last_x + (final_x - last_x) * ratio, last_y))
    return points


def _state_from_page(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """() => {
            const state = window.__mockSliderState || {};
            return {
              target: state.target || 'unknown',
              success: Boolean(state.success),
              failure: Boolean(state.failure),
              resolution: state.resolution || 'unknown',
              status_text: state.statusText || '',
              final_ratio: Number(state.finalRatio || 0),
              event_counts: state.eventCounts || {},
              path_length: Array.isArray(state.path) ? state.path.length : 0,
              challenge_visible: Boolean(state.challengeVisible),
              verify_mode: state.config && state.config.verifyMode ? state.config.verifyMode : '',
            };
        }"""
    )


def _launch_browser(playwright: Any, *, headless: bool) -> Any:
    try:
        return playwright.chromium.launch(headless=headless)
    except Exception as first_error:
        for executable in FALLBACK_BROWSERS:
            if executable.exists():
                try:
                    return playwright.chromium.launch(
                        executable_path=str(executable),
                        headless=headless,
                    )
                except Exception:
                    continue
        raise first_error


def run_mock_slider_drag_check(
    *,
    html_path: str | Path = DEFAULT_HTML,
    scenario: str = DEFAULT_SCENARIO,
    headless: bool = True,
    screenshot_path: str | Path | None = None,
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    html = Path(html_path)
    if not html.exists():
        raise FileNotFoundError(f"mock slider page not found: {html}")
    target_url = build_mock_slider_url(html_path=html, scenario=scenario)
    expected_resolution = str(get_scenario_expectation(scenario)["harness_resolution"])

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright, headless=headless)
        try:
            page = browser.new_page(viewport={"width": 900, "height": 600})
            page.goto(target_url, wait_until="domcontentloaded")
            handle = page.locator("#mock-slider-handle")
            track = page.locator("#mock-slider-track")
            handle.wait_for(state="visible", timeout=5000)
            track.wait_for(state="visible", timeout=5000)
            handle_box = handle.bounding_box()
            track_box = track.bounding_box()
            if not handle_box or not track_box:
                raise RuntimeError("mock slider elements are not visible")

            start_x = handle_box["x"] + handle_box["width"] / 2
            start_y = handle_box["y"] + handle_box["height"] / 2
            distance = track_box["width"] - handle_box["width"] - 8
            points = _drag_points(start_x, start_y, distance)

            page.mouse.move(start_x - 8, start_y)
            page.mouse.move(start_x, start_y)
            page.mouse.down()
            for x, y in points:
                page.mouse.move(x, y)
                time.sleep(0.008)
            page.mouse.up()
            if expected_resolution == "failure":
                page.wait_for_function(
                    "() => window.__mockSliderState && window.__mockSliderState.failure === true",
                    timeout=4000,
                )
            else:
                page.wait_for_function(
                    "() => window.__mockSliderState && window.__mockSliderState.success === true",
                    timeout=4000,
                )

            if screenshot_path:
                screenshot = Path(screenshot_path)
                screenshot.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(screenshot))

            state = _state_from_page(page)
            state["html_path"] = str(html)
            state["target_url"] = target_url
            state["scenario"] = scenario
            state["expected_resolution"] = expected_resolution
            state["resolved_as_expected"] = state.get("resolution") == expected_resolution
            state["headless"] = bool(headless)
            return state
        finally:
            browser.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a safe local mock slider drag check.")
    parser.add_argument("--html", default=str(DEFAULT_HTML))
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--screenshot", default=None)
    args = parser.parse_args()

    result = run_mock_slider_drag_check(
        html_path=args.html,
        scenario=args.scenario,
        headless=not args.headed,
        screenshot_path=args.screenshot,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("resolved_as_expected") else 1


if __name__ == "__main__":
    raise SystemExit(main())
