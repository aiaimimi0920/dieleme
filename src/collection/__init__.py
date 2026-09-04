"""Crow collection engine: rough discovery, detail capture, and AI archiving."""

from .adapters import GenericProductAdapter, TaobaoJudicialAuctionAdapter
from .adapter_resolver import collection_adapter_from_env, create_collection_adapter
from .detail_extractors import CallableDetailExtractor
from .detail_service import DetailCollectionService
from .readiness import generic_product_analysis_missing_fields
from .seed_scan_policy import (
    DEFAULT_SEED_SCAN_POLICY,
    GenericSeedScanPolicy,
    SeedScanPolicy,
    TaobaoJudicialSeedScanPolicy,
)
from .seed_service import SeedCollectionService
from .stage_state import derive_stage_state

__all__ = [
    "DetailCollectionService",
    "CallableDetailExtractor",
    "collection_adapter_from_env",
    "create_collection_adapter",
    "DEFAULT_SEED_SCAN_POLICY",
    "GenericProductAdapter",
    "GenericSeedScanPolicy",
    "generic_product_analysis_missing_fields",
    "SeedCollectionService",
    "SeedScanPolicy",
    "TaobaoJudicialAuctionAdapter",
    "TaobaoJudicialSeedScanPolicy",
    "derive_stage_state",
]
