from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import generate_seed_jobs  # noqa: E402


DEFAULT_CATEGORY = "50025969"
DEFAULT_CDP_ENDPOINT = "http://127.0.0.1:9223"
DEFAULT_OUTPUT = Path("datas") / "taobao_sf_locations_observed.json"
DEFAULT_OVERRIDES = Path("datas") / "taobao_sf_location_overrides.json"
DEFAULT_START_URL = "https://sf.taobao.com/list/{category}__2.htm?auction_source=0&st_param=-1&auction_start_seg=-1"
SCHEMA_VERSION = "taobao_sf_locations_v1"
LOCATION_OPTION_IGNORE_LABELS = {
    "",
    "不限",
    "全省",
    "全市",
    "全部",
}
CATEGORY_LABELS = {
    "住宅用房",
    "商业用房",
    "工业用房",
    "其他用房",
    "机动车",
    "航空交通",
    "船舶",
    "其他交通",
    "股权",
    "债权",
    "林权",
    "矿权",
    "土地",
    "工程",
    "海域",
    "机器设备",
    "资产",
    "无形资产",
    "古玩字画",
    "珠宝首饰",
    "其他",
}
DIRECT_MUNICIPALITIES = {"北京市", "天津市", "上海市", "重庆市"}
CHALLENGE_MARKERS = (
    "_____tmd_____/punish",
    "x5secdata=",
    "霸下通用 web 页面-验证码",
    "请完成验证",
    "安全验证",
    "RGV587_ERROR",
)


@dataclass(frozen=True)
class LocationOption:
    label: str
    href: str
    level: str
    location_code: str | None = None


@dataclass(frozen=True)
class LocationFilterOptions:
    provinces: list[LocationOption]
    cities: list[LocationOption]
    districts: list[LocationOption]
    source_url: str = ""


@dataclass(frozen=True)
class TaobaoLocationEntry:
    province: str
    city: str
    district: str
    location_code: str
    source_url: str = ""

    def to_override_dict(self) -> dict[str, str]:
        return {
            "province": self.province,
            "city": self.city,
            "district": self.district,
            "location_code": self.location_code,
        }

    def to_observed_dict(self) -> dict[str, str]:
        payload = self.to_override_dict()
        if self.source_url:
            payload["source_url"] = self.source_url
        return payload


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: str | Path, default: Any = None) -> Any:
    target = Path(path)
    if not target.exists():
        return default
    return json.loads(target.read_text(encoding="utf-8"))


