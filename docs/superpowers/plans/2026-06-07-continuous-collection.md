# Continuous FapaiFang Collection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a normal-operation collection path that generates full seed jobs, starts long-running collectors, and pops official Taobao verification pages for manual intervention when required.

**Architecture:** Add a file-based seed job source to avoid oversized environment variables, generate jobs from `datas/all_locations.json`, and add PowerShell operator scripts for login watchdog and continuous startup. The existing DB-backed seed/detail workers remain the runtime core.

**Tech Stack:** Python 3.10, pytest, PowerShell, Docker Compose, Playwright CDP through existing health helpers.

---

## File map

- Create `tools/generate_seed_jobs.py`: pure Python generator for full seed job files.
- Create `tools/test/test_generate_seed_jobs.py`: unit tests for location tree flattening and CLI output.
- Modify `tools/seed_collector.py`: add `--jobs-file` / `FAPAI_SEED_JOBS_FILE`.
- Modify `tools/docker_entrypoint.py`: pass `--jobs-file`.
- Modify `docker-compose.collection.yml`: expose `FAPAI_SEED_JOBS_FILE`.
- Create `scripts/generate-all-seed-jobs.ps1`: host wrapper around the generator.
- Create `scripts/taobao-login-watchdog.ps1`: safe login health watchdog.
- Create `scripts/register-taobao-login-watchdog-task.ps1`: Windows scheduled task registration.
- Create `scripts/start-continuous-collection.ps1`: operator entrypoint for full continuous collection.
- Modify `README.md`: document the continuous workflow.
- Add or update tests under `tools/test/` for each behavior.

## Task 1: Full seed job generator

- [ ] Write failing tests in `tools/test/test_generate_seed_jobs.py`:
  - flatten nested location tree into leaf jobs with province/city/district names;
  - generate jobs for two categories and six sorts;
  - write JSON without requiring live network or DB.
- [ ] Run `python -m pytest tools/test/test_generate_seed_jobs.py -q` and confirm it fails because `tools.generate_seed_jobs` is missing.
- [ ] Implement `tools/generate_seed_jobs.py` with `load_location_jobs`, `build_seed_jobs`, and CLI `--locations-file --output --categories --max-page`.
- [ ] Re-run `python -m pytest tools/test/test_generate_seed_jobs.py -q` and confirm it passes.

## Task 2: Seed collector jobs-file support

- [ ] Add failing tests in `tools/test/test_seed_collector.py` for `FAPAI_SEED_JOBS_FILE`.
- [ ] Add failing test in `tools/test/test_docker_entrypoint.py` for `--jobs-file` command passthrough and compose env.
- [ ] Run targeted tests and confirm expected failures.
- [ ] Implement `parse_seed_job_specs_file` and CLI/env wiring.
- [ ] Re-run targeted tests and confirm green.

## Task 3: Operator PowerShell scripts

- [ ] Add tests in `tools/test/test_continuous_collection_scripts.py` that inspect:
  - `scripts/generate-all-seed-jobs.ps1`;
  - `scripts/taobao-login-watchdog.ps1`;
  - `scripts/register-taobao-login-watchdog-task.ps1`;
  - `scripts/start-continuous-collection.ps1`.
- [ ] Verify tests fail because scripts are missing.
- [ ] Implement scripts with safe output, no cookie values, no `--remove-orphans`, and no PostgreSQL restart.
- [ ] Re-run script tests.

## Task 4: Documentation and local env helper

- [ ] Update `README.md` with normal-operation commands.
- [ ] Add documented defaults:
  - `FAPAI_SEED_JOBS_FILE=/data/jobs/seed_jobs_all.json`
  - `FAPAI_COOKIE_SNAPSHOT=/data/secrets/taobao-cookies.json`
  - `FAPAI_SEED_RESCAN_INTERVAL_SECONDS=900`
- [ ] Run targeted docs/script tests.

## Task 5: Verification

- [ ] Run:
  `python -m pytest tools/test/test_generate_seed_jobs.py tools/test/test_seed_collector.py tools/test/test_docker_entrypoint.py tools/test/test_continuous_collection_scripts.py tools/test/test_start_taobao_cdp_browser_script.py tools/test/test_taobao_login_health.py -q`
- [ ] Run related regression:
  `python -m pytest tools/test/test_live_batch_smoke.py tools/test/test_detail_worker.py tools/test/test_seed_collector.py tools/test/test_seed_queue_repository.py tools/test/test_docker_entrypoint.py tools/test/test_start_taobao_cdp_browser_script.py tools/test/test_taobao_login_health.py tools/test/test_browserless_seed_probe.py tools/test/test_generate_seed_jobs.py tools/test/test_continuous_collection_scripts.py -q`
- [ ] Generate a real jobs file under the host data root and report counts only.
- [ ] Run login health check and cookie snapshot probe without printing sensitive values.
