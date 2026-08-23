from __future__ import annotations

import os
import shutil
import subprocess
import sys
from typing import Any

import pytest
import requests

from src import llm_helper


class _FakeResponse:
    status_code = 200
    text = '{"choices":[{"message":{"content":"```json\\n{\\"ok\\":true}\\n```"}}]}'

    @property
    def ok(self) -> bool:
        return True

    def json(self) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {
                        "content": "```json\n{\"ok\":true}\n```",
                    }
                }
            ]
        }

    def raise_for_status(self) -> None:
        return None


class _FakeUtf8Response:
    status_code = 200
    text = '{"choices":[{"message":{"content":"{\\"å¸\\u0082å\\u009cºè¯\\u0084ä¼\\u00b0ä»·\\":1,\\"æ\\u0098¯å\\u0090¦æ\\u0088\\u0090äº¤\\":true}"}}]}'
    content = (
        b'{"choices":[{"message":{"content":"{\\"'
        + "市场评估价".encode("utf-8")
        + b'\\":1,\\"'
        + "是否成交".encode("utf-8")
        + b'\\":true}"}}]}'
    )

    @property
    def ok(self) -> bool:
        return True

    def json(self) -> dict[str, Any]:
        return {
            "choices": [
                {
                    "message": {
                        "content": "{\"å¸\u0082å\u009cºè¯\u0084ä¼°ä»·\":1,\"æ\u0098¯å\u0090¦æ\u0088\u0090äº¤\":true}",
                    }
                }
            ]
        }

    def raise_for_status(self) -> None:
        return None


def test_chat_with_glm_uses_openai_compatible_backend_when_env_is_set(monkeypatch):
    calls: list[dict[str, Any]] = []

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: float):
            calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout, "trust_env": self.trust_env})
            return _FakeResponse()

    def fake_session_factory():
        return FakeSession()

    monkeypatch.setattr(llm_helper.requests, "Session", fake_session_factory)

    class BrokenAIService:
        def __init__(self, *args, **kwargs):
            raise AssertionError("legacy MaaS websocket backend should not be used")

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setattr(llm_helper, "AIService", BrokenAIService)

    result = llm_helper.chat_with_glm("return json")

    assert result == "{\"ok\":true}"
    assert len(calls) == 1
    assert calls[0]["url"] == "https://example.test/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert calls[0]["headers"]["Content-Type"] == "application/json"
    assert calls[0]["json"]["model"] == "test-model"
    assert calls[0]["json"]["messages"] == [{"role": "user", "content": "return json"}]
    assert calls[0]["json"]["temperature"] == 0
    assert calls[0]["trust_env"] is False


def test_chat_with_glm_forwards_valid_reasoning_effort(monkeypatch):
    calls: list[dict[str, Any]] = []

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def post(self, _url: str, *, json: dict[str, Any], **_kwargs):
            calls.append(json)
            return _FakeResponse()

    monkeypatch.setattr(llm_helper.requests, "Session", lambda: FakeSession())
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "LOW")

    result = llm_helper.chat_with_glm("return json")

    assert result == '{"ok":true}'
    assert calls[0]["reasoning_effort"] == "low"


def test_openai_compatible_config_rejects_invalid_reasoning_effort(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "fastest")

    with pytest.raises(ValueError, match="OPENAI_REASONING_EFFORT"):
        llm_helper._get_openai_compatible_config()


def test_chat_with_glm_applies_explicit_openai_compatible_proxy_without_trusting_env(monkeypatch):
    calls: list[dict[str, Any]] = []

    class FakeSession:
        def __init__(self):
            self.trust_env = True
            self.proxies: dict[str, str] = {}

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: float):
            calls.append({"url": url, "proxies": dict(self.proxies), "trust_env": self.trust_env})
            return _FakeResponse()

    monkeypatch.setattr(llm_helper.requests, "Session", lambda: FakeSession())
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("FAPAI_LLM_HTTP_PROXY", "http://llm-http.proxy:3128")
    monkeypatch.setenv("FAPAI_LLM_HTTPS_PROXY", "http://llm-https.proxy:3128")

    result = llm_helper.chat_with_glm("return json")

    assert result == "{\"ok\":true}"
    assert calls == [
        {
            "url": "https://example.test/v1/chat/completions",
            "proxies": {
                "http": "http://llm-http.proxy:3128",
                "https": "http://llm-https.proxy:3128",
            },
            "trust_env": False,
        }
    ]


