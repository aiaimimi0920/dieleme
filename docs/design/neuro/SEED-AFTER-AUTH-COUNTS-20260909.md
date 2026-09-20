# 认证后的商品链接增长与 PostgreSQL 计数修复

日期：2026-09-09，时间均按北京时间说明。

## 当前已经确认的结果

本次人工认证后，唯一商品链接已经从 273682 增至 273853，增加 171 个。05:18 的数据库与 API 核验一致；05:28:23 再次读取桌面使用的 `/api/collection/overview`，`modules.links.unique_items=273853`、`modules.links.total=908527`、`statistics.valid=true`、`statistics.stale=false`，链接阶段 `paused=false`。

05:28 的最近一分钟增量为 `[0, 2, 0]`，分别对应链接、详情、分析。这个链接 `+0` 是该采样区间没有新去重商品，不能解读为认证以来一直没有新增。没有修改唯一商品的计数口径，也没有用重复出现记录替代唯一商品数量。

认证后最初的批次确实读到已有商品；随后在另一个分类发现了 171 个新商品。期间还有短暂的挑战暂停，不能保证站点以后不再要求认证。最新状态已经解除暂停，本轮没有重新提交 Cookie 或强制清除挑战。

## 数据库证据

只读事务查询的认证后区间起点为 UTC `2026-09-08 21:00:00`，即北京时间 05:00。

- 查询时唯一商品总数为 273853；该区间首次入库商品为 171，最后一个新商品首次入库时间为 05:08:38。
- 05:17 的链接出现记录区间统计为 672 条，涉及 361 个去重商品。
- `510302-50025969` 任务产生 190 条出现记录，涉及 190 个认证前已知商品，页码范围 18 至 63。
- `510302-200782003` 任务产生 482 条出现记录，涉及 171 个新商品，页码范围 1 至 25。
- 之后出现记录继续增加，05:28 总数达到 908527。出现记录与唯一商品数量各有独立含义，重复商品在不同排序或页面出现不会增加唯一商品总数。

只读证据文件：`.debug/seed-target-20260909/after-auth-database.json`；后续状态快照位于同目录 `postcheck-*.json`。

## 另外找到并复现的代码缺陷

`src/storage/repository_seed_items.py` 原先使用 `result.rowcount > 0` 判断 PostgreSQL 的 `INSERT ... ON CONFLICT DO NOTHING` 是否成功新增。实际 psycopg / SQLAlchemy 组合可返回 `rowcount=-1`，因此已经提交的新商品被错误记为已有商品，已经新增的出现记录被错误记为 0。

这解释了现场日志与数据库的矛盾：多个批次报告 `new_items=0`、`new_occurrences=0`，但数据库记录确实增加。先前只依据这些日志把所有商品判为重复的推断不成立；本次以数据库首次入库时间和实际行数校正。

在本机 Docker Desktop 创建独立、临时 PostgreSQL 16 数据库后，使用真实仓库代码复现：数据库提交了 2 个唯一商品和 3 条出现记录，原代码第一次调用却返回 `new_items=0`、`existing_items=2`、`new_occurrences=0`。该测试不连接 NAS 或 PC2 数据库。

修复对 PostgreSQL 插入增加 `RETURNING`，根据是否返回实际插入的 ID 判断新增。冲突仍由数据库原有唯一约束处理，同页重复返回 0，不同页的新出现记录返回 1。SQLite 路径保持原逻辑。

该缺陷影响采集日志和批次统计，不直接驱动当前桌面的唯一商品总数。当前 NAS 使用轻量统计路径，按 seed 队列数据库状态计数汇总 `total_ids`，桌面读取 `modules.links.unique_items`；不能把本补丁描述为修正了桌面总数或促成了上述 171 个商品入库。

## 修改与验证

- 修改：`src/storage/repository_seed_items.py`。
- 新增回归：`tools/test/test_seed_postgres_insert_counts.py`，仅允许显式配置的本机临时测试数据库。
- 修复前真实 PostgreSQL 回归失败，明确复现上述错误计数。
- 修复后 PostgreSQL 回归、seed identity、scan policy、seed queue repository 共 71 项通过。
- 有效代码行规则测试 19 项通过；ratchet 通过，963 个文件，既有超过 1500 行的基线文件未变。
- `git diff --check` 通过；两个源文件/测试文件均为 UTF-8 无 BOM。
- 独立只读复核未发现阻塞问题。
- 本机临时 PostgreSQL 测试容器已删除；未改动其他 Docker 容器或任何线上业务数据。

