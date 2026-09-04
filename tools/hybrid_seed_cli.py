from __future__ import annotations
from tools.hybrid_seed_context import *  # noqa: F401,F403
from tools.hybrid_seed_normalization import *  # noqa: F401,F403
from tools.hybrid_seed_status import *  # noqa: F401,F403
from tools.hybrid_seed_mode import *  # noqa: F401,F403
from tools.hybrid_seed_loop import *  # noqa: F401,F403
from tools.hybrid_seed_runtime import *  # noqa: F401,F403
from tools.hybrid_seed_policy_state import *  # noqa: F401,F403
from tools.hybrid_seed_operator_guidance import *  # noqa: F401,F403
from tools.hybrid_seed_operator_console import *  # noqa: F401,F403
from tools.hybrid_seed_cli_support import *  # noqa: F401,F403


def main(argv: list[str] | None = None) -> int:
    args = build_hybrid_seed_argument_parser().parse_args(argv)

    guidance_payload: dict[str, Any] = {}
    recovery_policy_payload: dict[str, Any] = {}
    guidance_resolution: dict[str, Any] = {}
    effective_mode = str(_coerce_optional_text(args.mode) or DEFAULT_MODE)
    effective_mode_for_result: str | None = None

    if args.loop:
        result = run_loop(
            api_base=args.api_base,
            session_id=args.session_id,
            cdp_endpoint=args.cdp_endpoint,
            submit=args.submit,
            mode=args.mode,
            profile_dir=Path(args.profile_dir),
            open_browser_fallback=args.open_browser_fallback,
            max_runs=args.max_runs,
            idle_sleep_seconds=args.idle_sleep_seconds,
            success_sleep_seconds=args.success_sleep_seconds,
            fallback_sleep_seconds=args.fallback_sleep_seconds,
            stop_on_fallback=args.stop_on_fallback,
            stop_on_operator_escalation=args.stop_on_operator_escalation,
            max_consecutive_fallbacks=args.max_consecutive_fallbacks,
            respect_operator_guidance=bool(args.respect_operator_guidance),
            load_operator_status_bundle_fn=load_hybrid_collection_operator_status_bundle,
            load_recovery_policy_fn=load_hybrid_collection_recovery_policy,
            load_lifecycle_summary_fn=load_hybrid_collection_lifecycle_state_summary,
            load_intervention_summary_fn=load_hybrid_collection_operator_intervention_policy_summary,
            load_stability_summary_fn=load_hybrid_collection_operator_intervention_stability_summary,
            load_digest_summary_fn=load_hybrid_collection_operator_digest_summary,
            load_digest_stability_summary_fn=load_hybrid_collection_operator_digest_stability_summary,
            load_escalation_event_trend_summary_fn=load_hybrid_collection_operator_escalation_event_trend_summary,
            load_escalation_event_stability_summary_fn=load_hybrid_collection_operator_escalation_event_stability_summary,
        )
    else:
        with hybrid_collection_status_snapshot_scope():
            try:
                operator_status_bundle = load_hybrid_collection_operator_status_bundle(args.api_base)
            except requests.exceptions.RequestException:
                operator_status_bundle = {}
            operator_status_bundle = _coerce_optional_mapping(operator_status_bundle)
            if args.respect_operator_guidance:
                guidance_payload = _coerce_optional_mapping(operator_status_bundle.get("guidance"))
                recovery_policy_payload = _coerce_optional_mapping(operator_status_bundle.get("recovery_policy"))
            guidance_resolution = resolve_effective_mode(
                requested_mode=args.mode,
                guidance=guidance_payload,
                recovery_policy=recovery_policy_payload,
                respect_operator_guidance=bool(args.respect_operator_guidance),
            )
            resolution_effective_mode = _coerce_optional_text(
                guidance_resolution.get("effective_mode")
            )
            effective_mode = _first_optional_text(
                resolution_effective_mode,
                guidance_resolution.get("requested_mode"),
                args.mode,
                DEFAULT_MODE,
            ) or DEFAULT_MODE
            effective_mode_for_result = resolution_effective_mode
            result = run_once(
                api_base=args.api_base,
                session_id=args.session_id,
                cdp_endpoint=args.cdp_endpoint,
                submit=args.submit,
                mode=effective_mode,
                profile_dir=Path(args.profile_dir),
                open_browser_fallback=args.open_browser_fallback,
            )
            result = _coerce_optional_mapping(result)
            if "task" in result:
                result["task"] = _normalize_task_payload(result.get("task"))
            if "collection_result" in result:
                result["collection_result"] = _normalize_collection_result_payload(
                    result.get("collection_result")
                )
            result["decision"] = _coerce_optional_text(result.get("decision"))
            result["reason"] = _coerce_optional_text(result.get("reason"))
            if "error" in result:
                result["error"] = _coerce_optional_text(result.get("error"))
            if "task_message" in result:
                result["task_message"] = _coerce_optional_text(result.get("task_message"))
            if "message" in result:
                result["message"] = _coerce_optional_text(result.get("message"))
            result["browser_fallback_opened"] = (
                _coerce_optional_bool(result.get("browser_fallback_opened")) is True
            )
            result["fallback_url"] = _coerce_optional_text(result.get("fallback_url"))
            requested_mode_for_result = _first_optional_text(
                guidance_resolution.get("requested_mode"),
                args.mode,
                DEFAULT_MODE,
            )
            result["requested_mode"] = requested_mode_for_result
            result["effective_mode"] = effective_mode_for_result
            effective_mode_source = _coerce_optional_text(guidance_resolution.get("effective_mode_source"))
            result["effective_mode_source"] = effective_mode_source
            result["guidance_applied"] = (
                _coerce_optional_bool(guidance_resolution.get("guidance_applied")) is True
            )
            guidance_status = _coerce_optional_text(guidance_resolution.get("guidance_status"))
            result["guidance_status"] = guidance_status
            guidance_recommended_mode = _coerce_optional_mapping(
                guidance_resolution.get("guidance")
            ).get("recommended_mode")
            guidance_recommended_mode = _coerce_optional_text(guidance_recommended_mode)
            result["guidance_recommended_mode"] = guidance_recommended_mode
            top_guidance_reason = _coerce_optional_mapping(
                guidance_resolution.get("guidance")
            ).get("top_guidance_reason")
            top_guidance_reason = _coerce_optional_text(top_guidance_reason)
            top_policy_reason = _coerce_optional_mapping(
                guidance_resolution.get("recovery_policy")
            ).get("top_policy_reason")
            top_policy_reason = _coerce_optional_text(top_policy_reason)
            if guidance_resolution.get("effective_mode_source") == "recovery_policy":
                top_guidance_reason = top_policy_reason or top_guidance_reason
            result["top_guidance_reason"] = top_guidance_reason
            result["top_policy_reason"] = top_policy_reason
            recovery_policy_status = _coerce_optional_text(guidance_resolution.get("recovery_policy_status"))
            result["recovery_policy_status"] = recovery_policy_status
            recovery_policy_priority = _coerce_optional_text(guidance_resolution.get("recovery_policy_priority"))
            result["recovery_policy_priority"] = recovery_policy_priority
            result["recovery_policy_mode_pin_active"] = _coerce_optional_bool(
                guidance_resolution.get("recovery_policy_mode_pin_active")
            )
            recovery_policy_effective_recommended_mode = _coerce_optional_mapping(
                guidance_resolution.get("recovery_policy")
            ).get("effective_recommended_mode")
            recovery_policy_effective_recommended_mode = _coerce_optional_text(
                recovery_policy_effective_recommended_mode
            )
            result["recovery_policy_effective_recommended_mode"] = (
                recovery_policy_effective_recommended_mode
            )
            lifecycle_summary = _coerce_optional_mapping(operator_status_bundle.get("lifecycle_summary"))
            intervention_summary = _coerce_optional_mapping(operator_status_bundle.get("intervention_summary"))
            intervention_stability_summary = _coerce_optional_mapping(operator_status_bundle.get("intervention_stability_summary"))
            final_guidance_summary = _coerce_optional_mapping(operator_status_bundle.get("final_guidance_summary"))
            operator_digest_summary = _coerce_optional_mapping(operator_status_bundle.get("digest_summary"))
            operator_digest_stability_summary = _coerce_optional_mapping(operator_status_bundle.get("digest_stability_summary"))
            operator_escalation_event_trend_summary = _coerce_optional_mapping(operator_status_bundle.get("escalation_event_trend_summary"))
            operator_escalation_event_stability_summary = _coerce_optional_mapping(operator_status_bundle.get("escalation_event_stability_summary"))
    if args.loop:
        with hybrid_collection_status_snapshot_scope():
            try:
                lifecycle_summary = load_hybrid_collection_lifecycle_state_summary(args.api_base)
            except requests.exceptions.RequestException:
                lifecycle_summary = {}
            lifecycle_summary = _coerce_optional_mapping(lifecycle_summary)
            try:
                intervention_summary = load_hybrid_collection_operator_intervention_policy_summary(args.api_base)
            except requests.exceptions.RequestException:
                intervention_summary = {}
            intervention_summary = _coerce_optional_mapping(intervention_summary)
            try:
                intervention_stability_summary = load_hybrid_collection_operator_intervention_stability_summary(args.api_base)
            except requests.exceptions.RequestException:
                intervention_stability_summary = {}
            intervention_stability_summary = _coerce_optional_mapping(intervention_stability_summary)
            try:
                final_guidance_summary = load_hybrid_collection_operator_final_guidance_summary(args.api_base)
            except requests.exceptions.RequestException:
                final_guidance_summary = {}
            final_guidance_summary = _coerce_optional_mapping(final_guidance_summary)
            try:
                operator_digest_summary = load_hybrid_collection_operator_digest_summary(args.api_base)
            except requests.exceptions.RequestException:
                operator_digest_summary = {}
            operator_digest_summary = _coerce_optional_mapping(operator_digest_summary)
            try:
                operator_digest_stability_summary = load_hybrid_collection_operator_digest_stability_summary(args.api_base)
            except requests.exceptions.RequestException:
                operator_digest_stability_summary = {}
            operator_digest_stability_summary = _coerce_optional_mapping(operator_digest_stability_summary)
            try:
                operator_escalation_event_trend_summary = load_hybrid_collection_operator_escalation_event_trend_summary(args.api_base)
            except requests.exceptions.RequestException:
                operator_escalation_event_trend_summary = {}
            operator_escalation_event_trend_summary = _coerce_optional_mapping(operator_escalation_event_trend_summary)
            try:
                operator_escalation_event_stability_summary = load_hybrid_collection_operator_escalation_event_stability_summary(args.api_base)
            except requests.exceptions.RequestException:
                operator_escalation_event_stability_summary = {}
            operator_escalation_event_stability_summary = _coerce_optional_mapping(operator_escalation_event_stability_summary)
    digest_status = _coerce_optional_text(operator_digest_summary.get("digest_status"))
    result["operator_digest_status"] = digest_status
    digest_priority = _coerce_optional_text(operator_digest_summary.get("digest_priority"))
    result["operator_digest_priority"] = digest_priority
    digest_message = _coerce_optional_text(operator_digest_summary.get("operator_digest_message"))
    result["operator_digest_message"] = digest_message
    digest_stability_status = _coerce_optional_text(
        operator_digest_stability_summary.get("stability_status")
    )
    digest_stability_severity = _coerce_optional_text(
        operator_digest_stability_summary.get("stability_severity")
    )
    digest_stability_explanation = _coerce_optional_text(
        operator_digest_stability_summary.get("operator_readable_explanation")
    )
    result["operator_digest_stability_status"] = digest_stability_status
    result["operator_digest_stability_severity"] = digest_stability_severity
    result["operator_digest_stability_explanation"] = digest_stability_explanation
    source_last_changed_at = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("last_source_change_at")
    )
    current_source = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("current_operator_escalation_source")
    )
    previous_source = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("previous_distinct_operator_escalation_source")
    )
    source_stability_status = _coerce_optional_text(
        operator_escalation_event_stability_summary.get("stability_status")
    )
    source_stability_severity = _coerce_optional_text(
        operator_escalation_event_stability_summary.get("stability_severity")
    )
    source_stability_explanation = _coerce_optional_text(
        operator_escalation_event_stability_summary.get("operator_readable_explanation")
    )
    final_guidance_label = _coerce_optional_text(final_guidance_summary.get("guidance_label"))
    final_guidance_priority = _coerce_optional_text(final_guidance_summary.get("guidance_priority"))
    final_guidance_message = _coerce_optional_text(final_guidance_summary.get("guidance_message"))
    result["operator_escalation_current_source"] = current_source
    result["operator_escalation_previous_source"] = previous_source
    operator_escalation_source_change_count = _coerce_optional_int(
        operator_escalation_event_trend_summary.get("recent_source_change_count")
    )
    if operator_escalation_source_change_count is not None and operator_escalation_source_change_count < 0:
        operator_escalation_source_change_count = 0
    result["operator_escalation_source_change_count"] = operator_escalation_source_change_count
    result["operator_escalation_source_last_changed_at"] = source_last_changed_at
    result["operator_escalation_source_stability_status"] = source_stability_status
    result["operator_escalation_source_stability_severity"] = source_stability_severity
    result["operator_escalation_source_stability_explanation"] = source_stability_explanation
    escalation_source = operator_escalation_source(
        result,
        lifecycle_summary=lifecycle_summary,
        intervention_summary=intervention_summary,
        stability_summary=intervention_stability_summary,
    )
    if escalation_source is not None:
        result["operator_escalation_source"] = escalation_source
        result["operator_action_hint"] = operator_action_hint(
            result,
            lifecycle_summary=lifecycle_summary,
            intervention_summary=intervention_summary,
            stability_summary=intervention_stability_summary,
        )
        result["operator_final_guidance_label"] = final_guidance_label
        result["operator_final_guidance_priority"] = final_guidance_priority
        result["operator_final_guidance_message"] = final_guidance_message
        audit_message = operator_escalation_audit_message(
            result,
            lifecycle_summary=lifecycle_summary,
            intervention_summary=intervention_summary,
            stability_summary=intervention_stability_summary,
            final_guidance_summary=final_guidance_summary,
            digest_summary=operator_digest_summary,
            digest_stability_summary=operator_digest_stability_summary,
        )
        audit_message = _coerce_optional_text(audit_message)
        if audit_message is not None:
            result["operator_escalation_audit_message"] = audit_message
        else:
            result.pop("operator_escalation_audit_message", None)
    elif _coerce_optional_text(result.get("operator_escalation_source")) is None:
        result.pop("operator_escalation_source", None)
    audit_message = _coerce_optional_text(result.get("operator_escalation_audit_message"))
    if audit_message is not None:
        result["operator_escalation_audit_message"] = audit_message
    else:
        result.pop("operator_escalation_audit_message", None)
    recovery_events = persist_main_runtime_artifacts(
        result=result,
        args=args,
        effective_mode=effective_mode,
        effective_mode_for_result=effective_mode_for_result,
        guidance_resolution=guidance_resolution,
        lifecycle_summary=lifecycle_summary,
        intervention_summary=intervention_summary,
        intervention_stability_summary=intervention_stability_summary,
        final_guidance_summary=final_guidance_summary,
        operator_digest_summary=operator_digest_summary,
        operator_digest_stability_summary=operator_digest_stability_summary,
        operator_escalation_event_trend_summary=operator_escalation_event_trend_summary,
        operator_escalation_event_stability_summary=operator_escalation_event_stability_summary,
    )
    digest_message = _coerce_optional_text(operator_digest_summary.get("operator_digest_message")) or ""
    digest_status = _coerce_optional_text(operator_digest_summary.get("digest_status")) or ""
    audit_message = _coerce_optional_text(result.get("operator_escalation_audit_message")) or ""
    has_audit_message = bool(audit_message)
    final_guidance_message = _coerce_optional_text(result.get("operator_final_guidance_message")) or ""
    suppress_digest_message = False
    suppress_digest_status = False
    if digest_message:
        suppress_digest_message = (
            (has_audit_message and digest_message in audit_message)
            or (not has_audit_message and digest_message == final_guidance_message)
        )
    if digest_status:
        suppress_digest_status = has_audit_message and f"digest={digest_status}" in audit_message
    emit_operator_digest_console_summary(
        operator_digest_summary,
        suppress_message=suppress_digest_message,
        suppress_status=suppress_digest_status,
    )
    digest_stability_current = _coerce_optional_text(
        operator_digest_stability_summary.get("current_digest_status")
    )
    suppress_digest_stability_current = digest_status != "" and digest_status == digest_stability_current
    digest_stability_status = _coerce_optional_text(
        operator_digest_stability_summary.get("stability_status")
    )
    suppress_digest_stability_status = (
        digest_stability_status is not None
        and has_audit_message
        and f"digest_stability={digest_stability_status}" in audit_message
    )
    emit_operator_digest_stability_console_summary(
        operator_digest_stability_summary,
        suppress_current=suppress_digest_stability_current,
        suppress_status=suppress_digest_stability_status,
    )
    if not has_audit_message:
        emit_operator_final_guidance_console_summary(final_guidance_summary)
    emit_operator_escalation_event_trend_console_summary(operator_escalation_event_trend_summary)
    trend_current_source = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("current_operator_escalation_source")
    ) or ""
    trend_previous_source = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("previous_distinct_operator_escalation_source")
    )
    trend_last_changed_at = _coerce_optional_text(
        operator_escalation_event_trend_summary.get("last_source_change_at")
    )
    trend_recent_change_count = _coerce_optional_int(
        operator_escalation_event_trend_summary.get("recent_source_change_count")
    )
    if trend_recent_change_count is not None and trend_recent_change_count < 0:
        trend_recent_change_count = None
    stability_current_source = _coerce_optional_text(
        operator_escalation_event_stability_summary.get("current_operator_escalation_source")
    ) or ""
    stability_previous_source = _coerce_optional_text(
        operator_escalation_event_stability_summary.get("previous_operator_escalation_source")
    )
    stability_recent_source_change_count = _coerce_optional_int(
        operator_escalation_event_stability_summary.get("recent_source_change_count")
    )
    if stability_recent_source_change_count is not None and stability_recent_source_change_count < 0:
        stability_recent_source_change_count = None
    trend_line_visible = bool(trend_current_source) and (
        trend_recent_change_count not in {None, 0}
        or bool(trend_previous_source)
        or trend_last_changed_at is not None
    )
    suppress_escalation_stability_source_context = trend_line_visible and (
        trend_current_source == stability_current_source
    ) and (
        trend_previous_source == stability_previous_source
    ) and (
        trend_recent_change_count == stability_recent_source_change_count
    )
    suppress_escalation_stability_status = (
        _coerce_optional_text(
            operator_escalation_event_stability_summary.get("operator_readable_explanation")
        )
        is not None
    )
    emit_operator_escalation_event_stability_console_summary(
        operator_escalation_event_stability_summary,
        suppress_source_context=suppress_escalation_stability_source_context,
        suppress_status=suppress_escalation_stability_status,
    )
    emit_operator_console_summary(
        result,
        lifecycle_summary=lifecycle_summary,
        intervention_summary=intervention_summary,
        stability_summary=intervention_stability_summary,
        final_guidance_summary=final_guidance_summary,
        digest_summary=operator_digest_summary,
        digest_stability_summary=operator_digest_stability_summary,
    )
    emit_operator_recovery_console_summary(recovery_events)
    suppression_source = operator_escalation_source(
        result,
        lifecycle_summary=lifecycle_summary,
        intervention_summary=intervention_summary,
        stability_summary=intervention_stability_summary,
    )
    suppression_reason = _coerce_optional_text(intervention_summary.get("intervention_reason"))
    suppression_priority = _coerce_optional_text(intervention_summary.get("intervention_priority"))
    suppression_suggested_mode = _coerce_optional_text(intervention_summary.get("suggested_mode"))
    suppression_escalation_reason = _first_optional_text(
        result.get("top_policy_reason"),
        intervention_summary.get("intervention_reason"),
        lifecycle_summary.get("priority_hint"),
    )
    suppression_escalation_priority = _first_optional_text(
        result.get("recovery_policy_priority"),
        intervention_summary.get("intervention_priority"),
    )
    suppression_escalation_mode = _first_optional_text(
        result.get("recovery_policy_effective_recommended_mode"),
        intervention_summary.get("suggested_mode"),
        lifecycle_summary.get("suggested_mode"),
        result.get("effective_mode"),
    )
    suppress_intervention_reason = bool(suppression_source) and bool(suppression_reason) and (
        suppression_reason == suppression_escalation_reason
    )
    suppress_intervention_priority = bool(suppression_source) and bool(suppression_priority) and (
        suppression_priority == suppression_escalation_priority
    )
    suppress_intervention_suggested_mode = bool(suppression_source) and bool(suppression_suggested_mode) and (
        suppression_suggested_mode == suppression_escalation_mode
    )
    emit_operator_intervention_console_summary(
        intervention_summary,
        suppress_reason=suppress_intervention_reason,
        suppress_priority=suppress_intervention_priority,
        suppress_suggested_mode=suppress_intervention_suggested_mode,
    )
    intervention_action_hint = _coerce_optional_text(
        intervention_summary.get("preferred_operator_action_hint")
    )
    intervention_stability_action_hint = _coerce_optional_text(
        intervention_stability_summary.get("stability_action_hint")
    )
    suppress_intervention_stability_action_hint = (
        intervention_action_hint is not None
        and intervention_action_hint == intervention_stability_action_hint
    )
    intervention_status = _coerce_optional_text(intervention_summary.get("intervention_status"))
    intervention_stability_current = _coerce_optional_text(
        intervention_stability_summary.get("current_intervention_status")
    )
    suppress_intervention_stability_current = (
        intervention_status is not None
        and intervention_status == intervention_stability_current
    )
    suppress_intervention_stability_status = (
        _coerce_optional_text(intervention_stability_summary.get("operator_readable_explanation"))
        is not None
    )
    emit_operator_intervention_stability_console_summary(
        intervention_stability_summary,
        suppress_action_hint=suppress_intervention_stability_action_hint,
        suppress_current=suppress_intervention_stability_current,
        suppress_status=suppress_intervention_stability_status,
    )
    emit_operator_lifecycle_console_summary(lifecycle_summary)
    print(json.dumps(result, ensure_ascii=False))
    if args.fail_on_operator_escalation:
        escalation_exit_code = operator_escalation_exit_code(
            result,
            lifecycle_summary=lifecycle_summary,
            intervention_summary=intervention_summary,
            stability_summary=intervention_stability_summary,
            configured_exit_code=args.operator_escalation_exit_code,
        )
        if escalation_exit_code is not None:
            print(
                f"[OPERATOR] Returning dedicated operator escalation exit code {escalation_exit_code} "
                f"(source={result.get('operator_escalation_source')})",
                file=sys.stderr,
            )
            return escalation_exit_code
    return 0

__all__ = ('main',)
