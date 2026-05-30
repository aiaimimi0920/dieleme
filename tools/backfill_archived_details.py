#!/usr/bin/env python3
"""对已归档的详情页 HTML/TXT 回放坐标与可选风控抽取。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
import sys

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import src.llm_helper as llm_helper
from src.detail_artifacts import extract_detail_artifacts
from src.storage.repository import create_repository_from_env
from tools.avm_data_loader import discover_raw_record_files, load_json_payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="回放 archived detail enrich")
    parser.add_argument("--data-root", type=Path, default=Path("datas"))
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--extract-risk", action="store_true", help="启用 LLM 风控抽取")
    parser.add_argument("--output-path", type=Path, default=Path("datas/avm/archived_detail_backfill.json"))
    return parser.parse_args()


def _iter_rows(data_root: Path) -> list[tuple[Path, list[dict[str, Any]]]]:
    outputs: list[tuple[Path, list[dict[str, Any]]]] = []
    for path in discover_raw_record_files(data_root):
        payload = load_json_payload(path)
        if isinstance(payload, list):
            outputs.append((path, [row for row in payload if isinstance(row, dict)]))
    return outputs


def _needs_risk_enrich(row: dict[str, Any]) -> bool:
    risk_payload = row.get("avm_risk_features")
    if not isinstance(risk_payload, dict):
        return True
    return not any(
        risk_payload.get(key) not in (None, "", "UNK")
        for key in ("is_occupied", "has_long_lease", "clear_delivery", "tax_burden", "is_fractional_share")
    )


def _merge_risk_features(row: dict[str, Any], extracted: dict[str, Any]) -> None:
    row["avm_risk_features"] = extracted
    for key in (
        "community_name",
        "build_year",
        "total_floors",
        "floor_level",
        "has_elevator",
        "orientation",
        "land_right_type",
        "is_occupied",
        "has_long_lease",
        "clear_delivery",
        "tax_burden",
        "is_haunted",
        "housing_type",
        "has_keys",
        "property_fee_owed",
        "special_school_tag",
        "evaluation_price",
        "layout",
        "is_restricted_purchase",
        "includes_parking",
        "is_fractional_share",
        "tax_is_company_owned",
        "has_lease_before_mortgage",
        "extraction_confidence",
        "evidence_span",
        "evidence_source",
        "extraction_version",
    ):
        value = extracted.get(key)
        if value not in (None, "", "UNK"):
            row[key] = value


def backfill_archived_details(
    data_root: Path,
    limit: int,
    dry_run: bool = False,
    extract_risk: bool = False,
) -> dict[str, Any]:
    scanned = 0
    updated = 0
    touched_files = 0
    samples: list[dict[str, Any]] = []
    repo = create_repository_from_env()
    candidate_files: list[tuple[Path, list[dict[str, Any]]]] = []
    if repo.enabled:
        try:
            candidates = repo.iter_archived_detail_candidates(
                limit=limit,
                require_missing_coordinates=True,
                require_missing_risk=extract_risk,
            )
        except Exception:
            candidates = []
        if candidates:
            grouped: dict[str, list[dict[str, Any]]] = {}
            for row in candidates:
                file_path = row.get("__file_path") or row.get("json_file") or row.get("source_json_path")
                if isinstance(file_path, str) and file_path.strip():
                    grouped.setdefault(file_path, []).append(row)
            candidate_files = [(Path(file_path), rows) for file_path, rows in sorted(grouped.items())]

    source_rows = candidate_files or _iter_rows(data_root)

    for file_path, rows in source_rows:
        changed = False
        file_rows = load_json_payload(file_path)
        if not isinstance(file_rows, list):
            continue
        indexed = {
            str(row.get("id") or row.get("item_id") or ""): row
            for row in file_rows
            if isinstance(row, dict)
        }
        changed_rows: list[dict[str, Any]] = []

        for row in rows:
            target_row = indexed.get(str(row.get("id") or row.get("item_id") or ""))
            if not isinstance(target_row, dict):
                continue
            archive_rel = target_row.get("detail_archive_path") or row.get("detail_archive_path")
            if not archive_rel:
                continue
            archive_path = data_root / str(archive_rel)
            if not archive_path.exists():
                continue
            scanned += 1
            if scanned > limit:
                break

            content = archive_path.read_text(encoding="utf-8", errors="ignore")
            item_id = str(target_row.get("id") or target_row.get("item_id") or row.get("id") or row.get("item_id") or "")

            row_changed = False
            artifact_fields = extract_detail_artifacts(
                data_root=data_root,
                html_content=content,
                item_id=item_id,
                auction_date=target_row.get("auction_date") or target_row.get("交易时间"),
                source_url=target_row.get("source_url") or target_row.get("原始网站") or target_row.get("url"),
            )
            for key, value in artifact_fields.items():
                if value not in (None, "", []) and target_row.get(key) in (None, "", []):
                    target_row[key] = value
                    row_changed = True
            if target_row.get("latitude") in (None, "") or target_row.get("longitude") in (None, ""):
                coord = llm_helper.extract_property_coordinates(content)
                if coord:
                    lat = round(float(coord["latitude"]), 6)
                    lon = round(float(coord["longitude"]), 6)
                    target_row["latitude"] = lat
                    target_row["longitude"] = lon
                    target_row["纬度"] = lat
                    target_row["经度"] = lon
                    target_row["coordinate_backfill_strategy"] = "archived_detail_html"
                    row_changed = True

            if extract_risk:
                if _needs_risk_enrich(target_row):
                    extracted = llm_helper.extract_avm_risk_features(content, item_id=item_id)
                    if extracted:
                        _merge_risk_features(target_row, extracted)
                        row_changed = True

            if row_changed:
                updated += 1
                changed = True
                changed_rows.append(target_row)
                if len(samples) < 20:
                    samples.append(
                        {
                            "file_path": str(file_path),
                            "item_id": item_id,
                            "detail_archive_path": str(archive_path),
                            "updated_latitude": target_row.get("latitude"),
                            "updated_longitude": target_row.get("longitude"),
                            "has_risk_features": isinstance(target_row.get("avm_risk_features"), dict),
                        }
                    )

        if scanned > limit:
            break
        if changed:
            touched_files += 1
            if not dry_run:
                file_path.write_text(json.dumps(file_rows, ensure_ascii=False, indent=4), encoding="utf-8")
                if repo.enabled and changed_rows:
                    repo.upsert_flat_items(
                        changed_rows,
                        event_type="archived_detail_backfill",
                        event_payload_factory=lambda record, _idx, file_path=file_path: {
                            "source_file": str(file_path),
                            "item_id": record["source"]["item_id"],
                        },
                    )

    return {
        "limit": limit,
        "dry_run": dry_run,
        "extract_risk": extract_risk,
        "scanned_archives": scanned,
        "updated_records": updated,
        "touched_files": touched_files,
        "samples": samples,
    }


def main() -> None:
    args = parse_args()
    report = backfill_archived_details(
        data_root=args.data_root,
        limit=args.limit,
        dry_run=args.dry_run,
        extract_risk=args.extract_risk,
    )
    args.output_path.parent.mkdir(parents=True, exist_ok=True)
    args.output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
