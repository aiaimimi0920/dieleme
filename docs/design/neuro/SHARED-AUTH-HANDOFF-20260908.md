# 一次人工认证，共享链接与详情 Cookie

本机 Crow 已于 2026-09-08 20:48:12（北京时间）更新并重启，版本标记为 `20260908-shared-auth`。

现在可以从链接或详情任一认证入口打开页面，完成人工认证后点击一次“已完成挑战”。Crow 导出一次 Cookie，自动依次提交到 PC2 的链接与详情认证恢复流程，不需要为了交接另一阶段再人工认证或再次点击完成。

## 报错原因与处理

旧流程把两个阶段作为独立任务提交给 NAS 的单任务协调器。已有另一个阶段的任务时，NAS 返回 HTTP 423；桌面映射为“另一认证交接正在进行，请稍后重试”。同一错误码也用于本机认证锁竞争。

离线测试复现了一个阶段已领取但尚未发布 Cookie，另一个阶段提交时无法推进的场景。新流程遇到相同挑战的未发布人工任务时，保留原恢复 ID、阶段和目标，重新让 NAS 校验挑战身份，然后用本次认证的快照续接。已有快照正在传输时，保留该快照并自动排队，等待结束后继续，不再要求用户反复点击。

本轮只读查询 NAS 时，`stage_auth_protocol=2`、`pc2_stage_auth_ready=true`，且没有活动恢复任务。因此无法把用户之前那次报错进一步确定为某个具体历史任务或本机锁竞争；上述冲突路径来自真实代码和离线复现。

## 实现约束

- 一次捕获生成一个不可变 Cookie 快照。两个阶段发布的文件内容和 SHA-256 完全相同，各有独立恢复 ID、目标 URL、挑战 ID、PC2 回执。
- 正常顺序为链接后详情；存在可续接的旧人工任务时先完成旧任务，再处理另一阶段。
- 不重启 PC2 浏览器，不覆盖正在传输的文件。链接仍要求列表数据探测，详情仍要求导入后的详情捕获进展。
- 一个阶段验证失败后仍使用同一 Cookie 处理另一个阶段，界面分别显示结果，不把部分成功当成全部成功。
- 交接 ACK 丢失或暂时网络故障会复用本地任务和原快照重试，不重新导出 Cookie。
- 关闭弹窗后继续推进共享任务。重开 Crow 后，点击任一认证入口可恢复已保存的共享任务查询。
- 自动轮询仍有 15 分钟上限；超时后可以点击完成按钮继续查询。超过 30 分钟尚未提交的阶段不再使用旧快照，会明确要求重新提交当前浏览器会话。
- 新挑战身份不匹配时，不把旧请求当作当前挑战完成。缺少详情验证目标时，会提示先选择商品；不会用链接页面代替详情验证。

主要实现：`tools/pc1_shared_auth.py`。它复用现有 v2 NAS / PC2 协议，本轮没有修改、部署或重启 NAS / PC2 服务，也没有主动向线上提交 Cookie。

## 验证

- Python 聚焦回归：68 项通过，覆盖一次捕获、两份内容一致的发布、两阶段回执、旧任务续接、传输排队、ACK 丢失、单阶段失败、过期和 API 来源约束，以及既有认证/安装包测试。
- Node 契约与有效代码行规则：27 项通过。
- Rust `auth_bridge::tests`：2 项通过；`cargo fmt --check` 通过。
- TypeScript 认证契约与阶段模块类型检查通过。
- `npm run tauri:build` 成功，生成 EXE、MSI、NSIS 包。
- 实际浏览器离线夹具：8 项检查通过，无页面异常；验证跨阶段入口复用、关闭弹窗继续轮询、重载后续接和部分成功展示。
- `node scripts/effective-code-lines.mjs --mode ratchet --json artifacts/effective-code-lines.json` 通过；已有超过 1500 行的基线文件没有在本轮改动。
- `git diff --check` 通过；本轮 9 个源文件/测试文件均验证为 UTF-8 无 BOM；已有工作区修改保留。
- 安装目录中的新 Python 模块在隔离解释器中导入成功；实际安装的 PowerShell 启动器离线调用退出码为 0，并按预期返回 `invalid_api`，未访问线上接口。

浏览器夹具：`tools/test/collector_shared_auth_ui_smoke.mjs`。截图：`output/playwright/shared-auth-partial.png`。

## 本机激活证据

- 运行文件：`%LOCALAPPDATA%\FapaiFangCollectorDesktop\fapaifang_collector_desktop.exe`。
- 新 Crow PID：`14572`；启动后已核验真实进程路径。
- EXE SHA-256：`4bdcaa0cd4c3b891805af1851e72011cd2ba688117aa3be2dca47f5585db7506`。
- 安装清单 32 个文件全部通过 SHA-256 检查。
- 本轮替换 EXE、认证 PowerShell 启动器、PC1 认证入口模块，并新增共享任务模块；替换前已备份旧文件。
- 备份：`%LOCALAPPDATA%\FapaiFangCollectorDesktop\backups\20260908-204802-shared-auth`。
- 运行配置哈希保持不变，9 个既有人工认证浏览器根进程仍在；未触碰凭据、数据库或现有 Cookie。
- `Crow.lnk` 已由 `scripts/update-collector-desktop-shortcut.ps1` 更新，目标、工作目录、图标和 EXE 哈希均已核验。
- 激活回执：`.debug/shared-auth-20260908/activation-receipt.json`。

本轮证明了本地修复、离线双阶段交接与实际桌面安装。真实站点的一次人工认证是否同时恢复两个采集阶段，仍由下一次提交后 PC2 的分别验证结果确认。
