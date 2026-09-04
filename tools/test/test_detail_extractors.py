from __future__ import annotations

import pytest

from src.collection.detail_extractors import CallableDetailExtractor, resolve_detail_extractor


def test_callable_detail_extractor_forwards_item_id() -> None:
    calls: list[tuple[str, str | None]] = []
    extractor = CallableDetailExtractor(
        lambda content, item_id=None: calls.append((content, item_id)) or "{}"
    )

    assert extractor.extract("page", item_id="sku-7") == "{}"
    assert calls == [("page", "sku-7")]


def test_resolve_detail_extractor_wraps_legacy_callable() -> None:
    extractor = resolve_detail_extractor(
        detail_extractor=None,
        legacy_extract_auction_data=lambda _content, item_id=None: f'{{"id":"{item_id}"}}',
    )

    assert extractor.extract("page", item_id="legacy-7") == '{"id":"legacy-7"}'


def test_resolve_detail_extractor_rejects_ambiguous_or_missing_inputs() -> None:
    extractor = CallableDetailExtractor(lambda *_args, **_kwargs: "{}")
    with pytest.raises(ValueError, match="not both"):
        resolve_detail_extractor(
            detail_extractor=extractor,
            legacy_extract_auction_data=lambda *_args, **_kwargs: "{}",
        )
    with pytest.raises(ValueError, match="requires"):
        resolve_detail_extractor(
            detail_extractor=None,
            legacy_extract_auction_data=None,
        )
