from __future__ import annotations

import json
import re
import unicodedata
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable, Mapping, Sequence

from src.collection.adapters.generic_product import GenericProductAnalysisProfile
from src.collection.adapters.taobao_judicial import TaobaoJudicialAnalysisProfile
from src.collection.contracts import AnalysisProfile


ANALYSIS_MODULE_B_VERSION = "analysis_module_b_v1"
DEFAULT_ANALYSIS_PROFILE: AnalysisProfile = TaobaoJudicialAnalysisProfile()
GENERIC_ANALYSIS_PROFILE: AnalysisProfile = GenericProductAnalysisProfile()

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


def normalize_field_value(
    field_path: str,
    value: Any,
    *,
    profile: AnalysisProfile = DEFAULT_ANALYSIS_PROFILE,
) -> str:
    field = _field_name(field_path)
    if value is None or value == "":
        return "null"
    if field in profile.boolean_fields:
        if isinstance(value, bool):
            return f"bool:{str(value).lower()}"
        normalized = _normalize_text(value)
        if normalized in {"true", "1", "是", "有", "已成交", "done"}:
            return "bool:true"
        if normalized in {"false", "0", "否", "无", "未成交", "failed"}:
            return "bool:false"
        return f"text:{normalized}"
    numeric_fields = (
        profile.money_fields
        | profile.area_fields
        | profile.ratio_fields
        | profile.count_fields
        | profile.derived_fields
    )
    if field in numeric_fields:
        number = _decimal_value(value, ratio=field in profile.ratio_fields)
        if number is None:
            return f"text:{_normalize_text(value)}"
        if field in profile.money_fields:
            number = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif field in profile.area_fields | profile.derived_fields:
            number = number.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        elif field in profile.ratio_fields:
            number = number.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        elif field in profile.count_fields:
            number = number.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        return f"number:{format(number.normalize(), 'f')}"
    if field in profile.datetime_fields:
        digits = re.findall(r"\d+", unicodedata.normalize("NFKC", str(value)))
        return "datetime:" + "-".join(digits[:6]) if digits else f"text:{_normalize_text(value)}"
    if isinstance(value, Mapping):
        normalized = {
            str(key): normalize_field_value(str(key), item, profile=profile)
            for key, item in sorted(value.items())
        }
        return "object:" + json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        normalized = sorted(normalize_field_value(field_path, item, profile=profile) for item in value)
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


def _keyword_windows(
    field_path: str,
    source_text: str,
    *,
    profile: AnalysisProfile,
    radius: int = 160,
) -> list[str]:
    field = _field_name(field_path)
    keywords = profile.field_keywords.get(field, (field,))
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


def find_source_evidence(
    field_path: str,
    value: Any,
    source_text: str,
    *,
    profile: AnalysisProfile = DEFAULT_ANALYSIS_PROFILE,
) -> tuple[bool, list[str]]:
    field = _field_name(field_path)
    if value is None or value == "":
        return False, []
    if field in profile.system_fields:
        return True, ["system-owned field"]
    if field in profile.derived_fields:
        return False, []

    windows = _keyword_windows(field_path, source_text, profile=profile)
    search_windows = windows or [source_text]
    target = normalize_field_value(field_path, value, profile=profile)
    if target.startswith("number:"):
        for window in search_windows:
            for match in _NUMBER_RE.finditer(window):
                if normalize_field_value(field_path, match.group(0), profile=profile) == target:
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
    profile: AnalysisProfile = DEFAULT_ANALYSIS_PROFILE,
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
        normalized_values = [
            normalize_field_value(field_path, value, profile=profile)
            for value in values
        ]
        if field in profile.system_fields:
            system_fields.append(field_path)
            continue
        if field in profile.derived_fields:
            derived_fields.append(field_path)
            continue

        unique_values = sorted(set(normalized_values))
        if len(unique_values) == 1 and unique_values[0] == "null":
            omitted_fields.append(field_path)
            continue
        evidence_supported = False
        evidence: list[str] = []
        if len(unique_values) == 1:
            evidence_supported, evidence = find_source_evidence(
                field_path,
                values[0],
                source_text,
                profile=profile,
            )
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
            "high_risk": field in profile.high_risk_fields,
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
    profile: AnalysisProfile = DEFAULT_ANALYSIS_PROFILE,
) -> str:
    if len(candidates) != 3:
        raise ValueError("analysis module B adjudication requires exactly three candidate results")
    conflicts = consensus.get("conflicts") if isinstance(consensus.get("conflicts"), Mapping) else {}
    return profile.adjudication_prompt(
        item_id=item_id,
        conflicts=conflicts,
        candidates=candidates,
        source_text=source_text,
    )


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
    profile: AnalysisProfile = DEFAULT_ANALYSIS_PROFILE,
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
                or normalize_field_value(field_path, value, profile=profile)
                != normalize_field_value(
                    field_path,
                    candidate_values[candidate_index],
                    profile=profile,
                )
            ):
                value = None
                decision = "needs_review"
                confidence = 0.0
                validation = "candidate_value_mismatch"
        if value is not None:
            normalized_evidence = _normalize_text(evidence)
            evidence_supported, _windows = find_source_evidence(
                field_path,
                value,
                evidence,
                profile=profile,
            )
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
    profile: AnalysisProfile = DEFAULT_ANALYSIS_PROFILE,
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

    profile.derive_final_fields(field_values)
    field_values["is_processed"] = True
    return unflatten_payload(field_values)


def final_status(adjudication: Mapping[str, Any] | None) -> str:
    if adjudication is None:
        return "finalized"
    needs_review = adjudication.get("needs_review")
    return "needs_review" if isinstance(needs_review, list) and needs_review else "finalized"
