"""AVM 规范层数据结构定义。"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, Literal


HousingType = Literal["住宅", "商业", "办公", "工业", "别墅", "车位", "其他"]
FloorLevel = Literal["低区", "中区", "高区", "顶层", "底层", "独栋"]
Orientation = Literal["南", "南北", "东", "西", "北", "未知"]
LandRightType = Literal["出让", "划拨", "未知"]
TaxBurden = Literal["买受人承担全部", "各自承担", "未知"]


@dataclass(slots=True)
class CanonicalRecord:
    """核心数学模型字段。"""

    item_id: str
    source_item_id: str | None = None
    source_url: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    transaction_price: float | None = None
    starting_price: float | None = None
    actual_paid_price: float | None = None
    area_sqm: float | None = None
    auction_date: str | None = None
    province: str | None = None
    city: str | None = None
    district: str | None = None
    community_name: str | None = None
    business_area: str | None = None
    status: str | None = None
    auction_round: int | None = None
    housing_type: HousingType = "其他"
    bid_count: int | None = None
    apply_count: int | None = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RiskFeatures:
    """LLM 风控/属性抽取字段。"""

    community_name: str | None = None
    build_year: int | None = None
    total_floors: int | None = None
    floor_level: FloorLevel | None = None
    has_elevator: bool | None = None
    orientation: Orientation | None = None
    land_right_type: LandRightType | None = None
    is_occupied: bool | None = None
    has_long_lease: bool | None = None
    clear_delivery: bool | None = None
    tax_burden: TaxBurden | None = None
    is_haunted: bool | None = None
    has_keys: bool | None = None
    property_fee_owed: bool | None = None
    special_school_tag: bool | None = None
    evaluation_price: float | None = None
    layout: str | None = None
    is_restricted_purchase: bool | None = None
    includes_parking: bool | None = None
    is_fractional_share: bool | None = None
    tax_is_company_owned: bool | None = None
    has_lease_before_mortgage: bool | None = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
