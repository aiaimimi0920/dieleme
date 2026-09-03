from __future__ import annotations

import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Mapping, Sequence


ANALYSIS_MODULE_B_VERSION = "analysis_module_b_v1"

MONEY_FIELDS = {
    "市场评估价",
    "起拍价格",
    "成交价格",
    "保证金",
    "evaluation_price",
    "starting_price",
    "transaction_price",
    "deposit",
}
AREA_FIELDS = {
    "建筑面积",
    "产权建筑面积",
    "area_sqm",
    "gross_area_sqm",
    "interior_area_sqm",
    "land_area_sqm",
}
RATIO_FIELDS = {"产权份额比例", "ownership_share_ratio"}
COUNT_FIELDS = {
    "竞拍人数",
    "出价次数",
    "出价人数",
    "围观人数",
    "提醒人数",
    "浏览次数",
    "apply_count",
    "bid_count",
    "bidder_count",
    "watch_count",
    "reminder_count",
    "view_count",
    "build_year",
    "total_floors",
}
BOOLEAN_FIELDS = {
    "是否成交",
    "is_occupied",
    "has_long_lease",
    "clear_delivery",
    "property_fee_owed",
    "is_restricted_purchase",
    "is_fractional_share",
    "tax_is_company_owned",
    "has_lease_before_mortgage",
    "has_elevator",
    "includes_parking",
    "has_keys",
    "is_haunted",
    "special_school_tag",
}
DATETIME_FIELDS = {"开拍时间", "交易时间", "auction_date", "auction_start_time"}
DERIVED_FIELDS = {"单价", "unit_price"}
SYSTEM_FIELDS = {
    "id",
    "唯一id",
    "source_item_id",
    "原始网站",
    "source_url",
    "url",
    "标题",
    "title",
    "source_title",
    "is_processed",
    "detail_captured",
    "status",
    "auction_date",
    "currentPrice",
    "initialPrice",
    "applyCount",
    "bidCount",
    "bidderCount",
    "deposit",
    "latitude",
    "longitude",
    "纬度",
    "经度",
    "coordinate_source",
    "extraction_confidence",
    "evidence_span",
    "evidence_source",
    "extraction_version",
}
HIGH_RISK_FIELDS = {
    *MONEY_FIELDS,
    *AREA_FIELDS,
    *RATIO_FIELDS,
    *DATETIME_FIELDS,
    "是否成交",
    "法院名称",
    "案号",
    "is_occupied",
    "has_long_lease",
    "clear_delivery",
    "tax_burden",
    "property_fee_owed",
    "is_restricted_purchase",
    "is_fractional_share",
    "tax_is_company_owned",
    "has_lease_before_mortgage",
}

FIELD_KEYWORDS: dict[str, tuple[str, ...]] = {
    "市场评估价": ("市场评估价", "评估价", "评估价格"),
    "起拍价格": ("起拍价格", "起拍价", "initialPrice"),
    "成交价格": ("成交价格", "成交价", "拍下价", "currentPrice"),
    "保证金": ("保证金", "deposit"),
    "开拍时间": ("开拍时间", "startTime"),
    "交易时间": ("交易时间", "auction_date", "结束时间"),
    "是否成交": ("是否成交", "status"),
    "竞拍人数": ("竞拍人数", "报名人数", "applyCount"),
    "出价次数": ("出价次数", "bidCount"),
    "出价人数": ("出价人数", "bidUserNumber"),
    "围观人数": ("围观人数", "围观", "watchCount", "pv"),
    "提醒人数": ("提醒人数", "提醒", "remindCount"),
    "浏览次数": ("浏览次数", "浏览", "viewCount"),
    "地点": ("地点", "地址", "address"),
    "完整地址": ("完整地址", "地址", "address"),
    "所属小区": ("所属小区", "小区", "楼盘", "community"),
    "省份": ("省份", "省"),
    "城市": ("城市", "市"),
    "区": ("区县", "行政区", "区"),
    "最靠近商圈": ("商圈", "板块"),
    "建筑面积": ("建筑面积", "description_area_sqm", "building_area"),
    "产权建筑面积": ("产权建筑面积", "原始产权建筑面积"),
    "产权份额比例": ("产权份额比例", "产权份额", "所有权份额"),
    "法院名称": ("法院名称", "执行法院", "法院"),
    "案号": ("案号",),
    "is_occupied": ("占用", "占有人", "腾退"),
    "has_long_lease": ("租赁", "租约", "承租"),
    "clear_delivery": ("腾退", "交付", "清场"),
    "tax_burden": ("税费", "税款", "税金"),
    "property_fee_owed": ("物业费", "欠费"),
    "is_restricted_purchase": ("限购", "购房资格"),
    "is_fractional_share": ("份额", "产权"),
    "tax_is_company_owned": ("公司所有", "企业所有", "税费"),
    "has_lease_before_mortgage": ("租赁", "抵押"),
}

