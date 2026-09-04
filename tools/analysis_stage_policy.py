from __future__ import annotations

from typing import Any


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


def _receipt_validation_guidance(reason: str | None) -> tuple[list[str], list[str]]:
    if not reason:
        return [], []
    return (
        list(RECEIPT_FIX_ACTIONS.get(reason, [])),
        list(RECEIPT_VALIDATION_REPAIR_HINTS.get(reason, [])),
    )


__all__ = ['MANUAL_REVIEW_REASON_PRIORITY', 'MANUAL_REVIEW_ACTION_INSTRUCTIONS', 'MANUAL_REVIEW_REENTRY_PATHS', 'MANUAL_REVIEW_QUEUE_LEVEL_INSTRUCTIONS', 'MANUAL_REVIEW_QUEUE_LEVEL_CHECKLISTS', 'MANUAL_REVIEW_PRIORITY_REASONS', 'MANUAL_REVIEW_COMPLETION_CRITERIA', 'MANUAL_REENTRY_VALIDATION_CHECKLISTS', 'MANUAL_HANDOFF_ARTIFACT_FIELDS', 'MANUAL_REQUIRED_HUMAN_EVIDENCE', 'MANUAL_REENTRY_BLOCKERS_IF_INCOMPLETE', 'MANUAL_REQUIRED_RESOLUTION_NOTES', 'MANUAL_REENTRY_READY_SIGNALS', 'MANUAL_HANDOFF_COMPLETION_PAYLOADS', 'RECEIPT_FIX_ACTIONS', 'RECEIPT_VALIDATION_REPAIR_HINTS', '_manual_review_priority_label', '_manual_review_suggested_handoff_priority', '_manual_review_queue_metadata', '_auto_retry_policy_for_handoff_mode', '_handoff_lifecycle_state_for_mode', '_receipt_validation_guidance']
