from __future__ import annotations

import json
from pathlib import Path
import os
import shutil
import subprocess
import sys

def _copy_repo_batch_to_fake_repo(repo_root: Path, tmp_path: Path, name: str) -> Path:
    fake_repo = tmp_path / "repo"
    (fake_repo / "auto").mkdir(parents=True, exist_ok=True)
    (fake_repo / "src").mkdir(parents=True, exist_ok=True)
    shutil.copy2(repo_root / "auto" / name, fake_repo / "auto" / name)
    for helper_path in (repo_root / "auto").glob("*.ps1"):
        shutil.copy2(helper_path, fake_repo / "auto" / helper_path.name)
    return fake_repo


def _write_fake_python_cmd(fake_repo: Path, log_path: Path) -> Path:
    fake_python = fake_repo / "fake_python.cmd"
    fake_python.write_text(
        "\n".join(
            [
                "@echo off",
                f'echo STUB_CWD=%CD%> "{log_path}"',
                f'echo STUB_ARGS=%*>> "{log_path}"',
                "exit /b 0",
            ]
        ),
        encoding="utf-8",
    )
    return fake_python


def _write_fake_python_cmd_with_exit(fake_repo: Path, log_path: Path, exit_code: int) -> Path:
    fake_python = fake_repo / "fake_python_exit.cmd"
    fake_python.write_text(
        "\n".join(
            [
                "@echo off",
                f'echo STUB_CWD=%CD%> "{log_path}"',
                f'echo STUB_ARGS=%*>> "{log_path}"',
                f"exit /b {exit_code}",
            ]
        ),
        encoding="utf-8",
    )
    return fake_python


def _write_fake_python_cmd_with_exit_and_summary(
    fake_repo: Path,
    log_path: Path,
    *,
    summary_path: Path,
    exit_code: int,
    summary_payload: dict[str, object],
) -> Path:
    fake_python = fake_repo / "fake_python_with_summary.cmd"
    fake_python.write_text(
        "\n".join(
            [
                "@echo off",
                f'echo STUB_CWD=%CD%> "{log_path}"',
                f'echo STUB_ARGS=%*>> "{log_path}"',
                f'echo {json.dumps(summary_payload, ensure_ascii=False)}> "{summary_path}"',
                f"exit /b {exit_code}",
            ]
        ),
        encoding="utf-8",
    )
    return fake_python


def _write_real_python_target(target_path: Path, log_path: Path) -> None:
    target_path.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                f'Path(r"{str(log_path)}").write_text("REAL_PYTHON_INVOKED", encoding="utf-8")',
            ]
        ),
        encoding="utf-8",
    )