def test_preflight_openai_compatible_backend_uses_same_proxy_controls(monkeypatch):
    calls: list[dict[str, Any]] = []

    class FakeResponse:
        status_code = 401
        text = '{"error":"auth required"}'

    class FakeSession:
        def __init__(self):
            self.trust_env = True
            self.proxies: dict[str, str] = {}

        def get(self, url: str, *, headers: dict[str, str], timeout: float):
            calls.append({"url": url, "headers": headers, "timeout": timeout, "proxies": dict(self.proxies), "trust_env": self.trust_env})
            return FakeResponse()

    monkeypatch.setattr(llm_helper.requests, "Session", lambda: FakeSession())
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("FAPAI_HTTPS_PROXY", "http://fapai-proxy.local:3128")

    result = llm_helper.preflight_openai_compatible_backend(timeout=7.5)

    assert result == {"enabled": True, "url": "https://example.test/v1/models", "status_code": 401}
    assert calls == [
        {
            "url": "https://example.test/v1/models",
            "headers": {"Authorization": "Bearer test-key"},
            "timeout": 7.5,
            "proxies": {"https": "http://fapai-proxy.local:3128"},
            "trust_env": False,
        }
    ]


def test_preflight_local_openai_compatible_backend_bypasses_generic_fapai_proxy(monkeypatch):
    calls: list[dict[str, Any]] = []

    class FakeResponse:
        status_code = 200
        text = '{"data":[]}'

    class FakeSession:
        def __init__(self):
            self.trust_env = True
            self.proxies: dict[str, str] = {}

        def get(self, url: str, *, headers: dict[str, str], timeout: float):
            calls.append({"url": url, "proxies": dict(self.proxies), "trust_env": self.trust_env})
            return FakeResponse()

    monkeypatch.setattr(llm_helper.requests, "Session", lambda: FakeSession())
    monkeypatch.setenv("OPENAI_BASE_URL", "http://host.docker.internal:8317/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("FAPAI_HTTP_PROXY", "http://collector-proxy.local:3128")
    monkeypatch.setenv("FAPAI_HTTPS_PROXY", "http://collector-proxy.local:3128")

    result = llm_helper.preflight_openai_compatible_backend(timeout=7.5)

    assert result == {"enabled": True, "url": "http://host.docker.internal:8317/v1/models", "status_code": 200}
    assert calls == [
        {
            "url": "http://host.docker.internal:8317/v1/models",
            "proxies": {},
            "trust_env": False,
        }
    ]


def test_preflight_openai_compatible_backend_can_probe_chat_completions(monkeypatch):
    calls: list[dict[str, Any]] = []

    class ModelsResponse:
        status_code = 200
        text = '{"data":[]}'

    class BusyChatResponse:
        status_code = 503
        text = '{"error":"busy"}'

    class FakeSession:
        def __init__(self):
            self.trust_env = True
            self.proxies: dict[str, str] = {}

        def get(self, url: str, *, headers: dict[str, str], timeout: float):
            calls.append({"method": "get", "url": url, "headers": headers, "timeout": timeout, "trust_env": self.trust_env})
            return ModelsResponse()

        def post(self, url: str, *, headers: dict[str, str], json: dict[str, Any], timeout: float):
            calls.append(
                {
                    "method": "post",
                    "url": url,
                    "headers": headers,
                    "json": json,
                    "timeout": timeout,
                    "trust_env": self.trust_env,
                }
            )
            return BusyChatResponse()

    monkeypatch.setattr(llm_helper.requests, "Session", lambda: FakeSession())
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")

    result = llm_helper.preflight_openai_compatible_backend(timeout=7.5, check_chat=True)

    assert result == {
        "enabled": True,
        "url": "https://example.test/v1/models",
        "status_code": 200,
        "chat_url": "https://example.test/v1/chat/completions",
        "chat_status_code": 503,
    }
    assert calls[0] == {
        "method": "get",
        "url": "https://example.test/v1/models",
        "headers": {"Authorization": "Bearer test-key"},
        "timeout": 7.5,
        "trust_env": False,
    }
    assert calls[1]["method"] == "post"
    assert calls[1]["url"] == "https://example.test/v1/chat/completions"
    assert calls[1]["headers"] == {
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json",
    }
    assert calls[1]["json"]["model"] == "test-model"
    assert calls[1]["json"]["messages"] == [
        {
            "role": "user",
            "content": '这是法拍房分析服务连通性检查。请仅返回 JSON：{"ok":true}',
        }
    ]
    assert calls[1]["json"]["temperature"] == 0
    assert calls[1]["json"]["max_tokens"] == 32
    assert calls[1]["timeout"] == 7.5
    assert calls[1]["trust_env"] is False


def test_llm_helper_import_allows_openai_env_without_secrets_json(tmp_path):
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "__init__.py").write_text("", encoding="utf-8")
    shutil.copy2(llm_helper.__file__, src_dir / "llm_helper.py")

    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(tmp_path),
            "OPENAI_BASE_URL": "https://example.test/v1",
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL": "test-model",
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src import llm_helper; "
            "assert llm_helper.MODEL_POOL == []; "
            "assert llm_helper.APP_ID == ''; "
            "assert llm_helper.MODEL_ID == ''; "
            "print('import-ok')",
        ],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr + result.stdout
    assert "import-ok" in result.stdout
    assert "secrets.json not found" not in result.stdout


