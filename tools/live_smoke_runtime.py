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
from tools.live_smoke_analysis import *  # noqa: F401,F403


def process_item(
    http: requests.Session,
    seed: dict[str, Any],
    browser_pages: dict[str, tuple[str, str]],
    *,
    config: LiveSmokeConfig,
) -> dict[str, Any]:
    from src.avm.collection_template import sync_collection_record
    from src.collection.detail_service import DetailCollectionService

    item_id = str(seed.get("item_id") or seed.get("id") or seed.get("source_item_id"))
    source_item_id = str(seed.get("source_item_id") or seed.get("id") or item_id)
    item_dir = config.output_dir / item_id
    item_dir.mkdir(parents=True, exist_ok=True)
    write_json(item_dir / "seed.json", seed)

    html, final_url, detail_bytes, fetch_method = fetch_detail_html(
        http,
        seed,
        browser_pages,
        cdp_endpoint=config.cdp_endpoint,
        referer_url=str(seed.get("source_page_url") or config.target_url),
        user_agent=resolve_runtime_user_agent(config.cdp_endpoint),
    )
    (item_dir / "detail.html").write_text(html, encoding="utf-8")
    description_data = build_description_audit(html, item_dir)
    write_json(item_dir / "description-data.json", description_data)

    if config.raw_only:
        selected = raw_detail_summary(
            seed=seed,
            html=html,
            final_url=final_url,
            detail_bytes=detail_bytes,
            fetch_method=fetch_method,
            description_data=description_data,
            item_dir=item_dir,
        )
        write_json(item_dir / "selected.json", selected)
        return selected

    from src import llm_helper

    extracted = json.loads(llm_helper.extract_auction_data(html, item_id=item_id))
    extracted["id"] = int(item_id) if item_id.isdigit() else item_id
    extracted["source_item_id"] = source_item_id
    DetailCollectionService._preserve_seed_values(extracted, seed)
    write_json(item_dir / "extracted.json", extracted)

    risk = {}
    if config.do_risk:
        risk = llm_helper.extract_avm_risk_features(html, item_id=item_id) or {}
        write_json(item_dir / "risk.json", risk)

    combined = dict(seed)
    combined.update(extracted)
    DetailCollectionService._preserve_seed_values(combined, seed)
    combined["id"] = int(item_id) if item_id.isdigit() else item_id
    combined["source_item_id"] = source_item_id
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
    write_json(item_dir / "selected.json", selected)
    return selected

