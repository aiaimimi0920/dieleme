# AVM 第一阶段实现计划（已启动）

本文件用于描述当前已落地的 AVM v1 基线能力，遵循 `docs/AVM_Architecture_Overview.md` 与 `docs/AVM_Data_Schema.md` 的总体方向。

## 已实现模块

- `src/avm/schema.py`：Canonical 数据结构定义。
- `src/avm/normalize.py`：金额/面积/数值标准化工具。
- `src/avm/canonical_mapper.py`：现状字段映射到规范字段。
- `src/avm/feature_builder.py`：基础特征构建。
- `src/avm/engine.py`：3km 距离衰减估值基线引擎。
- `src/avm/service.py`：数据加载与按 item_id 预测服务。
- `tools/build_canonical_dataset.py`：离线 canonical 数据集构建与质量报告。

## 当前能力边界

- 已支持：
  - 原始采集数据到 canonical 数据的统一映射。
  - 基于坐标和面积的可比样本估值。
  - 简单的安全垫指标（起拍价对比估值）。
- 未完成（后续迭代）：
  - 23项风控标签完整抽取与估值修正。
  - 时序趋势拟合（区域趋势线）。
  - 误差回测与自动调参。

## API 集成

- 在 `src/server.py` 新增 `GET /api/avm/predict?id=ITEM_ID`。
- 返回估值结果、置信度、可比样本数及安全垫（若可计算）。

## 运行示例

```bash
python tools/build_canonical_dataset.py --data-dir datas --output-dir datas/canonical
```


## 子任务编排（已新增）

支持一键启动 AVM 全部离线子任务（按顺序执行）：
1. canonical 数据构建
2. feature 数据构建
3. 告警生成

### API
- `POST /api/avm/start_all_subtasks`：异步启动全部子任务（后台线程执行）。
- `POST /api/avm/run_all_subtasks_sync`：同步执行全部子任务（调用结束即全部完成/失败）。
- `GET /api/avm/pipeline_status`：查询当前执行状态与每个子任务状态。
- `GET /api/avm/merge_check`：返回“子任务是否全部合并并被执行到统一链路”的核验结果。

### CLI
```bash
python tools/run_avm_pipeline.py --data-dir datas
# 或异步模式
python tools/run_avm_pipeline.py --data-dir datas --async
```

独立子任务脚本：
- `python tools/build_canonical_dataset.py --data-dir datas --output-dir datas/canonical`
- `python tools/build_avm_features.py --canonical datas/canonical/canonical.jsonl --output datas/avm/features.jsonl --stats datas/avm/feature_stats.json`
- `python tools/generate_avm_alerts.py --data-dir datas --output datas/avm/alerts.json --threshold 0.15 --limit 500`



## 统一执行入口（建议）

为合并多轮迭代的子任务入口，新增统一 API：

- `POST /api/avm/run`
  - `mode`: `"async"` 或 `"sync"`
  - `data_dir`: 数据目录（默认 `datas`）
  - `alerts_threshold`: 告警阈值（默认 `0.15`）
  - `alerts_limit`: 告警扫描上限（默认 `500`）

兼容旧接口（内部已转发到统一执行器）：
- `POST /api/avm/start_all_subtasks`
- `POST /api/avm/run_all_subtasks_sync`

CLI 也已统一到同一执行器：

```bash
python tools/run_avm_pipeline.py --data-dir datas --alerts-threshold 0.2 --alerts-limit 800
python tools/run_avm_pipeline.py --data-dir datas --async --alerts-threshold 0.2 --alerts-limit 800
```


### 合并核验字段

`merge_check` 与 `GET /api/avm/merge_check` 返回：
- `expected_subtasks`
- `observed_subtasks`
- `missing_subtasks`
- `unexpected_subtasks`
- `is_fully_merged`

当 `is_fully_merged=true` 且 `missing_subtasks=[]` 时，表示当前版本已将子任务内容合并到统一执行链路。
