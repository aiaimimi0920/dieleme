"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.taobao_sf_locations_context import *


def _page_goto_and_content(page: Any, url: str, *, wait_ms: int) -> tuple[str, str]:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
    except Exception:
        # Taobao challenge pages can leave the load event pending. Capture DOM and
        # let the caller classify it instead of hanging the taxonomy crawler.
        pass
    if wait_ms > 0:
        page.wait_for_timeout(wait_ms)
    return page.content(), page.url


def _page_goto_and_content_with_challenge_retries(
    page: Any,
    url: str,
    *,
    wait_ms: int,
    challenge_retries: int = 1,
    challenge_retry_delay_seconds: float = 30.0,
) -> tuple[str, str]:
    attempts = max(int(challenge_retries), 0) + 1
    for attempt_index in range(attempts):
        html, final_url = _page_goto_and_content(page, url, wait_ms=wait_ms)
        if not is_challenge_html(html, final_url) or attempt_index >= attempts - 1:
            return html, final_url
        if challenge_retry_delay_seconds > 0:
            time.sleep(challenge_retry_delay_seconds)
    return html, final_url


def crawl_taobao_sf_locations(
    *,
    cdp_endpoint: str,
    output_path: str | Path,
    all_locations_path: str | Path,
    category: str = DEFAULT_CATEGORY,
    delay_seconds: float = 8.0,
    wait_ms: int = 1500,
    province_filters: Sequence[str] = (),
    max_provinces: int | None = None,
    max_cities_per_province: int | None = None,
    resume: bool = True,
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    admin_index = AdminLocationIndex(all_locations_path)
    output = Path(output_path)
    observed = load_observed_payload(output) if resume else new_observed_payload()
    completed = {clean_text(value) for value in observed.get("completed_provinces", []) if clean_text(value)}
    filter_set = {canonical_province_name(value, admin_index) for value in province_filters if clean_text(value)}
    start_url = DEFAULT_START_URL.format(category=category)
    started_at = time.time()
    challenge_retry_delay_seconds = max(float(delay_seconds) * 4, 30.0)

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(cdp_endpoint, timeout=120_000)
        try:
            if not browser.contexts:
                raise RuntimeError("attached CDP browser has no contexts")
            context = browser.contexts[0]
            page = context.new_page()
            try:
                html, final_url = _page_goto_and_content_with_challenge_retries(
                    page,
                    start_url,
                    wait_ms=wait_ms,
                    challenge_retry_delay_seconds=challenge_retry_delay_seconds,
                )
                if is_challenge_html(html, final_url):
                    raise RuntimeError(f"Taobao challenge/login page encountered at taxonomy start URL: {final_url}")
                base_options = extract_location_filter_options(html, page_url=final_url)
                province_options = base_options.provinces
                if not province_options:
                    raise RuntimeError("No province options found in Taobao SF location filter")

                province_count = 0
                for province_option in province_options:
                    province_name = canonical_province_name(province_option.label, admin_index)
                    if filter_set and province_name not in filter_set:
                        continue
                    if resume and province_name in completed:
                        continue
                    if max_provinces is not None and province_count >= max_provinces:
                        break
                    province_count += 1
                    province_status = {
                        "status": "in_progress",
                        "started_at": utc_now_iso(),
                        "source_url": province_option.href,
                    }
                    observed.setdefault("province_status", {})[province_name] = province_status
                    save_observed_payload(output, observed)

                    html, final_url = _page_goto_and_content_with_challenge_retries(
                        page,
                        province_option.href,
                        wait_ms=wait_ms,
                        challenge_retry_delay_seconds=challenge_retry_delay_seconds,
                    )
                    if is_challenge_html(html, final_url):
                        province_status.update({"status": "challenge", "final_url": final_url, "updated_at": utc_now_iso()})
                        save_observed_payload(output, observed)
                        raise RuntimeError(f"Taobao challenge/login page encountered while opening province {province_name}: {final_url}")
                    province_options_page = extract_location_filter_options(html, page_url=final_url)
                    city_options = province_options_page.cities
                    if not city_options and province_options_page.districts:
                        city_options = [LocationOption(label="", href=final_url, level="city")]

                    city_count = 0
                    for city_option in city_options:
                        if max_cities_per_province is not None and city_count >= max_cities_per_province:
                            break
                        city_count += 1
                        city_name = canonical_city_name(province_name, city_option.label, admin_index)
                        city_url = city_option.href or final_url
                        if city_option.href:
                            if delay_seconds > 0:
                                time.sleep(delay_seconds)
                            city_html, city_final_url = _page_goto_and_content_with_challenge_retries(
                                page,
                                city_url,
                                wait_ms=wait_ms,
                                challenge_retry_delay_seconds=challenge_retry_delay_seconds,
                            )
                        else:
                            city_html, city_final_url = html, final_url
                        if is_challenge_html(city_html, city_final_url):
                            province_status.update(
                                {
                                    "status": "challenge",
                                    "city": city_name,
                                    "final_url": city_final_url,
                                    "updated_at": utc_now_iso(),
                                }
                            )
                            save_observed_payload(output, observed)
                            raise RuntimeError(f"Taobao challenge/login page encountered while opening {province_name}/{city_name}: {city_final_url}")
                        city_page_options = extract_location_filter_options(city_html, page_url=city_final_url)
                        entries = build_location_entries_from_page(
                            city_page_options,
                            province=province_name,
                            city=city_name,
                        )
                        merge_entries_into_observed(observed, entries)
                        province_status.update(
                            {
                                "status": "in_progress",
                                "last_city": city_name,
                                "last_city_url": city_final_url,
                                "location_count": sum(1 for entry in observed_entries_from_payload(observed) if entry.province == province_name),
                                "updated_at": utc_now_iso(),
                            }
                        )
                        save_observed_payload(output, observed)
                        if delay_seconds > 0:
                            time.sleep(delay_seconds)

                    completed.add(province_name)
                    observed["completed_provinces"] = sorted(completed, key=_province_sort_key)
                    province_status.update(
                        {
                            "status": "completed",
                            "completed_at": utc_now_iso(),
                            "location_count": sum(1 for entry in observed_entries_from_payload(observed) if entry.province == province_name),
                        }
                    )
                    save_observed_payload(output, observed)
            finally:
                page.close()
        finally:
            browser.close()

    return {
        "ok": True,
        "output": str(output),
        "duration_seconds": round(time.time() - started_at, 2),
        "completed_provinces": observed.get("completed_provinces", []),
        "location_count": len(observed_entries_from_payload(observed)),
    }


__all__ = (
    '_page_goto_and_content',
    '_page_goto_and_content_with_challenge_retries',
    'crawl_taobao_sf_locations',
)
