from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
import json
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.mock_slider_drag_check import run_mock_slider_drag_check
from tools.mock_slider_scenarios import DEFAULT_SCENARIO, SCENARIOS, get_scenario_expectation
from tools.mock_solver_probe import run_mock_solver_probe_series


DEFAULT_SCENARIO_TIMEOUT_SECONDS = 240.0


def _port_stride_for_runs(runs: int) -> int:
    return max(20, max(int(runs or 0), 1))


def _run_matrix_scenario(
    scenario: str,
    scenario_index: int,
    runs: int,
    port_base: int,
    headed: bool,
) -> dict[str, object]:
    expectation = get_scenario_expectation(scenario)
    port_stride = _port_stride_for_runs(runs)
    harness_result = run_mock_slider_drag_check(
        headless=not headed,
        scenario=scenario,
    )
    probe_runs = run_mock_solver_probe_series(
        scenario=scenario,
        port=port_base + scenario_index * port_stride,
        headless=not headed,
        max_attempts=1,
        runs=runs,
    )
    harness_ok = bool(harness_result.get("resolved_as_expected"))
    expected_solver_success = bool(expectation["solver_success"])
    expected_solver_reason = str(expectation["solver_reason"])
    solver_ok = True
    for probe_result in probe_runs:
        solver_ok = solver_ok and (bool(probe_result.get("success")) == expected_solver_success)
        solver_ok = solver_ok and (str(probe_result.get("reason")) == expected_solver_reason)
    scenario_ok = harness_ok and solver_ok
    return {
        "scenario": scenario,
        "expectation": expectation,
        "harness": harness_result,
        "probe_runs": probe_runs,
        "harness_ok": harness_ok,
        "solver_ok": solver_ok,
        "success": scenario_ok,
    }


def run_matrix_scenarios(
    scenario_args: list[tuple[str, int, int, int, bool]],
    *,
    workers: int,
    scenario_timeout_seconds: float,
) -> list[dict[str, object]]:
    if workers == 1 or len(scenario_args) <= 1:
        return [_run_matrix_scenario(*scenario_arg) for scenario_arg in scenario_args]

    effective_timeout = max(float(scenario_timeout_seconds or 0), 1.0)
    results_by_index: dict[int, dict[str, object]] = {}
    future_to_meta: dict[object, tuple[int, str, float]] = {}
    executor = ProcessPoolExecutor(max_workers=workers)
    try:
        for index, scenario_arg in enumerate(scenario_args):
            future = executor.submit(_run_matrix_scenario, *scenario_arg)
            future_to_meta[future] = (index, scenario_arg[0], time.monotonic())
        while future_to_meta:
            done, _pending = wait(tuple(future_to_meta.keys()), timeout=0.2, return_when=FIRST_COMPLETED)
            for future in done:
                index, _scenario_name, _started_at = future_to_meta.pop(future)
                results_by_index[index] = future.result()
            now = time.monotonic()
            for future, (index, scenario_name, started_at) in list(future_to_meta.items()):
                if now - started_at < effective_timeout:
                    continue
                future.cancel()
                results_by_index[index] = {
                    "scenario": scenario_name,
                    "harness_ok": False,
                    "solver_ok": False,
                    "success": False,
                    "timeout_seconds": effective_timeout,
                    "error": f"scenario timed out after {effective_timeout:.1f}s",
                    "probe_runs": [],
                }
                future_to_meta.pop(future, None)
        return [results_by_index[index] for index in sorted(results_by_index)]
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local mock slider stability matrix.")
    parser.add_argument("--scenario", action="append", dest="scenarios", default=None)
    parser.add_argument("--runs", type=int, default=2)
    parser.add_argument("--port-base", type=int, default=9340)
    parser.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument("--scenario-timeout-seconds", type=float, default=DEFAULT_SCENARIO_TIMEOUT_SECONDS)
    parser.add_argument("--headed", action="store_true")
    args = parser.parse_args()

    scenario_names = args.scenarios or list(SCENARIOS.keys())
    if DEFAULT_SCENARIO not in scenario_names and args.scenarios is None:
        scenario_names.insert(0, DEFAULT_SCENARIO)

    scenario_args = [
        (scenario, scenario_index, args.runs, args.port_base, args.headed)
        for scenario_index, scenario in enumerate(scenario_names)
    ]
    workers = max(1, min(int(args.workers or 1), len(scenario_args)))
    results = run_matrix_scenarios(
        scenario_args,
        workers=workers,
        scenario_timeout_seconds=args.scenario_timeout_seconds,
    )
    overall_success = all(bool(result.get("success")) for result in results)

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0 if overall_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