def _run_batch(batch_path: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["cmd", "/c", str(batch_path)],
        cwd=str(batch_path.parent),
        env=env,
        input="\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _path_matches_windows_drive_alias(invoked_cwd: Path, expected_cwd: Path) -> bool:
    if invoked_cwd == expected_cwd:
        return True
    try:
        if invoked_cwd.exists() and expected_cwd.exists() and invoked_cwd.samefile(expected_cwd):
            return True
    except OSError:
        pass
    if os.name != "nt" or not invoked_cwd.anchor or not expected_cwd.anchor:
        return False
    invoked_parts = tuple(part.casefold() for part in invoked_cwd.parts[1:])
    expected_parts = tuple(part.casefold() for part in expected_cwd.parts[1:])
    return invoked_parts == expected_parts


def _assert_stub_invocation(
    log_path: Path,
    expected_arg: str,
    expected_cwd: Path | None = None,
    expected_cwd_suffix: tuple[str, ...] | None = None,
) -> None:
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("STUB_CWD=")
    invoked_cwd = Path(lines[0].split("=", 1)[1])
    if expected_cwd is not None:
        assert _path_matches_windows_drive_alias(invoked_cwd, expected_cwd)
    if expected_cwd_suffix is not None:
        assert invoked_cwd.parts[-len(expected_cwd_suffix) :] == expected_cwd_suffix
    assert lines[1] == f"STUB_ARGS={expected_arg}"


def test_main_batch_respects_predefined_python_cmd(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "main.bat")
    log_path = fake_repo / "main-log.txt"
    fake_python = _write_fake_python_cmd(fake_repo, log_path)
    _write_real_python_target(fake_repo / "src" / "server.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = _run_batch(fake_repo / "auto" / "main.bat", env)

    assert result.returncode == 0
    _assert_stub_invocation(log_path, "src/server.py", expected_cwd=fake_repo)


def test_data_fixer_batch_respects_predefined_python_cmd(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "data_fixer.bat")
    log_path = fake_repo / "data-fixer-log.txt"
    fake_python = _write_fake_python_cmd(fake_repo, log_path)
    _write_real_python_target(fake_repo / "src" / "data_fixer.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = _run_batch(fake_repo / "auto" / "data_fixer.bat", env)

    assert result.returncode == 0
    _assert_stub_invocation(log_path, "src/data_fixer.py", expected_cwd=fake_repo)


def test_main_batch_returns_python_exit_code(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "main.bat")
    log_path = fake_repo / "main-exit-log.txt"
    fake_python = _write_fake_python_cmd_with_exit(fake_repo, log_path, 23)
    _write_real_python_target(fake_repo / "src" / "server.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = _run_batch(fake_repo / "auto" / "main.bat", env)

    assert result.returncode == 23
    _assert_stub_invocation(log_path, "src/server.py", expected_cwd=fake_repo)


def test_data_fixer_batch_returns_python_exit_code(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "data_fixer.bat")
    log_path = fake_repo / "data-fixer-exit-log.txt"
    fake_python = _write_fake_python_cmd_with_exit(fake_repo, log_path, 24)
    _write_real_python_target(fake_repo / "src" / "data_fixer.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = _run_batch(fake_repo / "auto" / "data_fixer.bat", env)

    assert result.returncode == 24
    _assert_stub_invocation(log_path, "src/data_fixer.py", expected_cwd=fake_repo)


def test_main_batch_resumes_parent_after_cmd_python_wrapper(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "main.bat")
    log_path = fake_repo / "main-parent-resume-log.txt"
    fake_python = _write_fake_python_cmd_with_exit(fake_repo, log_path, 25)
    _write_real_python_target(fake_repo / "src" / "server.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = _run_batch(fake_repo / "auto" / "main.bat", env)

    assert result.returncode == 25
    _assert_stub_invocation(log_path, "src/server.py", expected_cwd=fake_repo)
    assert "[INFO] main.bat finished with exit code 25" in result.stdout


def test_data_fixer_batch_resumes_parent_after_cmd_python_wrapper(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "data_fixer.bat")
    log_path = fake_repo / "data-fixer-parent-resume-log.txt"
    fake_python = _write_fake_python_cmd_with_exit(fake_repo, log_path, 26)
    _write_real_python_target(fake_repo / "src" / "data_fixer.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = _run_batch(fake_repo / "auto" / "data_fixer.bat", env)

    assert result.returncode == 26
    _assert_stub_invocation(log_path, "src/data_fixer.py", expected_cwd=fake_repo)
    assert "[INFO] data_fixer.bat finished with exit code 26" in result.stdout


def test_main_batch_smoke_runs_against_actual_repo_with_stub_python(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    log_path = tmp_path / "actual-main-log.txt"
    fake_python = _write_fake_python_cmd(tmp_path, log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = subprocess.run(
        ["cmd", "/c", str(repo_root / "auto" / "main.bat")],
        cwd=str(repo_root),
        env=env,
        input="\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    _assert_stub_invocation(
        log_path,
        "src/server.py",
        expected_cwd_suffix=("project", "project", "fapaifang"),
    )


def test_data_fixer_batch_smoke_runs_against_actual_repo_with_stub_python(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    log_path = tmp_path / "actual-data-fixer-log.txt"
    fake_python = _write_fake_python_cmd(tmp_path, log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = subprocess.run(
        ["cmd", "/c", str(repo_root / "auto" / "data_fixer.bat")],
        cwd=str(repo_root),
        env=env,
        input="\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    _assert_stub_invocation(
        log_path,
        "src/data_fixer.py",
        expected_cwd_suffix=("project", "project", "fapaifang"),
    )


def test_seed_hybrid_collector_batch_respects_predefined_python_cmd(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-log.txt"
    fake_python = _write_fake_python_cmd(fake_repo, log_path)
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 0
    stub_args = log_path.read_text(encoding="utf-8").splitlines()[1]
    assert stub_args.startswith("STUB_ARGS=tools/run_hybrid_seed_collection.py")
    assert "--submit" in stub_args
    assert "--loop" in stub_args
    assert "--open-browser-fallback" in stub_args
    assert "--mode \"hybrid\"" in stub_args
    assert "--respect-operator-guidance" in stub_args


def test_seed_hybrid_collector_batch_appends_hybrid_extra_args(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-extra-log.txt"
    fake_python = _write_fake_python_cmd(fake_repo, log_path)
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_EXTRA_ARGS"] = "--max-runs 1 --stop-on-fallback"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 0
    stub_args = log_path.read_text(encoding="utf-8").splitlines()[1]
    assert "--max-runs 1" in stub_args
    assert "--stop-on-fallback" in stub_args


def test_seed_hybrid_collector_batch_respects_run_mode_override(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-mode-log.txt"
    fake_python = _write_fake_python_cmd(fake_repo, log_path)
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_RUN_MODE"] = "browser"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 0
    stub_args = log_path.read_text(encoding="utf-8").splitlines()[1]
    assert "--mode \"browser\"" in stub_args


def test_seed_hybrid_collector_batch_can_disable_operator_guidance(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-guidance-log.txt"
    fake_python = _write_fake_python_cmd(fake_repo, log_path)
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_RESPECT_OPERATOR_GUIDANCE"] = "0"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 0
    stub_args = log_path.read_text(encoding="utf-8").splitlines()[1]
    assert "--respect-operator-guidance" not in stub_args


def test_seed_hybrid_collector_batch_can_enable_fail_on_operator_escalation(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-escalation-flag-log.txt"
    fake_python = _write_fake_python_cmd(fake_repo, log_path)
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 0
    stub_args = log_path.read_text(encoding="utf-8").splitlines()[1]
    assert "--fail-on-operator-escalation" in stub_args


def test_seed_hybrid_collector_batch_can_enable_stop_on_operator_escalation(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-stop-escalation-log.txt"
    fake_python = _write_fake_python_cmd(fake_repo, log_path)
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_STOP_ON_OPERATOR_ESCALATION"] = "1"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 0
    stub_args = log_path.read_text(encoding="utf-8").splitlines()[1]
    assert "--stop-on-operator-escalation" in stub_args


def test_seed_hybrid_collector_batch_surfaces_operator_escalation_source_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-escalation-source-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "lifecycle_high_priority_backlog",
            "recovery_policy_status": "steady_hybrid",
            "effective_mode": "hybrid",
            "top_policy_reason": "high_priority_backlog_present",
            "intervention_status": "intervention_required",
            "intervention_priority": "high",
            "intervention_reason": "high_priority_unresolved_escalation_backlog",
            "intervention_stability_status": "escalating",
            "intervention_stability_severity": "high",
            "intervention_stability_explanation": "Intervention escalated from ready to intervention_required recently.",
            "intervention_stability_action_hint": "prefer browser and investigate escalating intervention",
            "operator_final_guidance_label": "Escalating intervention",
            "operator_final_guidance_priority": "high",
            "operator_final_guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "operator_digest_status": "intervention_required",
            "operator_digest_priority": "high",
            "operator_digest_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
            "operator_digest_stability_status": "digest_recently_shifted",
            "operator_digest_stability_severity": "high",
            "operator_digest_stability_explanation": "Operator digest recently shifted from ready to intervention_required.",
            "lifecycle_follow_up": "prefer_browser_and_investigate_escalation",
            "lifecycle_suggested_mode": "browser",
            "operator_action_hint": "inspect unresolved high-priority backlog; suggested mode=browser",
            "operator_escalation_audit_message": "Escalating intervention: prefer browser and investigate escalating intervention. [source=lifecycle_high_priority_backlog, digest=intervention_required, digest_stability=digest_recently_shifted]",
            "operator_escalation_current_source": "intervention_stability",
            "operator_escalation_previous_source": "recovery_policy",
            "operator_escalation_source_change_count": 1,
            "operator_escalation_source_last_changed_at": "2026-05-18 18:24:00",
            "operator_escalation_source_stability_status": "source_recently_shifted",
            "operator_escalation_source_stability_severity": "high",
            "operator_escalation_source_stability_explanation": "Operator escalation source recently shifted from recovery_policy to intervention_stability.",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator escalation source: lifecycle_high_priority_backlog" not in result.stdout
    assert "Operator escalation effective mode: hybrid" in result.stdout
    assert "Operator escalation reason: high_priority_backlog_present" not in result.stdout
    assert "Operator intervention status: intervention_required" not in result.stdout
    assert "Operator intervention priority: high" in result.stdout
    assert "Operator intervention reason: high_priority_unresolved_escalation_backlog" in result.stdout
    assert "Operator intervention stability: escalating" not in result.stdout
    assert "Operator intervention stability severity: high" in result.stdout
    assert "Operator intervention stability explanation: Intervention escalated from ready to intervention_required recently." in result.stdout
    assert "Operator intervention stability action hint: prefer browser and investigate escalating intervention" in result.stdout
    assert "Operator final guidance: Escalating intervention: prefer browser and investigate escalating intervention." not in result.stdout
    assert "Operator digest status: intervention_required" not in result.stdout
    assert "Operator digest priority: high" in result.stdout
    assert "Operator digest: Escalating intervention: prefer browser and investigate escalating intervention." not in result.stdout
    assert "Operator digest stability: digest_recently_shifted" not in result.stdout
    assert "Operator digest stability severity: high" in result.stdout
    assert "Operator digest stability explanation: Operator digest recently shifted from ready to intervention_required." in result.stdout
    assert "Operator escalation audit: Escalating intervention: prefer browser and investigate escalating intervention. [source=lifecycle_high_priority_backlog, digest=intervention_required, digest_stability=digest_recently_shifted]" in result.stdout
    assert "Operator escalation current source: intervention_stability" not in result.stdout
    assert "Operator escalation previous source: recovery_policy" not in result.stdout
    assert "Operator escalation source change count: 1" in result.stdout
    assert "Operator escalation source last changed at: 2026-05-18 18:24:00" in result.stdout
    assert "Operator escalation source stability: source_recently_shifted" not in result.stdout
    assert "Operator escalation source stability severity: high" in result.stdout
    assert "Operator escalation source stability explanation: Operator escalation source recently shifted from recovery_policy to intervention_stability." in result.stdout
    assert "Operator follow-up: prefer_browser_and_investigate_escalation" not in result.stdout
    assert "Operator suggested mode: browser" not in result.stdout
    assert "Operator action hint: inspect unresolved high-priority backlog; suggested mode=browser" in result.stdout
    warn_lines = [line for line in result.stdout.splitlines() if line.startswith("[WARN]")]
    assert warn_lines[1].startswith("[WARN] Operator digest priority:")
    assert warn_lines[2].startswith("[WARN] Operator digest stability severity:")
    assert warn_lines[3].startswith("[WARN] Operator digest stability explanation:")
    assert warn_lines[4].startswith("[WARN] Operator escalation audit:")
    assert warn_lines[5].startswith("[WARN] Operator escalation source change count:")
    assert warn_lines[6].startswith("[WARN] Operator escalation source last changed at:")
    assert warn_lines[7].startswith("[WARN] Operator escalation source stability severity:")
    assert warn_lines[8].startswith("[WARN] Operator escalation source stability explanation:")
    assert warn_lines[9].startswith("[WARN] Operator escalation effective mode:")


def test_seed_hybrid_collector_batch_surfaces_recovery_policy_action_hint(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-recovery-policy-hint-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-recovery.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "recovery_policy_status": "escalate_repeated_repin",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "lifecycle_follow_up": "prefer_browser_and_investigate_escalation",
            "lifecycle_suggested_mode": "browser",
            "operator_action_hint": "follow recovery policy escalation guidance; suggested mode=browser",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator escalation source: recovery_policy" not in result.stdout
    assert "Operator escalation effective mode: browser" not in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout
    assert "Operator follow-up: prefer_browser_and_investigate_escalation" not in result.stdout
    assert "Operator suggested mode: browser" not in result.stdout
    assert "Operator action hint: follow recovery policy escalation guidance; suggested mode=browser" in result.stdout


def test_seed_hybrid_collector_batch_omits_blank_suggested_mode_in_generated_recovery_policy_action_hint(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-recovery-policy-hint-no-mode-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-recovery-no-mode.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "recovery_policy_status": "escalate_repeated_repin",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "lifecycle_follow_up": "prefer_browser_and_investigate_escalation",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator escalation source: recovery_policy" not in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout
    assert "Operator suggested mode:" not in result.stdout
    assert "suggested mode=" not in result.stdout
    assert "Operator action hint: follow recovery policy escalation guidance" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_current_source_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-current-source-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-current-source.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_action_hint": "follow recovery policy escalation guidance; suggested mode=browser",
            "lifecycle_suggested_mode": "browser",
            "operator_escalation_current_source": "unknown",
            "operator_escalation_previous_source": "recovery_policy",
            "operator_escalation_source_change_count": 1,
            "operator_escalation_source_last_changed_at": "2026-05-18 18:24:00",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator escalation current source: unknown" not in result.stdout
    assert "Operator escalation previous source: recovery_policy" in result.stdout
    assert "Operator escalation source change count: 1" in result.stdout
    assert "Operator escalation source last changed at: 2026-05-18 18:24:00" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_previous_source_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-previous-source-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-previous-source.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_action_hint": "follow recovery policy escalation guidance; suggested mode=browser",
            "lifecycle_suggested_mode": "browser",
            "operator_escalation_current_source": "recovery_policy",
            "operator_escalation_previous_source": "unknown",
            "operator_escalation_source_change_count": 1,
            "operator_escalation_source_last_changed_at": "2026-05-18 18:24:00",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator escalation current source: recovery_policy" in result.stdout
    assert "Operator escalation previous source: unknown" not in result.stdout
    assert "Operator escalation source change count: 1" in result.stdout
    assert "Operator escalation source last changed at: 2026-05-18 18:24:00" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_source_stability_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-source-stability-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-source-stability.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_action_hint": "follow recovery policy escalation guidance; suggested mode=browser",
            "lifecycle_suggested_mode": "browser",
            "operator_escalation_current_source": "recovery_policy",
            "operator_escalation_previous_source": "intervention_stability",
            "operator_escalation_source_change_count": 1,
            "operator_escalation_source_last_changed_at": "2026-05-18 18:24:00",
            "operator_escalation_source_stability_status": "unknown",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator escalation current source: recovery_policy" in result.stdout
    assert "Operator escalation previous source: intervention_stability" in result.stdout
    assert "Operator escalation source stability: unknown" not in result.stdout
    assert "Operator escalation source change count: 1" in result.stdout
    assert "Operator escalation source last changed at: 2026-05-18 18:24:00" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_source_last_changed_at_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-source-last-changed-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-source-last-changed.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_action_hint": "follow recovery policy escalation guidance; suggested mode=browser",
            "lifecycle_suggested_mode": "browser",
            "operator_escalation_current_source": "recovery_policy",
            "operator_escalation_previous_source": "intervention_stability",
            "operator_escalation_source_change_count": 1,
            "operator_escalation_source_last_changed_at": "unknown",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator escalation current source: recovery_policy" in result.stdout
    assert "Operator escalation previous source: intervention_stability" in result.stdout
    assert "Operator escalation source change count: 1" in result.stdout
    assert "Operator escalation source last changed at: unknown" not in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_source_change_count_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-source-change-count-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-source-change-count.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_action_hint": "follow recovery policy escalation guidance; suggested mode=browser",
            "lifecycle_suggested_mode": "browser",
            "operator_escalation_current_source": "recovery_policy",
            "operator_escalation_previous_source": "intervention_stability",
            "operator_escalation_source_change_count": "unknown",
            "operator_escalation_source_last_changed_at": "2026-05-18 18:24:00",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator escalation current source: recovery_policy" in result.stdout
    assert "Operator escalation previous source: intervention_stability" in result.stdout
    assert "Operator escalation source change count: unknown" not in result.stdout
    assert "Operator escalation source last changed at: 2026-05-18 18:24:00" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_effective_mode_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-effective-mode-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-effective-mode.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "unknown",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_action_hint": "follow recovery policy escalation guidance; suggested mode=browser",
            "lifecycle_suggested_mode": "browser",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator escalation effective mode: unknown" not in result.stdout
    assert "Operator action hint: follow recovery policy escalation guidance; suggested mode=browser" in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_source_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-source-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-source.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "unknown",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator escalation source: unknown" not in result.stdout
    assert "Operator escalation effective mode: browser" in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_digest_status_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-digest-status-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-digest-status.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_digest_status": "unknown",
            "operator_digest_priority": "high",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator digest status: unknown" not in result.stdout
    assert "Operator digest priority: high" in result.stdout
    assert "Operator escalation effective mode: browser" in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_digest_stability_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-digest-stability-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-digest-stability.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_digest_stability_status": "unknown",
            "operator_digest_stability_severity": "high",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator digest stability: unknown" not in result.stdout
    assert "Operator digest stability severity: high" in result.stdout
    assert "Operator escalation effective mode: browser" in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_digest_priority_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-digest-priority-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-digest-priority.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_digest_status": "intervention_required",
            "operator_digest_priority": "unknown",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator digest status: intervention_required" in result.stdout
    assert "Operator digest priority: unknown" not in result.stdout
    assert "Operator escalation effective mode: browser" in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_digest_message_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-digest-message-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-digest-message.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_digest_status": "intervention_required",
            "operator_digest_message": "unknown",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator digest status: intervention_required" in result.stdout
    assert "Operator digest: unknown" not in result.stdout
    assert "Operator escalation effective mode: browser" in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_digest_stability_severity_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-digest-stability-severity-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-digest-stability-severity.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_digest_stability_status": "digest_recently_shifted",
            "operator_digest_stability_severity": "unknown",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator digest stability: digest_recently_shifted" in result.stdout
    assert "Operator digest stability severity: unknown" not in result.stdout
    assert "Operator escalation effective mode: browser" in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_digest_stability_explanation_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-digest-stability-explanation-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-digest-stability-explanation.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_digest_stability_status": "digest_recently_shifted",
            "operator_digest_stability_explanation": "unknown",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator digest stability: digest_recently_shifted" in result.stdout
    assert "Operator digest stability explanation: unknown" not in result.stdout
    assert "Operator escalation effective mode: browser" in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_final_guidance_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-final-guidance-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-final-guidance.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_final_guidance_message": "unknown",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator final guidance: unknown" not in result.stdout
    assert "Operator escalation effective mode: browser" in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_escalation_reason_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-escalation-reason-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-escalation-reason.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "unknown",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator escalation effective mode: browser" in result.stdout
    assert "Operator escalation reason: unknown" not in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_source_stability_severity_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-source-stability-severity-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-source-stability-severity.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_escalation_source_stability_status": "source_recently_shifted",
            "operator_escalation_source_stability_severity": "unknown",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator escalation source stability: source_recently_shifted" in result.stdout
    assert "Operator escalation source stability severity: unknown" not in result.stdout
    assert "Operator escalation effective mode: browser" in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_source_stability_explanation_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-source-stability-explanation-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-source-stability-explanation.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_escalation_current_source": "recovery_policy",
            "operator_escalation_source_stability_status": "source_recently_shifted",
            "operator_escalation_source_stability_explanation": "unknown",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator escalation current source: recovery_policy" in result.stdout
    assert "Operator escalation source stability: source_recently_shifted" in result.stdout
    assert "Operator escalation source stability explanation: unknown" not in result.stdout
    assert "Operator escalation effective mode: browser" in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_intervention_status_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-intervention-status-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-intervention-status.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "intervention_status": "unknown",
            "intervention_priority": "high",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator intervention status: unknown" not in result.stdout
    assert "Operator intervention priority: high" in result.stdout
    assert "Operator escalation effective mode: browser" in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_intervention_priority_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-intervention-priority-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-intervention-priority.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "intervention_status": "intervention_required",
            "intervention_priority": "unknown",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator intervention status: intervention_required" in result.stdout
    assert "Operator intervention priority: unknown" not in result.stdout
    assert "Operator escalation effective mode: browser" in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_intervention_reason_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-intervention-reason-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-intervention-reason.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "intervention_status": "intervention_required",
            "intervention_priority": "high",
            "intervention_reason": "unknown",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator intervention status: intervention_required" in result.stdout
    assert "Operator intervention priority: high" in result.stdout
    assert "Operator intervention reason: unknown" not in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_intervention_stability_severity_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-intervention-stability-severity-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-intervention-stability-severity.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "intervention_status": "intervention_required",
            "intervention_stability_status": "escalating",
            "intervention_stability_severity": "unknown",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator intervention status: intervention_required" in result.stdout
    assert "Operator intervention stability: escalating" in result.stdout
    assert "Operator intervention stability severity: unknown" not in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_intervention_stability_explanation_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-intervention-stability-explanation-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-intervention-stability-explanation.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "intervention_status": "intervention_required",
            "intervention_stability_status": "escalating",
            "intervention_stability_explanation": "unknown",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator intervention status: intervention_required" in result.stdout
    assert "Operator intervention stability: escalating" in result.stdout
    assert "Operator intervention stability explanation: unknown" not in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_intervention_stability_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-intervention-stability-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-intervention-stability.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "intervention_status": "intervention_required",
            "intervention_stability_status": "unknown",
            "intervention_stability_severity": "high",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator intervention status: intervention_required" in result.stdout
    assert "Operator intervention stability: unknown" not in result.stdout
    assert "Operator intervention stability severity: high" in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_intervention_stability_action_hint_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-intervention-stability-action-hint-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-intervention-stability-action-hint.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "intervention_status": "intervention_required",
            "intervention_stability_status": "escalating",
            "intervention_stability_action_hint": "unknown",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator intervention status: intervention_required" in result.stdout
    assert "Operator intervention stability: escalating" in result.stdout
    assert "Operator intervention stability action hint: unknown" not in result.stdout
    assert "Operator action hint: follow recovery policy escalation guidance" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_follow_up_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-follow-up-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-follow-up.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "lifecycle_follow_up": "unknown",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator follow-up: unknown" not in result.stdout
    assert "Operator escalation effective mode: browser" in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_omits_unknown_suggested_mode_banner(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-suggested-mode-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-suggested-mode.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "lifecycle_suggested_mode": "unknown",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator suggested mode: unknown" not in result.stdout
    assert "Operator escalation effective mode: browser" in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_treats_unknown_action_hint_as_missing_for_recovery_policy(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-action-hint-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-action-hint.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_action_hint": "unknown",
            "lifecycle_follow_up": "prefer_browser_and_investigate_escalation",
            "lifecycle_suggested_mode": "browser",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator action hint: unknown" not in result.stdout
    assert "Operator action hint: follow recovery policy escalation guidance; suggested mode=browser" in result.stdout
    assert "Operator follow-up: prefer_browser_and_investigate_escalation" not in result.stdout
    assert "Operator suggested mode: browser" not in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_treats_unknown_audit_message_as_missing(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-unknown-audit-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-unknown-audit.json"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_escalation_audit_message": "unknown",
            "operator_final_guidance_message": "Escalating intervention: prefer browser and investigate escalating intervention.",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert "Operator escalation audit: unknown" not in result.stdout
    assert "Operator final guidance: Escalating intervention: prefer browser and investigate escalating intervention." in result.stdout
    assert "Operator escalation reason: repeated_repin_cycle_detected" in result.stdout


def test_seed_hybrid_collector_batch_deduplicates_matching_intervention_stability_action_hint(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-intervention-hint-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-intervention.json"
    shared_hint = "follow recovery policy escalation guidance; suggested mode=browser"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "intervention_status": "intervention_required",
            "intervention_priority": "high",
            "intervention_reason": "repeated_repin_cycle_detected",
            "intervention_stability_status": "persistent_noninfo",
            "intervention_stability_severity": "high",
            "intervention_stability_explanation": "Persistent intervention required: keep browser mode active.",
            "intervention_stability_action_hint": shared_hint,
            "operator_action_hint": shared_hint,
            "lifecycle_suggested_mode": "browser",
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert f"Operator intervention stability action hint: {shared_hint}" not in result.stdout
    assert f"Operator action hint: {shared_hint}" in result.stdout


def test_seed_hybrid_collector_batch_deduplicates_matching_intervention_reason_when_escalation_reason_is_visible(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-intervention-reason-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-intervention-reason.json"
    shared_reason = "repeated_repin_cycle_detected"
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "effective_mode": "browser",
            "top_policy_reason": shared_reason,
            "intervention_status": "intervention_required",
            "intervention_priority": "high",
            "intervention_reason": shared_reason,
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert f"Operator escalation reason: {shared_reason}" in result.stdout
    assert f"Operator intervention reason: {shared_reason}" not in result.stdout


def test_seed_hybrid_collector_batch_deduplicates_digest_message_when_final_guidance_matches_without_audit(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    fake_repo = _copy_repo_batch_to_fake_repo(repo_root, tmp_path, "seed_hybrid_collector.bat")
    log_path = fake_repo / "seed-hybrid-digest-guidance-log.txt"
    summary_path = fake_repo / "hybrid-runtime-summary-digest-guidance.json"
    shared_message = "Escalating intervention: prefer browser and investigate escalating intervention."
    fake_python = _write_fake_python_cmd_with_exit_and_summary(
        fake_repo,
        log_path,
        summary_path=summary_path,
        exit_code=42,
        summary_payload={
            "operator_escalation_source": "recovery_policy",
            "recovery_policy_status": "escalate_repeated_repin",
            "effective_mode": "browser",
            "top_policy_reason": "repeated_repin_cycle_detected",
            "operator_final_guidance_message": shared_message,
            "operator_digest_status": "intervention_required",
            "operator_digest_priority": "high",
            "operator_digest_message": shared_message,
        },
    )
    (fake_repo / "tools").mkdir(parents=True, exist_ok=True)
    _write_real_python_target(fake_repo / "tools" / "run_hybrid_seed_collection.py", log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)
    env["HYBRID_FAIL_ON_OPERATOR_ESCALATION"] = "1"
    env["HYBRID_RUNTIME_SUMMARY_PATH"] = str(summary_path)
    env["HYBRID_OPERATOR_ESCALATION_EXIT_CODE"] = "42"

    result = _run_batch(fake_repo / "auto" / "seed_hybrid_collector.bat", env)

    assert result.returncode == 42
    assert f"Operator final guidance: {shared_message}" in result.stdout
    assert "Operator digest status: intervention_required" in result.stdout
    assert "Operator digest priority: high" in result.stdout
    assert f"Operator digest: {shared_message}" not in result.stdout


def test_seed_hybrid_collector_batch_smoke_runs_against_actual_repo_with_stub_python(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[2]
    log_path = tmp_path / "actual-seed-hybrid-log.txt"
    fake_python = _write_fake_python_cmd(tmp_path, log_path)

    env = os.environ.copy()
    env["PYTHON_CMD"] = str(fake_python)

    result = subprocess.run(
        ["cmd", "/c", str(repo_root / "auto" / "seed_hybrid_collector.bat")],
        cwd=str(repo_root),
        env=env,
        input="\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    assert result.returncode == 0
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("STUB_CWD=")
    invoked_cwd = Path(lines[0].split("=", 1)[1])
    assert invoked_cwd.parts[-3:] == ("project", "project", "fapaifang")
    assert lines[1].startswith("STUB_ARGS=tools/run_hybrid_seed_collection.py")
    assert "--submit" in lines[1]
    assert "--loop" in lines[1]
    assert "--open-browser-fallback" in lines[1]
    assert "--mode \"hybrid\"" in lines[1]
    assert "--respect-operator-guidance" in lines[1]
