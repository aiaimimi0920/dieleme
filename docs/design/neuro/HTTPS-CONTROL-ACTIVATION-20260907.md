# 采集运行配置：HTTPS 控制链路已上线

日期：2026-09-07，Asia/Shanghai。

## 结论

此前“线上应用尚未启用、HTTPS 控制入口未确认、PC2 控制器未接入”的阻塞已经解除。

- NAS 已启用独立 HTTPS 控制服务：`https://192.168.15.200:18443`。
- PC2 统一控制器已启动并设置开机启动，最后检查为 `active / enabled`，自动重启次数为 0。
- PC1 的三个桌面安装目录均已更新；控制地址、应用专用 CA 和本机控制凭据已接入，不需要手填控制授权。
- 设置仍可编辑、保存本机草稿；“保存并应用”现在能够提交到 NAS，并收到 PC2 的最终应用回执。
- 原 NAS API、PostgreSQL、8 个采集 Worker 和浏览器均未重建；原容器、启动时间和挂载保持不变。

这里的“数据库未改动”是指没有清空、覆盖、迁移或恢复业务库。采集服务继续正常写入新增数据，不是把业务数据库冻结不变。

## 现在如何使用

1. 使用原来的 Crow 桌面快捷方式。当前运行进程已经是本次更新后的 EXE。
2. 打开左下角“设置”中的“采集运行配置”。
3. 点击“读取线上配置”，以 PC2 实际生效参数作为编辑基线。
4. 修改 Worker 数量、采集间隔、重试参数或 AI 参数后，点击“保存并应用”，确认操作。
5. 等待状态显示“参数已应用”。“已保存，等待 PC2 应用”只是排队，不代表已经生效。

AI API Key 留空会保留现有密钥；密钥不会回显，也不会进入本机草稿。已有草稿如果基于旧版本，界面会要求重新读取线上配置，避免覆盖较新的设置。

普通数据 API 默认地址仍是 `http://192.168.15.200:8001`。不要把普通 API 地址改成 18443；两个入口职责不同。

## 真实线上验证

### 1. 无参数变更的应用请求

通过已经安装的桌面助手发起请求，使用本机配置文件和凭据，清除了调用进程中的 `FAPAI_*` 和 `PYTHONPATH` 覆盖项：

| 项目 | 结果 |
| --- | --- |
| 请求 ID | `verify-noop-c77a8692909d411dacb3a94b467ce4fe` |
| 版本 | `0 → 1` |
| 观察到的状态 | `requested → applying → succeeded` |
| PC2 最终结果 | `applied` |
| 参数 | 与请求前完全一致 |
| AI 密钥 | 保留，不替换 |
| 三个桌面安装目录 | 均能读取同一份 HTTPS 生效配置 |

验证时间为北京时间 2026-09-07 00:28:47。请求经过了真实 NAS 持久化、PC2 领取、Compose 配置校验、生效模型保存和最终回执，不是前端模拟成功。

### 2. 原生桌面桥接

额外从正式安装目录执行了 Rust 原生桥接的只读探针，实际调用了配置读取和 HTTPS GET：

- 读取到应用专用 CA、固定 Python 路径和已安装的控制组件。
- HTTPS 返回 `ok=true`、`available=true` 和真实生效配置。
- 探针通过；默认测试运行不会执行这个线上探针。
- 最后检查桌面进程 PID 为 `10260`，`Responding=true`，执行路径为正式安装目录。

### 3. 数据及运行实例保护

- PostgreSQL 容器 ID：`9ea6c8cce67a8d19cf9152ff96abf03691c9b3303da69ce76caecb09c476edd4`，与上线前相同。
- NAS 原 API 和 PostgreSQL 的镜像、启动时间、挂载逐项核对无变化。
- 15 张有主键的业务/管理表完成旧主键集合核对，缺失数全部为 0。
- PC2 的 8 个 Worker 和浏览器 ID、镜像、配置、启动时间、挂载均与上线前一致；Worker 全部健康。
- 本次没有执行 `down -v`、数据库恢复、迁移、清表、卷删除或 Worker 重建。

新建并完整解码验证的 PostgreSQL 备份：

```text
/volume1/docker/fapaifang/backups/postgres/20260906-https-control/before.dump
bytes: 233906474
sha256: 58b5cfaa94fd31763478018951c8327d627053efd36c1334eac0bca59f9ba3c6
schema: 20260905_0011
```

## 实现与部署范围

### NAS

新容器 `crow-collection-control` 只提供设置和引擎重启的控制邮箱，不替换原 API 镜像：

- 仅发布 NAS 局域网地址的 18443 端口。
- 使用服务端 TLS 和不同的 operator/agent token 进行权限区分，不是双向 TLS。
- 验证完整证书链、IP SAN 和 TLS 版本；没有关闭证书校验。
- 只挂载控制状态目录、只读 token 文件和必要证书文件，没有业务数据库凭据、业务数据库卷或 Docker socket。
- 容器启用只读根文件系统、去除 capabilities、禁止提权，并限制内存和进程数。
- NAS 内核不支持 NanoCPUs/CFS 限额，因此没有声称 CPU 限额已生效。

证书采用应用专用 CA，没有修改系统信任库、Synology 443 配置或 SSH 转发策略。普通浏览器不会自动信任这个私有 CA；正式桌面通过原生组件使用指定 CA。

