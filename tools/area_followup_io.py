"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.area_followup_context import *


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def decode_response_text(response: Any) -> str:
    content = bytes(getattr(response, "content", b"") or b"")
    content_type = str(getattr(response, "headers", {}).get("Content-Type", ""))
    declared = None
    match = re.search(r"charset=([A-Za-z0-9_\-]+)", content_type, re.I)
    if match:
        declared = match.group(1)
    encodings = [declared, getattr(response, "encoding", None), "utf-8", "gb18030", "gbk"]
    best_text = ""
    best_replacements = None
    for encoding in [enc for enc in encodings if enc]:
        try:
            text = content.decode(str(encoding), errors="replace")
        except LookupError:
            continue
        replacements = text.count("\ufffd")
        if best_replacements is None or replacements < best_replacements:
            best_text = text
            best_replacements = replacements
            if replacements == 0:
                break
    if best_text:
        return best_text
    return str(getattr(response, "text", "") or "")


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def has_positive_area(value: Any) -> bool:
    parsed = parse_area_sqm(value)
    return parsed is not None and parsed > 0


def _evidence_window(text: str, area: float) -> str:
    markers = ("房屋建筑面积", "不动产建筑面积", "产权建筑面积", "证载建筑面积", "建筑面积")
    best_index = -1
    for marker in markers:
        index = text.find(marker)
        if index >= 0:
            best_index = index
            break
    if best_index < 0:
        best_index = text.find(str(area))
    if best_index < 0:
        best_index = 0
    start = max(best_index - 40, 0)
    end = min(best_index + 140, len(text))
    return " ".join(text[start:end].split())


__all__ = (
    "load_json",
    "write_json",
    "decode_response_text",
    "as_dict",
    "deep_merge",
    "has_positive_area",
    "_evidence_window",
)
