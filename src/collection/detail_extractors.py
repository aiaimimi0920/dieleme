from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .contracts import DetailExtractor


@dataclass(frozen=True)
class CallableDetailExtractor:
    """Adapt an existing JSON-string extraction function to DetailExtractor."""

    callback: Callable[..., str]

    def extract(self, content: str, *, item_id: str | None = None) -> str:
        return self.callback(content, item_id=item_id)


def resolve_detail_extractor(
    *,
    detail_extractor: DetailExtractor | None,
    legacy_extract_auction_data: Callable[..., str] | None,
) -> DetailExtractor:
    if detail_extractor is not None and legacy_extract_auction_data is not None:
        raise ValueError("provide detail_extractor or extract_auction_data, not both")
    if detail_extractor is not None:
        return detail_extractor
    if legacy_extract_auction_data is None:
        raise ValueError("detail extraction requires detail_extractor or extract_auction_data")
    return CallableDetailExtractor(legacy_extract_auction_data)
