from __future__ import annotations

import datetime
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, MutableMapping, Sequence

from ..contracts import NumberParser, Record


def _first_non_empty(item: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", []):
            return value
    return None


@dataclass(frozen=True)
class GenericProductAdapter:
    """Default domain policy for collecting arbitrary product-like records."""

    source_platform: str = "generic"

    def item_id(self, item: Mapping[str, Any]) -> str:
        value = _first_non_empty(item, "source_item_id", "id", "item_id", "sku")
        if value is None:
            raise ValueError("collection item is missing source_item_id/id/item_id/sku")
        return str(value)

    def build_seed_record(
        self,
        item: Mapping[str, Any],
        *,
        parse_number: NumberParser,
        safe_int: NumberParser,
    ) -> Record:
        del parse_number, safe_int
        record = {str(key): value for key, value in item.items() if value not in (None, "")}
        item_id = self.item_id(item)
        title = _first_non_empty(item, "source_title", "title", "name")
        source_url = _first_non_empty(item, "source_url", "url", "detail_url")
        record.update(
            {
                "id": item_id,
                "source_item_id": item_id,
                "source_platform": item.get("source_platform") or self.source_platform,
                "is_processed": False,
            }
        )
        if title is not None:
            record.setdefault("title", title)
            record.setdefault("source_title", title)
        if source_url is not None:
            record.setdefault("url", source_url)
            record.setdefault("source_url", source_url)
        return record

    def accepts_seed(self, item: Mapping[str, Any], record: Mapping[str, Any]) -> bool:
        del record
        return not bool(item.get("skip_collection", False))

    def sync_record(self, record: MutableMapping[str, Any]) -> None:
        del record

    def partition_key(self, record: Mapping[str, Any]) -> str:
        raw = _first_non_empty(record, "collected_at", "published_at", "updated_at")
        if raw:
            return str(raw).split(" ", 1)[0][:10] or "unknown"
        return datetime.date.today().isoformat()

    def prepare_detail_record(
        self,
        record: MutableMapping[str, Any],
        *,
        existing: Mapping[str, Any],
        item_id: str,
    ) -> None:
        for key, value in existing.items():
            if value not in (None, "", []) and record.get(key) in (None, "", []):
                record[key] = value
        record["id"] = item_id
        record["source_item_id"] = item_id
        record.setdefault("source_platform", existing.get("source_platform") or self.source_platform)
        source_url = self.source_url(record) or self.source_url(existing)
        if source_url:
            record.setdefault("url", source_url)
            record.setdefault("source_url", source_url)

    def accepts_detail(self, record: Mapping[str, Any]) -> bool:
        return str(record.get("status") or "").strip().lower() not in {
            "cancelled",
            "canceled",
            "deleted",
            "removed",
        }

    def retry_reason(self, record: Mapping[str, Any]) -> str | None:
        del record
        return None

    def finalize_detail_record(self, record: MutableMapping[str, Any]) -> None:
        record["detail_captured"] = True
        record["is_processed"] = True

    def archive_date(self, record: Mapping[str, Any]) -> Any:
        return _first_non_empty(record, "collected_at", "published_at", "updated_at") or datetime.datetime.now()

    def source_url(self, record: Mapping[str, Any]) -> str | None:
        value = _first_non_empty(record, "source_url", "url", "detail_url")
        return str(value) if value is not None else None

    def quality_summary(self, record: Mapping[str, Any]) -> str:
        populated = sum(value not in (None, "", []) for value in record.values())
        return f"fields={populated}"

    def location_prompt(self, *, address: str, title: str) -> str | None:
        del address, title
        return None


@dataclass(frozen=True)
class GenericProductAnalysisProfile:
    """Evidence rules that make no assumptions about a product category."""

    money_fields: frozenset[str] = field(default_factory=frozenset)
    area_fields: frozenset[str] = field(default_factory=frozenset)
    ratio_fields: frozenset[str] = field(default_factory=frozenset)
    count_fields: frozenset[str] = field(default_factory=frozenset)
    boolean_fields: frozenset[str] = field(default_factory=frozenset)
    datetime_fields: frozenset[str] = field(default_factory=frozenset)
    derived_fields: frozenset[str] = field(default_factory=frozenset)
    system_fields: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "id",
                "source_item_id",
                "source_platform",
                "source_url",
                "url",
                "source_title",
                "title",
                "is_processed",
                "detail_captured",
            }
        )
    )
    high_risk_fields: frozenset[str] = field(default_factory=frozenset)
    field_keywords: Mapping[str, Sequence[str]] = field(default_factory=dict)

    def adjudication_prompt(
        self,
        *,
        item_id: str,
        conflicts: Mapping[str, Any],
        candidates: Sequence[Mapping[str, Any]],
        source_text: str,
    ) -> str:
        return f"""
# Role
You are Crow's evidence adjudicator. Resolve only conflicts among three independent extraction results.

# Hard rules
1. Return only fields present in conflicts; never rewrite locked fields.
2. Every non-null value must cite a short exact fragment from the source evidence.
3. A value may come from a candidate or be new only when the source explicitly supports it.
4. If evidence is missing, ambiguous, or contradictory, use null and needs_review.
5. Return JSON only, without Markdown.

# Output schema
{{"decisions": {{"field.path": {{"value": null, "decision": "candidate_1|candidate_2|candidate_3|new|needs_review", "evidence": "", "confidence": 0.0}}}}}}

# Item
{item_id}

# Three independent results
{json.dumps(list(candidates), ensure_ascii=False, sort_keys=True)}

# Conflicts
{json.dumps(conflicts, ensure_ascii=False, sort_keys=True)}

# Source evidence
{source_text[:100000]}
""".strip()

    def derive_final_fields(self, field_values: MutableMapping[str, Any]) -> None:
        del field_values
