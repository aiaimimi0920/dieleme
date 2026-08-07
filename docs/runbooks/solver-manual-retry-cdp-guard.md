# Solver manual-retry CDP guard

The server-side captcha solver manual-retry loop probes the CDP endpoint before it
re-submits a solver request. When the browser is gone, the retry is skipped and the
`manual_required` state is preserved instead of being cleared and re-raised on a loop.

## Why this guard exists

`_trigger_manual_solver_retry_if_due()` used to retry on a fixed interval without
checking whether the target browser was still reachable. When a collector PC lost its
CDP browser, every cycle would:

1. see `manual_required`;
2. clear the `manual_required` pause and the force-unlock flag;
3. submit a solver request;
4. block inside `_wait_for_solver_cdp_ready()` until it timed out; and
5. mark `manual_required` again.

That loop cannot succeed, because a captcha cannot be solved without a live browser.
It ran for roughly a month on the NAS deployment and reached
`manual_retry_attempts: 3372` while every collection counter stayed flat. The
`manual_required` pause was also being cleared every cycle, so the surfaced state
oscillated instead of reporting a stable "operator needed" signal.

The external PowerShell monitor already had this protection and logged
`reason=cdp_endpoint_unhealthy`. Only the in-server retry path was missing it.

## What it checks

Before clearing the pause and submitting, the retry path calls
`_probe_solver_cdp_endpoint()` with the `cdp_endpoint` of the resolved solver request:

- a `GET {cdp_endpoint}/json/version` that must return parseable JSON;
- any exception, timeout, or non-JSON body counts as unhealthy;
- a request with **no** `cdp_endpoint` is treated as healthy, so pure `target_url`
  retries are not blocked.

When the probe fails, the retry returns without side effects other than the cooldown:

```json
{"queued": false, "reason": "cdp_endpoint_unhealthy", "cdp_endpoint": "http://192.168.15.104:9224"}
```

- `PAUSED` and `COLLECTION_PAUSE_REASON` stay as they were;
- the force-unlock flag file is left in place;
- `SOLVER_MANUAL_RETRY_ATTEMPTS` is **not** incremented, so that counter keeps
  meaning "real solver submissions" and stays useful as a runaway signal;
- `SOLVER_MANUAL_RETRY_LAST_EPOCH` **is** set, so the probe follows the retry
  interval rather than firing on every poll cycle.

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `FAPAI_SOLVER_CDP_PROBE_TIMEOUT_SECONDS` | `3` | Per-probe HTTP timeout, clamped to `[0.5, 30]`. |
| `FAPAI_SOLVER_MANUAL_RETRY_INTERVAL_SECONDS` | `180` | Existing retry cooldown; now also paces the probe. |

The guard has no disable switch by design. Retrying a solver against an unreachable
browser has no success path, so there is no configuration in which skipping is wrong.

## Operator flow when this trips

A `cdp_endpoint_unhealthy` skip means the pipeline needs a human, not another retry.

1. Confirm the endpoint really is down from the API host:
   `curl http://<collector-ip>:9224/json/version`
2. Start the CDP browser on that collector PC:
   `scripts/start-taobao-cdp-browser.ps1`
3. Complete the Taobao login interactively. The captcha in this state is a login
   challenge and cannot be solved headlessly.
4. The next retry cycle probes successfully and resumes on its own. No manual
   force-unlock is required.

## Related tests

`tools/test/test_server_collection_api_status.py`

- `test_manual_required_auto_retry_skips_when_cdp_endpoint_is_unreachable`
- `test_manual_required_auto_retry_queues_when_cdp_endpoint_is_reachable`
- `test_probe_solver_cdp_endpoint_reports_unreachable_endpoint_as_unhealthy`
- `test_probe_solver_cdp_endpoint_treats_missing_endpoint_as_healthy`