def run_live_smoke(config: LiveSmokeConfig) -> int:
    if not config.raw_only and (not os.environ.get("OPENAI_BASE_URL") or not os.environ.get("OPENAI_API_KEY")):
        raise RuntimeError("OPENAI_BASE_URL/OPENAI_API_KEY must be set in this subprocess")

    browserless_seed_probe = _browserless_seed_probe()
    config.output_dir.mkdir(parents=True, exist_ok=True)
    llm_preflight_result = None
    if config.llm_preflight_enabled and not config.raw_only:
        llm_preflight_result = preflight_llm_backend(timeout=config.llm_preflight_timeout_seconds)
        print(f"[SMOKE] LLM preflight ok: {json.dumps(llm_preflight_result, ensure_ascii=False)}")

    resume_state_path = config.resume_state_path or (config.output_dir / DEFAULT_RESUME_STATE_FILENAME)
    resume_state = load_resume_state(resume_state_path) if config.resume_enabled else new_resume_state()
    started_at = time.time()
    cookies = export_cookies(config.cdp_endpoint)
    http = build_http(cookies)
    list_collection = collect_list_union(browserless_seed_probe, http, config)
    all_items = list_collection["items"]
    list_union = list_collection["list_union"]
    first_fetch = list_collection["first_fetch"]
    list_status = first_fetch.get("list_status")
    list_final_url = first_fetch.get("list_final_url") or config.target_url
    list_fetch_method = first_fetch.get("list_fetch_method")
    list_item_count = first_fetch.get("list_item_count")
    artifact_completed_ids: list[str] = []
    if config.resume_enabled:
        artifact_completed_ids = hydrate_resume_state_from_artifacts(
            resume_state,
            all_items,
            output_dir=config.output_dir,
        )
        if artifact_completed_ids:
            save_resume_state(resume_state_path, resume_state)
        items, skipped_completed_ids = select_resume_candidates(
            all_items,
            resume_state,
            limit=config.max_attempts,
        )
    else:
        items = all_items[: config.max_attempts]
        skipped_completed_ids = []
    if not items:
        summary_path = config.output_dir / "summary.json"
        summary = {
            "summary_path": str(summary_path),
            "target_url": config.target_url,
            "list_status": list_status,
            "list_final_url": list_final_url,
            "list_fetch_method": list_fetch_method,
            "list_item_count": list_item_count,
            "list_union": list_union,
            "eligible_done_item_count": len(all_items),
            "target_success": config.target_success,
            "max_attempts": config.max_attempts,
            "attempted_items": 0,
            "processed_items": 0,
            "error_count": 0,
            "cookie_count": len(cookies),
            "duration_seconds": round(time.time() - started_at, 2),
            "resume_enabled": bool(config.resume_enabled),
            "resume_state_path": str(resume_state_path) if config.resume_enabled else None,
            "skipped_completed_items": len(skipped_completed_ids),
            "skipped_completed_item_ids": skipped_completed_ids[:50],
            "artifact_completed_items": len(artifact_completed_ids),
            "artifact_completed_item_ids": artifact_completed_ids[:50],
            "llm_preflight": llm_preflight_result,
            "no_candidate_reason": "all_candidates_already_completed" if skipped_completed_ids else "no_eligible_done_items",
            "results": [],
            "errors": [],
        }
        enriched = attach_area_artifacts(summary, output_dir=config.output_dir)
        queue = build_area_followup_queue(enriched, artifact_root=config.output_dir)
        write_json(config.output_dir / "area_followup_queue.json", queue)
        write_json(summary_path, enriched)
        print(json.dumps(enriched, ensure_ascii=False, indent=2))
        return 0 if skipped_completed_ids else 1

    browser_pages = load_open_browser_pages(config.cdp_endpoint)
    results = []
    errors = []
    for index, seed in enumerate(items, start=1):
        if len(results) >= config.target_success:
            break
        seed_id = str(seed.get("item_id") or seed.get("id") or seed.get("source_item_id"))
        try:
            print(f"[SMOKE] {index}/{len(items)} item={seed_id}")
            if config.resume_enabled:
                mark_resume_item(
                    resume_state,
                    seed_id,
                    status="in_progress",
                    metadata={
                        "source_url": seed.get("url"),
                        "source_page_url": seed.get("source_page_url"),
                        "title": seed.get("title"),
                        "target_url": config.target_url,
                        "list_location_code": seed.get("list_location_code"),
                        "list_category": seed.get("list_category"),
                        "list_st_param": seed.get("list_st_param"),
                        "list_page": seed.get("list_page"),
                    },
                )
                save_resume_state(resume_state_path, resume_state)
            selected = process_item(http, seed, browser_pages, config=config)
            results.append(selected)
            if config.resume_enabled:
                mark_resume_item(
                    resume_state,
                    seed_id,
                    status=RESUME_COMPLETED_STATUS,
                    metadata={
                        "source_url": pick_first(selected.get("final_core", {}).get("source_url"), seed.get("url")),
                        "source_page_url": seed.get("source_page_url"),
                        "title": pick_first(selected.get("final_core", {}).get("title"), seed.get("title")),
                        "selected_json_path": str(config.output_dir / seed_id / "selected.json"),
                        "final_json_path": str(config.output_dir / seed_id / "final.json"),
                        "has_completed_artifacts": has_completed_item_artifacts(config.output_dir, seed_id),
                        "list_location_code": seed.get("list_location_code"),
                        "list_category": seed.get("list_category"),
                        "list_st_param": seed.get("list_st_param"),
                        "list_page": seed.get("list_page"),
                    },
                )
                save_resume_state(resume_state_path, resume_state)
        except Exception as exc:
            errors.append({"item_id": seed_id, "error": repr(exc), "traceback": traceback.format_exc()})
            write_json(config.output_dir / f"{seed_id}.error.json", errors[-1])
            if config.resume_enabled:
                mark_resume_item(
                    resume_state,
                    seed_id,
                    status="failed",
                    metadata={
                        "source_url": seed.get("url"),
                        "source_page_url": seed.get("source_page_url"),
                        "title": seed.get("title"),
                        "target_url": config.target_url,
                        "list_location_code": seed.get("list_location_code"),
                        "list_category": seed.get("list_category"),
                        "list_st_param": seed.get("list_st_param"),
                        "list_page": seed.get("list_page"),
                        "error": repr(exc),
                    },
                )
                save_resume_state(resume_state_path, resume_state)
            print(f"[SMOKE][ERROR] item={seed_id}: {exc}")
        time.sleep(1)

    summary_path = config.output_dir / "summary.json"
    summary = {
        "summary_path": str(summary_path),
        "target_url": config.target_url,
        "list_status": list_status,
        "list_final_url": list_final_url,
        "list_fetch_method": list_fetch_method,
        "list_item_count": list_item_count,
        "list_union": list_union,
        "eligible_done_item_count": len(all_items),
        "target_success": config.target_success,
        "max_attempts": config.max_attempts,
        "attempted_items": len(results) + len(errors),
        "processed_items": len(results),
        "error_count": len(errors),
        "cookie_count": len(cookies),
        "duration_seconds": round(time.time() - started_at, 2),
        "resume_enabled": bool(config.resume_enabled),
        "resume_state_path": str(resume_state_path) if config.resume_enabled else None,
        "skipped_completed_items": len(skipped_completed_ids),
        "skipped_completed_item_ids": skipped_completed_ids[:50],
        "artifact_completed_items": len(artifact_completed_ids),
        "artifact_completed_item_ids": artifact_completed_ids[:50],
        "llm_preflight": llm_preflight_result,
        "results": results,
        "errors": errors,
    }
    enriched = attach_area_artifacts(summary, output_dir=config.output_dir)
    queue = build_area_followup_queue(enriched, artifact_root=config.output_dir)
    write_json(config.output_dir / "area_followup_queue.json", queue)
    write_json(summary_path, enriched)
    print(json.dumps(enriched, ensure_ascii=False, indent=2))
    return 0 if len(results) >= min(config.target_success, len(items)) else 1

