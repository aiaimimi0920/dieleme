from __future__ import annotations

import json
from pathlib import Path

import requests

from tools import area_followup_runner


def test_extract_area_candidates_from_local_text_prefers_building_area(tmp_path: Path) -> None:
    text_path = tmp_path / "notice.txt"
    text_path.write_text(
        "标的物土地面积300平方米，房屋建筑面积88.88平方米，竞买人自行核实。",
        encoding="utf-8",
    )

    candidates = area_followup_runner.extract_area_candidates_from_paths([text_path])

    assert candidates[0]["area_sqm"] == 88.88
    assert candidates[0]["source_type"] == "local_text"
    assert candidates[0]["source_path"] == str(text_path)
    assert "房屋建筑面积88.88平方米" in candidates[0]["evidence"]


def test_resolve_job_from_local_artifacts_builds_patch_and_report(tmp_path: Path) -> None:
    item_dir = tmp_path / "123"
    item_dir.mkdir()
    detail_html = item_dir / "detail.html"
    detail_html.write_text(
        """
        <html>
          <body>
            <div id="J_NoticeDetail">评估对象房屋建筑面积为66.6平方米。</div>
            <a href="https://example.com/report.pdf">评估报告附件</a>
          </body>
        </html>
        """,
        encoding="utf-8",
    )
    final_json = item_dir / "final.json"
    final_json.write_text(
        json.dumps(
            {
                "id": 123,
                "成交价格": 999000,
                "建筑面积": None,
                "产权建筑面积": None,
                "单价": 0,
                "property": {"area_sqm": None, "gross_area_sqm": None},
                "auction": {"transaction_price": 999000},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    job = {
        "item_id": "123",
        "transaction_price": 999000,
        "detail_html_path": str(detail_html),
        "final_json_path": str(final_json),
    }

    result = area_followup_runner.resolve_job(job, artifact_root=tmp_path, write_patch=False)

    assert result["status"] == "resolved"
    assert result["selected_candidate"]["area_sqm"] == 66.6
    assert result["patch"]["建筑面积"] == 66.6
    assert result["patch"]["产权建筑面积"] == 66.6
    assert result["patch"]["单价"] == 15000.0
    assert result["patch"]["property"]["area_sqm"] == 66.6
    assert result["patch"]["property"]["gross_area_sqm"] == 66.6
    assert result["patch"]["property"]["unit_price"] == 15000.0
    assert result["artifacts"]["attachment_manifest_path"]
    assert result["artifacts"]["announcement_attachment_urls"] == ["https://example.com/report.pdf"]


def test_run_queue_writes_patch_for_resolved_jobs(tmp_path: Path) -> None:
    item_dir = tmp_path / "456"
    item_dir.mkdir()
    detail_html = item_dir / "detail.html"
    detail_html.write_text("<html><body>房屋建筑面积为120.5平方米</body></html>", encoding="utf-8")
    final_json = item_dir / "final.json"
    final_json.write_text(
        json.dumps({"id": 456, "成交价格": 2410000, "property": {}, "auction": {"transaction_price": 2410000}}, ensure_ascii=False),
        encoding="utf-8",
    )
    queue = {
        "schema_version": "area_followup_queue_v1",
        "jobs": [
            {
                "item_id": "456",
                "transaction_price": 2410000,
                "detail_html_path": str(detail_html),
                "final_json_path": str(final_json),
            }
        ],
    }
    queue_path = tmp_path / "area_followup_queue.json"
    queue_path.write_text(json.dumps(queue, ensure_ascii=False), encoding="utf-8")

    summary = area_followup_runner.run_queue(queue_path, output_dir=tmp_path)

    assert summary["processed_jobs"] == 1
    assert summary["resolved_jobs"] == 1
    patch_path = item_dir / "area_followup_patch.json"
    assert patch_path.exists()
    patch = json.loads(patch_path.read_text(encoding="utf-8"))
    assert patch["patch"]["建筑面积"] == 120.5
    assert patch["patch"]["单价"] == 20000.0


def test_apply_area_patch_updates_final_json_and_canonical_sections(tmp_path: Path) -> None:
    item_dir = tmp_path / "456"
    item_dir.mkdir()
    final_path = item_dir / "final.json"
    final_path.write_text(
        json.dumps(
            {
                "id": 456,
                "source_item_id": "456",
                "source_url": "https://sf-item.taobao.com/sf_item/456.htm",
                "标题": "测试房源",
                "成交价格": 2410000,
                "建筑面积": None,
                "产权建筑面积": None,
                "单价": 0,
                "property": {"area_sqm": None, "gross_area_sqm": None, "ownership_share_ratio": 1.0},
                "auction": {"transaction_price": 2410000},
                "audit": {"community_stable_key": "collector::北京市::东城区::测试片区"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    patch_path = item_dir / "area_followup_patch.json"
    patch_path.write_text(
        json.dumps(
            {
                "item_id": "456",
                "status": "resolved",
                "selected_candidate": {
                    "area_sqm": 120.5,
                    "source_type": "notice_detail",
                    "evidence": "建筑面积：120.5平方米",
                },
                "patch": {
                    "建筑面积": 120.5,
                    "产权建筑面积": 120.5,
                    "单价": 20000.0,
                    "area_sqm": 120.5,
                    "gross_area_sqm": 120.5,
                    "unit_price": 20000.0,
                    "property": {"area_sqm": 120.5, "gross_area_sqm": 120.5, "unit_price": 20000.0},
                    "archive": {"notice_text_path": "notice.txt"},
                    "legal_context": {"announcement_attachment_urls": ["https://example.com/notice"]},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = area_followup_runner.apply_patch_file(patch_path, final_path=final_path)

    assert result["status"] == "applied"
    assert result["backup_path"]
    assert Path(result["backup_path"]).exists()
    updated = json.loads(final_path.read_text(encoding="utf-8"))
    assert updated["建筑面积"] == 120.5
    assert updated["产权建筑面积"] == 120.5
    assert updated["单价"] == 20000.0
    assert updated["property"]["area_sqm"] == 120.5
    assert updated["property"]["gross_area_sqm"] == 120.5
    assert updated["property"]["unit_price"] == 20000.0
    assert updated["auction"]["transaction_price"] == 2410000
    assert updated["archive"]["notice_text_path"] == "notice.txt"
    assert updated["legal_context"]["announcement_attachment_urls"] == ["https://example.com/notice"]
    assert updated["area_followup_applied"] is True
    assert updated["area_followup_source"] == "notice_detail"
    assert "建筑面积：120.5平方米" in updated["area_followup_evidence"]


def test_apply_area_patch_refuses_unresolved_patch(tmp_path: Path) -> None:
    final_path = tmp_path / "final.json"
    final_path.write_text('{"id": 1}', encoding="utf-8")
    patch_path = tmp_path / "area_followup_patch.json"
    patch_path.write_text('{"status": "unresolved", "patch": {"建筑面积": 120.5}}', encoding="utf-8")

    result = area_followup_runner.apply_patch_file(patch_path, final_path=final_path)

    assert result == {"status": "skipped", "reason": "patch_not_resolved", "patch_path": str(patch_path)}
    assert json.loads(final_path.read_text(encoding="utf-8")) == {"id": 1}


def test_build_area_result_payload_maps_canonical_fields() -> None:
    patch_result = {
        "item_id": "456",
        "selected_candidate": {"source_type": "notice_detail", "evidence": "建筑面积：120.5平方米"},
        "patch": {
            "建筑面积": 120.5,
            "产权建筑面积": 120.5,
            "单价": 20000.0,
            "area_sqm": 120.5,
            "gross_area_sqm": 120.5,
            "unit_price": 20000.0,
            "property": {"area_sqm": 120.5, "gross_area_sqm": 120.5, "unit_price": 20000.0},
            "archive": {"notice_text_path": "notice.txt"},
            "legal_context": {"announcement_attachment_urls": ["https://example.com/notice"]},
        },
        "artifacts": {"notice_text_path": "html_archive/2026/2026-06-01/item-456.notice.txt"},
    }

    payload = area_followup_runner.build_area_result_payload(patch_result)

    assert payload["id"] == "456"
    assert payload["建筑面积"] == 120.5
    assert payload["产权建筑面积"] == 120.5
    assert payload["单价"] == 20000.0
    assert payload["property"]["area_sqm"] == 120.5
    assert payload["property"]["gross_area_sqm"] == 120.5
    assert payload["property"]["unit_price"] == 20000.0
    assert payload["source_type"] == "notice_detail"
    assert payload["evidence_source"] == "建筑面积：120.5平方米"
    assert payload["source"] == "area_followup_runner"
    assert payload["area_followup_patch_path"] == ""


def test_push_area_result_posts_json_payload_and_returns_response(tmp_path: Path) -> None:
    patch_result = {
        "item_id": "456",
        "selected_candidate": {"source_type": "notice_detail", "evidence": "建筑面积：120.5平方米"},
        "patch": {
            "建筑面积": 120.5,
            "产权建筑面积": 120.5,
            "单价": 20000.0,
            "property": {"area_sqm": 120.5, "gross_area_sqm": 120.5, "unit_price": 20000.0},
        },
    }

    calls: list[dict[str, object]] = []

    class FakeResponse:
        status_code = 200

        def json(self):
            return {"status": "ok"}

        def raise_for_status(self) -> None:
            return None

    class FakeSession:
        def post(self, url: str, *, json: dict[str, object], timeout: float):
            calls.append({"url": url, "json": json, "timeout": timeout})
            return FakeResponse()

    result = area_followup_runner.push_area_result(
        patch_result,
        api_url="http://127.0.0.1:8080/api/collection/details/area_result",
        session=FakeSession(),
    )

    assert result == {"status": "ok", "response": {"status": "ok"}}
    assert calls[0]["url"] == "http://127.0.0.1:8080/api/collection/details/area_result"
    payload = calls[0]["json"]
    assert payload["id"] == "456"
    assert payload["建筑面积"] == 120.5
    assert payload["产权建筑面积"] == 120.5
    assert payload["单价"] == 20000.0
    assert payload["source_type"] == "notice_detail"
    assert payload["source"] == "area_followup_runner"


def test_push_resolved_patches_writes_summary(tmp_path: Path) -> None:
    item_dir = tmp_path / "456"
    item_dir.mkdir()
    patch_path = item_dir / "area_followup_patch.json"
    patch_path.write_text(
        json.dumps(
            {
                "item_id": "456",
                "status": "resolved",
                "selected_candidate": {"source_type": "notice_detail", "evidence": "建筑面积：120.5平方米"},
                "patch": {
                    "建筑面积": 120.5,
                    "产权建筑面积": 120.5,
                    "单价": 20000.0,
                    "property": {"area_sqm": 120.5, "gross_area_sqm": 120.5, "unit_price": 20000.0},
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    calls: list[dict[str, object]] = []

    class FakeResponse:
        def json(self):
            return {"status": "ok"}

        def raise_for_status(self) -> None:
            return None

    class FakeSession:
        def post(self, url: str, *, json: dict[str, object], timeout: float):
            calls.append({"url": url, "json": json, "timeout": timeout})
            return FakeResponse()

    summary = area_followup_runner.push_resolved_patches(
        tmp_path,
        api_url="http://127.0.0.1:8080/api/collection/details/area_result",
        session=FakeSession(),
    )

    assert summary["pushed_count"] == 1
    assert summary["failed_count"] == 0
    assert (tmp_path / "area_followup_push_result.json").exists()
    assert calls[0]["json"]["id"] == "456"
    assert calls[0]["json"]["area_followup_patch_path"] == str(patch_path)


def test_decode_response_prefers_declared_charset_for_notice_pages() -> None:
    response = requests.Response()
    response.status_code = 200
    response.headers["Content-Type"] = "text/html; charset=gbk"
    response._content = "建筑面积：156.83平方米".encode("gbk")

    text = area_followup_runner.decode_response_text(response)

    assert "建筑面积：156.83平方米" in text


def test_resolve_job_fetches_notice_detail_pages_for_area(tmp_path: Path) -> None:
    item_dir = tmp_path / "789"
    item_dir.mkdir()
    detail_html = item_dir / "detail.html"
    detail_html.write_text("<html><body>公告详情加载中</body></html>", encoding="utf-8")
    final_json = item_dir / "final.json"
    final_json.write_text(
        json.dumps({"id": 789, "成交价格": 1568300, "property": {}, "auction": {"transaction_price": 1568300}}, ensure_ascii=False),
        encoding="utf-8",
    )
    job = {
        "item_id": "789",
        "transaction_price": 1568300,
        "detail_html_path": str(detail_html),
        "final_json_path": str(final_json),
        "source_url": "https://sf-item.taobao.com/sf_item/789.htm",
        "announcement_attachment_urls": [
            "https://sf.taobao.com/notice_detail/1685440.htm?outside_source=null&item_id=789",
        ],
    }

    class FakeResponse:
        status_code = 200
        url = "https://sf.taobao.com/notice_detail/1685440.htm?outside_source=null&item_id=789"
        headers = {"Content-Type": "text/html; charset=gbk"}
        content = (
            '<html><div class="notice-content">一、拍卖标的：房屋建筑面积：156.83平方米。</div></html>'
        ).encode("gbk")

        def raise_for_status(self) -> None:
            return None

    class FakeSession:
        def get(self, url: str, **kwargs):
            assert "notice_detail" in url
            return FakeResponse()

    result = area_followup_runner.resolve_job(job, artifact_root=tmp_path, write_patch=False, http_session=FakeSession())

    assert result["status"] == "resolved"
    assert result["selected_candidate"]["area_sqm"] == 156.83
    assert result["selected_candidate"]["source_type"] == "notice_detail"
    assert result["patch"]["建筑面积"] == 156.83
    assert result["patch"]["单价"] == 10000.0
    assert result["fetched_notice_count"] == 1


def test_resolve_job_fetches_notice_detail_urls_discovered_from_detail_html(tmp_path: Path) -> None:
    item_dir = tmp_path / "790"
    item_dir.mkdir()
    detail_html = item_dir / "detail.html"
    detail_html.write_text(
        '<html><body><a href="https://sf.taobao.com/notice_detail/1685441.htm?item_id=790">查看公告</a></body></html>',
        encoding="utf-8",
    )
    final_json = item_dir / "final.json"
    final_json.write_text(
        json.dumps({"id": 790, "成交价格": 888000, "property": {}, "auction": {"transaction_price": 888000}}, ensure_ascii=False),
        encoding="utf-8",
    )
    job = {
        "item_id": "790",
        "transaction_price": 888000,
        "detail_html_path": str(detail_html),
        "final_json_path": str(final_json),
        "source_url": "https://sf-item.taobao.com/sf_item/790.htm",
    }

    class FakeResponse:
        status_code = 200
        url = "https://sf.taobao.com/notice_detail/1685441.htm?item_id=790"
        headers = {"Content-Type": "text/html; charset=utf-8"}
        content = '<html><div class="notice-content">一、拍卖标的：建筑面积：88.8平方米。</div></html>'.encode("utf-8")

        def raise_for_status(self) -> None:
            return None

    class FakeSession:
        def get(self, url: str, **kwargs):
            assert "1685441" in url
            return FakeResponse()

    result = area_followup_runner.resolve_job(job, artifact_root=tmp_path, write_patch=False, http_session=FakeSession())

    assert result["status"] == "resolved"
    assert result["fetched_notice_count"] == 1
    assert result["selected_candidate"]["source_type"] == "notice_detail"
    assert result["patch"]["建筑面积"] == 88.8
    assert result["patch"]["单价"] == 10000.0
