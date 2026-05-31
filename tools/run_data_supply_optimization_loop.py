#!/usr/bin/env python3
"""Run repeated AVM data-supply maintenance rounds until progress converges."""

from __future__ import annotations

import argparse
import copy
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.analysis_stage_planner import (
    load_manual_review_receipt_snapshot,
    recommend_analysis_stage_actions,
    summarize_action_feedback,
    summarize_manual_review_backlog,
    summarize_manual_review_receipt_snapshot,
    summarize_operator_action_surface,
    summarize_operator_overview,
    summarize_recoverability_snapshot,
)
from tools.audit_recent_avm_gaps import build_recent_gap_audit
from tools.run_recent_enrich_maintenance import get_collection_stage_snapshot, run_recent_enrich_maintenance
from src.storage.repository import create_repository_from_env


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run repeated AVM data-supply maintenance rounds")
    parser.add_argument("--data-root", type=Path, default=Path("datas"))
    parser.add_argument("--window-days", type=int, default=7)
    parser.add_argument("--archive-limit", type=int, default=50)
    parser.add_argument("--sample-limit", type=int, default=10)
    parser.add_argument("--replay-limit", type=int, default=20)
    parser.add_argument("--fetch-limit", type=int, default=10)
    parser.add_argument("--fetch-timeout", type=int, default=15)
    parser.add_argument("--max-rounds", type=int, default=5)
    parser.add_argument("--idle-stop-rounds", type=int, default=2)
    parser.add_argument("--sleep-seconds", type=float, default=0.0)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--extract-risk", action="store_true")
    parser.add_argument("--fetch-archives", action="store_true")
    parser.add_argument("--prepare-replay", action="store_true")
    parser.add_argument("--output-path", type=Path, default=Path("datas/avm/data_supply_optimization_loop.json"))
    return parser.parse_args()


def _missing_delta(before: dict[str, Any], after: dict[str, Any]) -> dict[str, int]:
    deltas: dict[str, int] = {}
    keys = set(before) | set(after)
    for key in keys:
        before_value = int(before.get(key, 0) or 0)
        after_value = int(after.get(key, 0) or 0)
        deltas[key] = before_value - after_value
    return deltas


def _progress_summary(report: dict[str, Any]) -> dict[str, Any]:
    fetch_report = report.get("detail_archive_fetch", {})
    archived_report = report.get("archived_detail_backfill", {})
    coordinate_report = report.get("recent_coordinate_backfill", {})
    replay_report = report.get("detail_replay_preparation", {})
    before_missing = (report.get("before") or {}).get("missing_field_counts", {})
    after_missing = (report.get("after") or {}).get("missing_field_counts", {})
    before_stage = report.get("before_stage") or {}
    after_stage = report.get("after_stage") or {}
    missing_delta = _missing_delta(before_missing, after_missing)
    blocker_delta = _missing_delta(
        before_stage.get("analysis_blockers", {}) or {},
        after_stage.get("analysis_blockers", {}) or {},
    )
    detail_enriched_delta = int(after_stage.get("detail_enriched", 0) or 0) - int(before_stage.get("detail_enriched", 0) or 0)
    analysis_ready_delta = int(after_stage.get("analysis_ready", 0) or 0) - int(before_stage.get("analysis_ready", 0) or 0)

    summary = {
        "fetched_count": int(fetch_report.get("fetched_count", 0) or 0),
        "blocked_count": int(fetch_report.get("blocked_count", 0) or 0),
        "failed_count": int(fetch_report.get("failed_count", 0) or 0),
        "archived_updated_count": int(archived_report.get("updated_records", 0) or 0),
        "coordinate_updated_count": int(coordinate_report.get("updated_count", 0) or 0),
        "replay_prepared_count": int(replay_report.get("prepared_count", 0) or 0),
        "missing_field_delta": missing_delta,
        "missing_reduction_total": sum(delta for delta in missing_delta.values() if delta > 0),
        "analysis_blocker_delta": blocker_delta,
        "analysis_blocker_reduction_total": sum(delta for delta in blocker_delta.values() if delta > 0),
        "detail_enriched_delta": max(0, detail_enriched_delta),
        "analysis_ready_delta": max(0, analysis_ready_delta),
    }
    summary["progress_score"] = (
        summary["fetched_count"]
        + summary["archived_updated_count"]
        + summary["coordinate_updated_count"]
        + summary["replay_prepared_count"]
        + summary["missing_reduction_total"]
        + summary["analysis_blocker_reduction_total"]
        + summary["detail_enriched_delta"]
        + summary["analysis_ready_delta"]
    )
    return summary


