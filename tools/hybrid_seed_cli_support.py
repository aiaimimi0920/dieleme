from __future__ import annotations

from tools.hybrid_seed_context import *  # noqa: F401,F403
from tools.hybrid_seed_policy_state import *  # noqa: F401,F403
from tools.hybrid_seed_runtime import *  # noqa: F401,F403


def build_hybrid_seed_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run browserless-first hybrid seed collection against the real seed task dispatcher."
    )
    parser.add_argument("--api-base", default=DEFAULT_API_BASE)
    parser.add_argument("--session-id", default=DEFAULT_SESSION_ID)
    parser.add_argument("--cdp-endpoint", default=DEFAULT_CDP_ENDPOINT)
    parser.add_argument("--mode", choices=["hybrid", "browserless", "browser"], default=DEFAULT_MODE)
    parser.add_argument("--submit", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--max-runs", type=int, default=None)
    parser.add_argument("--idle-sleep-seconds", type=float, default=10.0)
    parser.add_argument("--success-sleep-seconds", type=float, default=2.0)
    parser.add_argument("--fallback-sleep-seconds", type=float, default=15.0)
    parser.add_argument("--stop-on-fallback", action="store_true")
    parser.add_argument("--stop-on-operator-escalation", action="store_true")
    parser.add_argument("--max-consecutive-fallbacks", type=int, default=None)
    parser.add_argument("--open-browser-fallback", action="store_true")
    parser.add_argument("--profile-dir", default=str(DEFAULT_PROFILE_DIR))
    parser.add_argument("--respect-operator-guidance", action="store_true")
    parser.add_argument("--runtime-summary-path", default=str(DEFAULT_RUNTIME_SUMMARY_PATH))
    parser.add_argument("--runtime-history-path", default=str(DEFAULT_RUNTIME_HISTORY_PATH))
    parser.add_argument("--runtime-switch-events-path", default=str(DEFAULT_RUNTIME_SWITCH_EVENTS_PATH))
    parser.add_argument("--runtime-recovery-policy-state-path", default=str(DEFAULT_RECOVERY_POLICY_STATE_PATH))
    parser.add_argument("--runtime-recovery-policy-events-path", default=str(DEFAULT_RECOVERY_POLICY_EVENTS_PATH))
    parser.add_argument("--runtime-operator-escalation-events-path", default=str(DEFAULT_OPERATOR_ESCALATION_EVENTS_PATH))
    parser.add_argument("--runtime-operator-escalation-state-path", default=str(DEFAULT_OPERATOR_ESCALATION_STATE_PATH))
    parser.add_argument(
        "--runtime-operator-escalation-recovery-events-path",
        default=str(DEFAULT_OPERATOR_ESCALATION_RECOVERY_EVENTS_PATH),
    )
    parser.add_argument("--runtime-operator-intervention-state-path", default=str(DEFAULT_OPERATOR_INTERVENTION_STATE_PATH))
    parser.add_argument("--runtime-operator-intervention-events-path", default=str(DEFAULT_OPERATOR_INTERVENTION_EVENTS_PATH))
    parser.add_argument("--fail-on-operator-escalation", action="store_true")
    parser.add_argument("--operator-escalation-exit-code", type=int, default=42)
    return parser


def persist_main_runtime_artifacts(
    *,
    result: dict[str, Any],
    args: argparse.Namespace,
    effective_mode: str,
    effective_mode_for_result: str | None,
    guidance_resolution: dict[str, Any],
    lifecycle_summary: dict[str, Any],
    intervention_summary: dict[str, Any],
    intervention_stability_summary: dict[str, Any],
    final_guidance_summary: dict[str, Any],
    operator_digest_summary: dict[str, Any],
    operator_digest_stability_summary: dict[str, Any],
    operator_escalation_event_trend_summary: dict[str, Any],
    operator_escalation_event_stability_summary: dict[str, Any],
) -> list[dict[str, Any]]:
    runtime_summary = build_runtime_summary(
        result=result,
        requested_mode=args.mode,
        effective_mode=effective_mode_for_result if not args.loop else effective_mode,
        submit=args.submit,
        api_base=args.api_base,
        cdp_endpoint=args.cdp_endpoint,
        session_id=args.session_id,
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
    persist_runtime_summary(runtime_summary, Path(args.runtime_summary_path))
    append_runtime_history(runtime_summary, Path(args.runtime_history_path))
    append_mode_switch_events(result, Path(args.runtime_switch_events_path), session_id=args.session_id)
    append_recovery_policy_transition_events(
        result,
        Path(args.runtime_recovery_policy_state_path),
        Path(args.runtime_recovery_policy_events_path),
        session_id=args.session_id,
    )
    append_operator_escalation_events(
        result,
        Path(args.runtime_operator_escalation_events_path),
        session_id=args.session_id,
    )
    recovery_events = append_operator_escalation_recovery_events(
        result,
        Path(args.runtime_operator_escalation_state_path),
        Path(args.runtime_operator_escalation_recovery_events_path),
        session_id=args.session_id,
    )
    append_operator_intervention_transition_events(
        result,
        intervention_summary,
        final_guidance_summary,
        Path(args.runtime_operator_intervention_state_path),
        Path(args.runtime_operator_intervention_events_path),
        session_id=args.session_id,
    )
    return recovery_events


__all__ = ("build_hybrid_seed_argument_parser", "persist_main_runtime_artifacts")
