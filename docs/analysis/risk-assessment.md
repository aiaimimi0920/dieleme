# 风险评估

## P0 风险

### 1. 估值主链分裂

- `src/avm/engine.py`
- `src/query.py`
- `src/avm_temporal.py`
- `src/avm_weighting.py`
- `src/server.py`

影响：

- 同名 AVM 能力在不同入口表现不一致
- API 返回结果可能依赖命中的是哪一条历史逻辑

### 2. 采集首跳丢字段

- `tampermonkey_scripts/fapaifang_unified.user.js`
- `src/server.py:/api/save`（兼容别名）
- `src/server.py:/api/collection/seeds/batch`

影响：

- 分析模块拿不到标题、列表价格、报名/出价人数等上下文
- HTML 抽取失败时几乎没有可降级的原始结构化数据

### 3. 风控字段未真正参与估值

- `src/llm_helper.py`
- `src/avm/canonical_mapper.py`
- `src/avm/feature_builder.py`
- `src/avm/service.py`

影响：

- 虽然抽取了风险字段，但主估值结果仍接近“只看面积和距离”

## P1 风险

### 4. 缺坐标时主链失效

- 当前强分析逻辑高度依赖 `latitude/longitude`
- 真实数据中这两个字段未稳定供给

影响：

- 结果频繁退化成弱估值或直接无法估值

### 5. API 重复分支

- `src/server.py` 中 `/api/avm/predict` 分支重复

影响：

- 后续改动极易漏改
- 外部调用难以判断真实契约

## P2 风险

### 6. 文档与实现代际不一致

- 旧文档与 legacy 注释曾大量引用 `tb_adapter/*`
- 当前主实现中心已明确迁移到 `src/*`、`tools/*` 与 `tampermonkey_scripts/fapaifang_unified.user.js`

影响：

- 新增功能容易继续叠加而非收口
