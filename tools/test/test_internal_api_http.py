from __future__ import annotations

from tools import internal_api_http


def test_fetch_json_ignores_proxy_env(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, object]:
            return {"ok": True}

    class _Session:
        def __init__(self) -> None:
            self.trust_env = True
            self.proxies: dict[str, object] = {}

        def __enter__(self) -> "_Session":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def get(self, url: str, *, timeout: float):
            calls.append(
                {
                    "url": url,
                    "timeout": timeout,
                    "trust_env": self.trust_env,
                    "proxies": dict(self.proxies),
                }
            )
            return _Response()

    monkeypatch.setattr(internal_api_http.requests, "Session", _Session)

    payload = internal_api_http.fetch_json("http://192.168.15.200:8001/api/status", timeout=5)

    assert payload == {"ok": True}
    assert calls == [
        {
            "url": "http://192.168.15.200:8001/api/status",
            "timeout": 5,
            "trust_env": False,
            "proxies": {"http": None, "https": None},
        }
    ]


def test_post_json_ignores_proxy_env(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    class _Response:
        def raise_for_status(self) -> None:
            return None

        @staticmethod
        def json() -> dict[str, object]:
            return {"status": "queued"}

    class _Session:
        def __init__(self) -> None:
            self.trust_env = True
            self.proxies: dict[str, object] = {}

        def __enter__(self) -> "_Session":
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, url: str, *, json: dict[str, object], timeout: float):
            calls.append(
                {
                    "url": url,
                    "json": dict(json),
                    "timeout": timeout,
                    "trust_env": self.trust_env,
                    "proxies": dict(self.proxies),
                }
            )
            return _Response()

    monkeypatch.setattr(internal_api_http.requests, "Session", _Session)

    payload = internal_api_http.post_json(
        "http://192.168.15.200:8001/api/report_captcha",
        {"url": "https://sf.taobao.com/list/page"},
        timeout=10,
    )

    assert payload == {"status": "queued"}
    assert calls == [
        {
            "url": "http://192.168.15.200:8001/api/report_captcha",
            "json": {"url": "https://sf.taobao.com/list/page"},
            "timeout": 10,
            "trust_env": False,
            "proxies": {"http": None, "https": None},
        }
    ]
