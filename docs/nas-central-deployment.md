# FapaiFang NAS 中央化采集部署

目标拓扑：

- NAS `192.168.15.200` 运行中央 PostgreSQL + PostGIS、`fapaifang-api`、HTML 采集观察台。
- 每台采集 PC 只运行 seed/detail/analysis workers、本机 CDP 浏览器和本机认证流程。
- 所有 worker 连接同一个中央数据库，通过 DB lease/claim 避免重复采集。
- 文件型产物统一写入 NAS 共享目录；不同采集节点通过 `FAPAI_NODE_ID` 隔离 output 和 cookie snapshot。

## 迁移前必须备份

切换中央 DB 前必须先备份当前本地数据库和关键文件目录：

```powershell
docker exec fapaifang-postgres pg_dump -U fapaifang -d fapaifang -Fc -f /tmp/fapaifang.dump
docker cp fapaifang-postgres:/tmp/fapaifang.dump \\192.168.15.200\home\backups\fapaifang\fapaifang.dump
```

关键文件目录至少包括：

```text
output/
datas/
jobs/
secrets/
```

不要把运行中的浏览器 profile/cache 当作必须恢复的数据；它们可能被占用或不断变化。

## NAS 中央服务

在 NAS 上准备本机数据目录，例如：

```bash
mkdir -p /volume1/docker/fapaifang/{postgres,output,datas,jobs,secrets,backups}
```

复制 `env.nas.example` 为 `env.nas.local`，按 NAS 实际路径调整：

```bash
cp env.nas.example env.nas.local
```

启动中央 DB/API：

```bash
docker compose --env-file env.nas.local -f docker-compose.nas-central.yml up -d --build
```

### 中央 API 受控更新

中央 API 更新使用 `scripts/deploy-nas-central-api.sh`。脚本只重建/重启
`fapaifang-api`，不会重建 PostgreSQL；但每次部署前仍强制创建并验证一份
`pg_dump -Fc` 备份。

先在 NAS 项目目录做无副作用检查：

```bash
bash scripts/deploy-nas-central-api.sh --env-file env.nas.local --dry-run
```

完整构建：

```bash
bash scripts/deploy-nas-central-api.sh --env-file env.nas.local
```

仅替换应用代码并复用当前镜像依赖层：

```bash
bash scripts/deploy-nas-central-api.sh --env-file env.nas.local --hotfix
```

当工作区还有其他未审查改动、只需发布 NAS 自动认证恢复状态机时，使用最小覆盖层：

```bash
bash scripts/deploy-nas-central-api.sh --env-file env.nas.local --auth-recovery-hotfix
```

该模式以当前线上镜像为基线，只覆盖 `src/server.py` 和
`src/nas_auth_recovery.py`，不会把工作区内其他脏文件复制进镜像。

脚本会：

1. 计算并注入 `FAPAI_BUILD_VERSION`、Git commit、构建时间和关键源码摘要；
2. 验证 PostgreSQL dump 能被 `pg_restore -l` 读取；
3. 给当前 API 镜像创建独立 rollback tag；
4. 只更新 `fapaifang-api`；
5. 等待 `/api/status` 返回本次准确的 `build_info.version` 和
   `build_info.source_digest`；
6. 验证 DB mode、`pg_isready` 和 `/api/collection/overview`；
7. 任一健康门失败时自动恢复 rollback 镜像。

`--hotfix` 不更新 Python、Chromium 或系统依赖；依赖发生变化时必须执行完整构建。
不要在包含未审查临时文件的工作目录执行部署，因为 Docker build context 会包含
未被 `.dockerignore` 排除的文件。

验证：

```bash
docker exec fapaifang-postgres pg_isready -U fapaifang -d fapaifang
curl http://127.0.0.1:8001/api/collection/overview
curl http://127.0.0.1:8001/collection
```

同时检查实际运行版本：

```bash
curl -s http://127.0.0.1:8001/api/status | python3 -c \
  'import json,sys; print(json.load(sys.stdin)["build_info"])'
```

局域网客户端访问：

```text
http://192.168.15.200:8001/collection
```

## 恢复数据库到 NAS

将迁移前 dump 复制到 NAS 后执行：

```bash
docker cp fapaifang.dump fapaifang-postgres:/tmp/fapaifang.dump
docker exec fapaifang-postgres pg_restore -U fapaifang -d fapaifang --clean --if-exists /tmp/fapaifang.dump
docker exec fapaifang-postgres psql -U fapaifang -d fapaifang -c "select count(*) from fapai_seed_item;"
```

恢复后比对本地迁移前计数，至少检查：

```sql
select count(*) from fapai_seed_item;
select count(*) from fapai_seed_occurrence;
select count(*) from fapai_seed_scan_progress;
```

## 采集 PC worker-only 部署

每台采集 PC 复制 `env.worker.example` 为 `env.worker.local`：

```powershell
Copy-Item env.worker.example env.worker.local
```

按机器修改：

