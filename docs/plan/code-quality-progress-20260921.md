# Crow 代码优化进度与验证记录

日期：2026-09-21。依据：`code-quality-review-20260920.md`。

状态：**部分完成，不能将原清单三批任务标记为全部完成。**
最新执行边界：用户已要求全部代码任务完成后再部署测试。本次续作没有部署、重启应用，
也没有迁移业务数据库。下文“本地桌面已更新”是该指令之前的历史记录。
2026-09-22 的 API 并发、后台任务和最新门禁结果见文末；接口用法见
[`collection-async-operations.md`](../collection-async-operations.md)。
本轮保留并验证其他 AI 的未提交成果，补充数据持久化、请求边界、watchdog
与测试门禁缺口。本地桌面已更新；NAS API 与 PC2 尚未激活这批源码。

## 数据保护边界

- 未执行业务数据删除、数据库重置、恢复覆盖、表清空、迁移降级、volume 删除、
  `prune`、release 清理或 Cookie 快照过期删除。
- 未运行清单 #33、#40、#46 中的自动删除建议。后续实现也必须遵守用户的
  “无论如何不删除已经整理好的数据”要求。
- Python 测试从新建的系统临时目录启动，显式关闭默认业务数据库，覆盖运行数据路径；
  仓库已有测试网络隔离保持启用。没有将测试指向 NAS 业务数据库。
- Postgres 并发测试使用已有专用容器 `crow-quality-pg-20260920`，已核实
  `crow.purpose=quality-regression`、仅 loopback 暴露端口、无业务目录挂载。
  每项测试创建独立随机 schema，测试结束保留 schema，没有清空原有测试数据。
- 本地应用更新只替换 EXE 和 3 个随包代码文件。运行配置、凭据、Cookie、浏览器
  profile 与数据库内容未被更新操作替换；运行配置 SHA-256 前后相同。
- 没有重启电脑、PC1 人工认证浏览器、NAS、PC2 或不相关服务。

以上是本轮操作边界，不等同于对全部历史业务数据做了全量完整性审计。

## 本轮新增修复

### #39：任务进度写入失败必须可见

`jobs/job_manager.py`：

- 保留已有的“损坏 JSON 读取失败即抛错”修复。
- 缓存读写采用深拷贝，调用方不能在保存成功前修改缓存中的已确认进度。
- 使用目标目录内唯一临时文件，写入后 `flush`、`fsync`，再原子替换。
- 保存失败使缓存失效并向上传播；公开的 `update_progress` 同样传播失败。
- 失败时保留原文件和待写临时快照，便于恢复，不清理既有文件。

回归测试：`tools/test/test_job_progress_durability.py`，覆盖缓存隔离、fsync 失败、
replace 失败、公开调用失败传播，核对原始文件 bytes 不变。

### #49：派发时间缓存不再永久增长

`src/collection/detail_service.py`：

- 三个派发入口在选取候选前移除达到冷却期限的内存时间戳。
- 未到期条目继续阻止重复派发；到期候选可重新派发。
- 不删除文件、记录或采集证据。

回归测试：`tools/test/test_detail_dispatch_retention.py`，覆盖三个入口、空候选、
冷却边界、重复派发防护与归档文件保留。

### #38：损坏 watchdog 状态不能重置重启上限

`tools/pc2_collection_watchdog.py`：

- 拒绝损坏 JSON、非对象状态、负数/布尔/字符串计数、非法或非有限时间戳。
- 状态不可读时保留原文件，返回 `state_unavailable`，暂停自动重启并输出错误日志。
- restart 命令失败时持久化 `restart_failed` 与告警，保留已消耗的重试次数。

回归测试：`tools/test/test_watchdog_state_preservation.py`，全部使用 FakeDocker，
不调用真实 Docker restart。

### #2、#25：补启动鉴权与路由边界

`src/server.py`：

- `/api/collection/control/start` 在业务操作前验证控制 token 和 JSON 请求体。
- GET 具体 API 使用解析后的 path 精确匹配，查询参数保留并继续传入 handler。
- `/api/avm/predict_extra` 等未知后缀不再匹配真实接口。
- upload 只匹配 `/api/upload`，未知后缀不进入文件写入路径。

回归测试：`tools/test/test_http_route_boundaries.py`。

此处不表示 #2 已全部完成：多个采集写入口仍需统一认证与配套客户端更新。
#25 的 POST/DELETE 全面路由表重构也尚未完成。

### #21：修复 Windows 上拒绝请求时的连接中止

合并测试真实捕获到 WinError 10053。错误 Content-Type 与未知 POST API 在未读取
请求体时关闭连接，可能使客户端收不到预期的 415/404。

`src/server_request_guard.py` 与 `src/server_handler_ingest.py` 复用已有
`_send_guard_error`：先发送并半关闭响应，再执行有字节上限及超时的请求体读取。
补充 2、4096、65536 字节请求体用例。最终合并测试通过。

### 测试门禁修复

`tools/test/test_server_source_contract.py`：

- 由测试文件位置推导仓库根，允许从隔离临时目录运行，防止扫描空目录造成假通过。
- 扫描所有路由 if 分支，避免首个独立 if 使后面的路由链被遗漏。
- JSON 路由清单识别统一 `_read_json_body`；HEAD 的明确 404 纳入契约。
- 没有删除原有用例或放宽行数策略。

`tools/test/test_control_plane_error_contracts.py` 与增强的
`tools/test/test_quality_http_guards.py` 验证设置、重启、认证恢复与上传的负向错误码。
这些测试调用真实 HTTP handler，使用替代的授权/存储对象，不操作真实控制邮箱。

## 对已有 AI 成果的本轮验证

已有 quality 测试覆盖的成果包括：上传路径约束与禁止覆盖、HEAD 404、AVM 数据目录
限制、控制 token 缺失拒绝、认证完成目标限制、公共恢复状态裁剪、JSON 大小/类型限制、
5xx 异常详情裁剪、种子重扫保留内部字段、租约不被短租期抢占、跨节点 artifact
认领不永久阻塞、fallback savepoint、DB 故障传播、409 回执归档、Cookie 原子写入、
禁止 HTTP 重定向、LLM 429 冷却和输出预算、worker 生命周期等。

这些成果仍在工作树中，未替其他 AI 提交、回滚或覆盖其实现。
“测试覆盖”只针对具体用例，不等同于原编号全部子要求及多机器发布均完成。

## 新鲜验证结果

| 检查 | 结果 |
|---|---|
| 本轮相关 Python 合并集，隔离目录执行 | **156 passed，20.67 秒** |
| 专用 Postgres，两 worker 同步竞争 search/page/page_parallel/detail | **4 passed，4.40 秒** |
| `node --test scripts/tests/effective-code-lines.test.mjs` | **19 passed** |
| `effective-code-lines --mode ratchet` | 通过；保留基线历史超大文件，没有新增豁免 |
| `git diff --check` | 通过；Git 有 LF/CRLF 提示，无空白错误 |
| `npm run typecheck` | 通过 |
| `npm run test` | **30 passed** |
| `npm run build` | 通过 |
| `cargo fmt -- --check` | 通过 |
| `cargo test --locked` | **9 passed，1 ignored**；忽略项为显式线上只读 probe |
| Playwright collection/authentication/settings smoke | **3 passed，24.1 秒** |
| `cargo build --release --locked` | 通过 |

默认 Playwright headless shell 未安装；使用现有 Chrome channel 的全新测试 profile
完成 smoke。没有附着或关闭人工认证浏览器。没有把失败的初次启动计为成功。

本轮编辑的源码/测试均核对为 UTF-8 无 BOM。没有运行全仓所有历史 pytest 用例，
没有宣称全量测试通过。

## 本地桌面激活证据

安装目录：`%LOCALAPPDATA%/FapaiFangCollectorDesktop`。

替换文件：

- `fapaifang_collector_desktop.exe`
- `tools/pc1_desktop_recovery.py`
- `tools/browserless_seed_probe_cookies.py`
- `tools/internal_api_http.py`

4 个文件均与对应验证源的 SHA-256 一致。

EXE SHA-256：
`4974266fa9694723c1680fd29964ff18c25eb61789c4e54c76a134ad27f7b5bc`。

原文件与原运行配置备份：
`%LOCALAPPDATA%/FapaiFangCollectorDesktop/backup/quality-20260921-3f0b268dfaf44997b262bb28d3314d82`。

首次替换遇到 Windows EXE 退出后的占用窗口，已恢复原版本；增加明确等待进程退出后，
第二次激活成功。新进程 PID `36296`，实际 executable path 指向上述安装目录。

运行配置 SHA-256 保持：
`7618a76d6fa1655af51f58e475e06dd0d103ef588484efe3034003553b349ddc`。

通过 `scripts/update-collector-desktop-shortcut.ps1` 更新桌面 `Crow.lnk`，并验证 target、
working directory、icon、EXE hash。未删除其他桌面文件。

使用安装配置中指定的 Python 运行已安装 helper：`config` 返回 `ok=true`、
`configured=true`；真实 HTTPS `get` 返回 `ok=true`、`available=true`，含 effective
设置。没有提交设置变更、重启请求或认证完成请求。

## NAS/PC2 发布阻塞与剩余工作

NAS 只读检查：`/api/status`、`/api/collection/overview` 均 HTTP 200；DB mode 为 true。
状态接口报告版本 `20260906-manual-auth-r2`。这只是当前线上观察，不能作为本轮部署证据。

**本轮没有部署或重启 NAS API、PC2 worker、PC2 browser。** 整包发布前仍需处理：

1. 鉴权与客户端不一致：`desktop_runtime_controls.ts` 的 `toggleRuntimePause` 调用
   `post(base, action, {})`，未传 token；服务端 pause/resume/start 已要求控制 token。
   现有 native HTTPS helper 仅支持 settings 与 restart，尚无这些运行控制操作。
   直接发布当前服务端会使相应桌面操作收到拒绝。应先完成受配置约束的凭据传递，
   不能退回无鉴权或把私密 token 暴露给任意 origin。
2. 全部写接口的统一认证仍未收口，例如采集上传与部分上报入口；GET resume 的
   loopback 兼容策略也尚未退役。需要同步验证现有 worker/userscript 协议。
3. `scripts/deploy-nas-central-api.sh` 的健康门仍从未鉴权 `/api/status` 读取
   `auth_recovery.enabled`；新的公共状态裁剪不会返回该字段。发布检查必须同步更新。
4. NAS 与 PC2 发布脚本仍包含服务级 Compose 重建；发布前必须检查相同项目/服务标签
   是否有保留备份容器，并在有备份时采用 exact-ID 替换与旧容器保留。

其余清单尚未完成的主要部分：

- #15 HTTPS 与角色 token 全链路迁移。
- #17 单线程 API、长任务异步化；#18 captcha deadline/可中断等待；#22 solver 状态封装。
- #20 页面输入与指令分离的完整契约；#27 aware UTC/schema 迁移与 clock 注入。
- #40 容量管理只能采用不删除整理数据的方案；#41 requirements lock 与基础镜像 digest。
- #42-45 验证码后端、异常、重复选择器与延迟配置加载等结构改造。
- #46 索引与批量锁；#47 剩余全量加载；#48 Alembic metadata 与生产 auto-create 策略。
- #50 热路径快照缓存；#56 非 root 浏览器；#57 多子进程监督。
- 第三批依赖注入、去运行时函数克隆、完整路由表、存储 policy 边界、测试组织与 CI。

行数政策沿用 AGENTS.md，没有修改基线、排除项或自行放宽测试目录。
后续先补齐全部剩余代码与验证任务；部署、应用重启、NAS/PC2 实际运行测试继续延期。

## 续作：AVM facade 显式依赖收口

`src/avm/service.py`、`src/avm/service_health.py`、`src/avm/service_data.py`、
`src/avm/service_prediction.py` 和 `src/avm/service_review.py` 已将
`service_context` 的通配符导入替换为显式导入。保留
AVM facade 的公共常量、类型依赖和五个可 monkeypatch 的函数，并继续由
`_ServiceFacadeModule` 将这些 patch 同步到各 mixin 模块。这样减少隐式名称泄漏，
同时不改变 `AVMService` 的公共导入路径和现有测试替身语义。

`src/avm/engine.py` 同步改为显式重导出 `predict_price`、`predict_fair_price`、
`AVM_CONFIG_MANAGER` 和 `get_active_risk_factor_overrides`，避免通过预测引擎的
通配符链泄漏整个内部模块命名空间，同时保留现有配置 monkeypatch 入口。

`src/avm/engine_temporal.py` 也已改为显式声明核心时间、筛选、权重和风险依赖；
保留供下游统计、护栏和预测模块使用的内部符号，避免在底层引擎迁移过程中改变
预测行为。AVM engine 聚焦回归 **48 passed**。

验证：AVM engine、HTTP contract 与 weighting 聚焦集合 **53 passed**；本项不包含
FunctionType 动态克隆、其他 facade 或生产数据库迁移，剩余 facade 收口仍未完成。

## 续作：安全运行控制、快照缓存和存储查询

以下为用户明确延期部署之后新增的源码工作。全部测试使用临时目录、合成凭据或独立
`crow_quality` 数据库的新 UUID schema，没有对整理数据进行删除、覆盖恢复或清理。

### 桌面开始、暂停与恢复的安全传输

- `desktop_runtime_controls.ts` 使用 native 配置地址与 helper 发起 start/pause/resume，
  不把 operator token 交给浏览器 fetch。浏览器回退要求显式 token，并复用已有 HTTPS/
  loopback origin 检查。未知 action 在发出请求前拒绝。
- Rust action 白名单和 `desktop_settings_client.py` 同步支持三个固定 action；helper
  强制配置 origin、空 JSON body、固定目标路径、私有 CA 和禁止重定向。
- 独立 TLS 网关先验证 operator 角色，再经 `collection_runtime_proxy.py` 转交同机 API。
  agent token、任意 URL、非 loopback 主机、query、path、GET 变更请求均不被允许。
- TLS 网关部署时需显式提供 `FAPAI_CONTROL_LOCAL_API_BASE`，值为与网关处于同一网络
  命名空间的 API loopback HTTP origin，包含实际端口。没有隐式远程地址回退；未配置
  返回 503。主 API 与网关必须使用同一 operator token 文件；如果主 API 配有优先级更高的
  `FAPAI_CONTROL_PLANE_TOKEN`，也须与之匹配。此项配置尚未写入任何运行环境。
- NAS 的网关发布包需要包含 `tools/collection_runtime_proxy.py`；桌面 helper 没有导入
  此网关模块，因此桌面包无需携带它。

验证：合成私有 CA 的真实 loopback TLS、固定路由、角色拒绝及重定向拒绝测试组
**20 passed**；桌面 `npm run typecheck` 通过、`npm run test` **31 passed**；Rust
`cargo fmt --check` 通过，`cargo test --locked` **9 passed, 1 ignored**。忽略项为明确要求
手动启用的安装包在线探测，没有在本次执行。没有构建或激活新的桌面发布包。

此处补齐了上文第 1 项“native helper 不支持运行控制”的代码缺口；统一所有写接口的
鉴权和其他客户端迁移仍未完成，不能据此将 #2 或 #15 整体标记完成。

### 快照缓存与 OS 鼠标默认策略

- `runtime_snapshot_cache.py` 提供按 resolved path、JSON/JSONL 类型及文件 signature
  区分的 LRU 缓存。signature 包含 mtime_ns、大小、ctime_ns 和 inode；缓存条目最多
  128 个，缓存源文件字节预算 8 MiB，超预算文件仍可读取但不驻留。此预算不是 Python
  解析后对象的精确内存上限。
- 每次返回深拷贝；文件变化、损坏、读取失败或过深 JSON 不返回旧成功值；读取过程中
  文件变化也不发布该结果。只移除内存缓存条目，完全不删除文件。
- `server_hybrid_runtime.py` 的两个公共 JSON/JSONL 读取助手已接入。manual review
  其他独立读取函数尚未全部接入，#50 仍是部分完成。
- #42：`captcha_os_windows.py` 默认禁用 OS 鼠标，只有显式
  `FAPAI_SOLVER_OS_MOUSE` 真值才启用；移除生产代码对 `PYTEST_CURRENT_TEST` 的判断。
  测试只注入 policy/mock target，不接触鼠标或真实浏览器。

验证：首次快照/鼠标/HTTP 组合 **53 passed**；之后补充过深 JSON 保留源文件的用例，
随最后一次存储组合测试验证通过。

### 存储查询和非破坏性索引迁移

- `repository_detail_claim.py` 的 detail 和 analysis 两条认领路径均由逐候选 SELECT
  改为批量 `IN (...) FOR UPDATE SKIP LOCKED`。仍按现有优先级获取候选、加锁后重新
  校验状态和租约，再按业务优先级排序；没有降低现有租约保护。
- `repository_seed_scan_jobs.py` 只查询 `DISTINCT status` 集合，保留空任务、completed、
  blocked、in_progress、pending 的原有判断，避免加载全部 progress ORM 对象。
  #47 的分页认领仍有其他全量 job 查询，需要继续处理。