_NUMBER_RE = re.compile(r"[-+]?\d[\d,]*(?:\.\d+)?\s*(?:亿元|万元|亿|万|元|平方米|平方|㎡|%|％)?")
_PUNCTUATION_RE = re.compile(r"[\s\-—_，,。.;；:：/\\()（）\[\]【】{}<>《》'\"]+")


def parse_distinct_models(value: str | Iterable[str], *, expected: int = 3) -> tuple[str, ...]:
    raw_values = re.split(r"[;,]", value) if isinstance(value, str) else list(value)
    models: list[str] = []
    for raw in raw_values:
        model = str(raw or "").strip()
        if model and model not in models:
            models.append(model)
    if len(models) != expected:
        raise ValueError(f"analysis module B requires exactly {expected} distinct candidate models; got {len(models)}")
    return tuple(models)


def _field_name(field_path: str) -> str:
    return str(field_path).rsplit(".", 1)[-1]


def _normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    text = text.replace("幢", "栋")
    return _PUNCTUATION_RE.sub("", text)


def _decimal_value(value: Any, *, ratio: bool = False) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            result = Decimal(str(value))
        except InvalidOperation:
            return None
        return result

    text = unicodedata.normalize("NFKC", str(value)).strip().replace(",", "")
    if not text:
        return None
    multiplier = Decimal("1")
    if "亿" in text:
        multiplier = Decimal("100000000")
    elif "万" in text:
        multiplier = Decimal("10000")
    if ratio and ("%" in text or "％" in str(value)):
        multiplier = Decimal("0.01")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", text)
    if match is None:
        return None
    try:
        return Decimal(match.group(0)) * multiplier
    except InvalidOperation:
        return None


def normalize_field_value(field_path: str, value: Any) -> str:
    field = _field_name(field_path)
    if value is None or value == "":
        return "null"
    if field in BOOLEAN_FIELDS:
        if isinstance(value, bool):
            return f"bool:{str(value).lower()}"
        normalized = _normalize_text(value)
        if normalized in {"true", "1", "是", "有", "已成交", "done"}:
            return "bool:true"
        if normalized in {"false", "0", "否", "无", "未成交", "failed"}:
            return "bool:false"
        return f"text:{normalized}"
    if field in MONEY_FIELDS | AREA_FIELDS | RATIO_FIELDS | COUNT_FIELDS | DERIVED_FIELDS:
        number = _decimal_value(value, ratio=field in RATIO_FIELDS)
        if number is None:
            return f"text:{_normalize_text(value)}"
        if field in MONEY_FIELDS:
            number = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif field in AREA_FIELDS | DERIVED_FIELDS:
            number = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif field in RATIO_FIELDS:
            number = number.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        elif field in COUNT_FIELDS:
            number = number.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"number:{format(number.normalize(), 'f')}"
    if field in DATETIME_FIELDS:
        digits = re.findall(r"\d+", unicodedata.normalize("NFKC", str(value)))
        return "datetime:" + "-".join(digits[:6]) if digits else f"text:{_normalize_text(value)}"
    if isinstance(value, Mapping):
        normalized = {str(key): normalize_field_value(str(key), item) for key, item in sorted(value.items())}
        return "object:" + json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        normalized = sorted(normalize_field_value(field_path, item) for item in value)
        return "list:" + json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    return f"text:{_normalize_text(value)}"


