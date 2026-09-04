from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping


CANONICAL_RECORD_SCHEMA_VERSION = 2

_ENVELOPE_KEYS = {
    "canonical_payload",
    "record_schema_version",
    "schema_version",
    "entity_type",
    "evidence",
    "provenance",
    "extensions",
}


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_value(item) for item in value]
    return str(value)


def _mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {str(key): _json_value(item) for key, item in value.items()}


def _non_empty_updates(target: dict[str, Any], source: Mapping[str, Any]) -> None:
    for key, value in source.items():
        if value not in (None, "", []):
            target[str(key)] = _json_value(value)


def build_canonical_payload(
    item: Mapping[str, Any],
    normalized_record: Mapping[str, Any],
    *,
    previous: Mapping[str, Any] | None = None,
    captured_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the source-neutral, lossless envelope stored beside legacy columns."""

    previous_payload = _mapping(previous)
    source = _mapping(previous_payload.get("source"))
    attributes = _mapping(previous_payload.get("attributes"))
    evidence = _mapping(previous_payload.get("evidence"))
    provenance = _mapping(previous_payload.get("provenance"))
    extensions = _mapping(previous_payload.get("extensions"))

    embedded = _mapping(item.get("canonical_payload"))
    _non_empty_updates(source, _mapping(embedded.get("source")))
    _non_empty_updates(attributes, _mapping(embedded.get("attributes")))
    _non_empty_updates(evidence, _mapping(embedded.get("evidence")))
    _non_empty_updates(provenance, _mapping(embedded.get("provenance")))
    _non_empty_updates(extensions, _mapping(embedded.get("extensions")))

    normalized_source = _mapping(normalized_record.get("source"))
    _non_empty_updates(
        source,
        {
            "platform": normalized_source.get("source_platform"),
            "id": normalized_source.get("source_item_id") or normalized_source.get("item_id"),
            "url": normalized_source.get("source_url"),
            "title": normalized_source.get("source_title"),
        },
    )

    for key, value in item.items():
        key_text = str(key)
        if key_text in _ENVELOPE_KEYS:
            continue
        attributes[key_text] = _json_value(value)

    _non_empty_updates(extensions, _mapping(item.get("extensions")))
    archive = _mapping(normalized_record.get("archive"))
    audit = _mapping(normalized_record.get("audit"))
    _non_empty_updates(evidence, archive)
    _non_empty_updates(
        evidence,
        {
            key: audit.get(key)
            for key in ("evidence_span", "evidence_source", "extraction_confidence")
        },
    )
    _non_empty_updates(
        provenance,
        {
            "captured_at": provenance.get("captured_at") or captured_at or datetime.utcnow(),
            "source_stage": item.get("source_stage") or item.get("detail_status") or item.get("seed_status"),
            "extractor_version": audit.get("extraction_version"),
        },
    )

    return {
        "schema_version": CANONICAL_RECORD_SCHEMA_VERSION,
        "entity_type": str(embedded.get("entity_type") or previous_payload.get("entity_type") or "product"),
        "source": source,
        "attributes": attributes,
        "evidence": evidence,
        "provenance": provenance,
        "extensions": extensions,
    }


def merge_canonical_payload_into_flat(
    legacy_payload: Mapping[str, Any],
    canonical_payload: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Expose generic attributes while keeping normalized legacy values authoritative."""

    canonical = _mapping(canonical_payload)
    merged = _mapping(canonical.get("attributes"))
    merged.update(_mapping(legacy_payload))
    if canonical:
        merged["record_schema_version"] = int(canonical.get("schema_version") or 1)
        merged["canonical_payload"] = canonical
        extensions = _mapping(canonical.get("extensions"))
        if extensions:
            merged["extensions"] = extensions
    return merged


__all__ = [
    "CANONICAL_RECORD_SCHEMA_VERSION",
    "build_canonical_payload",
    "merge_canonical_payload_into_flat",
]
