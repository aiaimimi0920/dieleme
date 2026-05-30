#!/usr/bin/env python3
"""Shared blocker-aware planning for detail->analysis maintenance flows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tools.manual_review_receipt_store import list_manual_review_receipts

MANUAL_REVIEW_REASON_PRIORITY = {
    "manual_location_review": 0,
    "manual_detail_capture_review": 1,
    "manual_price_anchor_review": 2,
    "manual_risk_review": 3,
    "manual_area_review": 4,
    "manual_status_review": 5,
}

MANUAL_REVIEW_ACTION_INSTRUCTIONS = {
    "manual_location_review": "优先核对 full_address/community_name/business_area，并补 latitude/longitude 或位置层级。",
    "manual_detail_capture_review": "优先确认详情页是否还能访问；若可回源则补抓 HTML/TXT/附件并重跑 enrich。",
    "manual_price_anchor_review": "优先补 transaction_price/starting_price/evaluation_price 等价格锚点，并确认单位。",
    "manual_risk_review": "优先补占用、租约、税费、份额等风险事实，必要时复核公告与须知。",
    "manual_area_review": "优先核对建筑面积/权属面积，并确认量纲与份额口径。",
    "manual_status_review": "优先核对成交/流拍/撤回状态，避免错误进入分析池。",
}

MANUAL_REVIEW_REENTRY_PATHS = {
    "manual_location_review": "infer_location_or_coordinate_backfill",
    "manual_detail_capture_review": "detail_replay_or_fetch_then_enrich",
    "manual_price_anchor_review": "analysis_ready_recheck",
    "manual_risk_review": "extract_risk_then_analysis_ready_recheck",
    "manual_area_review": "analysis_ready_recheck",
    "manual_status_review": "stage_state_reconcile",
}

MANUAL_REVIEW_QUEUE_LEVEL_INSTRUCTIONS = {
    "manual_location_review": "优先处理这组位置相关样本，统一核对 full_address/community_name/business_area，并补 latitude/longitude 或位置层级。",
    "manual_detail_capture_review": "优先处理这组详情缺失样本，统一确认详情页是否还能访问，并补抓 HTML/TXT/附件后重跑 enrich。",
    "manual_price_anchor_review": "优先处理这组价格锚点缺口样本，统一补 transaction_price/starting_price/evaluation_price 等价格事实并确认单位。",
    "manual_risk_review": "优先处理这组风险事实缺口样本，统一复核占用、租约、税费、份额等信息。",
    "manual_area_review": "优先处理这组面积口径缺口样本，统一核对建筑面积/权属面积并确认量纲与份额口径。",
    "manual_status_review": "优先处理这组状态不一致样本，统一复核成交/流拍/撤回状态并修正阶段判断。",
}

MANUAL_REVIEW_QUEUE_LEVEL_CHECKLISTS = {
    "manual_location_review": [
        "核对 full_address 是否完整且可定位。",
        "核对 community_name 与 business_area 是否一致。",
        "补 latitude/longitude 或明确位置层级后重试坐标链。",
    ],
    "manual_detail_capture_review": [
        "确认详情页是否仍可访问。",
        "补抓 HTML/TXT/附件并确认 archive 已落盘。",
        "重跑 enrich / replay 以恢复 detail_stage。",
    ],
    "manual_price_anchor_review": [
        "补 transaction_price/starting_price/evaluation_price 至少一类价格锚点。",
        "确认价格单位、总价/单价口径一致。",
        "补完后重新检查 analysis-ready 条件。",
    ],
    "manual_risk_review": [
        "复核占用、租约、税费、份额等风险字段。",
        "必要时回看公告正文与须知页。",
        "补完后重新触发风险抽取或 analysis-ready 复核。",
    ],
    "manual_area_review": [
        "核对建筑面积/权属面积字段来源。",
        "确认量纲与份额口径无歧义。",
        "补完后重新检查单价与可比样本链路。",
    ],
    "manual_status_review": [
        "核对成交/流拍/撤回等状态是否正确。",
        "确认状态时间与阶段状态一致。",
        "修正后重新检查是否允许进入分析池。",
    ],
}

MANUAL_REVIEW_PRIORITY_REASONS = {
    "manual_location_review": "位置核对通常最容易重新打开坐标补全和后续分析链路，因此优先级最高。",
    "manual_detail_capture_review": "详情回源是恢复 enrich 和后续分析链的前置条件，应尽早处理。",
    "manual_price_anchor_review": "价格锚点直接影响估值与可比样本可信度，缺失时需要尽快补齐。",
    "manual_risk_review": "风险事实缺失会影响 operator 判断与风险抽取结果，应在位置/详情后优先补齐。",
    "manual_area_review": "面积口径会影响单价与可比样本，但通常依赖前面链路先稳定。",
    "manual_status_review": "状态修正重要但通常不如位置/详情/价格缺口更容易重新打开自动链。",
}

MANUAL_REVIEW_COMPLETION_CRITERIA = {
    "manual_location_review": [
        "latitude/longitude 或位置层级字段已补齐，且地址信息足以重新定位。",
        "community_name/business_area 与地址信息不再互相冲突。",
        "样本可重新进入 infer_location 或 coordinate_backfill 链。",
    ],
    "manual_detail_capture_review": [
        "详情页可访问性已确认，或已明确不可回源。",
        "HTML/TXT/附件已补抓并成功归档。",
        "样本可重新进入 replay / enrich 链。",
    ],
    "manual_price_anchor_review": [
        "至少一类价格锚点已补齐且单位明确。",
        "价格字段口径一致，不再影响估值入口。",
        "样本可重新进入 analysis-ready 复核。",
    ],
    "manual_risk_review": [
        "关键风险字段已补齐或已明确无来源。",
        "风险事实与公告/须知描述一致。",
        "样本可重新进入风险抽取或 analysis-ready 复核。",
    ],
    "manual_area_review": [
        "面积字段来源与量纲已核对清楚。",
        "份额口径与面积口径不再冲突。",
        "样本可重新进入单价/可比样本链路复核。",
    ],
    "manual_status_review": [
        "成交/流拍/撤回状态已人工确认。",
        "阶段状态与事件时间一致。",
        "样本可重新进入 stage_state_reconcile 或分析池判断。",
    ],
}

MANUAL_REENTRY_VALIDATION_CHECKLISTS = {
    "manual_location_review": [
        "确认样本重新进入 infer_location_or_coordinate_backfill 后不再被 location blocker 卡住。",
        "确认 coordinate_backfill 或 infer_location 至少有一条自动链可继续尝试。",
    ],
    "manual_detail_capture_review": [
        "确认样本重新进入 detail_replay_or_fetch_then_enrich 后 detail_stage blocker 开始下降。",
        "确认 archive 路径与 enrich 输入已联通。",
    ],
    "manual_price_anchor_review": [
        "确认 analysis-ready 复核时不再缺价格锚点。",
        "确认估值/可比样本链开始消费新的价格事实。",
    ],
    "manual_risk_review": [
        "确认 extract_risk 或 analysis-ready 复核时风险缺口下降。",
        "确认风险字段已进入导出与告警链。",
    ],
    "manual_area_review": [
        "确认面积相关 blocker 或口径警告下降。",
        "确认单价链与可比样本链可重新消费面积数据。",
    ],
    "manual_status_review": [
        "确认状态修正后样本不会错误进入分析池。",
        "确认 stage_state_reconcile 后状态统计恢复一致。",
    ],
}

MANUAL_HANDOFF_ARTIFACT_FIELDS = {
    "manual_location_review": ["full_address", "community_name", "business_area", "latitude", "longitude"],
    "manual_detail_capture_review": ["detail_archive_path", "detail_text_path", "detail_html_path"],
    "manual_price_anchor_review": ["transaction_price", "starting_price", "evaluation_price"],
    "manual_risk_review": ["is_occupied", "has_long_lease", "clear_delivery", "tax_burden", "is_fractional_share"],
    "manual_area_review": ["area_sqm", "ownership_area_sqm"],
    "manual_status_review": ["status", "status_at"],
}

MANUAL_REQUIRED_HUMAN_EVIDENCE = {
    "manual_location_review": [
        "提供能支撑坐标修复的地址/商圈/小区证据，或人工确认后的坐标结果。",
        "记录位置核对后为何可以重新进入坐标链。",
    ],
    "manual_detail_capture_review": [
        "提供详情页可访问或不可访问的人工结论。",
        "记录归档后的 HTML/TXT/附件路径或无法回源的证据。",
    ],
    "manual_price_anchor_review": [
        "提供价格锚点来源截图、文本或人工录入依据。",
        "记录价格单位与口径确认结果。",
    ],
    "manual_risk_review": [
        "提供公告/须知/人工核查得到的风险事实证据。",
        "记录哪些风险字段已确认，哪些仍然无来源。",
    ],
    "manual_area_review": [
        "提供面积来源证据或人工核对记录。",
        "记录量纲与份额口径的最终结论。",
    ],
    "manual_status_review": [
        "提供成交/流拍/撤回状态的人工核查证据。",
        "记录状态时间与阶段修正依据。",
    ],
}

MANUAL_REENTRY_BLOCKERS_IF_INCOMPLETE = {
    "manual_location_review": [
        "location blocker 仍会阻止样本重新进入 infer_location 或 coordinate_backfill。",
        "地址冲突未消除时 analysis-ready 仍可能被位置精度卡住。",
    ],
    "manual_detail_capture_review": [
        "detail_stage blocker 仍会阻止 enrich / replay 继续推进。",
        "缺少 archive 产物时 detail 链无法恢复。",
    ],
    "manual_price_anchor_review": [
        "price_anchor blocker 仍会阻止估值与 analysis-ready 复核。",
        "价格口径不清时可比样本链仍不可信。",
    ],
    "manual_risk_review": [
        "风险缺口仍会阻止 extract_risk 或 analysis-ready 复核。",
        "风险事实不完整时告警和导出链仍然缺损。",
    ],
    "manual_area_review": [
        "面积口径缺失仍会阻止单价链稳定运行。",
        "面积与份额冲突未消除时可比样本链仍可能失真。",
    ],
    "manual_status_review": [
        "状态不一致仍会阻止 stage_state_reconcile 收口。",
        "错误状态仍可能导致样本误入或误出分析池。",
    ],
}

MANUAL_REQUIRED_RESOLUTION_NOTES = {
    "manual_location_review": [
        "记录地址/商圈/小区的人工核对结论，以及最终采用的坐标或位置层级。",
        "说明为何该结论足以重新进入坐标链。",
    ],
    "manual_detail_capture_review": [
        "记录详情页可访问性核对结论。",
        "说明归档产物路径或不可回源原因。",
    ],
    "manual_price_anchor_review": [
        "记录价格锚点最终采用值、来源与单位结论。",
        "说明是否仍有价格口径不确定项。",
    ],
    "manual_risk_review": [
        "记录风险字段人工核查结论与证据来源。",
        "说明哪些风险项仍无法确认。",
    ],
    "manual_area_review": [
        "记录面积字段最终采用值、来源与量纲结论。",
        "说明份额口径是否已经统一。",
    ],
    "manual_status_review": [
        "记录状态人工核查结论与时间依据。",
        "说明状态修正后阶段判断是否同步更新。",
    ],
}

MANUAL_REENTRY_READY_SIGNALS = {
    "manual_location_review": "location_artifacts_complete",
    "manual_detail_capture_review": "detail_artifacts_complete",
    "manual_price_anchor_review": "price_anchor_complete",
    "manual_risk_review": "risk_facts_complete",
    "manual_area_review": "area_facts_complete",
    "manual_status_review": "status_reconciled",
}

MANUAL_HANDOFF_COMPLETION_PAYLOADS = {
    "manual_location_review": {
        "required_fields": ["full_address", "community_name", "business_area", "latitude", "longitude"],
        "resolution_notes_field": "manual_location_resolution_notes",
        "ready_signal": "location_artifacts_complete",
    },
    "manual_detail_capture_review": {
        "required_fields": ["detail_archive_path", "detail_text_path", "detail_html_path"],
        "resolution_notes_field": "manual_detail_capture_resolution_notes",
        "ready_signal": "detail_artifacts_complete",
    },
    "manual_price_anchor_review": {
        "required_fields": ["transaction_price", "starting_price", "evaluation_price"],
        "resolution_notes_field": "manual_price_anchor_resolution_notes",
        "ready_signal": "price_anchor_complete",
    },
    "manual_risk_review": {
        "required_fields": ["is_occupied", "has_long_lease", "clear_delivery", "tax_burden", "is_fractional_share"],
        "resolution_notes_field": "manual_risk_resolution_notes",
        "ready_signal": "risk_facts_complete",
    },
    "manual_area_review": {
        "required_fields": ["area_sqm", "ownership_area_sqm"],
        "resolution_notes_field": "manual_area_resolution_notes",
        "ready_signal": "area_facts_complete",
    },
    "manual_status_review": {
        "required_fields": ["status", "status_at"],
        "resolution_notes_field": "manual_status_resolution_notes",
        "ready_signal": "status_reconciled",
    },
}

RECEIPT_FIX_ACTIONS = {
    "missing_required_fields": ["complete_required_fields"],
    "ready_signal_mismatch": ["use_expected_ready_signal"],
    "unknown_action": ["use_known_handoff_action"],
    "receipt_action_not_waiting": ["submit_receipt_for_waiting_action"],
    "unsupported_receipt_status": ["use_supported_receipt_status"],
    "malformed_payload": ["submit_structured_payload_object"],
    "duplicate_ready_signal": ["deduplicate_ready_signal_submission"],
    "duplicate_payload_for_same_action": ["deduplicate_payload_submission"],
    "late_receipt_for_closed_queue": ["refresh_active_handoff_queue"],
    "stale_receipt_for_recovered_item": ["avoid_resubmitting_recovered_item_receipt"],
}

RECEIPT_VALIDATION_REPAIR_HINTS = {
    "missing_required_fields": [
        "Complete the required fields for the active handoff queue before resubmitting the receipt.",
    ],
    "ready_signal_mismatch": [
        "Use the expected ready signal for the active handoff queue when resubmitting the receipt.",
    ],
    "unknown_action": [
        "Use a known handoff action from the active manual review backlog when resubmitting the receipt.",
    ],
    "receipt_action_not_waiting": [
        "Submit receipts only for actions that are currently waiting in the active manual review backlog.",
    ],
    "unsupported_receipt_status": [
        "Use a supported receipt status such as ready_for_reentry or reentered_auto_pipeline.",
    ],
    "malformed_payload": [
        "Submit the receipt payload as a structured object with named fields instead of a scalar or malformed value.",
    ],
    "duplicate_ready_signal": [
        "Do not resubmit a ready signal that has already been accepted for the same active handoff queue.",
    ],
    "duplicate_payload_for_same_action": [
        "Do not resubmit the exact same payload for the same active handoff action once it has already been accepted.",
    ],
    "late_receipt_for_closed_queue": [
        "Refresh the active manual review backlog before submitting a receipt, and avoid sending receipts for already-closed queues.",
    ],
    "stale_receipt_for_recovered_item": [
        "Do not resubmit receipts for items that have already reentered the automatic pipeline and are no longer waiting in the manual review backlog.",
    ],
}


def _manual_review_priority_label(priority_rank: int) -> str:
    if priority_rank <= 1:
        return "high"
    if priority_rank <= 3:
        return "medium"
    return "low"


def _manual_review_suggested_handoff_priority(priority_rank: int) -> str:
    if priority_rank <= 1:
        return "P0"
    if priority_rank <= 3:
        return "P1"
    return "P2"


def _manual_review_queue_metadata(reason: str) -> dict[str, Any]:
    priority_rank = MANUAL_REVIEW_REASON_PRIORITY.get(reason, 99)
    return {
        "priority_rank": priority_rank,
        "priority_label": _manual_review_priority_label(priority_rank),
        "suggested_handoff_priority": _manual_review_suggested_handoff_priority(priority_rank),
        "instruction": MANUAL_REVIEW_ACTION_INSTRUCTIONS.get(reason, ""),
        "queue_level_instruction": MANUAL_REVIEW_QUEUE_LEVEL_INSTRUCTIONS.get(reason, ""),
        "queue_level_checklist": list(MANUAL_REVIEW_QUEUE_LEVEL_CHECKLISTS.get(reason, [])),
        "queue_level_completion_criteria": list(MANUAL_REVIEW_COMPLETION_CRITERIA.get(reason, [])),
        "reentry_validation_checklist": list(MANUAL_REENTRY_VALIDATION_CHECKLISTS.get(reason, [])),
        "handoff_artifact_fields": list(MANUAL_HANDOFF_ARTIFACT_FIELDS.get(reason, [])),
        "required_human_evidence": list(MANUAL_REQUIRED_HUMAN_EVIDENCE.get(reason, [])),
        "reentry_blockers_if_incomplete": list(MANUAL_REENTRY_BLOCKERS_IF_INCOMPLETE.get(reason, [])),
        "required_human_resolution_notes": list(MANUAL_REQUIRED_RESOLUTION_NOTES.get(reason, [])),
        "reentry_ready_signal": MANUAL_REENTRY_READY_SIGNALS.get(reason),
        "handoff_completion_payload": dict(MANUAL_HANDOFF_COMPLETION_PAYLOADS.get(reason, {})),
        "suggested_handoff_priority_reason": MANUAL_REVIEW_PRIORITY_REASONS.get(reason, ""),
        "expected_reentry_path": MANUAL_REVIEW_REENTRY_PATHS.get(reason),
    }


def _auto_retry_policy_for_handoff_mode(handoff_mode: str) -> dict[str, Any]:
    if handoff_mode == "manual_required_hard_stop":
        return {
            "policy": "human_fix_required_before_retry",
            "auto_retry_allowed": False,
            "requires_human_fix_before_retry": True,
            "should_pause_scheduler": True,
        }
    if handoff_mode == "manual_required_retryable":
        return {
            "policy": "delayed_retry_with_human_review",
            "auto_retry_allowed": True,
            "requires_human_fix_before_retry": False,
            "should_pause_scheduler": False,
        }
    if handoff_mode == "auto_continue":
        return {
            "policy": "continue_immediately",
            "auto_retry_allowed": True,
            "requires_human_fix_before_retry": False,
            "should_pause_scheduler": False,
        }
    return {
        "policy": "observe_only",
        "auto_retry_allowed": False,
        "requires_human_fix_before_retry": False,
        "should_pause_scheduler": True,
    }


def _handoff_lifecycle_state_for_mode(handoff_mode: str) -> str:
    if handoff_mode == "manual_required_hard_stop":
        return "awaiting_human_receipt_hard_stop"
    if handoff_mode == "manual_required_retryable":
        return "awaiting_human_receipt_retryable"
    if handoff_mode == "auto_continue":
        return "auto_pipeline_active"
    return "observe_only"


def load_recent_gap_audit_snapshot(report_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(report_path) if report_path is not None else Path("datas/avm/recent_gap_audit.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return dict(payload or {})


def load_manual_review_receipt_snapshot(
    report_path: str | Path | None = None,
    repository: Any | None = None,
) -> dict[str, Any]:
    path = Path(report_path) if report_path is not None else Path("datas/avm/manual_review_receipts.json")
    return dict(list_manual_review_receipts(path, repository=repository))


def _receipt_validation_guidance(reason: str | None) -> tuple[list[str], list[str]]:
    if not reason:
        return [], []
    return (
        list(RECEIPT_FIX_ACTIONS.get(reason, [])),
        list(RECEIPT_VALIDATION_REPAIR_HINTS.get(reason, [])),
    )


def recommend_analysis_stage_actions(
    stage_snapshot: dict[str, Any] | None,
    *,
    gap_report: dict[str, Any] | None = None,
    action_effectiveness: dict[str, Any] | None = None,
    manual_review_receipt_summary: dict[str, Any] | None = None,
    fetch_archives: bool = False,
    prepare_replay: bool = False,
) -> dict[str, Any]:
    blockers = dict((stage_snapshot or {}).get("analysis_blockers", {}) or {})
    gap_report = gap_report or {}
    action_effectiveness = action_effectiveness or {}
    manual_review_receipt_summary = manual_review_receipt_summary or {}
    missing_field_counts = dict(gap_report.get("missing_field_counts", {}) or {})
    detail_stage_blockers = int(blockers.get("detail_stage", 0) or 0)
    price_anchor_blockers = int(blockers.get("price_anchor", 0) or 0)
    location_precision_blockers = int(blockers.get("location_precision", 0) or 0)
    business_area_blockers = int(blockers.get("business_area", 0) or 0)
    location_blockers = location_precision_blockers + business_area_blockers
    detail_archive_present_count = int(gap_report.get("detail_archive_present_count", 0) or 0)
    recoverability_counts = dict(gap_report.get("recoverability_counts", {}) or {})
    has_recoverability = bool(recoverability_counts)
    coordinate_missing = int(missing_field_counts.get("latitude", 0) or 0) + int(missing_field_counts.get("longitude", 0) or 0)
    matched_ready_signals = set(str(item) for item in (manual_review_receipt_summary.get("matched_ready_signals") or []))
    receipt_status = str(manual_review_receipt_summary.get("top_receipt_status") or "")
    receipt_location_ready = receipt_status in {"ready_for_reentry", "reentered_auto_pipeline"} and "location_artifacts_complete" in matched_ready_signals
    receipt_detail_ready = receipt_status in {"ready_for_reentry", "reentered_auto_pipeline"} and "detail_artifacts_complete" in matched_ready_signals
    receipt_risk_ready = receipt_status in {"ready_for_reentry", "reentered_auto_pipeline"} and "risk_facts_complete" in matched_ready_signals
    receipt_price_ready = receipt_status in {"ready_for_reentry", "reentered_auto_pipeline"} and "price_anchor_complete" in matched_ready_signals
    receipt_area_ready = receipt_status in {"ready_for_reentry", "reentered_auto_pipeline"} and "area_facts_complete" in matched_ready_signals
    receipt_status_ready = receipt_status in {"ready_for_reentry", "reentered_auto_pipeline"} and "status_reconciled" in matched_ready_signals
    future_fixable_count = int(recoverability_counts.get("future_fixable", 0) or 0)
    historical_unrecoverable_count = int(recoverability_counts.get("historical_unrecoverable", 0) or 0)
    archive_backfill_candidate_count = int(recoverability_counts.get("archive_backfill_candidate", 0) or 0)
    replay_candidate_count = int(recoverability_counts.get("replay_candidate", 0) or 0)
    coordinate_infer_candidate_count = int(recoverability_counts.get("coordinate_infer_candidate", 0) or 0)
    risk_missing = sum(
        int(missing_field_counts.get(key, 0) or 0)
        for key in ("is_occupied", "has_long_lease", "clear_delivery", "tax_burden", "is_fractional_share")
    )
    archived_effect = dict(action_effectiveness.get("archived_detail_backfill", {}) or {})
    fetch_effect = dict(action_effectiveness.get("detail_archive_fetch", {}) or {})
    replay_effect = dict(action_effectiveness.get("detail_replay_preparation", {}) or {})
    coordinate_effect = dict(action_effectiveness.get("recent_coordinate_backfill", {}) or {})
    archived_low_yield = (
        int(archived_effect.get("executed_rounds", 0) or 0) >= 2
        and int(archived_effect.get("productive_rounds", 0) or 0) <= 0
    )
    fetch_low_yield = (
        int(fetch_effect.get("executed_rounds", 0) or 0) >= 2
        and int(fetch_effect.get("productive_rounds", 0) or 0) <= 0
    )
    replay_low_yield = (
        int(replay_effect.get("executed_rounds", 0) or 0) >= 2
        and int(replay_effect.get("productive_rounds", 0) or 0) <= 0
    )
    coordinate_low_yield = (
        int(coordinate_effect.get("executed_rounds", 0) or 0) >= 2
        and int(coordinate_effect.get("productive_rounds", 0) or 0) <= 0
    )

    planned_fetch_archives = bool(fetch_archives or detail_stage_blockers > 0 or price_anchor_blockers > 0)
    planned_prepare_replay = bool(prepare_replay or detail_stage_blockers > 0)
    coordinate_focus = location_blockers > 0 or coordinate_missing > 0
    suggest_infer_location = location_blockers > 0
    run_archived_backfill = bool(detail_archive_present_count > 0 and (coordinate_missing > 0 or risk_missing > 0 or detail_stage_blockers > 0 or price_anchor_blockers > 0))
    run_coordinate_backfill = coordinate_focus and not coordinate_low_yield
    suggest_extract_risk = risk_missing > 0
    suggest_analysis_ready_recheck = False
    suggest_stage_state_reconcile = False
    deprioritized_actions: list[str] = []
    deprioritized_reason_map: dict[str, str] = {}
    feedback_hints: list[str] = []
    fallback_routes: dict[str, str] = {}
    manual_review_candidate = False
    if archived_low_yield:
        run_archived_backfill = False
        deprioritized_actions.append("archived_detail_backfill")
        deprioritized_reason_map["archived_detail_backfill"] = "archived_detail_backfill_low_yield"
        feedback_hints.append("archived_detail_backfill_low_yield")
        if suggest_extract_risk:
            fallback_routes["archived_detail_backfill"] = "extract_risk"
    if fetch_low_yield and not fetch_archives:
        planned_fetch_archives = False
        deprioritized_actions.append("fetch_archives")
        deprioritized_reason_map["fetch_archives"] = "detail_archive_fetch_low_yield"
        feedback_hints.append("detail_archive_fetch_low_yield")
        if detail_stage_blockers > 0:
            fallback_routes["fetch_archives"] = "prepare_replay"
    if replay_low_yield and not prepare_replay:
        planned_prepare_replay = False
        deprioritized_actions.append("prepare_replay")
        deprioritized_reason_map["prepare_replay"] = "detail_replay_preparation_low_yield"
        feedback_hints.append("detail_replay_preparation_low_yield")
        fallback_routes["prepare_replay"] = "manual_review"
        manual_review_candidate = True
    if coordinate_low_yield:
        deprioritized_actions.append("coordinate_backfill")
        deprioritized_reason_map["coordinate_backfill"] = "coordinate_backfill_low_yield"
        feedback_hints.append("coordinate_backfill_low_yield")
        suggest_infer_location = True
        fallback_routes["coordinate_backfill"] = "infer_location"

    if receipt_detail_ready:
        planned_prepare_replay = True
        if "manual_receipt_detail_ready" not in feedback_hints:
            feedback_hints.append("manual_receipt_detail_ready")
    if receipt_location_ready:
        coordinate_focus = True
        run_coordinate_backfill = True
        suggest_infer_location = True
        if "manual_receipt_location_ready" not in feedback_hints:
            feedback_hints.append("manual_receipt_location_ready")
    if receipt_risk_ready:
        suggest_extract_risk = True
        if "manual_receipt_risk_ready" not in feedback_hints:
            feedback_hints.append("manual_receipt_risk_ready")
    if receipt_price_ready:
        suggest_analysis_ready_recheck = True
        if "manual_receipt_price_ready" not in feedback_hints:
            feedback_hints.append("manual_receipt_price_ready")
    if receipt_area_ready:
        suggest_analysis_ready_recheck = True
        if "manual_receipt_area_ready" not in feedback_hints:
            feedback_hints.append("manual_receipt_area_ready")
    if receipt_status_ready:
        suggest_stage_state_reconcile = True
        if "manual_receipt_status_ready" not in feedback_hints:
            feedback_hints.append("manual_receipt_status_ready")

    if has_recoverability and run_archived_backfill and archive_backfill_candidate_count <= 0:
        run_archived_backfill = False
        deprioritized_actions.append("archived_detail_backfill")
        deprioritized_reason_map["archived_detail_backfill"] = "no_archive_backfill_candidate"
        feedback_hints.append("no_archive_backfill_candidate")

    if has_recoverability and planned_prepare_replay and replay_candidate_count <= 0 and historical_unrecoverable_count > 0 and not prepare_replay and not receipt_detail_ready:
        planned_prepare_replay = False
        deprioritized_actions.append("prepare_replay")
        deprioritized_reason_map["prepare_replay"] = "no_replay_candidate"
        feedback_hints.append("no_replay_candidate")

    if has_recoverability and planned_fetch_archives and replay_candidate_count <= 0 and detail_archive_present_count <= 0 and historical_unrecoverable_count > 0 and not fetch_archives:
        planned_fetch_archives = False
        deprioritized_actions.append("fetch_archives")
        deprioritized_reason_map["fetch_archives"] = "no_recoverable_detail_source"
        feedback_hints.append("no_recoverable_detail_source")

    if has_recoverability and run_coordinate_backfill and coordinate_infer_candidate_count <= 0 and coordinate_missing > 0 and not receipt_location_ready:
        run_coordinate_backfill = False
        deprioritized_actions.append("coordinate_backfill")
        deprioritized_reason_map["coordinate_backfill"] = "no_coordinate_candidate"
        feedback_hints.append("no_coordinate_candidate")

    if has_recoverability and suggest_infer_location and coordinate_infer_candidate_count <= 0 and coordinate_missing > 0 and not receipt_location_ready:
        suggest_infer_location = False

    if has_recoverability and suggest_extract_risk and archive_backfill_candidate_count <= 0 and risk_missing > 0:
        suggest_extract_risk = False

    if has_recoverability and historical_unrecoverable_count > 0 and future_fixable_count <= 0:
        manual_review_candidate = True
        if "historical_unrecoverable_gap" not in feedback_hints:
            feedback_hints.append("historical_unrecoverable_gap")

    reasons: list[str] = []
    if detail_stage_blockers > 0:
        reasons.append("detail_stage")
    if price_anchor_blockers > 0:
        reasons.append("price_anchor")
    if location_precision_blockers > 0:
        reasons.append("location_precision")
    if business_area_blockers > 0:
        reasons.append("business_area")
    if coordinate_missing > 0:
        reasons.append("missing_coordinates")
    if risk_missing > 0:
        reasons.append("risk_gap")
    if detail_archive_present_count > 0:
        reasons.append("detail_archive_present")
    reasons.extend(feedback_hints)

    priority_actions: list[str] = []
    if planned_fetch_archives:
        priority_actions.append("fetch_archives")
    if run_archived_backfill:
        priority_actions.append("archived_detail_backfill")
    if planned_prepare_replay:
        priority_actions.append("prepare_replay")
    if run_coordinate_backfill:
        priority_actions.append("coordinate_backfill")
    if suggest_infer_location:
        priority_actions.append("infer_location")
    if suggest_extract_risk:
        priority_actions.append("extract_risk")
    if suggest_analysis_ready_recheck:
        priority_actions.append("analysis_ready_recheck")
    if suggest_stage_state_reconcile:
        priority_actions.append("stage_state_reconcile")

    next_best_alternative_actions: list[str] = []
    if manual_review_candidate:
        next_best_alternative_actions.append("manual_review")
    for target_action in fallback_routes.values():
        if target_action not in next_best_alternative_actions:
            next_best_alternative_actions.append(target_action)
    for action in priority_actions:
        if action not in next_best_alternative_actions:
            next_best_alternative_actions.append(action)
    deprioritized_actions = list(dict.fromkeys(deprioritized_actions))
    feedback_hints = list(dict.fromkeys(feedback_hints))

    operator_summary = {
        "primary_action": priority_actions[0] if priority_actions else None,
        "next_best_alternative_actions": next_best_alternative_actions,
        "top_alternative_actions": next_best_alternative_actions[:3],
        "top_alternative_action": next_best_alternative_actions[0] if next_best_alternative_actions else None,
        "deprioritized_actions": deprioritized_actions,
        "feedback_hints": feedback_hints,
        "manual_review_candidate": manual_review_candidate,
        "manual_review_candidates": ["manual_review"] if manual_review_candidate else [],
    }

    return {
        "analysis_blockers": blockers,
        "missing_field_counts": missing_field_counts,
        "recoverability_counts": recoverability_counts,
        "fetch_archives": planned_fetch_archives,
        "prepare_replay": planned_prepare_replay,
        "coordinate_focus": coordinate_focus,
        "run_archived_backfill": run_archived_backfill,
        "run_coordinate_backfill": run_coordinate_backfill,
        "suggest_infer_location": suggest_infer_location,
        "suggest_extract_risk": suggest_extract_risk,
        "suggest_analysis_ready_recheck": suggest_analysis_ready_recheck,
        "suggest_stage_state_reconcile": suggest_stage_state_reconcile,
        "priority_actions": priority_actions,
        "next_best_alternative_actions": next_best_alternative_actions,
        "deprioritized_actions": deprioritized_actions,
        "deprioritized_reason_map": deprioritized_reason_map,
        "feedback_hints": feedback_hints,
        "fallback_routes": fallback_routes,
        "manual_review_candidate": manual_review_candidate,
        "operator_summary": operator_summary,
        "reasons": reasons,
    }


def load_action_effectiveness_snapshot(report_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(report_path) if report_path is not None else Path("datas/avm/data_supply_optimization_loop.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    total_progress = payload.get("total_progress") or {}
    snapshot = total_progress.get("action_effectiveness")
    return dict(snapshot or {})


def load_optimization_loop_progress_snapshot(report_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(report_path) if report_path is not None else Path("datas/avm/data_supply_optimization_loop.json")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    total_progress = payload.get("total_progress") or {}
    return dict(total_progress or {})


def summarize_manual_review_receipt_snapshot(
    receipt_snapshot: dict[str, Any] | None,
    manual_review_backlog_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    receipt_snapshot = receipt_snapshot or {}
    manual_review_backlog_summary = manual_review_backlog_summary or {}
    receipts = list(receipt_snapshot.get("receipts") or [])
    top_human_actions = list(manual_review_backlog_summary.get("top_human_actions") or [])
    action_queues = dict(manual_review_backlog_summary.get("human_action_queues") or {})
    queue_open = bool(action_queues or top_human_actions)
    known_manual_actions = set(MANUAL_REENTRY_READY_SIGNALS)
    expected_ready_signals: set[str] = set()
    for action_name in top_human_actions:
        queue = dict(action_queues.get(action_name, {}) or _manual_review_queue_metadata(action_name))
        ready_signal = queue.get("reentry_ready_signal")
        if ready_signal:
            expected_ready_signals.add(str(ready_signal))

    matched_ready_signals: list[str] = []
    valid_receipt_count = 0
    top_receipt_status = None
    status_priority = {"reentered_auto_pipeline": 2, "ready_for_reentry": 1}
    best_status_rank = -1
    invalid_receipt_reasons: dict[str, int] = {}
    seen_ready_signals: set[str] = set()
    seen_action_payloads: set[tuple[str, str]] = set()
    for receipt in receipts:
        action_name = str(receipt.get("action") or "")
        action_recognized = action_name in known_manual_actions
        action_waiting = not top_human_actions or action_name in action_queues or action_name in top_human_actions
        action_known = action_recognized and action_waiting
        queue = dict(action_queues.get(action_name, {}) or _manual_review_queue_metadata(action_name))
        ready_signal = str(receipt.get("ready_signal") or "")
        status = str(receipt.get("status") or "")
        raw_payload = receipt.get("payload")
        payload_is_mapping = isinstance(raw_payload, dict)
        payload = dict(raw_payload or {}) if payload_is_mapping else {}
        payload_fingerprint = json.dumps(payload, ensure_ascii=False, sort_keys=True) if payload_is_mapping else ""
        required_fields = list(((queue.get("handoff_completion_payload") or {}).get("required_fields") or []))
        missing_required_fields = [
            field
            for field in required_fields
            if payload.get(field) in (None, "", [])
        ]
        ready_signal_expected = ready_signal and (not expected_ready_signals or ready_signal in expected_ready_signals)
        status_supported = status in {"ready_for_reentry", "reentered_auto_pipeline"}
        if not queue_open:
            closed_queue_reason = (
                "stale_receipt_for_recovered_item"
                if status == "reentered_auto_pipeline"
                else "late_receipt_for_closed_queue"
            )
            invalid_receipt_reasons[closed_queue_reason] = int(invalid_receipt_reasons.get(closed_queue_reason, 0) or 0) + 1
        elif action_recognized and not action_waiting:
            invalid_receipt_reasons["receipt_action_not_waiting"] = int(invalid_receipt_reasons.get("receipt_action_not_waiting", 0) or 0) + 1
        elif payload_is_mapping and (action_name, payload_fingerprint) in seen_action_payloads:
            invalid_receipt_reasons["duplicate_payload_for_same_action"] = int(invalid_receipt_reasons.get("duplicate_payload_for_same_action", 0) or 0) + 1
        elif ready_signal and ready_signal in seen_ready_signals:
            invalid_receipt_reasons["duplicate_ready_signal"] = int(invalid_receipt_reasons.get("duplicate_ready_signal", 0) or 0) + 1
        elif action_known and payload_is_mapping and status_supported and ready_signal_expected and not missing_required_fields:
            if ready_signal not in matched_ready_signals:
                matched_ready_signals.append(ready_signal)
            if ready_signal:
                seen_ready_signals.add(ready_signal)
            seen_action_payloads.add((action_name, payload_fingerprint))
            valid_receipt_count += 1
            rank = status_priority.get(status, 0)
            if rank > best_status_rank:
                best_status_rank = rank
                top_receipt_status = status or None
        elif not action_recognized:
            invalid_receipt_reasons["unknown_action"] = int(invalid_receipt_reasons.get("unknown_action", 0) or 0) + 1
        elif not payload_is_mapping:
            invalid_receipt_reasons["malformed_payload"] = int(invalid_receipt_reasons.get("malformed_payload", 0) or 0) + 1
        elif not status_supported:
            invalid_receipt_reasons["unsupported_receipt_status"] = int(invalid_receipt_reasons.get("unsupported_receipt_status", 0) or 0) + 1
        elif not ready_signal_expected:
            invalid_receipt_reasons["ready_signal_mismatch"] = int(invalid_receipt_reasons.get("ready_signal_mismatch", 0) or 0) + 1
        elif missing_required_fields:
            invalid_receipt_reasons["missing_required_fields"] = int(invalid_receipt_reasons.get("missing_required_fields", 0) or 0) + 1

    if top_receipt_status is None and invalid_receipt_reasons:
        top_receipt_status = "receipt_incomplete"
    top_invalid_receipt_reason = (
        sorted(invalid_receipt_reasons.items(), key=lambda item: (-item[1], item[0]))[0][0]
        if invalid_receipt_reasons
        else None
    )
    top_receipt_fix_actions, receipt_validation_repair_hints = _receipt_validation_guidance(top_invalid_receipt_reason)

    return {
        "receipt_count": len(receipts),
        "valid_receipt_count": valid_receipt_count,
        "matched_ready_signals": matched_ready_signals,
        "top_matched_ready_signal": matched_ready_signals[0] if matched_ready_signals else None,
        "top_receipt_status": top_receipt_status,
        "invalid_receipt_count": sum(invalid_receipt_reasons.values()),
        "invalid_receipt_reasons": invalid_receipt_reasons,
        "top_invalid_receipt_reason": top_invalid_receipt_reason,
        "top_receipt_fix_actions": top_receipt_fix_actions,
        "receipt_validation_repair_hints": receipt_validation_repair_hints,
    }


def summarize_manual_review_reentry_application_summary(
    manual_review_receipt_summary: dict[str, Any] | None,
    action_feedback: dict[str, Any] | None,
    before_gap_report: dict[str, Any] | None,
    after_gap_report: dict[str, Any] | None,
    before_stage: dict[str, Any] | None,
    after_stage: dict[str, Any] | None,
) -> dict[str, Any]:
    manual_review_receipt_summary = manual_review_receipt_summary or {}
    action_feedback = action_feedback or {}
    before_gap_report = before_gap_report or {}
    after_gap_report = after_gap_report or {}
    before_stage = before_stage or {}
    after_stage = after_stage or {}

    ready_status = str(manual_review_receipt_summary.get("top_receipt_status") or "")
    matched_ready_signals = list(manual_review_receipt_summary.get("matched_ready_signals") or [])
    if ready_status != "ready_for_reentry" or not matched_ready_signals:
        return {
            "reentry_applied": False,
            "reentry_confirmed": False,
            "applied_ready_signals": [],
            "top_applied_ready_signal": None,
            "applied_actions": [],
            "top_applied_action": None,
            "confirmed_ready_signals": [],
            "top_confirmed_ready_signal": None,
            "missing_reduction_total": 0,
            "analysis_blocker_reduction_total": 0,
            "detail_enriched_delta": 0,
            "analysis_ready_delta": 0,
        }

    productive_actions = [
        action_name
        for action_name, feedback in action_feedback.items()
        if dict(feedback or {}).get("produced_work")
    ]
    before_missing = dict((before_gap_report.get("missing_field_counts") or {}) or {})
    after_missing = dict((after_gap_report.get("missing_field_counts") or {}) or {})
    missing_reduction_total = sum(
        max(0, int(before_missing.get(key, 0) or 0) - int(after_missing.get(key, 0) or 0))
        for key in set(before_missing) | set(after_missing)
    )
    before_blockers = dict((before_stage.get("analysis_blockers") or {}) or {})
    after_blockers = dict((after_stage.get("analysis_blockers") or {}) or {})
    blocker_reduction_total = sum(
        max(0, int(before_blockers.get(key, 0) or 0) - int(after_blockers.get(key, 0) or 0))
        for key in set(before_blockers) | set(after_blockers)
    )
    detail_enriched_delta = max(0, int(after_stage.get("detail_enriched", 0) or 0) - int(before_stage.get("detail_enriched", 0) or 0))
    analysis_ready_delta = max(0, int(after_stage.get("analysis_ready", 0) or 0) - int(before_stage.get("analysis_ready", 0) or 0))
    reentry_applied = bool(
        productive_actions
        or missing_reduction_total > 0
        or blocker_reduction_total > 0
        or detail_enriched_delta > 0
        or analysis_ready_delta > 0
    )
    reentry_confirmed = bool(
        missing_reduction_total > 0
        or blocker_reduction_total > 0
        or detail_enriched_delta > 0
        or analysis_ready_delta > 0
    )

    return {
        "reentry_applied": reentry_applied,
        "reentry_confirmed": reentry_confirmed,
        "applied_ready_signals": matched_ready_signals if reentry_applied else [],
        "top_applied_ready_signal": matched_ready_signals[0] if reentry_applied and matched_ready_signals else None,
        "applied_actions": productive_actions if reentry_applied else [],
        "top_applied_action": productive_actions[0] if reentry_applied and productive_actions else None,
        "confirmed_ready_signals": matched_ready_signals if reentry_confirmed else [],
        "top_confirmed_ready_signal": matched_ready_signals[0] if reentry_confirmed and matched_ready_signals else None,
        "missing_reduction_total": missing_reduction_total,
        "analysis_blocker_reduction_total": blocker_reduction_total,
        "detail_enriched_delta": detail_enriched_delta,
        "analysis_ready_delta": analysis_ready_delta,
    }


def summarize_action_effectiveness_snapshot(action_effectiveness: dict[str, Any] | None) -> dict[str, Any]:
    snapshot = dict(action_effectiveness or {})
    low_yield_rows: list[tuple[str, int, int]] = []
    productive_rows: list[tuple[str, int]] = []
    for action_name, stats in snapshot.items():
        executed_rounds = int((stats or {}).get("executed_rounds", 0) or 0)
        productive_rounds = int((stats or {}).get("productive_rounds", 0) or 0)
        if executed_rounds > 0 and productive_rounds <= 0:
            low_yield_rows.append((action_name, executed_rounds, productive_rounds))
        if productive_rounds > 0:
            productive_rows.append((action_name, productive_rounds))
    low_yield_rows.sort(key=lambda item: (-item[1], item[0]))
    productive_rows.sort(key=lambda item: (-item[1], item[0]))
    low_yield_actions = [name for name, _, _ in low_yield_rows]
    productive_actions = [name for name, _ in productive_rows]
    return {
        "action_count": len(snapshot),
        "low_yield_actions": low_yield_actions,
        "productive_actions": productive_actions,
        "top_low_yield_action": low_yield_actions[0] if low_yield_actions else None,
        "top_productive_action": productive_actions[0] if productive_actions else None,
        "top_low_yield_actions": low_yield_actions[:3],
        "top_productive_actions": productive_actions[:3],
        "snapshot": snapshot,
    }


def summarize_operator_action_surface(
    recommended_actions: dict[str, Any] | None,
    action_effectiveness_summary: dict[str, Any] | None = None,
    recoverability_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    recommended_actions = recommended_actions or {}
    action_effectiveness_summary = action_effectiveness_summary or {}
    recoverability_summary = recoverability_summary or {}
    operator_summary = dict(recommended_actions.get("operator_summary", {}) or {})
    feedback_hints = list(operator_summary.get("feedback_hints") or [])
    top_manual_review_reason = None
    for hint in feedback_hints:
        if "manual_review" in hint or "historical_unrecoverable" in hint:
            top_manual_review_reason = hint
            break
    if top_manual_review_reason is None and recoverability_summary.get("top_manual_review_reason"):
        top_manual_review_reason = recoverability_summary.get("top_manual_review_reason")
    manual_review_candidates = list(
        operator_summary.get("manual_review_candidates")
        or (["manual_review"] if operator_summary.get("manual_review_candidate") else [])
    )
    return {
        "primary_action": operator_summary.get("primary_action"),
        "top_alternative_actions": list(operator_summary.get("top_alternative_actions") or operator_summary.get("next_best_alternative_actions") or [])[:3],
        "deprioritized_actions": list(operator_summary.get("deprioritized_actions") or []),
        "feedback_hints": feedback_hints,
        "manual_review_candidates": manual_review_candidates,
        "manual_review_required": bool(manual_review_candidates or top_manual_review_reason),
        "top_low_yield_actions": list(action_effectiveness_summary.get("top_low_yield_actions") or []),
        "top_productive_actions": list(action_effectiveness_summary.get("top_productive_actions") or []),
        "recoverability_summary": recoverability_summary,
        "top_manual_review_reason": top_manual_review_reason,
    }


def summarize_recoverability_snapshot(gap_report: dict[str, Any] | None) -> dict[str, Any]:
    gap_report = gap_report or {}
    counts = dict(gap_report.get("recoverability_counts", {}) or {})
    action_candidates = [
        ("infer_location", int(counts.get("coordinate_infer_candidate", 0) or 0)),
        ("archived_detail_backfill", int(counts.get("archive_backfill_candidate", 0) or 0)),
        ("prepare_replay", int(counts.get("replay_candidate", 0) or 0)),
    ]
    action_candidates = [item for item in action_candidates if item[1] > 0]
    action_candidates.sort(key=lambda item: (-item[1], item[0]))
    future_fixable = int(counts.get("future_fixable", 0) or 0)
    historical_unrecoverable = int(counts.get("historical_unrecoverable", 0) or 0)
    return {
        "future_fixable": future_fixable,
        "historical_unrecoverable": historical_unrecoverable,
        "archive_backfill_candidate": int(counts.get("archive_backfill_candidate", 0) or 0),
        "replay_candidate": int(counts.get("replay_candidate", 0) or 0),
        "coordinate_infer_candidate": int(counts.get("coordinate_infer_candidate", 0) or 0),
        "top_recoverable_actions": [name for name, _count in action_candidates[:3]],
        "top_manual_review_reason": "historical_unrecoverable_gap" if historical_unrecoverable > 0 and future_fixable <= 0 else None,
    }


def summarize_manual_review_backlog(
    gap_report: dict[str, Any] | None,
    *,
    limit: int = 5,
) -> dict[str, Any]:
    gap_report = gap_report or {}
    counts = dict(gap_report.get("recoverability_counts", {}) or {})
    samples = list(gap_report.get("samples") or [])
    backlog_samples = [sample for sample in samples if sample.get("historical_unrecoverable")]
    trimmed = backlog_samples[:limit]
    reason_buckets: dict[str, int] = {}
    reason_priority = {
        "manual_location_review": 0,
        "manual_detail_capture_review": 1,
        "manual_price_anchor_review": 2,
        "manual_risk_review": 3,
        "manual_area_review": 4,
        "manual_status_review": 5,
    }

    def _bump(reason: str) -> None:
        reason_buckets[reason] = int(reason_buckets.get(reason, 0) or 0) + 1

    human_action_queues: dict[str, dict[str, Any]] = {}

    def _queue(reason: str, sample: dict[str, Any]) -> None:
        queue = human_action_queues.setdefault(
            reason,
            {
                "count": 0,
                **_manual_review_queue_metadata(reason),
                "sample_item_ids": [],
                "sample_titles": [],
                "sample_summaries": [],
            },
        )
        queue["count"] = int(queue.get("count", 0) or 0) + 1
        item_id = sample.get("item_id")
        if item_id not in (None, "") and len(queue["sample_item_ids"]) < limit:
            queue["sample_item_ids"].append(str(item_id))
        title = sample.get("title")
        if title not in (None, "") and len(queue["sample_titles"]) < limit:
            queue["sample_titles"].append(str(title))
        if len(queue["sample_summaries"]) < limit:
            queue["sample_summaries"].append(
                {
                    "item_id": sample.get("item_id"),
                    "title": sample.get("title"),
                    "missing_fields": list(sample.get("missing_fields") or []),
                    "analysis_missing_fields": list(sample.get("analysis_missing_fields") or []),
                }
            )

    for sample in backlog_samples:
        analysis_missing = set(str(item) for item in (sample.get("analysis_missing_fields") or []))
        missing_fields = set(str(item) for item in (sample.get("missing_fields") or []))
        location_review_needed = False
        if "detail_stage" in analysis_missing:
            _bump("manual_detail_capture_review")
            _queue("manual_detail_capture_review", sample)
        if "price_anchor" in analysis_missing:
            _bump("manual_price_anchor_review")
            _queue("manual_price_anchor_review", sample)
        if (
            "location_precision" in analysis_missing
            or "city" in analysis_missing
            or "district" in analysis_missing
            or "business_area" in analysis_missing
            or "latitude" in missing_fields
            or "longitude" in missing_fields
        ):
            location_review_needed = True
        if "area_sqm" in analysis_missing:
            _bump("manual_area_review")
            _queue("manual_area_review", sample)
        if "status" in analysis_missing:
            _bump("manual_status_review")
            _queue("manual_status_review", sample)
        if {"is_occupied", "has_long_lease", "clear_delivery", "tax_burden", "is_fractional_share"} & missing_fields:
            _bump("manual_risk_review")
            _queue("manual_risk_review", sample)
        if sample.get("historical_unrecoverable"):
            location_review_needed = True
        if location_review_needed:
            _bump("manual_location_review")
            _queue("manual_location_review", sample)

    sorted_reasons = sorted(
        reason_buckets.items(),
        key=lambda item: (-item[1], MANUAL_REVIEW_REASON_PRIORITY.get(item[0], 99), item[0]),
    )
    return {
        "candidate_count": int(counts.get("historical_unrecoverable", 0) or 0),
        "sample_item_ids": [str(sample.get("item_id") or "") for sample in trimmed if sample.get("item_id") not in (None, "")],
        "sample_titles": [str(sample.get("title") or "") for sample in trimmed if sample.get("title") not in (None, "")],
        "reason_buckets": reason_buckets,
        "top_human_actions": [name for name, _count in sorted_reasons[:3]],
        "top_human_action_instructions": [MANUAL_REVIEW_ACTION_INSTRUCTIONS.get(name, "") for name, _count in sorted_reasons[:3]],
        "top_human_reentry_paths": [MANUAL_REVIEW_REENTRY_PATHS.get(name) for name, _count in sorted_reasons[:3]],
        "human_action_queues": human_action_queues,
        "sample_summaries": [
            {
                "item_id": sample.get("item_id"),
                "title": sample.get("title"),
                "missing_fields": list(sample.get("missing_fields") or []),
                "analysis_missing_fields": list(sample.get("analysis_missing_fields") or []),
            }
            for sample in trimmed
        ],
    }


def summarize_scheduler_feedback_snapshot(total_progress: dict[str, Any] | None) -> dict[str, Any]:
    total_progress = total_progress or {}
    fallback_usage = dict(total_progress.get("fallback_usage", {}) or {})
    handoff_mode_counts = dict(total_progress.get("handoff_mode_counts", {}) or {})
    handoff_lifecycle_counts = dict(total_progress.get("handoff_lifecycle_counts", {}) or {})
    human_action_counts = dict(total_progress.get("human_action_counts", {}) or {})
    retry_policy_counts = dict(total_progress.get("retry_policy_counts", {}) or {})
    pending_ready_signal_counts = dict(total_progress.get("pending_ready_signal_counts", {}) or {})
    matched_ready_signal_counts = dict(total_progress.get("matched_ready_signal_counts", {}) or {})
    invalid_receipt_reason_counts = dict(total_progress.get("invalid_receipt_reason_counts", {}) or {})
    confirmed_ready_signal_counts = dict(total_progress.get("confirmed_ready_signal_counts", {}) or {})
    manual_review_candidate_rounds = int(total_progress.get("manual_review_candidate_rounds", 0) or 0)
    if not handoff_mode_counts and manual_review_candidate_rounds > 0:
        handoff_mode_counts["manual_required_hard_stop"] = manual_review_candidate_rounds
    if not handoff_lifecycle_counts and manual_review_candidate_rounds > 0:
        handoff_lifecycle_counts["awaiting_human_receipt_hard_stop"] = manual_review_candidate_rounds
    flattened_fallbacks: list[tuple[str, int]] = []
    for source_action, targets in fallback_usage.items():
        for target_action, count in dict(targets or {}).items():
            flattened_fallbacks.append((f"{source_action}->{target_action}", int(count or 0)))
    flattened_fallbacks.sort(key=lambda item: (-item[1], item[0]))
    top_handoff_mode = total_progress.get("top_handoff_mode")
    if top_handoff_mode is None and handoff_mode_counts:
        top_handoff_mode = sorted(handoff_mode_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    top_human_actions = total_progress.get("top_human_actions")
    if top_human_actions is None and human_action_counts:
        top_human_actions = [
            name
            for name, _count in sorted(
                human_action_counts.items(),
                key=lambda item: (-int(item[1] or 0), MANUAL_REVIEW_REASON_PRIORITY.get(item[0], 99), item[0]),
            )[:3]
        ]
    top_retry_policy = total_progress.get("top_retry_policy")
    if top_retry_policy is None and retry_policy_counts:
        top_retry_policy = sorted(retry_policy_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    top_handoff_lifecycle_state = total_progress.get("top_handoff_lifecycle_state")
    if top_handoff_lifecycle_state is None and handoff_lifecycle_counts:
        top_handoff_lifecycle_state = sorted(handoff_lifecycle_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    top_pending_ready_signal = total_progress.get("top_pending_ready_signal")
    if top_pending_ready_signal is None and pending_ready_signal_counts:
        top_pending_ready_signal = sorted(pending_ready_signal_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    top_matched_ready_signal = total_progress.get("top_matched_ready_signal")
    if top_matched_ready_signal is None and matched_ready_signal_counts:
        top_matched_ready_signal = sorted(matched_ready_signal_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    top_invalid_receipt_reason = total_progress.get("top_invalid_receipt_reason")
    if top_invalid_receipt_reason is None and invalid_receipt_reason_counts:
        top_invalid_receipt_reason = sorted(invalid_receipt_reason_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    top_receipt_fix_actions, receipt_validation_repair_hints = _receipt_validation_guidance(top_invalid_receipt_reason)
    top_reentry_confirmed_signal = total_progress.get("top_reentry_confirmed_signal")
    if top_reentry_confirmed_signal is None and confirmed_ready_signal_counts:
        top_reentry_confirmed_signal = sorted(confirmed_ready_signal_counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return {
        "manual_review_candidate_rounds": manual_review_candidate_rounds,
        "manual_review_reasons": dict(total_progress.get("manual_review_reasons", {}) or {}),
        "top_manual_review_reason": total_progress.get("top_manual_review_reason"),
        "fallback_usage": fallback_usage,
        "top_fallback_routes": [name for name, _count in flattened_fallbacks[:3]],
        "human_action_counts": human_action_counts,
        "top_human_actions": list(top_human_actions or []),
        "retry_policy_counts": retry_policy_counts,
        "top_retry_policy": top_retry_policy,
        "handoff_mode_counts": handoff_mode_counts,
        "top_handoff_mode": top_handoff_mode,
        "handoff_lifecycle_counts": handoff_lifecycle_counts,
        "top_handoff_lifecycle_state": top_handoff_lifecycle_state,
        "pending_ready_signal_counts": pending_ready_signal_counts,
        "top_pending_ready_signal": top_pending_ready_signal,
        "matched_ready_signal_counts": matched_ready_signal_counts,
        "top_matched_ready_signal": top_matched_ready_signal,
        "invalid_receipt_reason_counts": invalid_receipt_reason_counts,
        "top_invalid_receipt_reason": top_invalid_receipt_reason,
        "top_receipt_fix_actions": top_receipt_fix_actions,
        "receipt_validation_repair_hints": receipt_validation_repair_hints,
        "reentry_confirmed_rounds": int(total_progress.get("reentry_confirmed_rounds", 0) or 0),
        "confirmed_ready_signal_counts": confirmed_ready_signal_counts,
        "top_reentry_confirmed_signal": top_reentry_confirmed_signal,
    }


def summarize_operator_overview(
    operator_action_summary: dict[str, Any] | None,
    scheduler_feedback_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    operator_action_summary = operator_action_summary or {}
    scheduler_feedback_summary = scheduler_feedback_summary or {}
    recoverability_summary = dict(operator_action_summary.get("recoverability_summary", {}) or {})
    manual_review_backlog_summary = dict(operator_action_summary.get("manual_review_backlog_summary", {}) or {})
    manual_review_receipt_summary = dict(operator_action_summary.get("manual_review_receipt_summary", {}) or {})
    manual_review_reentry_application_summary = dict(operator_action_summary.get("manual_review_reentry_application_summary", {}) or {})
    top_human_actions = list(manual_review_backlog_summary.get("top_human_actions") or [])
    top_human_action_instructions = list(manual_review_backlog_summary.get("top_human_action_instructions") or [])
    top_human_reentry_paths = list(manual_review_backlog_summary.get("top_human_reentry_paths") or [])
    manual_review_required = bool(operator_action_summary.get("manual_review_required"))
    future_fixable = int(recoverability_summary.get("future_fixable", 0) or 0)
    receipt_status = str(manual_review_receipt_summary.get("top_receipt_status") or "")
    top_invalid_receipt_reason = manual_review_receipt_summary.get("top_invalid_receipt_reason")
    top_receipt_fix_actions = list(manual_review_receipt_summary.get("top_receipt_fix_actions") or [])
    receipt_validation_repair_hints = list(manual_review_receipt_summary.get("receipt_validation_repair_hints") or [])
    if not top_receipt_fix_actions and top_invalid_receipt_reason:
        top_receipt_fix_actions, receipt_validation_repair_hints = _receipt_validation_guidance(str(top_invalid_receipt_reason))
    elif not top_receipt_fix_actions:
        top_receipt_fix_actions = list(scheduler_feedback_summary.get("top_receipt_fix_actions") or [])
        receipt_validation_repair_hints = list(scheduler_feedback_summary.get("receipt_validation_repair_hints") or [])
    if receipt_status == "reentered_auto_pipeline":
        handoff_mode = "auto_continue"
        handoff_lifecycle_state = "reentered_auto_pipeline"
    elif manual_review_reentry_application_summary.get("reentry_confirmed"):
        handoff_mode = "auto_continue"
        handoff_lifecycle_state = "reentry_confirmed"
    elif manual_review_reentry_application_summary.get("reentry_applied"):
        handoff_mode = "auto_continue"
        handoff_lifecycle_state = "reentry_applied"
    elif receipt_status == "ready_for_reentry":
        handoff_mode = "auto_continue"
        handoff_lifecycle_state = "receipt_ready_for_reentry"
    elif receipt_status == "receipt_incomplete":
        handoff_mode = "manual_required_retryable" if future_fixable > 0 else "manual_required_hard_stop"
        handoff_lifecycle_state = "awaiting_valid_receipt"
    elif manual_review_required:
        handoff_mode = "manual_required_retryable" if future_fixable > 0 else "manual_required_hard_stop"
        handoff_lifecycle_state = _handoff_lifecycle_state_for_mode(handoff_mode)
    elif operator_action_summary.get("primary_action") or recoverability_summary.get("top_recoverable_actions"):
        handoff_mode = "auto_continue"
        handoff_lifecycle_state = _handoff_lifecycle_state_for_mode(handoff_mode)
    else:
        handoff_mode = "observe_only"
        handoff_lifecycle_state = _handoff_lifecycle_state_for_mode(handoff_mode)
    auto_retry_policy = _auto_retry_policy_for_handoff_mode(handoff_mode)
    top_queue_action = top_human_actions[0] if top_human_actions else None
    top_queue = None
    if top_queue_action:
        top_queue = dict((manual_review_backlog_summary.get("human_action_queues") or {}).get(top_queue_action, {}) or {})
        queue_defaults = _manual_review_queue_metadata(top_queue_action)
        queue_defaults["instruction"] = (
            top_human_action_instructions[0]
            if top_human_action_instructions
            else queue_defaults["instruction"]
        )
        queue_defaults["expected_reentry_path"] = (
            top_human_reentry_paths[0]
            if top_human_reentry_paths
            else queue_defaults["expected_reentry_path"]
        )
        for key, value in queue_defaults.items():
            top_queue.setdefault(key, value)
        top_queue.setdefault("count", int((manual_review_backlog_summary.get("reason_buckets") or {}).get(top_queue_action, 0) or 0))
        sample_summaries = list(top_queue.get("sample_summaries") or [])
        if not sample_summaries:
            backlog_sample_summaries = list(manual_review_backlog_summary.get("sample_summaries") or [])
            if backlog_sample_summaries:
                sample_summaries = backlog_sample_summaries
            else:
                sample_item_ids = list(manual_review_backlog_summary.get("sample_item_ids") or [])
                sample_titles = list(manual_review_backlog_summary.get("sample_titles") or [])
                sample_summaries = [
                    {"item_id": item_id, "title": sample_titles[index] if index < len(sample_titles) else None}
                    for index, item_id in enumerate(sample_item_ids)
                ]
        top_queue.setdefault(
            "sample_summaries",
            sample_summaries,
        )
        top_queue = {"action": top_queue_action, **top_queue}
    pending_ready_signals = []
    if top_queue_action:
        ready_signal = (top_queue or {}).get("reentry_ready_signal")
        if ready_signal:
            pending_ready_signals.append(str(ready_signal))
    matched_ready_signals = list(manual_review_receipt_summary.get("matched_ready_signals") or [])
    top_matched_ready_signal = manual_review_receipt_summary.get("top_matched_ready_signal")
    applied_ready_signals = list(manual_review_reentry_application_summary.get("applied_ready_signals") or [])
    top_applied_ready_signal = manual_review_reentry_application_summary.get("top_applied_ready_signal")
    top_applied_action = manual_review_reentry_application_summary.get("top_applied_action")
    confirmed_ready_signals = list(manual_review_reentry_application_summary.get("confirmed_ready_signals") or [])
    top_confirmed_ready_signal = manual_review_reentry_application_summary.get("top_confirmed_ready_signal")
    handoff_waiting_for_human_receipt = (
        handoff_lifecycle_state.startswith("awaiting_human_receipt")
        or handoff_lifecycle_state == "awaiting_valid_receipt"
    )
    scheduler_pause_recommended = handoff_waiting_for_human_receipt or bool(auto_retry_policy.get("should_pause_scheduler"))
    resume_on_ready_signal = top_applied_ready_signal or top_matched_ready_signal or (pending_ready_signals[0] if pending_ready_signals else scheduler_feedback_summary.get("top_pending_ready_signal"))
    resume_action = (top_queue or {}).get("expected_reentry_path") if top_queue else None
    should_resume_automation = handoff_lifecycle_state in {
        "receipt_ready_for_reentry",
        "reentry_applied",
        "reentry_confirmed",
        "reentered_auto_pipeline",
        "auto_pipeline_active",
    }
    return {
        "primary_action": operator_action_summary.get("primary_action"),
        "handoff_mode": handoff_mode,
        "handoff_lifecycle_state": handoff_lifecycle_state,
        "auto_retry_policy": auto_retry_policy,
        "handoff_waiting_for_human_receipt": handoff_waiting_for_human_receipt,
        "scheduler_pause_recommended": scheduler_pause_recommended,
        "resume_on_ready_signal": resume_on_ready_signal,
        "resume_action": resume_action,
        "should_resume_automation": should_resume_automation,
        "matched_ready_signals": matched_ready_signals,
        "top_matched_ready_signal": top_matched_ready_signal,
        "reentry_applied": bool(manual_review_reentry_application_summary.get("reentry_applied")),
        "applied_ready_signals": applied_ready_signals,
        "top_applied_ready_signal": top_applied_ready_signal,
        "top_applied_action": top_applied_action,
        "reentry_confirmed": bool(manual_review_reentry_application_summary.get("reentry_confirmed")),
        "confirmed_ready_signals": confirmed_ready_signals,
        "top_confirmed_ready_signal": top_confirmed_ready_signal,
        "invalid_receipt_count": int(manual_review_receipt_summary.get("invalid_receipt_count", 0) or 0),
        "top_invalid_receipt_reason": top_invalid_receipt_reason,
        "top_receipt_fix_actions": top_receipt_fix_actions,
        "receipt_validation_repair_hints": receipt_validation_repair_hints,
        "manual_review_required": manual_review_required,
        "top_manual_review_reason": operator_action_summary.get("top_manual_review_reason"),
        "manual_review_candidate_rounds": int(scheduler_feedback_summary.get("manual_review_candidate_rounds", 0) or 0),
        "handoff_mode_counts": dict(scheduler_feedback_summary.get("handoff_mode_counts", {}) or {}),
        "top_handoff_mode": scheduler_feedback_summary.get("top_handoff_mode"),
        "handoff_lifecycle_counts": dict(scheduler_feedback_summary.get("handoff_lifecycle_counts", {}) or {}),
        "top_handoff_lifecycle_state": scheduler_feedback_summary.get("top_handoff_lifecycle_state"),
        "pending_ready_signal_counts": dict(scheduler_feedback_summary.get("pending_ready_signal_counts", {}) or {}),
        "top_pending_ready_signal": top_matched_ready_signal or (pending_ready_signals[0] if pending_ready_signals else scheduler_feedback_summary.get("top_pending_ready_signal")),
        "pending_ready_signals": pending_ready_signals,
        "top_fallback_routes": list(scheduler_feedback_summary.get("top_fallback_routes") or []),
        "top_recoverable_actions": list(recoverability_summary.get("top_recoverable_actions") or []),
        "top_human_actions": top_human_actions,
        "top_human_action_instructions": top_human_action_instructions,
        "top_human_reentry_paths": top_human_reentry_paths,
        "top_human_action_queue": top_queue,
        "manual_review_sample_item_ids": list(manual_review_backlog_summary.get("sample_item_ids") or []),
        "future_fixable": future_fixable,
        "historical_unrecoverable": int(recoverability_summary.get("historical_unrecoverable", 0) or 0),
        "top_low_yield_actions": list(operator_action_summary.get("top_low_yield_actions") or []),
        "top_alternative_actions": list(operator_action_summary.get("top_alternative_actions") or []),
    }


def summarize_action_feedback(
    recommended_actions: dict[str, Any] | None,
    report_sections: dict[str, dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    recommended_actions = recommended_actions or {}
    report_sections = report_sections or {}
    action_specs = {
        "detail_archive_fetch": {
            "recommended_flag": "fetch_archives",
            "productive_key": "fetched_count",
        },
        "archived_detail_backfill": {
            "recommended_flag": "run_archived_backfill",
            "productive_key": "updated_records",
        },
        "recent_coordinate_backfill": {
            "recommended_flag": "run_coordinate_backfill",
            "productive_key": "updated_count",
        },
        "detail_replay_preparation": {
            "recommended_flag": "prepare_replay",
            "productive_key": "prepared_count",
        },
        "analysis_ready_recheck": {
            "recommended_flag": "suggest_analysis_ready_recheck",
            "productive_key": "updated_count",
        },
        "stage_state_reconcile": {
            "recommended_flag": "suggest_stage_state_reconcile",
            "productive_key": "updated_count",
        },
    }

    output: dict[str, dict[str, Any]] = {}
    for action_name, spec in action_specs.items():
        section = dict(report_sections.get(action_name, {}) or {})
        productive_key = spec["productive_key"]
        skipped = bool(section.get("skipped"))
        executed = bool(section) and not skipped
        productive_count = int(section.get(productive_key, 0) or 0)
        output[action_name] = {
            "recommended": bool(recommended_actions.get(spec["recommended_flag"])),
            "executed": executed,
            "produced_work": productive_count > 0,
            "productive_count": productive_count,
            "metrics": section,
        }
    return output