def flatten_payload(payload: Mapping[str, Any], prefix: str = "") -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for raw_key, value in payload.items():
        key = str(raw_key)
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, Mapping):
            nested = flatten_payload(value, path)
            if nested:
                flattened.update(nested)
            else:
                flattened[path] = {}
        else:
            flattened[path] = value
    return flattened


def unflatten_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for field_path, value in payload.items():
        cursor = result
        parts = str(field_path).split(".")
        for part in parts[:-1]:
            child = cursor.get(part)
            if not isinstance(child, dict):
                child = {}
                cursor[part] = child
            cursor = child
        cursor[parts[-1]] = value
    return result


def _keyword_windows(field_path: str, source_text: str, *, radius: int = 160) -> list[str]:
    field = _field_name(field_path)
    keywords = FIELD_KEYWORDS.get(field, (field,))
    lowered = source_text.casefold()
    windows: list[str] = []
    for keyword in keywords:
        needle = str(keyword).casefold()
        start = 0
        while needle and len(windows) < 8:
            index = lowered.find(needle, start)
            if index < 0:
                break
            windows.append(source_text[max(index - radius, 0) : index + len(needle) + radius])
            start = index + len(needle)
    return windows


def find_source_evidence(field_path: str, value: Any, source_text: str) -> tuple[bool, list[str]]:
    field = _field_name(field_path)
    if value is None or value == "":
        return False, []
    if field in SYSTEM_FIELDS:
        return True, ["system-owned field"]
    if field in DERIVED_FIELDS:
        return False, []

    windows = _keyword_windows(field_path, source_text)
    search_windows = windows or [source_text]
    target = normalize_field_value(field_path, value)
    if target.startswith("number:"):
        for window in search_windows:
            for match in _NUMBER_RE.finditer(window):
                if normalize_field_value(field_path, match.group(0)) == target:
                    return True, [window.strip()[:320]]
        return False, []
    if field == "是否成交" and target == "bool:true":
        for window in search_windows:
            normalized_window = _normalize_text(window)
            if "statusdone" in normalized_window or "是否成交true" in normalized_window or "已成交" in normalized_window:
                return True, [window.strip()[:320]]
        return False, []

    normalized_value = _normalize_text(value)
    if len(normalized_value) < 2:
        return False, []
    for window in search_windows:
        if normalized_value in _normalize_text(window):
            return True, [window.strip()[:320]]
    return False, []


def build_field_consensus(
    candidates: Sequence[Mapping[str, Any]],
    *,
    source_text: str,
) -> dict[str, Any]:
    if len(candidates) != 3:
        raise ValueError("analysis module B consensus requires exactly three candidates")
    flattened = [flatten_payload(candidate) for candidate in candidates]
    field_paths = sorted({field for candidate in flattened for field in candidate})
    locked_fields: dict[str, Any] = {}
    conflicts: dict[str, Any] = {}
    system_fields: list[str] = []
    derived_fields: list[str] = []
    omitted_fields: list[str] = []

    for field_path in field_paths:
        field = _field_name(field_path)
        values = [candidate.get(field_path) for candidate in flattened]
        normalized_values = [normalize_field_value(field_path, value) for value in values]
        if field in SYSTEM_FIELDS:
            system_fields.append(field_path)
            continue
        if field in DERIVED_FIELDS:
            derived_fields.append(field_path)
            continue

        unique_values = sorted(set(normalized_values))
        if len(unique_values) == 1 and unique_values[0] == "null":
            omitted_fields.append(field_path)
            continue
        evidence_supported = False
        evidence: list[str] = []
        if len(unique_values) == 1:
            evidence_supported, evidence = find_source_evidence(field_path, values[0], source_text)
        if len(unique_values) == 1 and evidence_supported:
            locked_fields[field_path] = {
                "value": values[0],
                "normalized_value": normalized_values[0],
                "agreement": "3/3",
                "evidence": evidence,
            }
            continue

        reason = "evidence_missing" if len(unique_values) == 1 else "candidate_disagreement"
        conflicts[field_path] = {
            "candidate_values": values,
            "normalized_values": normalized_values,
            "reason": reason,
            "high_risk": field in HIGH_RISK_FIELDS,
        }

    return {
        "schema_version": ANALYSIS_MODULE_B_VERSION,
        "candidate_count": len(candidates),
        "locked_fields": locked_fields,
        "conflicts": conflicts,
        "system_fields": system_fields,
        "derived_fields": sorted(set(derived_fields)),
        "omitted_fields": omitted_fields,
        "stats": {
            "field_count": len(field_paths),
            "locked_count": len(locked_fields),
            "conflict_count": len(conflicts),
            "omitted_count": len(omitted_fields),
            "high_risk_conflict_count": sum(1 for conflict in conflicts.values() if conflict["high_risk"]),
        },
    }