- 新增迁移 `20260921_0012` 和一致的模型索引：
  `fapai_seed_item(status, first_seen_at)`、`property_ingest_event(event_type, created_at)`。
  upgrade 只建索引，downgrade 只撤销这两个索引；不删除事件或条目。
- 保留期删除没有实现，也不允许按原建议加入。后续容量管理应保留历史事件和整理数据。

验证：初次 SQLite 索引迁移、种子队列和数据保留测试 **67 passed**；独立 PostgreSQL
并发与 SQLite/PostgreSQL 索引双向迁移组 **6 passed**。之后补充 analysis 两 worker
竞争用例；最终 PostgreSQL 五类认领、种子队列和快照缓存组合 **64 passed**。
所有 PG 测试 schema 保留，没有清理数据库。索引迁移尚未在业务库执行；未来激活时需
安排实际表的建索引窗口，这些测试不构成线上迁移或完整 Alembic 历史链验证。

### 尚未完成的范围

续作门禁：有效行数 checker 自测 **19 passed**；最终 ratchet **1016 files** 通过，
`git diff --check` 通过。本轮检查的源码/测试/文档均无 UTF-8 BOM；Git 状态没有删除项，
其他 AI 的未提交成果仍保留。两轮独立只读核验覆盖运行控制通道及存储/缓存改动。

原清单仍有全量写接口授权、客户端 HTTPS/角色迁移、RuntimeState/线程化/长任务异步、
captcha deadline、aware UTC/clock/schema、完整 LLM 证据与指令分离、依赖 lock/digest、
完整快照缓存、非 root 浏览器、进程监督，以及第三批结构改造和 CI 等任务。
第三批要求把约 97k 行测试合为不超过 30 个模块，与现行有效行数门禁有直接冲突，尚未
获得修改门禁的明确授权；没有通过删除测试、修改 baseline 或增加排除项规避该冲突。
本次不会将这些剩余项标记已完成，也不进入部署阶段。

## 最新续作：deadline、依赖、CI、LLM 与迁移门禁

本节覆盖上文尚未更新的状态。原清单仍未全部完成；没有部署、重启本地 Crow、NAS、PC2
或人工认证浏览器，没有迁移业务数据库，没有删除整理数据、Cookie、历史事件或发布包。
其他 AI 的工作树改动保留，未执行暂存、提交、回滚、镜像清理或容器卷删除。

### 已实现并验证的新增范围

- #18：`captcha_budget.py` 为 solve 提供 monotonic deadline、取消 Event、有限锁等待。
  retry、preflight、slider、fallback、OS 输入等待改为可中断等待；CDP HTTP/WebSocket
  超时受剩余预算限制；服务器重试与 CDP readiness 共用 deadline。停止后释放已按下的
  CDP 鼠标，保留需要人工恢复的页面，不为清理再发超时网络请求。OCR/native 调用仍采用
  合作式取消，不宣称能强行终止所有底层调用。测试修复了旧模拟时钟与全局状态泄漏。
- #41：增加完整 hash 的 `requirements.lock` / `requirements-dev.lock`，声明 numpy，
  删除已核对无使用的 selenium-wire、requests-toolbelt；Python 3.10 限定有 wheel 的
  onnxruntime 版本。Python、Node 基础镜像及 CI PostGIS 镜像固定到实际查询的 digest。
  Linux 使用 opencv-python-headless，Windows/macOS 保留 opencv-python，避免两个包
  同时拥有 cv2，以及纯 Python slim 环境下图形库缺失造成 OCR 导入失败。
- CI：新增 `.github/workflows/ci.yml`、隔离测试运行器与显式快路径、security、postgres
  分组；快路径超过 60 秒会失败，普通组有 180 秒上限。Python 增量 Ruff/mypy、桌面
  typecheck/test/build、Rust fmt/test 和定时 Playwright smoke 已接入。没有运行 hosted
  workflow，也不将本地结果表述为 GitHub CI 已通过。
- #57 的进程监督部分：新增 `process-supervisor.sh`，等待任一关键子进程退出，使用
  共同 grace deadline 停止并 wait/reap 同组子进程；watchdog 使用实际父 PID。
  两个 browser Dockerfile 和发布包预检均包含 helper。真实 Linux 假子进程以状态 0、7
  退出时，均验证其兄弟进程被收尾回收。没有运行发布脚本。
- #45：删除 import 阶段 secrets.json 读取及全局凭据别名，模型池/selector 首次使用时
  加锁加载，迁移了 data_fixer、auto-tuner 和根目录诊断入口。QualificationStore 按进程、
  绝对路径、凭据与请求策略摘要复用，最多缓存 16 个；共享 store 的 scan_lock 与 SQLite
  lease 共同阻止重叠扫描。取消 slot 等待不会惩罚模型评分；selector 的满容量等待也有
  deadline/取消检查，未知、禁用、空模型池统一报 backend unavailable。
- #20：商品、拍卖、AVM 和资格评估通过共同 EvidencePrompt 保留原字符串调用契约，
  HTTP、资格池及 WebSocket 传输均把固定指令放在 system、来源证据放在 JSON user
  数据字段；转义角色/标签文本，集中输入与输出预算。抓取文本不会拼入 system。
  捕获 wire payload 的测试验证三条传输路径；这不等同于证明模型绝不会受提示注入影响。
  资格版本改为 `collection-exact-v2-evidence`，旧资格记录保留，不复用旧提示的评分。
- #48：生产 auto_create 默认关闭，显式 `FAPAI_DB_AUTO_CREATE=1` 仍可用于空测试库。
  Alembic 接入 Base.metadata；PostgreSQL 元数据补全初始迁移原有的 geom/GiST，过滤
  真正属于 extension 的表。删除 alembic.ini 中隐式数据库凭据默认值，迁移需明确 URL。
  没有改写历史 migration 或创建业务表。SQLite/PostGIS 完整升级链、保留证据以及
  `alembic check` 通过；新增测试列能确实触发 drift 错误，过滤器没有将检查变成空操作。
- #50：除了已有 hybrid JSON/JSONL 缓存，gap audit、optimization progress、action
  effectiveness、manual review 文件快照和校准 JSON 对象检测也接入统一缓存。
  DB receipt 仍实时查询，写入流程不使用缓存。补充了 facade 调用测试并修复克隆函数
  globals 无 snapshots 的真实回归；损坏文件不返回旧成功值，也不改写源文件。
- #43 的裸 except 部分：`src/` 裸 except 已清零，Ruff E722 全目录检查加入 CI。
  全量 print/logging 迁移和其他 broad exception 的分层处理仍未完成。

### 额外数据保护修复

核对异常处理时发现 `update_item_in_json` 和地区列表保存会把损坏 JSON 当空数据继续
写回。新增 `archive_json_io.py`：读取失败或形状非法即报错；序列化、flush、fsync 成功
后才原子替换目标。失败保留确认文件和 `.tmp` 待恢复快照，临时快照不会被 `*.json`
归档扫描误认。测试验证损坏 JSON、非法形状、fsync/replace 失败时原 bytes 不变，以及
成功追加保留其他记录。所有这些测试只写临时测试目录。

### 验证记录与发现的测试环境问题

- LLM/legacy caller 第一轮 **202 passed**；新增证据边界后的综合组修复假响应结构。
- 最近一次包含 LLM、planner、dual-write、entrypoint、server status、归档保护与
  data_fixer 的组合：**483 passed，3 failed**。3 个失败为历史正向 HTTP 测试未携带
  已要求的 operator token；补充合成凭据后针对这 3 项重跑：**3 passed，186 deselected**。
  没有关闭生产鉴权来让测试通过，也没有把分次结果伪称为一次全仓通过。
- Windows 隔离快路径：**100 passed，10.17 秒总耗时**；security：
  **78 passed，2 skipped，13.70 秒总耗时**。跳过的是 POSIX 子进程监督测试，已在 Linux
  实际执行相同责任的测试。
- 真实独立 Postgres/PostGIS 分组：**10 passed，8.84 秒总耗时**。包括五种双 worker
  认领、两种数据库索引保留测试、显式 auto-create，以及 SQLite/PostGIS 完整迁移链、
  数据保留与负向 drift 检测。专用容器 `crow-quality-postgis-bf3b00e4`，仅 loopback
  暴露且没有业务 bind mount；保留随机 schema，没有执行数据库清理。
- Linux 首次测试缺少 jobs 源码挂载，未收集成功；第二次源码直接经 NAS bind mount
  读取，全部快路径测试通过但 **71.20 秒**，正确触发时限失败。将只读挂载的测试源码
  复制到测试容器本地文件系统后，快路径 **100 passed，3.83 秒总耗时**；security
  **79 passed，1 skipped，10.05 秒总耗时**。Linux 跳过的是 Windows launcher 用例。
  容器仅用于测试，未替换任何应用容器。
- cv2 导入实测发现 Linux 安装 full OpenCV 缺少 libxcb；随后调整平台依赖标记并重建
  hash lock。最终全新 Linux 锁依赖安装与 OCR 导入验证结果另见下方追加记录。
- 全 `src` Ruff E722 通过；本轮责任模块 E9/E722/F63/F7/F82/B 通过；
  captcha_budget、llm_evidence_prompt、quality_suites 的 mypy strict 通过。

### 仍未完成的任务

上述结果不代表三批清单全部完成。还包括：全部写接口与 worker/userscript 的统一鉴权；
全链路 HTTPS 与角色凭据迁移；RuntimeState、线程化及长任务异步；aware UTC/clock
和兼容迁移；#47 剩余分页队列全量查询；非删除式容量管理；非 root 浏览器；验证码
指针/选择器抽象；去 FunctionType/import-star、路由表、storage policy 边界、认证码
单一来源、控制器/拓扑合并、桌面剩余 TypeScript 迁移、测试组织及全量 logging。

测试模块不超过 30 个的要求与现行 700 有效行上限冲突，已经提出澄清，尚未获得变更
行数政策的答复。继续保留全部测试、原 baseline 和排除规则，不通过删测试满足指标。
未进入部署阶段；已整理的数据及线上配置仍按用户要求保留。

### 最后一次锁依赖与本地门禁结果

全新 Python slim 测试容器按更新后的 hash lock 安装成功；第一次 OCR 探针因宿主到
bash 的嵌套引号错误未执行，修正测试命令后复用该隔离依赖层，没有改动包来绕过错误。
`crow-quality-headless-final-67d6240c` 在 network=none 下：cv2、ddddocr、numpy、
onnxruntime 全部导入成功，`pip check` 通过；fast **100 passed，3.83 秒总耗时**；
security **79 passed，1 skipped，8.39 秒总耗时**。Windows 验证虚拟环境按同一更新锁
检查 **72 packages compatible**，四个 CV/OCR 模块导入成功。

最终有效行数门禁：checker 自测 **19 passed**；ratchet **1032 files** 通过，
`>1500=1` 为未改变源码的历史基线项，`701-1500=0`、`501-700=0`，无新增豁免。
`git diff --check` 通过；Git 状态 182 个未提交/未跟踪路径，没有删除项，也没有
FPFData/datas/output/secrets/release 路径的版本化变更。已检查变更源码、配置和文档无
UTF-8 BOM。此 Git 检查不等于遍历未版本化业务数据做全量审计。

剩余任务继续以上一节清单为准，尚不能报告“全部优化完成”或开始部署。

## 续作：种子查询、HTTP 路由和存储显式依赖

本节更新前述剩余项的状态。仍未部署、替换容器、重启应用或操作业务数据库。

### 本次已实现

- #47：`seed_scan_candidates.py` 用 SQL 排序和每批 128 条的 keyset 分页读取候选。
  删除认领前全量加载 job/progress 的步骤；只加载类别名称来计算 policy 排序。
  前面的候选被租约、失败冷却、页数上限或其他 policy 阻挡时，继续读取后面的窗口。
  顺序模式仍按区域、类别、job、sort、page 分发；并行模式保留 retry/page 优先级。
- claim 前继续先锁 job，再锁定并刷新当前 progress。独立复核指出初版仍会在锁 job
  后加载全部 sort，已改成只刷新当前候选、分批读取需要检查的前序 sort。
  测试覆盖超过 512 个不可用候选、其他 policy 占满窗口、单 job 超过 512 个 sort，
  并检查实际实例化的 ORM 行数。真实 PostgreSQL 验证 keyset 后续窗口和双 worker 排他。
  全程未删除 job、progress 或业务证据。
- #25 与第三批路由改造：GET/POST 静态路由统一为 `(method, path)` 表，包含 engine、
  settings 和 manual-review 注册项；注册重复路由即报错。仅静态资源和 item ID 保留
  必要的前缀匹配。全部 `_server_*_branch_NN` 改为业务名称，不保留旧名字别名。
- POST/DELETE 使用 `urlparse(self.path).path`，query 仍供 handler 读取；修复
  pause 带 query 被误认为 resume、recovery claim 被误认为 result、manual captcha
  带 query 失去人工处理类型的问题。pause/resume 也读取有大小限制的 JSON body。
  DELETE 先鉴权再解析 body，缺失配置使用统一 fail-closed 错误。
- 测试的路由枚举改读实际路由表；新增对每个 POST 路由携带 query 和非法 suffix 的
  HTTP 检查，以及 pause/recovery 的真实分派检查。旧测试的手工 handler 补充正确的
  Content-Type；只验证错误脱敏的 stub 改发空 body，避免 Windows 未读 body 的连接重置。
- 第三批显式依赖：16 个 repository Mixin 全部移除 `repository_context import *`。
  stdlib、SQLAlchemy、models 和业务 helper 分别从实际来源导入。现有 repository
  门面和 context 的动态导出仍保留，尚未完成整个门面重构。
  readiness 的字段名与聚合结果使用 `zip(strict=True)`，避免今后列数漂移时静默截断。
- CI 新增这 16 个 Mixin 的 import/F401/F403/F405/F821 等检查，以及新路由和候选模块
  的 lint、格式和 mypy strict。实际 `--show-files` 返回 16 个文件，未使用空扫描充当通过。

### 本次验证

- 最后一次存储与 HTTP 综合回归：**298 passed，131.23 秒**。包含 DB dual-write、
  种子队列、generic collection、observer query budget、manual-review store/jobs、
  路由边界、source contract 和 auth stage isolation。
- 最后一次独立 Postgres/PostGIS suite：**24 passed，40.31 秒总耗时**，包含新候选
  窗口测试、原有认领并发、索引、完整迁移及负向 drift 检查。仅使用已核验的
  `crow-quality-postgis-bf3b00e4` 测试容器和新增随机测试 schema，保留测试数据。
- 本轮 security：**83 passed，2 skipped，21.49 秒总耗时**，跳过的是 Windows
  无法执行的 POSIX 监督用例。此结果发生在最后的 Mixin import 调整之前；之后使用
  上述 298 项和 24 项回归验证 import 调整，没有将分次结果拼成全仓一次通过。
- 新模块 Ruff 格式检查及 mypy strict 通过；16 个 Mixin 的增量 lint 通过。
  对旧 server 动态命名空间尝试 F821 会报告既有动态导入符号，本次没有添加忽略规则
  将其伪装为通过；server 本身的 E9/E722/B 检查通过。
- checker 自测 **19 passed**；最新 ratchet **1035 files** 通过，无新增例外；
  `>1500=1` 仍为未改动源码的历史基线，`701-1500=0`、`501-700=0`。
- Git 状态检查为 198 个未提交/未跟踪路径，无删除项，无 FPFData/datas/output/secrets/
  release 的版本化变更；检查到的变更源码、配置、文档均无 UTF-8 BOM。
  此检查未遍历或改写未版本化业务数据。

### 尚未完成，不能部署验收

#47 和 #25 本次已处理。第三批路由的统一资源 404/error envelope、GET 副作用迁移、
全部写接口鉴权及客户端凭据迁移仍未完成。其他剩余项包括 RuntimeState/线程化/异步任务、
aware UTC 与兼容迁移、全链路 HTTPS 和角色 token、非删除式容量管理、非 root 浏览器、
验证码 backend/selector 抽象、其余 FunctionType/import-star 门面、storage policy 解耦、
认证码单一来源、控制器/拓扑收敛、桌面剩余 TypeScript、测试组织及 logging。
仍保留原有效行数政策、全部既有测试和数据；尚未满足“清单全部完成”。

## 续作：认证契约、验证码后端及桌面基础依赖

本次继续修改和隔离验证，未执行部署脚本，未重启 Crow、PC2、NAS 或人工认证浏览器。
未读取或改写业务数据库，未删除 Cookie、资料、备份、release 或历史测试产物。

### 本次已实现

- 第三批认证码单一来源：新增纯模块 `src/auth_recovery_codes.py`，集中活动状态、
  超时原因、失败码、快照可用状态与原有中文桌面提示。NAS、PC1 与 snapshot endpoint
  使用同一份定义；生成器输出 `auth_recovery_codes.generated.ts`，CI 运行 `--check`
  阻止漂移。未知状态/原因及对象、列表等异常 wire 值安全回退，不回显内部诊断。
