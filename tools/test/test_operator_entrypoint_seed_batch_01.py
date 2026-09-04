from tools.test.operator_entrypoint_smoke_context import *  # noqa: F401,F403


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
