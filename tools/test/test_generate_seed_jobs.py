from __future__ import annotations

import json
from pathlib import Path

from tools import generate_seed_jobs


def _write_locations(path: Path) -> None:
    path.write_text(
        json.dumps(
            [
                {
                    "code": "440000",
                    "name": "广东省",
                    "children": [
                        {
                            "code": "440100",
                            "name": "广州市",
                            "children": [
                                {"code": "440115", "name": "南沙区"},
                                {"code": "440106", "name": "天河区"},
                            ],
                        }
                    ],
                },
                {
                    "code": "110000",
                    "name": "北京市",
                    "children": [{"code": "110101", "name": "东城区"}],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_build_seed_jobs_expands_all_six_digit_locations_categories_and_default_sorts(tmp_path: Path) -> None:
    locations_path = tmp_path / "all_locations.json"
    _write_locations(locations_path)

    jobs = generate_seed_jobs.build_seed_jobs(
        locations_path=locations_path,
        categories=("50025969", "200782003"),
        max_page=83,
    )

    assert len(jobs) == 12
    first = jobs[0]
    assert first["job_key"] == "440000-50025969"
    assert first["province"] == "广东省"
    assert first["city"] == ""
    assert first["district"] == ""
    assert first["location_code"] == "440000"
    assert first["category"] == "50025969"
    assert first["max_page"] == 83
    assert [sort["st_param"] for sort in first["sorts"]] == ["0", "3", "2", "1", "4", "5"]
    assert [sort["sort_name"] for sort in first["sorts"][:2]] == ["默认排序", "价格由高到低"]
    assert [job["job_key"] for job in jobs] == [
        "440000-50025969",
        "440000-200782003",
        "440100-50025969",
        "440100-200782003",
        "440115-50025969",
        "440115-200782003",
        "440106-50025969",
        "440106-200782003",
        "110000-50025969",
        "110000-200782003",
        "110101-50025969",
        "110101-200782003",
    ]


def test_build_seed_jobs_merges_taobao_sf_location_overrides(tmp_path: Path) -> None:
    locations_path = tmp_path / "all_locations.json"
    overrides_path = tmp_path / "taobao_sf_location_overrides.json"
    locations_path.write_text(
        json.dumps(
            [
                {
                    "code": "310000",
                    "name": "上海市",
                    "children": [
                        {
                            "code": "310100",
                            "name": "市辖区",
                            "children": [
                                {"code": "310101", "name": "黄浦区"},
                                {"code": "310104", "name": "徐汇区"},
                                {"code": "310151", "name": "崇明区"},
                            ],
                        }
                    ],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    overrides_path.write_text(
        json.dumps(
            [
                {"province": "上海市", "city": "市辖区", "district": "卢湾", "location_code": "310103"},
                {"province": "上海市", "city": "市辖区", "district": "闸北", "location_code": "310108"},
                {"province": "上海市", "city": "市辖区", "district": "南汇", "location_code": "310119"},
                {"province": "上海市", "city": "市辖区", "district": "川沙", "location_code": "310152"},
                {"province": "上海市", "city": "市辖区", "district": "崇明", "location_code": "310230"},
                {"province": "上海市", "city": "市辖区", "district": "其它", "location_code": "310231"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    jobs = generate_seed_jobs.build_seed_jobs(
        locations_path=locations_path,
        taobao_locations_path=overrides_path,
        categories=("50025969",),
        max_page=83,
    )

    by_code = {job["location_code"]: job for job in jobs}
    assert {"310103", "310108", "310119", "310152", "310230", "310231"} <= set(by_code)
    assert by_code["310103"]["district"] == "卢湾"
    assert by_code["310103"]["metadata"]["location_source"] == "taobao_sf_location_overrides"
    assert by_code["310151"]["district"] == "崇明区"


def test_cli_uses_taobao_sf_location_overrides_when_file_is_provided(tmp_path: Path) -> None:
    locations_path = tmp_path / "all_locations.json"
    output_path = tmp_path / "seed_jobs_all.json"
    overrides_path = tmp_path / "taobao_sf_location_overrides.json"
    _write_locations(locations_path)
    overrides_path.write_text(
        json.dumps(
            [{"province": "上海市", "city": "市辖区", "district": "卢湾", "location_code": "310103"}],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    exit_code = generate_seed_jobs.main(
        [
            "--locations-file",
            str(locations_path),
            "--taobao-locations-file",
            str(overrides_path),
            "--output",
            str(output_path),
            "--categories",
            "50025969",
            "--max-page",
            "12",
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert any(job["job_key"] == "310103-50025969" for job in payload)


def test_build_seed_jobs_can_replace_admin_province_with_taobao_locations(tmp_path: Path) -> None:
    locations_path = tmp_path / "all_locations.json"
    overrides_path = tmp_path / "taobao_sf_location_overrides.json"
    locations_path.write_text(
        json.dumps(
            [
                {
                    "code": "310000",
                    "name": "上海市",
                    "children": [
                        {
                            "code": "310100",
                            "name": "市辖区",
                            "children": [{"code": "310151", "name": "崇明区"}],
                        }
                    ],
                },
                {
                    "code": "440000",
                    "name": "广东省",
                    "children": [{"code": "440100", "name": "广州市"}],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    overrides_path.write_text(
        json.dumps(
            {
                "replace_admin_provinces": ["上海市"],
                "locations": [
                    {"province": "上海市", "city": "市辖区", "district": "崇明", "location_code": "310230"}
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    jobs = generate_seed_jobs.build_seed_jobs(
        locations_path=locations_path,
        taobao_locations_path=overrides_path,
        categories=("50025969",),
    )

    codes = {job["location_code"] for job in jobs}
    assert "310230" in codes
    assert "310151" not in codes
    assert "440100" in codes


def test_cli_writes_seed_jobs_json_file(tmp_path: Path) -> None:
    locations_path = tmp_path / "all_locations.json"
    output_path = tmp_path / "seed_jobs_all.json"
    _write_locations(locations_path)

    exit_code = generate_seed_jobs.main(
        [
            "--locations-file",
            str(locations_path),
            "--output",
            str(output_path),
            "--categories",
            "50025969",
            "--max-page",
            "12",
        ]
    )

    assert exit_code == 0
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(payload) == 6
    assert payload[0]["job_key"] == "440000-50025969"
    assert payload[0]["max_page"] == 12
