from tools.test.operator_entrypoint_smoke_context import *  # noqa: F401,F403


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
