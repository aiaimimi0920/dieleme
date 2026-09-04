from __future__ import annotations
from tools.live_smoke_context import *  # noqa: F401,F403
from tools.live_smoke_resume import *  # noqa: F401,F403
from tools.live_smoke_list import *  # noqa: F401,F403
from tools.live_smoke_area import *  # noqa: F401,F403
from tools.live_smoke_auth import *  # noqa: F401,F403
from tools.live_smoke_cdp import *  # noqa: F401,F403
from tools.live_smoke_browser import *  # noqa: F401,F403
from tools.live_smoke_summary import *  # noqa: F401,F403
from tools.live_smoke_analysis_config import *  # noqa: F401,F403


def analyze_raw_item(
    item_id: str,
    *,
    output_dir: Path,
    do_risk: bool = False,
) -> dict[str, Any]:
    from src import llm_helper
    from src.avm.collection_template import sync_collection_record
    from src.collection.detail_service import DetailCollectionService

    seed_id = str(item_id)
    item_dir = output_dir / seed_id
    seed_path = item_dir / "seed.json"
    detail_html_path = item_dir / "detail.html"
    description_json_path = item_dir / "description-data.json"
    selected_json_path = item_dir / "selected.json"

    if not detail_html_path.exists():
        raise FileNotFoundError(f"raw detail html not found: {detail_html_path}")

    seed = load_json(seed_path) if seed_path.exists() else {"id": seed_id, "item_id": seed_id, "source_item_id": seed_id}
    html = detail_html_path.read_text(encoding="utf-8")
    if description_json_path.exists():
        description_data = load_json(description_json_path)
    else:
        description_data = build_description_audit(html, item_dir)
        write_json(description_json_path, description_data)

    raw_selected = load_json(selected_json_path) if selected_json_path.exists() else {}
    effective_seed, analysis_text = _build_detail_analysis_input(
        item_id=seed_id,
        item_dir=item_dir,
        seed=seed,
        html=html,
        selected=raw_selected,
        description_data=description_data,
    )
    fetch = as_dict(raw_selected.get("fetch"))
    final_url = pick_first(
        fetch.get("detail_final_url"),
        effective_seed.get("url"),
        effective_seed.get("source_url"),
        effective_seed.get("原始网站"),
        "",
    )
    detail_bytes = fetch.get("detail_html_bytes")
    if not isinstance(detail_bytes, int):
        detail_bytes = len(html.encode("utf-8"))
    fetch_method = str(fetch.get("method") or "raw_artifact")

    module_b_mode = _analysis_module_b_mode()
    module_b_result: dict[str, Any] | None = None
    module_b_shadow_selected = (
        module_b_mode != "shadow" or _analysis_module_b_shadow_selected(seed_id)
    )
    evidence_text = ""
    if module_b_mode != "off" and module_b_shadow_selected:
        evidence_text = _redact_detail_analysis_text(
            analysis_text
            + "\n\n【原始详情页正文】\n"
            + llm_helper.filter_content(html)[:80000]
        )

    if module_b_mode == "primary":
        module_b_result = _run_analysis_module_b(
            item_id=seed_id,
            item_dir=item_dir,
            analysis_text=analysis_text,
            evidence_text=evidence_text,
            html=html,
            effective_seed=effective_seed,
            do_risk=do_risk,
            mode=module_b_mode,
        )
        if module_b_result.get("status") != "finalized":
            raise AnalysisModuleBIncompleteError(
                "analysis module B primary result is not publishable: "
                f"status={module_b_result.get('status')}"
            )
        extracted = dict(module_b_result.get("final_payload") or {})
        risk = as_dict(extracted.pop("avm_risk_features", {}))
    else:
        extracted = json.loads(llm_helper.extract_auction_data(analysis_text, item_id=seed_id))
        extracted["id"] = int(seed_id) if seed_id.isdigit() else seed_id
        extracted["source_item_id"] = seed_id
        DetailCollectionService._preserve_seed_values(extracted, effective_seed)
        risk = {}
        if do_risk:
            risk = llm_helper.extract_avm_risk_features(html, item_id=seed_id) or {}
        if module_b_mode == "shadow" and module_b_shadow_selected:
            try:
                module_b_result = _run_analysis_module_b(
                    item_id=seed_id,
                    item_dir=item_dir,
                    analysis_text=analysis_text,
                    evidence_text=evidence_text,
                    html=html,
                    effective_seed=effective_seed,
                    do_risk=do_risk,
                    mode=module_b_mode,
                )
            except Exception as exc:
                module_b_result = {
                    "schema_version": "analysis_module_b_v1",
                    "item_id": seed_id,
                    "mode": module_b_mode,
                    "status": "failed",
                    "error": _safe_module_b_error(exc),
                    "updated_at": utc_now_iso(),
                }
                write_json(item_dir / "analysis-b" / "latest.json", module_b_result)
        elif module_b_mode == "shadow":
            module_b_result = {
                "schema_version": "analysis_module_b_v1",
                "item_id": seed_id,
                "mode": module_b_mode,
                "status": "sampled_out",
                "shadow_sample_rate": _analysis_module_b_shadow_sample_rate(),
                "updated_at": utc_now_iso(),
            }

    extracted["id"] = int(seed_id) if seed_id.isdigit() else seed_id
    extracted["source_item_id"] = seed_id
    DetailCollectionService._preserve_seed_values(extracted, effective_seed)
    write_json(item_dir / "extracted.json", extracted)
    if risk:
        write_json(item_dir / "risk.json", risk)

    combined = dict(effective_seed)
    combined.update(extracted)
    DetailCollectionService._preserve_seed_values(combined, effective_seed)
    combined["id"] = int(seed_id) if seed_id.isdigit() else seed_id
    combined["source_item_id"] = seed_id
    combined["source_url"] = final_url
    combined["原始网站"] = final_url
    combined.setdefault("source_platform", "taobao_sf")
    combined["detail_captured"] = True
    combined["is_processed"] = True
    if risk:
        combined["avm_risk_features"] = risk
        risk_aliases(combined)

    final_item = sync_collection_record(combined)
    write_json(item_dir / "final.json", final_item)
    selected = selected_summary(
        seed=seed,
        html=html,
        final_url=final_url,
        detail_bytes=detail_bytes,
        fetch_method=fetch_method,
        extracted=extracted,
        final_item=final_item,
        description_data=description_data,
    )
    selected["detail_capture_mode"] = "ai_finalized_from_raw"
    selected["raw_selected_json_path"] = str(selected_json_path) if selected_json_path.exists() else None
    if module_b_result is not None:
        selected["analysis_module_b"] = {
            key: value
            for key, value in module_b_result.items()
            if key != "final_payload"
        }
    write_json(selected_json_path, selected)
    return selected

__all__ = ('analyze_raw_item',)