def test_chat_with_glm_decodes_openai_compatible_utf8_even_without_charset(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def post(self, *args, **kwargs):
            return _FakeUtf8Response()

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setattr(llm_helper.requests, "Session", lambda: FakeSession())

    result = llm_helper.chat_with_glm("return json")

    assert result == "{\"市场评估价\":1,\"是否成交\":true}"


def test_chat_with_glm_retries_transient_openai_compatible_503(monkeypatch):
    calls: list[int] = []

    class RetryableResponse:
        status_code = 503
        content = b'{"error":"busy"}'
        text = '{"error":"busy"}'

        def raise_for_status(self) -> None:
            raise requests.HTTPError("503 Server Error", response=self)

    class SuccessfulResponse(_FakeResponse):
        content = _FakeResponse.text.encode("utf-8")

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def post(self, *args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                return RetryableResponse()
            return SuccessfulResponse()

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "2")
    monkeypatch.setattr(llm_helper.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(llm_helper.requests, "Session", lambda: FakeSession())

    result = llm_helper.chat_with_glm("return json")

    assert result == "{\"ok\":true}"
    assert len(calls) == 2


def test_chat_with_glm_retries_transient_openai_compatible_524(monkeypatch):
    calls: list[int] = []

    class RetryableResponse:
        status_code = 524
        content = b'{"error":"timeout"}'
        text = '{"error":"timeout"}'

        def raise_for_status(self) -> None:
            raise requests.HTTPError("524 Server Error", response=self)

    class SuccessfulResponse(_FakeResponse):
        content = _FakeResponse.text.encode("utf-8")

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def post(self, *args, **kwargs):
            calls.append(1)
            if len(calls) == 1:
                return RetryableResponse()
            return SuccessfulResponse()

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "2")
    monkeypatch.setattr(llm_helper.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(llm_helper.requests, "Session", lambda: FakeSession())

    result = llm_helper.chat_with_glm("return json")

    assert result == "{\"ok\":true}"
    assert len(calls) == 2


def test_chat_with_glm_falls_back_across_openai_model_candidates(monkeypatch):
    calls: list[str] = []

    class UnavailableResponse:
        status_code = 503
        content = b'{"error":{"code":"model_not_found"}}'
        text = content.decode("utf-8")

        def raise_for_status(self) -> None:
            raise requests.HTTPError("503 Server Error", response=self)

    class SuccessfulResponse(_FakeResponse):
        content = _FakeResponse.text.encode("utf-8")

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def post(self, _url: str, *, json: dict[str, Any], **_kwargs):
            calls.append(json["model"])
            return UnavailableResponse() if json["model"] == "primary-model" else SuccessfulResponse()

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "primary-model")
    monkeypatch.setenv("OPENAI_MODEL_CANDIDATES", "primary-model;fallback-model")
    monkeypatch.setattr(llm_helper.requests, "Session", lambda: FakeSession())

    result = llm_helper.chat_with_glm("return json")

    assert result == '{"ok":true}'
    assert calls == ["primary-model", "fallback-model"]


def test_chat_with_glm_does_not_hide_openai_candidate_auth_failure(monkeypatch):
    calls: list[str] = []

    class UnauthorizedResponse:
        status_code = 401
        content = b'{"error":"unauthorized"}'
        text = content.decode("utf-8")

        def raise_for_status(self) -> None:
            raise requests.HTTPError("401 Client Error", response=self)

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def post(self, _url: str, *, json: dict[str, Any], **_kwargs):
            calls.append(json["model"])
            return UnauthorizedResponse()

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "bad-key")
    monkeypatch.setenv("OPENAI_MODEL", "primary-model")
    monkeypatch.setenv("OPENAI_MODEL_CANDIDATES", "fallback-model")
    monkeypatch.setattr(llm_helper.requests, "Session", lambda: FakeSession())

    with pytest.raises(requests.HTTPError):
        llm_helper.chat_with_glm("return json")

    assert calls == ["primary-model"]


