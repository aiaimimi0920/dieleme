"""Crow collection engine: rough discovery, detail capture, and AI archiving."""

from .adapters import GenericProductAdapter, TaobaoJudicialAuctionAdapter
from .adapter_resolver import collection_adapter_from_env, create_collection_adapter
from .detail_extractors import CallableDetailExtractor
from .detail_service import DetailCollectionService
from .readiness import generic_product_analysis_missing_fields
from .seed_service import SeedCollectionService
from .stage_state import derive_stage_state

__all__ = [
    "DetailCollectionService",
    "CallableDetailExtractor",
    "collection_adapter_from_env",
    "create_collection_adapter",
    "GenericProductAdapter",
    "generic_product_analysis_missing_fields",
    "SeedCollectionService",
    "TaobaoJudicialAuctionAdapter",
    "derive_stage_state",
]
