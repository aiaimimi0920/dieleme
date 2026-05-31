# 分析模块与采集模块协同改造

## 任务描述

目标：

- 优化并实现分析模块中的多维度分析引擎
- 基于分析模块需要，回推修改采集模块
- 游戏化模块暂不调整

## 分析文档

- [project-overview](../analysis/project-overview.md)
- [module-inventory](../analysis/module-inventory.md)
- [risk-assessment](../analysis/risk-assessment.md)

## 计划文档

- [task-breakdown](../plan/task-breakdown.md)
- [dependency-graph](../plan/dependency-graph.md)
- [milestones](../plan/milestones.md)

## 阶段进度

- [x] Phase 1: Analysis Engine (4/4 tasks) [details](./phase-1-analysis-engine.md)
- [x] Phase 2: Collection Contract (2/2 tasks) [details](./phase-2-collection-contract.md)
- [x] Phase 3: Validation (2/2 tasks) [details](./phase-3-validation.md)

## Current Status

- 当前阶段：Validation Evidence Refreshed
- 当前任务：分析模块主链、采集契约、服务契约与自动化测试已继续推进；长期模型校准新增了县镇/弱成交场景下的更强保守护栏、同名社区跨城禁入、special regime 的 zero-same-type fallback veto，并补了机读/人读两套房源采集信息模板。随后又把模板反推回采集链：列表页 stub、详情助手、基础 AI 抽取提示词都已开始对齐 `full_address / bid_count vs bidder_count / deposit / source_title` 这些关键字段。最新真实离线评估已继续下降到 `MAPE 49.39% / P90 96.62%`。当前阶段的本地工程实现继续向长期校准收口，但剩余阻塞仍主要是历史 recent 缺档、数据补给与 residual fallback 长尾误差
- 当前采集合同已冻结为 `avm_collection_contract_v1_frozen`；后续若要改 authoritative key、字段语义或单位，应按 breaking change 升新版本，不再原地改名。
- 当前 PostgreSQL + PostGIS 主落盘已完成第一轮真实建表与全量历史回填；后端仍保留 JSON 兼容/归档层，但运行时索引已进一步收敛为“零预载 + 按需懒加载工作项”，`/api/status /api/get_item /api/get_tasks /api/next_task /api/get_next_task /api/update_item /api/analyze_html /api/area_result /api/approve_area /api/save /api/avm/screen` 与部分控制面 loader 已开始向数据库优先切换，且任务派发/修正完成后会主动逐出运行时缓存。当前实测 `runtime_seen=0`、`runtime_pending=0`，而数据库侧 `db_total=223445`、`db_processed=219214`、`db_pending=4231`、`db_detail_captured=219181`；`/api/status` 与 `/api/avm/health` 也已开始直接暴露这些数据库计数用于运营观测。本轮继续把 `drift_status / release_gate / evaluate_avm / generate_avm_alerts` 的 loader 显式切成 DB-first 调用，并让 `update_item / analyze_html / area_result / approve_area / process_single_file` 这类旧接口在 DB-first 模式下无需先把 item 常驻进 `SEEN_IDS` 就能完成写回。下一步重点是继续把更重的分析控制面与残余内存状态继续收口。

## Next Steps

1. 优先修复近 7 天坐标与风险字段缺失，提升 `release_gate` 的 completeness 指标
2. 针对 `eval_report.json` 中剩余的高倍数误差样本，继续做 fallback 策略、低价/大面积样本清洗与 `UNK` 场景保护，重点盯 `其他 + global/city/district fallback`
3. 基于 `recent_gap_audit.json`、`recent_enrich_maintenance.json` 和 archived detail backfill 链补 future enrich 回放；当前坐标 centroid 回填 dry-run 已证实历史数据缺少可用坐标池
