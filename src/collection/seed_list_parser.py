from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Mapping, Protocol
from urllib.parse import urljoin, urlsplit


Record = dict[str, Any]


@dataclass(frozen=True)
class SeedListParseResult:
    items: tuple[Record, ...]
    summary: Record
    has_challenge: bool = False


class SeedListParser(Protocol):
    def parse(self, html: str, *, final_url: str) -> SeedListParseResult: ...


@dataclass(frozen=True)
class TaobaoSeedListParser:
    """Adapter around the retained Taobao browser-probe contract."""

    probe: Any

    def parse(self, html: str, *, final_url: str) -> SeedListParseResult:
        summary = self.probe.summarize_list_page(html, final_url=final_url)
        if not isinstance(summary, dict):
            summary = {}
        payload = self.probe.extract_list_payload(html)
        if payload is None:
            challenged = bool(
                summary.get("body_has_challenge")
                or summary.get("body_has_login")
                or summary.get("body_has_punish")
            )
            return SeedListParseResult((), summary, challenged)
        batch = self.probe.build_userscript_like_batch_payload(
            payload,
            source_page_url=final_url,
        )
        items = tuple(
            dict(item)
            for item in (batch.get("items") or [])
            if isinstance(item, dict)
        )
        return SeedListParseResult(items, summary)


class _JsonScriptCollector(HTMLParser):
    _JSON_TYPES = {"application/json", "application/ld+json"}
    _JSON_IDS = {"__next_data__", "__nuxt_data__"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._capturing = False
        self._parts: list[str] = []
        self.scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.casefold() != "script":
            return
        values = {key.casefold(): str(value or "") for key, value in attrs}
        self._capturing = (
            values.get("type", "").casefold() in self._JSON_TYPES
            or values.get("id", "").casefold() in self._JSON_IDS
        )
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capturing:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "script" and self._capturing:
            self.scripts.append("".join(self._parts).strip())
            self._capturing = False
            self._parts = []


_CONTAINER_KEYS = ("items", "products", "results", "list", "data", "@graph")
_ID_KEYS = ("source_item_id", "id", "item_id", "sku", "product_id", "@id")
_URL_KEYS = ("source_url", "url", "itemUrl", "detail_url")
_TITLE_KEYS = ("source_title", "title", "name")


def _first_text(item: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _is_item_candidate(item: Mapping[str, Any]) -> bool:
    raw_url = _first_text(item, _URL_KEYS)
    if not raw_url:
        return False
    try:
        scheme = urlsplit(raw_url).scheme.casefold()
    except ValueError:
        return False
    return scheme in {"", "http", "https"}


def _find_items(value: Any, depth: int = 0) -> list[Mapping[str, Any]]:
    if depth > 4:
        return []
    if isinstance(value, list):
        direct_items = [
            item for item in value if isinstance(item, Mapping) and _is_item_candidate(item)
        ]
        if direct_items:
            return direct_items
        nested_items: list[Mapping[str, Any]] = []
        for item in value:
            if isinstance(item, Mapping):
                nested_items.extend(_find_items(item, depth + 1))
        return nested_items
    if not isinstance(value, Mapping):
        return []
    for key in _CONTAINER_KEYS:
        if key not in value:
            continue
        items = _find_items(value[key], depth + 1)
        if items:
            return items
    if _is_item_candidate(value):
        return [value]
    return []


def normalize_source_item_id(raw_id: str, source_url: str = "") -> str:
    value = raw_id or f"url:{hashlib.sha256(source_url.encode('utf-8')).hexdigest()[:40]}"
    if len(value) <= 64:
        return value
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()[:56]}"


def _normalize_item(item: Mapping[str, Any], final_url: str) -> Record | None:
    raw_url = _first_text(item, _URL_KEYS)
    if not raw_url:
        return None
    source_url = urljoin(final_url, raw_url)
    parsed = urlsplit(source_url)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        return None
    raw_id = _first_text(item, _ID_KEYS)
    source_id = normalize_source_item_id(raw_id, source_url)
    normalized = {str(key): value for key, value in item.items()}
    if raw_id and raw_id != source_id:
        normalized["raw_source_item_id"] = raw_id
    normalized.update(
        {
            "id": source_id,
            "source_item_id": source_id,
            "url": source_url,
            "source_url": source_url,
        }
    )
    title = _first_text(item, _TITLE_KEYS)
    if title:
        normalized.setdefault("title", title)
        normalized.setdefault("source_title", title)
    return normalized


def _json_payloads(html: str) -> list[Any]:
    text = str(html or "").strip()
    candidates: list[str] = []
    if text.startswith(("{", "[")):
        candidates.append(text)
    collector = _JsonScriptCollector()
    collector.feed(text)
    candidates.extend(candidate for candidate in collector.scripts if candidate)
    payloads: list[Any] = []
    for candidate in candidates:
        try:
            payloads.append(json.loads(candidate))
        except (TypeError, ValueError):
            continue
    return payloads


@dataclass(frozen=True)
class GenericJsonSeedListParser:
    """Parse source-neutral JSON or embedded JSON product listings."""

    def parse(self, html: str, *, final_url: str) -> SeedListParseResult:
        payloads = _json_payloads(html)
        raw_items: list[Mapping[str, Any]] = []
        for payload in payloads:
            raw_items = _find_items(payload)
            if raw_items:
                break
        items = tuple(
            normalized
            for item in raw_items
            if (normalized := _normalize_item(item, final_url)) is not None
        )
        text = str(html or "")
        lowered = text.casefold()
        lowered_url = str(final_url or "").casefold()
        has_login = any(marker in lowered_url for marker in ("/login", "/signin"))
        has_login = has_login or any(marker in lowered for marker in ("登录", "sign in", "log in"))
        has_captcha = any(
            marker in lowered
            for marker in ("captcha", "验证码", "人机验证", "access denied")
        )
        has_punish = "/punish" in lowered_url
        challenged = has_login or has_captcha or has_punish
        summary: Record = {
            "has_script": bool(payloads),
            "item_count": len(raw_items) if payloads else None,
            "parsed_item_count": len(items),
            "rejected_item_count": max(len(raw_items) - len(items), 0),
            "first_ids": [item.get("source_item_id") for item in items[:5]],
            "first_urls": [item.get("source_url") for item in items[:5]],
            "body_has_login": has_login,
            "body_has_captcha": has_captcha,
            "body_has_punish": has_punish,
            "body_has_challenge": challenged,
            "body_snippet": "",
        }
        return SeedListParseResult(items, summary, challenged)


__all__ = (
    "GenericJsonSeedListParser",
    "normalize_source_item_id",
    "SeedListParseResult",
    "SeedListParser",
    "TaobaoSeedListParser",
)
