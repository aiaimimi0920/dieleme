from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HTML = REPO_ROOT / "tools" / "mock_slider.html"
FALLBACK_BROWSERS = (
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
)


def _file_url(path: Path) -> str:
    return path.resolve().as_uri()


def _drag_points(start_x: float, start_y: float, distance: float, *, steps: int = 36) -> list[tuple[float, float]]:
    points: list[tuple[float, float]] = []
    overshoot = min(max(distance * 0.015, 2.0), 6.0)
    total = distance + overshoot
    for index in range(steps + 1):
        t = index / steps
        # Smoothstep gives slow start/end while remaining deterministic for tests.
        eased = t * t * (3 - 2 * t)
        wiggle = math.sin(t * math.pi * 3) * 1.2
        points.append((start_x + total * eased, start_y + wiggle))

    # Correction phase: pull back the small overshoot before releasing.
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
              final_ratio: Number(state.finalRatio || 0),
              event_counts: state.eventCounts || {},
              path_length: Array.isArray(state.path) ? state.path.length : 0,
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
    headless: bool = True,
    screenshot_path: str | Path | None = None,
) -> dict[str, Any]:
    """Verify mouse-drag mechanics against a local mock slider only.

    This helper intentionally opens a file:// page from this repository and never
    navigates to third-party sites or real verification pages.
    """

    from playwright.sync_api import sync_playwright

    html = Path(html_path)
    if not html.exists():
        raise FileNotFoundError(f"mock slider page not found: {html}")

    with sync_playwright() as playwright:
        browser = _launch_browser(playwright, headless=headless)
        page = browser.new_page(viewport={"width": 900, "height": 600})
        page.goto(_file_url(html), wait_until="domcontentloaded")
        handle = page.locator("#mock-slider-handle")
        track = page.locator("#mock-slider-track")
        handle_box = handle.bounding_box()
        track_box = track.bounding_box()
        if not handle_box or not track_box:
            browser.close()
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
        page.wait_for_timeout(150)

        if screenshot_path:
            screenshot = Path(screenshot_path)
            screenshot.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(screenshot))

        state = _state_from_page(page)
        state["html_path"] = str(html)
        state["headless"] = bool(headless)
        browser.close()
        return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a safe local mock slider drag check.")
    parser.add_argument("--html", default=str(DEFAULT_HTML))
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--screenshot", default=None)
    args = parser.parse_args()

    result = run_mock_slider_drag_check(
        html_path=args.html,
        headless=not args.headed,
        screenshot_path=args.screenshot,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
