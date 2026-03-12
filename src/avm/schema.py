from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any


@dataclass
class CanonicalRecord:
    """Canonical AVM data record used for valuation pipelines."""

    item_id: str
    source_url: Optional[str] = None
    transaction_price: Optional[float] = None  # Yuan
    starting_price: Optional[float] = None  # Yuan
    actual_paid_price: Optional[float] = None  # Yuan (optional estimate)
    area_sqm: Optional[float] = None
    auction_date: Optional[str] = None
    province: Optional[str] = None
    city: Optional[str] = None
    district: Optional[str] = None
    community_name: Optional[str] = None
    business_area: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    status: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
