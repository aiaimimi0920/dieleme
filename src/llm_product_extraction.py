from __future__ import annotations

import json


def build_product_extraction_prompt(content: str) -> str:
    return f"""
# Role
You archive product records from source evidence for the Crow collection engine.

# Rules
1. Return one JSON object only. Do not add Markdown or explanatory text.
2. Extract only facts explicitly supported by the input; never infer auction, property, legal, or geographic fields.
3. Keep useful source field names when no shared product name exists.
4. Use null only for an important field that is named but has no value; otherwise omit unsupported fields.
5. Preserve identifiers, titles, URLs, prices, inventory, timestamps, specifications, seller data, and category data when present.
6. Do not return credentials, cookies, access tokens, phone numbers, email addresses, or hidden form values.

# Source evidence
{content[:100000]}
""".strip()


def extract_product_data(content: str, item_id: str | None = None, *, model: str | None = None) -> str:
    """Extract a source-neutral product payload through the configured LLM backend."""

    filtered = filter_content(content or "")
    response = chat_with_glm(build_product_extraction_prompt(filtered), model=model) if model else chat_with_glm(
        build_product_extraction_prompt(filtered)
    )
    try:
        payload = json.loads(response)
    except json.JSONDecodeError as exc:
        raise ValueError("generic product extractor returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("generic product extractor must return a JSON object")
    if item_id is not None:
        payload.setdefault("id", str(item_id))
    return json.dumps(payload, ensure_ascii=False, indent=2)


__all__ = ["build_product_extraction_prompt", "extract_product_data"]
