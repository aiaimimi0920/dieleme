# 分阶段认证 V2 线上部署报告

核验日期：2026-09-08，Asia/Shanghai。最终运行核验约 10:08。

## 结论

**新协议已部署到 NAS API、PC2 认证接收端和 PC2 链接采集端，并完成真实网络握手验证。**

- NAS 返回 `stage_auth_protocol: 2`。
- NAS 返回 `pc2_stage_auth_ready: true`，确认新版 PC2 接收端正在自行发送能力心跳。验证脚本没有伪造这次心跳。
- 已认证的协议状态请求返回 HTTP 200；非法阶段请求返回 400；无认证凭据请求返回 403。
- PC2 认证接收端、链接采集端最终均为 `running / healthy`。
- PC2 原有 3 个详情采集容器、4 个 AI 分析容器的 ID、镜像、运行状态、环境配置和挂载保持不变。
- PostgreSQL 容器 ID、镜像和数据卷保持不变，最终状态为 `running / healthy`。
- 本机 Crow 已重新启动到此前安装的分阶段认证版本，桌面 `Crow.lnk` 已刷新并核验。

**仍需人工完成的部分：链接采集当前确实处于独立的人工认证暂停状态。部署协议不会替代人工通过挑战。**

最终业务状态样本：

| 阶段 | 状态 |
| --- | --- |
| 链接采集 `seed` | `paused=true`、`manual_required=true`、`pause_reason=manual_required` |
| 详情采集 `detail` | `paused=false`、`manual_required=false`、`last_status=idle` |

这与两个阶段分别认证的设计一致，不应因为详情可采集，就把链接认证标记为成功。

下一步可在已重启的 Crow 中选择**链接采集认证 → 打开挑战页面 → 人工通过挑战 → 已完成挑战**。PC2 会导入认证快照，并重新请求真实列表页面验证链接阶段；不会再用详情数量增长作为链接认证成功的依据。

本次没有代替用户提交虚假的认证完成任务。因此，**部署和协议握手已验证；新版协议下真实人工挑战完成后的端到端成功，仍待实际人工操作验证**。线上最近一条历史成功回执的 `scope` 为 `null`、原因为 `captured_count_advanced`，属于旧协议回执，未把它作为 V2 人工认证成功证据。

## 部署范围与镜像

采用当前运行镜像作为基底，仅覆盖认证协议涉及的源码文件，没有同步整个脏工作区。

| 目标 | 覆盖文件数 | 当前容器 ID 前缀 | 当前镜像 SHA256 |
| --- | ---: | --- | --- |
| NAS `fapaifang-api` | 8 | `51dea0f12608` | `afc113a0b98940dfc9056659d0136f7c3565c8d6e770adfee6a6a640a585a1b9` |
| PC2 `fapaifang-pc2-browser-solver` | 3 | `1e922e4263cf` | `f2d24313bb7a7a62ba75e966ea507c74b86d668c4b4ee7600ad64177908bff40` |
| PC2 `fapaifang-pc2-seed-1` | 1 | `a4ff26ea230b` | `68a8fb073ac0498640e38526f045c4cf648bbbece124e8ff4808366457af31ee` |

对应镜像标签：

- `fapaifang-collector:nas-20260908-stage-auth-v2`
- `crow-browser:20260908-stage-auth-v2`
- `fapaifang-worker:20260908-seed-stage-auth-v2`

NAS 未替换 `server.py`，避免把与本次协议无关的本地设置界面改动一并部署。镜像中既有拆分依赖经去除 BOM、统一换行后的源码比较确认一致，不需要批量覆盖。

所有目标容器均核验了已安装文件 SHA256，以及环境变量、启动命令、用户、重启策略、端口、资源限制和数据挂载等运行契约。NAS API 原本没有 Docker healthcheck，不能把其 `health=null` 写成 Docker 健康检查通过；其实际可用性由真实 HTTP 200 和协议响应验证。

PC2 认证容器最终 `RestartCount=1`，链接容器为 0；最终两者均为 healthy。本次报告不将进程健康等同于站点挑战已经通过。

## 数据保护

切换前通过正在运行的 PostgreSQL 执行一致性 `pg_dump -Fc`，并完成目录检查和整个备份的解码检查。

- 备份：`/volume1/docker/fapaifang/releases/20260908-stage-auth-v2/postgres-before.dump`
- 大小：`238818206` 字节。
- SHA256：`867fb1e531b12940f383185374e33aa8954743b062e3276156ed6dcebfa3ea32`
- 权限：`0600`；部署目录不向其他用户开放。
- `pg_restore -l` 成功。
- `pg_restore -f /dev/null` 完整解码成功。
- PostgreSQL 容器 ID 始终为 `9ea6c8cce67a8d19cf9152ff96abf03691c9b3303da69ce76caecb09c476edd4`。
- 数据目录仍为 `/volume1/docker/fapaifang/postgres`，挂载到 `/var/lib/postgresql/data`。

没有清空数据库、删除卷、执行数据库恢复、重置采集队列或更换 PostgreSQL 镜像。没有部署新的数据库迁移源码。PC2 浏览器 profile、认证快照、输出和 secrets 挂载保持不变；凭据和 Cookie 内容没有写入报告。

最终一次轻量状态样本为：唯一链接 `272109`、商品详情 `108839`、商品分析 `79524`。这是状态快照，不是本次部署期间增长量的证明；没有为验证部署而反复执行全库 COUNT。

