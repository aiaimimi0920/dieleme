# Crow V0.1.0 代码质量评审与优化清单

日期：2026-09-20
基线：tag `V0.1.0`（commit `43502a6f9`）
范围：`src/`、`tools/`、`collector-desktop/`、`ops/`、`scripts/`、`jobs/`、`tools/test/`

## 1. 总体评价

采集流程在功能上已经闭环，领域抽象（Adapter/Policy 协议、认证恢复状态机、PC2 控制面的"不确定即拒绝、先落盘再变更"）比典型的 GPT 生成代码认真。但有四类问题贯穿整个仓库，需要在继续堆功能之前处理：

1. **安全边界不一致。** NAS HTTP 服务默认无鉴权、`Access-Control-Allow-Origin: *`，同时暴露文件上传路径拼接、任意目录写、SSRF 等入口。局域网内任意页面或主机都能触发暂停、恢复、重置认证、写文件。
2. **并发正确性靠运气。** 单线程 `TCPServer`、Postgres 认领无 `FOR UPDATE`、solver 与任务队列的全局状态裸读裸写、验证码 solve 循环持锁阻塞无总时限。所有存储测试跑 SQLite，并发语义零覆盖。
3. **为满足行数策略做的机械拆分。** `effective-code-lines` 阈值催生了 189 个 `_part_NN.py` 测试切片、`from x_context import *` 共享命名空间、`types.FunctionType` 运行时克隆函数把切片缝回同一 globals。物理文件变小，逻辑耦合反而变大，IDE 与静态分析全盲。
4. **工程门禁缺失。** 无 ruff/mypy/eslint/tsc，无 CI 工作流，`requirements.txt` 全 `>=` 无 lock，`pytest.ini` 的 `quick` 标记零使用，前端 smoke 已与 DOM 脱节无人发现。

## 2. 评审方法

六个方向并行人工评审并逐条核对源码，外加全仓库量化扫描：

| 方向 | 主要文件 |
|------|----------|
| 服务端 API | `src/server*.py` |
| 采集引擎与存储 | `src/collection/`、`src/storage/`、`alembic/` |
| 认证交接与安全 | `src/nas_auth_recovery.py`、`src/server_auth_*.py`、`tools/pc1_*`、`tools/manual_auth_snapshot.py` |
| 验证码与 LLM | `src/captcha_*.py`、`src/llm_*.py` |
| 桌面控制台 | `collector-desktop/` |
| PC2 运维与部署 | `tools/pc2_*`、`tools/docker_entrypoint.py`、`ops/`、`scripts/*.ps1` |

桌面方向的 `cargo test`（8 过 1 忽略）与 `node --test`（21 过）在本机实际运行过；其余结论来自源码核对。

## 3. 全局度量

| 指标 | 值 |
|------|----|
| `src/` 有效代码行 | 约 35.8k |
| `tools/test/` 代码行 / 文件数 | 约 97.5k / 399 |
| `_part_NN.py` 机械切片测试文件 | 189（占 48%） |
| `from ..._context import *` 测试文件 | 215 |
| 对脚本文本做字符串包含断言 | 1225 处，36 个文件 |
| pytest 用例数 / 收集耗时 | 3111 / 9.5s，0 错误 |
| `src → tools` 反向导入 | 24 处（`src/server_context.py` 导入 7 个 tools 模块） |
| 导入循环 | `tools.pc1_desktop_auth` 与 `tools.pc1_shared_auth` |
| `src/` 中 `except Exception` / 裸 `except:` / `print(` | 288 / 38 / 416，`logging` 零使用 |
| 硬编码 `192.168.x.x` | 12 个源码文件 + 33 个测试文件，含 `collector-desktop/src-tauri/src/lib.rs` |
| 函数类型注解覆盖 | 约 60% |
| `requirements.txt` | 全部 `>=`；`selenium-wire`、`requests-toolbelt` 零导入；`numpy` 被 5 个文件使用却未声明 |
| Sentrux 质量信号 | 0.49，瓶颈为 acyclicity |
| 高风险零测试文件比例 | coverage_ratio 65 |

## 4. 缺陷清单

严重度：**P0** 安全或数据损坏，尽快修；**P1** 正确性或可用性缺陷；**P2** 质量与可维护性。工作量：小（1 天以内）、中（2 到 5 天）、大（1 周以上）。

### 4.1 P0

