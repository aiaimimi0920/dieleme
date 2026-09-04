from tools.test.operator_entrypoint_smoke_context import *  # noqa: F401,F403


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
    assert _path_matches_windows_drive_alias(invoked_cwd, repo_root)
    assert lines[1].startswith("STUB_ARGS=tools/run_hybrid_seed_collection.py")
    assert "--submit" in lines[1]
    assert "--loop" in lines[1]
    assert "--open-browser-fallback" in lines[1]
    assert "--mode \"hybrid\"" in lines[1]
    assert "--respect-operator-guidance" in lines[1]
