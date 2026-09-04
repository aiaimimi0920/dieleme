"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.browserless_seed_probe_context import *


def redact_taobao_sensitive_text(value: str) -> str:
    redacted = value
    for pattern in _SENSITIVE_INLINE_PATTERNS:
        redacted = pattern.sub("taobao_security_value=<redacted>", redacted)
    return redacted


def normalize_seed_item_url(value: Any) -> str:
    url = str(value or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        url = f"https:{url}"
    try:
        parsed = urlsplit(url)
    except ValueError:
        return url
    if (parsed.hostname or "").lower() != "sf-item.taobao.com":
        return url
    path = parsed.path
    while "//" in path:
        path = path.replace("//", "/")
    return urlunsplit((parsed.scheme or "https", parsed.netloc, path, parsed.query, parsed.fragment))


__all__ = (
    "redact_taobao_sensitive_text",
    "normalize_seed_item_url",
)
