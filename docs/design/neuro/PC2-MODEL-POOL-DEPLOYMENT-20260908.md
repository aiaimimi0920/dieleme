# PC2 模型池修复部署与运行验证

日期：2026-09-08，北京时间；最终容器复核时间为 05:41。时间均为北京时间，原始回执使用 UTC。

## 当前结论

**PC2 侧的模型池请求保护修复已实际部署，不再是仅修改本地源码。** 4 个商品分析 worker 均已重建为新镜像并通过健康检查；原环境变量、启动参数、安全和资源配置、数据挂载均保持一致。

**商品分析恢复尚未确认。** 新版首轮测试中，`deepseek-v4-flash` 已有 3 个标准案例全部答对，随后一个请求超时。因此，“所有模型完全无法调用”不是当前事实，但该模型尚未完成五例资格测试，不能冒充已获得 4/5 合格分数，也不能把容器 healthy 当成业务恢复。

新版已经按预期进入共享冷却，避免在相同故障下继续高频扫描模型和别名。已经观察到下一轮自动重试：冷却结束后尝试 `guji/deepseek-v4-flash`，收到 HTTP 503 后再次停止并退避。**截至 05:39，合格模型仍为 0，AI 归档仍为 79524，待分析有 27385 条。PC2 代码修复和部署完成，端到端分析恢复未完成。**

## 1. 本次实际部署范围

用户明确授权 PC2 修复后，仅定向执行：

- 替换镜像内的 `src/llm_qualification_pool.py`、`src/llm_qualification_store.py`、`src/llm_qualification_transport.py`。
- 重建、重启 `pc2-analysis-1` 至 `pc2-analysis-4`。
- 保留 PC2 原 Compose、容器配置快照及私有模型池 SQLite 一致性备份。
- 按约定重启本机 Crow 程序，未重启电脑。

没有部署或重启 NAS，没有重建链接、详情采集或认证浏览器容器，没有修改共享 AIGateway 的配置，也没有更换或导出密钥。

这次部署针对采集引擎的 AI 归档阶段，不表示 Crow 独立的数据分析引擎或预测引擎已经完成。

## 2. 镜像与容器证据

旧镜像：

```text
sha256:04b7a2ec2dedd9942d4ee446b4b0bf27e405f3c75088df8d64b83f028aefb0c3
```

新镜像标签：`fapaifang-worker:20260908-modelpool-throttle-r1`

新镜像 ID：

```text
sha256:475f7f1e4c4a0be5285728149b8bc8fa8f5f59435d2435cb66ffa869fe52b44a
```

新镜像从已确认的旧镜像派生，仅增加三份 Python 源码和发布标记，未上传整个脏工作区，未安装或升级依赖。

| Worker | 新容器 ID 前缀 | 启动时间 | 05:25 检查 |
| --- | --- | --- | --- |
| analysis-1 | `98a07c8f7ed9` | 05:23:18 | running / healthy，重启计数 0 |
| analysis-2 | `0db666943134` | 05:23:18 | running / healthy，重启计数 0 |
| analysis-3 | `4738c1c50a3d` | 05:23:17 | running / healthy，重启计数 0 |
| analysis-4 | `38f9c7958dd8` | 05:23:18 | running / healthy，重启计数 0 |

4 个容器内的三份源码 SHA-256 均与经过测试的本地补丁清单一致。全部环境变量逐项相等，命令、工作目录、用户、健康检查、重启策略、网络、权限、安全选项、内存/CPU/进程限制和挂载配置均核对一致。05:41 再次复核时，四个容器仍为 healthy，重启计数仍为 0，容器 ID 未发生变化。

以下容器的 ID 与部署前完全一致，未被本次操作重建：

- `fapaifang-pc2-seed-1`
- `fapaifang-pc2-detail-1`、`detail-2`、`detail-3`
- `fapaifang-pc2-browser-solver`

证据：[PC2 部署回执](C:/Users/Public/nas_home/crow/.debug/model-pool-throttle-20260908/pc2-deployment-receipt.json)、[补丁清单](C:/Users/Public/nas_home/crow/.debug/model-pool-throttle-20260908/patch-manifest.json)。补丁清单保留打包时的 `local-verified-not-deployed` 历史状态，实际部署状态以部署回执为准。

