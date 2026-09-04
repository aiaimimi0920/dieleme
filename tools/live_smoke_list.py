from __future__ import annotations
from tools.live_smoke_context import *  # noqa: F401,F403
from tools.live_smoke_resume import *  # noqa: F401,F403


def expand_list_urls(config: LiveSmokeConfig) -> list[dict[str, Any]]:
    parsed = urlparse(config.target_url)
    query = parse_qs(parsed.query)
    default_location = (query.get("location_code") or [""])[0]
    default_st_param = (query.get("st_param") or ["2"])[0]
    path_category: str | None = None
    for part in parsed.path.split("/"):
        if part.startswith("50025969") or part.startswith("200782003"):
            path_category = part.split("__", 1)[0].split(".", 1)[0]
            break
    location_codes = config.list_location_codes or ((default_location,) if default_location else ("",))
    categories = config.list_categories or ((path_category,) if path_category else ("",))
    st_params = config.list_st_params or (default_st_param,)
    max_pages = max(1, int(config.list_max_pages or 1))
    specs: list[dict[str, Any]] = []
    for location_code in location_codes:
        for category in categories:
            for st_param in st_params:
                for page in range(1, max_pages + 1):
                    specs.append(
                        {
                            "url": replace_list_url_params(
                                config.target_url,
                                location_code=location_code,
                                category=category,
                                st_param=st_param,
                                page=page,
                            ),
                            "location_code": location_code,
                            "category": category,
                            "st_param": st_param,
                            "page": page,
                        }
                    )
    return specs

def deduplicate_list_items(items: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    deduped: list[dict[str, Any]] = []
    by_id: dict[str, dict[str, Any]] = {}
    duplicate_count = 0
    for item in items:
        item_id = resume_item_id(item)
        if not item_id:
            deduped.append(dict(item))
            continue
        source_page_url = str(item.get("source_page_url") or item.get("page_url") or item.get("url") or "")
        existing = by_id.get(item_id)
        if existing is None:
            cloned = dict(item)
            if source_page_url:
                cloned["list_union_sources"] = [source_page_url]
            by_id[item_id] = cloned
            deduped.append(cloned)
            continue
        duplicate_count += 1
        if source_page_url:
            sources = existing.setdefault("list_union_sources", [])
            if isinstance(sources, list) and source_page_url not in sources:
                sources.append(source_page_url)
    return deduped, duplicate_count

def collect_list_union(
    browserless_seed_probe: Any,
    http: requests.Session,
    config: LiveSmokeConfig,
) -> dict[str, Any]:
    specs = expand_list_urls(config)
    list_fetches: list[dict[str, Any]] = []
    raw_items: list[dict[str, Any]] = []
    stopped_keys: set[tuple[str, str, str]] = set()
    first_fetch: dict[str, Any] | None = None
    successful_payload_count = 0

    for spec in specs:
        key = (
            str(spec.get("location_code") or ""),
            str(spec.get("category") or ""),
            str(spec.get("st_param") or ""),
        )
        record: dict[str, Any] = {
            "url": spec["url"],
            "location_code": spec.get("location_code"),
            "category": spec.get("category"),
            "st_param": spec.get("st_param"),
            "page": spec.get("page"),
        }
        if key in stopped_keys:
            record["skipped"] = True
            record["skip_reason"] = "previous_empty_page"
            list_fetches.append(record)
            continue

        try:
            list_html, list_final_url, list_status, list_fetch_method = fetch_list_page(
                http,
                cdp_endpoint=config.cdp_endpoint,
                target_url=str(spec["url"]),
                user_agent=getattr(browserless_seed_probe, "DEFAULT_USER_AGENT", DEFAULT_USER_AGENT),
            )
            list_summary = browserless_seed_probe.summarize_list_page(list_html, final_url=list_final_url)
            payload = browserless_seed_probe.extract_list_payload(list_html)
            record.update(
                {
                    "list_status": list_status,
                    "list_final_url": list_final_url,
                    "list_fetch_method": list_fetch_method,
                    "list_item_count": list_summary.get("item_count") if isinstance(list_summary, dict) else None,
                    "body_has_challenge": list_summary.get("body_has_challenge") if isinstance(list_summary, dict) else None,
                    "body_has_login": list_summary.get("body_has_login") if isinstance(list_summary, dict) else None,
                    "body_has_punish": list_summary.get("body_has_punish") if isinstance(list_summary, dict) else None,
                    "payload_present": payload is not None,
                }
            )
            if first_fetch is None:
                first_fetch = dict(record)
            if payload is None:
                record["error"] = f"list payload missing: {list_summary}"
                list_fetches.append(record)
                if isinstance(list_summary, dict) and list_summary.get("body_has_challenge"):
                    stopped_keys.add(key)
                continue

            successful_payload_count += 1
            batch = browserless_seed_probe.build_userscript_like_batch_payload(payload, source_page_url=list_final_url)
            batch_items = [item for item in (batch.get("items") or []) if isinstance(item, dict)]
            for item in batch_items:
                enriched_item = dict(item)
                enriched_item.setdefault("source_page_url", list_final_url)
                enriched_item["list_location_code"] = spec.get("location_code")
                enriched_item["list_category"] = spec.get("category")
                enriched_item["list_st_param"] = spec.get("st_param")
                enriched_item["list_page"] = spec.get("page")
                raw_items.append(enriched_item)

            record["eligible_item_count"] = len(batch_items)
            list_fetches.append(record)
            if config.list_stop_on_empty and int(spec.get("page") or 1) > 1 and not batch_items:
                stopped_keys.add(key)
        except Exception as exc:
            record["error"] = repr(exc)
            record["traceback"] = traceback.format_exc()
            list_fetches.append(record)
            if config.list_stop_on_empty and int(spec.get("page") or 1) > 1:
                stopped_keys.add(key)

    if successful_payload_count == 0:
        raise RuntimeError(f"list payload missing for all list sources: {list_fetches[:5]}")

    all_items, duplicate_item_count = deduplicate_list_items(raw_items)
    source_count = len(specs)
    fetched_source_count = sum(1 for record in list_fetches if not record.get("skipped"))
    return {
        "items": all_items,
        "first_fetch": first_fetch or {},
        "list_union": {
            "source_count": source_count,
            "fetched_source_count": fetched_source_count,
            "successful_payload_count": successful_payload_count,
            "raw_item_count": len(raw_items),
            "unique_item_count": len(all_items),
            "duplicate_item_count": duplicate_item_count,
            "list_stop_on_empty": bool(config.list_stop_on_empty),
            "sources": list_fetches,
        },
    }

__all__ = ('expand_list_urls', 'deduplicate_list_items', 'collect_list_union')
