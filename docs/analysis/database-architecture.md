# PostgreSQL + PostGIS 主落盘架构

## 目标

将当前以 `datas/*.json` 和 `datas/archive/**/*.json` 为主的事实落盘，逐步迁移到：

- **PostgreSQL**：唯一权威结构化库
- **PostGIS**：空间索引与地理查询
- **文件归档**：HTML / payload / PDF / 图片等大对象仍保留为文件路径与 manifest

当前阶段采取 **dual-write**，但运行态已经明显向数据库收口：

1. 继续保留现有 JSON 写入
2. 新数据同时写 PostgreSQL
3. 查询、控制面与离线分析链逐步改成显式 DB-first
4. JSON 逐步退化为原始归档、回放材料和兼容层

---

## 技术栈

- ORM / 写入层：`SQLAlchemy 2.x`
- 迁移：`Alembic`
- PostgreSQL 驱动：`psycopg 3`
- 空间扩展：`PostGIS`

---

## 当前新增组件

### 1. 数据库模型

- `src/storage/models.py`
  - `property_listing`
  - `property_risk_flags`
  - `property_legal_context`
  - `property_audit`
  - `property_ingest_event`

### 2. 仓储层

- `src/storage/repository.py`
  - 环境变量创建仓储
  - 初始化表结构
  - PostgreSQL 下自动尝试启用 PostGIS
  - `upsert_flat_item(...)`
  - `upsert_collection_record(...)`
  - `mark_deleted(...)`

### 3. dual-write 接入点

当前已接入：

- `/api/save`
- `process_single_file(...)`
- `/api/approve_area`
- `/api/area_result`
- `/api/update_item`
- `/api/analyze_html`

### 4. 回填工具

- `tools/backfill_json_to_db.py`
  - 将现有 JSON / archive 历史数据批量回填到数据库

### 5. 本地 PostgreSQL 运行文件

- `docker-compose.postgres.yml`

### 6. Alembic

- `alembic.ini`
- `alembic/env.py`
- `alembic/versions/20260511_0001_initial_property_dual_write.py`

---

## 环境变量

至少支持：

- `FAPAI_DB_URL`
  - 例：`postgresql+psycopg://fapaifang:fapaifang@127.0.0.1:55432/fapaifang`
- `FAPAI_DB_ENABLED`
  - 默认：如果 `FAPAI_DB_URL` 为空，则仓储自动禁用
- `FAPAI_DB_AUTO_CREATE`
  - 默认启用
- `FAPAI_DB_ENABLE_POSTGIS`
  - PostgreSQL 下默认启用
- `FAPAI_DB_ECHO`
  - SQL 调试输出
- `FAPAI_DB_PREFER_RUNTIME_INDEX`
  - 默认建议启用；服务运行时切为 DB-first，启动后保持零预载，按需懒加载工作对象
- `FAPAI_DB_PREFER_ANALYTICS_SOURCE`
  - 默认关闭；仅在明确需要时让 `release_gate / evaluate / drift` 一类离线工具优先从数据库读取

---

## 推荐启动方式

### 本地数据库

```bash
docker compose -f docker-compose.postgres.yml up -d
```

### 设置数据库连接

```powershell
$env:FAPAI_DB_URL="postgresql+psycopg://fapaifang:fapaifang@127.0.0.1:55432/fapaifang"
```

### 运行 Alembic 迁移

```bash
python -m alembic upgrade head
```

### 历史 JSON 回填

```bash
python tools/backfill_json_to_db.py --data-root datas --db-url postgresql+psycopg://fapaifang:fapaifang@127.0.0.1:55432/fapaifang
```

---

## 当前真实状态

- PostgreSQL + PostGIS 已真实运行
- Alembic 主迁移已执行
- 历史 archive 已全量回填
- 当前数据库主计数：
  - `db_total = 223445`
  - `db_processed = 219214`
  - `db_pending = 4231`
  - `db_detail_captured = 219181`
- `property_audit.source_json_path` 已落地：
  - 数据库会持续保存每条记录对应的原始 JSON 文件路径
  - `get_flat_item / iter_recent_flat_items` 会把它重新暴露成 `json_file / __file_path`
  - 因而 recent replay / coordinate backfill 这类必须回写原 JSON 的维护链，已经可以安全地先走 DB-first recent 选样，再回到文件系统落修复
- 文件型维护链已开始做 dual-write 同步：
  - `prepare_recent_detail_replay`
  - `backfill_recent_coordinates`
  - `backfill_archived_details`
  这些工具在写回原 JSON 后，也会同步把更新后的行回写到 PostgreSQL，避免维护链改了文件但数据库仍旧滞后
- `AVMService` 轻量化增强已落地：
  - `/api/avm/health` 默认走 lightweight snapshot，不再为了健康检查强制触发全量 feature dataset 构建
  - coordinate centroid cache 已优先改成数据库侧聚合（`build_coordinate_centroids()`），不再总是先在 Python 层扫描全量坐标样本
- 运行时状态已收口为：
  - `runtime_seen = 0`
  - `runtime_pending = 0`
- 显式 DB-first 链路已经覆盖：
  - 在线任务控制面：`status / get_item / get_tasks / next_task / get_next_task`
  - 在线更新链：`save / update_item / analyze_html / area_result / approve_area / process_single_file`
  - 离线分析链：`release_gate / drift_status / evaluate_avm / generate_avm_alerts / build_canonical_dataset / run_avm_pipeline / export_to_excel`

## 为什么仍保留 JSON

当前不直接删 JSON 的原因：

1. 现有链路大量读写仍依赖 `SEEN_IDS` + 文件路径
2. HTML / raw payload / 组件 JSON / 附件 manifest 更适合作为文件归档
3. dual-write 可以降低迁移风险
4. 历史数据尚未全部回填数据库

最终方向是：

- PostgreSQL = 主事实库
- JSON / 文件归档 = 原始材料与重抽取材料

---

## 下一步建议

1. 继续压缩 `SEEN_IDS / PENDING_TASKS` 的剩余角色，向更彻底的 query-backed runtime 收口
2. 对仍然整批 materialize 的离线工具补流式/分块处理
3. 继续降低 `AVMService` 全量特征集构建成本，重点盯预测主链、evaluate 与 pipeline 的整批 dataset 构建
4. 继续把纯统计/纯分析工具显式 DB-first，保留 replay/repair/coordinate backfill 的文件优先边界