- TS 消息查询检查自有属性，`toString`、`constructor`、`__proto__` 等输入不能命中
  原型链。保留各阶段及 legacy 的既有语义；本次未退役 legacy 状态机。
- 桌面部署文件列表补入 Python registry；standalone helper 测试在临时目录中使用
  `python -I`，验证不依赖仓库导入回退。只检查部署脚本语法，没有执行部署。
- #44：新增 `captcha_dom.py`，集中 slider/track、验证、预检、重试和 Playwright/OCR
  fallback 的选择器；共享主文档及一层同源 iframe 遍历。保留各调用者原有的选择器
  范围、隐藏 iframe 策略及坐标语义，不扩大 fallback 的匹配范围或递归深度。
  修复 x 偏移为 0 的 iframe 被误标为 main 的问题。
- #44：新增 `OSPointerBackend` 协议及 PyAutoGUI、Win32、uinput 三个实现。
  实际代码中只有三个可选拖拽后端；X11 是坐标映射和残留按键恢复能力，继续独立。
  默认仍为 PyAutoGUI，native/uinput 显式启用；uinput 设备生命周期及可中断反馈
  收敛循环由 solver 持有。构造函数支持注入后端，测试不打开真实输入设备。
- 独立复核发现 OS 拖拽会吞掉 `SolveStopped`，已让停止信号穿过输入初始化、焦点、
  映射和拖拽异常边界。真实 budget 的 deadline/cancel 测试验证：先释放已按下的
  按钮，再由外层关闭 solver 资源并释放锁，不把停止原因改写为一般拖拽异常。
- 第三批桌面依赖：新增 `desktop_value.ts`、`desktop_dom.ts`、`desktop_native.ts`。
  object 不再放在 overview 中，移除 overview/auth_scope 的运行时循环；三个 element
  helper 和 HTML escaping 共用定义；Tauri 检测与调用共用入口并保留方法 receiver。
  native settings/restart 的串行队列和超时策略保持不变。其余 JS 迁移仍未完成。
- desktop smoke 实际运行暴露旧脚本未填凭据就等待暂停成功的问题。现在先验证无
  凭据时不发送控制写请求，再填隔离 fixture 凭据验证暂停/开始；preview 服务同时
  对 pause/start/restart 校验 fixture token。没有放宽产品鉴权以迁就测试。

### 本次验证

- 最后一次认证、stage isolation、standalone bundle、captcha DOM/solver/pointer/
  deadline/X11 聚合回归：**241 passed，97.84 秒**。使用锁定依赖的 Python 3.10，
  临时工作目录、禁用业务 DB、独立数据根和 solver state，关闭真实 OS 输入。
- 快路径：**123 passed，12.78 秒总耗时**，包含新增契约、DOM、pointer 和 bundle
  用例。DOM 测试在 Node VM 中执行实际发给 CDP 的 JavaScript。
- desktop `typecheck` 通过；Node 测试 **34 passed**；Vite build 通过（38 modules）。
  此 build 只生成本地构建产物，未激活 desktop EXE，也未执行 Tauri 发布。
- 浏览器 smoke 首次因缺少 Playwright 对应 headless-shell 版本而不能启动。
  使用已安装 Edge 的独立临时浏览器上下文后，authentication/settings 通过；collection
  暴露上述凭据问题，修正后单独重跑通过（8.3 秒总耗时）。这些是分次验证结果，
  不是宣称修改后的三个 smoke 曾在同一轮全部通过。新建的 UUID 测试目录均保留。
- 新增 Python 模块的 mypy strict、增量 Ruff lint/format、部署脚本 PowerShell
  解析通过；生成 TS 契约与 Python registry 一致。
- checker 自测 **19 passed**；ratchet **1047 files** 通过，无新增例外；
  `>1500=1` 为未改变的历史基线，`701-1500=0`、`501-700=0`。
- Git 检查为 **222** 个未提交/未跟踪路径，无删除项，无受保护数据目录的版本化
  变更；检查到的变更源码/配置/文档无 UTF-8 BOM，`git diff --check` 通过。
  未遍历未版本化业务数据，未用上述 Git 结果声称已做全量数据审计。

### 剩余范围

本次完成认证码单一来源及 #44 的代码改造，并推进桌面共享依赖。仍不能报告清单全完：
全部写接口鉴权与客户端迁移、GET 副作用/统一资源错误、RuntimeState/线程化/异步任务、
aware UTC 兼容迁移、全链路 HTTPS/角色 token、非删除式容量管理、非 root 浏览器、
其余 FunctionType/import-star 门面、storage policy 边界、legacy 协议退役、控制器/
拓扑收敛、剩余 JS/TS 与 lint 门禁、测试组织、logging 等仍需继续处理。
保留数据和现行有效行数门禁的约束不变，部署仍按用户要求推迟。

## 续作：采集客户端凭据绑定与提交确认

本轮已完成的独立部分：

- 新增 `src/collection_api_credentials.py`。配置
  `FAPAI_COLLECTION_WORKER_TOKEN_FILE` 后，HTTP helper 按需读取该 token，使用
  `X-FAPAI-Collection-Token`，只自动附加到 `FAPAI_API_BASE_URL` 指定的同一
  scheme/host/port 和 `/api/` 路径。默认端口规范化、路径边界及异常配置均有测试。
- 自动 worker 凭据不发送给外部供应商、其他端口、CDP 路径或其他 API 前缀。
  对配置目标的远程 HTTP、路径点段及 percent 编码歧义先拒绝，再读取 token。
  支持 HTTPS 或 loopback 隧道；不关闭 TLS 校验。显式传入的既有角色 header 不被替换。
- 这是可选的客户端准备工作：未配置新 token 时维持现有调用；服务端尚未启用
  worker 总鉴权，不能将本项报告为“全部写接口已鉴权”或“全链路 HTTPS 已完成”。
  尚未向任何现有安装写入新凭据，也未修改生产环境变量或 Compose 运行配置。
- `internal_api_http` 的 GET/POST 接入凭据绑定；POST 可复用调用方提供的 session，
  默认仍由 helper 管理无环境代理的 session；全部请求禁止自动跟随重定向。
- `hybrid_seed_collector` 和 `area_followup_persistence` 的直接 POST 改用共享传输。
  修复种子 batch 失败后仍提交进度的问题：3xx/4xx/5xx、错误 envelope、空或无效
  回执均阻止 progress 请求，避免未保存种子时将扫描页标为完成。
- 桌面 helper 打包列表补入新依赖；质量测试运行器清空新 token-file 环境变量，
  防止本机测试意外读取安装凭据；CI 增加新模块的 lint、format、mypy 和负向测试。

本轮验证：fast **153 passed，27.02 秒总耗时**；security **100 passed、2 skipped，
23.50 秒总耗时**（Windows 跳过 POSIX 监督用例）；面积补全回归 **11 passed**。
首次面积回归发现两个旧 FakeSession 未接收 `allow_redirects`，已让 fake 检查禁止
重定向，并补齐真实 response 的 status_code 契约，然后重跑通过。
新增模块 mypy strict、增量 Ruff lint/format 通过；checker 自测 **19 passed**，
ratchet **1049 files** 通过，未修改既有行数规则或 baseline。

### 用户脚本生成产物需要确认

现有安装文件有 **1909** 行有效代码，由 12 个受门禁检查的源文件拼接而成。
源文件均为 58 到 275 行，生成输出必须保持单文件安装。修改鉴权 helper 后重新生成
会违反当前“历史超限文件内容不得改变”的规则。没有擅自放宽规则、排除产品源码、
更新 hash 检查或把未经客户端迁移的服务端鉴权开关提前打开。

具体事实、baseline commit、policy/source hash 和源文件行数已记录到
`docs/plan/userscript-generated-artifact-review-20260921.md`。已请求用户确认是否仅对
这一份可重复生成的安装文件采用生成产物规则，并继续检查全部源文件与生成一致性。
此确认点来自项目 AGENTS.md 的行数政策与现有单文件安装约定，未引用 Skill 来添加审批。

业务数据、资料、Cookie、profile、备份和 release 均未删除，部署仍未执行。
全部写接口的服务端收口和其他未完成结构任务继续保留，清单尚未完成。

## 恢复会话 01a0c1e9：写接口鉴权、客户端与验证续作

本节更新上文过期状态。未部署、替换容器、重启应用或修改业务数据库；没有删除整理
数据、Cookie、profile、备份或 release。已有工作树改动继续保留，没有暂存或提交。

### 已恢复并验证的实现

- 服务端每个已注册 POST 在分派前进入统一鉴权，新增路由默认要求 operator。
  worker、node recovery、operator、engine/settings agent 使用明确角色边界。
  任务认领、resume、replay 和生成报告的旧 GET 返回 405，并提供 POST 替代路径。
  新 HTTP 安全测试遍历全部 POST 路由，验证无凭据和错误凭据不能产生业务副作用。
- 用户脚本使用独立 worker/operator 凭据，绑定配置的 loopback 端口；认领使用 POST，
  session_id 放 JSON body。单文件生成例外已经得到用户确认并实现，详情和完整性 hash
  见 `userscript-generated-artifact-review-20260921.md`。没有扩大手写源码或测试例外。
- 桌面 manual_update/reanalyze/reset_links 经固定 native helper 和 HTTPS operator
  通道发送；浏览器回退须显式凭据，不能向远程 HTTP 发送秘密。Rust action 白名单、
  Python helper、同机代理、打包依赖和前端测试已同步。
- hybrid seed claim 改为共享 POST helper，session_id 不再放 URL；旧 fake session
  同步检查 POST body 和禁止重定向。相关 547 项回归通过，见下文时间边界。

### 本次新增：Python 节点凭据与私有 CA

- `collection_api_credentials.py` 在明确配置的 API origin 下，仅给三个 node-auth
  POST（complete、force_reset、resume_after_cooldown）附加现有 recovery 凭据。
  普通 worker 请求不读取 recovery 文件；其他 origin、端口、CDP 路径不自动获得它。
  缺失、无效或与 worker 相同的 recovery 凭据被拒绝；每次读取支持轮换。
- 显式 supplied 角色凭据继续由调用者负责，不自动升级成其他权限。只有 recovery
  配置时，独立 PC1/helper 的显式传输和普通 CDP 请求不被强制绑定到 collection origin。
  此兼容步骤不等于完成 PC1/PC2/desktop 三角色全部凭据退役和迁移。
- `FAPAI_API_CA_FILE` 为共享 GET/POST 提供私有 CA，仅用于绑定 API；未设置时使用
  正常证书验证，配置文件不存在即失败。真实合成 TLS 测试验证 GET/POST 成功及移除 CA
  后拒绝不可信证书，没有连接线上 API。
- 独立复核发现 requests.Session 会合并旧默认角色 header，已用单请求 None 覆盖
  清除默认 worker/recovery/operator header，再加入本次角色，不修改共享 session。
  supplied session 的 verify=False 不能关闭本次证书验证。测试检查真实 requests
  PreparedRequest 和 adapter options，未用假的字典合并模拟替代 requests 行为。
- `check_server.py`、`unpause_check.py` 改为配置驱动的安全 API 地址和共享传输；
  恢复与认领使用 POST，恢复缺少 operator 文件不发送写请求。测试只使用替代传输，
  本次未实际运行这两个脚本访问应用。
- 隔离测试运行器清空新增 CA 环境变量；CI 增加新角色策略、操作合同和诊断客户端
  的增量 lint/format/mypy 检查。没有运行 hosted CI。

### 新鲜验证与失败边界

- Rust 官方 formatter 已修复中断点的格式错误；`cargo test --locked`：9 passed、
  1 ignored。忽略项为显式安装包在线 probe，本轮未执行。
- 最新 fast：172 passed，23.31 秒总耗时；security：125 passed、2 skipped，
  22.59 秒总耗时。跳过的是 Windows 上的 POSIX 进程监督用例。
- hybrid seed、PC2 solver、standalone desktop bundle：547 passed，50.89 秒。
  此结果在后续 supplied-session 默认 header 清理之前；该清理由上述最新安全组验证，
  不能把不同时点结果拼成一次全仓通过。
- desktop typecheck 通过，Node 36 passed，Vite build 通过；Edge 独立临时 profile
  下 collection/authentication/settings 三条 smoke 同轮全部通过，23.6 秒。
  没有附着、重启或关闭人工认证浏览器，没有生成或激活新的桌面发布 EXE。
- userscript/checker 四个 Node 测试文件：51 passed；ratchet 通过。新 Python 模块
  strict mypy 与增量 Ruff 通过。新增 CI 检查暴露的旧 server_routes 格式问题已用
  官方 formatter 修复，没有关闭检查。
- 扩大到 `test_avm_http_contract.py` 和 `test_server_source_contract.py`：
  **251 passed、110 failed，65.28 秒**。这组未通过，不能报告 HTTP 全量回归通过。
  失败包含仍调用 GET 写路由、未携带新凭据的旧请求、GET-only 数值路由 inventory、
  新错误码契约和依赖 CWD 的源码编译/测试清单检查。需要逐项迁移请求和断言，
  不能用全局替换 urllib 请求或关闭服务器鉴权来隐藏差异。
- 已针对 CWD 问题修正测试根目录解析与 Git cwd；源码编译输出放在测试临时目录，
  避免在工作树产生 pyc。其单独验证结果在下方补充。

### 后续仍需完成

优先收尾上述旧 HTTP 契约和 source inventory；继续检查所有角色客户端及完整 HTTPS
入口/Compose 配置，尚未给任何运行环境写入新凭据或 CA 配置。统一 404/error envelope、
RuntimeState、线程化/异步任务、aware UTC 兼容迁移、非删除式容量管理、非 root
浏览器、其余 FunctionType/import-star、storage policy 边界、legacy 协议退役、
控制器/拓扑、剩余 JS/TS 和测试/logging 改造仍未全部完成。

约 97k 测试行合为不超过 30 个模块仍与现行 700 有效行上限冲突；已批准的单生成文件
例外不授权放宽测试政策。没有删测试或重新生成历史 baseline 来消除该冲突。
清单仍为部分完成，继续遵守全部代码任务完成后再部署测试的要求。

### 本次最后检查

隔离 CWD 下源码编译与测试 inventory 两项定向重跑：2 passed、348 deselected，
35.82 秒。没有重跑或宣称前述 361 项整组已转绿，其余失败仍需处理。
最终 9 个责任模块 Ruff lint/format 通过；ratchet 扫描 1055 个文件通过，
`>1500=0`、`701-1500=0`、`501-700=0`（生成输出按已批准规则单独验证）。
`git diff --check` 通过；255 个未提交/未跟踪路径，删除项 0，受保护数据目录版本化
变更 0，检查到的变更文本无 UTF-8 BOM。这些 Git 检查不等于审计未版本化业务数据。

## 最新续作：旧 HTTP 契约迁移与资源错误状态

本节替代上文“110 failed 仍待修复”和“优先收尾旧 HTTP 契约”的当前状态。
整份三批开发清单仍未完成。未部署、重启应用、访问线上 API 或迁移业务数据库；
没有删除整理数据、凭据、Cookie、profile、备份或 release，没有暂存、提交或回滚。

### 已完成的契约迁移

- 85 处旧 GET 写请求逐项迁移到带明确合成角色凭据的 POST，参数放 JSON body；
  另补齐 12 处原有正向 POST 的凭据。没有猴子补丁改写 urllib 或放宽服务端鉴权。
- 旧 HTTP fixture 把 solver 状态目录绑定到各自临时数据目录，并在结束时恢复环境。
  force-unlock 用例读取正确目录，历史 challenge 状态不再跨测试污染。
- 更新 resume envelope、save-locations 的实际写入失败注入点，以及退役 GET 的
  source inventory；13 个迁移 POST 纳入 JSON 对象请求体检查，28 个旧测试名同步。
- prepare_replay 的 POST alias 使用现有 archive 合同：默认 30 天 / 500 条，
  负数 limit 归零；不增加旧 GET 的 7 天 / 100 条兼容分支。

### 维护操作的写入边界

- 新增 `collection_maintenance_options.py`，统一维护参数的整数与负数处理，
  显式 limit=0 保持为零；超时非正值回到默认值。
- replay/fetch handler 仅在 JSON `dry_run: false` 时允许真实写入与 reload。
  null、0、空字符串及字符串 "false" 均保持 dry-run，避免非法假值意外激活写入。
- `test_maintenance_write_boundary.py` 的 15 个真实 HTTP 用例覆盖三个路由及上述值。

### 资源接口错误状态

- get_item、两个 update_item alias、两个 HTML alias、两个 observer item 入口：
  缺少或空白 ID 返回 400，明确不存在的条目统一返回
  `404 / AVM_DETAIL_ITEM_NOT_FOUND`。