| # | 位置 | 问题 | 修法 | 量 |
|---|------|------|------|----|
| 1 | `src/server_handler_ingest.py:214-229` | `/api/upload` 的 `id`、`name` 直接拼进 `downloads/` 路径，只去掉反斜杠，`../` 与 `/` 未过滤，且 `parse_qs` 后再 `unquote` 二次解码。任意路径写文件。 | `Path.resolve()` 后 `relative_to(downloads_root)` 校验（`server_collection_console.py:182-199` 已有正确范例）；`item_id` 限定 `[A-Za-z0-9_-]+`；设 `Content-Length` 上限。 | 小 |
| 2 | `src/server_handler_core.py:8,21`、`src/server.py:101-106` | 全部响应带 `Access-Control-Allow-Origin: *`，而 `/api/resume`（GET）、`/api/collection/control/*`、`/api/avm/run`、`/api/save_locations`、`/api/upload` 等状态变更接口无鉴权、不校验 `Content-Type`。操作员浏览器打开任意网页即可被跨站触发。 | 统一鉴权中间件，CORS 改白名单，GET 不做写操作。 | 中 |
| 3 | `src/server_collection_operations.py:5-15` | `_verify_control_plane_token` 环境变量缺失时 `return True`；用 `==` 而非 `hmac.compare_digest`；只保护 manual review 三个端点。 | 缺失即拒绝并启动告警；常量时间比较；覆盖全部写接口。 | 小 |
| 4 | `src/server_handler_task_control.py:398-418`、`src/server_auth_cookie.py:267-269,380-384,403` | `/api/collection/auth/complete` 无鉴权；请求体 `cdp_endpoint`（非 localhost 时原样使用）与 `cookie_snapshot_path`（无路径限制）直接进入 `_refresh_auth_cookie_snapshot`。可让 NAS 连任意 CDP 端点（SSRF）并把 Cookie 写到任意路径；还能解除人工暂停。 | 复用 `_nas_auth_recovery_authorized`；`cookie_snapshot_path` 只允许 `secrets/nodes/<node_id>/` 下；`cdp_endpoint` 白名单为配置值。 | 小 |
| 5 | `src/server_handler_task_control.py:380-391` | `/api/collection/auth/force_reset` 无鉴权，局域网任意客户端可强制重置挑战作用域。 | 同上。 | 小 |
| 6 | `src/server.py:100,302` | `DataHandler` 继承 `SimpleHTTPRequestHandler` 未覆盖 `do_HEAD`，HEAD 请求走父类 `send_head`，按进程 CWD 解析并回显文件存在与大小。 | 覆盖 `do_HEAD` 返回 404，或改继承 `BaseHTTPRequestHandler`。 | 小 |
| 7 | `src/server_handler_analysis.py:112` | `/api/avm/run` 把客户端传入的 `data_dir` 直接作为 pipeline 数据目录，pipeline 会在该目录写 `canonical/`、`avm/`。任意目录写。 | 删除该字段或限定为 `DATA_DIR` 子目录。 | 小 |
| 8 | `collector-desktop/src-tauri/src/lib.rs:54-61`、`settings_bridge.rs:51-61` | 找不到 exe 旁脚本时沿 `current_dir().ancestors()` 向上找 `scripts/desktop-auth-challenge.ps1` 并以 `-ExecutionPolicy Bypass` 执行；Python 解释器路径同样由此推导。启动目录可被快捷方式控制，即脚本劫持。 | 仅信任 exe 同级目录或 `resource_dir`；cwd 回退只在 `debug_assertions` 下启用。 | 小 |
| 9 | `src/storage/repository_seed_items.py:164` | 已存在种子被再次扫描到时 `source_payload` 整体覆盖，抹掉 `_raw_detail_artifacts`、`_analysis_attempt_count`、`_blocked_recovery`。处于 `raw_detail_captured` 的条目下次被认领时（`repository_detail_claim.py:392-400`）因找不到 html 路径被永久标 `analysis_blocked`。 | 只合并非下划线键，保留内部 `_` 前缀字段；补回归测试。 | 小 |
| 10 | `src/storage/repository_search.py:75-97`、`src/storage/repository_seed_scan_pages.py:38-151` | `claim_search_task`、`claim_seed_scan_page` 读改写全程无 `FOR UPDATE`，READ COMMITTED 下多个 worker 认领同一任务或同一页。compose 中有多个 worker 实例。 | 改为 `UPDATE ... WHERE status IN (...) AND (lease_until IS NULL OR lease_until < :now) RETURNING`，或 `with_for_update(skip_locked=True)`。 | 中 |
| 11 | `src/storage/repository_context.py:97-99` | `_lease_reclaimable` 用认领方的 `lease_seconds` 算 `max_window`。若任一进程以较小 `lease_seconds` 调用同一认领函数，会判定别人合法租约"过长"而抢走，造成双写。 | 以持有方租约或表内固定上限判断，调用方 `lease_seconds` 不参与回收判断。 | 小 |
| 12 | `tools/pc2_collection_controller.py:29-32`、`tools/pc2_settings_controller.py:53-57` | 回执 journal 存在时先 `client.post("result")` 再 `unlink`；NAS 对过期 claim 返回 409 时抛 HTTPError 被当 OSError 吞掉，journal 永不删除。控制器每 5s 重放同一回执、永不 poll 新命令，且 `step():47` 因 journal 存在也停掉浏览器 watchdog。`pc2_engine_controller.run_loop:174-177` 已处理 409，统一控制器漏了。 | 对 4xx 终态响应也 unlink journal 并记录；补 Windows 可跑的测试。 | 小 |
| 13 | `tools/docker_entrypoint.py:439` | `subprocess.call` 让 Python 留作 PID 1 且无 SIGTERM handler，`docker restart --time 30` 必然退化为 30s 后 SIGKILL，worker 租约与写入无法收尾。compose 无 `init: true` 与 `stop_grace_period`。 | `os.execvp(command[0], command)` 或 compose 加 `init: true`；worker 装 SIGTERM handler 释放租约。 | 中 |
| 14 | `tools/pc2_linux_healthcheck.py:116-124` | worker 健康检查只看 PID 1 存活、NAS `/status`、输出目录可写，不看 worker 自身进展。挂死 worker 永远 healthy，无组件重启它；NAS 掉线时 8 个 worker 全部 unhealthy，`EngineController.restart` 因此报 `health_timeout`。 | worker 写心跳文件（参照 `pc2_solver_watchdog.py`），healthcheck 读心跳；NAS 可达性单独上报。 | 中 |
| 15 | `tools/pc1_desktop_recovery.py:16,31`、`scripts/write-collector-desktop-runtime-config.ps1:4`、`scripts/deploy-collector-desktop-local.ps1:5`、`scripts/watch-pc1-nas-auth-recovery.ps1:28` | 默认 API 为 `http://192.168.15.200:8001`，`X-Fapai-Recovery-Token` 明文传输；同一 token 同时授权 PC1、PC2、桌面三种角色。 | 只允许 https（复用 `collection_control_https.py` 私有 CA 方案）；按角色拆分 token 文件。 | 大 |
| 16 | `scripts/deploy-collector-desktop-local.ps1:9-11,187`、`scripts/backup-postgres-to-host.ps1:6`、`scripts/sync-docker-data-to-host.ps1:8` | 默认 `RemoteAuthUser="Admin"`、`RemoteAuthHost=192.168.15.104`，`-RemoteAuthPassword` 明文写入 `start-fapaifang-collector.ps1` 并随备份复制 5 份；两个脚本默认参数硬编码 DB 密码 `"fapaifang"`。 | 改凭据文件或 DPAPI，launcher 只写路径；删除密码默认值，改必填或读 env。 | 小 |