def write_json_atomic(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f".{target.name}.tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_path.replace(target)


def clean_text(value: Any) -> str:
    text = re.sub(r"[\ue000-\uf8ff]", "", str(value if value is not None else ""))
    return re.sub(r"\s+", " ", text).strip()


def short_region_name(value: str) -> str:
    text = clean_text(value)
    for suffix in ("特别行政区", "维吾尔自治区", "壮族自治区", "回族自治区", "自治区", "省", "市", "区", "县"):
        if text.endswith(suffix) and len(text) > len(suffix):
            return text[: -len(suffix)]
    return text


def canonical_province_name(value: str, admin_index: "AdminLocationIndex | None" = None) -> str:
    text = clean_text(value)
    if not text:
        return text
    if admin_index:
        matched = admin_index.province_by_short_name.get(short_region_name(text))
        if matched:
            return matched
    if text in {"北京", "天津", "上海", "重庆"}:
        return f"{text}市"
    if text in {"内蒙古", "广西", "西藏", "宁夏", "新疆"}:
        suffix = {
            "内蒙古": "自治区",
            "广西": "壮族自治区",
            "西藏": "自治区",
            "宁夏": "回族自治区",
            "新疆": "维吾尔自治区",
        }[text]
        return f"{text}{suffix}"
    if not text.endswith(("省", "市", "自治区", "特别行政区")):
        return f"{text}省"
    return text


def canonical_city_name(province: str, value: str, admin_index: "AdminLocationIndex | None" = None) -> str:
    province_name = canonical_province_name(province, admin_index)
    text = clean_text(value)
    if province_name in DIRECT_MUNICIPALITIES:
        return "市辖区"
    if not text:
        return ""
    if admin_index:
        matched = admin_index.city_by_province_and_short_name.get((province_name, short_region_name(text)))
        if matched:
            return matched
    if not text.endswith(("市", "州", "盟", "地区", "自治州", "县")):
        return f"{text}市"
    return text


class AdminLocationIndex:
    def __init__(self, all_locations_path: str | Path):
        self.province_by_short_name: dict[str, str] = {}
        self.city_by_province_and_short_name: dict[tuple[str, str], str] = {}
        self._load(all_locations_path)

    def _load(self, all_locations_path: str | Path) -> None:
        payload = read_json(all_locations_path, default=[])
        if not isinstance(payload, list):
            return
        for province_node in payload:
            if not isinstance(province_node, dict):
                continue
            province = clean_text(province_node.get("name"))
            if not province:
                continue
            self.province_by_short_name.setdefault(short_region_name(province), province)
            children = province_node.get("children")
            if not isinstance(children, list):
                continue
            for city_node in children:
                if not isinstance(city_node, dict):
                    continue
                city = clean_text(city_node.get("name"))
                if city:
                    self.city_by_province_and_short_name.setdefault((province, short_region_name(city)), city)


def is_challenge_html(html: str, final_url: str = "") -> bool:
    parsed_url = urlparse(final_url or "")
    if parsed_url.hostname in {"login.taobao.com", "login.tmall.com"}:
        return True
    text = f"{final_url}\n{html or ''}"
    return any(marker in text for marker in CHALLENGE_MARKERS)


def absolute_href(href: str, page_url: str = "https://sf.taobao.com/") -> str:
    clean_href = clean_text(href)
    if clean_href.startswith("//"):
        return f"https:{clean_href}"
    return urljoin(page_url or "https://sf.taobao.com/", clean_href)


def extract_location_code(href: str) -> str | None:
    parsed = urlparse(href)
    values = parse_qs(parsed.query).get("location_code") or []
    if not values:
        return None
    code = clean_text(values[0])
    return code if code else None


def _is_taobao_sf_list_href(href: str) -> bool:
    return "sf.taobao.com/list/" in href or href.startswith("//sf.taobao.com/list/")


def _is_city_location_href(href: str) -> bool:
    path = urlparse(href).path
    return "___" in path


def _is_province_location_href(href: str) -> bool:
    path = urlparse(href).path
    return "__" in path and "___" not in path


def _tag_text(tag: Any) -> str:
    return clean_text(tag.get_text(" ", strip=True) if tag is not None else "")


def _find_location_filter_scope(soup: BeautifulSoup) -> Any | None:
    key_nodes = soup.find_all(string=lambda value: clean_text(value) == "所在地")
    for key_node in key_nodes:
        key_tag = getattr(key_node, "parent", None)
        current = key_tag
        for _ in range(5):
            if current is None:
                break
            current = current.parent
            if current is None or getattr(current, "name", None) in {"body", "html", "[document]"}:
                break
            anchors = current.find_all("a", href=True)
            if not anchors:
                continue
            location_like_count = sum(1 for anchor in anchors if _is_taobao_sf_list_href(absolute_href(anchor.get("href", ""))))
            if location_like_count and len(anchors) <= 260:
                return current
    return None


def _collect_location_anchors_from_document_order(soup: BeautifulSoup, page_url: str) -> list[Any]:
    key = soup.find(string=lambda value: clean_text(value) == "所在地")
    if key is None:
        return []
    key_tag = getattr(key, "parent", None)
    anchors: list[Any] = []
    started = False
    for tag in soup.find_all(True):
        if tag is key_tag:
            started = True
            continue
        if not started:
            continue
        if "sf-filter-key" in (tag.get("class") or []) and clean_text(tag.get_text(strip=True)) != "所在地":
            break
        if tag.name == "a" and tag.get("href"):
            href = absolute_href(str(tag.get("href")), page_url)
            if _is_taobao_sf_list_href(href):
                anchors.append(tag)
    return anchors


def extract_location_filter_options(html: str, *, page_url: str = "https://sf.taobao.com/") -> LocationFilterOptions:
    soup = BeautifulSoup(html or "", "html.parser")
    scope = _find_location_filter_scope(soup)
    anchors = scope.find_all("a", href=True) if scope is not None else _collect_location_anchors_from_document_order(soup, page_url)
    provinces: list[LocationOption] = []
    cities: list[LocationOption] = []
    districts: list[LocationOption] = []
    seen: set[tuple[str, str, str | None, str]] = set()
    for anchor in anchors:
        label = _tag_text(anchor)
        if label in LOCATION_OPTION_IGNORE_LABELS or (label in CATEGORY_LABELS and label not in {"其他", "其它"}):
            continue
        href = absolute_href(str(anchor.get("href") or ""), page_url)
        if not _is_taobao_sf_list_href(href):
            continue
        location_code = extract_location_code(href)
        if location_code:
            level = "district"
        elif _is_city_location_href(href):
            level = "city"
        elif _is_province_location_href(href):
            level = "province"
        else:
            continue
        key = (level, label, location_code, href)
        if key in seen:
            continue
        seen.add(key)
        option = LocationOption(label=label, href=href, level=level, location_code=location_code)
        if level == "district":
            districts.append(option)
        elif level == "city":
            cities.append(option)
        else:
            provinces.append(option)
    return LocationFilterOptions(provinces=provinces, cities=cities, districts=districts, source_url=page_url)


def build_location_entries_from_page(
    options: LocationFilterOptions,
    *,
    province: str,
    city: str,
) -> list[TaobaoLocationEntry]:
    province_name = clean_text(province)
    city_name = clean_text(city)
    entries: list[TaobaoLocationEntry] = []
    for district in options.districts:
        if not district.location_code:
            continue
        entries.append(
            TaobaoLocationEntry(
                province=province_name,
                city=city_name,
                district=district.label,
                location_code=district.location_code,
                source_url=district.href or options.source_url,
            )
        )
    return dedupe_entries(entries)


def normalize_observed_location(item: dict[str, Any]) -> TaobaoLocationEntry | None:
    code = clean_text(item.get("location_code") or item.get("code"))
    if not code:
        return None
    province = clean_text(item.get("province"))
    city = clean_text(item.get("city"))
    district = clean_text(item.get("district") or item.get("name") or item.get("label"))
    if not province or not district:
        return None
    return TaobaoLocationEntry(
        province=province,
        city=city,
        district=district,
        location_code=code,
        source_url=clean_text(item.get("source_url")),
    )


def observed_entries_from_payload(payload: Any) -> list[TaobaoLocationEntry]:
    if not isinstance(payload, dict):
        return []
    raw_locations = payload.get("locations") or payload.get("entries") or []
    if not isinstance(raw_locations, list):
        return []
    entries = [entry for entry in (normalize_observed_location(item) for item in raw_locations if isinstance(item, dict)) if entry]
    return dedupe_entries(entries)


def dedupe_entries(entries: Iterable[TaobaoLocationEntry]) -> list[TaobaoLocationEntry]:
    by_code: dict[str, TaobaoLocationEntry] = {}
    order: list[str] = []
    for entry in entries:
        if entry.location_code not in by_code:
            order.append(entry.location_code)
        by_code[entry.location_code] = entry
    return [by_code[code] for code in order]


def _province_sort_key(value: str) -> tuple[int, str]:
    order = [
        "北京市",
        "天津市",
        "河北省",
        "山西省",
        "内蒙古自治区",
        "辽宁省",
        "吉林省",
        "黑龙江省",
        "上海市",
        "江苏省",
        "浙江省",
        "安徽省",
        "福建省",
        "江西省",
        "山东省",
        "河南省",
        "湖北省",
        "湖南省",
        "广东省",
        "广西壮族自治区",
        "海南省",
        "重庆市",
        "四川省",
        "贵州省",
        "云南省",
        "西藏自治区",
        "陕西省",
        "甘肃省",
        "青海省",
        "宁夏回族自治区",
        "新疆维吾尔自治区",
    ]
    try:
        return order.index(value), value
    except ValueError:
        return len(order), value


def admin_entries_by_province(all_locations_path: str | Path) -> dict[str, dict[str, generate_seed_jobs.LocationEntry]]:
    result: dict[str, dict[str, generate_seed_jobs.LocationEntry]] = {}
    for entry in generate_seed_jobs.load_location_entries(all_locations_path):
        if not entry.province:
            continue
        result.setdefault(entry.province, {})[entry.code] = entry
    return result


def compare_observed_locations(
    *,
    all_locations_path: str | Path,
    observed_payload: dict[str, Any],
) -> dict[str, Any]:
    observed_entries = observed_entries_from_payload(observed_payload)
    raw_completed_provinces = observed_payload.get("completed_provinces")
    if not raw_completed_provinces:
        raw_completed_provinces = observed_payload.get("replace_admin_provinces") or []
    completed_provinces = {
        clean_text(value)
        for value in raw_completed_provinces
        if clean_text(value)
    }
    observed_by_province: dict[str, dict[str, TaobaoLocationEntry]] = {}
    for entry in observed_entries:
        observed_by_province.setdefault(entry.province, {})[entry.location_code] = entry
    admin_by_province = admin_entries_by_province(all_locations_path)
    all_provinces = sorted(set(admin_by_province) | set(observed_by_province), key=_province_sort_key)
    province_reports: dict[str, Any] = {}
    recommended_replace: list[str] = []
    for province in all_provinces:
        admin_codes = admin_by_province.get(province, {})
        taobao_codes = observed_by_province.get(province, {})
        only_admin_codes = sorted(set(admin_codes) - set(taobao_codes))
        only_taobao_codes = sorted(set(taobao_codes) - set(admin_codes))
        name_mismatches = []
        for code in sorted(set(admin_codes) & set(taobao_codes)):
            admin_name = clean_text(admin_codes[code].district or admin_codes[code].city or admin_codes[code].province)
            taobao_name = clean_text(taobao_codes[code].district)
            if admin_name and taobao_name and admin_name != taobao_name:
                name_mismatches.append({"location_code": code, "admin": admin_name, "taobao": taobao_name})
        completed = province in completed_provinces
        if completed and (only_admin_codes or only_taobao_codes or name_mismatches):
            recommended_replace.append(province)
        province_reports[province] = {
            "completed": completed,
            "admin_count": len(admin_codes),
            "taobao_count": len(taobao_codes),
            "only_admin_codes": only_admin_codes,
            "only_taobao_codes": only_taobao_codes,
            "name_mismatches": name_mismatches,
        }
    return {
        "schema_version": "taobao_sf_location_compare_v1",
        "generated_at": utc_now_iso(),
        "observed_location_count": len(observed_entries),
        "completed_provinces": sorted(completed_provinces, key=_province_sort_key),
        "recommended_replace_admin_provinces": sorted(recommended_replace, key=_province_sort_key),
        "provinces": province_reports,
    }


def _normalize_override_locations(payload: Any) -> list[TaobaoLocationEntry]:
    if not isinstance(payload, dict):
        return []
    raw_locations = payload.get("locations") or []
    if not isinstance(raw_locations, list):
        return []
    return [entry for entry in (normalize_observed_location(item) for item in raw_locations if isinstance(item, dict)) if entry]


def build_override_payload(
    *,
    existing_payload: dict[str, Any] | None,
    observed_payload: dict[str, Any],
) -> dict[str, Any]:
    existing = existing_payload if isinstance(existing_payload, dict) else {}
    completed_provinces = {
        clean_text(value)
        for value in observed_payload.get("completed_provinces", [])
        if clean_text(value)
    }
    observed_entries = observed_entries_from_payload(observed_payload)
    if completed_provinces:
        observed_entries = [entry for entry in observed_entries if entry.province in completed_provinces]
    else:
        completed_provinces = {entry.province for entry in observed_entries}

    retained_existing = [
        entry
        for entry in _normalize_override_locations(existing)
        if entry.province not in completed_provinces
    ]
    merged_entries = dedupe_entries([*retained_existing, *observed_entries])
    replace_provinces = {
        clean_text(value)
        for value in existing.get("replace_admin_provinces", [])
        if clean_text(value)
    }
    replace_provinces.update(completed_provinces)
    return {
        "replace_admin_provinces": sorted(replace_provinces, key=_province_sort_key),
        "locations": [entry.to_override_dict() for entry in merged_entries],
    }


def new_observed_payload() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": utc_now_iso(),
        "updated_at": utc_now_iso(),
        "completed_provinces": [],
        "province_status": {},
        "locations": [],
    }


