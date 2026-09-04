"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.taobao_sf_locations_context import *


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


__all__ = (
    'utc_now_iso',
    'read_json',
    'write_json_atomic',
    'clean_text',
    'short_region_name',
    'canonical_province_name',
    'canonical_city_name',
    'build_location_entries_from_page',
    'normalize_observed_location',
    'observed_entries_from_payload',
    'dedupe_entries',
)
