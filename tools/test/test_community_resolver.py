import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.avm.community_resolver import (
    CommunityIndex,
    CommunityResolution,
    apply_community_resolution,
    load_default_community_index,
    resolve_community_name,
)


def test_resolve_community_name_exact_beike_entry():
    index = CommunityIndex.from_rows(
        [
            {
                "city": "北京市",
                "district": "东城区",
                "canonical_name": "朝阳门内大街288号院",
                "beike_id": "bj-test-001",
            }
        ]
    )

    result = resolve_community_name(
        {
            "城市": "北京市",
            "区": "东城区",
            "所属小区": "朝阳门内大街288号院",
            "地点": "北京市东城区朝阳门内大街288号院3号楼1单元1502号房产",
        },
        index,
    )

    assert result.name == "朝阳门内大街288号院"
    assert result.source == "beike_exact"
    assert result.confidence == 1.0
    assert result.beike_id == "bj-test-001"
    assert result.stable_key == "beike::北京市::东城区::朝阳门内大街288号院"


def test_resolve_community_name_matches_alias_and_preserves_canonical_name():
    index = CommunityIndex.from_rows(
        [
            {
                "city": "北京市",
                "district": "朝阳区",
                "canonical_name": "远洋天地",
                "aliases": ["远洋天地一期", "远洋天地小区"],
            }
        ]
    )

    result = resolve_community_name(
        {
            "city": "北京市",
            "district": "朝阳区",
            "community_name": "远洋天地小区",
            "full_address": "北京市朝阳区八里庄远洋天地小区7号楼",
        },
        index,
    )

    assert result.name == "远洋天地"
    assert result.source == "beike_alias"
    assert result.confidence == 0.98
    assert result.raw_name == "远洋天地小区"


def test_resolve_community_name_uses_address_when_ai_name_is_missing():
    index = CommunityIndex.from_rows(
        [
            {
                "city": "上海市",
                "district": "浦东新区",
                "canonical_name": "张江汤臣豪园",
            }
        ]
    )

    result = resolve_community_name(
        {
            "城市": "上海市",
            "区": "浦东新区",
            "地点": "上海市浦东新区晨晖路828弄张江汤臣豪园12号楼202室",
        },
        index,
    )

    assert result.name == "张江汤臣豪园"
    assert result.source == "beike_address"
    assert result.confidence == 0.95


def test_resolve_community_name_prefers_address_beike_match_over_unmatched_raw_name():
    index = CommunityIndex.from_rows(
        [
            {
                "city": "北京市",
                "district": "朝阳区",
                "canonical_name": "远洋天地",
            }
        ]
    )

    result = resolve_community_name(
        {
            "城市": "北京市",
            "区": "朝阳区",
            "所属小区": "八里庄住宅",
            "地点": "北京市朝阳区八里庄远洋天地7号楼",
        },
        index,
    )

    assert result.name == "远洋天地"
    assert result.source == "beike_address"
    assert result.raw_name == "八里庄住宅"


def test_load_default_community_index_uses_env_path(tmp_path: Path, monkeypatch):
    index_file = tmp_path / "beike_communities.json"
    index_file.write_text(
        """[
  {"city": "北京市", "district": "朝阳区", "canonical_name": "远洋天地", "aliases": ["远洋天地小区"]}
]""",
        encoding="utf-8",
    )
    monkeypatch.setenv("FAPAI_COMMUNITY_INDEX_PATH", str(index_file))

    index = load_default_community_index(refresh=True)
    result = resolve_community_name(
        {"城市": "北京市", "区": "朝阳区", "所属小区": "远洋天地小区"},
        index,
    )

    assert result.name == "远洋天地"
    assert result.source == "beike_alias"


def test_resolve_community_name_returns_geo_anchor_when_beike_entry_missing():
    result = resolve_community_name(
        {
            "城市": "温州市",
            "区": "瑞安市",
            "最靠近商圈": "陶山镇",
            "地点": "浙江省温州市瑞安市陶山镇石坑村201室房地产",
        },
        CommunityIndex.empty(),
    )

    assert result.name == "瑞安市陶山镇位置片区"
    assert result.source == "geo_fallback"
    assert result.confidence == 0.45
    assert result.stable_key == "geo::温州市::瑞安市::陶山镇"


def test_resolve_community_name_uses_geo_anchor_when_raw_name_is_full_address():
    full_address = "北京市朝阳区八里庄远洋天地小区7号楼1单元101室"

    result = resolve_community_name(
        {
            "城市": "北京市",
            "区": "朝阳区",
            "最靠近商圈": "八里庄",
            "所属小区": full_address,
            "地点": full_address,
        },
        CommunityIndex.empty(),
    )

    assert result.name == "朝阳区八里庄位置片区"
    assert result.source == "geo_fallback"
    assert result.confidence == 0.45
    assert result.stable_key == "geo::北京市::朝阳区::八里庄"
    assert result.raw_name == full_address


def test_resolve_community_name_uses_district_anchor_when_full_address_has_no_business_area():
    full_address = "北京市朝阳区远洋天地小区7号楼1单元101室"

    result = resolve_community_name(
        {
            "城市": "北京市",
            "区": "朝阳区",
            "所属小区": full_address,
            "地点": full_address,
        },
        CommunityIndex.empty(),
    )

    assert result.name == "朝阳区位置片区"
    assert result.source == "geo_fallback"
    assert result.confidence == 0.35
    assert result.stable_key == "geo::北京市::朝阳区"
    assert result.raw_name == full_address


def test_resolve_community_name_keeps_numbered_courtyard_as_collector_name():
    raw_name = "朝阳门内大街288号院"

    result = resolve_community_name(
        {
            "城市": "北京市",
            "区": "东城区",
            "所属小区": raw_name,
        },
        CommunityIndex.empty(),
    )

    assert result.name == raw_name
    assert result.source == "collector"
    assert result.stable_key == "collector::北京市::东城区::朝阳门内大街288号院"


def test_apply_community_resolution_writes_flat_nested_and_audit_fields():
    item = {
        "id": "item-1",
        "城市": "温州市",
        "区": "瑞安市",
        "最靠近商圈": "陶山镇",
        "地点": "浙江省温州市瑞安市陶山镇石坑村201室房地产",
    }
    result = CommunityResolution(
        name="瑞安市陶山镇位置片区",
        source="geo_fallback",
        confidence=0.45,
        stable_key="geo::温州市::瑞安市::陶山镇",
        raw_name="",
        beike_id=None,
    )

    apply_community_resolution(item, result)

    assert item["所属小区"] == "瑞安市陶山镇位置片区"
    assert item["community_name"] == "瑞安市陶山镇位置片区"
    assert item["location"]["community_name"] == "瑞安市陶山镇位置片区"
    assert item["community_name_source"] == "geo_fallback"
    assert item["community_name_confidence"] == 0.45
    assert item["community_stable_key"] == "geo::温州市::瑞安市::陶山镇"
