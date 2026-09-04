from __future__ import annotations

import os
from collections.abc import Mapping

from .adapters import GenericProductAdapter, TaobaoJudicialAuctionAdapter
from .contracts import CollectionAdapter


GENERIC_ADAPTER_NAMES = frozenset({"generic", "generic_product"})
TAOBAO_JUDICIAL_ADAPTER_NAMES = frozenset(
    {"taobao", "taobao_judicial", "taobao_sf", "sf.taobao.com"}
)


def create_collection_adapter(
    adapter_name: str = "generic",
    *,
    source_platform: str | None = None,
) -> CollectionAdapter:
    """Create one domain adapter without leaking source rules into orchestration."""

    normalized_name = str(adapter_name or "generic").strip().lower().rstrip("/")
    if normalized_name in GENERIC_ADAPTER_NAMES:
        normalized_platform = str(source_platform or "generic").strip() or "generic"
        return GenericProductAdapter(source_platform=normalized_platform)
    if normalized_name in TAOBAO_JUDICIAL_ADAPTER_NAMES:
        return TaobaoJudicialAuctionAdapter()
    supported = sorted(GENERIC_ADAPTER_NAMES | TAOBAO_JUDICIAL_ADAPTER_NAMES)
    raise ValueError(
        f"unsupported collection adapter {adapter_name!r}; expected one of {supported}"
    )


def collection_adapter_from_env(
    *,
    default: str = "generic",
    environ: Mapping[str, str] | None = None,
) -> CollectionAdapter:
    """Resolve the configured adapter while keeping library defaults source-neutral."""

    settings = os.environ if environ is None else environ
    adapter_name = settings.get("CROW_COLLECTION_ADAPTER") or default
    source_platform = settings.get("CROW_COLLECTION_SOURCE_PLATFORM")
    return create_collection_adapter(
        adapter_name,
        source_platform=source_platform,
    )