def build_adjudication_prompt(
    *,
    item_id: str,
    consensus: Mapping[str, Any],
    candidates: Sequence[Mapping[str, Any]],
    source_text: str,
) -> str:
    if len(candidates) != 3:
        raise ValueError("analysis module B adjudication requires exactly three candidate results")
    conflicts = consensus.get("conflicts") if isinstance(consensus.get("conflicts"), Mapping) else {}
    return f"""
# Role
你是法拍房分析模块 B 的证据仲裁模型。你只处理三份独立分析结果中的冲突字段。

# Hard rules
1. 只能返回下方 conflicts 中已有的字段，禁止修改任何已锁定字段。
2. 每个非空结论都必须引用【原始证据】中的原文片段；不能只按多数票决定。
3. 可以选择任一候选值，也可以在原文明确支持时给出新值。
4. 原文不足、含糊或互相矛盾时，value 必须为 null，decision 必须为 needs_review。
5. “未说明”不等于 false；禁止根据常识补全租赁、占用、税费、腾退、面积或价格。
6. 仅输出 JSON，不要输出 Markdown 或解释性前后缀。

# Output schema
{{
  "decisions": {{
    "字段路径": {{
      "value": null,
      "decision": "candidate_1|candidate_2|candidate_3|new|needs_review",
      "evidence": "原文中的短片段；value 非空时必填",
      "confidence": 0.0
    }}
  }}
}}

# Item
{item_id}

# Three independent module A results
{json.dumps(list(candidates), ensure_ascii=False, sort_keys=True)}

# Conflicts
{json.dumps(conflicts, ensure_ascii=False, sort_keys=True)}

# 原始证据
{source_text[:100000]}
""".strip()


def _strip_json_wrapper(raw: str) -> str:
    text = str(raw or "").strip()
    if "```json" in text:
        return text.split("```json", 1)[1].split("```", 1)[0].strip()
    if "```" in text:
        return text.split("```", 1)[1].split("```", 1)[0].strip()
    return text


