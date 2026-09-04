from __future__ import annotations
from tools.pc2_solver_context import *  # noqa: F401,F403
from tools.pc2_solver_transport import *  # noqa: F401,F403
from tools.pc2_solver_scope import *  # noqa: F401,F403
from tools.pc2_solver_auth import *  # noqa: F401,F403
from tools.pc2_solver_fallback import *  # noqa: F401,F403
from tools.pc2_solver_auth_pending import *  # noqa: F401,F403
from tools.pc2_solver_cdp import *  # noqa: F401,F403
from tools.pc2_solver_execution import *  # noqa: F401,F403
from tools.pc2_solver_loop_control import *  # noqa: F401,F403


def local_solver_loop(api_base_url=None, cdp_endpoint=None, poll_seconds=None, max_attempts=None, expected_node_id=None):
    if api_base_url is None: api_base_url = DEFAULT_API_BASE_URL
    if cdp_endpoint is None: cdp_endpoint = DEFAULT_CDP_ENDPOINT
    if poll_seconds is None: poll_seconds = DEFAULT_POLL_SECONDS
    if max_attempts is None: max_attempts = DEFAULT_MAX_ATTEMPTS
    log_event({
        "kind": "local_solver_boot",
        "api_base_url": api_base_url,
        "cdp_endpoint": cdp_endpoint,
        "poll_seconds": poll_seconds,
        "max_attempts": max_attempts,
        "expected_node_id": expected_node_id,
        "real_taobao_auto_solver_enabled": real_taobao_auto_solver_enabled(),
        "cooldown_fail_threshold": SOLVER_COOLDOWN_FAIL_THRESHOLD,
        "cooldown_seconds": SOLVER_COOLDOWN_SECONDS,
        "slider_retry_interval_seconds": SLIDER_RETRY_INTERVAL_SECONDS,
    })
    write_solver_heartbeat("waiting_for_cdp")
    while not check_cdp_healthy(cdp_endpoint):
        write_solver_heartbeat("waiting_for_cdp")
        log_event({"kind": "waiting_for_cdp", "cdp_endpoint": cdp_endpoint})
        time.sleep(5)
    last_probe_target = None
    last_auth_confirmed_at = 0.0
    while True:
        write_solver_heartbeat("polling")
        try:
            pending_control = process_pending_control_actions(
                api_base_url=api_base_url,
                cdp_endpoint=cdp_endpoint,
                expected_node_id=expected_node_id,
                poll_seconds=poll_seconds,
                last_probe_target=last_probe_target,
                last_auth_confirmed_at=last_auth_confirmed_at,
            )
            last_probe_target = pending_control["last_probe_target"]
            last_auth_confirmed_at = pending_control["last_auth_confirmed_at"]
            if pending_control["handled"]:
                continue
            solver_status = read_solver_status(api_base_url)
            if "error" in solver_status:
                log_event({"kind": "status_error", "error": solver_status["error"]})
                time.sleep(poll_seconds); continue
            compaction = compact_active_challenge_pages(cdp_endpoint, solver_status)
            if compaction.get("closed"):
                log_event({
                    "kind": "scoped_challenge_tabs_compacted",
                    "closed": compaction.get("closed"),
                    "scopes": compaction.get("scopes"),
                })
            solver_status = reset_forced_solver_scopes(
                api_base_url,
                cdp_endpoint,
                solver_status,
                expected_node_id,
            )
            fallback_state = _load_fallback_state()
            solver_status = select_solver_scope_status(
                solver_status,
                preferred_challenge_id=fallback_state.get("challenge_id"),
            )
            paused = bool(solver_status.get("paused"))
            running = bool(solver_status.get("running"))
            manual_required = bool(solver_status.get("manual_required"))
            if (
                solver_status_requires_manual_only(solver_status)
                and not manual_challenge_registration_needed(solver_status)
            ):
                log_event({"kind": "waiting_for_manual_auth", "challenge_id": solver_status.get("challenge_id")})
                time.sleep(poll_seconds)
                continue
            # Manual escalation is opt-in. A stale fallback latch must never disable
            # the automatic solver after an operator turns manual fallback off.
            fallback_state, challenge_reset = _sync_challenge_state(
                fallback_state,
                solver_status.get("challenge_id"),
                scope=solver_status.get("scope"),
            )
            if challenge_reset:
                last_probe_target = None
                log_event({
                    "kind": "slider_challenge_changed",
                    "challenge_id": fallback_state.get("challenge_id"),
                })
            cooldown_started = _begin_solver_cooldown_if_needed(fallback_state)
            if cooldown_started:
                _save_fallback_state(fallback_state)
                log_event({
                    "kind": "solver_cooldown_started",
                    "until": fallback_state["solver_cooldown_until"],
                    "seconds": max(0.0, SOLVER_COOLDOWN_SECONDS),
                    "consecutive_failures": fallback_state.get("consecutive_failures", 0),
                })
            blocked_report = _retry_node_solver_blocked_report(
                api_base_url,
                solver_status,
                fallback_state,
                expected_node_id=expected_node_id,
            )
            if blocked_report.get("attempted"):
                log_event({
                    "kind": "node_solver_blocked_report",
                    "confirmed": blocked_report.get("confirmed"),
                    "attempt": fallback_state.get("node_solver_blocked_report_attempts", 0),
                    "result_status": (blocked_report.get("result") or {}).get("status"),
                    "error": (blocked_report.get("result") or {}).get("error"),
                })
            if _solver_cooldown_active(fallback_state):
                _save_fallback_state(fallback_state)
                log_event({
                    "kind": "solver_cooldown_active",
                    "until": fallback_state.get("solver_cooldown_until"),
                    "reason": fallback_state.get("solver_cooldown_reason"),
                    "consecutive_failures": fallback_state.get("consecutive_failures", 0),
                })
                time.sleep(poll_seconds)
                continue
            cooldown_until = float(fallback_state.get("solver_cooldown_until") or 0)
            if cooldown_until and cooldown_until <= time.time():
                fallback_state = _mark_collection_resume_pending(fallback_state)
                log_event({
                    "kind": "solver_cooldown_elapsed",
                    "resume_request_id": fallback_state.get("collection_resume_request_id"),
                })
                resume_result = _retry_pending_collection_resume(
                    api_base_url,
                    state=fallback_state,
                )
                if resume_result.get("confirmed"):
                    cleanup_target = resolve_stale_challenge_probe_target_after_resume(
                        cdp_endpoint,
                        last_probe_target,
                        resume_result,
                    )
                    cleanup = close_stale_challenge_probe_target(cdp_endpoint, cleanup_target)
                    last_probe_target = None
                    last_auth_confirmed_at = time.time()
                    local_solver_loop._probe_counter = 0
                    log_event({
                        "kind": "collection_resume_confirmed",
                        "result": resume_result.get("result"),
                        "challenge_target_cleanup": cleanup,
                    })
                else:
                    log_event({
                        "kind": "collection_resume_pending",
                        "request_id": fallback_state.get("collection_resume_request_id"),
                        "next_retry_at": resume_result.get("next_retry_at"),
                        "result": resume_result.get("result"),
                    })
                time.sleep(poll_seconds)
                continue
            if fallback_state.get("manual_pushed"):
                if not manual_required:
                    # PC1 manual auth completed/cleared; reset fallback state
                    log_event({"kind": "fallback_manual_resolved"})
                    _reset_fallback_state()
                elif _manual_fallback_latch_active(fallback_state, manual_required):
                    log_event({"kind": "fallback_waiting_manual_auth", "manual_required": manual_required})
                    time.sleep(poll_seconds); continue
                else:
                    log_event({"kind": "fallback_manual_latch_bypassed", "manual_required": manual_required})
                    _reset_fallback_state()
            # Primary trigger: API says paused + not running (standard flow)
            api_trigger = paused and not running
            last_request = solver_status.get("last_request")
            requested_target_urls = solver_request_target_urls(last_request)
            requested_target_url = requested_target_urls[0] if requested_target_urls else ""
            # Secondary trigger: probe CDP for slider whenever manual_required is set.
            # The Docker solver keeps resetting the API state via manual_retry, so we check CDP directly.
            cdp_trigger = False
            probe_target = None
            probe_request_target_url = ""
            if manual_required or api_trigger:
                for candidate_target_url in requested_target_urls or [None]:
                    slider_found = check_cdp_browser_for_slider(
                        cdp_endpoint,
                        target_url=candidate_target_url,
                    )
                    if slider_found:
                        log_event({"kind": "cdp_probe_slider_found", "slider": slider_found})
                        cdp_trigger = True
                        probe_target = slider_found
                        probe_request_target_url = str(candidate_target_url or "")
                        last_probe_target = slider_found
                        break
                    requested_route = CaptchaSolver(
                        cdp_endpoint=cdp_endpoint,
                        target_url=candidate_target_url,
                    )._solver_target_route(candidate_target_url)
                    log_event({
                        "kind": "cdp_probe_no_slider",
                        "running": running,
                        "paused": paused,
                        "requested_route": requested_route,
                    })
                    challenge_found = check_cdp_browser_for_challenge_page(
                        cdp_endpoint,
                        target_url=candidate_target_url,
                    )
                    if challenge_found:
                        log_event({
                            "kind": "cdp_probe_challenge_page",
                            "target": challenge_found,
                        })
                        cdp_trigger = True
                        probe_target = challenge_found
                        probe_request_target_url = str(candidate_target_url or "")
                        last_probe_target = challenge_found
                        break
                if not cdp_trigger:
                    last_probe_target = None

            if api_trigger and not cdp_trigger:
                last_request = solver_status.get("last_request")
                target_url = solver_request_target_url(last_request)
                recent_healthy_snapshot = bool(
                    target_url and _recent_healthy_auth_snapshot(solver_status)
                )
                authenticated_target = None
                authenticated_target_url = ""
                if not recent_healthy_snapshot:
                    for candidate_target_url in requested_target_urls:
                        authenticated_target = check_cdp_browser_for_authenticated_target(
                            cdp_endpoint,
                            candidate_target_url,
                        )
                        if authenticated_target:
                            authenticated_target_url = candidate_target_url
                            log_event({
                                "kind": "cdp_authenticated_target_found",
                                "target_id": authenticated_target.get("_target_id"),
                            })
                            break
                confirmation_target_url = target_url if recent_healthy_snapshot else authenticated_target_url
                if confirmation_target_url:
                    pending_state = _mark_auth_complete_pending(
                        confirmation_target_url,
                        challenge_id=solver_status.get("challenge_id"),
                    )
                    confirmation = _retry_pending_auth_confirmation(api_base_url, state=pending_state)
                    log_event({
                        "kind": "stale_pause_auth_complete_result",
                        "result": confirmation,
                    })
                    if confirmation.get("confirmed"):
                        last_auth_confirmed_at = time.time()
                        local_solver_loop._probe_counter = 0
                elif (
                    str(solver_status.get("challenge_id") or "").strip()
                    and target_url
                    and node_owns_last_request(
                        solver_status,
                        cdp_endpoint,
                        expected_node_id,
                    )
                ):
                    rebuild = rebuild_missing_challenge_target(cdp_endpoint, target_url)
                    last_probe_target = rebuild.get("probe_target")
                    local_solver_loop._probe_counter = 0
                    log_event({
                        "kind": "missing_challenge_target_rebuild_result",
                        "attempted": bool(rebuild.get("attempted")),
                        "opened": bool(rebuild.get("opened")),
                        "scope": rebuild.get("scope"),
                        "reason": rebuild.get("reason"),
                        "error_type": rebuild.get("error_type"),
                    })
                else:
                    log_event({
                        "kind": "skip_api_pause_without_cdp_challenge",
                        "last_status": solver_status.get("last_status"),
                    })
                time.sleep(poll_seconds)
                continue
            # Periodic CDP probe even when API says not paused, to catch slider after Docker resets state
            _cdp_probe_counter = getattr(local_solver_loop, "_probe_counter", 0) + 1
            local_solver_loop._probe_counter = _cdp_probe_counter
            # Probe every ~30 seconds. The previous calculation multiplied the
            # poll duration by three and then treated that value as an iteration
            # count, turning a 30-second probe into a 5-minute probe at the
            # default 10-second polling interval.
            _probe_interval = max(1, int(30 / max(1, poll_seconds)))
            post_auth_probe_grace = _post_auth_cdp_probe_grace_active(last_auth_confirmed_at)
            if (
                not api_trigger
                and not cdp_trigger
                and not manual_required
                and not post_auth_probe_grace
                and _cdp_probe_counter >= _probe_interval
            ):
                _cdp_probe_counter = 0
                for candidate_target_url in requested_target_urls or [None]:
                    periodic_found = check_cdp_browser_for_slider(
                        cdp_endpoint,
                        target_url=candidate_target_url,
                    )
                    if periodic_found:
                        log_event({"kind": "cdp_periodic_probe_slider_found", "slider": periodic_found})
                        cdp_trigger = True
                        probe_target = periodic_found
                        probe_request_target_url = str(candidate_target_url or "")
                        last_probe_target = periodic_found
                        break
                    challenge_found = check_cdp_browser_for_challenge_page(
                        cdp_endpoint,
                        target_url=candidate_target_url,
                    )
                    if challenge_found:
                        log_event({"kind": "cdp_periodic_probe_challenge_page", "cdp_endpoint": cdp_endpoint})
                        cdp_trigger = True
                        probe_target = challenge_found
                        probe_request_target_url = str(candidate_target_url or "")
                        last_probe_target = challenge_found
                        break
            if not cdp_trigger:
                time.sleep(poll_seconds); continue
            # CDP probing can take several seconds. Re-read the control plane at
            # the execution boundary so a concurrently started NAS solver wins
            # instead of both processes acting on the same browser challenge.
            latest_solver_status = select_solver_scope_status(
                read_solver_status(api_base_url),
                preferred_challenge_id=solver_status.get("challenge_id"),
            )
            execution_block_reason = node_solver_execution_block_reason(
                latest_solver_status,
                cdp_endpoint,
                expected_node_id,
            )
            if execution_block_reason:
                if execution_block_reason == "manual_only" and manual_challenge_registration_needed(
                    latest_solver_status
                ):
                    manual_report = notify_manual_challenge(
                        api_base_url,
                        latest_solver_status,
                        expected_node_id,
                    )
                    report_solver = manual_report.get("captcha_solver")
                    log_event({
                        "kind": "manual_challenge_reported",
                        "status": manual_report.get("status"),
                        "ok": manual_report.get("ok"),
                        "error": manual_report.get("error"),
                        "challenge_id": report_solver.get("challenge_id") if isinstance(report_solver, dict) else None,
                    })
                log_event({"kind": "local_solver_execution_blocked", "reason": execution_block_reason})
                time.sleep(poll_seconds); continue
            solver_status = latest_solver_status
            last_request = solver_status.get("last_request")
            target_url = match_solver_request_target_url(
                last_request,
                probe_request_target_url,
                cdp_endpoint,
            )
            if not target_url:
                log_event({
                    "kind": "skip_probe_target_superseded",
                    "selected_target_url": probe_request_target_url,
                })
                time.sleep(poll_seconds); continue
            if not check_cdp_healthy(cdp_endpoint):
                log_event({"kind": "cdp_unhealthy_before_solve", "cdp_endpoint": cdp_endpoint})
                time.sleep(poll_seconds); continue
            fallback_state = _load_fallback_state()
            if not _slider_retry_due(fallback_state):
                log_event({
                    "kind": "slider_retry_wait",
                    "next_attempt_at": fallback_state.get("slider_next_attempt_at"),
                    "attempts": fallback_state.get("slider_attempts", 0),
                })
                time.sleep(poll_seconds)
                continue
            scheduled_attempt = int(fallback_state.get("slider_attempts", 0) or 0) + 1
            drag_profile_offset = (scheduled_attempt - 1) % max(DEFAULT_DRAG_PROFILE_VARIANTS, 1)
            log_event({
                "kind": "slider_attempt_started",
                "attempt": scheduled_attempt,
                "max_attempts": max(1, SOLVER_COOLDOWN_FAIL_THRESHOLD),
                "drag_profile_offset": drag_profile_offset,
            })
            _record_slider_attempt_started(fallback_state)
            write_solver_heartbeat(
                "solver_attempt",
                challenge_id=fallback_state.get("challenge_id"),
                attempt=scheduled_attempt,
            )
            success = run_solver_local_with_deadline(
                cdp_endpoint,
                target_url,
                max_attempts=max_attempts,
                probe_target=probe_target,
                drag_profile_offset=drag_profile_offset,
            )
            write_solver_heartbeat("polling")
            if success:
                log_event({"kind": "local_solver_success"})
                completed_state = _load_fallback_state()
                completed_state["slider_attempt_started_at"] = None
                completed_state["slider_last_progress_at"] = time.time()
                _save_fallback_state(completed_state)
                completion_status = select_solver_scope_status(
                    read_solver_status(api_base_url),
                    preferred_challenge_id=solver_status.get("challenge_id"),
                )
                completion_challenge_id = _completion_challenge_id(
                    solver_status,
                    completion_status,
                    target_url,
                    cdp_endpoint,
                    expected_node_id,
                )
                log_event({
                    "kind": "auth_completion_challenge_resolved",
                    "started_challenge_id": solver_status.get("challenge_id"),
                    "completion_challenge_id": completion_challenge_id,
                })
                pending_state = _mark_auth_complete_pending(
                    target_url,
                    challenge_id=completion_challenge_id,
                )
                confirmation = _retry_pending_auth_confirmation(api_base_url, state=pending_state)
                log_event({"kind": "auth_complete_result", "result": confirmation})
                if confirmation.get("confirmed"):
                    last_auth_confirmed_at = time.time()
                    local_solver_loop._probe_counter = 0
            else:
                log_event({"kind": "local_solver_failure"})
                rotation = rotate_failed_challenge_target(
                    cdp_endpoint,
                    target_url,
                    probe_target=probe_target,
                )
                rotated_probe = rotation.get("probe_target")
                last_probe_target = rotated_probe if isinstance(rotated_probe, dict) else None
                log_event({
                    "kind": "failed_challenge_target_rotation",
                    "attempted": rotation.get("attempted"),
                    "opened": rotation.get("opened"),
                    "closed": rotation.get("closed", 0),
                    "scope": rotation.get("scope"),
                    "reason": rotation.get("reason"),
                    "error_type": rotation.get("error_type"),
                })
                state = _load_fallback_state()
                now = time.time()
                failure = _record_slider_attempt_failure(state, now=now)
                # A successful solve anywhere after a previous failure resets the window.
                last_success_at = float(state.get("last_success_at") or 0) or None
                window_started_at = float(state.get("window_started_at") or 0) or now
                stalled_seconds = now - window_started_at if last_success_at is None else now - max(last_success_at, window_started_at)
                threshold_reached = int(state["slider_attempts"]) >= FALLBACK_FAIL_THRESHOLD
                stalled = stalled_seconds >= FALLBACK_STALL_SECONDS
                cooldown_started = bool(failure.get("cooldown_started"))
                should_push = bool(
                    manual_fallback_enabled()
                    and threshold_reached
                    and stalled
                    and not state.get("manual_pushed")
                )
                state["stalled_seconds"] = round(stalled_seconds, 1)
                state["threshold_reached"] = threshold_reached
                state["stalled"] = stalled
                _save_fallback_state(state)
                log_event({
                    "kind": "slider_attempt_failed",
                    "attempt": state["slider_attempts"],
                    "next_attempt_at": state.get("slider_next_attempt_at"),
                    "cooldown_until": state.get("solver_cooldown_until"),
                })
                log_event({
                    "kind": "pc1_manual_escalation_check",
                    "consecutive_failures": state["consecutive_failures"],
                    "stalled_seconds": round(stalled_seconds, 1),
                    "threshold": FALLBACK_FAIL_THRESHOLD,
                    "stalled_threshold_seconds": FALLBACK_STALL_SECONDS,
                    "should_push": should_push,
                    "manual_pushed": state.get("manual_pushed", False),
                })
                if cooldown_started:
                    log_event({
                        "kind": "solver_cooldown_started",
                        "until": state["solver_cooldown_until"],
                        "seconds": max(0.0, SOLVER_COOLDOWN_SECONDS),
                        "consecutive_failures": state["consecutive_failures"],
                    })
                if should_push:
                    manual_result = _report_manual_captcha(api_base_url, cdp_endpoint, target_url)
                    state["manual_pushed"] = True
                    state["manual_pushed_at_epoch"] = time.time()
                    state["manual_result"] = manual_result
                    _save_fallback_state(state)
                    log_event({"kind": "pc1_manual_auth_pushed", "result": manual_result})
        except Exception as exc:
            log_event({"kind": "loop_error", "error": repr(exc), "traceback": traceback.format_exc()})
        time.sleep(poll_seconds)

__all__ = ('local_solver_loop',)