- get_item 数据库查询失败且无缓存时返回 503；已有缓存仍可返回 200。
  observer 存储未启用或缺少详情能力返回 503。服务异常继续返回 500，意外的
  update service 状态不伪装为资源不存在。
- 空任务队列保留 200 与空对象。正常结果 payload 保留原合同。
- 新增 `test_item_resource_errors.py`，覆盖路由 alias、缺参、无存储、资源不存在、
  正常详情、数据库异常缓存回退及非预期 service 结果；已加入 security 和 CI lint。
  独立只读复核确认 detail service 的 id_not_found 与 repository 的 found=false 合同。

### 本次新鲜验证

| 检查 | 结果 |
|---|---|
| 旧 HTTP、source inventory、write access、维护边界、资源错误五文件合并 | 412 passed，27.76 秒 |
| fast 隔离组 | 172 passed；测试 22.95 秒，总耗时 27.39 秒 |
| security 隔离组 | 168 passed、2 skipped；测试 38.46 秒，总耗时 43.91 秒 |
| 有效行数 checker 自测 | 19 passed |
| ratchet | 1058 files；三个超过 500 行的档位均为 0 |
| 维护参数模块和两个新增测试 Ruff lint/format | 通过 |
| 维护参数模块 strict mypy | 通过 |
| git diff --check | 通过 |

security 跳过项仍为 Windows 上的 POSIX 进程监督用例。Python 测试使用新临时目录、
关闭业务数据库并隔离 solver/模型池状态。合并测试最初暴露的 observer 故障注入前置
条件和错误码 inventory 已修复；表中为之后完整重跑结果。新测试的官方 formatter
调整后又通过 security 组，不把第一次失败计为成功。没有运行 hosted CI 或部署验证。

仍需继续完成完整 HTTPS/角色客户端迁移、RuntimeState 与线程/异步任务、aware UTC
兼容迁移、非删除式容量管理、非 root 浏览器、其余 FunctionType/import-star、storage
policy、legacy 认证协议退役、控制器/拓扑、剩余前端 TypeScript 和测试/logging 改造。
测试不超过 30 模块与现行行数上限的冲突仍保留，未扩大用户批准的单生成文件例外。

### 资源查询防御性补充

observer item handler 现在要求详情属性可调用；启用的 repository 若暴露同名非函数
属性，会按存储能力不可用返回 503，而不会落入误导性的 500。新增边界用例后，资源
错误测试为 **30 passed**。未对已有超大 legacy handler 运行全文件 formatter，避免
无关格式化扩散；`git diff --check` 仍通过。

### 凭据目标边界补充

`collection_api_credentials._bound_target` 不再把缺少路径的 API 配置静默补成 `/api`。
现在必须显式配置 `/api` 前缀；根路径和其他路径均在读取凭据前失败。新增两个配置
负向用例后，collection credential 与 node credential 合并测试 **35 passed**。
客户端已有的 session stale-role 清理和私有 CA 验证保持不变；HTTPS 服务端 listener
与 Compose/部署接线仍未完成，不能将 #15 标记完成。

安全隔离组在该约束变更后重新执行：**172 passed、2 skipped，25.56 秒测试耗时**。
跳过项仍为 Windows 上的 POSIX 进程监督用例；没有运行 hosted CI 或线上验证。

## 最新续作：可选 HTTPS API listener

新增 `src/collection_http_server.py`，为 collection API 提供显式可选 TLS listener：

- 证书和私钥必须同时提供，TLS 最低版本为 TLS 1.2；缺少任一文件或证书材料无效时，
  在 runtime 初始化前失败。
- 每个连接在有限握手超时内完成 TLS handshake；明文请求、错误证书和 stalled
  handshake 不会占住 listener。默认未配置证书时仍保持原有 HTTP listener，避免把
  Compose 的 HTTP URL 单独切换成无法连接的 HTTPS。
- `run_isolated_collection_api.py` 增加 `--tls-cert-file` / `--tls-key-file`，
  `docker_entrypoint.build_api_command()` 通过 `FAPAI_API_TLS_CERT_FILE` 与
  `FAPAI_API_TLS_KEY_FILE` 传递；不完整 TLS 配置直接拒绝。
- 新增真实 loopback TLS 测试，验证证书信任、角色鉴权仍在 TLS 下生效、明文被拒绝、
  listener 在异常握手后可恢复以及启动参数传递。测试已加入 security suite 与 CI 增量
  lint/format。此改动没有修改 Compose 默认 URL，也没有部署证书或私钥。

验证：TLS/entrypoint/docker 组合 **47 passed**；新增模块 Ruff lint/format 通过，
`git diff --check` 通过。完整 HTTPS 默认化、Compose secret mount、反向代理和部署
证书供应仍未完成，#15 继续保持未完成状态。

### HTTPS Compose 配置接线补充

collection 与 NAS central API compose 的 API 服务现在显式传递可选的
`FAPAI_API_TLS_CERT_FILE` / `FAPAI_API_TLS_KEY_FILE`。默认值为空，因此不会在没有证书
时改变现有 HTTP 行为；两个服务原有 `/data/secrets` 挂载继续作为证书文件的受控来源，
没有新增公开 bind mount、复制证书或读取运行时 secrets。新增 Compose 文本契约与 TLS
启动组合测试后，相关组 **44 passed**。反向代理、默认 HTTPS URL、证书供应脚本和
worker CA/token mount 仍需后续完成。

### collection worker TLS/角色凭据环境接线

collection compose 中的 12 个 seed/detail/analysis worker 现在都显式接收：

- `FAPAI_API_CA_FILE`，用于已配置 HTTPS API 的私有 CA；
- `FAPAI_COLLECTION_WORKER_TOKEN_FILE`，默认指向共享 secret volume 中的
  `/data/secrets/collection-worker.token`。

默认 API URL 仍保持 HTTP，CA 和 token 环境变量默认为空或受控路径；这不会改变现有
部署行为，也没有生成或写入任何 secret。新增 Compose 计数契约后，`test_docker_entrypoint.py`
全文件 **37 passed**。worker 的默认 URL 切换、token 文件实际供应/权限校验及 NAS/PC2
部署脚本接线仍待完成。

### 异常边界清理补充

扫描 `tools/` 后发现的 3 个旧裸 `except:` 已改为显式异常边界：价格分析日期转换
仅捕获类型/数值转换异常；两个 solver 辅助脚本捕获 `Exception`，不再吞掉
`KeyboardInterrupt` 等进程控制异常。三文件 `py_compile` 通过，当前 `src/` 与
`tools/` 均无裸 `except:`。未扩大改动到无关异常处理或改变 solver 业务流程。

### PC2 worker CA/token 环境接线

`ops/pc2-linux/compose.yaml` 的 `x-common-env` 现在同步传递
`FAPAI_API_CA_FILE` 与 `FAPAI_COLLECTION_WORKER_TOKEN_FILE`，所有 PC2 seed/detail/
analysis worker 通过公共环境块继承同一配置；secret volume 继续只读挂载到
`/data/secrets`。新增的 PC2 Compose 契约用例通过。该文件其余历史部署断言仍有两项
与此前进程监督/浏览器 hotfix 改动不一致，未将失败归因于本次环境接线，也未借机修改
无关部署逻辑。

### 公共状态健康门修复

部署脚本的健康门继续使用无需凭据的 `GET /api/status`，因此公共 recovery 快照现在
保留非敏感的 `enabled` 标志，同时继续剥离 recovery ID、目标和快照摘要。这样健康门
可以验证 recovery 功能已启用，而不会要求部署脚本读取或传递 recovery token。更新了
HTTP guard 回归断言；当前环境没有安装 pytest，本轮只完成 `py_compile` 语法验证，需在
锁定的测试容器中重跑 `test_quality_http_guards.py` 与 `test_nas_centralization_config.py`。

### 搜索任务认领的有界读取

`RepositorySearchMixin.claim_search_task` 已移除对全部活动任务的无界
`scalars().all()`，改为数据库按既有 pending/priority/sort/更新时间顺序排序并以
`yield_per=128` 流式读取，查询本身使用 `FOR UPDATE SKIP LOCKED`，保持双 worker
排他认领语义。当前仅完成 `py_compile` 和 diff 检查；PostgreSQL 并发及大任务集回归
仍需在锁定测试容器中执行。

### collection/worker-node 凭据环境接线补全

默认 collection 的 seed/detail 主服务以及 `docker-compose.worker-node.yml` 的共享环境
现在显式传递 `FAPAI_API_CA_FILE` 和 `FAPAI_COLLECTION_WORKER_TOKEN_FILE`，与已有的
副本 worker、PC2 compose 和只读 `/data/secrets` 挂载保持一致。清除了 collection compose
中两组重复的 CA/token 键，避免 YAML 重复键导致 Compose 解析失败。使用 `FAPAI_NODE_ID`
和临时 `FAPAI_SHARED_DATA_ROOT_HOST` 进行 `docker compose ... config --quiet` 已通过；
尚未切换默认 HTTP URL，也没有供应或复制任何真实 secret。

## 恢复会话 01a0c339：搜索认领与桌面安全配置

此前最后一批搜索认领代码未通过运行验证。本次在锁定的 Python 3.10 环境复现了
5 个失败：空地区优先级生成了非法的 `CASE ELSE ... END`。现已改用 SQL literal，
并将流式查询限制为候选主键；只有实际选中的行才加载 ORM 对象并执行
`FOR UPDATE SKIP LOCKED`，加锁后重新确认状态和租约。有效租约在 SQL 中排除，
迭代结果通过 context manager 关闭。新增 513 行候选队列、跨 policy 窗口、过期租约、
单行物化和真实 PostgreSQL 并发测试，证明一个 worker 持有事务时另一个仍能领取不同任务。

PC1 `RecoveryClient` 现在要求显式安全 API 配置，支持 `FAPAI_API_CA_FILE`，并在每次
请求时重读 token；保留禁用代理和拒绝重定向。公共 Python HTTP helper 对显式传入的
worker/recovery/operator 头同样检查 HTTPS 或 loopback HTTP，关闭无自动凭据配置时
提前返回造成的明文传输绕过。新增真实 TLS、私有 CA、重定向、token 轮换和畸形 origin
测试。没有读取、生成或轮换任何运行中的真实凭据。

桌面配置写入和本地部署准备现在共用 `collection-api-origin.ps1`。省略 API/CA 参数
时保留既有配置；远程明文 HTTP、畸形 origin、不可读或无效安装配置在构建、停止应用和
替换文件之前拒绝。新增 `ApiCaFile` 参数和 Python runtime path 识别，备份范围补入随包
`src/` 文件。`resolve-pc1-auth-python.ps1` 选择一个 Python 应用，修复多个 PATH 命中
被拼成无效命令的问题。测试显式使用具备锁定依赖的解释器，没有放宽产品依赖检查。

### 本批验证

| 检查 | 结果 |
|---|---|
| search policy、新搜索回归、既有 PG 并发组 | 18 passed |
| 完整 postgres 隔离组 | 30 passed，16.08 秒测试耗时 |
| fast 隔离组 | 174 passed，11.57 秒测试耗时，13.25 秒总耗时 |
| security 隔离组 | 208 passed、2 skipped，43.82 秒测试耗时 |
| 安装配置、Python resolver、launcher 定向组 | 23 passed |
| fixture/lint 修正后搜索、TLS、安装配置、runtime config 复验 | 43 passed，29.16 秒 |
| 有效行数工具测试 | 19 passed |
| ratchet | 1065 个文件；501-700、701-1500、超过 1500 均为 0 |
| 本批 8 个 Python 文件 Ruff lint/format、UTF-8 无 BOM | 通过 |
| `collection_api_credentials.py` strict mypy | 通过 |
| `git diff --check` | 通过 |

security 的两个跳过项是 Windows 上的 POSIX 进程监督测试。PG 使用已核验的无业务挂载、
仅 loopback 端口、`crow.purpose=quality-regression` 专用测试容器；每次创建独立 UUID
schema 并保留，没有接入业务库。测试套件运行器的定向列表需要文件名，初次误传
`tools/test/` 前缀导致路径重复，纠正后得到上述 43 passed。

完整 lint 初次发现新测试的 fixture 导入、UTC 调用和 subprocess check 参数问题，
以及 runtime config 的格式差异，均已修正。没有修改行数 baseline、排除项或批准例外。
四个只读子代理均因默认模型渠道返回 HTTP 503 失败，本批没有独立代理复核证据。

## 恢复会话 01a0c3a2：共享认证维护入口安全收口

继续保留未部署、未注册计划任务和未修改业务数据的边界。只修复共享认证维护脚本中
仍遗留的远程明文默认地址：`register-pc1-shared-auth-maintenance.ps1` 现在要求显式
API origin 或环境变量，复用 `collection-api-origin.ps1` 的 HTTPS/loopback 校验，并将
可选私有 CA 文件传递到 NAS 恢复任务注册器。脚本在 CA 文件不存在时提前失败，不会
创建计划任务。测试补充默认值、来源校验、旧远程地址不存在及 CA 参数传递断言。

PowerShell AST 解析通过；本机 Python 环境未安装 pytest，定向 pytest 尚未执行，需在
锁定测试环境中运行 `tools/test/continuous_collection_scripts_test_part_01.py`。没有运行
部署脚本或写入任何真实凭据。

## 继续收口：数据修复器浏览器启动边界

`src/data_fixer_app_part_03.py` 原先将记录中的 URL 拼接进 `start "" "..."` 并以
`shell=True` 执行。现在仅接受带 host 的 HTTP/HTTPS URL，拒绝控制字符、引号和其他
协议，并通过 `webbrowser.open` 打开，避免记录内容进入命令解释器。新增静态回归测试
锁定无 shell 命令拼接和 URL 校验。未改变整理数据、浏览器 profile 或运行配置。

同时修复 detail 调度器的线程竞态：`next_task`、`next_visit_task` 和 `batch_tasks` 在
冷却检查与写入 `dispatched_tasks` 之间使用共享锁，避免多个 HTTP worker 同时派发同一
条目。新增双线程回归测试；没有改变持久化数据或冷却策略。

另外收紧 `watch-pc1-auth-auto-resume.ps1`：删除远程 HTTP 默认地址，改为显式 API
配置并复用统一 origin 校验。未配置或配置为非 HTTPS/非 loopback HTTP 时，在发出请求
前失败；新增脚本契约断言。

同样收紧 `trigger-taobao-login-recovery-if-needed.ps1` 的状态检查路径：删除其远程
HTTP 默认地址，复用 HTTPS/loopback origin 校验，避免计划任务在缺少配置时把凭据和
状态请求发送到固定远程地址。

同时修复 legacy Flask facade 中的 `/api/next_task` GET 副作用：任务认领路由现在仅保留
POST，与主 server 路由和已退役 GET 合同一致，避免浏览器预取或跨站 GET 推进共享任务状态。
新增路由方法回归断言。

桌面端 API 默认地址也完成第一步收敛：浏览器无法推导 origin、Tauri 配置缺失时只回退
到 loopback `127.0.0.1:8001`，不再回退到硬编码 NAS 远程 HTTP 地址。Rust、前端和
CSP 同步更新，并新增默认值测试；远程 NAS 使用显式运行配置提供地址。

detail service 的两个运行时 `print` 也已迁移到模块 logger：HTML 持久化使用结构化
`info`，LLM 推断失败使用 `logger.exception` 保留堆栈，同时维持原有失败事件和返回
契约。新增源码回归断言，未改变业务数据。

solver stale-auth 预检异常也改为 logging exception，保留原有“故障隔离后继续释放提交
令牌”的状态机行为，避免异常文本直接写 stdout。新增源码回归断言。

AVM 配置加载器的启动、热重载和 watcher 日志也已从 `print` 迁移到模块 logger；失败
路径使用 `logger.exception` 保留堆栈，配置 fallback 行为不变。新增结构化日志回归断言。

detail dispatch 时间戳改用 aware UTC clock；为兼容历史/测试传入的 naive timestamp，过期
计算会按 UTC 解释后再比较。新增时钟回归测试，尚未扩展到整个 storage schema 的 UTC
迁移。

storage canonical record 和 seed collision repair 的生成时间也改用 `timezone.utc`；修复
receipt 继续输出兼容的 `Z` 格式，避免改变现有外部契约。新增 storage UTC 源码契约测试，
数据库列类型和其余时间调用仍需后续迁移。

collection stage state 和 generic product adapter 的默认时间也改用 UTC-aware clock，
并新增默认时间源码契约测试。调用方显式传入的时间保持原有优先级。

repository context 的内部 clock 现在优先调用 aware `clock.now(timezone.utc)`，仅在兼容
旧 facade/test clock 时回退到 `utcnow()`；租约和 cooldown 仍按统一 UTC 归一化比较。新增
clock 契约测试，尚未改变历史数据库列的 naive 存储格式。

