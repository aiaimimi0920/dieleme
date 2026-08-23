# PC2 host-direct workers

This runbook documents the current PC2 host-direct worker layout used for the
real collection cutover path.

## Worker roles

- `pc2-real-seed-1`
  - Runs the seed queue loop directly on the PC2 host.
  - Uses DB-backed queue claiming and `FOR UPDATE SKIP LOCKED` semantics through
    the repository layer.
  - Uses the automatic node-local solver for real Taobao challenges when the
    solver flag is enabled; manual reporting remains an explicit fallback.
- `pc2-real-detail-1`
  - Raw detail capture worker.
  - Uses the automatic node-local solver when the solver flag is enabled, with
    manual challenge reporting available as the explicit fallback.
- `pc2-real-detail-2`
  - Second raw detail capture worker wrapping the same primary detail launcher
    with a distinct worker id.
- `pc2-real-detail-3`
  - HTTP-biased detail worker variant with browser fallback override disabled.
- `pc2-real-detail-4` through `pc2-real-detail-8`
  - Dynamically generated detail workers with browser fallback disabled. They
    still respect the collector CDP health gate unless external cookie-snapshot
    mode makes CDP unnecessary. The watchdog starts four detail workers by
    default and accepts a bounded count from 3 through 8.
- `pc2-real-analysis-1`
  - Primary analysis worker for AI finalization from previously captured raw detail
    artifacts.
- `pc2-real-analysis-2`
  - Second independently leased analysis worker, enabled after a bounded PC2
    concurrency canary confirmed that two workers can finalize in parallel.
- `pc2-real-analysis-3`
  - Third independently leased analysis worker, enabled after a bounded live
    canary confirmed that three concurrent `grok-4.5` requests can finalize
    without increasing `analysis_failed`.
- `pc2-real-analysis-4` through `pc2-real-analysis-8`
  - Dynamically generated analysis workers using the same production model and
    isolated leases/output directories. The watchdog starts four by default;
    higher counts must be enabled incrementally after a throughput/error canary.

## Authentication and quiescing behavior

- Host-direct workers run against the local PC2 CDP browser by default.
- The watchdog can quiesce workers while the shared auth/CDP browser is being
  recovered.
- A manual detail-page challenge quiesces raw-detail workers, while the
  scope-aware seed worker remains supervised and only pauses for list-stage
  challenges.
- The automatic solver remains enabled when the node solver flag is on. Manual
  challenge reporting is the fallback when the solver flag is off and the API
  advertises `manual_captcha_report_v1`.
- If a human temporarily owns the auth tab, browser fallbacks can still be
  turned down independently without deleting the runtime wiring.

## Environment expectations

- `FAPAI_CDP_ENDPOINT=http://127.0.0.1:9223` for local-only mode, or
  `http://127.0.0.1:9225` when PC2 uses the supported PC1 shared-auth tunnel.
- `FAPAI_DETAIL_CDP_ENDPOINT` defaults to the same PC2-local endpoint when not
  overridden.
- `FAPAI_SEED_CAPTCHA_SOLVER_ENABLED` and `FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED`
  default to the node-wide `FAPAI_CAPTCHA_SOLVER_ENABLED` setting. When enabled,
  real `*.taobao.com` challenges are sent to the node-local automatic solver.
- `FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED=1` must be set on both the NAS API and
  PC2 before real Taobao requests leave `manual_only`. It is an explicit opt-in;
  the default remains `0` so other deployments fail closed.
- `FAPAI_SOLVER_MANUAL_FALLBACK_ENABLED=0` keeps automatic solving primary after
  repeated failures. Set it to `1` only when operations explicitly require a
  persistent human-auth handoff after the configured failure threshold.
- `FAPAI_LIST_BROWSER_FALLBACK=1` and `FAPAI_DETAIL_BROWSER_FALLBACK=1` are the
  normal real-runtime defaults unless a cookie-only auth window is being used.
