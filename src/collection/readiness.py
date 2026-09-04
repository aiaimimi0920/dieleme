from __future__ import annotations

from typing import Any, Mapping


def _present(value: Any) -> bool:
    return value not in (None, "", [], {})


def taobao_judicial_analysis_missing_fields(
    record: Mapping[str, Any],
    detail_status: str | None,
) -> list[str]:
    """Legacy AVM readiness contract, isolated from generic stage tracking."""

    auction = record.get("auction", {}) or {}
    location = record.get("location", {}) or {}
    property_section = record.get("property", {}) or {}
    status = str(auction.get("status") or "").strip().lower()
    if status in {"done", "成交", "true", "finished", "ended", "success"}:
        status = "done"

    missing: list[str] = []
    for name, value in (
        ("auction_date", auction.get("auction_date")),
        ("area_sqm", property_section.get("area_sqm")),
        ("city", location.get("city")),
        ("district", location.get("district")),
        ("business_area", location.get("business_area")),
    ):
        if not _present(value):
            missing.append(name)
    if not any(
        _present(auction.get(key))
        for key in ("transaction_price", "starting_price", "actual_paid_price", "evaluation_price")
    ):
        missing.append("price_anchor")
    if detail_status not in {"archived", "enriched"}:
        missing.append("detail_stage")
    if status != "done":
        missing.append("status")
    if not _present(location.get("latitude")) and not _present(location.get("community_name")):
        missing.append("location_precision")
    return missing


def generic_product_analysis_missing_fields(
    record: Mapping[str, Any],
    detail_status: str | None,
) -> list[str]:
    """Minimal readiness rule for a non-domain-specific product record."""

    missing: list[str] = []
    if not _present(record.get("source_item_id") or record.get("id")):
        missing.append("source_item_id")
    if not _present(record.get("source_url") or record.get("url")):
        missing.append("source_url")
    if detail_status not in {"archived", "enriched"}:
        missing.append("detail_stage")
    return missing