def _load_manual_review_receipt_snapshot_for_loop(data_root: Path, repository) -> dict[str, Any]:
    receipt_path = data_root / "avm" / "manual_review_receipts.json"
    try:
        return load_manual_review_receipt_snapshot(
            receipt_path,
            repository=repository if repository.enabled else None,
        )
    except TypeError:
        return load_manual_review_receipt_snapshot(receipt_path)


def run_data_supply_optimization_loop(
    *,
    data_root: Path,
    window_days: int,
    archive_limit: int,
    sample_limit: int,
    replay_limit: int,
    fetch_limit: int,
    fetch_timeout: int,
    max_rounds: int,
    idle_stop_rounds: int,
    sleep_seconds: float,
    dry_run: bool,
    extract_risk: bool,
    fetch_archives: bool,
    prepare_replay: bool,
) -> dict[str, Any]:
    rounds: list[dict[str, Any]] = []
    idle_rounds = 0
    terminate_reason = "max_rounds_reached"
    current_action_effectiveness: dict[str, dict[str, int]] = {}
    repository = create_repository_from_env()

    for round_index in range(1, max_rounds + 1):
        before_stage_snapshot = get_collection_stage_snapshot()
        planning_gap_report = build_recent_gap_audit(data_root, window_days, sample_limit)
        planning_manual_review_backlog_summary = summarize_manual_review_backlog(planning_gap_report)
        planning_manual_review_receipt_summary = summarize_manual_review_receipt_snapshot(
            _load_manual_review_receipt_snapshot_for_loop(data_root, repository),
            planning_manual_review_backlog_summary,
        )
        current_effectiveness_snapshot = copy.deepcopy(current_action_effectiveness)
        round_plan = recommend_analysis_stage_actions(
            before_stage_snapshot,
            gap_report=planning_gap_report,
            action_effectiveness=current_effectiveness_snapshot,
            manual_review_receipt_summary=planning_manual_review_receipt_summary,
            fetch_archives=fetch_archives,
            prepare_replay=prepare_replay,
        )
        report = run_recent_enrich_maintenance(
            data_root=data_root,
            window_days=window_days,
            archive_limit=archive_limit,
            sample_limit=sample_limit,
            replay_limit=replay_limit,
            fetch_limit=fetch_limit,
            fetch_timeout=fetch_timeout,
            dry_run=dry_run,
            extract_risk=extract_risk,
            prepare_replay=round_plan["prepare_replay"],
            fetch_archives=round_plan["fetch_archives"],
            action_effectiveness=current_effectiveness_snapshot,
            repository=repository if repository.enabled else None,
        )
        action_feedback = report.get("action_feedback") or summarize_action_feedback(
            round_plan,
            {
                "detail_archive_fetch": report.get("detail_archive_fetch", {}),
                "archived_detail_backfill": report.get("archived_detail_backfill", {}),
                "recent_coordinate_backfill": report.get("recent_coordinate_backfill", {}),
                "detail_replay_preparation": report.get("detail_replay_preparation", {}),
                "analysis_ready_recheck": report.get("analysis_ready_recheck", {}),
                "stage_state_reconcile": report.get("stage_state_reconcile", {}),
            },
        )
        operator_summary = dict((report.get("operator_action_summary")) or {})
        if not operator_summary:
            operator_summary = summarize_operator_action_surface(
                report.get("recommended_actions"),
                {},
                summarize_recoverability_snapshot(report.get("before")),
            )
            operator_summary["manual_review_backlog_summary"] = summarize_manual_review_backlog(report.get("before"))
            operator_summary["manual_review_receipt_summary"] = dict((report.get("manual_review_receipt_summary")) or {})
            operator_summary["manual_review_reentry_application_summary"] = dict((report.get("manual_review_reentry_application_summary")) or {})
        operator_overview = dict((report.get("operator_overview")) or {})
        generated_operator_overview = summarize_operator_overview(operator_summary, {})
        if not operator_overview:
            operator_overview = generated_operator_overview
        else:
            for key, value in generated_operator_overview.items():
                operator_overview.setdefault(key, value)
        report.setdefault("operator_action_summary", operator_summary)
        report.setdefault("operator_overview", operator_overview)
        progress = _progress_summary(report)
        rounds.append(
            {
                "round": round_index,
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "plan": round_plan,
                "action_feedback": action_feedback,
                "fallback_routes_used": dict(report.get("fallback_routes_used", {}) or {}),
                "progress": progress,
                "report": report,
            }
        )
        for action_name, feedback in (action_feedback or {}).items():
            stats = current_action_effectiveness.setdefault(
                action_name,
                {"recommended_rounds": 0, "executed_rounds": 0, "productive_rounds": 0},
            )
            if feedback.get("recommended"):
                stats["recommended_rounds"] += 1
            if feedback.get("executed"):
                stats["executed_rounds"] += 1
            if feedback.get("produced_work"):
                stats["productive_rounds"] += 1

        recoverability_counts = dict((report.get("before") or {}).get("recoverability_counts", {}) or {})
        lifecycle_state = str(operator_overview.get("handoff_lifecycle_state") or "")
        if progress["progress_score"] <= 0 and lifecycle_state == "receipt_ready_for_reentry":
            idle_rounds = 0
            if sleep_seconds > 0 and round_index < max_rounds:
                time.sleep(sleep_seconds)
            continue
        if progress["progress_score"] <= 0 and lifecycle_state == "reentry_confirmed":
            idle_rounds = 0
            if sleep_seconds > 0 and round_index < max_rounds:
                time.sleep(sleep_seconds)
            continue
        if progress["progress_score"] <= 0 and lifecycle_state == "reentered_auto_pipeline":
            idle_rounds = 0
        if (
            progress["progress_score"] <= 0
            and int(recoverability_counts.get("future_fixable", 0) or 0) <= 0
            and bool((report.get("recommended_actions") or {}).get("manual_review_candidate"))
        ):
            terminate_reason = "no_recoverable_candidates"
            break
        if progress["progress_score"] <= 0 and lifecycle_state == "awaiting_valid_receipt":
            terminate_reason = "awaiting_valid_receipt"
            break
        if progress["progress_score"] <= 0 and lifecycle_state == "awaiting_human_receipt_hard_stop":
            terminate_reason = "awaiting_human_receipt_hard_stop"
            break
        if progress["progress_score"] <= 0 and lifecycle_state == "awaiting_human_receipt_retryable":
            terminate_reason = "awaiting_human_receipt_retryable"
            break

        if progress["progress_score"] <= 0:
            idle_rounds += 1
        else:
            idle_rounds = 0

        if idle_rounds >= idle_stop_rounds:
            terminate_reason = "idle_stop"
            break

        if sleep_seconds > 0 and round_index < max_rounds:
            time.sleep(sleep_seconds)

    total_progress = {
        "fetched_count": sum(item["progress"]["fetched_count"] for item in rounds),
        "blocked_count": sum(item["progress"]["blocked_count"] for item in rounds),
        "failed_count": sum(item["progress"]["failed_count"] for item in rounds),
        "archived_updated_count": sum(item["progress"]["archived_updated_count"] for item in rounds),
        "coordinate_updated_count": sum(item["progress"]["coordinate_updated_count"] for item in rounds),
        "replay_prepared_count": sum(item["progress"]["replay_prepared_count"] for item in rounds),
        "missing_reduction_total": sum(item["progress"]["missing_reduction_total"] for item in rounds),
        "analysis_blocker_reduction_total": sum(item["progress"]["analysis_blocker_reduction_total"] for item in rounds),
        "detail_enriched_delta": sum(item["progress"]["detail_enriched_delta"] for item in rounds),
        "analysis_ready_delta": sum(item["progress"]["analysis_ready_delta"] for item in rounds),
    }
    action_effectiveness: dict[str, dict[str, int]] = {}
    fallback_usage: dict[str, dict[str, int]] = {}
    manual_review_candidate_rounds = 0
    manual_review_reasons: dict[str, int] = {}
    handoff_mode_counts: dict[str, int] = {}
    handoff_lifecycle_counts: dict[str, int] = {}
    human_action_counts: dict[str, int] = {}
    retry_policy_counts: dict[str, int] = {}
    pending_ready_signal_counts: dict[str, int] = {}
    matched_ready_signal_counts: dict[str, int] = {}
    invalid_receipt_reason_counts: dict[str, int] = {}
    reentry_applied_rounds = 0
    applied_ready_signal_counts: dict[str, int] = {}
    reentry_confirmed_rounds = 0
    confirmed_ready_signal_counts: dict[str, int] = {}
    for item in rounds:
        for action_name, feedback in (item.get("action_feedback") or {}).items():
            stats = action_effectiveness.setdefault(
                action_name,
                {"recommended_rounds": 0, "executed_rounds": 0, "productive_rounds": 0},
            )
            if feedback.get("recommended"):
                stats["recommended_rounds"] += 1
            if feedback.get("executed"):
                stats["executed_rounds"] += 1
            if feedback.get("produced_work"):
                stats["productive_rounds"] += 1
        for source_action, target_action in dict(item.get("fallback_routes_used", {}) or {}).items():
            source_counts = fallback_usage.setdefault(source_action, {})
            source_counts[target_action] = int(source_counts.get(target_action, 0) or 0) + 1
        report_payload = item.get("report") or {}
        operator_summary = dict((report_payload.get("operator_action_summary")) or {})
        if not operator_summary:
            operator_summary = summarize_operator_action_surface(
                report_payload.get("recommended_actions"),
                {},
                summarize_recoverability_snapshot(report_payload.get("before")),
            )
            operator_summary["manual_review_backlog_summary"] = summarize_manual_review_backlog(report_payload.get("before"))
            operator_summary["manual_review_receipt_summary"] = dict((report_payload.get("manual_review_receipt_summary")) or {})
            operator_summary["manual_review_reentry_application_summary"] = dict((report_payload.get("manual_review_reentry_application_summary")) or {})
        operator_overview = dict((report_payload.get("operator_overview")) or {})
        generated_operator_overview = summarize_operator_overview(operator_summary, {})
        if not operator_overview:
            operator_overview = generated_operator_overview
        else:
            for key, value in generated_operator_overview.items():
                operator_overview.setdefault(key, value)
        if operator_overview.get("manual_review_required"):
            manual_review_candidate_rounds += 1
        reason = operator_overview.get("top_manual_review_reason")
        if reason:
            manual_review_reasons[reason] = int(manual_review_reasons.get(reason, 0) or 0) + 1
        handoff_mode = operator_overview.get("handoff_mode")
        if handoff_mode:
            handoff_mode_counts[handoff_mode] = int(handoff_mode_counts.get(handoff_mode, 0) or 0) + 1
        handoff_lifecycle_state = operator_overview.get("handoff_lifecycle_state")
        if handoff_lifecycle_state:
            handoff_lifecycle_counts[handoff_lifecycle_state] = int(handoff_lifecycle_counts.get(handoff_lifecycle_state, 0) or 0) + 1
        retry_policy = dict(operator_overview.get("auto_retry_policy", {}) or {}).get("policy")
        if retry_policy:
            retry_policy_counts[retry_policy] = int(retry_policy_counts.get(retry_policy, 0) or 0) + 1
        for ready_signal in list(operator_overview.get("pending_ready_signals") or []):
            pending_ready_signal_counts[ready_signal] = int(pending_ready_signal_counts.get(ready_signal, 0) or 0) + 1
        for ready_signal in list(operator_overview.get("matched_ready_signals") or []):
            matched_ready_signal_counts[ready_signal] = int(matched_ready_signal_counts.get(ready_signal, 0) or 0) + 1
        invalid_reason = operator_overview.get("top_invalid_receipt_reason")
        if invalid_reason:
            invalid_receipt_reason_counts[invalid_reason] = int(invalid_receipt_reason_counts.get(invalid_reason, 0) or 0) + 1
        if operator_overview.get("reentry_applied") or handoff_lifecycle_state == "reentry_applied":
            reentry_applied_rounds += 1
        for ready_signal in list(operator_overview.get("applied_ready_signals") or []):
            applied_ready_signal_counts[ready_signal] = int(applied_ready_signal_counts.get(ready_signal, 0) or 0) + 1
        if operator_overview.get("reentry_confirmed") or handoff_lifecycle_state == "reentry_confirmed":
            reentry_confirmed_rounds += 1
        for ready_signal in list(operator_overview.get("confirmed_ready_signals") or []):
            confirmed_ready_signal_counts[ready_signal] = int(confirmed_ready_signal_counts.get(ready_signal, 0) or 0) + 1
        backlog_summary = dict((report_payload.get("manual_review_backlog_summary")) or {})
        for action_name, action_queue in dict(backlog_summary.get("human_action_queues", {}) or {}).items():
            human_action_counts[action_name] = int(human_action_counts.get(action_name, 0) or 0) + int((action_queue or {}).get("count", 0) or 0)
    total_progress["action_effectiveness"] = action_effectiveness
    total_progress["fallback_usage"] = fallback_usage
    total_progress["manual_review_candidate_rounds"] = manual_review_candidate_rounds
    total_progress["manual_review_reasons"] = manual_review_reasons
    total_progress["handoff_mode_counts"] = handoff_mode_counts
    total_progress["handoff_lifecycle_counts"] = handoff_lifecycle_counts
    total_progress["human_action_counts"] = human_action_counts
    total_progress["retry_policy_counts"] = retry_policy_counts
    total_progress["pending_ready_signal_counts"] = pending_ready_signal_counts
    total_progress["matched_ready_signal_counts"] = matched_ready_signal_counts
    total_progress["invalid_receipt_reason_counts"] = invalid_receipt_reason_counts
    total_progress["reentry_applied_rounds"] = reentry_applied_rounds
    total_progress["applied_ready_signal_counts"] = applied_ready_signal_counts
    total_progress["reentry_confirmed_rounds"] = reentry_confirmed_rounds
    total_progress["confirmed_ready_signal_counts"] = confirmed_ready_signal_counts
    total_progress["top_manual_review_reason"] = (
        sorted(manual_review_reasons.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if manual_review_reasons
        else None
    )
    total_progress["top_handoff_mode"] = (
        sorted(handoff_mode_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if handoff_mode_counts
        else None
    )
    total_progress["top_handoff_lifecycle_state"] = (
        sorted(handoff_lifecycle_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if handoff_lifecycle_counts
        else None
    )
    total_progress["top_human_actions"] = [
        name
        for name, _count in sorted(
            human_action_counts.items(),
            key=lambda item: (-int(item[1] or 0), item[0]),
        )[:3]
    ]
    total_progress["top_retry_policy"] = (
        sorted(retry_policy_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if retry_policy_counts
        else None
    )
    total_progress["top_pending_ready_signal"] = (
        sorted(pending_ready_signal_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if pending_ready_signal_counts
        else None
    )
    total_progress["top_matched_ready_signal"] = (
        sorted(matched_ready_signal_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if matched_ready_signal_counts
        else None
    )
    total_progress["top_invalid_receipt_reason"] = (
        sorted(invalid_receipt_reason_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if invalid_receipt_reason_counts
        else None
    )
    total_progress["top_reentry_applied_signal"] = (
        sorted(applied_ready_signal_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if applied_ready_signal_counts
        else None
    )
    total_progress["top_reentry_confirmed_signal"] = (
        sorted(confirmed_ready_signal_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if confirmed_ready_signal_counts
        else None
    )
    total_progress["progress_score"] = (
        total_progress["fetched_count"]
        + total_progress["archived_updated_count"]
        + total_progress["coordinate_updated_count"]
        + total_progress["replay_prepared_count"]
        + total_progress["missing_reduction_total"]
        + total_progress["analysis_blocker_reduction_total"]
        + total_progress["detail_enriched_delta"]
        + total_progress["analysis_ready_delta"]
    )

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "max_rounds": max_rounds,
        "idle_stop_rounds": idle_stop_rounds,
        "dry_run": dry_run,
        "extract_risk": extract_risk,
        "fetch_archives": fetch_archives,
        "prepare_replay": prepare_replay,
        "terminate_reason": terminate_reason,
        "round_count": len(rounds),
        "total_progress": total_progress,
        "rounds": rounds,
    }


def main() -> None:
    args = parse_args()
    report = run_data_supply_optimization_loop(
        data_root=args.data_root,
        window_days=args.window_days,
        archive_limit=args.archive_limit,
        sample_limit=args.sample_limit,
        replay_limit=args.replay_limit,
        fetch_limit=args.fetch_limit,
        fetch_timeout=args.fetch_timeout,
        max_rounds=args.max_rounds,
        idle_stop_rounds=args.idle_stop_rounds,
        sleep_seconds=args.sleep_seconds,
        dry_run=args.dry_run,
        extract_risk=args.extract_risk,
        fetch_archives=args.fetch_archives,
        prepare_replay=args.prepare_replay,
    )
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
