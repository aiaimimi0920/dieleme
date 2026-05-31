# 模块清单

## 分析模块

### `src/avm/canonical_mapper.py`

- 责任：把 raw 数据映射到 canonical 字段
- 现状：已覆盖基础价格/面积/时间/行政区字段
- 问题：未稳定吸收 `avm_risk_features` 与更多采集侧补充字段

### `src/avm/feature_builder.py`

- 责任：从 canonical 记录构建分析特征
- 现状：仅包含基础地理与价格特征
- 问题：风控、用途、楼龄、税费、占用等维度未进主特征集

### `src/avm/engine.py`

- 责任：估值核心逻辑
- 现状：
  - `predict_price()`：基础空间加权
  - `predict_fair_price()`：更接近目标的空间 + 时间 + 风控
- 问题：
  - 主链路未默认使用更强实现
  - 无坐标或坐标稀缺时缺少可靠降级策略

### `src/avm/service.py`

- 责任：数据加载与按 item_id 预测
- 现状：主入口
- 问题：仍调用弱版 `predict_price()`

### `src/query.py`

- 责任：另一套按可比样本做降级估值的逻辑
- 现状：具备社区/区/市三级回退思想
- 问题：未并入主链

### `src/avm_temporal.py`

- 责任：时间趋势调整
- 现状：独立可用，已有测试
- 问题：未接入当前 AVM 主服务

### `src/avm_weighting.py`

- 责任：距离与位置关系权重
- 现状：独立可用，已有测试
- 问题：未接入当前 AVM 主服务

## 采集模块

### `tampermonkey_scripts/fapaifang_unified.user.js`

- 责任：列表页嗅探、详情页抓取、HTML 上传、页面辅助
- 现状：列表页已能产出成交价、起拍价、竞拍人数等候选字段
- 问题：首跳发送到 `/api/save` 的字段过少，很多上下文没有持久化

### `src/server.py`

- 责任：采集编排与数据落盘
- 现状：
  - `/api/save` 只落极少数字段
  - `/api/analyze_html` 负责详情 HTML 入队
- 问题：
  - `/api/avm/predict` 已收敛到 `AVMService.predict_by_item_id`
  - `build_avm_result()` 仍服务 `/api/avm/screen` 的 alert 包装层，应继续避免新增第三套估值主链

### `src/llm_helper.py`

- 责任：LLM 调用、拍卖字段抽取、AVM 风控抽取
- 现状：已支持 AVM 风控字段抽取，公开入口为 `extract_avm_risk_features`
- 问题：历史 raw helper 仍保留为内部辅助，后续不要再新增并行公开入口