### 4.2 P1

| # | 位置 | 问题 | 修法 | 量 |
|---|------|------|------|----|
| 17 | `src/server.py:302-303` | `ReusableTCPServer(socketserver.TCPServer)` 单线程、handler 无 `timeout`。慢客户端或同步长任务（`/api/avm/run_all_subtasks_sync`、`fetch_missing_archives`、`load_data` 全盘扫描）让全部 API 停摆，连 `LAST_REQUEST_TIME` 看门狗也停。 | `ThreadingMixIn` + `DataHandler.timeout = 30`；长任务改异步任务 ID 轮询。 | 中 |
| 18 | `src/captcha_orchestration.py:12-395` | 整个 solve 循环持锁阻塞，最多 50 次尝试、每次含多段固定 sleep，无墙钟总时限。 | 加 deadline 参数，`sleep` 改 `Event.wait` 可中断。 | 中 |
| 19 | `src/llm_openai_compatible.py:124-159` | 429/403/5xx 时遍历所有候选模型再整轮重来，不看 `Retry-After`。账号被限流时反而加倍打。 | 429 按 `Retry-After` 或指数退避冷却该模型；403 直接跳过。 | 小 |
| 20 | `src/llm_*.py` | 生产 chat 无 `max_tokens`；输入截断 100k 到 120k 字符散落多处；抓取的页面文本与指令放同一 user message，存在 prompt injection 面。 | 统一 token 预算常量；system/user 拆分并对页面文本做定界转义。 | 中 |
| 21 | `src/server_handler_analysis.py:238,278,303,325,350`、`src/server_handler_ingest.py:194,238,273`、`src/server_handler_task_control.py:228` | `int(self.headers['Content-Length'])` 无 try，缺头 `KeyError`、非数字 `ValueError` 逃出 `do_POST`，客户端收到连接重置而非 400。JSON 端点读 body 无大小上限（仅 settings、engine 两处有限制）。 | 抽 `_read_json_body(self, max_bytes)`。 | 小 |
| 22 | `src/server_handler_core.py:120,127,140,182` 对比 `src/server_solver_dispatch.py:302-320` | `SOLVER_RUNNING`、`SOLVER_LAST_STATUS` 在 dispatch 受 `SOLVER_LOCK` 保护，但 `run_solver` executor 线程裸写，`_server_post_branch_24` 裸读。 | solver 状态收进带锁 dataclass。 | 中 |
| 23 | `src/server_handler_task_control.py:160-166,173-193` | `/api/get_tasks` 非 DB 分支对 `PENDING_TASKS`、`SEEN_IDS` 无 `DATA_LOCK`，与 executor 线程的 `process_single_file` 并发改写；181 到 185 行是不可达死码。 | 加锁；删死码。 | 小 |
| 24 | `src/server_data_runtime.py:70-73` | `load_data` 直接 `SEEN_IDS = {}` 重新绑定，而 `process_single_file` 已把旧 dict 引用传给分析线程，replay 或 fetch 后并发结果写进被丢弃的旧 dict。 | 改 `SEEN_IDS.clear(); SEEN_IDS.update(...)`。 | 小 |
| 25 | `src/server.py:146-177` | 路由一半用去 query 的 `request_path`，一半用 `self.path`：`/api/get_tasks?x=1`、`/api/resume?x=1`、`/api/next_task?x=1` 落到 404；`startswith('/api/avm/predict')` 误匹配 `/api/avm/predict_foo`。 | 全部用 `parsed.path` 精确匹配，改路由表。 | 中 |
| 26 | `src/server_*.py` 共 56 处 | 500 响应 `details={'error': str(e)}` 把内部异常原文（含文件路径、DB 错误、SQL）返回给未鉴权客户端。 | 返回错误 ID，原文只进日志。 | 小 |
| 27 | `src/storage/models.py:14-20`、`repository_context.py:79-83` | `updated_at` 由 DB `func.now()`（timestamp without tz）写入，`lease_until` 与 8 处 `row.updated_at = now` 用 Python `utcnow()`；`generic_product.py:155`、`stage_state.py:51`、`detail_artifacts.py` 用本地 `datetime.now()`。DB 时区非 UTC 时 `_cooldown_active`、stale-failed 优先级、`_lease_reclaimable` 全部失效。 | 统一 `DateTime(timezone=True)` + aware UTC；注入 clock 可调用。 | 中 |
| 28 | `src/storage/repository_detail_claim.py:381-400` | 持有行锁的事务内做 `os.path.isfile`，且路径按当前节点解析；Windows worker 写入的路径在 Linux 侧不可见时直接判 `analysis_blocked`，不可自动恢复。 | 存在性校验移到事务外；失败只设 `analysis_failed` 并记录错误。 | 小 |
| 29 | `src/storage/repository_seed_items.py:143-145` | 非 PG、SQLite 方言分支在 `session_factory.begin()` 内直接 `session.rollback()`，回滚整批已写条目后继续循环。同仓 `repository_seed_scan_jobs.py:176-185` 用了正确的 `begin_nested()`。 | 统一 `begin_nested()`。 | 小 |
| 30 | `src/collection/seed_service.py:71-89,107-108` | DB 异常被 `except Exception: pass/return None` 吞掉，`next_task` 对 DB 故障返回"所有嗅探任务已完成"。 | 记录日志并向上返回错误状态。 | 小 |
| 31 | `tools/internal_api_http.py:16-31,34-50` | PC2 侧 `requests` 默认跟随重定向，只在跨主机时剥离 `Authorization`，自定义头 `X-Fapai-Recovery-Token` 会被带到重定向目标。PC1 侧已有 `NoRedirect`。 | `allow_redirects=False`。 | 小 |
| 32 | `tools/browserless_seed_probe_cookies.py:8-14` | NAS 侧正式 Cookie 快照 `secrets/nodes/pc2/taobao-cookies.json` 用 `write_text` 非原子写、继承 umask 无 0600；PC2 可能读到半写文件，与 sha256 校验打架表现为 409。 | `mkstemp(0600)` + `os.replace`，与 `manual_auth_snapshot.publish_snapshot` 统一。 | 小 |
| 33 | `tools/manual_auth_snapshot.py:17`、`tools/pc1_shared_auth.py:19` | `desktop-auth/auth-recovery-<id>-<sha>.json` 与 `shared-<id>.json` 不可变文件从不清理，每次人工认证在共享盘永久留一份完整 Cookie。 | 恢复终态后或超过 `MAX_AGE` 删除；PC2 拉取成功后 NAS 侧删除。 | 小 |
| 34 | `src/server_handler_get_collection.py:262`、`src/nas_auth_recovery.py:158,208` | `/api/status` 无鉴权即返回 `recovery_id`、`manual_request_id`、快照 sha256、`target_url`、`value_fingerprint`，配合 #4 可精确定位并篡改进行中的恢复。 | 公共状态只暴露 `status`、`phase`。 | 小 |
| 35 | `collector-desktop/src/desktop_runtime_controls.ts:41-73` | `refreshEngineRestartStatus` 在 `finally` 无条件 `setTimeout(..., 5_000)` 自我重排；每轮调用 native `config` 与 `restart_status`，Tauri 下每 5 秒 spawn 两个 Python 进程并出网。 | 只在重启请求处于 requested/restarting 时轮询，缓存 origin，空闲退回 60 秒周期。 | 小 |
| 36 | `collector-desktop/src/desktop_collection_views.js:86-88` | `parseEditableValue` 把任何 `^-?\d+(\.\d+)?$` 文本强转 Number，电话与编号字段丢前导零、超 2^53 丢精度，类型变化写回 DB。 | 按原字段类型决定是否转数。 | 小 |
| 37 | `tools/test/collector_auth_ui_smoke.mjs:36-37,78`、`tools/test/collector_collection_ui_smoke.mjs:26,61,67-68` | 引用 `#authButton`，模板早已改为 `#seedAuthButton` 与 `#detailAuthButton`；`localStorage` 的 `crow.apiBase` 无代码读取。两条 smoke 已失效且不在任何门禁。 | 修选择器并写运行器纳入 CI。 | 中 |
| 38 | `tools/pc2_collection_watchdog.py:37,47`、`tools/pc2_collection_controller.py:47-53` | watchdog 只有 grace 120s 与 cooldown 600s，无最大次数、退避、告警，浏览器持续 unhealthy 时每 10 分钟无限重启；同一 tick 里 watchdog 刚重启浏览器紧接着执行 `restart.step()`，手动重启大概率得到 `health_timeout`。 | 连续 N 次失败后停止并写告警；watchdog 返回 `restart_requested` 时本 tick 直接 return。 | 小 |
| 39 | `jobs/job_manager.py:153-176,201` | `_load_job_file` 吞所有异常返回 `{"all_done": False}`，损坏 JSON 被当空任务文件，随后 `_save_job_file` 覆盖，静默丢进度。 | 解析失败抛错或重命名为 `.corrupt`。 | 小 |
| 40 | `ops/pc2-linux/compose.yaml`、`ops/pc2-linux/deploy.sh` | 9 个服务无日志轮转，worker 持续打 JSON 事件有磁盘填满风险；每次发布构建两个镜像（含 Chrome），`releases/` 与镜像不清理。 | `x-logging` anchor 加 `max-size`/`max-file`；保留最近 N 个 release 并 prune 镜像。 | 小 |
| 41 | `requirements.txt:15-20`、`Dockerfile:1` | 6 个包完全无版本；`selenium-wire`、`requests-toolbelt` 零导入；`numpy` 使用却未声明；无 lock；基础镜像用可变 tag。 | pip-compile 生成 lock，删未用依赖，镜像按 digest 固定。 | 小 |

