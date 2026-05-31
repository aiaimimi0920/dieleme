# 法拍房采集与 AVM 分析系统

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Storage](https://img.shields.io/badge/Storage-JSON%20%2B%20PostgreSQL-green)
![Control%20Plane](https://img.shields.io/badge/Control%20Plane-Receipt%20Aware-orange)
![Status](https://img.shields.io/badge/Status-Active-yellow)

## 项目简介

本仓库当前的核心不是“演示型游戏项目”，而是一套正在持续演进的 **法拍房数据采集、结构化治理、AVM 分析、以及 operator handoff control-plane**。

当前实现重点包括：

- **采集主链路**：浏览器侧脚本抓取 + Python 后端接收、调度、归档。
- **DB-first / dual-write**：保留 JSON 归档，同时支持 PostgreSQL 作为主索引与分析落盘方向。
- **analysis-ready / AVM**：围绕 Canonical / feature / alert / gate 的分析侧工具链。
- **maintenance & recovery**：围绕 recent gap、replay、coordinate backfill、analysis reconcile 的维护闭环。
- **manual review control-plane**：围绕 receipt、async maintenance job、operation audit、status/gate surface 的人工回执与自动恢复链路。

如果你是第一次进入这个仓库，可以把它理解为：

> **一个正在从“采集系统”升级为“采集 + 数据治理 + AVM + operator control-plane”一体化平台的工程。**

---

## 常用 operator 入口

### 后端本地入口

- 启动主服务：
  - `auto/main.bat`
- 启动数据修复：
  - `auto/data_fixer.bat`
- 启动 hybrid 种子采集执行器（browserless fast path + 浏览器 fallback）：
  - `auto/seed_hybrid_collector.bat`

这两个 batch 入口现在都支持外部覆盖 `PYTHON_CMD`，因此在 smoke / 包装脚本 / 定制 Python 环境下可以直接注入解释器路径，而不是只能依赖仓库内 `venv` 或系统 `python`。

其中 `auto/seed_hybrid_collector.bat` 额外支持：

- `HYBRID_API_BASE`
- `HYBRID_SESSION_ID`
- `HYBRID_CDP_ENDPOINT`
- `HYBRID_RUN_MODE`
- `TAOBAO_AUTH_PROFILE_DIR`
- `HYBRID_EXTRA_ARGS`

运行模式说明：

- `HYBRID_RUN_MODE=hybrid`
  - 默认模式
  - 先走 browserless fast path
  - 命中 login / challenge / punish / missing payload 时按现有 fallback 逻辑切回浏览器 worker
- `HYBRID_RUN_MODE=browserless`
  - 只跑 browserless
  - 即使命中 fallback 条件，也只返回结果，不自动打开浏览器
- `HYBRID_RUN_MODE=browser`
  - 跳过 browserless 探测
  - 直接把真实 task URL 改写为 `uni_mode=SNIFF_WORKER` 并打开浏览器 worker

`HYBRID_EXTRA_ARGS` 可继续补 runner 级控制，例如：

- `--max-runs 1`
- `--stop-on-fallback`
- `--max-consecutive-fallbacks 3`

例如，可以安全做一次单轮 bounded run：

```powershell
$env:HYBRID_API_BASE = "http://127.0.0.1:8011/api"
$env:HYBRID_EXTRA_ARGS = "--max-runs 1 --stop-on-fallback"
cmd /c auto\seed_hybrid_collector.bat
```

### 前端本地入口

- 从当前工作区稳定构建前端：
  - `python tools/build_web_app.py`
- 从当前工作区稳定启动前端静态预览：
  - `python tools/preview_web_app.py`
- 从当前工作区稳定启动前端 dev server：
  - `python tools/dev_web_app.py`

这些 helper 会优先处理当前 Windows + UNC 工作目录下的本地盘映射问题，避免直接 `npm run build` / `npm run dev` 时踩 `CMD.EXE` 的 UNC cwd 限制。

### Userscript smoke 入口

- 启动本地 userscript harness 预览：
  - `python tools/preview_userscript_harness.py`

它会暴露：

- `http://127.0.0.1:43180/tools/userscript_harness.html`

用于对：

- `tampermonkey_scripts/fapaifang_unified.user.js`

做本地 load-time smoke，而不需要直接碰真实站点。

---

## 当前系统实际在做什么

### 1. 数据采集

- 后端主入口：`src/server.py`
- 浏览器脚本入口：`tampermonkey_scripts/fapaifang_unified.user.js`
- 采集服务实现：
  - `src/collection/seed_service.py`
  - `src/collection/detail_service.py`

当前支持：

- 搜索/种子采集
- 详情任务分发
- HTML / payload / 详情归档
- DB-first pending task 读取

### 2. 数据存储与索引

当前是 **JSON + PostgreSQL dual-write** 模式：

- JSON 仍负责：
  - 历史归档
  - HTML / payload / 附件路径
  - 本地离线调试与回放
- PostgreSQL 负责：
  - 主索引
  - pending / stage / readiness 统计
  - 后续 analysis-ready 主落盘方向

关键实现：

- `src/storage/repository.py`
- `src/storage/models.py`

### 3. AVM 与分析侧工具链

在线能力：

- `src/avm/service.py`
- `src/avm/engine.py`
- `src/avm/pipeline.py`

离线 / 构建 / 门禁工具：

- `tools/build_canonical_dataset.py`
- `tools/check_feature_drift.py`
- `tools/evaluate_avm.py`
- `tools/generate_avm_alerts.py`
- `tools/avm_release_gate.py`

### 4. recent enrich maintenance 与自动恢复

当前维护闭环已经不是单纯“补详情”，而是面向 collection-stage / analysis-stage 的系统化修复：

- `tools/run_recent_enrich_maintenance.py`
- `tools/run_analysis_stage_reconcile.py`
- `tools/run_data_supply_optimization_loop.py`
- `tools/analysis_stage_planner.py`

支持：

- detail archive fetch
- archived detail backfill
- recent coordinate backfill
- detail replay preparation
- analysis ready recheck
- stage state reconcile

### 5. manual review control-plane

当前已经有正式的 receipt control-plane：

- snapshot store：
  - `tools/manual_review_receipt_store.py`
- async maintenance jobs：
  - `tools/manual_review_receipt_jobs.py`
- append-only audit log：
  - `tools/manual_review_receipt_audit.py`

对外接口位于：

- `GET/POST/DELETE /api/avm/manual_review_receipts`
- `GET /api/avm/manual_review_receipt_jobs`
- `GET /api/avm/manual_review_receipt_operations`

并且 status / health / release gate 已经可见：

- `manual_review_receipt_summary`
- `manual_review_reentry_application_summary`
- `manual_review_receipt_jobs_summary`
- `manual_review_receipt_operations_summary`

---

## 快速开始

### 环境要求

- Python 3.10+
- Chrome + Tampermonkey
- 可选：Docker（本地 PostgreSQL）

### 1. 安装依赖

```powershell
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
```

### 2. 启动后端

最小启动：

```powershell
python src/server.py
```

### 3. 可选：启用 PostgreSQL 主索引

```powershell
docker compose -f docker-compose.postgres.yml up -d
$env:FAPAI_DB_URL="postgresql+psycopg://fapaifang:fapaifang@127.0.0.1:55432/fapaifang"
$env:FAPAI_DB_PREFER_RUNTIME_INDEX="1"
python src/server.py
```

说明：

- 不配置 `FAPAI_DB_URL` 时，系统仍可在 JSON 模式下运行。
- 配置后，运行时 pending / stage / readiness 统计会优先走 DB-first。

### 4. 安装浏览器脚本

将以下脚本导入 Tampermonkey：

- `tampermonkey_scripts/fapaifang_unified.user.js`

### 5. 常用维护命令

#### recent enrich maintenance

```powershell
python tools/run_recent_enrich_maintenance.py --dry-run
```

#### data supply optimization loop

```powershell
python tools/run_data_supply_optimization_loop.py --dry-run --max-rounds 2
```

#### release gate

```powershell
python tools/avm_release_gate.py --reuse-eval-report --reuse-drift-report
```

---

## 常用接口

### 采集 / 状态

- `GET /api/status`
- `GET /api/avm/health`
- `GET /api/analysis/health`

### AVM

- `GET /api/avm/predict?id=<item_id>`
- `POST /api/avm/screen`
- `POST /api/avm/evaluate`

### maintenance / pipeline

- `POST /api/avm/recent_enrich_maintenance`
- `POST /api/avm/run`

### manual review control-plane

- `GET/POST/DELETE /api/avm/manual_review_receipts`
- `GET /api/avm/manual_review_receipt_jobs`
- `GET /api/avm/manual_review_receipt_operations`

详细契约见：

- `docs/AVM_API.md`
- `docs/AVM_Runbook.md`

---

## 文档索引

建议按下面顺序阅读：

1. `README.md`
2. `architecture.md`
3. `docs/AVM_API.md`
4. `docs/AVM_Runbook.md`
5. `docs/AVM_Architecture_Overview.md`
6. `docs/analysis/final-collection-contract.md`

其中：

- `architecture.md`：当前实现视角的工程架构
- `docs/AVM_Architecture_Overview.md`：AVM 目标蓝图 / 规划视角

---

## 目录结构

```text
fapaifang/
├── src/
│   ├── server.py                 # 主 HTTP 服务
│   ├── collection/               # seed/detail collection services
│   ├── storage/                  # DB-first repository and models
│   └── avm/                      # AVM online service / pipeline / schema
├── tools/
│   ├── run_recent_enrich_maintenance.py
│   ├── run_data_supply_optimization_loop.py
│   ├── run_analysis_stage_reconcile.py
│   ├── avm_release_gate.py
│   ├── analysis_stage_planner.py
│   ├── manual_review_receipt_store.py
│   ├── manual_review_receipt_jobs.py
│   └── manual_review_receipt_audit.py
├── datas/                        # JSON 归档、AVM 报告、receipt/job/audit 状态
├── docs/                         # API、Runbook、架构文档
├── tampermonkey_scripts/         # 浏览器采集脚本
├── jobs/                         # 搜索/调度任务文件
└── auto/                         # Windows 本地脚本入口
```

---

## 当前边界

当前仓库仍有这些明确边界：

- manual review control-plane 当前已支持 **DB-backed first phase**，但在 repository disabled 场景下仍会回退到 JSON persistence
- live DB migration / alembic 不是默认可执行路径，仍依赖环境显式配置
- `docs/AVM_Architecture_Overview.md` 是目标蓝图，不应误读为“所有能力都已上线”
- 游戏 / 可视化内容仍存在，但已经不是仓库主叙事中心

---

## 许可证与使用说明

1. 本项目仅供技术研究、学习与内部工程实践使用。
2. 数据源来自公开网页，使用时需遵守目标站点协议与相关法律法规。
3. 仓库内的自动化、抓取、分析与估值能力都应在合规边界内使用。