def load_observed_payload(path: str | Path) -> dict[str, Any]:
    payload = read_json(path, default=None)
    if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
        return new_observed_payload()
    payload.setdefault("completed_provinces", [])
    payload.setdefault("province_status", {})
    payload.setdefault("locations", [])
    return payload


def save_observed_payload(path: str | Path, payload: dict[str, Any]) -> None:
    payload["schema_version"] = SCHEMA_VERSION
    payload["updated_at"] = utc_now_iso()
    payload["locations"] = [entry.to_observed_dict() for entry in dedupe_entries(observed_entries_from_payload(payload))]
    payload["completed_provinces"] = sorted({clean_text(value) for value in payload.get("completed_provinces", []) if clean_text(value)}, key=_province_sort_key)
    write_json_atomic(path, payload)


def merge_entries_into_observed(
    payload: dict[str, Any],
    entries: Iterable[TaobaoLocationEntry],
) -> None:
    merged = dedupe_entries([*observed_entries_from_payload(payload), *entries])
    payload["locations"] = [entry.to_observed_dict() for entry in merged]


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


def _parse_csv(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    values: list[str] = []
    for chunk in str(raw).replace(";", ",").split(","):
        value = clean_text(chunk)
        if value and value not in values:
            values.append(value)
    return tuple(values)


def cmd_crawl(args: argparse.Namespace) -> int:
    summary = crawl_taobao_sf_locations(
        cdp_endpoint=args.cdp_endpoint,
        output_path=args.output,
        all_locations_path=args.all_locations_file,
        category=args.category,
        delay_seconds=float(args.delay_seconds),
        wait_ms=int(args.wait_ms),
        province_filters=_parse_csv(args.province),
        max_provinces=args.max_provinces,
        max_cities_per_province=args.max_cities_per_province,
        resume=not bool(args.no_resume),
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    observed = read_json(args.observed, default={})
    report = compare_observed_locations(all_locations_path=args.all_locations_file, observed_payload=observed)
    if args.output:
        write_json_atomic(args.output, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def cmd_merge_overrides(args: argparse.Namespace) -> int:
    observed = read_json(args.observed, default={})
    existing = read_json(args.existing, default={}) if args.existing else {}
    payload = build_override_payload(existing_payload=existing, observed_payload=observed)
    write_json_atomic(args.output, payload)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "replace_admin_provinces": payload["replace_admin_provinces"],
                "location_count": len(payload["locations"]),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect and reconcile Taobao SF judicial-auction location taxonomy.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    crawl = subparsers.add_parser("crawl", help="Low-frequency, resumable live crawl from an authenticated CDP browser.")
    crawl.add_argument("--cdp-endpoint", default=os.environ.get("FAPAI_CDP_ENDPOINT_HOST", DEFAULT_CDP_ENDPOINT))
    crawl.add_argument("--all-locations-file", type=Path, default=Path("datas") / "all_locations.json")
    crawl.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    crawl.add_argument("--category", default=DEFAULT_CATEGORY)
    crawl.add_argument("--delay-seconds", type=float, default=8.0)
    crawl.add_argument("--wait-ms", type=int, default=1500)
    crawl.add_argument("--province", default="", help="Comma-separated province filters, e.g. 上海市,江苏省. Empty means all.")
    crawl.add_argument("--max-provinces", type=int, default=None)
    crawl.add_argument("--max-cities-per-province", type=int, default=None)
    crawl.add_argument("--no-resume", action="store_true")
    crawl.set_defaults(func=cmd_crawl)

    report = subparsers.add_parser("report", help="Compare observed Taobao locations with datas/all_locations.json.")
    report.add_argument("--all-locations-file", type=Path, default=Path("datas") / "all_locations.json")
    report.add_argument("--observed", type=Path, default=DEFAULT_OUTPUT)
    report.add_argument("--output", type=Path, default=None)
    report.set_defaults(func=cmd_report)

    merge = subparsers.add_parser("merge-overrides", help="Merge completed observed provinces into taobao_sf_location_overrides.json.")
    merge.add_argument("--observed", type=Path, default=DEFAULT_OUTPUT)
    merge.add_argument("--existing", type=Path, default=DEFAULT_OVERRIDES)
    merge.add_argument("--output", type=Path, default=DEFAULT_OVERRIDES)
    merge.set_defaults(func=cmd_merge_overrides)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
