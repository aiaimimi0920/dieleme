from tools.test.operator_entrypoint_smoke_context import *  # noqa: F401,F403


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