def test_preflight_openai_compatible_backend_falls_back_across_model_candidates(monkeypatch):
    calls: list[str] = []

    class ModelsResponse:
        status_code = 200

    class ChatResponse:
        def __init__(self, status_code: int):
            self.status_code = status_code

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def get(self, *_args, **_kwargs):
            return ModelsResponse()

        def post(self, _url: str, *, json: dict[str, Any], **_kwargs):
            calls.append(json["model"])
            return ChatResponse(503 if json["model"] == "primary-model" else 200)

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "primary-model")
    monkeypatch.setenv("OPENAI_MODEL_CANDIDATES", "fallback-model")
    monkeypatch.setattr(llm_helper.requests, "Session", lambda: FakeSession())

    result = llm_helper.preflight_openai_compatible_backend(timeout=7.5, check_chat=True)

    assert result["status_code"] == 200
    assert result["chat_status_code"] == 200
    assert result["chat_model_name"] == "fallback-model"
    assert calls == ["primary-model", "fallback-model"]


def test_preflight_openai_compatible_backend_reports_network_unavailable_without_raising(monkeypatch):
    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def get(self, *_args, **_kwargs):
            raise requests.ConnectTimeout("provider unavailable")

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setattr(llm_helper.requests, "Session", lambda: FakeSession())

    result = llm_helper.preflight_openai_compatible_backend(timeout=1.0, check_chat=True)

    assert result["enabled"] is True
    assert result["status_code"] == 0
    assert result["error_type"] == "ConnectTimeout"


