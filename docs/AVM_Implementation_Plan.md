# AVM 当前实现基线与未完成项

> 本文档描述 **已经落地的 AVM / collection-stage / control-plane 基线能力**，以及当前仍然明确未完成的边界。
> 若要看长期目标，请结合 `docs/AVM_Architecture_Overview.md` 阅读。

## 1. 已落地能力

### 1.1 数据规范与映射

当前已经有稳定的规范与映射层：

- `src/avm/schema.py`
- `src/avm/risk_schema.py`
- `src/avm/normalize.py`
- `src/avm/canonical_mapper.py`
- `src/avm/collection_template.py`

已支持：

- 原始采集字段到 canonical 字段的统一映射
- 金额 / 面积 / bool / 枚举的标准化
- analysis-ready 所需主字段的统一口径

### 1.2 在线 AVM 服务

当前在线 AVM 主链已经位于：

- `src/avm/engine.py`
- `src/avm/service.py`
- `src/avm/pipeline.py`

并由：

- `src/server.py`

对外暴露接口。

已支持：

- 单条预测
- 批量筛选
- evaluate / pipeline 入口
- health / status surface

### 1.3 DB-first / dual-write

当前存储层已具备：

- JSON 归档
- PostgreSQL dual-write
- DB-first pending / stage / readiness 统计

关键实现：

- `src/storage/models.py`
- `src/storage/repository.py`

### 1.4 recent enrich maintenance 与恢复闭环

当前维护层已经形成统一 workflow：

- `tools/run_recent_enrich_maintenance.py`
- `tools/run_analysis_stage_reconcile.py`
- `tools/run_data_supply_optimization_loop.py`
- `tools/analysis_stage_planner.py`

当前已接入的恢复动作包括：

- detail archive fetch
- archived detail backfill
- recent coordinate backfill
- detail replay preparation
- analysis ready recheck
- stage state reconcile

### 1.5 manual review control-plane

当前 operator control-plane 已经不是草稿，而是正式可用的一条链：

- snapshot store：
  - `tools/manual_review_receipt_store.py`
- async job manager：
  - `tools/manual_review_receipt_jobs.py`
- append-only audit：
  - `tools/manual_review_receipt_audit.py`

已支持：

- receipt CRUD
- async maintenance job
- operation history
- control-plane token gate
- status / gate surface

## 2. 对外接口现状

### 2.1 核心 AVM 接口

- `GET /api/avm/predict?id=<item_id>`
- `POST /api/avm/screen`
- `POST /api/avm/evaluate`
- `POST /api/avm/run`

当前离线主流水线也已从：

- canonical
- risk
- feature
- predict
- alert

扩展到继续产出：

- `eval_report.json`
- `calibration_targets.json`
- `release_gate.json`

### 2.2 状态与观察面

- `GET /api/status`
- `GET /api/avm/health`
- `GET /api/analysis/health`

### 2.3 operator receipt control-plane

- `GET/POST/DELETE /api/avm/manual_review_receipts`
- `GET /api/avm/manual_review_receipt_jobs`
- `GET /api/avm/manual_review_receipt_operations`

以及对应的 `analysis` 前缀别名。

## 3. 当前仍未完成的内容

### 3.1 估值能力仍未完全达到蓝图目标

目前仍未完全做实：

- 区域时间趋势拟合
- 风控标签对主估值结果的稳定修正
- 更成熟的误差回测与调参闭环

当前已经新增的过渡能力包括：

- 在线估值与历史回测的语义开始拆分：
  - 在线 `/api/avm/evaluate` 默认 `current_market`
  - 离线 `tools/evaluate_avm.py` 默认 `historical_strict`
  - 离线评估报告现在会同时产出：
    - `historical_strict` 主指标
    - `current_market` 参考指标
    - `valuation_mode_sample_counts`
    - `valuation_mode_metrics`
- `src/avm_temporal.py` 已开始作为共享 temporal source of truth，被 `src/avm/engine.py` 复用，而不再维持完全独立的时间趋势实现
- temporal trace 现在已显式暴露：
  - `valuation_mode`
  - `temporal_reference_mode`
  - `temporal_target_date`
  - `future_dated_comparable_count_excluded`
