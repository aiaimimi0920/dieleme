"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.taobao_sf_locations_context import *


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


__all__ = (
    '_province_sort_key',
    'admin_entries_by_province',
    'compare_observed_locations',
)