### 4.3 P2

| # | 位置 | 问题 | 修法 | 量 |
|---|------|------|------|----|
| 42 | `src/captcha_os_windows.py` | OS 鼠标后端默认开启；生产代码里检查 `PYTEST_CURRENT_TEST`。 | 默认关闭，测试通过注入而非环境变量探测。 | 小 |
| 43 | `src/captcha_fallbacks.py`、`captcha_orchestration.py`、`captcha_preflight.py`、`src/server_data_runtime.py:12,35,97,104,328`、`src/data_fixer.py` 等 | 38 处裸 `except:` 吞掉 `KeyboardInterrupt`；288 处 `except Exception`。 | 至少改 `except Exception`，关键路径记录日志。 | 中 |
| 44 | `src/captcha_*.py` | 5 处重复的 iframe 选择器 JS 块；硬编码 `#nc_1_n1z` 等选择器；4 个指针后端无抽象。 | 抽 `_eval_in_all_frames` 助手；选择器集中常量；`OSPointerBackend` 接口。 | 中 |
| 45 | `src/llm_qualification_pool.py`、`src/llm_config.py` | 前者 sleep 最长 180s 且每次重建 `QualificationStore`；后者 import 时读 `secrets.json` 并导出 `API_KEY` 全局。 | 可中断等待与单例 store；延迟加载配置。 | 小 |
| 46 | `src/storage/repository_detail_claim.py:93-99`、`src/storage/models.py:301-308`、`repository_task_events.py:175-190` | 每批 16 个候选逐条 `SELECT ... FOR UPDATE`（N+1），`ORDER BY CASE ... LIMIT 16` 全表排序，`fapai_seed_item` 只有单列 `status` 索引；`property_ingest_event` 无清理，`created_at` 无索引。 | `WHERE item_id IN (...) FOR UPDATE SKIP LOCKED`；加 `(status, first_seen_at)`、`(event_type, created_at)` 索引；保留期清理任务。 | 小 |
| 47 | `src/storage/repository_seed_scan_pages.py:39-43,82` | 每次认领把全部 job 行与 progress 行加载到内存排序，再对每行调用 `_refresh_seed_scan_job_status`。 | SQL 排序 + LIMIT；状态刷新改聚合 UPDATE。 | 小 |
| 48 | `src/storage/repository_core.py:34-35`、`alembic/env.py:20` | `FAPAI_DB_AUTO_CREATE` 默认 True 让 `create_all` 与 Alembic 争夺 schema；`target_metadata=None` 使 autogenerate 无法发现漂移。 | 生产默认 `auto_create=False`；env.py 绑定 `Base.metadata`；CI 跑 `alembic check`。 | 小 |
| 49 | `src/collection/detail_service.py:47-57,90-93` | `dispatched_tasks` 只增不删，长期运行内存线性增长。 | TTL 驱逐。 | 小 |
| 50 | `src/server_manual_review.py:5-60`、`src/server_hybrid_*.py` | `/api/status`、`/api/avm/health` 每次同步重读约 22 个 JSON/JSONL，无缓存，单线程服务器上的热路径。 | 按 mtime 缓存快照。 | 小 |
| 51 | `src/server_auth_recovery.py:233-237`、`src/server_auth_cookie.py:275-278` | `hmac.compare_digest(str, str)` 遇非 ASCII 头值抛 `TypeError` 未捕获；`_resolve_auth_cookie_snapshot_path` 采用来自无鉴权上报的 `SOLVER_LAST_REQUEST.cookie_snapshot_path`。 | `.encode()` 后比较；路径只信任配置。 | 小 |
| 52 | `tools/pc1_desktop_recovery.py:84-97` | `requested_timeout`、`pc1_claimed_timeout`、`desktop_manual_takeover` 未映射，落到"PC2 未能确认恢复"；找不到 recovery_id 一律报 `challenge_changed`。 | 补映射；新增 `recovery_unknown`。 | 小 |
| 53 | `collector-desktop/src-tauri/src/auth_bridge.rs:86-105`、`helper_process.rs:13-19` | 四种 helper 失败映射成同一句"超时或异常"，stderr 被 `Stdio::null()` 吞掉，Rust 侧无日志；`api_base` 只校验长度与控制字符，`-` 开头的值会被 `powershell -File` 当参数名；`stdin(Stdio::null())` 被 `run()` 覆盖为 piped。 | 错误码进返回值并 `eprintln!`；stderr 读到有限缓冲；复用 `runtime_config::parse_api_base` 校验并拒绝 `^-`。 | 小 |
| 54 | `collector-desktop/src/desktop_settings.ts:62-74,126-153` | `load(false)` 中表单校验错覆盖状态行并计入 `pollFailures`；`input` 事件每次触发 `reset()` 清空 AI 密钥框。 | 校验从轮询路径拆出；`reset` 改 `change` 且不清密钥。 | 小 |
| 55 | `collector-desktop/src/desktop_runtime_controls.ts:84-87`、`desktop_settings_transport.ts:44,48`、`desktop_shell.ts:3`、`desktop_collection_views.js:235`、`tauri.conf.json:25` | 先 `response.json()` 再判 `ok`；404 判断重复不可达；import 无 `.ts` 后缀；`source_url` 无 scheme 白名单且 `target="_blank"` 在 Tauri 2 无 opener 时无反应；CSP `connect-src` 含裸 `https:`。 | 逐项小修。 | 小 |
| 56 | `ops/pc2-linux/Dockerfile.browser:4`、`deploy.sh:132` | `USER root` 后从未切回，Chrome 以 root + `--no-sandbox` 运行并挂 `/dev/uinput`；`xhost +SI:localuser:root`。 | 非 root 用户运行。 | 中 |
| 57 | `ops/pc2-linux/start-browser-solver.sh:41-47,351`、`deploy.sh:74`、`ops/pc2-host/*.ps1` | `cleanup` kill 后不 wait；只 `wait` solver，Chrome/Xvfb/relay 单独崩溃要等 healthcheck 与 watchdog 才恢复；正则硬编码 IP；19 个脚本无 `$ErrorActionPreference`。 | `wait -n`；用 `$expected_ip`；补 `Stop`。 | 小 |
| 58 | `src/server_handler_get_collection.py:81` | `_manual_review_receipt_context(active_data_root)` 同一行调用两次。 | 删重复。 | 小 |