- 风险特征校验现在开始进入在线估值响应与离线评估指标：
  - `risk_validation`
  - `risk_validation_counts`
- release gate 也开始把这两类新信号正式纳入 evaluation gate：
  - `historical_strict` 是否为主评估模式
  - `risk_validation` 的 invalid cohort 是否超预算
- cohort-aware 评估指标已开始输出：
  - `strategy_metrics`
  - `coordinate_strategy_metrics`
  - `risk_validation_metrics`
  - `risk_flag_metrics`
- 离线 backtest 现在也会复用 centroid 风格的 subject 坐标补齐逻辑，
  使 `coordinate_strategy_metrics` 更能反映在线服务真实主链，而不只是静态缺失标签。
- `AVMService.health_snapshot()` 也开始直接暴露数据集级别的风险字段质量摘要：
  - `risk_validation_counts`
  - `risk_feature_completeness_avg`
- release gate 的 evaluation 段现在不仅有主门禁指标，还会带：
  - `valuation_mode_metrics`
  - `strategy_watchlist`
  - `risk_validation_watchlist`
  - `risk_flag_metrics`
  - `calibration_targets`
- `tools/suggest_avm_calibration_targets.py` 已开始把风险标签 cohort 误差翻译成调参草案，包括：
  - `suggested_action`
  - `suggested_factor_step_pct`
  - `suggested_next_factor`
- 同一 calibration helper 现在也开始给出 temporal 调参建议：
  - `time_decay`
  - `suggested_next_value`
  - `config_patch.weighting.time_decay`
- 当多个风险标签 cohort 呈现一致的系统性偏差时，
  calibration helper 现在也会给出全局：
  - `risk_discount_factor`
  调参建议，而不只是单个 `risk_factor_overrides`
- calibration helper 现在还会给出高层 `guidance`，先区分：
  - 参数调优
  - 坐标补全 / centroid 质量
  - 样本覆盖
  - 风险字段质量修复
- 离线 pipeline 的 calibration / gate stage summary 现在也开始直接带：
  - `guidance_status`
  - `coordinate_strategy_watchlist`
  - `top_target_name`
  - `top_target_hint_status`
  - `top_target_playbook_id`
  - `recommended_bundle_id`
  - `recommended_bundle_changed_key_count`
  - `recommended_bundle_primary_change`
  - `recommended_bundle_secondary_changes`
  - `recommended_bundle_preview_command`
  - `recommended_bundle_write_command`
  - `recommended_bundle_verify_command`
  - `recommended_bundle_gate_command`
  便于 operator 快速判断这一轮应先看哪一类问题。
- `/api/avm/health` 现在也开始直接暴露：
  - `coordinate_strategy_counts`
  - `calibration_guidance`
  - `calibration_target_counts`
  - `top_calibration_target`
  - `top_calibration_target_hint`
  - `coordinate_strategy_watchlist`
  - `top_coordinate_strategy_group`
  使 operator 不打开完整 release gate，也能快速拿到这层判断。
- `top_calibration_target_hint` 现在还会继续带：
  - `suggested_commands`
  - `suggested_bundle_commands`
  - `playbook_id`
  - `runbook_refs`
  让 operator 可以从状态面直接跳转到建议的命令级操作。
- `calibration_patch_preview` 现在也会进入 operator surface，
  用于表达当前 patch 是否仍然会改动本地配置，以及会改动哪些 key；
  当前还会继续带：
  - `changed_paths`
  - `rollback_patch`
- 同时新增：
  - `top_calibration_patch_preview`
  用于只预览当前 `top_calibration_target` 对应的那部分 patch
- 现在还继续新增：
  - `recommended_bundle_patch_preview`
  用于只预览 `recommended_bundle` 对应的那组 patch
- 同时新增：
  - `recommended_bundle_risk_level`
  - `recommended_bundle_risk_reasons`
  用于快速表达 recommended bundle 的调整面是否已经偏宽
- 现在又新增：
  - `recommended_bundle_next_action`
  - `recommended_bundle_next_action_reasons`
  用于在风险摘要之上给出更直接的 first-response 建议
