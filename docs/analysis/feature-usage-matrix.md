# Feature Usage Matrix

## 已直接参与价格主链或直接改写价格

- `latitude`
- `longitude`
- `community_name`
- `business_area`
- `district`
- `city`
- `area_sqm`
- `actual_paid_price`
- `transaction_price`
- `auction_date`
- `housing_type`
- `build_year`
- `total_floors`
- `floor_level`
- `has_elevator`
- `orientation`
- `special_school_tag`
- `has_keys`
- `auction_round`
- `tax_burden`
- `is_occupied`
- `has_long_lease`
- `clear_delivery`
- `land_right_type`
- `is_restricted_purchase`
- `property_fee_owed`
- `tax_is_company_owned`
- `is_fractional_share`
- `is_haunted`
- `has_lease_before_mortgage`
- `layout`
- `includes_parking`
- `evaluation_price`
- `extraction_confidence`

## 已参与置信度或运行时判定

- `bid_count`
- `apply_count`

## 已参与运行时约束/服务逻辑

- `item_id`

## 当前明确保留为兼容/调试字段，不直接参与当前主链

- `auction_month_index`
- `unit_price`

## 当前明确作为元数据保留，不参与价格求解

- `province`
- `status`
- `evidence_source`
- `extraction_version`

## 当前明确不直接参与价格主链的原因

- `item_id`
  - 用于服务层排除 subject 自身，避免目标样本泄漏进 comparables。
- `auction_month_index`
  - 当前主链直接使用 `auction_date` 做时间趋势建模，保留该字段主要用于兼容旧分析脚本和离线调试。
- `unit_price`
  - 当前多维主链会用 `actual_paid_price/transaction_price + area_sqm` 重新计算单价；保留该字段主要用于旧版基础函数兼容和人工排查。
- `province`
  - 已被 `city/district/business_area` 更细粒度字段覆盖。
- `status`
  - 属于流程态字段，不是估值属性。
- `evidence_source`
  - 属于抽取审计字段，用于回溯风控信息来源。
- `extraction_version`
  - 属于抽取链版本元数据，用于兼容与回放。