## 5. 结构性问题

1. **`import *` 加运行时重绑定的伪模块化。** `src/server.py:50-98` 用 `types.FunctionType(code, server.globals())` 把 30 个模块的函数克隆到自己的命名空间；`src/server_context.py:398` 与 `src/storage/repository_context.py:288` 的 `__all__` 导出全部 globals；`src/data_fixer.py:20-60`、`tools/pc2_local_solver.py`、`_CaptchaFacadeModule.__setattr__` 同一套路。后果：修改 `server_context.PAUSED` 无效，只能 patch `server.X`；`global` 语句写的是别的文件的变量；IDE 与静态分析全盲。这是行数策略把 god module 切片后再用黑魔法缝回去。
2. **行数策略反噬。** `scripts/effective-code-lines.mjs` 阈值（150/500/700/1500）直接导致 189 个 `_part_NN.py` 测试切片、`live_smoke_*` 12 个文件 3517 行共享一个 `_context`、`pc2_local_solver` 从 11 个模块克隆函数。建议把阈值改为"每个模块单一职责"的评审规则，或只对 `src/` 生产代码生效并放宽测试目录。这需要用户决定，因为它是 AGENTS.md 里的门禁。
3. **全局可变状态。** 服务端约 40 个模块级变量、6 把锁、7 个后台线程、100 多处 `global`；`collection_statistics.SNAPSHOTS` 模块单例；`settings_store.status()` 用 `BEGIN IMMEDIATE` 做只读轮询串行化所有读取。应收敛为 `RuntimeState` dataclass 依赖注入。
4. **导入即副作用与反向依赖。** `src/server_context.py:29,245-247,347` 在 import 时构造 `CaptchaSolver`、repository、`AVMService`、`NasAuthRecoveryCoordinator`；`src/` 反向依赖 `tools/` 24 处；`src.storage` 依赖 `src.collection` 的 policy 与 parser，`stage_state` 又延迟 import `src.avm`；`tools.pc1_desktop_auth` 与 `tools.pc1_shared_auth` 互相导入。
5. **"generalize" 未完成。** `DEFAULT_SEED_SCAN_POLICY`、`DEFAULT_SEARCH_TASK_POLICY` 都是 Taobao 实例；`repository_search.py:19` 硬编码 `TaobaoJudicialSearchTaskPolicy.build_url`；`repository_context.py:240-268` 淘宝地区覆盖解析放在公共上下文；`detail_service.py:23` 无条件 new `TaobaoJudicialAuctionAdapter`。
6. **鉴权与状态码表分散。** 鉴权靠每个 branch 手工调用 `_nas_auth_recovery_authorized`，所以 `/auth/complete`、`/auth/force_reset`、`/api/status` 漏网；认证恢复状态码分散在 `nas_auth_recovery.py`、`pc1_desktop_recovery.recovery_phase`、`desktop_auth_contract.ts`、`server_handler_get_collection.py:175` 四处，无单一来源与跨端一致性测试；legacy 无 scope 与 v2 stage 两套状态机并存。
7. **路由是 60 个 `elif` 加 `_server_get_branch_NN` 编号函数**，`server.py:296` 再用字符串列表 `setattr` 回类上；响应体形状不统一（`{'ok':False}` 200、`{'error':{...}}`、`{'status':'id_not_found'}` 200、找不到返回 `{}` 200）。
8. **回调地狱。** `DetailProcessor.process`、`submit_html` 接收 10 多个回调参数（`src/collection/detail_processor.py:153-172`），把 server 全局状态以回调形式漏进服务层。
9. **重复实现。** PC2 三个控制器各写一遍 lock、journal、poll、sleep 循环（缺陷 #12 正是分叉产物）；HTTP 客户端三套（PC1 urllib+NoRedirect、PC2 requests、PowerShell Invoke-RestMethod）安全属性各不相同；桌面端三套 Tauri 探测、三套 HTTP 封装（超时 30s/15s/20s/40s）、`esc` 与 `escape`、`$` 与三个 `element()`；scope 到 host 映射、默认样本 URL、mkstemp+replace 写文件各有 2 到 4 份。
10. **拓扑与配置散布。** `192.168.15.104/.200/.20` 作为默认值散布在约 30 个源码与配置文件、33 个测试文件；同一配置项在 `docker_entrypoint.py`、`compose.yaml`、`env.example` 三层默认值不一致（seed loop 间隔 1800 对 60）；PC2 有 `ops/pc2-host/`（38 个 ps1）与 `ops/pc2-linux/`（Docker）两套并行部署栈，浏览器镜像靠 `Dockerfile.auth-recovery` 热修层叠加。
11. **桌面端工程缺口。** `.js` 与 `.ts` 混用且无 `tsconfig.json`，类型注解从未被检查；`package.json` 无 `test`、`lint`、`typecheck` 脚本；`object()` 通用工具放在 `desktop_overview.ts` 被 auth、settings、transport 反向依赖；`desktop_template.js` 与 `desktop_shared.js:42-43` 按 dialog id 硬编码回焦按钮，模板与逻辑双向耦合。
12. **可观测性。** `src/` 416 处 `print`、零 `logging`；死代码 `watchdog_thread`、`check_and_launch_browser` 已禁用但仍启动线程；`challengeActive`、`state.regionRefreshInFlight` 只写不读。