- 同时新增：
  - `recommended_bundle_next_action_command`
  - `recommended_bundle_next_action_command_kind`
  用于把 first-response 建议进一步压成单条优先命令
- 现在继续新增：
  - `recommended_bundle_follow_up_command`
  - `recommended_bundle_follow_up_command_kind`
  用于把下一步动作扩成最小的两步 operator mini-playbook
- 当前还继续新增：
  - `recommended_bundle_command_chain`
  用于把这条 mini-playbook 进一步收成结构化命令链
- 当前 chain item 还会继续带：
  - `expected_signal`
  - `success_criterion`
  - `surface`
  - `artifact_kind`
  - `artifact_owner`
  - `artifact`
  - `artifact_resolved_path`
  - `artifact_check_command`
  - `artifact_check_timing`
  - `artifact_freshness`
  - `artifact_freshness_reason`
  - `artifact_next_expected_transition`
  - `artifact_ready_for_step`
  - `step_ready_summary`
  - `step_ready_recommended_action`
  - `step_ready_action_command`
  - `step_ready_follow_up_command`
  - `step_ready_follow_up_expected_signal`
  - `step_ready_follow_up_success_criterion`
  - `step_ready_terminal_outcome`
  - `step_ready_stage_span`
  - `step_ready_priority`
  - `step_ready_badge`
  - `step_ready_group_id`
  - `step_ready_group_label`
  - `step_ready_sort_key`
  - `step_ready_display_order`
  - `step_ready_lane`
  - `step_ready_lane_label`
  - `artifact_state`
  - `artifact_state_reason`
  用于把“执行完命令后看什么”也纳入同一个 contract
- `/api/status` 现在也会通过新增的 `avm` 子对象聚合这层信息，
  让总状态面也能直接看到 AVM 主链当前更像：
  - 参数问题
  - 坐标质量问题
  - 风险字段质量问题
- `src/avm_config.py` / `datas/avm/config.json` 现在支持可选：
  - `risk_factor_overrides`
  便于后续在不改源码的情况下试调风险折价/溢价系数
- 当前还新增了 `tools/apply_avm_calibration_patch.py`，
  用于把 `calibration_targets.json -> config_patch` 做成正式的 dry-run / write-back 工具，
  避免 operator 手工抄 patch。
- 这条 patch 工具链现在还支持：
  - `--target-type temporal|global_risk|risk_flag`
  - `--target-name <target_name>`
  - `--write`
  便于只 preview/apply 当前 top target 对应的那部分 patch，而不是整份 `config_patch` 一次性全吃。
- 当前这两个过滤参数也支持重复传入，
  便于后续把 patch preview / apply 从“单一 target”继续扩成“小型 target bundle”。
- 同一套配置入口也开始进入其它 AVM 主链参数：
  - `radius_km`
  - `weighting.distance_power`
  - `weighting.time_decay`
  - `weighting.community_boost`
  - `risk_discount_factor`
  - `alert_threshold`
  不再只是文档中的静态字段
- 当前参数语义：
  - `alert_threshold` 允许 `0.0`
  - `weighting.time_decay` 运行态会收敛到 `0.0 ~ 1.0`
- 当前阶段：
  - `distance_power` / `community_boost` 已进入空间权重主链
  - `time_decay` 已进入 shared temporal 主链，用于抑制更远时间跨度下的趋势外推幅度
  - `risk_discount_factor` 已进入风险修正主链，用于整体调节风险/正向修正强度
- 这层 override 现在也会进入运行态观察面：
  - `trace.risk_factor_override_count`
  - `trace.active_risk_discount_factor`
  - `trace.weighting_distance_power`
  - `trace.weighting_time_decay`
  - `trace.weighting_community_boost`
  - `/api/avm/health` -> `active_risk_discount_factor`
  - `/api/avm/health` -> `active_risk_factor_override_count`
  - `/api/avm/health` -> `active_risk_factor_overrides`
  - `/api/avm/health` -> `active_weighting`

也就是说：

> 当前已经有 AVM 工程骨架与部分在线能力，但还没有完全达到蓝图中“完整时空估值 + 全量风控折价修正”的终态。

### 3.2 control-plane 已进入 DB-backed first phase

目前 receipt / jobs / audit 已支持：