PC2 browser image 现在创建固定 UID/GID 的 `fapaifang` 非 root 用户并以该用户运行
启动器；部署脚本的 host-display 授权改为可配置用户，删除对 root 的硬编码。挂载的
profile、output 和 bridge-control 目录在镜像内预先授权。这样 Chrome 不再以 root 和
`--no-sandbox` 组合运行；实际 Docker 构建和 host-display 运行仍需在 PC2 发布窗口验证。

同时清除 `tools/pc2_solver_context.py` 中的远程 NAS API 默认拓扑，运行环境未提供地址
时仅回退到 loopback，生产远程地址必须由 Compose/runtime env 显式注入。新增源代码契约
测试，未改变现有显式 API 参数行为。

collection API listener 现在基于 `ThreadingMixIn` 提供 daemon request threads，并设置
`block_on_close=False`，避免慢客户端或同步 handler 阻塞其他请求和进程关闭。TLS handshake
的既有限时仍保留；新增 server 契约测试。真实长任务异步化和 PC2 发布验证仍需后续完成。

本批没有部署或重启 Crow、PC1 人工认证浏览器、PC2、NAS；继续遵守全部代码任务完成
后再部署测试的明确要求。#15 的剩余 PowerShell 客户端、角色隔离和证书供应，以及
RuntimeState、异步长任务、aware UTC 迁移、非删除式容量管理、非 root 浏览器和第三批
其他结构任务仍需继续。测试不超过 30 个模块与行数上限的冲突尚未获得新的政策决定。

## 2026-09-22：API 并发与后台任务回执

本批继续推进 #17，保留现有未提交成果。未部署或重启 Crow、PC2、NAS、人工认证
浏览器；未连接业务数据库，未修改运行配置、凭据、浏览器 profile 或已整理数据。
没有提交代码、删除文件、重新生成行数 baseline 或新增策略豁免。

### 已实现与复现证据

`collection_http_server.py` 原先即使启用了 ThreadingMixIn，TLS handshake 仍在
`get_request()` 中占用监听线程。真实 socket 回归先复现一个不完成握手的连接阻塞
另一个可信客户端，再将握手移入请求线程。握手 5 秒超时、HTTP handler 30 秒超时和
失败连接清理均保留；阻塞 handler 与半截请求头也改用真实并发测试验证。

新增 `collection_jobs.py`：每个 API 实例一个 FIFO worker，活动任务上限为 8。
queued 回执先通过原子 JSON 写入，再确认提交和执行。支持完成、失败、取消和查询时
识别 interrupted；重启后不自动重放可能已经产生写入的任务。失败时保留已确认的
回执、报告及待写快照，错误原文只进入日志。额外复现了“worker 已取出任务，关闭 API
后仍开始执行”的竞态，并补上启动前的关闭检查；对应测试由失败转为通过。

`collection_maintenance_jobs.py` 在入队前捕获服务、数据目录和规范化参数，承接近期
重放、归档重放、补抓详情及维护工作。维护报告先原子发布，需要时再重载数据。
只有明确的 JSON `dry_run: false` 才允许修改维护对象，`limit: 0` 不会被默认值覆盖。

11 个维护/pipeline 入口及别名现已返回 HTTP 202 与 `job_id`、`status_url`；新增
`GET /api/collection/jobs?id=...`，读取结果同样要求操作员鉴权。任务在后台完成后，
原响应内容位于回执的 `result`。Pipeline 在队列 worker 内同步执行，只有实际返回
`completed` 才记为成功；`already_running`、`started`、失败或缺少状态都不会误报完成。
默认 pipeline 数据目录也与配置的 AVM 服务目录保持一致。完整契约和恢复规则见
[`collection-async-operations.md`](../collection-async-operations.md)。

`_post_save_locations` 另有一个被线程化暴露的读改写竞态：测试强制第二个请求先写入，
第一个持有旧快照的请求随后覆盖它，丢失第二个地区。为整个读、合并、写入段加入
共享 FILE_LOCK 后，两个请求和原记录均保留；9 项归档保留测试通过。

旧 AVM HTTP 测试现在显式检查 202，并在 mock 和临时目录有效期内完成带鉴权的轮询。
保留空请求体、参数边界、错误码和报告内容检查。路由源码门禁跟踪真实委派方法及维护
参数准备函数，并带递归访问保护；没有删除路由覆盖或添加检查排除项。
队列及源码门禁已加入 fast，真实 HTTP 任务测试加入 security，新模块加入 CI
Ruff/formatter/strict mypy 检查。

全组门禁还捕获了两处此前未闭环的问题：LLM 提取函数被克隆到 `llm_helper` 后缺少
logger，触发 NameError；桌面配置成功测试没有创建传入的 CA 文件。补齐 logger、创建
明确的测试 CA 路径 fixture，并新增“CA 缺失时原配置字节不变”的负向测试，保留生产
配置写入器原有的拒绝行为。相关 LLM、风险提取、配置组 51 项通过。

### 最终验证

| 检查 | 结果 |
|---|---|
| fast 隔离组，含队列与路由源码门禁 | 198 passed；20.46 秒测试耗时，22.74 秒总耗时 |
| security 隔离组 | 255 passed、2 skipped；69.14 秒测试耗时 |
| 新队列、HTTP 任务、维护写入边界、完整 AVM HTTP 契约和源码门禁合并组 | 418 passed；29.66 秒测试耗时 |
| 关闭竞态修复后的队列与 HTTP 定向组 | 41 passed |
| LLM 与配置修复定向组 | 51 passed |
| 有效行数工具测试 | 19 passed |
| ratchet | 1088 个文件；501-700、701-1500、超过 1500 均为 0 |
| 13 个新模块/定向测试的严格 Ruff 规则集、14 个文件 formatter 检查 | 通过 |
| 本批 Python 文件 E9、E722、F63、F7、B 检查 | 通过 |
| 队列、维护准备、HTTP listener 三个模块 strict mypy | 通过 |
| 本批 30 个源码、测试、配置与文档 UTF-8 无 BOM 检查 | 通过 |
| `git diff --check` 与工作树范围复核 | 通过；无删除、无暂存、无受保护数据目录的 tracked 变更 |

security 的两个跳过项仍为 Windows 上的 POSIX 进程监督测试。表内各组有交集，不能
相加为独立用例总数。API 合并组使用 `scripts/run_quality_tests.py` 的隔离入口，在
进程内临时注册 `test_collection_jobs.py`、`test_collection_job_http.py`、
`test_maintenance_write_boundary.py`、`test_avm_http_contract.py` 和
`test_server_source_contract.py`；没有直接从业务运行目录启动 pytest。
最终工作树共有 329 条未提交/未跟踪路径记录，其中包含开始时的 322 条既有记录。
Git 的 LF/CRLF 提示不影响空白检查结果；没有为消除提示修改仓库换行配置。

本轮 4 个只读子代理均因默认模型渠道 HTTP 503 在启动时失败，没有取得独立代理
复核证据。没有运行新的 PostgreSQL、桌面构建或安装后验收；本批未改这些运行产物。

### 仍待推进

#17 的人工审核回执 sync/async 提交路径已统一进入通用 CollectionJobManager；旧
ManualReviewMaintenanceManager 仍仅作为历史查询兼容层保留，其他同步报告入口尚未
迁移，不能把所有长操作标记为完成。下一步仍需处理 solver/pause/队列的锁定状态对象
与 RuntimeState、aware UTC 数据库迁移、其余 HTTPS/角色凭据部署及证书供应、非删除式
容量管理、非 root 浏览器运行验证和第三批结构任务。测试模块数量与现行行数策略的冲突
继续保留为待决定事项。完整优化清单维持“部分完成”，全部代码任务完成后再部署测试。

### 2026-09-22：显式 async 回执队列与 Alembic metadata parity

显式 `mode: async` 的人工审核回执已改为提交到通用 `CollectionJobManager`，不再在
请求线程直接执行维护，也不再创建独立的 `ManualReviewMaintenanceManager` worker。
提交使用固定的 32 位十六进制任务 ID，仍返回旧客户端需要的 HTTP 200、
`maintenance_job_id` 和 `maintenance_job_status`，并额外提供通用 `job_id`/`status_url`。
旧的 receipt jobs 查询接口会合并读取这类通用回执；通用队列增加了持久化 receipt 列表、
显式任务 ID 防重和 `interrupted` 终态校验。异步队列拒绝时不会先写审核记录。

Alembic offline 配置现在按 URL backend 选择与 online 相同的 dialect-specific metadata；
schema gate 继续从 `20260905_0011` 升级到当前 `head`，并验证新增 `0012` 查询索引和
证据字段保留。定向验证：collection job tests `11 passed`，schema/index gate
`3 passed, 2 skipped`。AVM HTTP 契约已将显式 async 的拒绝路径改为模拟通用
`CollectionJobManager` 容量错误，当前 `350 passed、1034 subtests passed`。

storage 的 UTC 时钟另外增加了 `use_repository_clock()` context injection。它在请求或
测试上下文内优先使用显式 callable，并继续把 aware UTC 值规范化为现有 schema 使用的
UTC-naive 值；未注入时才走旧 facade clock 兼容路径。行为测试覆盖 aware 值规范化和
上下文退出后的恢复，尚未把全部 collection/AVM 直接 `datetime.now()` 调用迁移到该
接口。

### 2026-09-22：种子数据库异常传播与 savepoint 回归

`SeedCollectionService.submit_batch()` 现在不会把 `get_flat_item()` 的数据库异常当作
“没有已有记录”。查询失败会先记录结构化异常日志，再原样向上传播，避免数据库不可用
时继续走新项目写入路径。新增隔离回归测试确认异常会阻止持久化回调。

种子队列的通用方言 `begin_nested()` 分支新增了实际回归覆盖：测试将 SQLite fixture
的 dialect 名称临时切换为通用分支，模拟并发重复插入并验证 savepoint 回滚后外层事务
仍可继续写入 occurrence。生产代码未改变，也没有触碰业务数据库。

PC1 recovery 状态码映射已有 `requested_timeout`、`pc1_claimed_timeout`、
`desktop_manual_takeover` 和 `recovery_unknown` 的统一回归覆盖；#52 因而具备当前
代码证据。#28 的跨平台 FPFData 路径解析和 #36 的桌面编辑值类型边界也已由现有
Linux/UNC/TypeScript 测试覆盖。完整清单仍保持“部分完成”，RuntimeState、HTTPS
部署与真实 PC2/NAS 运行验证继续未完成。

同时收口了 solver 状态读取的一处并发窗口：`_captcha_solver_runtime_status()` 在同一
把 `SOLVER_LOCK` 下复制运行标志、队列标志、开始/结束时间、状态、失败原因、暂停原因、
最后请求和 challenge ID，再在锁外组装持久化 scope 信息。这样一次 status 响应不会把
一轮 solver 的字段拼成跨执行快照；完整 `RuntimeState` 写入 API 以及所有旧全局写点
仍待继续迁移。现有 collection status 与 solver ownership 回归共 `81 passed`。

### 2026-09-22：collection runtime snapshot 与 UTC fallback

新增 `_collection_runtime_snapshot()`，统一在一次读取中采集 solver 状态、有效暂停状态、
认证恢复快照和 collection scope。轻量 status 与完整 collection status 现在复用该快照，
避免分别读取这些跨线程状态后拼出不一致响应。新增回归验证 solver 与 recovery snapshot
各读取一次，相关 status/source-contract 组共 `91 passed`。

`GenericProductAdapter.partition_key()` 的无日期 fallback 也改为使用 aware UTC 日期，
不再依赖本地时区的 `date.today()`。collection UTC 默认值测试已补充该边界。数据库历史
列仍保持 UTC-naive 兼容格式，完整 schema timezone 迁移尚未执行。

### 2026-09-22：solver execution snapshot 与 recovery malformed-state guard

`SolverExecutionState` 新增只读 `snapshot()`，在同一把状态锁下复制当前 execution 的
身份、epoch 和取消/替换标志，同时保留 `owns()` 所需的真实 execution 对象。该 API
为后续 RuntimeState 收口提供兼容边界，没有迁移现有全局写入点，也没有改变 replacement
run 的所有权语义。新增空状态、激活、取消和清理回归覆盖。

PC1 desktop recovery 对 NAS 返回的 malformed 顶层或阶段字段改为 fail-closed，统一返回
`recovery_unknown`，不会因 `None`、数组或字符串状态触发属性错误，也不会把未知 recovery
ID 误报为 `challenge_changed`。现有 timeout/manual takeover 映射继续由统一状态码模块
提供。定向 recovery 与 solver ownership 测试共 29 项通过；完整清单仍保持“部分完成”，
RuntimeState 写入迁移、HTTPS 部署和真实 PC2/NAS 运行验证仍未完成。

本轮重新运行 collection UTC、seed service/savepoint、collection status snapshot 和 solver
ownership 合并回归组，共 `103 passed`；结果未改变上述剩余范围。

桌面设置轮询另外收口：只有请求传输阶段的失败会消耗连续轮询失败预算；成功取得状态
后若 `effective` 配置不符合响应契约，错误仍会显示给操作员，但不会把轮询重试计数误判
为网络故障。`collector-desktop` 的 TypeScript 类型检查和 37 项测试全部通过。

请求体边界继续收口：collection settings、engine restart 和 desktop auth 三类仍直接
读取 `Content-Length` 的入口现在统一使用 `_read_limited_body()`。非法、缺失、超限或
不完整 body 都会进入现有 400 错误路径，不再让 `KeyError` / `ValueError` 逃出 handler。
HTTP guard、写入权限和路由边界定向组共 `57 passed`。

第三批结构任务开始收口认证恢复状态码来源：PC1 desktop recovery、desktop auth 和
shared auth 现在复用 `auth_recovery_codes.py` 中的 challenge/unknown 常量，减少跨端
硬编码字符串漂移。相关恢复、阶段、NAS 和代码生成测试共 `80 passed`；server facade
仍保留兼容重绑定，尚未完成全量 FunctionType/import-star 重构。

## 2026-09-22：solver 执行状态集中管理

本批推进第二批的带锁状态对象与第三批的显式状态依赖，保留已有未提交成果。
继续遵守“全部代码任务完成后再部署测试”的要求；没有部署、重启 Crow、PC2、NAS
或人工认证浏览器，没有迁移业务数据库、修改运行凭据或删除整理数据。

### 已完成的状态迁移

`SolverExecutionState` 现在同时持有执行身份、运行标志、提交令牌、起止时间和结果状态。
已移除 `server_context` 中以下六个独立全局变量，未增加旧字段转发或镜像状态：

- `SOLVER_RUNNING`、`SOLVER_PENDING_TOKEN`、`SOLVER_START_TIME`。
- `SOLVER_LAST_STATUS`、`SOLVER_LAST_FAILURE_REASON`、`SOLVER_LAST_FINISHED_TIME`。

生产写入统一使用 `reserve`、`release`、`activate`、`record_outcome`、`finish`、`clear`
及人工状态方法；这些方法在对象自己的 RLock 下完成成组更新。提交令牌只允许持有者
释放或激活，过期令牌不能消费新的提交；带执行身份的结果与完成操作拒绝旧执行，两个
执行具有相同时间戳时也不会混淆。清理会通知旧执行取消和被替换，并保留已确认的结束
时间。状态接口、重试、报告和恢复入口改为读取同一对象的快照。

服务器执行、派发、人工认证、Cookie 恢复与控制入口已迁移到这些方法。源码核对确认
`src/server*.py` 中不再引用上述六个旧全局，也没有直接给对应对象字段赋值。现有
HTTP 响应合同和阶段隔离继续由行为回归验证。

HTTP fixture 每次注入独立的执行对象及其锁；旧测试直接配置对象字段，不再依赖被
删除的全局变量。新增八线程竞争提交、旧令牌释放/激活、同时间戳执行替换、清理后
迟到结果与结束时间保留的回归。原有假替换执行改用真实 `begin()`，同时覆盖身份取消。

扩大回归时发现一条历史 force-reset 正向测试没有传入已经要求的 recovery 凭据，
因此实际先返回 403。现在分别检查无凭据时的 403，以及携带合成测试凭据后业务拒绝的
409；没有降低服务端鉴权要求。

### 新鲜验证

测试复用经 `uv pip sync --dry-run --require-hashes` 核实的 Python 3.10.11 专用环境，
72 个锁定依赖无需改变。Python 用例全部经 `scripts/run_quality_tests.py` 从新临时目录
运行，关闭业务 DB，隔离数据根、solver 状态、模型池及凭据环境，并保留默认网络隔离。