## 6. 测试与门禁观察

**做得好的部分**：coordinator 单飞、超时、冷却、文件锁（`test_nas_auth_recovery.py`）；403 与摘要匹配；回执不含凭据；watchdog、engine、settings runtime 的 FakeDocker hermetic 测试；Rust `helper_process` 覆盖超时与 stdin 阻塞；`test_server_source_contract.py` 用 AST 强制每个路由字面量必须出现在测试文本中。

**问题**：

1. 3111 条用例中 1225 条是对 PowerShell、Dockerfile、compose 文本的字符串包含断言（36 个文件），锁定魔数而非行为，`test_collector_desktop_tauri_app.py` 515 行基本如此。
2. 服务端测试全部起真实 TCP 服务并 monkeypatch 55 个 `server.PAUSED` 之类全局变量，慢、有状态、脆，没有单元层。
3. 存储测试全部基于 `sqlite:///tmp`，`with_for_update(skip_locked)` 在 SQLite 是空操作，认领竞争与租约回收在真实 DB 上零覆盖；唯一 PG 测试需手动设 `CROW_TEST_POSTGRES_URL`。
4. 安全面基本无测试：上传目录穿越、HEAD 泄露、CORS 加无鉴权、`data_dir` 注入、超大 body、`/auth/complete` 与 `/auth/force_reset` 负向鉴权、重定向不带 token。
5. `test_collection_controller_coordination.py:33` 在非 posix 整体 skip（fcntl），统一控制器逻辑在 Windows 开发机从不执行，409 卡死路径无任何测试。
6. 测试助手重复：`_make_repo` 13 份、`_FakeResponse` 5 份；无 conftest fixture 体系。
7. `pytest.ini` 声明的 `quick` 标记零使用，markers 自动分配导致 `-m quick` 约等于全量。
8. 无 CI 工作流；桌面 smoke 无运行器且已失效；`tests/` 目录只有 1 个从 `tools/test` 切出的文件。

