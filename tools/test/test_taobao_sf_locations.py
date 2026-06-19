from __future__ import annotations

import json
from pathlib import Path

from tools import taobao_sf_locations


LOCATION_FILTER_HTML = """
<html>
  <body>
    <div class="sf-filter-row">
      <div class="sf-filter-key">分类</div>
      <a href="//sf.taobao.com/list/50025969__2.htm?location_code=310101&auction_source=0">住宅用房</a>
      <a href="//sf.taobao.com/list/200782003__2.htm?location_code=310101&auction_source=0">商业用房</a>
    </div>
    <div class="sf-filter-row">
      <div class="sf-filter-key">所在地</div>
      <a href="//sf.taobao.com/list/50025969__2.htm?auction_source=0">不限</a>
      <a href="//sf.taobao.com/list/50025969__2__%C9%CF%BA%A3.htm?auction_source=0">上海</a>
      <a href="//sf.taobao.com/list/50025969__2___%C9%CF%BA%A3.htm?auction_source=0" class="selected">上海</a>
      <a href="//sf.taobao.com/list/50025969__2.htm?location_code=310101&auction_source=0">黄浦</a>
      <a href="//sf.taobao.com/list/50025969__2.htm?location_code=310103&auction_source=0">卢湾</a>
      <a href="//sf.taobao.com/list/50025969__2.htm?location_code=310230&auction_source=0">崇明</a>
      <a href="//sf.taobao.com/list/50025969__2.htm?location_code=310231&auction_source=0">其它</a>
    </div>
  </body>
</html>
""".strip()


def test_is_challenge_html_allows_logged_in_pages_with_logout_links() -> None:
    html = """
    <html>
      <body>
        <a href="//login.taobao.com/member/logout.jhtml?redirectURL=https%3A%2F%2Fsf.taobao.com%2Flist%2F50025969__2.htm">退出</a>
        <div class="sf-filter-row">
          <div class="sf-filter-key">所在地</div>
          <a href="//sf.taobao.com/list/50025969__2__%B9%E3%B6%AB.htm?auction_source=0">广东</a>
        </div>
      </body>
    </html>
    """

    assert taobao_sf_locations.is_challenge_html(
        html,
        final_url="https://sf.taobao.com/list/50025969__2.htm?auction_source=0",
    ) is False


def test_is_challenge_html_detects_login_redirect_url() -> None:
    assert taobao_sf_locations.is_challenge_html(
        "<html><body>登录</body></html>",
        final_url="https://login.taobao.com/member/login.jhtml?redirectURL=https%3A%2F%2Fsf.taobao.com",
    ) is True