| 检查 | 结果 |
|---|---|
| 改动前 solver 所有权、采集状态、阶段隔离基线 | 108 passed |
| 状态迁移后同一基线 | 108 passed |
| 最终 solver、完整 AVM HTTP、源码合同、认证恢复/阶段及控制链路合并组 | 517 passed，35.66 秒测试耗时，37.59 秒总耗时 |
| fast 隔离组 | 212 passed，21.75 秒测试耗时，23.66 秒总耗时 |
| security 隔离组 | 272 passed、2 skipped，73.59 秒测试耗时，75.45 秒总耗时 |
| 有效行数 checker 自测 | 19 passed |
| ratchet | 1092 files；501-700、701-1500、超过 1500 三档均为 0 |
| 状态对象及所有权测试的严格 Ruff lint/format | 通过 |
| `solver_execution_state.py` strict mypy | 通过 |
| 其余责任文件的增量 lint | 28 个文件 E9/E722/F63/F7/F82/B 通过；context 见下方说明 |
| 本批 29 个 Python 文件 UTF-8 无 BOM 检查 | 通过 |
| `git diff --check` 与工作树范围复核 | 通过；无删除、无暂存、无受保护数据目录的版本化变更 |

合并组先出现的 `516 passed, 1 failed` 已由上表的完整重跑替代。各组存在交集，不能将
用例数相加。security 的两个跳过项仍为 Windows 上的 POSIX 进程监督测试；没有运行
新的 PostgreSQL、桌面构建、hosted CI 或安装后运行验证。

额外对全部责任文件尝试 F82 检查时，`server_context.py` 的两个既有动态依赖
`_real_taobao_auto_solver_enabled`、`_normalize_challenge_scope` 仍报告 F821；本批仅从
该文件删除六个状态声明，没有改写这两处函数。其 E9/E722/F63/F7/B 检查通过。没有添加
忽略标记或修改 CI 规则把动态门面问题隐藏为全量 lint 通过。

两个只读子代理均因默认模型渠道 HTTP 503 未能启动，本批没有独立代理复核证据。
最终源码、调用点、测试、行数和 Git 范围由主线程核对；历史代码图没有作为当前实现证据。

### 仍待推进

本批完成了执行状态这一项归属迁移，完整 RuntimeState 仍未完成。暂停原因、阶段
challenge、人工恢复 epoch 与重试计数、SEEN_IDS/PENDING_TASKS 等仍需继续迁移；
`FunctionType` 门面和其余结构任务仍在。HTTPS/角色凭据供应、aware UTC schema、
非删除式容量管理、PC2 浏览器实际验证及测试组织政策冲突也未由本批解决。
完整优化清单继续标记“部分完成”，部署继续延期。

### 2026-09-22：文件处理占用状态收口

新增 `CollectionProcessingState`，把后台 detail 文件的去重占用从裸集合移入
`RuntimeState.processing`。`claim()` 在一次锁内完成检查与登记，`release()` 在
提交完成、提交失败和 detail 处理收尾路径统一释放；扫描器和服务层继续接收
`MutableSet` 兼容接口，因此不改变现有回调合同。旧的 `CURRENT_PROCESSING` 只保留
为兼容别名，生产读写已经改走 `RUNTIME.processing`，避免扫描线程与 HTTP/后台线程
在检查和登记之间重复提交同一文件。

认证完成回执的内存确认集合也已并入 `SolverRecoveryState`。持久化 JSON 仍是回执的
跨进程来源，运行时状态只保存受锁保护的副本并按既有 256/192 条上限裁剪；旧发布
字典在测试或兼容调用被替换时会在下一次操作同步到 `RUNTIME.recovery`，不会形成
第二个生产真相源。

Cookie 快照刷新状态和后台线程句柄也已由 `RuntimeState.cookie_snapshot` 持有；调度、
轮询状态与写入更新共用同一把运行时锁。历史 `AUTH_COOKIE_SNAPSHOT_STATE` 发布名在
被替换时只执行一次兼容同步，并重置旧线程句柄，防止测试或热重载复用失效 worker。

`CollectionRuntimeIndex` 现在持有 `SEEN_IDS`、`PENDING_TASKS` 和
`DISPATCHED_TASKS` 的默认容器，`DATA_LOCK` 与索引锁绑定；旧发布名仍作为兼容别名，
后续调用点可以逐步改为 `RUNTIME.collection` 的原子方法。当前仍保留旧 handler 的
可变 dict/list 合同，尚未宣称所有调用点都完成显式依赖注入。

Runtime 生命周期的 `started_at` 与 `initialized` 也归入 `RuntimeState`；初始化只在
状态对象未启动时执行，健康接口通过兼容读取器读取旧发布时间，既支持历史测试注入，
也避免再增加一组独立可变全局。

新增并发回归验证八个 worker 只有一个成功 claim，重复 add/release 不会残留占用；
定向 collection/runtime/solver 回归 **20 passed**，随后 collection state 与 runtime
回归 **9 passed**。新增源码和测试完成 `py_compile`；有效行数 checker 自测 **19
passed**，ratchet **1101 files** 通过，`git diff --check` 通过。Ruff/mypy 命令在
当前 `venv` 中不可用，未把缺少工具报告成通过。

续作门禁补充：在当前隔离质量入口重新运行 fast 套件为 **220 passed**（21.93 秒测试
耗时，24.86 秒总耗时）；security 套件为 **272 passed、2 skipped**（67.39 秒测试
耗时，68.67 秒总耗时）。security 的两个跳过项仍为 Windows 上的 POSIX 进程监督
测试；末尾的 HTTP 测试线程异常只来自测试服务器关闭阶段，没有失败用例。两组均由
`scripts/run_quality_tests.py` 创建临时数据根运行，未连接业务数据库。

该批只收口文件处理占用状态，不表示 `SEEN_IDS/PENDING_TASKS`、完整 RuntimeState、
HTTPS 证书供应、数据库 UTC schema 或部署验收已经完成。

### 2026-09-22：collection index 兼容别名同步与共享鉴权锁

`CollectionRuntimeIndex.bind_legacy_aliases()` 现在在索引自己的 RLock 内吸收
`SEEN_IDS`、`PENDING_TASKS`、`DISPATCHED_TASKS` 被 facade 或旧测试重新绑定的容器，
保留原对象身份，不复制或丢弃调用方注入的数据。`server_context._collection_runtime_index()`
会在运行时入口重新发布 state-owned 容器和 `DATA_LOCK`；`load_data()`、detail 文件处理、
运行时条目驱逐以及 seed batch 提交已改用该索引的容器。这让新路径依赖 `RuntimeState.collection`
，同时保留既有 handler/service 的 dict/list 参数合同和旧测试的可替换 seam。

`AUTH_COMPLETION_LOCK` 与 `AUTH_COOKIE_SNAPSHOT_LOCK` 的兼容发布名现在分别指向
`RuntimeState.recovery`、`RuntimeState.cookie_snapshot` 的共享 RLock。确认回执和 Cookie
快照的状态读写不会再因独立模块锁与状态锁分离而产生竞态；现有线程句柄和旧状态字典的
替换兼容逻辑保持不变。认证完成 finalize 使用的串行锁也已归入
`SolverRecoveryState.finalize_lock`，保留原有独立锁的串行语义。HTTP 测试 fixture 同步
注入新 RuntimeState 的对应锁和 `DATA_LOCK`。

验证：RuntimeState 与 collection runtime 定向组 **13 passed**；旧 collection status
兼容组 **24 passed**；fast 隔离组 **220 passed**
（20.94 秒测试耗时，21.86 秒总耗时）；security 隔离组 **272 passed、2 skipped**
（66.34 秒测试耗时，67.33 秒总耗时）。本轮修改的 Python 文件 `py_compile` 通过，
有效行数工具测试 **19 passed**，ratchet **1101 files**（501-700、701-1500、超过 1500
均为 0），`git diff --check` 通过。当前 `venv` 仍未安装 Ruff/mypy；使用临时 `uv run`
环境对新增 RuntimeState 文件和测试执行 Ruff lint/format、对 `collection_runtime_index.py`
与 `runtime_state.py` 执行 strict mypy，均通过。责任范围的完整旧文件 lint 仍保留
`server_context.py` 中既有的两个动态依赖 F821，以及历史 formatter 差异，未通过放宽规则
隐藏。未部署、重启本地 Crow、连接业务数据库或修改已整理数据。


### 2026-09-22：seed scan 维护分页与 PC2 recovery token 校验

archive_seed_scan_jobs_except() 现在按稳定的 job_key keyset 游标和 128 行窗口读取 stale jobs；每个窗口先按既有 policy ownership 过滤，再按 progress_key 以同样窗口归档 progress。job 与 progress 仍在一个事务内更新，保留已归档行不重复计数、lease 清除、跨 policy 不归档和三字段返回合同；窗口结束后释放 ORM 引用，避免长生命周期 worker session 保留整个旧队列。

新增回归测试覆盖 257 个 stale jobs/progress 的窗口边界、identity map 峰值不超过两个窗口、lease 清除和第二次调用计数为零。此前完成的 release_seed_scan_worker_leases() 也继续使用 128 行窗口，并保留 job 状态刷新；observer-region reset_seed_link_region() 现在同样按 job_key/progress_key 窗口重置，仍保留单事务和 collected item/occurrence 不变。

tools/pc2_auth_recovery.load_recovery_token() 现在与 PC1 recovery client 使用相同的 fail-closed 格式合同：去除文件首尾换行后，token 必须是 16 至 4096 个 ASCII 非空白字符；空文件与非法格式分别保留明确的 ValueError。测试覆盖 16/4096 边界、首尾换行、中间空白、非 ASCII 和超长/过短 token。

本批验证：seed_queue_repository_test_part_02.py 8 passed，加上 test_seed_maintenance_windows.py 2 passed；seed candidate/release 组合 23 passed、2 skipped；PC2 recovery 14 passed；effective-code-lines 19 passed、ratchet 1102 files；相关 Python py_compile 与 Ruff 规则检查通过，git diff --check 通过。责任文件仍存在历史 Ruff formatter 差异，未做全文件无关格式化；未部署、重启本地 Crow 或接触业务数据。

### 2026-09-22?legacy detail dispatch ? UTC ????

legacy detail task/status ???????? aware UTC ??????? cooldown ???
???? naive dispatch timestamp ? UTC ????? DB/detail service ???? aware
????????????? naive ??????? aware/naive ????????????
? aware UTC??????? naive/aware ????legacy ???????????? aware
?????????

???legacy dispatch ? detail service ??? **5 passed**????? `py_compile`
? Ruff ?????????`server_context.py` ???????? facade F821??????
??? formatter ???`git diff --check` ???????????? timezone schema ???
????????? Crow/PC2/NAS ???

### 2026-09-22?LLM prediction metrics ? UTC ????

`src/llm_metrics.py` ????????????????????? aware UTC clock
??????????????????????????? JSONL ???? UTC offset?
?????? UTC ?????????????????????

???LLM metrics/helper/lazy-config ??? **31 passed**????? formatter?
???? `py_compile` ??? Ruff ???????`llm_metrics.py` ???? formatter
??????????????????????????

### 2026-09-22?AVM pipeline ?????? UTC

AVM pipeline ? run/task `started_at`?`finished_at` ? run completion timestamps ??
? aware UTC ??????? JSON ??????????????? pipeline ?????
??? UTC offset??? pipeline ????????????

???AVM pipeline ??? **31 passed**????? `py_compile` ??? Ruff ?????
???? formatter ???pipeline ?????? formatter ???????????????
??? schema ????????????????????

### 2026-09-22: AVM alert timestamp UTC boundary

The `/api/avm/screen` alert writer now obtains `created_at` from the shared
aware UTC clock. The existing `YYYY-MM-DD HH:MM:SS` string contract, second
precision, and one timestamp shared by a screen batch remain unchanged.

Added a focused behavior test that injects an aware UTC clock and verifies the
persisted alert timestamp is rendered from UTC rather than the host local
timezone. The focused test passed; no AVM alert schema or offline generator
was changed.

### 2026-09-22: snapshot cache nesting guard

The bounded runtime snapshot cache now scans JSON text for excessive structural
nesting before calling `json.loads`. JSONL records use the same guard. This
prevents malformed or adversarial snapshots from exhausting the Python C stack
on Windows while preserving the existing empty-result and source-file
preservation contract.

The focused cache tests pass, including the 2,000-level nesting regression,
and the isolated fast quality suite passes 221 tests.

### 2026-09-22: real `/api/status` recovery projection

The authenticated status response keeps the full recovery snapshot for operator or
node callers, while the anonymous `/api/status` response uses the existing public
projection. The projection removes recovery IDs, manual request IDs, target URLs,
challenge IDs, and snapshot digests/fingerprints.

Added a real TCP regression test that runs the actual `_get_status` handler with an
active synthetic recovery snapshot, checks the anonymous response for the public
shape and absence of sensitive values, and checks the control-token response still
returns the full snapshot. The focused security file passes **33 tests**.

No runtime credentials, database contents, or deployed applications were touched.


### 2026-09-22: hybrid event timestamp parser boundary

Hybrid escalation and recovery summaries now parse both legacy
`YYYY-MM-DD HH:MM:SS` values and ISO `Z`/offset values into aware UTC before
calculating unresolved-window duration or recovery latency. Canonical mixed-format
ordering also compares UTC instants; malformed or historically non-canonical text
keeps the previous lexical fallback so existing negative-latency fixtures remain
stable. Writers and historical JSONL values were not rewritten.

The focused hybrid timestamp tests pass **3**, and the existing escalation/recovery
regression files pass **16** together. No runtime data or deployed service was
touched.

### 2026-09-22: bounded runtime JSON readers and iterative location traversal

Added `src/runtime_json.py` as the shared runtime JSON boundary. It scans structural
nesting before decoding, catches decoder recursion failures, and exposes bounded text
and file readers with a 256-level limit. Collection job receipts, search job snapshots,
archive records, collection data, and AVM raw-record loading now use the shared reader
and fail closed or skip invalid files according to their existing contracts. The
search location loader now walks `children` with an explicit stack, so a deep in-memory
location tree does not consume Python recursion.

The deep-tree regression injects an in-memory tree so it tests iterative traversal
without bypassing the JSON parser guard. Diagnostic HTTPS fixtures now provide an
explicit test CA path, matching the remote-HTTPS fail-closed credential contract.
Focused runtime, collection, server, and safety regressions pass **51 tests**.
The isolated fast quality suite passes **234 tests**; the security suite passes **275
with 2 skipped**. Effective-code-lines tests pass **19**, ratchet reports **1109
files** with all oversized tiers at zero, and `git diff --check` exits successfully
with only the repository's existing LF-to-CRLF warnings. No deployment or runtime
restart was performed.
### 2026-09-22: seed scan worker lease release regression

Added a bounded-window regression for `release_seed_scan_worker_leases()` in
`tools/test/test_seed_maintenance_windows.py`. It exercises more than two
maintenance windows, verifies that only the exact worker owner is released,
checks job status refresh and identity-map bounds, and confirms a second release
is idempotent. The production lease release implementation was not rewritten.
The focused maintenance-window file passes **3 tests**.
The seed maintenance regression is now included in `scripts/quality_suites.py`'s
unit/fast selection rather than relying only on an ad-hoc focused command. The
registered fast suite rerun passes **237 tests** in **18.44 seconds**.
### 2026-09-22: source-aware detail claim URL policy

Detail and raw-analysis claims now resolve the seed URL policy from an explicit
`SeedScanPolicy`, the stored `source_platform`, or the explicit source URL. Generic
rows therefore use `GenericSeedScanPolicy` and fail with a controlled missing-source-URL
error instead of fabricating a Taobao detail URL. Unlabelled legacy rows without a URL
retain the Taobao compatibility fallback; Taobao platform aliases keep their existing
normalization. The optional keyword-only policy argument preserves existing worker
callers and lets a future adapter pass its complete policy without a storage-to-adapter
reverse dependency.

The seed identity regressions now cover both detail and raw-analysis claims for generic
rows without a URL, including transaction rollback of the lease/status mutation. The
focused identity, seed queue, and generic runtime tests pass **55 tests**. This change
only touched isolated test databases; no runtime data, credentials, deployed service,
or application restart was used.
### 2026-09-22: collection handlers read RuntimeState-owned containers

The legacy detail dispatch, status preview, item lookup, analysis-screen lookup,
manual item update, next-visit, and HTML submission handlers now obtain the shared
`CollectionRuntimeIndex` at the request boundary and use its lock, seen IDs, pending
queue, and dispatch cooldown map. The server facade still publishes the old names for
older callbacks and tests, while these production paths no longer read a stale copied
container after an alias rebind.

The focused dispatch, ingest, RuntimeState, write-access, and item-resource regressions
pass **56 tests**. This is a scoped RuntimeState write/read migration; solver/control
state and the remaining facade exports still require separate work. No deployment,
restart, runtime-data access, or business database connection was performed.
### 2026-09-22：人工审核异步回执与 maintenance reconcile_limit 合同

新增 HTTP 回归验证，显式 `mode: async` 的两条人工审核入口都返回旧客户端需要的 HTTP 200、32 位 `maintenance_job_id`、`maintenance_job_status=queued`，同时使用通用 CollectionJobManager 的 `job_id/status_url`。测试将 legacy `ManualReviewMaintenanceManager` 设为禁止调用，并等待通用回执完成，确认完成结果会更新 `maintenance_job_status=completed`。

