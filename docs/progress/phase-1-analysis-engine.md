# Phase 1: Analysis Engine

- [x] 统一 `AVMService` 到单一主预测链
  - 验收：不再默认调用弱版 `predict_price()`
- [x] 把空间、时间、风控逻辑收口到统一引擎
  - 验收：结果包含主策略与降级策略信息
- [x] 把 `avm_risk_features` 纳入 canonical / feature 主链
  - 验收：风控字段可被引擎直接消费
- [x] 清理重复分析入口与重复定义
  - 验收：`/api/avm/predict` 逻辑路径唯一可追踪

## Notes

- 已完成主链收口：`AVMService`、`predict_fair_price()`、`/api/avm/predict` 已对齐。
- 第二轮已完成 `llm_helper.py` 中重复 AVM 风控抽取定义的收口，并补齐审计字段默认值。
- 后续继续接入了 `property_fee_owed`、`layout`、`includes_parking`、`bid_count/apply_count` 等已进特征流但此前未消费的维度。
- 进一步补齐了 `evaluation_price` 的新旧量纲兼容与软锚点逻辑，避免直接硬覆盖估值主价。