def run_loop(
    config: LiveSmokeConfig,
    *,
    max_runs: int | None,
    interval_seconds: float,
) -> dict[str, Any]:
    run_count = 0
    exit_codes: list[int] = []
    errors: list[dict[str, Any]] = []
    started_at = time.time()
    while max_runs is None or run_count < max_runs:
        run_count += 1
        try:
            exit_codes.append(run_live_smoke(config))
        except Exception as exc:
            exit_codes.append(1)
            error = {
                "run": run_count,
                "error": repr(exc),
                "traceback": traceback.format_exc(),
                "timestamp": utc_now_iso(),
            }
            errors.append(error)
            if len(errors) > 50:
                errors = errors[-50:]
            print(json.dumps({"loop_error": error}, ensure_ascii=False, indent=2), flush=True)
        if max_runs is not None and run_count >= max_runs:
            break
        if interval_seconds > 0:
            time.sleep(interval_seconds)
    return {
        "run_count": run_count,
        "exit_codes": exit_codes,
        "ok": all(code == 0 for code in exit_codes),
        "duration_seconds": round(time.time() - started_at, 2),
        "resume_enabled": bool(config.resume_enabled),
        "resume_state_path": str(config.resume_state_path or (config.output_dir / DEFAULT_RESUME_STATE_FILENAME))
        if config.resume_enabled
        else None,
        "errors": errors,
    }

__all__ = ('process_item', 'run_live_smoke', 'run_loop')
