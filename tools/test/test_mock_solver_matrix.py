from __future__ import annotations

from concurrent.futures import Future

from tools import mock_solver_matrix


def test_run_matrix_scenario_reports_success_when_harness_and_probe_match(monkeypatch) -> None:
    probe_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        mock_solver_matrix,
        "get_scenario_expectation",
        lambda scenario: {
            "harness_resolution": "success",
            "solver_success": True,
            "solver_reason": "OK",
            "scenario": scenario,
        },
    )
    monkeypatch.setattr(
        mock_solver_matrix,
        "run_mock_slider_drag_check",
        lambda *, headless, scenario: {
            "resolved_as_expected": True,
            "headless": headless,
            "scenario": scenario,
        },
    )

    def fake_probe_series(**kwargs: object) -> list[dict[str, object]]:
        probe_calls.append(kwargs)
        return [
            {"success": True, "reason": "OK", "run_index": 1},
            {"success": True, "reason": "OK", "run_index": 2},
        ]

    monkeypatch.setattr(mock_solver_matrix, "run_mock_solver_probe_series", fake_probe_series)

    result = mock_solver_matrix._run_matrix_scenario(
        "wide_delay",
        scenario_index=3,
        runs=2,
        port_base=9300,
        headed=False,
    )

    assert result["scenario"] == "wide_delay"
    assert result["harness_ok"] is True
    assert result["solver_ok"] is True
    assert result["success"] is True
    assert result["probe_runs"] == [
        {"success": True, "reason": "OK", "run_index": 1},
        {"success": True, "reason": "OK", "run_index": 2},
    ]
    assert probe_calls == [
        {
            "scenario": "wide_delay",
            "port": 9360,
            "headless": True,
            "max_attempts": 1,
            "runs": 2,
        }
    ]


def test_run_matrix_scenario_fails_when_probe_reason_mismatches_expectation(monkeypatch) -> None:
    monkeypatch.setattr(
        mock_solver_matrix,
        "get_scenario_expectation",
        lambda _scenario: {
            "harness_resolution": "failure",
            "solver_success": False,
            "solver_reason": "manual_required",
        },
    )
    monkeypatch.setattr(
        mock_solver_matrix,
        "run_mock_slider_drag_check",
        lambda *, headless, scenario: {
            "resolved_as_expected": True,
            "headless": headless,
            "scenario": scenario,
        },
    )
    monkeypatch.setattr(
        mock_solver_matrix,
        "run_mock_solver_probe_series",
        lambda **_kwargs: [
            {"success": False, "reason": "max_attempts_exceeded", "run_index": 1},
        ],
    )

    result = mock_solver_matrix._run_matrix_scenario(
        "near_miss",
        scenario_index=0,
        runs=1,
        port_base=9340,
        headed=False,
    )

    assert result["harness_ok"] is True
    assert result["solver_ok"] is False
    assert result["success"] is False


def test_run_matrix_scenario_fails_when_harness_is_not_resolved_as_expected(monkeypatch) -> None:
    monkeypatch.setattr(
        mock_solver_matrix,
        "get_scenario_expectation",
        lambda _scenario: {
            "harness_resolution": "success",
            "solver_success": True,
            "solver_reason": "OK",
        },
    )
    monkeypatch.setattr(
        mock_solver_matrix,
        "run_mock_slider_drag_check",
        lambda *, headless, scenario: {
            "resolved_as_expected": False,
            "headless": headless,
            "scenario": scenario,
        },
    )
    monkeypatch.setattr(
        mock_solver_matrix,
        "run_mock_solver_probe_series",
        lambda **_kwargs: [
            {"success": True, "reason": "OK", "run_index": 1},
        ],
    )

    result = mock_solver_matrix._run_matrix_scenario(
        "default",
        scenario_index=1,
        runs=1,
        port_base=9340,
        headed=True,
    )

    assert result["harness_ok"] is False
    assert result["solver_ok"] is True
    assert result["success"] is False


def test_port_stride_for_runs_expands_once_run_count_exceeds_default_block() -> None:
    assert mock_solver_matrix._port_stride_for_runs(3) == 20
    assert mock_solver_matrix._port_stride_for_runs(25) == 25


def test_run_matrix_scenarios_returns_timeout_result_and_cancels_remaining_futures(monkeypatch) -> None:
    class _FakeFuture(Future):
        def __init__(self, *, scenario_name: str, done: bool, payload: dict[str, object] | None = None) -> None:
            super().__init__()
            self.scenario_name = scenario_name
            self.cancel_calls = 0
            if done and payload is not None:
                self.set_result(payload)

        def cancel(self) -> bool:
            self.cancel_calls += 1
            return True

    class _FakeExecutor:
        def __init__(self, max_workers: int) -> None:
            self.max_workers = max_workers
            self.submitted: list[tuple[str, _FakeFuture]] = []
            self.shutdown_calls: list[dict[str, object]] = []

        def submit(self, _fn, *scenario_arg):
            scenario_name = scenario_arg[0]
            if scenario_name == "done":
                future = _FakeFuture(
                    scenario_name=scenario_name,
                    done=True,
                    payload={"scenario": scenario_name, "success": True},
                )
            else:
                future = _FakeFuture(scenario_name=scenario_name, done=False)
            self.submitted.append((scenario_name, future))
            return future

        def shutdown(self, **kwargs) -> None:
            self.shutdown_calls.append(dict(kwargs))

    fake_executor = _FakeExecutor(max_workers=2)
    monotonic_values = iter([10.0, 10.1, 16.5])

    monkeypatch.setattr(mock_solver_matrix, "ProcessPoolExecutor", lambda max_workers: fake_executor)
    monkeypatch.setattr(mock_solver_matrix.time, "monotonic", lambda: next(monotonic_values))

    def _fake_wait(futures, timeout: float, return_when):
        done = {future for future in futures if getattr(future, "scenario_name", "") == "done"}
        return done, set(futures) - done

    monkeypatch.setattr(mock_solver_matrix, "wait", _fake_wait)

    results = mock_solver_matrix.run_matrix_scenarios(
        [
            ("done", 0, 1, 9300, False),
            ("hung", 1, 1, 9300, False),
        ],
        workers=2,
        scenario_timeout_seconds=5,
    )

    assert results == [
        {"scenario": "done", "success": True},
        {
            "scenario": "hung",
            "harness_ok": False,
            "solver_ok": False,
            "success": False,
            "timeout_seconds": 5.0,
            "error": "scenario timed out after 5.0s",
            "probe_runs": [],
        },
    ]
    hung_future = dict(fake_executor.submitted)["hung"]
    assert hung_future.cancel_calls == 1
    assert fake_executor.shutdown_calls == [{"wait": False, "cancel_futures": True}]


def test_run_matrix_scenarios_single_worker_runs_inline(monkeypatch) -> None:
    calls: list[tuple[str, int, int, int, bool]] = []

    monkeypatch.setattr(
        mock_solver_matrix,
        "_run_matrix_scenario",
        lambda *scenario_arg: calls.append(scenario_arg) or {"scenario": scenario_arg[0], "success": True},
    )

    results = mock_solver_matrix.run_matrix_scenarios(
        [("default", 0, 1, 9340, False)],
        workers=1,
        scenario_timeout_seconds=30,
    )

    assert results == [{"scenario": "default", "success": True}]
    assert calls == [("default", 0, 1, 9340, False)]