def test_clean_text_strips_private_use_icon_glyphs_from_filter_labels(tmp_path: Path) -> None:
    admin_path = tmp_path / "all_locations.json"
    admin_path.write_text(
        json.dumps(
            [
                {
                    "name": "广东省",
                    "children": [{"name": "广州市", "children": []}],
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    admin_index = taobao_sf_locations.AdminLocationIndex(admin_path)

    assert taobao_sf_locations.clean_text("天津 \ue605") == "天津"
    assert taobao_sf_locations.canonical_province_name("天津 \ue605") == "天津市"
    assert taobao_sf_locations.canonical_city_name("广东省", "广州 \ue605", admin_index) == "广州市"


def test_page_goto_and_content_retries_once_when_challenge_is_transient(monkeypatch) -> None:
    class FakePage:
        def __init__(self) -> None:
            self.goto_calls = 0
            self.wait_calls: list[int] = []
            self.url = "https://sf.taobao.com/list/50025969__2.htm"

        def goto(self, url: str, wait_until: str, timeout: int) -> None:
            self.goto_calls += 1
            self.url = url

        def wait_for_timeout(self, wait_ms: int) -> None:
            self.wait_calls.append(wait_ms)

        def content(self) -> str:
            if self.goto_calls == 1:
                return "<html>请完成验证</html>"
            return "<html><div class='sf-filter-key'>所在地</div></html>"

    sleep_calls: list[float] = []
    monkeypatch.setattr(taobao_sf_locations.time, "sleep", sleep_calls.append)
    page = FakePage()

    html, final_url = taobao_sf_locations._page_goto_and_content_with_challenge_retries(
        page,
        "https://sf.taobao.com/list/50025969__2.htm",
        wait_ms=1800,
        challenge_retries=1,
        challenge_retry_delay_seconds=30.0,
    )

    assert page.goto_calls == 2
    assert sleep_calls == [30.0]
    assert taobao_sf_locations.is_challenge_html(html, final_url) is False


def test_extract_location_filter_options_ignores_non_location_rows() -> None:
    options = taobao_sf_locations.extract_location_filter_options(
        LOCATION_FILTER_HTML,
        page_url="https://sf.taobao.com/list/50025969__2.htm?location_code=310101",
    )

    assert [option.label for option in options.provinces] == ["上海"]
    assert [option.label for option in options.cities] == ["上海"]
    assert [(option.label, option.location_code) for option in options.districts] == [
        ("黄浦", "310101"),
        ("卢湾", "310103"),
        ("崇明", "310230"),
        ("其它", "310231"),
    ]


def test_build_location_entries_from_page_maps_direct_municipality_city() -> None:
    options = taobao_sf_locations.extract_location_filter_options(
        LOCATION_FILTER_HTML,
        page_url="https://sf.taobao.com/list/50025969__2.htm?location_code=310101",
    )

    entries = taobao_sf_locations.build_location_entries_from_page(
        options,
        province="上海市",
        city="市辖区",
    )

    assert [entry.to_override_dict() for entry in entries] == [
        {"province": "上海市", "city": "市辖区", "district": "黄浦", "location_code": "310101"},
        {"province": "上海市", "city": "市辖区", "district": "卢湾", "location_code": "310103"},
        {"province": "上海市", "city": "市辖区", "district": "崇明", "location_code": "310230"},
        {"province": "上海市", "city": "市辖区", "district": "其它", "location_code": "310231"},
    ]


def test_build_location_entries_preserves_taobao_other_district_options() -> None:
    html = """
    <html>
      <body>
        <div class="sf-filter-row">
          <div class="sf-filter-key">所在地</div>
          <a href="//sf.taobao.com/list/50025969__2.htm?auction_source=0">不限</a>
          <a href="//sf.taobao.com/list/50025969__2.htm?location_code=440199&auction_source=0">其它</a>
          <a href="//sf.taobao.com/list/50025969__2.htm?location_code=440198&auction_source=0">其他</a>
        </div>
      </body>
    </html>
    """
    options = taobao_sf_locations.extract_location_filter_options(
        html,
        page_url="https://sf.taobao.com/list/50025969__2.htm",
    )

    entries = taobao_sf_locations.build_location_entries_from_page(
        options,
        province="广东省",
        city="广州市",
    )

    assert [entry.to_override_dict() for entry in entries] == [
        {"province": "广东省", "city": "广州市", "district": "其它", "location_code": "440199"},
        {"province": "广东省", "city": "广州市", "district": "其他", "location_code": "440198"},
    ]


def test_compare_observed_locations_reports_admin_and_taobao_differences(tmp_path: Path) -> None:
    admin_path = tmp_path / "all_locations.json"
    admin_path.write_text(
        json.dumps(
            [
                {
                    "code": "31",
                    "name": "上海市",
                    "children": [
                        {
                            "code": "3101",
                            "name": "市辖区",
                            "children": [
                                {"code": "310101", "name": "黄浦区"},
                                {"code": "310151", "name": "崇明区"},
                            ],
                        }
                    ],
                },
                {
                    "code": "44",
                    "name": "广东省",
                    "children": [{"code": "4401", "name": "广州市"}],
                },
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    observed = {
        "completed_provinces": ["上海市"],
        "locations": [
            {"province": "上海市", "city": "市辖区", "district": "黄浦", "location_code": "310101"},
            {"province": "上海市", "city": "市辖区", "district": "卢湾", "location_code": "310103"},
            {"province": "上海市", "city": "市辖区", "district": "崇明", "location_code": "310230"},
        ],
    }

    report = taobao_sf_locations.compare_observed_locations(
        all_locations_path=admin_path,
        observed_payload=observed,
    )

    shanghai = report["provinces"]["上海市"]
    assert shanghai["completed"] is True
    assert shanghai["admin_count"] == 2
    assert shanghai["taobao_count"] == 3
    assert shanghai["only_admin_codes"] == ["310151"]
    assert shanghai["only_taobao_codes"] == ["310103", "310230"]
    assert shanghai["name_mismatches"] == [{"location_code": "310101", "admin": "黄浦区", "taobao": "黄浦"}]
    assert report["recommended_replace_admin_provinces"] == ["上海市"]


def test_build_override_payload_preserves_existing_and_replaces_completed_provinces() -> None:
    existing = {
        "replace_admin_provinces": ["旧省"],
        "locations": [
            {"province": "旧省", "city": "旧市", "district": "旧区", "location_code": "990001"},
            {"province": "上海市", "city": "市辖区", "district": "旧上海", "location_code": "310999"},
        ],
    }
    observed = {
        "completed_provinces": ["上海市"],
        "locations": [
            {"province": "上海市", "city": "市辖区", "district": "黄浦", "location_code": "310101"},
            {"province": "上海市", "city": "市辖区", "district": "崇明", "location_code": "310230"},
        ],
    }

    payload = taobao_sf_locations.build_override_payload(existing_payload=existing, observed_payload=observed)

    assert payload["replace_admin_provinces"] == ["上海市", "旧省"]
    assert payload["locations"] == [
        {"province": "旧省", "city": "旧市", "district": "旧区", "location_code": "990001"},
        {"province": "上海市", "city": "市辖区", "district": "黄浦", "location_code": "310101"},
        {"province": "上海市", "city": "市辖区", "district": "崇明", "location_code": "310230"},
    ]