## 部署异常与恢复记录

此次部署并非全程无中断，以下问题已经明确记录：

1. **NAS 历史镜像接近 Docker 层深度上限。** 最初逐文件 COPY 的候选构建报 `max depth exceeded`。改为按已筛选的源码目录 COPY，减少新增层数；没有压平或重建整个生产基底。
2. **NAS 使用旧版独立 `docker-compose`。** 隔离 HOME 下没有 `docker compose` 插件；旧版 Compose 输出的 JSON 还包含无法回读的 `command: null` 等字段。部署脚本改用实际存在的工具，并只剔除无值字段。
3. **NAS 控制器存在错误的 Compose 服务标签。** `crow-collection-control` 错误声明自己属于 `app / fapaifang-api`，且缺少容器序号。第一次 Compose 切换因此误处理控制器，发生 API 切换中断、控制器被停止和改名；尝试 Compose 回滚也受到相同标签问题影响。
4. **已恢复现场并切换精确容器操作。** 恢复原控制器的名称和运行状态，再通过 Docker API 按精确名称创建新版本 `fapaifang-api`，继承原 API 的配置、HostConfig 和网络配置。最终 API HTTP 验证通过，原控制器 ID `0d5be834d6cb36336e7e72b419f1f6ee65d90c746ce99c45c7c4f9dee7665f10` 未改变，恢复后为 healthy。数据库未停止。

不能把本次描述为“零停机部署”或“所有非目标服务从未重启”。PC2 的详情与 AI 容器确实未重建；NAS 控制器则因上述标签冲突受到影响，随后恢复。

**遗留运维风险：控制器的错误 Compose 标签本身没有在本次认证协议发布中重建修正。不要对 NAS 的 `app / fapaifang-api` 继续盲目执行 Compose up/rollback。后续 NAS API 更新或回滚应沿用精确容器 ID/名称操作，或者先单独修复控制器标签归属。**

## 回退材料

原镜像和私有运行配置均保留，没有执行镜像清理。

- NAS 发布目录：`/volume1/docker/fapaifang/releases/20260908-stage-auth-v2`
- PC2 发布目录：`/srv/apps/fapaifang-worker/shared/collection-control/release-20260908-stage-auth-v2`
- 两端均保存 `before.private.json`、原 Compose 声明、候选声明、文件哈希和部署回执。
- PC2 保存 browser、seed 两份仅改变目标镜像且保留实际运行环境的 rollback Compose 声明。
- NAS 原 API 镜像：`sha256:168f84dcfecf097eca311f3e38d657607b7c543279275e0bea1a75edd3651e61`。
- NAS 回退必须使用精确容器操作，**不要直接执行已保存的 NAS rollback Compose**，原因见上面的标签冲突记录。

私有文件可能包含运行凭据，不应复制进 Git 或直接输出到终端。回退认证代码不需要恢复数据库备份；没有数据损坏时不得用旧备份覆盖继续写入的数据库。

## 本机 Crow

- 安装目录：`C:\Users\vmjcv\AppData\Local\FapaiFangCollectorDesktop`
- 可执行文件：`C:\Users\vmjcv\AppData\Local\FapaiFangCollectorDesktop\fapaifang_collector_desktop.exe`
- 当前版本：`20260908-stage-auth`，本次没有为相同桌面源码重复构建。
- EXE SHA256：`4979bd5d53546ca95c9974a05d850fe5edd15c4e58ed0dce44df77827de07e2d`
- 重启时间：2026-09-08 10:07:14 左右。
- 重启后的 PID：`49332`。
- 桌面快捷方式：`C:\Users\vmjcv\Desktop\Crow.lnk`，目标、工作目录已核验。

只重启 Crow 程序，没有重启电脑，也没有关闭 PC1 的人工认证浏览器。重启前识别到的认证浏览器主进程 PID `53512` 在重启后仍存在。

## 验证与证据

本轮新运行的验证：

- 分阶段认证回归测试：`14 passed`。
- effective-code-lines 测试：`19 passed`。
- effective-code-lines ratchet：通过，950 个受检查文件；既有未改动的超大文件债务仍保留，不作已清理声明。
- `git diff --check`：通过。
- NAS 候选镜像：源码哈希、编译、导入、两阶段回执、快照摘要校验、PC2 心跳 TTL、详情恢复条件测试通过。
- PC2 候选镜像：源码哈希、编译、导入、合法空列表和错误页面判定测试通过。
- seed 候选镜像：导入和显式 `scope=seed` 通知检查通过；该检查不冒充真实站点采集测试。
- 隔离镜像测试未挂载生产凭据和生产数据，未访问外网。测试中“没有 secrets.json / 0 models”的启动提示是隔离环境所致，不是线上 AI 模型池不可用的证据。
- 线上实际 V2 能力心跳、请求鉴权和非法阶段拒绝验证通过。

本地证据目录：`C:\Users\Public\nas_home\crow\.debug\stage-auth-deploy-20260908`

主要非敏感回执：

- `protocol-handshake.json`
- `nas-deployment-receipt.json`
- `pc2-deployment-receipt.json`
- `nas-database-backup.json`
- `nas-exact-activation.json`
- `nas-health.json`
- `pc2-health.json`
- `crow-restart.json`

本轮没有提交 Git commit、回退用户已有修改、更新 AI 模型选择配置或部署新的分析功能。发布成功与站点人工认证成功分开报告，避免再次把“快照传输完成”误当成“链接已经恢复采集”。
