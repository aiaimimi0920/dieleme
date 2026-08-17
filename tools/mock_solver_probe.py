import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.captcha_solver import CaptchaSolver
from tools.mock_slider_drag_check import FALLBACK_BROWSERS
from tools.mock_slider_scenarios import DEFAULT_HTML, DEFAULT_SCENARIO, build_mock_slider_url


def cleanup_debug_browser_processes(port: int, *, timeout_seconds: float = 10.0) -> None:
    normalized_port = int(port or 0)
    if normalized_port <= 0 or os.name != "nt":
        return
    ps_command = (
        "$targets = Get-CimInstance Win32_Process | Where-Object { "
        "($_.Name -in @('msedge.exe','chrome.exe')) -and "
        f"($_.CommandLine -like '*--remote-debugging-port={normalized_port}*') "
        "}; "
        "foreach ($process in $targets) { "
        "Stop-Process -Id $process.ProcessId -Force -ErrorAction SilentlyContinue "
        "}"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_command],
            capture_output=True,
            check=False,
            text=True,
            timeout=max(float(timeout_seconds or 0), 1.0),
        )
    except Exception:
        return


def _launch_probe_browser(
    playwright: object,
    *,
    headless: bool,
    port: int,
    launch_retries: int = 3,
) -> object:
    launch_kwargs = {
        "headless": headless,
        "args": [f"--remote-debugging-port={port}"],
    }
    attempts = max(int(launch_retries or 1), 1)
    last_error = None
    for attempt_index in range(attempts):
        try:
            return playwright.chromium.launch(**launch_kwargs)
        except Exception as error:
            last_error = error
            for executable in FALLBACK_BROWSERS:
                if executable.exists():
                    try:
                        return playwright.chromium.launch(
                            executable_path=str(executable),
                            **launch_kwargs,
                        )
                    except Exception as fallback_error:
                        last_error = fallback_error
            if attempt_index + 1 >= attempts:
                raise last_error
            cleanup_debug_browser_processes(port)
            time.sleep(min(0.1 * (attempt_index + 1), 0.25))
    raise RuntimeError("unreachable probe launch state")


def _run_probe_in_context(
    *,
    browser: object,
    target_url: str,
    scenario: str,
    port: int,
    max_attempts: int,
    run_index: int,
) -> dict[str, object]:
    context = None
    solver = None
    try:
        context = browser.new_context(viewport={"width": 900, "height": 600})
        page = context.new_page()
        page.goto(target_url, wait_until="domcontentloaded")
        page.locator("#mock-slider-handle").wait_for(state="visible", timeout=5000)

        solver = CaptchaSolver(port=port, target_url=target_url)
        result = solver.solve(max_attempts=max_attempts)
        return {
            "success": bool(result),
            "reason": solver.last_failure_reason or "OK",
            "scenario": scenario,
            "target_url": target_url,
            "port": port,
            "run_index": run_index,
        }
    finally:
        if solver is not None and solver.ws is not None:
            try:
                solver.ws.close()
            except Exception:
                pass
            solver.ws = None
        if context is not None:
            context.close()


def run_mock_solver_probe_series(
    *,
    html_path: str | Path = DEFAULT_HTML,
    scenario: str = DEFAULT_SCENARIO,
    port: int = 9223,
    headless: bool = True,
    max_attempts: int = 1,
    runs: int = 1,
) -> list[dict[str, object]]:
    run_count = max(int(runs or 0), 1)
    mock_html = Path(html_path)
    target_url = build_mock_slider_url(html_path=mock_html, scenario=scenario)
    from playwright.sync_api import sync_playwright

    results: list[dict[str, object]] = []
    with sync_playwright() as playwright:
        for run_index in range(run_count):
            run_port = port + run_index
            browser = None
            try:
                cleanup_debug_browser_processes(run_port)
                browser = _launch_probe_browser(
                    playwright,
                    headless=headless,
                    port=run_port,
                )
                results.append(
                    _run_probe_in_context(
                        browser=browser,
                        target_url=target_url,
                        scenario=scenario,
                        port=run_port,
                        max_attempts=max_attempts,
                        run_index=run_index + 1,
                    )
                )
            finally:
                if browser is not None:
                    try:
                        browser.close()
                    finally:
                        cleanup_debug_browser_processes(run_port)
    return results


def run_mock_solver_probe(
    *,
    html_path: str | Path = DEFAULT_HTML,
    scenario: str = DEFAULT_SCENARIO,
    port: int = 9223,
    headless: bool = True,
    max_attempts: int = 1,
) -> dict[str, object]:
    return run_mock_solver_probe_series(
        html_path=html_path,
        scenario=scenario,
        port=port,
        headless=headless,
        max_attempts=max_attempts,
        runs=1,
    )[0]


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe the local mock slider with the bundled solver.")
    parser.add_argument("--html", default=str(DEFAULT_HTML))
    parser.add_argument("--scenario", default=DEFAULT_SCENARIO)
    parser.add_argument("--port", type=int, default=9223)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--max-attempts", type=int, default=1)
    args = parser.parse_args()

    result = run_mock_solver_probe(
        html_path=args.html,
        scenario=args.scenario,
        port=args.port,
        headless=not args.headed,
        max_attempts=args.max_attempts,
    )
    print(f"Mock page: {result['target_url']}")
    print(f"\n{'SUCCESS' if result['success'] else 'FAILED'}: {result['reason']}")
    return 0 if result["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