```text
FAPAI_NODE_ID=pc1
FAPAI_SHARED_DATA_ROOT_HOST=C:\Users\Public\nas_home\AI\FPFData
FAPAI_CENTRAL_API_BASE_URL=http://host.docker.internal:18081/api
FAPAI_WORKER_DB_URL=postgresql+psycopg://fapaifang:fapaifang@host.docker.internal:15532/fapaifang
FAPAI_LIST_BROWSER_FALLBACK=1
FAPAI_SEED_CAPTCHA_SOLVER_ENABLED=1
FAPAI_DETAIL_CDP_ENDPOINT=http://host.docker.internal:9223
FAPAI_DETAIL_BROWSER_FALLBACK=1
FAPAI_DETAIL_CAPTCHA_SOLVER_ENABLED=1
FAPAI_SEED_AUTH_PROBE_INTERVAL_SECONDS=60
```

`FAPAI_LIST_BROWSER_FALLBACK=1` 很关键：当 HTTP cookie 请求命中淘宝
`_____tmd_____/punish` 验证页时，seed worker 会回退到本机已认证的 CDP
浏览器读取列表页。`FAPAI_SEED_AUTH_PROBE_INTERVAL_SECONDS` 控制挑战/认证相关
失败后的低频重试间隔，避免单次失败后整段链接采集停 30 分钟。

真实 `*.taobao.com` challenge 默认强制 `manual_only`。只有在 NAS API 与拥有可见
Windows/CDP 浏览器的 PC2 节点同时设置 `FAPAI_REAL_TAOBAO_AUTO_SOLVER_ENABLED=1`
时，API 才会把真实挑战委派给节点自动 solver。未设置、设置为 `0`、NAS/PC2 任一
侧缺失，都会继续 fail closed；自动失败后的人工认证仍作为恢复路径。

Windows Docker Desktop 通常不能直接把 NAS SMB/UNC 路径作为 Linux 容器 bind
mount。推荐每台 Windows worker 使用本机数据根，再把关键 artifact 镜像到 NAS：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\sync-worker-artifacts-to-nas.ps1 `
  -SourceRoot '.\FPFData' `
  -TargetRoot '\\192.168.15.200\docker\fapaifang' `
  -LoopIntervalSeconds 60
```

`SourceRoot` defaults to the checkout-local `FPFData/` directory (or
`FAPAI_DATA_ROOT_HOST`). `TargetRoot` has no machine-specific default; pass it
explicitly or set `FAPAI_ARTIFACT_SYNC_TARGET_ROOT` before registering a sync
task.

中央 API 读取 NAS 上的镜像副本；worker 本地继续用同样的 `/data/output`、
`/data/datas`、`/data/jobs`、`/data/secrets` 容器路径，所以数据库里的 artifact
路径在 NAS API 容器中仍保持一致。

如果 worker 容器不能直接访问 `192.168.15.200:55432/8001`，在每台 Windows
worker 主机上启动本机 TCP 转发器，让容器通过 `host.docker.internal` 访问：

```powershell
python tools\worker_tcp_forwarder.py `
  --forward 0.0.0.0:15532=192.168.15.200:55432 `
  --forward 0.0.0.0:18081=192.168.15.200:8001
```

后台隐藏启动示例：

```powershell
Start-Process -WindowStyle Hidden -FilePath python -ArgumentList @(
  'tools\worker_tcp_forwarder.py',
  '--forward', '0.0.0.0:15532=192.168.15.200:55432',
  '--forward', '0.0.0.0:18081=192.168.15.200:8001'
)
```

启动 worker，不启动本地 Postgres，也不启动本地 API：

```powershell
docker compose --env-file env.worker.local `
  -f docker-compose.collection.yml `
  -f docker-compose.worker-node.yml `
  --profile analysis `
  up -d --build `
  fapaifang-seed-collector `
  fapaifang-seed-collector-2 `
  fapaifang-seed-collector-3 `
  fapaifang-seed-collector-4 `
  fapaifang-seed-collector-5 `
  fapaifang-seed-collector-6 `
  fapaifang-detail-worker `
  fapaifang-detail-worker-2 `
  fapaifang-detail-worker-3 `
  fapaifang-detail-analysis-worker `
  fapaifang-detail-analysis-worker-2 `
  fapaifang-detail-analysis-worker-3
```

`FAPAI_NODE_ID` 会使 worker id 和输出目录自动变为：

```text
pc1-seed-1
/data/output/nodes/pc1/seed_collector
```

这样第二台 PC 使用 `FAPAI_NODE_ID=pc2` 时不会覆盖第一台 PC 的运行产物。

## 认证边界

NAS 中央 API 负责状态和任务协调，但淘宝认证仍属于采集 PC 本机浏览器/CDP 状态。

- Tauri 桌面控制台仍可在本机打开认证浏览器。
- HTML 控制台可通知中央 API 清除待认证状态、提交 solver 任务、打开当前浏览器认证页。
- 如果需要从 HTML 控制台远程打开某一台采集 PC 的本地认证浏览器，需要后续增加 node-agent。

## 回滚

在 NAS 稳定运行前，不要删除本地：

```text
fapaifang-postgres
fapaifang_postgres_data
C:\Users\Public\nas_home\AI\FPFData
```

如果 NAS 切换失败：

1. 停止 worker。
2. 恢复 worker 的 `docker.local.env`。
3. 重新连接本机 `127.0.0.1:55432` / `host.docker.internal:55432`。
4. 重新启动原 worker。
