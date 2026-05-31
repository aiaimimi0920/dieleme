# src/ 目录说明

> ⚠️ 本目录不是“已被 `tb_adapter/` 取代”的旧快照。
> 当前仓库的主实现已经集中到 `src/`，其中：
>
> - `src/server.py` 是统一 HTTP 服务入口
> - `src/collection/` 是现网采集服务实现
> - `src/storage/` 是 DB-first / dual-write 存储层
> - `src/avm/` 是 AVM 在线服务与分析相关实现
>
> 只有少数顶层遗留脚本仍保留为历史参考。

## 当前主实现目录

### 1. `src/server.py`

当前统一入口，负责：

- collection API
- status / health surface
- AVM API
- maintenance / pipeline 触发
- manual review receipt control-plane

### 2. `src/collection/`

当前采集主链路实现：

- `seed_service.py`
- `detail_service.py`
- `search_bootstrap.py`
- `stage_state.py`

它们负责：

- 搜索任务分配
- 详情任务调度
- stage state 维护
- DB-first pending task 流程

### 3. `src/storage/`

当前存储层实现：

- `models.py`
- `repository.py`

职责：

- PostgreSQL dual-write
- DB-first pending / stage / readiness 读取
- event / audit / search task 状态支撑

### 4. `src/avm/`

当前 AVM 在线实现：

- `service.py`
- `engine.py`
- `pipeline.py`
- `schema.py`
- `risk_schema.py`
- `canonical_mapper.py`
- `feature_builder.py`
- `collection_template.py`
- `quality.py`

---

## 仍保留的 legacy 顶层模块

以下顶层模块仍存在，但不再代表当前主链：

| 文件 | 原功能 | 当前定位 |
|------|--------|----------|
| `scraper_ali.py` | Playwright 列表页爬虫 | 历史采集实现参考 |
| `scraper_detail.py` | Playwright 详情页爬虫 | 历史详情采集实现参考 |
| `processor.py` | 成本计算器 | 局部逻辑未来可能复用 |
| `custom_browser.py` | 反检测浏览器会话 | 仅 legacy scraper 相关 |
| `db.py` | SQLite 初始化 | 历史存储实现参考 |
| `query.py` | 早期估值查询 | 已不是当前唯一 AVM 入口 |
| `scraper.py` | 基础爬虫类 | legacy 继承基类 |

这些文件仍可读，但不应被误解为当前主实现中心。

---

## 浏览器脚本侧对应关系

当前浏览器侧主脚本是：

- `tampermonkey_scripts/fapaifang_unified.user.js`

它与 `src/server.py` / `src/collection/*` 配合工作。
不要再把旧的 `tb_adapter/taobao_monitor.user.js` / `taobao_fast_worker.user.js` 当成当前仓库主入口。

---

## 建议阅读顺序

如果要从 `src/` 开始理解当前系统，建议顺序：

1. `src/server.py`
2. `src/collection/`
3. `src/storage/repository.py`
4. `src/avm/service.py`
