# 项目总览

## 任务目标

本轮改造仅聚焦两个模块：

1. 分析模块
2. 采集模块

游戏化模块暂不调整。

核心目标是把仓库里分散的 AVM/估值逻辑收口为一条真正可运行的多维度分析主链，并让采集模块稳定供给主链所需字段。

## 当前架构

- 浏览器侧：
  - `tampermonkey_scripts/fapaifang_unified.user.js`
  - 负责列表页嗅探、详情页抓取、HTML 回传、本地修复辅助
- 后端编排：
  - `src/server.py`
  - 负责任务调度、数据落盘、AI 解析、AVM API、离线子任务编排
- 分析模块：
  - `src/avm/*`
  - `src/query.py`
  - `src/avm_temporal.py`
  - `src/avm_weighting.py`
- AI 抽取：
  - `src/llm_helper.py`
- 离线工具：
  - `tools/build_canonical_dataset.py`
  - `tools/build_avm_features.py`
  - `tools/generate_avm_alerts.py`

## 主要入口

- 启动服务：`auto/main.bat` -> `src/server.py`
- 数据修复：`auto/data_fixer.bat` -> `src/data_fixer.py`
- AVM 离线链路：
  - canonical dataset
  - feature build
  - alerts generation

## 当前诊断

- 主链路仍以采集与数据治理为主。
- AVM 相关代码已经形成多个并存实现，但没有统一到单一预测主链。
- 采集链路第一跳保存的数据过于精简，导致分析模块无法稳定消费完整上下文。
