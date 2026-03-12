# AVM Implementation Plan

## 目标
在不影响现有主链路的前提下，为 `src/avm/` 建立最小可扩展骨架，明确模块职责与输入输出契约，便于后续逐步落地估值与风控能力。

## 模块职责与输入输出

### 1) `src/avm/canonical_mapper.py`
- **职责**：承接“现状采集字段 -> AVM 规范字段”的统一映射入口。
- **输入**：`raw_record: Dict[str, Any]`（采集原始记录）。
- **输出**：`canonical_record: Dict[str, Any]`（规范字段记录）。
- **备注**：当前为占位透传，并补充 `schema_version`。

### 2) `src/avm/risk_schema.py`
- **职责**：定义风控评估结构体，统一风险标签表达。
- **输入**：风控引擎的规则/模型输出。
- **输出**：`RiskAssessment(score, tags, details)`。
- **备注**：`RiskTag` 作为单标签最小单元（编码、等级、描述）。

### 3) `src/avm/feature_builder.py`
- **职责**：将 Canonical 数据转换为估值模型可消费的特征字典。
- **输入**：`canonical_record: Dict[str, Any]`。
- **输出**：`features: Dict[str, Any]`。
- **备注**：当前为占位透传，后续接入时空特征与风控特征。

### 4) `src/avm/engine.py`
- **职责**：估值引擎主入口，返回统一估值结果结构。
- **输入**：`features: Dict[str, Any]`。
- **输出**：`AVMResult(estimated_price, confidence, components)`。
- **备注**：当前返回占位结果，`components` 预留可解释分解项。

### 5) `src/avm/service.py`
- **职责**：流程编排层，串联映射、特征构建、估值与风控聚合。
- **输入**：`raw_record: Dict[str, Any]`。
- **输出**：统一响应字典：
  - `canonical`
  - `features`
  - `estimate`
  - `risk`
- **备注**：当前仅为占位实现，未挂接现网主链路。

### 6) `src/avm/__init__.py`
- **职责**：集中导出 AVM 对外接口，降低调用方导入复杂度。
- **输入/输出**：模块导入行为。

## 与现有服务的接入策略
- 在 `src/server.py` 仅增加 AVM import 占位，不改动请求处理链路。
- 完整接入建议分两阶段进行：
  1. 离线回放验证（字段映射正确性 + 结果结构稳定性）。
  2. 在线灰度接入（旁路观测，不影响当前主流程）。

## 后续实施建议
1. 完成 Canonical 字段映射表（与 `docs/AVM_Data_Schema.md` 对齐）。
2. 补齐特征工程（空间、时间、资产属性、风控标签）。
3. 为 `AVMService.evaluate` 增加输入校验、日志和错误码。
4. 增加单元测试覆盖关键契约（I/O schema、空值处理、类型一致性）。