## 7. 优化清单（分批）

### 第一批：安全与数据正确性止血（约 1 到 2 周，全部为小或中）

1. 修 `/api/upload` 与 `/api/avm/run data_dir` 路径穿越，覆盖 `do_HEAD`（#1、#6、#7）。
2. 鉴权收口：`_verify_control_plane_token` 缺失即拒绝、`compare_digest`；所有写接口过鉴权；`/auth/complete`、`/auth/force_reset` 加校验并白名单 `cdp_endpoint`、`cookie_snapshot_path`；CORS 白名单；`/api/status` 收敛暴露字段（#2、#3、#4、#5、#34）。
3. 桌面 `bundled_script_path` 只信任 exe 目录；Rust 侧校验 `api_base`（#8、#53）。
4. `source_payload` 合并保留内部字段并加回归测试（#9）。
5. 三个认领函数改原子 `UPDATE ... RETURNING` 或 `SKIP LOCKED`；`_lease_reclaimable` 去掉调用方 `lease_seconds`（#10、#11）。
6. PC2 控制器 409 journal 卡死修复并补 Windows 可跑测试（#12）。
7. 密码出脚本：desktop launcher 与 postgres 脚本改凭据文件（#16）。
8. PC2 `allow_redirects=False`；Cookie 快照原子 0600 写；`desktop-auth/` 快照生命周期清理（#31、#32、#33）。
9. `_read_json_body(max_bytes)` 统一 body 读取；500 不回传 `str(e)`（#21、#26）。
10. LLM 重试改 `Retry-After` 冷却；统一 token 预算（#19、#20 前半）。

