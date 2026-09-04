"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.area_followup_context import *


def infer_final_path_from_patch_path(patch_path: Path) -> Path:
    return patch_path.parent / "final.json"


def apply_patch_payload(final_payload: dict[str, Any], patch_result: dict[str, Any]) -> dict[str, Any]:
    patch = as_dict(patch_result.get("patch"))
    selected = as_dict(patch_result.get("selected_candidate"))
    merged = deep_merge(final_payload, patch)
    if selected.get("source_type"):
        merged["area_followup_source"] = selected.get("source_type")
    if selected.get("evidence"):
        merged["area_followup_evidence"] = selected.get("evidence")
    merged["area_followup_applied"] = True
    merged["area_followup_item_id"] = patch_result.get("item_id")
    sync_collection_record(merged)
    area = patch.get("建筑面积") or patch.get("area_sqm")
    gross_area = patch.get("产权建筑面积") or patch.get("gross_area_sqm") or area
    unit_price = patch.get("单价") or patch.get("unit_price")
    if area not in (None, ""):
        merged["建筑面积"] = area
        merged["area_sqm"] = area
        merged.setdefault("property", {})["area_sqm"] = area
    if gross_area not in (None, ""):
        merged["产权建筑面积"] = gross_area
        merged["gross_area_sqm"] = gross_area
        merged.setdefault("property", {})["gross_area_sqm"] = gross_area
    if unit_price not in (None, ""):
        merged["单价"] = unit_price
        merged["unit_price"] = unit_price
        merged.setdefault("property", {})["unit_price"] = unit_price
    return merged


def build_area_result_payload(patch_result: dict[str, Any]) -> dict[str, Any]:
    patch = as_dict(patch_result.get("patch"))
    selected = as_dict(patch_result.get("selected_candidate"))
    payload = {
        "id": str(patch_result.get("item_id") or ""),
        "建筑面积": patch.get("建筑面积") or patch.get("area_sqm"),
        "产权建筑面积": patch.get("产权建筑面积") or patch.get("gross_area_sqm") or patch.get("area_sqm"),
        "单价": patch.get("单价") or patch.get("unit_price"),
        "area_sqm": patch.get("area_sqm") or patch.get("建筑面积"),
        "gross_area_sqm": patch.get("gross_area_sqm") or patch.get("产权建筑面积") or patch.get("area_sqm"),
        "unit_price": patch.get("unit_price") or patch.get("单价"),
        "property": dict(as_dict(patch.get("property"))),
        "archive": dict(as_dict(patch.get("archive"))),
        "legal_context": dict(as_dict(patch.get("legal_context"))),
        "source_type": selected.get("source_type") or patch.get("area_followup_source") or "area_followup",
        "evidence_source": selected.get("evidence") or patch.get("area_followup_evidence") or "",
        "source": "area_followup_runner",
        "area_followup_patch_path": patch_result.get("patch_path") or "",
        "area_followup_source": selected.get("source_type") or patch.get("area_followup_source") or "",
        "area_followup_evidence": selected.get("evidence") or patch.get("area_followup_evidence") or "",
    }
    payload["property"].update(
        {
            "area_sqm": payload["建筑面积"],
            "gross_area_sqm": payload["产权建筑面积"],
            "unit_price": payload["单价"],
            "area_followup_source": payload["area_followup_source"],
            "area_followup_evidence": payload["area_followup_evidence"],
        }
    )
    return payload


def push_area_result(
    patch_result: dict[str, Any],
    *,
    api_url: str,
    session: Any | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    http = session or requests.Session()
    payload = build_area_result_payload(patch_result)
    response = http.post(api_url, json=payload, timeout=timeout)
    if hasattr(response, "raise_for_status"):
        response.raise_for_status()
    body: Any
    if hasattr(response, "json"):
        try:
            body = response.json()
        except Exception:
            body = None
    else:
        body = None
    return {"status": "ok", "response": body}


def apply_patch_file(patch_path: str | Path, *, final_path: str | Path | None = None) -> dict[str, Any]:
    patch_path = Path(patch_path)
    patch_result = load_json(patch_path)
    if not isinstance(patch_result, dict):
        raise RuntimeError(f"patch must be a JSON object: {patch_path}")
    if patch_result.get("status") != "resolved":
        return {"status": "skipped", "reason": "patch_not_resolved", "patch_path": str(patch_path)}
    final_path = Path(final_path) if final_path is not None else infer_final_path_from_patch_path(patch_path)
    final_payload = load_json(final_path)
    if not isinstance(final_payload, dict):
        raise RuntimeError(f"final must be a JSON object: {final_path}")
    backup_path = final_path.with_suffix(final_path.suffix + ".area-followup.bak")
    backup_path.write_text(json.dumps(final_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    updated = apply_patch_payload(final_payload, patch_result)
    write_json(final_path, updated)
    return {
        "status": "applied",
        "patch_path": str(patch_path),
        "final_path": str(final_path),
        "backup_path": str(backup_path),
        "item_id": patch_result.get("item_id"),
        "area_sqm": updated.get("建筑面积"),
        "unit_price": updated.get("单价"),
    }


__all__ = (
    "infer_final_path_from_patch_path",
    "apply_patch_payload",
    "build_area_result_payload",
    "push_area_result",
    "apply_patch_file",
)
