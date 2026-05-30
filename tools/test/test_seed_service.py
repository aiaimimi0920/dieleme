from __future__ import annotations

import json
from pathlib import Path

from src.collection.seed_service import SeedCollectionService


def test_submit_batch_writes_new_seed_file_for_new_items(tmp_path: Path):
    data_root = tmp_path / "datas"
    data_root.mkdir()
    target_file = data_root / "2026-05-18.json"

    seen_ids: dict[str, dict[str, object]] = {}
    pending_tasks: list[str] = []
    persisted: list[tuple[dict[str, object], str, dict[str, object] | None]] = []

    service = SeedCollectionService(repository=None, jobs_dir=None, data_root=str(data_root))
    result = service.submit_batch(
        {
            "items": [
                {
                    "id": "123456",
                    "title": "测试法拍房",
                    "currentPrice": 1234567,
                    "initialPrice": 1000000,
                    "auction_date": "2026-05-18 10:00:00",
                    "auction_start_time": "2026-05-17 10:00:00",
                    "url": "https://sf-item.taobao.com/sf_item/123456.htm",
                    "status": "done",
                    "bidCount": 2,
                    "bidderCount": 1,
                    "applyCount": 1,
                    "watchCount": 10,
                    "remindCount": 5,
                    "viewCount": 30,
                    "location": "浙江省杭州市西湖区测试小区 1 幢 2 单元 301 室",
                    "full_address": "浙江省杭州市西湖区测试小区 1 幢 2 单元 301 室",
                    "district": "西湖区",
                    "city": "杭州市",
                    "latitude": 30.27,
                    "longitude": 120.15,
                    "coordinate_source": "list",
                    "auction_round": "一拍",
                    "housing_type": "住宅",
                    "deposit": 100000,
                    "is_processed": False,
                }
            ],
            "raw_payload": [{"id": "123456"}],
            "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
        },
        parse_price=lambda value: value,
        safe_int=lambda value: value,
        prefer_db_task_reads=lambda: False,
        get_seen_entry=lambda item_id: seen_ids.get(item_id),
        get_flat_item=lambda item_id: None,
        get_data_path=lambda date_str: str(target_file),
        update_file_global=lambda *_args, **_kwargs: None,
        persist_item_to_db=lambda item, event_type, event_payload=None: persisted.append((item, event_type, event_payload)),
        evict_runtime_item=lambda item_id: None,
        seen_ids=seen_ids,
        pending_tasks=pending_tasks,
        archive_list_payload=lambda *_args, **_kwargs: None,
    )

    assert result == {"status": "ok", "new": 1}
    assert target_file.exists()
    payload = json.loads(target_file.read_text(encoding="utf-8"))
    assert len(payload) == 1
    assert payload[0]["id"] == "123456"