另有 [只读安全核验明细](C:/Users/Public/nas_home/crow/.debug/model-pool-throttle-20260908/pc2-safety-audit.json)：包含各项运行配置比较结果、前后配置整体哈希、环境变量数量及挂载数量；确认新镜像保留旧镜像全部文件系统层，仅新增三层 COPY；包含实际 Dockerfile、仅四个 image 字段变化的配置差异、备份文件大小/权限/哈希和完整性复查结果。凭据值和私有配置正文没有输出。

## 3. 请求行为验证

### 第一轮自动资格测试

05:26:48 读取新版实际使用的模型池命名空间：

- 新命名空间已创建；旧命名空间仍保留，没有删除旧记录。
- `reasoning_effort=none`，业务配置超时仍为 180 秒；资格探测超时上限为 60 秒。
- `deepseek-v4-flash` 的前三例实际结果匹配为 `[1, 1, 1]`。
- 随后发生 `ReadTimeout`，该轮耗时约 136.613 秒。
- 记录为 `status=probe_error`、`score=null`，而非错误地记录模型五题全部答错。
- 合格模型数为 0，共享冷却剩余约 564 秒；资格租约已经释放。

05:31:38 再次只读检查：仍为同一条测试记录，没有继续扩散到其他模型；冷却剩余约 274 秒，下一次请求时间保持不变。这证明共享退避在实际运行中生效，而不只是单元测试通过。

这些观察通过读取模型池 SQLite 完成，没有额外向模型服务发送人工探测请求，没有调用 GPT/Codex/o 系列模型，没有修改评分、清空模型池或绕过服务方限制。

证据：[第一次观察](C:/Users/Public/nas_home/crow/.debug/model-pool-throttle-20260908/runtime-observation-1.json)、[冷却期间复查](C:/Users/Public/nas_home/crow/.debug/model-pool-throttle-20260908/runtime-pool-observation-2.json)。

### 冷却后的自动重试

05:36:14 自动重试触发，选择 `guji/deepseek-v4-flash`，约 0.575 秒后得到 HTTP 503，没有获得案例答案。程序将该项记录为 `probe_error`、`score=null`，再次进入 600 秒共享冷却，而不是继续向剩余模型刷请求。

05:38:57 读取池状态时，冷却剩余约 437 秒，租约已释放；合格模型数仍为 0。第一轮三个正确答案记录仍保留。这个结果证明自动重试及错误后的退避都已在线执行，但没有证明 `guji` 上游恢复；仅凭这次 HTTP 503 也不能判断封禁的具体剩余时间。

证据：[自动重试及业务统计复查](C:/Users/Public/nas_home/crow/.debug/model-pool-throttle-20260908/runtime-observation-3.json)。

### 业务计数

使用 NAS 轻量状态接口的统计快照，没有额外做业务数据库全表实时计数。

| 时间 | 已采详情 | 已 AI 归档 | 分析进行中 | 待分析 |
| --- | ---: | ---: | ---: | ---: |
| 05:17，部署前 | 108257 | 79524 | 0 | 27359 |
| 05:27，部署后 | 108283 | 79524 | 0 | 27385 |
| 05:39，自动重试后 | 108283 | 79524 | 0 | 27385 |

部署前后短窗口内详情增加了 26 条，随后观察未再增加；上述窗口内 AI 归档没有增长。这不是没有待处理商品，仍有 27385 条积压。更早调查中的 79342 与这里的 79524 之间的差额发生在本次部署前，不能归功于本次修复。

NAS 状态仍显示“待认证”。这次没有操作链接采集或认证浏览器；商品分析 worker 仍独立运行，其当前障碍是模型资格测试未完成，不应将所有停滞都归因于采集挑战。

## 4. 数据保护与回滚准备

本次没有执行 PostgreSQL 清空、迁移、恢复、维护写入或删除卷，没有执行 `down -v`，没有修改已有业务记录来制造增长。原有正常采集写入继续进行。

PC2 发布目录：

```text
/srv/apps/fapaifang-worker/shared/collection-control/release-20260908-modelpool-throttle-r1
```

目录内保留：

