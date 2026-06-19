# Taobao Login Health Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe Taobao/SF login-health helper that reuses the existing Edge CDP profile, opens the official login or verification page when needed, and lets collectors recover after the operator completes QR/security verification.

**Architecture:** The helper is a small CLI under `tools/` with pure classification functions for unit tests and injectable CDP/page operations for live use. Seed collector retryable challenge summaries will include an operator action hint pointing to this helper. No account credentials or cookies are printed or persisted by the helper.

**Tech Stack:** Python stdlib, existing Playwright CDP endpoint, existing `tools.browserless_seed_probe` list-page summary/payload helpers, pytest.

---

### Task 1: Add Taobao login-health classification tests

**Files:**
- Create: `tools/test/test_taobao_login_health.py`
- Create: `tools/taobao_login_health.py`

- [ ] Write tests for classifying healthy list payload, login page, punish/challenge page, and CLI-safe hint fields.
- [ ] Run the new tests and verify they fail because `tools.taobao_login_health` does not exist.

### Task 2: Implement login-health helper

**Files:**
- Create: `tools/taobao_login_health.py`

- [ ] Implement pure helpers: `classify_taobao_health`, `build_login_url`, `build_operator_hint`, and `check_taobao_health` with injectable fetch/open functions.
- [ ] Implement CLI arguments: `--cdp-endpoint`, `--check-url`, `--open-login`, `--wait-seconds`, `--poll-seconds`, `--json`.
- [ ] Ensure JSON output never includes cookie values or account credentials.
- [ ] Run `python -m pytest tools/test/test_taobao_login_health.py -q` and verify it passes.

### Task 3: Add seed collector recovery hint

**Files:**
- Modify: `tools/seed_collector.py`
- Modify: `tools/test/test_seed_collector.py`

- [ ] Add a failing test asserting retryable Taobao challenge summaries include a `login_recovery` action hint.
- [ ] Add minimal summary fields with the exact command operators can run.
- [ ] Run targeted seed collector tests.

### Task 4: Verify regression set

**Files:**
- No new files.

- [ ] Run `python -m pytest tools/test/test_taobao_login_health.py tools/test/test_seed_collector.py tools/test/test_start_taobao_cdp_browser_script.py -q`.
- [ ] Report exact output and any remaining live risk.
