# Continuous FapaiFang Collection Design

## Goal

Run FapaiFang as a long-lived, DB-backed collector that continuously discovers and enriches as many Taobao/SF legal-auction property listings as the current account, network, and Taobao controls allow.

## Approved operating model

Use the existing Docker long-running worker model:

- `fapaifang-seed-collector` and `fapaifang-seed-collector-2` scan list pages and enqueue unique seed items.
- `fapaifang-detail-worker` consumes queued detail URLs and writes canonical detail outputs.
- PostgreSQL remains the source of truth for scan progress, seed item status, leases, retry counts, and completed details.
- Taobao login state is supplied by a visible Edge/Chrome CDP profile and refreshed cookie snapshot.

## Full-coverage definition

The first full-coverage implementation will generate seed jobs from:

- every six-digit `location_code` in `datas/all_locations.json`;
- categories `50025969` and `200782003`;
- sort params `2`, `1`, `0`, `3`, `4`, `5`;
- `max_page=83` per location/category job unless overridden.

This is an operational definition of "all collectable" for the current codebase. It can be extended later if Taobao exposes more legal-auction categories or the location tree changes.

## Human verification boundary

The system may detect, open, and foreground official Taobao verification pages, but it must not solve, drag, bypass, or fake captcha/security checks. When a health check reports `punish_page`, `captcha_page`, or `challenge_required`, the watchdog opens the official page and waits for the operator to complete it manually.

After a successful verification, the watchdog refreshes `C:\Users\Public\nas_home\AI\FPFData\secrets\taobao-cookies.json` so workers can continue through `FAPAI_COOKIE_SNAPSHOT=/data/secrets/taobao-cookies.json`.

## Components

1. Full seed job generator
   - Reads `datas/all_locations.json`.
   - Preserves province/city/district names when present.
   - Writes a JSON array compatible with `tools/seed_collector.py`.

2. Seed collector jobs-file support
   - Adds `--jobs-file` and `FAPAI_SEED_JOBS_FILE`.
   - Uses jobs file before `--jobs-json`.
   - Keeps current single-job fallback.

3. Taobao login watchdog
   - Runs safe health checks.
   - Opens/foregrounds official Taobao verification when blocked.
   - Waits for manual verification.
   - Exports cookie snapshot on success.

4. Continuous collection starter
   - Creates host data directories.
   - Generates full seed jobs.
   - Starts CDP browser.
   - Performs login health recovery if required.
   - Exports cookie snapshot.
   - Starts Docker seed/detail workers.

5. Scheduled task registration
   - Registers the login watchdog under `\FapaiFang\FapaiFangTaobaoLoginWatchdog`.
   - Uses the current interactive user so the browser can become visible.

## Safety rules

- Do not print cookie values or Taobao security token values.
- Do not print `docker.local.env` contents.
- Do not restart or recreate PostgreSQL from these helper scripts.
- Do not use `--remove-orphans`.
- Keep cookie files outside the Git working tree.