通用 `recent_enrich_maintenance` 适配层和 `DetailCollectionService.run_maintenance()` 现在保留并转发 `reconcile_limit`，避免后台维护入口与人工审核回执入口的参数合同分裂。新增隔离测试验证适配层和 service 都把自定义 limit 传给 runner；人工审核 HTTP、collection job HTTP 与 detail service 聚焦组共 **50 passed**。
### 2026-09-22：日期路径解析异常边界

`server_data_runtime` 的两个日期路径 helper 现在只把无效日期文本的 `ValueError` 作为兼容 fallback；意外的解析器 `RuntimeError` 会继续传播，避免再次吞掉内部逻辑错误。新增回归测试用隔离 fake datetime 验证该边界；`tests/test_server_data_runtime.py` **2 passed**。
### 2026-09-22：detail service UTC fallback

DetailCollectionService._utc_now() now prefers an aware UTC clock and, when a
zero-argument test/facade clock raises TypeError, prefers utcnow() before the
legacy zero-argument now() compatibility fallback. This prevents local wall
clock values from being relabeled as UTC while preserving older deterministic
clock fakes. The regression test covers that fallback ordering, and the source
avoids dynamic attribute access that triggered the targeted Ruff B009 rule.

The focused detail, maintenance, collection-job, manual-review, and data-runtime
regressions pass **61 tests**. The touched Python files compile successfully and
the targeted Ruff B009 check passes. No runtime data, credentials, deployed
service, or application restart was used.
### 2026-09-22：UTC metadata boundary gate

Added an isolated SQLAlchemy metadata gate for the transitional UTC timestamp
contract. Every datetime column in Base.metadata must use UtcNaiveDateTime except
the three explicitly documented civil/business datetime fields:
property_listing.auction_date, property_listing.auction_start_time, and
property_legal_context.appraisal_benchmark_date. The exceptions are also
checked to remain legacy naive physical DateTime columns, so a future instant
column cannot silently regress to an ordinary naive type or be changed by this
gate without an explicit semantic decision. No production database schema was
modified.

The focused UTC type, schema migration, and storage timestamp tests pass
**8 passed, 1 skipped**, and the new metadata test file passes the targeted Ruff
check. This gate records the current transition boundary; it does not claim the
PostgreSQL timezone-aware schema migration is complete.
### 2026-09-22：Compose role credential wiring

The collection and NAS API Compose services now declare separate worker,
engine-operator, and engine-agent token file paths under the shared secrets
mount. Worker services continue to receive only the worker token path; the
recovery token remains isolated to the NAS API. The worker environment example
now uses an HTTPS central API URL and explicitly documents the private CA and
worker token paths, while noting that HTTP is limited to loopback development.

Added a text-level Compose regression that scopes worker counts before the API
service and verifies all three API role paths in both Compose files. The
credential/TLS/entrypoint focused group passes **88 tests**. This change only
updates configuration contracts and isolated tests; no secrets were created,
no runtime data was accessed, and no service was deployed or restarted.
### 2026-09-22：load_data 异常边界

server_data_runtime.load_data() now separates file read/JSON decode failures
from per-record processing. File-level fallback catches only OSError,
UnicodeError, and ValueError; non-object JSON list entries are skipped with a
warning. Expected malformed-record errors remain isolated to the individual
record, while unexpected RuntimeError-style processing bugs propagate instead
of being mislabeled as a file-load failure. This preserves the corrupt-file
continuation contract and makes the failure boundary observable.

Added a regression proving an unexpected record parser error is not swallowed.
The focused runtime JSON, collection runtime, and server data runtime group
passes **18 tests**. No runtime data or database was accessed.
### 2026-09-22：seed_batch 显式异步入口

/api/save and /api/collection/seeds/batch now accept an explicit
mode: async that queues the existing seed submission handler through the
durable CollectionJobManager. The response uses the standard 202 receipt and
/api/collection/jobs status URL. The control-only mode field is removed
before the business handler sees the payload. Default and non-async requests
retain the existing synchronous result and error contract.

HTTP regressions cover both aliases, receipt shape, payload forwarding,
completed result persistence, and the async failure code. The focused job HTTP
and legacy seed batch contract group passes **35 tests**. No seed data, runtime
database, or live service was modified.
### 2026-09-22：本轮续作回归

在 UTC fallback、metadata gate、load_data 异常边界、Compose role credential 路径及
seed_batch async 入口合入后重新运行：fast **244 passed**；security **281 passed、
2 skipped**；effective-code-lines tests **19 passed**；ratchet **1111 files**，
所有超限分级为 0。collection API Compose config --quiet、git diff --check 与本轮
责任 Python 文件 py_compile 均通过。最后一次定向运行覆盖 UTC、schema gate、job HTTP、
Compose 文本合同及 server data runtime，共 **86 passed**；涉及测试文件的 Ruff 检查通过。

security 两个 skip 仍为 Windows 环境不适用的 POSIX 进程监督用例。没有连接业务
PostgreSQL、读取 FPFData/凭据、部署或重启 Crow、PC2、NAS。本批不关闭完整代码质量清单；
证书供应和真实 HTTPS 部署、物理 UTC schema revision、其他长任务调用方迁移、完整
RuntimeState 和剩余结构任务仍需继续验收。
### 2026-09-22：seed_batch async operator receipt access

Async seed submissions now require the control-plane operator credential in
addition to the route-level worker authorization. This ensures the submitter is
authorized to read the returned generic job status URL; worker-authenticated
synchronous seed submissions keep their existing route and response contract.
The regression confirms worker credentials cannot enqueue async work.

After this authorization boundary change, the security suite passes **282
tests, 2 skipped**, and the job HTTP/legacy seed/worker-access focused group
passes **44 tests**. Effective-code-lines tests pass **19**, ratchet reports
**1111 files** with all oversized tiers at zero, py_compile succeeds, and
git diff --check exits 0. No deployment or application restart was performed.

### 2026-09-22: opt-in asynchronous AVM evaluation

`POST /api/avm/evaluate` and its `/api/analysis/evaluate` alias now accept a
top-level `execution_mode` of `sync` or `async`. Missing mode remains synchronous;
`options.valuation_mode` continues to control only the valuation time semantics.
Subject and area validation happen before queue submission, and the execution
control field is removed before calling `AVMService`. Async requests return the
shared durable job receipt, preserve an optional `request_id`, and store the
normal evaluation response in the job result. Existing synchronous response
and failure contracts remain unchanged.

The five new isolated HTTP regressions pass, including non-blocking completion,
the alias, async failure receipts, valuation-mode preservation, and rejection
before enqueue. Existing evaluate HTTP contracts pass **12 tests**; the isolated
security suite passes **287 tests, 2 skipped**. The skipped cases remain the
Windows-inapplicable POSIX process-supervision tests. No deployment or
application restart was performed.

### 2026-09-22: opt-in asynchronous location inference

`/api/infer_location` and `/api/collection/details/infer_location` now share
the same optional top-level `execution_mode` contract as online evaluation.
Requests without the field remain synchronous. Async work captures the request
values and detail service/LLM callbacks before queueing; the returned receipt
includes the optional item ID, and the original inference object is stored as
the completed result. The old synchronous HTTP result and failure code remain
unchanged.

Two new isolated HTTP tests cover async result and failure receipts. The new AVM
and detail-inference job tests pass **7 tests**, the existing evaluate/inference
HTTP contracts pass **18 tests**, and the security suite passes **289 tests, 2
skipped**. Ruff focused lint/format checks and Python compilation pass. The two
skips remain Windows-inapplicable POSIX process-supervision tests. No deployment
or application restart was performed. Effective-code-lines tests pass **19**;
the ratchet reports **1113 files** with all oversized tiers at zero, and
`git diff --check` exits 0.

### 2026-09-22: NAS API loopback binding and TLS guard

NAS Compose now publishes the API to `127.0.0.1` by default. The controlled
deployment helper validates the configured host address as IPv4 and rejects a
non-loopback binding unless both TLS certificate and key paths are configured.
TLS health checks resolve the certificate host to the configured listener
address; wildcard binding resolves through loopback. The deployment guide now
uses the configured HTTP/HTTPS mode when reading `/api/status` and documents the
external-binding requirement.

The focused deployment and loopback contract tests pass **4 tests**. The full
security suite passes **306 tests, 2 skipped**; effective-code-line tests pass
**19**, and the ratchet reports **1113 files** with all oversized tiers at zero.
Compose config validation and `bash -n` pass. Ruff is unavailable in the active
Python environment. No certificate, secret, runtime data, deployment, or service
restart was used. External certificate supply and real HTTPS runtime validation
remain open.

### 2026-09-22: async AVM screening and PostgreSQL UTC schema

`POST /api/avm/screen` now supports an explicit top-level
`execution_mode: "async"` and uses the durable collection-job receipt. The
default synchronous response remains unchanged; input validation precedes
enqueue, and the background result preserves alert writes and the original
summary payload.

Revision `20260922_0013` converts UTC instant columns to PostgreSQL
`timestamp with time zone` using `AT TIME ZONE 'UTC'` in both directions.
Civil/business date fields remain naive, and `UtcNaiveDateTime` binds aware
UTC values while retaining naive UTC Python results for current caller
compatibility. Offline migration and SQLite schema checks passed. The revision
has not been run against PostgreSQL, and no business database was accessed.

### 2026-09-22: restored NAS health invariant and continued RuntimeState writes

The NAS API candidate health gate again requires
`auth_recovery.enabled`; its contract test now asserts that requirement. The
area-result and area-approval handlers obtain the pending queue from the
current `CollectionRuntimeIndex`, so a legacy queue rebind is adopted before
the detail service receives it. A regression test covers both handlers.

Fresh verification: security **313 passed, 2 skipped**; unit **214 passed**;
effective-code-line tests **19 passed**; ratchet **1116 files**, with every
oversized tier at zero; targeted Python compilation, `bash -n`, and
`git diff --check` passed. Ruff is unavailable in the active environment. No
PostgreSQL migration, deployment, application restart, runtime-data access, or
credential access was performed.

### 2026-09-23: shared detail-dispatch lock

`DetailCollectionService` now accepts a dispatch lock. Production service
instances use `RuntimeState.collection.lock`, the same lock used by legacy
detail-task handlers that read or update `dispatched_tasks`; standalone service
instances retain the local fallback lock. The DB-backed status preview also
reads dispatch timestamps under the runtime-index lock. This removes the split
lock protection around the shared dispatch map without holding a lock during
repository iteration.

Added a concurrency regression proving service dispatch waits on the injected
runtime-state lock and registered it in the fast suite. Fresh validation: fast
**258 passed** (34.95 seconds total); security **313 passed, 2 skipped**
(100.47 seconds total); focused Ruff lint, Python syntax compilation, effective
code-line tests **19 passed**, ratchet **1118 files** with all oversized tiers
at zero, and `git diff --check` passed. The two security skips remain the
Windows-inapplicable POSIX process-supervision tests.

The changed-file formatter check still reports legacy formatting differences
in the touched modules; no whole-file formatting pass was applied. Strict mypy
for `detail_service.py` still reports six pre-existing errors in its callback
contract and untyped helper return values; it reported no error for the new
dispatch-lock type. No deployment, application restart, database migration, or
runtime-data access was performed; the optimization plan remains incomplete.

### 2026-09-23: consistent RuntimeState pause snapshots

Control-flow decisions that previously read `paused` and `reason` from separate
`RuntimeState.control.snapshot()` calls now use one snapshot. Solver transient
pause checks take the control and execution snapshots under their shared runtime
lock, and successful solver cleanup derives its challenge scope and completion
request from one recovery snapshot. This prevents concurrent transitions from
combining fields from different states.

A regression test supplies successive, conflicting control snapshots to model a
transition between reads; the scoped collector now remains paused according to
the single `manual_required` snapshot. The test is part of the existing fast
suite. The first run reproduced the bug (**1 failed, 262 passed**); after the
fix, fast passes **259 tests in 39.23 seconds**, and security passes **313 tests,
2 skipped in 115.31 seconds**. The skips remain the Windows-inapplicable POSIX
process-supervision tests.

The effective-code-lines tests pass **19**; ratchet passes for **1118 files**
with every oversized tier at zero. Focused Ruff lint, Python syntax compilation,
and `git diff --check` pass. Ruff format check still reports legacy formatting
differences in five touched server modules; no broad formatting rewrite was
applied. No deployment, application restart, database migration, runtime-data
access, or credential access was performed.

### 2026-09-23: lock-safe item lookup

`_get_item` checked `item_id in seen_ids` and then indexed the dictionary
separately, while runtime eviction removes entries under the collection index
lock. A concurrent eviction could therefore raise `KeyError`. The handler now
reads the entry once with `.get()` under that shared lock, then sends the
response after releasing it. A regression test verifies the index read holds
the lock. The initial fast-suite run reproduced the bug (**1 failed, 259
passed**); after the fix, fast passes **260 tests in 36.12 seconds**, security
passes **313 tests with 2 skipped in 98.92 seconds**, and the focused
RuntimeState module passes **12 tests in 2.33 seconds**.

Python syntax compilation, the effective-code-lines tests (**19 passed**), and
the ratchet (**1118 files; every oversized tier at zero**) pass. Ruff format
passes for the test module; the existing task-control module still reports
broad legacy formatting differences, so no whole-file rewrite was applied.
Ruff lint reports module-wide legacy findings; the `_get_item` block and test
module are clean. The full plan remains incomplete; no deployment or
application restart was performed.

### 2026-09-23: lock-protected next-visit snapshot

`_post_detail_next_visit` copied `seen_ids.items()` without the collection
index lock. A concurrent insertion or eviction could raise during dictionary
iteration or produce an inconsistent candidate snapshot. The handler now
copies the entries under the shared index lock, then calls the detail service
after releasing it. A guard-lock regression test reproduced the unsafe read
before the fix. The final fast suite, including both index-read regressions,
passes **261 tests in 34.65 seconds**.

Python syntax compilation, the effective-code-lines tests (**19 passed**), and
the ratchet (**1118 files; every oversized tier at zero**) pass. Ruff format
passes for the test module; full-file checks of `server_handler_task_control.py`
and `server_handler_ingest.py` still show legacy formatting differences. The
scoped lint run found no test-module diagnostics; the handler retains existing
`F405` findings for symbols supplied through `server_context` star imports.
No deployment or application restart was performed.

### 2026-09-24: NAS API container naming and post-rename verification

The NAS Compose service and current deployment references now use the consistent
container name `crow-api`; current worker and documentation contracts were
updated from the former `fapaifang-api` name. The active container was created
from the already verified image without rebuilding application code and is Up
with `127.0.0.1:19520->8001/tcp`. The previous container was stopped, renamed,
and retained for rollback rather than deleted.

After the rename, the host nginx TLS edge remained registered at
`/usr/local/etc/rc.d/S99crow-api-tls.sh`, and PC1 rechecked
`https://192.168.15.200:9520/api/status` with the local CA successfully. The
response still reports the pre-existing `auth_recovery.enabled=false` invariant;
this remains an open runtime health issue independent of TLS and naming.
CPA was not changed or redeployed.

### 2026-09-24: NAS API TLS activation and desktop HTTPS switch

A local private CA and NAS API certificate were provisioned under the
operator-controlled `aikey` directory and copied to the NAS secrets share.
The NAS API now uses external HTTPS port **9520**. Its existing HTTP API image
is held on protected loopback port **19520**, and the NAS host nginx TLS edge
proxies `https://192.168.15.200:9520` to that loopback endpoint. The previous
NAS environment and Compose files were retained as backups; the old API
containers were renamed rather than deleted for rollback.

The HTTPS endpoint was verified from PC1 with the local CA and returned a
valid `/api/status` JSON response. The active image reports the existing
runtime `auth_recovery.enabled=false` state; that independent health invariant
remains open and was not hidden by the TLS change. The Crow desktop runtime was
updated to the HTTPS origin and CA path, the verified EXE was installed after
backing up the prior installation, and `Crow.lnk` was refreshed. The running
desktop process resolves to the installed EXE and uses the new HTTPS runtime.

The NAS nginx edge was also registered as `/usr/local/etc/rc.d/S99crow-api-tls.sh`
with start/stop/restart handling. CPA was not changed.

The desktop Playwright smoke gate initially lacked the local Chromium
artifact. After installing the pinned Playwright Chromium/headless-shell
artifact, `npm run test:smoke` passed all **3 tests** (collection,
authentication, settings) in 12.6 seconds. This remains a frontend/browser
smoke result; native Tauri packaging and installed EXE runtime validation are
still open.

### 2026-09-23: desktop frontend and PostgreSQL UTC gate follow-up

The pending desktop frontend gates now pass in `collector-desktop`: `npm run
typecheck`, `npm run lint`, `npm test` (**42 passed**), and `npm run build`
(Vite converted 41 modules and produced `dist/index.html` plus the JS/CSS
assets). Native Tauri packaging and Playwright/runtime smoke remain separate
unverified gates.