**每项都要附负向测试**，这是本批与后续批次的验收标准。

### 第二批：并发与运行时健壮性（约 2 到 4 周，以中为主）

1. `ThreadingMixIn` + handler timeout；同步长任务改任务 ID 轮询（#17）。
2. solver、pause、任务队列状态封装为带锁对象，消灭 `global` 裸写；`SEEN_IDS` 原地更新（#22、#23、#24）。
3. `captcha_orchestration.solve()` 加 deadline，`sleep` 改 `Event.wait`（#18）。
4. 时间统一 aware UTC，删除 `_repository_datetime` hack，注入 clock（#27）。
5. entrypoint 改 `os.execvp`，compose 加 `init: true` 与 `stop_grace_period`，worker 加 SIGTERM 释放租约（#13）。
6. worker 心跳文件 + healthcheck 读心跳；watchdog 加最大次数与告警；同 tick 不叠加重启（#14、#38）。
7. 补索引、ingest_event 保留期清理、`alembic/env.py` 绑定 metadata 并在 CI 跑 `alembic check`（#46、#48）。
8. CI 加 Postgres 作业（testcontainers 或 compose），认领与租约测试跑在 PG 上，加 2-worker 并发用例。
9. compose 日志轮转、release 与镜像保留策略、requirements lock、删未用依赖、镜像 digest 固定（#40、#41）。
10. 桌面轮询策略重构；`parseEditableValue` 按原类型；smoke 运行器并修选择器（#35、#36、#37）。

### 第三批：结构还债（约 1 到 2 个月，以大为主，需要先做决定）

1. **重新评估行数策略**：改为只对 `src/` 生效并放宽测试目录，或改为职责评审规则。这是前提，否则下面的合并会被门禁挡回。
2. 拆掉 `import *` 与 `FunctionType` 重绑定：`server_context` 改为显式 `RuntimeState` 依赖注入；`repository_context` 只留 helpers，16 个 Mixin 显式 import；删除 `data_fixer`、`pc2_local_solver`、`_CaptchaFacadeModule` 的克隆门面。
3. 路由表化：`ROUTES = {(method, path): handler}`，删 60 个 `elif` 与 `_branch_NN` 命名；统一错误 envelope，`{}` 与 `id_not_found` 改 404。
4. 存储层去淘宝默认：`policy` 必填或 `PropertyRepository(adapter=...)` 注入；删 `repository_search.py` 淘宝 URL 硬编码；storage 只依赖 contracts，打断 `src.storage` 与 `src.collection` 的循环。
5. 认证恢复状态码单一来源 `auth_recovery_codes.py`，生成 TS 契约并加一致性测试；设弃用期后仅保留 v2 stage 状态机。
6. 传输层强制 https 并按角色分 token（#15）。
7. PC2 三个控制器合并为一个模块；拓扑集中到单一 env 文件，清除代码内 192.168 默认值；决定 `ops/pc2-host` 是否退役。
8. 验证码：`OSPointerBackend` 抽象、`_eval_in_all_frames` 助手、选择器常量化。
9. 桌面端：加 `tsconfig.json`（strict、noEmit）与 `npm run typecheck`、`test`、`lint`；`.js` 逐个改 `.ts`；抽 `desktop_dom.ts`、`desktop_http.ts`、`desktop_native.ts`；IP、端口、间隔集中到 `desktop_config.ts`。
10. 测试套件：`_part_NN` 合并为不超过 30 个按行为组织的模块；conftest fixture 替代 13 份 `_make_repo`；1225 处脚本文本断言改为行为断言；真实 `unit`、`integration`、`desktop` 标记并让 CI 快路径小于 60 秒。
11. `print` 换 `logging`；裸 `except:` 清零；删死代码。

### 门禁建议（贯穿三批）

- 引入 `ruff`（含 `E722` 裸 except、`B` 系列）与 `mypy --strict` 增量模式，从新改动文件开始 ratchet。
- 新增 `.github/workflows/ci.yml` 或等价流水线：快路径跑 `node --test`、`cargo test`、`pytest -m unit`；夜间跑 PG 集成与桌面 smoke。
- 安全用例作为独立标记 `security`，每个 P0 修复必须带一条。

## 8. 验证方式

第一批完成后应能通过：

```
pytest tools/test -m security
pytest tools/test/test_desktop_auth_launcher.py tools/test/test_nas_auth_recovery.py
node --test scripts/tests/effective-code-lines.test.mjs
node scripts/effective-code-lines.mjs --mode ratchet --json artifacts/effective-code-lines.json
git diff --check
```

第二批需要在 `CROW_TEST_POSTGRES_URL` 指向真实 Postgres 的环境下跑认领并发用例，并在 PC2 上验证 `docker restart` 在 `stop_grace_period` 内优雅退出。