def test_chat_with_glm_does_not_retry_non_transient_openai_compatible_400(monkeypatch):
    calls: list[int] = []

    class BadRequestResponse:
        status_code = 400
        content = b'{"error":"bad request"}'
        text = '{"error":"bad request"}'

        def raise_for_status(self) -> None:
            raise requests.HTTPError("400 Client Error", response=self)

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def post(self, *args, **kwargs):
            calls.append(1)
            return BadRequestResponse()

    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "3")
    monkeypatch.setattr(llm_helper.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(llm_helper.requests, "Session", lambda: FakeSession())

    with pytest.raises(requests.HTTPError):
        llm_helper.chat_with_glm("return json")

    assert len(calls) == 1


def test_avm_risk_prompt_asks_for_stable_reusable_location_index_name():
    prompt = llm_helper.build_avm_risk_prompt("北京市朝阳区八里庄远洋天地小区7号楼1单元101室")

    assert "稳定位置索引名" in prompt
    assert "后续可复用" in prompt
    assert "不要求官方名称" in prompt
    assert "楼号、单元号、房号" in prompt


def test_extract_auction_data_prompt_asks_for_stable_reusable_location_index_name(monkeypatch):
    captured: dict[str, str] = {}

    def fake_chat_with_glm(prompt: str) -> str:
        captured["prompt"] = prompt
        return "{}"

    monkeypatch.setattr(llm_helper, "chat_with_glm", fake_chat_with_glm)

    llm_helper.extract_auction_data(
        """
        <html>
          <head><title>北京市朝阳区八里庄远洋天地小区7号楼101室</title></head>
          <body><div class="item-address">北京市朝阳区八里庄远洋天地小区7号楼101室</div></body>
        </html>
        """,
        item_id="prompt-contract",
    )

    prompt = captured["prompt"]
    assert "稳定位置索引名" in prompt
    assert "后续归并、索引同片房源" in prompt
    assert "不要求它是官方名称" in prompt
    assert "不要输出城市、区县、道路门牌号、楼号、单元号、房号" in prompt


def test_extract_avm_risk_features_normalizes_list_evidence_source(monkeypatch):
    payload = {key: None for key in llm_helper.AVM_RISK_KEYS}
    payload.update(
        {
            "community_name": "朝阳门内大街288号院",
            "land_right_type": "未知",
            "floor_level": "中区",
            "orientation": "未知",
            "tax_burden": "未知",
            "housing_type": "住宅",
            "extraction_confidence": 0.8,
            "evidence_span": ["页面标题"],
            "evidence_source": ["页面主文", "公告"],
            "extraction_version": "avm_risk_v2",
        }
    )

    monkeypatch.setattr(llm_helper, "chat_with_glm", lambda _prompt: llm_helper.json.dumps(payload, ensure_ascii=False))

    features = llm_helper.extract_avm_risk_features("北京市东城区朝阳门内大街288号院3号楼", item_id="risk-list-source")

    assert features is not None
    assert features["evidence_source"] == "页面主文"


def test_extract_area_from_text_prefers_building_area_over_land_area():
    text = "标的物宗地面积为300.00㎡，房屋建筑面积为120.50㎡，用途为住宅。"

    assert llm_helper.extract_area_from_text(text) == 120.5


def test_fetch_description_data_text_decodes_gbk_description(monkeypatch):
    desc_html = "拍卖对象为北京市东城区测试房产，面积为88.88㎡。"
    html = """
    <html>
      <body>
        <script id="description-data" type="text/json">
          {&quot;link&quot;:&quot;https://itemcdn.tmall.com/desc/icoss!gbk!1&quot;}
        </script>
      </body>
    </html>
    """

    class FakeResponse:
        content = desc_html.encode("gb18030")
        text = ""

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def get(self, url: str, *, headers: dict[str, str], timeout: float):
            assert self.trust_env is False
            return FakeResponse()

    monkeypatch.setattr(llm_helper.requests, "Session", lambda: FakeSession())

    text = llm_helper.fetch_description_data_text(html)

    assert "面积为88.88㎡" in text
    assert llm_helper.extract_area_from_text(text) == 88.88


def test_extract_auction_data_backfills_area_from_description_data_link(monkeypatch):
    desc_html = (
        "<table><tr><td>拍品介绍</td><td>"
        "拍卖对象为北京市东城区朝阳门内大街288号院3号楼1单元1502号房产，面积为117.06㎡。"
        "</td></tr></table>"
    )
    html = """
    <html>
      <head><title>北京市东城区朝阳门内大街288号院3号楼1单元1502号房产</title></head>
      <body>
        <script id="description-data" type="text/json">
          {&quot;link&quot;:&quot;https://itemcdn.tmall.com/desc/icoss!0747988656830!11064941259?var=desc?var=desc&quot;}
        </script>
        <div id="J_desc">标的物详情加载中......</div>
      </body>
    </html>
    """

    captured: dict[str, str] = {}

    def fake_chat_with_glm(prompt: str) -> str:
        captured["prompt"] = prompt
        return llm_helper.json.dumps(
            {
                "id": 747988656830,
                "市场评估价": 9001680,
                "起拍价格": 13554680,
                "成交价格": 13554680,
                "标题": "北京市东城区朝阳门内大街288号院3号楼1单元1502号房产",
                "是否成交": True,
                "完整地址": "北京市东城区朝阳门内大街288号院3号楼1单元1502号房产",
                "所属小区": "朝阳门内大街288号院",
                "城市": "北京市",
                "区": "东城区",
                "建筑面积": None,
                "单价": 0,
                "is_processed": True,
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(llm_helper, "chat_with_glm", fake_chat_with_glm)

    class FakeResponse:
        content = desc_html.encode("utf-8")
        text = desc_html

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.trust_env = True
            self.urls: list[str] = []

        def get(self, url: str, *, headers: dict[str, str], timeout: float):
            self.urls.append(url)
            assert self.trust_env is False
            assert "itemcdn.tmall.com/desc/" in url
            return FakeResponse()

    fake_session = FakeSession()
    monkeypatch.setattr(llm_helper.requests, "Session", lambda: fake_session)

    result = llm_helper.json.loads(llm_helper.extract_auction_data(html, item_id="747988656830"))

    assert result["建筑面积"] == 117.06
    assert result["产权建筑面积"] == 117.06
    assert result["单价"] == round(13554680 / 117.06, 2)
    assert "异步标的物描述" in captured["prompt"]
    assert "面积为117.06㎡" in captured["prompt"]


def test_extract_auction_data_uses_description_area_as_gross_area_for_fractional_share(monkeypatch):
    desc_html = "拍卖标的为某房产二分之一产权，房屋建筑面积为120.00㎡。"
    html = """
    <html>
      <head><title>北京市朝阳区测试小区1号楼101室二分之一产权</title></head>
      <body>
        <script id="description-data" type="text/json">
          {&quot;link&quot;:&quot;https://itemcdn.tmall.com/desc/icoss!fractional!1&quot;}
        </script>
      </body>
    </html>
    """

    monkeypatch.setattr(
        llm_helper,
        "chat_with_glm",
        lambda _prompt: llm_helper.json.dumps(
            {
                "id": 1,
                "成交价格": 6000000,
                "完整地址": "北京市朝阳区测试小区1号楼101室",
                "所属小区": "测试小区",
                "建筑面积": None,
                "产权建筑面积": None,
                "产权份额比例": 0.5,
                "单价": 0,
                "is_processed": True,
            },
            ensure_ascii=False,
        ),
    )

    class FakeResponse:
        content = desc_html.encode("utf-8")
        text = desc_html

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self):
            self.trust_env = True

        def get(self, url: str, *, headers: dict[str, str], timeout: float):
            assert self.trust_env is False
            return FakeResponse()

    monkeypatch.setattr(llm_helper.requests, "Session", lambda: FakeSession())

    result = llm_helper.json.loads(llm_helper.extract_auction_data(html, item_id="fractional"))

    assert result["产权建筑面积"] == 120.0
    assert result["建筑面积"] == 60.0
    assert result["单价"] == 100000.0