def validate_adjudication(
    raw: str | Mapping[str, Any],
    *,
    consensus: Mapping[str, Any],
    source_text: str,
) -> dict[str, Any]:
    if isinstance(raw, Mapping):
        payload = dict(raw)
    else:
        decoded = json.loads(_strip_json_wrapper(raw))
        if not isinstance(decoded, dict):
            raise ValueError("analysis module B adjudication must be a JSON object")
        payload = decoded
    raw_decisions = payload.get("decisions")
    if not isinstance(raw_decisions, Mapping):
        raise ValueError("analysis module B adjudication missing decisions object")
    conflicts = consensus.get("conflicts") if isinstance(consensus.get("conflicts"), Mapping) else {}

    decisions: dict[str, Any] = {}
    needs_review: list[str] = []
    ignored_fields = sorted(str(field) for field in raw_decisions if str(field) not in conflicts)
    normalized_source = _normalize_text(source_text)
    allowed_decisions = {"candidate_1", "candidate_2", "candidate_3", "new", "needs_review"}
    for field_path in conflicts:
        raw_decision = raw_decisions.get(field_path)
        if not isinstance(raw_decision, Mapping):
            decisions[field_path] = {
                "value": None,
                "decision": "needs_review",
                "evidence": "",
                "confidence": 0.0,
                "validation": "missing_decision",
            }
            needs_review.append(field_path)
            continue
        value = raw_decision.get("value")
        evidence = str(raw_decision.get("evidence") or "").strip()
        decision = str(raw_decision.get("decision") or "needs_review").strip()
        try:
            confidence = min(max(float(raw_decision.get("confidence") or 0.0), 0.0), 1.0)
        except (TypeError, ValueError):
            confidence = 0.0

        validation = "accepted"
        if decision not in allowed_decisions:
            value = None
            decision = "needs_review"
            confidence = 0.0
            validation = "invalid_decision"
        elif decision == "needs_review":
            value = None
        elif value is None:
            decision = "needs_review"
            confidence = 0.0
            validation = "missing_value"
        elif decision.startswith("candidate_"):
            candidate_values = conflicts[field_path].get("candidate_values")
            candidate_index = int(decision.rsplit("_", 1)[-1]) - 1
            if (
                not isinstance(candidate_values, Sequence)
                or isinstance(candidate_values, (str, bytes, bytearray))
                or candidate_index >= len(candidate_values)
                or normalize_field_value(field_path, value)
                != normalize_field_value(field_path, candidate_values[candidate_index])
            ):
                value = None
                decision = "needs_review"
                confidence = 0.0
                validation = "candidate_value_mismatch"
        if value is not None:
            normalized_evidence = _normalize_text(evidence)
            evidence_supported, _windows = find_source_evidence(field_path, value, evidence)
            if (
                len(normalized_evidence) < 4
                or normalized_evidence not in normalized_source
                or not evidence_supported
            ):
                value = None
                decision = "needs_review"
                confidence = 0.0
                validation = "unsupported_evidence"
        if value is None or decision == "needs_review":
            needs_review.append(field_path)
        decisions[field_path] = {
            "value": value,
            "decision": decision,
            "evidence": evidence,
            "confidence": confidence,
            "validation": validation,
        }

    return {
        "schema_version": ANALYSIS_MODULE_B_VERSION,
        "decisions": decisions,
        "needs_review": sorted(set(needs_review)),
        "ignored_fields": ignored_fields,
    }


def compose_final_payload(
    *,
    consensus: Mapping[str, Any],
    adjudication: Mapping[str, Any] | None,
) -> dict[str, Any]:
    field_values: dict[str, Any] = {}
    locked_fields = consensus.get("locked_fields") if isinstance(consensus.get("locked_fields"), Mapping) else {}
    for field_path, record in locked_fields.items():
        if isinstance(record, Mapping):
            field_values[str(field_path)] = record.get("value")

    decisions = (
        adjudication.get("decisions")
        if isinstance(adjudication, Mapping) and isinstance(adjudication.get("decisions"), Mapping)
        else {}
    )
    for field_path, record in decisions.items():
        if isinstance(record, Mapping):
            field_values[str(field_path)] = record.get("value")

    transaction_price = _decimal_value(field_values.get("成交价格"))
    area = _decimal_value(field_values.get("建筑面积"))
    if transaction_price is not None and area is not None and area > 0:
        field_values["单价"] = float((transaction_price / area).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    else:
        field_values["单价"] = 0
    field_values["is_processed"] = True
    return unflatten_payload(field_values)


def final_status(adjudication: Mapping[str, Any] | None) -> str:
    if adjudication is None:
        return "finalized"
    needs_review = adjudication.get("needs_review")
    return "needs_review" if isinstance(needs_review, list) and needs_review else "finalized"
