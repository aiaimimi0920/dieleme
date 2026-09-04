from __future__ import annotations

import json

from pathlib import Path

import requests

from src import llm_helper

from tools import live_batch_smoke

def _write_raw_item(tmp_path: Path, item_id: str = "module-b-1") -> tuple[Path, dict, str]:
    item_dir = tmp_path / item_id
    item_dir.mkdir()
    seed = {
        "id": item_id,
        "title": "北京市东城区测试小区1号房",
        "url": f"https://sf-item.taobao.com/sf_item/{item_id}.htm",
        "currentPrice": 1_000_000,
        "initialPrice": 800_000,
        "auction_date": "2026-09-01 10:00:00",
        "status": "done",
    }
    html = """
    <html><body>
      <input id="J_StartPrice" value="800000" />
      <div id="itemAddress">北京市 东城区</div>
      <div id="itemAddressDetail">测试小区1号房</div>
      成交价格1000000元，起拍价格800000元，建筑面积80平方米。
    </body></html>
    """
    live_batch_smoke.write_json(item_dir / "seed.json", seed)
    (item_dir / "detail.html").write_text(html, encoding="utf-8")
    live_batch_smoke.write_json(
        item_dir / "description-data.json",
        {"area_sqm": 80, "text_len": 10, "has_area_marker": True},
    )
    live_batch_smoke.write_json(
        item_dir / "selected.json",
        {
            "fetch": {
                "method": "raw_artifact",
                "detail_final_url": seed["url"],
                "detail_html_bytes": len(html.encode("utf-8")),
            },
            "trusted_seed": seed,
        },
    )
    return item_dir, seed, html


__all__ = [name for name in globals() if not name.startswith("__")]