The native Tauri build subsequently passed and produced the release EXE plus
MSI and NSIS bundles under `collector-desktop/src-tauri/target/release`.
Attempted local activation was correctly stopped by the deployment guard:
the existing desktop runtime points at an authenticated non-loopback HTTP
collection API (`http://192.168.15.200:8001`) without a collection CA/TLS
configuration. No insecure activation was forced; the installed desktop was
not replaced or restarted.

The dedicated loopback PostGIS test container also completed the real UTC
migration regression. With the explicit psycopg 3 URL
`postgresql+psycopg://...`, `test_utc_datetime_type.py` and
`test_utc_datetime_migration.py` pass (**12 passed**), including both
`America/Los_Angeles` and `Asia/Shanghai` session zones, upgrade/downgrade,
instant preservation, and civil-date preservation. The generic
`postgresql://` URL selects unavailable psycopg2 in the current environment;
the project lock specifies psycopg 3, so the explicit driver URL is required
for this gate. No business database was accessed and no deployment or restart
was performed.

### 2026-09-23: lock pending-task removals

`DetailCollectionService.submit_html()` and `apply_working_item_patch()` removed
cached IDs from the shared `pending_tasks` list without taking the injected
runtime lock. The detail-task handler filters and iterates the same list under
that lock. Both removals now hold the service's shared lock only for the list
membership check and removal, leaving file and database work outside the lock.
A parametrized guard-lock test reproduced both unsafe paths before the fix
(**2 failed**) and passes for both operations after it. The focused detail
dispatch tests pass (**4 tests**), RuntimeState tests pass (**13 tests**), and
the final fast suite passes **263 tests in 33.29 seconds**.
The final security suite also passes **313 tests with 2 skipped in 86.82
seconds**.

Python syntax compilation, the effective-code-lines tests (**19 passed**), and
the ratchet (**1118 files; every oversized tier at zero**) pass. Ruff format
passes for both regression test modules; the existing source modules still have
whole-file formatting differences. Ruff reports no regression-test diagnostics;
the handlers retain existing `F405` findings from `server_context` star imports.
No deployment or application restart was performed.

### 2026-09-24: restore NAS auth-recovery health invariant

The NAS runtime environment now explicitly sets
`FAPAI_NAS_AUTH_RECOVERY_ENABLED=1`, with the existing recovery token file
present and non-empty. The `crow-api` container was recreated from the retained
`fapaifang-collector:tls-existing` image without rebuilding application code;
the previous container was renamed and retained for rollback. The container is
Up on `127.0.0.1:19520->8001/tcp`, and the HTTPS edge remains on port 9520.

Fresh PC1 verification through the local CA now reports
`auth_recovery.enabled=true` and build `20260924-auth-recovery-enabled`.
The API remains paused on the existing captcha challenge state; this is an
independent operational pause, not a TLS or container-health failure. CPA was
not changed or redeployed.

### 2026-09-24: enforce Chromium sandbox for PC2 browser

The PC2 browser startup script now refuses root execution and refuses to start
when the Linux unprivileged user-namespace sandbox is unavailable. The browser
continues to run as the dedicated non-root `fapaifang` user, and the unsafe
`--no-sandbox` launch flag was removed. The deployment contract test now locks
these requirements. Focused PC2 deployment tests pass **15 tests** and the
startup script passes `bash -n`; a real PC2 image rebuild and runtime smoke
remain required before marking the browser release gate complete.

### 2026-09-24: detail dispatch lock ownership follow-up

数据库详情任务的 `dispatched_tasks` 之前由 `server_handler_get_collection.py` 和
`server_handler_ingest.py` 直接传入 `DetailCollectionService`，服务内部默认使用
自己的 dispatch lock；状态读取路径却使用 `CollectionRuntimeIndex.lock`，导致同一
共享字典存在两把锁。`next_task()` 与 `next_visit_task()` 现在接受可选的调用方锁，
两个 RuntimeState handler 显式传入 `runtime_index.lock`，冷却清理和检查/写入操作
因此与状态快照共享同一所有权边界。既有独立服务调用仍保持默认锁兼容。

`compileall`、有效行数 ratchet（1125 files，三档 oversized 均为 0）和
`git diff --check` 通过。使用临时 `uv run` 补齐 pytest、BeautifulSoup、SQLAlchemy、
Requests 和 websocket-client 后，详情并发回归 **6 passed**。PC2 真实镜像运行、
Tauri 安装后验证、业务 PostgreSQL migration 与其余 RuntimeState 写入迁移仍保持开放。

### 2026-09-24: RuntimeState pending removal callback

详情 HTML 提交、条目更新、面积识别结果和人工确认路径现在可以把
`CollectionRuntimeIndex.remove_pending` 作为显式回调传入 `DetailCollectionService`。
这些 RuntimeState handler 不再要求服务直接从裸 `pending_tasks` 列表执行移除；服务仍
保留旧列表参数作为兼容回退，旧测试和非 RuntimeState 调用不改变。新增回归测试验证
回调路径确实移除当前条目，同时保留原有锁保护列表路径。

本批 `compileall`、有效行数 ratchet（1125 files，三档 oversized 均为 0）和
`git diff --check` 通过；详情并发回归使用临时依赖环境运行 **6 passed**。没有部署或
重启。`detail_processor.py`、`seed_service.py` 中的 `seen_ids`/`pending_tasks` 批量
写入仍需后续按 RuntimeState API 继续迁移。

### 2026-09-24: detail processor RuntimeState callbacks

`CollectionRuntimeIndex` 新增受锁的 `set_seen()`。详情处理器现在支持显式注入
`queue_pending`、`set_seen` 和 `remove_pending` 回调：重试任务通过 RuntimeState
队列去重，成功归档通过受锁 API 更新 seen entry 并移除 pending。`DetailCollectionService`
和 `process_single_file()` 已把这些回调接入当前 collection runtime；旧的裸容器参数
仍保留为兼容回退。两项过时测试改为重置 `RUNTIME.collection.pending_tasks`，不再依赖
已删除的 `server.PENDING_TASKS` 别名。

聚焦详情服务、并发分发和 runtime data 回归共 **15 passed**。`compileall`、有效行数
ratchet（1125 files，三档 oversized 均为 0）和 `git diff --check` 通过。seed service
仍需下一批处理其 check-then-append 的完整锁边界；没有部署或重启。

### 2026-09-24: seed service RuntimeState callbacks

`CollectionRuntimeIndex` 新增受锁的 `get_seen()`，seed batch handler 现在把
`get_seen`、`set_seen` 和 `queue_pending` 回调传给 `SeedCollectionService.submit_batch()`。
service 保留 `seen_ids` / `pending_tasks` 参数作为旧调用兼容面，但 RuntimeState 调用
路径不再直接写入新条目或追加 pending；已有条目合并在外层 collection lock 内完成，
新条目写入和 pending 去重使用受锁 callback。测试替身缺少新方法时由 handler 安全回退，
不改变旧测试契约。

详情处理、并发分发、runtime data、seed service 和 seed lock 边界组合回归 **19 passed**。
`compileall`、有效行数 ratchet（1125 files，三档 oversized 均为 0）和
`git diff --check` 通过。没有部署或重启。

### 2026-09-24: server facade contract coverage

在不改变动态 facade 实现的前提下，补充两项低风险契约回归：所有被重绑定到
`src.server` 的函数必须使用 `server` facade 的 globals，所有静态 `ROUTES` 注册项
必须对应 `DataHandler` 上可调用的方法。这样可以锁定 `FunctionType` 重绑定和路由
动态挂载的当前不变量，避免后续 RuntimeState 或路由重构静默破坏跨模块全局解析。

`tools/test/test_server_source_contract.py` 全部 **14 passed**。`compileall`、有效行数
ratchet（1125 files，三档 oversized 均为 0）和 `git diff --check` 通过。没有部署或
重启；FunctionType/import-star 的运行逻辑重构仍需单独处理。

### 2026-09-24: task-control RuntimeState dispatch methods

非 DB 详情任务控制路径不再直接重写 `pending_tasks` 或直接赋值
`dispatched_tasks`。`CollectionRuntimeIndex` 新增受锁的
`prune_processed_pending()` 和 `mark_dispatched()`，`server_handler_task_control.py`
在既有外层 collection lock 内使用这两个方法，保留冷却、已处理过滤、任务计数和
批量返回行为。该切片没有扩大到其他同型 handler。

RuntimeState、详情处理、seed service、并发分发和 runtime data 组合回归 **29 passed**。
`compileall`、有效行数 ratchet（1125 files，三档 oversized 均为 0）和
`git diff --check` 通过。没有部署或重启。

### 2026-09-24: seed batch RuntimeState lock boundary

`handle_seed_batch_submission()` 现在在调用 `SeedCollectionService.submit_batch()` 的
整个生命周期内持有 `CollectionRuntimeIndex.lock`，覆盖 seen entry 查找、数据库回退
查询、已有记录合并、新记录写入和 pending 入队。这样 check-then-append 不会被并发的
seed batch 请求拆开；service 的既有参数和持久化契约保持不变。新增回归测试验证调用
确实发生在 collection lock 内。

详情处理、并发分发、runtime data 和 seed lock 边界组合回归 **16 passed**。
`compileall`、有效行数 ratchet（1125 files，三档 oversized 均为 0）和
`git diff --check` 通过。seed service 的裸容器参数仍作为兼容面保留，后续可继续做
更细粒度的 RuntimeState callback 迁移；没有部署或重启。

### 2026-09-24: collection next-task RuntimeState methods

`server_handler_get_collection.py` 的非 DB 详情任务入口现在使用
`CollectionRuntimeIndex.prune_unavailable_pending()` 清理孤儿或已处理 pending 项，
并使用 `mark_dispatched()` 写入冷却时间。原有 URL 选择、冷却跳过和单任务响应行为
保持不变；该路径与 task-control 入口使用统一的 RuntimeState 方法。

RuntimeState、详情服务、详情并发和 runtime data 组合回归 **28 passed**。
`compileall`、有效行数 ratchet（1125 files，三档 oversized 均为 0）和
`git diff --check` 通过。没有部署或重启。

### 2026-09-23: runtime data loader 使用 RuntimeState collection API

`server_data_runtime.load_data()` 不再直接写入 `seen_ids` 和 `pending_tasks`。
文件扫描和数据库 hydration 现在通过 `CollectionRuntimeIndex.set_seen()` 与
`queue_pending()` 完成，保留重复入队抑制和既有 done/processed 判定。这样
启动加载路径与在线 handler 使用同一套受锁 RuntimeState API，减少裸容器写入面。

`test_runtime_json.py`、`test_runtime_state.py` 和
`test_collection_processing_state.py` 组合回归 **23 passed**。没有部署或重启；
其他 service 的兼容参数和剩余裸容器写入仍需继续迁移。

### 2026-09-23: runtime eviction 使用 RuntimeState collection API

`_evict_runtime_item()` 不再直接操作 `seen_ids.pop()`；
`CollectionRuntimeIndex` 新增受锁的 `remove_seen()`，并与既有
`remove_pending()` 一起用于运行时条目驱逐。该切片保持删除内存索引的原有语义，
不删除磁盘归档或业务数据库记录。

RuntimeState、collection processing 和 server data runtime 回归 **18 passed**，
有效代码行 ratchet 与 `git diff --check` 通过。其他 service 的裸容器参数和写入
仍需继续迁移；没有部署或重启。

### 2026-09-23: detail dispatch 写入通过 RuntimeState callback

详情服务的 `next_task()`、`next_visit_task()` 和 `batch_tasks()` 现在支持显式的
`mark_dispatched()` callback。在线 server handler 将 dispatch 时间写入
`CollectionRuntimeIndex`，兼容测试和旧调用仍可使用原始字典参数。这样新的详情
分发写入不再直接修改 RuntimeState 拥有的 `dispatched_tasks` 容器。

详情 dispatch、RuntimeState 和 collection restart 组合回归 **37 passed**，有效代码
行 ratchet 与 `git diff --check` 通过。过期清理和旧 service 参数仍保留兼容面，
没有部署或重启。

### 2026-09-23: seed batch 使用 RuntimeState lookup/update API

`SeedCollectionService.submit_batch()` 在 RuntimeState 调用路径中不再直接用
`seen_ids` 做存在性判断，也不直接修改已缓存 entry 的 `data`。已有条目通过
`get_seen_entry()` 查询，并优先使用 `set_seen()` 写回合并结果；旧参数仍保留给
独立 legacy 调用。seed batch 的整体 collection lock 和 pending callback 保持不变。

seed service、seed identity、collection processing 和 RuntimeState 回归 **26 passed**，
有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: collection read snapshots and atomic legacy next-task claim

`CollectionRuntimeIndex` 新增 `state_snapshot()` 和
`claim_next_pending()`。状态概览现在使用一致的 seen/pending/dispatch 快照，
legacy 详情任务入口则在 RuntimeState 内部一次锁操作中完成 pending 清理、冷却检查、
条目读取和 dispatch 标记，避免 handler 直接访问内部容器或把 check-then-mark 拆开。

RuntimeState、详情 dispatch、collection restart 和 server facade 契约回归 **45 passed**，
有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: handler collection reads and legacy batch claim use state APIs

`_get_working_item()`、analysis screen lookup 和 detail next-visit 入口不再直接读取
`seen_ids`；legacy visit entries 使用 RuntimeState snapshot。详情批量任务入口新增
`claim_pending_batch()`，在共享锁内完成 pending 清理、计数、冷却检查和 dispatch 标记，
避免 handler 自己遍历内部容器。历史 `PENDING_TASKS` 与 `DATA_LOCK` facade 接入仍保留，
用于不破坏既有维护回调和测试边界。

RuntimeState、detail dispatch、collection restart 和 server contract 回归 **53 passed**，
有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: task-control item lookup uses RuntimeState read API

`server_handler_task_control._get_item()` 现在优先使用 `CollectionRuntimeIndex.get_seen()`，
将在线 RuntimeState 读取与其他 handler 统一；针对旧的轻量测试替身保留受锁 fallback。
该改动不改变数据库优先级、404/503 错误合同或返回数据。

collection runtime、RuntimeState、detail dispatch 和 server facade 回归 **41 passed**，
有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: detail processor requires RuntimeState callbacks

`DetailProcessor` 和 `DetailCollectionService.process_html_file()` 已移除
`seen_ids` / `pending_tasks` 原始容器参数。重试、完成保存和 pending 清理现在必须
通过 `queue_pending()`、`set_seen()` 和 `remove_pending()` callback 完成；内部不再保留
直接 append/remove/index 写入 fallback。生产调用方已全部传入 RuntimeState callbacks，
相关单元测试改为验证 callback 合同。

collection adapter、detail service、detail dispatch 和 RuntimeState 回归 **40 passed**，
有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: detail update handlers remove raw pending container contract

`submit_html()` 和 `apply_working_item_patch()` 不再接收原始 `pending_tasks` 列表，
只接受必需的 `remove_pending()` callback。详情 ingest、area result 和 manual approve
handler 已全部改为传入 RuntimeState callback；detail service 内不再保留直接
`pending_tasks.remove()` fallback。相关 RuntimeState 测试改为验证 callback 身份。

detail service、detail dispatch、collection adapter、RuntimeState 和 quality collection
回归 **48 passed**，有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: seed service requires RuntimeState callbacks

`SeedCollectionService.submit_batch()` 已移除原始 `seen_ids` 和 `pending_tasks` 参数。
已有条目写回和新条目入队现在必须通过 `set_seen()` 与 `queue_pending()` callback，
生产入口由 `CollectionRuntimeIndex` 提供；seed service 内不再保留直接字典/列表写入
fallback。相关 seed 和 source-neutral adapter 测试已改为验证 callback 合同。

seed service、collection adapters、quality collection 和 seed identity 回归 **34 passed**，
有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: detail dispatch reads and expiry use RuntimeState callbacks

`CollectionRuntimeIndex` 新增 `get_dispatched()` 与 `prune_dispatched()`。detail
service 的在线 `next_task()`、`next_visit_task()` 和 `batch_tasks()` 现在通过
RuntimeState callback 读取和清理 dispatch cooldown；只有旧的字典调用才使用兼容
路径。handler 保持共享锁、时间语义和历史 facade alias 行为。

detail dispatch、RuntimeState、legacy UTC dispatch、quality collection 和 server facade
回归 **44 passed**，有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。

### 2026-09-24: runtime count and dispatch snapshots for read-only paths

`CollectionRuntimeIndex` 新增 `counts_snapshot()`。runtime loader 的 DB-first 和最终
加载日志不再直接读取内部 seen/pending 容器；状态概览的 DB dispatch preview 也统一
使用 `state_snapshot()`。这些只读路径保持原有日志、计数和 cooldown 行为，同时继续
由 RuntimeState 提供一致性边界。

RuntimeState、runtime JSON、quality collection 和 server facade 回归 **43 passed**，
有效代码行 ratchet 与 `git diff --check` 通过。没有部署或重启。
