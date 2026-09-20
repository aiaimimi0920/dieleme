"""Synthetic observer fixtures. Never reads production data."""

from copy import deepcopy

OVERVIEW = {
    "runtime_state": "运行中",
    "modules": {
        "links": {"total": 12840, "unique_items": 3200},
        "details": {"captured": 1260, "pending": 1940, "failed": 12, "blocked": 3},
        "analysis": {"finalized": 730, "pending": 530, "failed": 8, "blocked": 2},
    },
    "challenge_metrics": {
        "recent_challenge_hit_rate": 0.08,
        "current_challenge_hit_rate": 0.04,
        "recent_runs": 20,
        "recent_challenge_detected_count": 8,
        "recent_browserless_attempt_count": 100,
        "current_challenge_detected_count": 2,
        "current_browserless_attempt_count": 50,
        "recent_top_fallback_reason": "等待人工认证",
    },
    "auth_watcher": {
        "available": True,
        "status": "completed",
        "poll_seconds": 60,
        "max_wait_seconds": 1200,
        "wait_elapsed_seconds": 120,
    },
}

REGIONS = [
    {"province": "浙江省", "city": "杭州市", "district": "西湖区", "location_code": "330106", "completed": True, "status_label": "收集完成"},
    {"province": "浙江省", "city": "杭州市", "district": "上城区", "location_code": "330102", "completed": False, "status_label": "采集中"},
    {"province": "江苏省", "city": "南京市", "district": "鼓楼区", "location_code": "320106", "completed": False, "status_label": "存在阻塞"},
    {"province": "广东省", "city": "深圳市", "district": "南山区", "location_code": "440305", "completed": False, "status_label": "采集中"},
]


def overview(runtime, *, challenge=True, restart=None):
    result = deepcopy(OVERVIEW)
    result["runtime_state"] = runtime
    result["status"] = {"operator_paused": runtime == "暂停中", "paused": runtime == "暂停中", "captcha_solver": {
        "manual_required": challenge, "scopes": {"detail": {"manual_required": challenge}},
    }}
    result["engine_restart"] = restart or {"available": True, "request": None}
    return result


def item_list(stage, limit, offset, empty=False):
    total = 0 if empty else 12
    items = []
    for index in range(offset, min(offset + limit, total)):
        item_id = str(9900000000000 + index)
        item = {
            "item_id": item_id,
            "source_url": f"https://example.invalid/fixture/{item_id}",
            "source_payload": {"city": "杭州市", "district": "西湖区"},
            "artifacts": {},
            "status": {"links": "pending_detail", "details": "raw_detail_captured", "analysis": "detail_completed"}[stage],
        }
        if stage != "links":
            item["artifacts"]["detail_html_path"] = "fixture/detail.html"
        if stage == "analysis":
            item["final_json_path"] = "fixture/final.json"
        items.append(item)
    return {"total": total, "items": items}


def item_detail(item_id, updates):
    record = {
        "item_id": item_id,
        "title": "离线测试房产（非生产数据）",
        "full_address": "浙江省杭州市西湖区离线测试路 100 号，长地址展示测试。" * 4,
        "transaction_price": 1800000,
        "area_sqm": 98.5,
        "has_elevator": True,
        **updates.get(item_id, {}),
    }
    return {
        "item": {"source_payload": {"_analysis_attempt_count": 2}},
        "flat_item": record,
        "artifacts": {
            "detail_html": {"path": "fixture/detail.html", "content": "离线采集原文（非生产数据）\n" * 150},
            "final_json": {"path": "fixture/final.json", "json": record},
        },
    }