## 发布材料与授权范围

已只读取得 PC2 链接 worker 的准确源文件并比较，候选文件仅包含上述 PostgreSQL 计数修复。材料保存在 `.debug/seed-target-20260909/count-overlay/`。最初准备完成时尚未部署；用户随后明确授权仅更新并重启 PC2 链接采集容器，发布结果见下节。

- 目标：仅 `fapaifang-pc2-seed-1`。
- 文件：`src/storage/repository_seed_items.py`。
- 线上基线 SHA-256：`453246837a17d1bfab7e13da5b4ea73a45d8b6e22e18ad363b85d79d8293ee84`。
- 候选 SHA-256：`458504560241d126d45271a298829d05db0de811f25de11916f95aace24a5f6d`。

本轮使用用户随后给出的 PC2 专项授权执行，没有扩展为 NAS、详情 worker、浏览器或数据库服务重启。

链接采集曾实际产生 171 个新商品；这项历史增长已经确认。后续再次出现挑战，应按新的阶段状态处理；如果界面仍显示旧总数，可刷新以重新获取已经核验的 overview 数据。

## PC2 上线结果：05:56

用户授权后，计数补丁已于北京时间 2026-09-09 05:56:02 上线。只切换 `fapaifang-pc2-seed-1`。

- 新容器 ID：`b7a4ca18eb95444302f13306b24923c55728dfe1ea0108a1aff161f702504bd7`。
- 镜像：`sha256:ca50623539b265c8b2f6966f9f826c8780f1245ce34e03da590ba23952bcbe38`。
- 运行文件 SHA-256 与本报告候选哈希一致。
- Docker 状态 `healthy`，`restart_count=0`，已确认实际 seed collector 进程存在。
- 环境变量、启动配置、HostConfig、原有网络别名和数据挂载均通过与发布前的比较。仅排除新容器自动添加的短 ID 别名，并按挂载目标排序后比较。
- 其他 PC2 容器的镜像、运行状态、开始/结束时间均与发布前一致；没有重启详情 worker 或浏览器。
- 旧容器保留为 `fapaifang-pc2-seed-1-before-20260909-counts`，保留原镜像和回滚所需私有配置。
- PC2 发布目录：`/srv/apps/fapaifang-worker/shared/collection-control/release-20260909-seed-counts/`；目录权限为 0700。发布过程未使用 Compose。
- 候选镜像在无网络、无生产凭据/挂载、只读文件系统的临时容器中通过模块加载、源文件哈希和真实 SQLite 入库/去重/跨页出现记录测试；此前真实 PostgreSQL 回归与 71 项聚焦测试已经通过。
- 首次构建因 BuildKit 将本地 image ID 当作远端标签解析而失败，没有切换运行容器；改用本地经典构建器后成功构建，仍基于准确的原运行镜像，仅增加单文件覆盖层。

发布核验回执：`.debug/seed-target-20260909/count-overlay/verify-receipt.log`；新进程只读观察结果：同目录 `runtime-observation.json`。发布清单状态已更新为 `deployed_verified`。

## 当前剩余的现场限制

05:57:50 查询：唯一商品 273853、出现记录 908594、详情 114335。链接阶段报告新的挑战 `captcha-1788904089638120351`，`paused=true`、`pause_reason=manual_required`。

旧容器保留日志证明，05:53:20、05:54:24 和 05:55:28 已连续报告 `captcha_solver_manual_required`，均早于 05:56:02 的发布重启。因此，新容器继承的是发布前已经存在的挑战阻塞。

新进程首轮因该挑战采集 0 页，尚无可用于现场核验 PostgreSQL 新增计数的非空批次。补丁已部署且运行核验通过，但不能把本次零页批次当作新增计数的现场成功证明。完成当前新挑战后，后续批次将运行新的计数实现；没有伪造完成通知、重置进度、修改 Cookie 或强制解除暂停。
