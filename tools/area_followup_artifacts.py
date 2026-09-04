"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.area_followup_context import *


def _artifact_root_for_job(job: dict[str, Any], artifact_root: str | Path | None) -> Path | None:
    if artifact_root is not None:
        return Path(artifact_root)
    for key in ("detail_html_path", "final_json_path", "selected_json_path"):
        value = job.get(key)
        if value:
            path = Path(value)
            if path.parent.name == str(job.get("item_id")):
                return path.parent.parent
            return path.parent
    return None


def _job_item_dir(job: dict[str, Any], artifact_root: str | Path | None) -> Path:
    item_id = str(job.get("item_id") or "")
    root = _artifact_root_for_job(job, artifact_root)
    if root is not None and item_id:
        return root / item_id
    for key in ("detail_html_path", "final_json_path", "selected_json_path"):
        value = job.get(key)
        if value:
            return Path(value).parent
    return Path(".") / item_id


def _first_existing_path(*values: Any) -> Path | None:
    for value in values:
        if not value:
            continue
        path = Path(str(value))
        if path.exists():
            return path
    return None


def _relative_artifact_path(path: str | Path | None, root: Path) -> str:
    if not path:
        return ""
    candidate = Path(path)
    try:
        return os.path.relpath(candidate, root).replace("\\", "/")
    except ValueError:
        return str(candidate)


def _load_final_payload(job: dict[str, Any], item_dir: Path) -> dict[str, Any]:
    path = _first_existing_path(job.get("final_json_path"), item_dir / "final.json")
    if path is None:
        return {}
    payload = load_json(path)
    return payload if isinstance(payload, dict) else {}


def _transaction_price(job: dict[str, Any], final_payload: dict[str, Any]) -> float | None:
    auction = as_dict(final_payload.get("auction"))
    for value in (
        job.get("transaction_price"),
        final_payload.get("成交价格"),
        final_payload.get("transaction_price"),
        auction.get("transaction_price"),
    ):
        amount = parse_money_to_yuan(value)
        if amount is not None:
            return amount
    return None


def _extract_candidates_from_detail_html(job: dict[str, Any], item_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = _first_existing_path(job.get("detail_html_path"), item_dir / "detail.html")
    if path is None:
        return [], {}
    html = path.read_text(encoding="utf-8", errors="replace")
    source_url = job.get("source_url") or job.get("detail_final_url")
    artifacts = extract_detail_artifacts(item_dir, html, job.get("item_id"), job.get("auction_date"), source_url=str(source_url or ""))
    candidates = extract_area_candidates_from_text(html, source_type="detail_html", source_path=str(path))
    for rel_key in ("notice_text_path", "desc_text_path", "detail_text_path"):
        rel_path = artifacts.get(rel_key)
        if rel_path:
            candidate_path = item_dir / str(rel_path)
            if candidate_path.exists():
                source_type = rel_key.replace("_path", "")
                text = candidate_path.read_text(encoding="utf-8", errors="replace")
                candidates.extend(extract_area_candidates_from_text(text, source_type=source_type, source_path=str(candidate_path)))
    return candidates, artifacts


def _extract_candidates_from_job_paths(job: dict[str, Any]) -> list[dict[str, Any]]:
    paths = [
        job.get("description_data_path"),
        job.get("selected_json_path"),
    ]
    return extract_area_candidates_from_paths(path for path in paths if path)


def select_best_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid = [candidate for candidate in candidates if has_positive_area(candidate.get("area_sqm"))]
    if not valid:
        return None
    return sorted(
        valid,
        key=lambda item: (
            float(item.get("confidence") or 0),
            1 if item.get("source_type") in {"notice_text", "detail_html", "local_text"} else 0,
        ),
        reverse=True,
    )[0]


def build_area_patch(
    *,
    area_sqm: float,
    transaction_price: float | None,
    selected_candidate: dict[str, Any],
    final_payload: dict[str, Any],
    artifacts: dict[str, Any],
    item_dir: Path,
) -> dict[str, Any]:
    unit_price = round(transaction_price / area_sqm, 2) if transaction_price and area_sqm > 0 else 0
    property_section = dict(as_dict(final_payload.get("property")))
    property_section.update(
        {
            "area_sqm": area_sqm,
            "gross_area_sqm": area_sqm,
            "unit_price": unit_price,
            "area_followup_source": selected_candidate.get("source_type"),
            "area_followup_evidence": selected_candidate.get("evidence"),
        }
    )
    archive_section = dict(as_dict(final_payload.get("archive")))
    legal_section = dict(as_dict(final_payload.get("legal_context")))
    if artifacts:
        archive_section.update(
            {
                "detail_text_path": artifacts.get("detail_text_path", archive_section.get("detail_text_path", "")),
                "notice_text_path": artifacts.get("notice_text_path", archive_section.get("notice_text_path", "")),
                "desc_text_path": artifacts.get("desc_text_path", archive_section.get("desc_text_path", "")),
                "attachment_manifest_path": artifacts.get("attachment_manifest_path", archive_section.get("attachment_manifest_path", "")),
                "image_manifest_path": artifacts.get("image_manifest_path", archive_section.get("image_manifest_path", "")),
            }
        )
        if artifacts.get("announcement_attachment_urls"):
            legal_section["announcement_attachment_urls"] = artifacts.get("announcement_attachment_urls")
        if artifacts.get("appraisal_report_urls"):
            legal_section["appraisal_report_urls"] = artifacts.get("appraisal_report_urls")
    return {
        "建筑面积": area_sqm,
        "产权建筑面积": area_sqm,
        "单价": unit_price,
        "area_sqm": area_sqm,
        "gross_area_sqm": area_sqm,
        "unit_price": unit_price,
        "area_followup_source": selected_candidate.get("source_type"),
        "area_followup_evidence": selected_candidate.get("evidence"),
        "property": property_section,
        "archive": archive_section,
        "legal_context": legal_section,
        "attachment_manifest_path": _relative_artifact_path(item_dir / str(artifacts.get("attachment_manifest_path")), item_dir)
        if artifacts.get("attachment_manifest_path")
        else archive_section.get("attachment_manifest_path", ""),
    }


__all__ = (
    "_artifact_root_for_job",
    "_job_item_dir",
    "_first_existing_path",
    "_relative_artifact_path",
    "_load_final_payload",
    "_transaction_price",
    "_extract_candidates_from_detail_html",
    "_extract_candidates_from_job_paths",
    "select_best_candidate",
    "build_area_patch",
)