- `OPENAI_REASONING_EFFORT` is optional and remains unset by default. Enable a
  lower effort only after a fixed-corpus shadow gate confirms that required
  prices, fractional area, full address, and strict JSON output do not regress.
- `FAPAI_HOST_DETAIL_WORKER_COUNT` and `FAPAI_HOST_ANALYSIS_WORKER_COUNT` control
  watchdog concurrency independently. Both default to `4`; accepted values are
  `3` through `8`. Command-line `-DetailWorkerCount` and `-AnalysisWorkerCount`
  override the environment for bounded canaries.
- Keep `OPENAI_MODEL_CANDIDATES` empty in production concurrency runs. Scale one
  quality-gated model horizontally so output quality is not mixed by routing.
- In shared-auth cookie-only mode, `FAPAI_CDP_EXTERNAL=1` plus
  `FAPAI_COOKIE_SNAPSHOT_PREFER=1` means snapshot freshness matters more than
  local PC2 browser recovery.
- The raw-detail launcher defaults to batches of 10 successes / 30 attempts,
  with no delay after successful items or productive batches. Override with
  `FAPAI_HOST_DETAIL_TARGET_SUCCESS`, `FAPAI_HOST_DETAIL_MAX_ATTEMPTS`,
  `FAPAI_HOST_DETAIL_SUCCESS_DELAY_SECONDS`,
  `FAPAI_HOST_DETAIL_FAILURE_DELAY_SECONDS`, and
  `FAPAI_HOST_DETAIL_ACTIVE_LOOP_INTERVAL_SECONDS` only after measuring NAS
  database and PC2 CDP load.

## Related scripts

- `ops/pc2-host/load-host-direct-nas-env.ps1`
- `ops/pc2-host/start-host-direct-seed-worker.ps1`
- `ops/pc2-host/start-host-direct-detail-worker.ps1`
- `ops/pc2-host/start-host-direct-detail-worker-2.ps1`
- `ops/pc2-host/start-host-direct-detail-worker-3.ps1`
- `ops/pc2-host/start-host-direct-analysis-worker.ps1`
- `ops/pc2-host/start-host-direct-analysis-worker-2.ps1`
- `ops/pc2-host/start-host-direct-analysis-worker-3.ps1`
- `ops/pc2-host/launch-host-direct-workers.ps1`
- `ops/pc2-host/import-host-direct-analysis-env.ps1`
- `ops/pc2-host/apply-worker-concurrency-env.ps1`
- `ops/pc2-host/install-concurrency-runtime.ps1`
- `ops/pc2-host/watch-pc2-cdp-self-heal.ps1`
- `ops/pc2-host/register-pc2-cdp-self-heal.ps1`
- `scripts/register-pc1-shared-auth-maintenance.ps1`
- `scripts/deploy-pc2-llm-helper-hotfix.ps1`
- `scripts/optimize-pc2-external-cdp-host.ps1`

## Operational note

The current deployment runs collection and analysis on PC2 against the local
`127.0.0.1:9223` authentication browser. The PC2 automatic solver is enabled;
manual confirmation is an explicit fallback and must not silently replace the
automatic path.

`FapaiPc2CdpSelfHeal` runs the dedicated CDP recovery watchdog in the logged-in
PC2 session. It checks both CDP metadata and page targets every 60 seconds. Three
consecutive CDP failures, or a node-owned authentication confirmation stuck for
five minutes, triggers a bounded recovery: stop CDP-dependent runtime processes,
force-restart the dedicated browser, require a healthy CDP page target, clear
only the matching challenge through the idempotent cooldown-resume API, and then
restart the solver and worker launcher. It never uses the unguarded operator
resume endpoint.

When PC2 is intentionally pinned to the PC1 shared-auth bridge, keep the cookie
snapshot maintenance tasks enabled on PC1 and trim the unused local `9223` Edge
profile on PC2 before touching heavier system components such as Docker Desktop
or Defender.
