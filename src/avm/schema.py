"""AVM 规范层数据结构定义。

字段与 `docs/AVM_Data_Schema.md` 严格对齐：
- CanonicalRecord：核心数学模型字段（强结构化）
- RiskFeatures：LLM 抽取特征字段（非结构化转换）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


HousingType = Literal["住宅", "商业", "办公", "工业", "别墅", "车位", "其他"]
FloorLevel = Literal["低区", "中区", "高区", "顶层", "底层", "独栋"]
Orientation = Literal["南", "南北", "东", "西", "北", "未知"]
LandRightType = Literal["出让", "划拨", "未知"]
TaxBurden = Literal["买受人承担全部", "各自承担", "未知"]


@dataclass(slots=True)
class CanonicalRecord:
    """核心数学模型字段（与 AVM Data Schema 第 1 节一致）。"""

    # 来源字段：id；转换规则：直接映射为规范层唯一 ID（迁移期可与平台 ID 一致）；不可空。
    item_id: str

    # 来源字段：平台原始 ID；转换规则：原样保留用于回溯；不可空。
    source_item_id: str

    # 来源字段：页面坐标纬度；转换规则：解析为 float，保持 WGS 坐标语义；不可空。
    latitude: float

    # 来源字段：页面坐标经度；转换规则：解析为 float，注意不可与 latitude 反置；不可空。
    longitude: float

    # 来源字段：成交价格/落槌价；转换规则：统一换算为元（若为万元需 *10000）；不可空。
    transaction_price: float

    # 来源字段：落槌价、税费估算、欠费估算；转换规则：actual_paid_price = 落槌价 + 税费 + 欠费，单位元；不可空。
    actual_paid_price: float

    # 来源字段：建筑面积；转换规则：统一为平方米（sqm）；不可空。
    area_sqm: float

    # 来源字段：交易时间/拍卖结束时间；转换规则：标准化为北京时间 YYYY-MM-DD HH:mm:ss；不可空。
    auction_date: str

    # 来源字段：拍卖轮次（一拍/二拍/变卖）；转换规则：归一化为 1/2/3；可空（P1）。
    auction_round: int | None = None

    # 来源字段：房屋用途/标的类型；转换规则：归一化枚举[住宅, 商业, 办公, 工业, 别墅, 车位, 其他]；不可空。
    housing_type: HousingType = "其他"

    # 来源字段：出价记录数；转换规则：解析为整数总出价次数；可空（P1）。
    bid_count: int | None = None

    # 来源字段：报名人数；转换规则：解析为整数总报名人数；可空（P1）。
    apply_count: int | None = None


@dataclass(slots=True)
class RiskFeatures:
    """LLM 风控/属性抽取字段（与 AVM Data Schema 第 2 节一致）。"""

    # 来源字段：地址文本/标题/公告正文；转换规则：提取并规范化小区名称；可空（未提及返回 null）。
    community_name: str | None = None

    # 来源字段：公告正文、评估报告；转换规则：提取建成年份（4 位整数）；可空。
    build_year: int | None = None

    # 来源字段：楼栋信息；转换规则：提取总楼层数为整数；可空。
    total_floors: int | None = None

    # 来源字段：楼层描述；转换规则：归一化为[低区, 中区, 高区, 顶层, 底层, 独栋]；可空。
    floor_level: FloorLevel | None = None

    # 来源字段：公告/须知中的电梯信息；转换规则：是/否映射为 bool；可空。
    has_elevator: bool | None = None

    # 来源字段：户型或评估报告朝向描述；转换规则：归一化为[南, 南北, 东, 西, 北, 未知]；可空。
    orientation: Orientation | None = None

    # 来源字段：土地权利描述；转换规则：归一化为[出让, 划拨, 未知]；可空。
    land_right_type: LandRightType | None = None

    # 来源字段：占用/腾空状态描述；转换规则：有人居住或未腾空为 true；可空。
    is_occupied: bool | None = None

    # 来源字段：租赁权/带租约描述；转换规则：存在长期租约且买卖不破租赁为 true；可空。
    has_long_lease: bool | None = None

    # 来源字段：法院交付责任描述；转换规则：法院负责清场交付为 true，自行腾退为 false；可空。
    clear_delivery: bool | None = None

    # 来源字段：税费承担条款；转换规则：归一化为[买受人承担全部, 各自承担, 未知]；可空。
    tax_burden: TaxBurden | None = None

    # 来源字段：公告中的刑案/非正常死亡描述；转换规则：涉及凶宅风险为 true；可空。
    is_haunted: bool | None = None

    # 来源字段：看样安排/钥匙说明；转换规则：法院有钥匙可看房为 true；可空。
    has_keys: bool | None = None

    # 来源字段：欠费条款（物业/水电）；转换规则：存在或可能存在欠费为 true；可空。
    property_fee_owed: bool | None = None

    # 来源字段：标题/公告卖点；转换规则：出现“学区/学位”等标签为 true；可空。
    special_school_tag: bool | None = None

    # 来源字段：评估价/市场价；转换规则：统一为万元（原文为元时 /10000）；可空。
    evaluation_price: float | None = None

    # 来源字段：户型描述；转换规则：提取结构化户型字符串（如 3室2厅2卫）；可空。
    layout: str | None = None

    # 来源字段：限购政策说明；转换规则：受限购政策约束为 true；可空。
    is_restricted_purchase: bool | None = None

    # 来源字段：拍卖标的范围；转换规则：包含车位产权/使用权一并拍卖为 true；可空。
    includes_parking: bool | None = None

    # 来源字段：产权描述；转换规则：按份共有/部分产权为 true；可空。
    is_fractional_share: bool | None = None

    # 来源字段：被执行人/产权人主体类型；转换规则：原产权人为企业/公司为 true；可空。
    tax_is_company_owned: bool | None = None

    # 来源字段：租赁与抵押先后关系描述；转换规则：属于“先抵后租”可清场场景为 true；可空。
    has_lease_before_mortgage: bool | None = None
