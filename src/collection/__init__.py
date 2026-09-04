"""Crow collection engine: rough discovery, detail capture, and AI archiving."""

from .adapters import GenericProductAdapter, TaobaoJudicialAuctionAdapter
from .detail_service import DetailCollectionService
from .readiness import generic_product_analysis_missing_fields
from .seed_service import SeedCollectionService
from .stage_state import derive_stage_state

__all__ = [
    "DetailCollectionService",
    "GenericProductAdapter",
    "generic_product_analysis_missing_fields",
    "SeedCollectionService",
    "TaobaoJudicialAuctionAdapter",
    "derive_stage_state",
]