- repository enabled 时优先持久化到数据库
- repository disabled 时回退到：
  - `manual_review_receipts.json`
  - `manual_review_receipt_jobs.json`
  - `manual_review_receipt_operations.jsonl`
- repository enabled 且表为空时，可从现有 JSON / JSONL 自动 bootstrap
- 可显式把 repository-backed 当前状态重新导出成 JSON / JSONL 备份
- repository-backed 的 runtime mutation 现在也会自动刷新 JSON / JSONL 备份，进一步明确：
  - DB 是主路径
  - JSON 是 bootstrap + backup/export 层
- status / gate / control-plane 接口现在还能直接暴露 backup health：
  - 是否存在 warm JSON backup
  - 是否与 repository count 保持一致
- 并且 repository-backed 的读路径会在备份缺失/失配时自动做一次 repair，再通过：
  - `manual_review_control_plane_backup.backup_reason`
  解释是原本已同步，还是刚被自动修复
- 现在还有单独的 backend-status 读接口，便于 operator 在不翻大 status/gate payload 的情况下直接查看：
  - storage source
  - backup state
  - backup repair reason
- 这意味着 repository-first 迁移态现在已经具备：
  - status / gate 内嵌观察面
  - control-plane 专用 backend-status 单点观察面
- 进一步地，backup 自修复现在也有 repair summary，可用于判断这种修复是偶发，还是正在反复发生
- 当前这层 telemetry 已经能回答：
  - 是否修过
  - 最近一次为什么修
  - 最常见的修复原因是什么
- 现在还新增了更高层的 integrity summary，便于 operator 直接看到：
  - 当前是 healthy / repaired_recently / degraded 哪一类
  - 是否需要人工关注
- 同时也开始记录 integrity 历史转换，便于后续确认：
  - 什么时候从 healthy 进入 repaired / degraded
  - 这种切换是不是反复发生
- 在这之上又补了一层 stability summary，帮助 operator 更快判断：
  - 当前是 stable / watch / unstable 哪一类运行态
- 现在又补了一层 guidance summary，把这些状态进一步翻译成：
  - 现在是否需要立即动作
  - 建议先做哪一类 follow-up
- 在当前无 live DB 环境下，下一层最有价值的本地能力是 rollout preflight：
  - 在真正执行 migration / backfill 前先判断当前更适合先配库、先 backfill、先补 backup，还是已经可以做 runtime validation

下一层更重的升级不再是“从无到有的 DB 化”，而是：

- 把当前 first-phase DB persistence 继续扩成更完整的 repository-first contract
- 逐步弱化 JSON fallback 在生产路径中的角色

### 3.3 文档仍在持续对齐中

当前顶层文档已经基本围绕：

- README
- `architecture.md`
- `docs/AVM_API.md`
- `docs/AVM_Runbook.md`

完成了一轮对齐，但二级文档仍需持续维护，避免再次回到 legacy 叙事。

## 4. 当前建议的实施顺序

如果继续推进，建议遵循这条顺序：

1. **保持 collection-stage / analysis-stage / control-plane 文档持续对齐**
2. **把当前 receipt/job/audit 的 DB-backed first phase 继续推进成更完整的 repository-first 持久化**
3. **继续收口 AVM 蓝图中的时间趋势与风控修正能力**

## 5. 常用命令

### Canonical / analysis 相关

```powershell
python tools/build_canonical_dataset.py --data-dir datas --output-dir datas/canonical
python tools/check_feature_drift.py
python tools/evaluate_avm.py
python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report
```

### Maintenance / optimization

```powershell
python tools/run_recent_enrich_maintenance.py --dry-run
python tools/run_data_supply_optimization_loop.py --dry-run --max-rounds 2
```

### Control-plane

```powershell
curl "http://127.0.0.1:8001/api/avm/manual_review_receipts"
curl "http://127.0.0.1:8001/api/avm/manual_review_receipt_jobs"
curl "http://127.0.0.1:8001/api/avm/manual_review_receipt_operations"
python tools/backfill_manual_review_control_plane_to_db.py --data-root datas --db-url "<your-db-url>"
python tools/export_manual_review_control_plane_to_json.py --data-root datas --db-url "<your-db-url>"
```
