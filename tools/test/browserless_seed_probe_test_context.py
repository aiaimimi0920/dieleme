from __future__ import annotations

import json

import builtins

import importlib.util

from datetime import datetime

from pathlib import Path

import pytest

from tools import browserless_seed_probe

LIVE_LIKE_LIST_HTML = """
<!DOCTYPE html>
<html>
<head><title>住宅用房拍卖</title></head>
<body>
  <div class="site-nav">淘宝网首页 登录 帮助中心</div>
  <script id="sf-item-list-data" type="application/json">
    {
      "data": [
        {
          "id": 747988656830,
          "itemUrl": "//sf-item.taobao.com/sf_item/747988656830.htm?track_id=demo-1"
        },
        {
          "id": 660720568820,
          "itemUrl": "//sf-item.taobao.com/sf_item/660720568820.htm?track_id=demo-2"
        }
      ]
    }
  </script>
</body>
</html>
""".strip()

RAW_LIST_PAYLOAD = {
    "data": [
        {
            "id": 747988656830,
            "title": "测试法拍房 A",
            "currentPrice": 1234567,
            "initialPrice": 1000000,
            "end": "2026-05-18 10:00:00",
            "startTime": "2026-05-17 10:00:00",
            "itemUrl": "//sf-item.taobao.com/sf_item/747988656830.htm?track_id=demo-1",
            "status": "done",
            "bidCount": 2,
            "bidUserNumber": 1,
            "applyCount": 1,
            "watchCount": 10,
            "remindCount": 5,
            "viewCount": 30,
            "itemAddress": "浙江省杭州市西湖区测试小区 1 幢 2 单元 301 室",
            "district": "西湖区",
            "city": "杭州市",
            "latitude": 30.27,
            "longitude": 120.15,
            "auctionRound": "一拍",
            "housingType": "住宅",
            "deposit": 100000,
        },
        {
            "id": 111111111111,
            "title": "未成交测试",
            "itemUrl": "//sf-item.taobao.com/sf_item/111111111111.htm",
            "status": "todo",
            "bidCount": 0,
        },
    ]
}

LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head><title>登录</title></head>
<body>
  <div>扫码登录</div>
  <div>账户登录</div>
</body>
</html>
""".strip()

PUNISH_HTML = """
<script>
sessionStorage.x5referer = window.location.href;
var url = window.location.protocol + "//sf.taobao.com//list/50025969__2.htm/_____tmd_____/punish?x5secdata=demo";
</script>
""".strip()

class _FakeResponse:
    def __init__(self, *, status_code: int, url: str, text: str):
        self.status_code = status_code
        self.url = url
        self.text = text

class _FakeSession:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, headers: dict[str, str], timeout: int, allow_redirects: bool):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "timeout": timeout,
                "allow_redirects": allow_redirects,
            }
        )
        return self.response


__all__ = [name for name in globals() if not name.startswith("__")]