服务端证书到期时间为 **2027-09-07 00:22:32（北京时间）**，到期前需要续签并重载独立控制服务。

### PC2

统一控制器沿用 `crow-engine-controller.service` 名称，由一个进程处理配置与引擎重启。旧隧道服务没有启用。

持久状态目录：

```text
/srv/apps/fapaifang-worker/shared/collection-control
```

其中 `active.json` 保存真实生效的 Compose 模型，独立于 Worker 发布目录；文件和目录受权限保护，包含敏感运行配置，不应提交或公开。

原先实际容器与发布环境文件之间的 `OPENAI_MODEL`、`OPENAI_MODEL_CANDIDATES`、`OPENAI_REASONING_EFFORT` 差异已保留在实际运行基线中，没有用旧发布文件覆盖线上值。

设置应用、引擎重启和正常 deploy/rollback 入口共用操作锁。发布流程接入了设置保留逻辑：采用新发布镜像时保留已保存的参数和 AI 密钥，拒绝未经单独迁移的挂载变更。缺少辅助组件或存在未确认的发布日志时会拒绝继续，而不是静默覆盖配置。

### PC1 桌面

三个安装目录均校验了 18 个当前运行文件，并写入 `crow-control-install.manifest.json`：

```text
%LOCALAPPDATA%\FapaiFangCollectorDesktop
%LOCALAPPDATA%\FapaiFangCollectorDesktop\updates\20260906-manual-auth
%LOCALAPPDATA%\FapaiFangCollectorDesktop\updates\20260906-runtime-settings-editable
```

最终 EXE SHA-256：

```text
d597c380514cf6e15f11fcfd86c9f31cbf5c17408a20c3803d54d1214d26a450
```

应用 CA 和 operator token 存放在 `%LOCALAPPDATA%\CrowControl\20260906`，ACL 仅授权当前用户、SYSTEM 和管理员。运行配置记录路径，不包含 token 内容。原生桥接使用固定解释器路径，AI 密钥经标准输入和 HTTPS 传输，不写入命令行。

## 过程中定位并解决的问题

1. NAS 默认 OpenSSL 配置与额外 CA 扩展叠加产生重复扩展：改用明确的 CA 配置，重新验证证书链。
2. PC2 Python 3.13 严格校验要求证书 AKI/SKI：补全证书扩展，没有降低验证标准。
3. Synology 继承 ACL 使控制状态目录实际为 0755：明确设置并核验为 owner-only 0700。
4. Docker 挂载数组顺序不稳定导致保护检查误报：改为逐挂载完整字段集合比较，数据挂载实际未变。
5. 桌面助手独立安装缺少 schema 的异常类型依赖：补齐运行组件，并增加脱离仓库的安装闭包测试。
6. 控制器 lifetime lock 的 keyword-only 参数调用错误：修正并在 PC2 Linux 上实际验证锁互斥。

## 验证汇总与边界

- Python 聚焦回归：81 通过，1 个 Windows 不支持的 Linux flock 测试跳过；对应锁行为已在 PC2 Linux 上单独验证。
- TypeScript/Node 逻辑测试：19 通过。
- Rust 默认测试：5 通过；另一个默认忽略的原生只读线上探针显式运行通过。
- Chromium 设置编辑、应用竞态和启动草稿回归：38 项检查通过。
- 严格 TypeScript 检查、Vite/Tauri release 构建通过。
- 有效代码行测试：19 通过；ratchet 通过，保留 1 个未改动的历史超大文件，没有新增超限文件。
- `git diff --check` 通过；本次检查的修改文件为 UTF-8 无 BOM。原有脏工作区保留，没有提交或回退既有改动。
- NAS 5 个控制运行源文件、PC2 8 个控制/发布源文件的线上哈希与工作区一致。

**验证边界：** 本次真实线上验收使用无参数变更的请求，没有为了演示而重建 Worker。参数变更后的局部重建、缩容和失败回滚由离线 Docker 测试覆盖；没有将其表述为已经执行过线上重建/回滚。也没有用一次容器健康检查宣称 AI 推理或所有挑战问题已经解决。

“连续挑战失败多少次后唤起 PC1”仍是尚未接入的独立配置项。本次不改动现有人工认证策略。

## 备份、回滚与证据

- 桌面更新前文件：`%LOCALAPPDATA%\FapaiFangCollectorDesktop\backups\20260907-https-control`。
- PC2 旧 unit、旧 deploy 脚本和原始运行基线：持久控制目录下的 `before/`。
- NAS 原 API 和数据库不需要为了撤销独立控制服务而恢复数据库。
- 如需撤回控制功能，应先确认没有正在进行的操作，再停用新增控制能力并恢复相应桌面/unit 文件；这些是后续需明确授权的线上操作，本文没有自动执行回滚。
- 不要删除 `active.json`、回执日志或发布日志来强行解锁。已经应用新参数后，必须先对照实际容器和保留的 before/after 模型制定回滚。

本机详细证据位于仓库 `.debug/https-control-20260906/`：`noop-apply-receipt.json`、`final-live-receipt.json` 和桌面安装回执。相关运行文件可能包含敏感路径或配置，保持在 Git 之外。

持续维护说明见 `docs/runbooks/collection-runtime-settings.md`。