- `original-compose.private.json`：原部署配置，仅留在 PC2 私有目录，包含的凭据未输出。
- `before.private.json`：原容器状态和运行配置快照。
- `model-pool-backup.private.sqlite3`：只读连接源数据库后通过 SQLite backup API 生成的一致性备份，`PRAGMA integrity_check` 返回 `ok`。
- `compose.json`：本次候选配置，仅四个分析服务的镜像字段不同。
- `prepared.json`、`deployment-receipt.json`、构建日志。

如果需要回滚代码，可在再次确认当前服务未被其他部署改变后，在 PC2 执行以下定向命令；**本次没有执行回滚**：

```sh
release=/srv/apps/fapaifang-worker/shared/collection-control/release-20260908-modelpool-throttle-r1
DOCKER_CONFIG="$release/docker-config" HOME="$release" docker compose \
  --project-name fapaifang-pc2 --project-directory "$release" \
  -f "$release/original-compose.private.json" \
  up -d --no-deps --no-build --pull never \
  pc2-analysis-1 pc2-analysis-2 pc2-analysis-3 pc2-analysis-4
```

回滚无需恢复或覆盖业务数据库，也无需用备份覆盖正在使用的模型池；旧版命名空间仍在。回滚会重新引入旧版请求放大问题，不建议因上游超时而直接回退。

## 5. 验证与部署中处理的边界问题

- 本轮新跑联合 Python 回归：**145 passed，55.32 秒**。
- 模型池专项新跑：**52 passed**。
- 有效代码行检查器：**19 passed**。
- Ratchet：942 个文件，通过；未更新基线。
- 相关补丁 `git diff --check` 通过。
- 新镜像在无网络、只读根文件系统、无数据挂载的临时容器中，源码校验、编译和导入通过。该检查故意不提供凭据，因此导入时的缺少 `secrets.json` 提示不代表线上凭据丢失。
- Compose 在默认 SSH 环境下启动超时；改用此次命令专属的本地工作目录、`HOME` 和 `DOCKER_CONFIG` 后正常运行。未改写 PC2 用户全局配置，未将具体触发因素未经验证地归因于某个全局文件。
- 模型池目录属于 root 且权限为 0700；使用已可用的 `sudo -n` 进行只读源库备份，没有放宽目录或凭据权限。
- 首次离线临时容器验证超过 60 秒；改为非交互入口并设置有界等待后通过，未把超时视为成功。
- 部署后初次配置核验发现 Docker 返回的挂载数组排序变化。逐字段确认仅顺序不同后，校验器按目标路径排序；所有字段仍参与比较，没有忽略真实的挂载差异。没有因此多重启一次分析 worker。

## 6. 本机 Crow

按约定已重启本机 Crow，安装版本仍为已验证的 `20260908-manual-auth`：旧 PID 52536，新 PID **22456**，05:28 完成检查；31 个安装文件哈希通过，运行配置未改变，进程响应正常。

本次三份 Python 模型池模块不在桌面发布载荷内，所以没有伪造新的 EXE 构建，也没有修改前端。未关闭认证浏览器，未重启电脑。

证据：[本机 Crow 重启回执](C:/Users/Public/nas_home/crow/.debug/model-pool-throttle-20260908/desktop-restart-receipt.json)、[逐文件哈希和进程复核](C:/Users/Public/nas_home/crow/.debug/model-pool-throttle-20260908/desktop-live-verification.json)。后者记录各文件实际哈希与清单匹配结果、进程响应、窗口句柄及旧 PID 已退出。

## 7. 剩余限制

PC2 授权没有被扩张为修改共享 AIGateway 或 NAS。此前发现的上游封禁和网关重试配置是部署前调查证据；本次真实测试已经出现三个正确答案，不能继续把旧的“完全不可调用”观察当成现状。

仍需以完整五例测试达到至少 4 分、真实业务处理成功和归档数量增长来确认端到端恢复。共享网关或上游服务持续超时不能由重启 PC2 本身保证修复；也不能通过降低评分标准、借用其他账号或取消节流来假装解决。

后续处理边界：继续保留 PC2 的自动重试保护；如需主动修复共享网关的路由/重试或更换合法上游配置，应在 AIGateway 项目确认具体变更并获得相应线上操作授权。本轮没有擅自扩大“PC2 修复”的授权范围。
