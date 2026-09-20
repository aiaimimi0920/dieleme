# 认证快照等待与 PC2 接收状态修复

日期：2026-09-08，北京时间。

## 结论与应用状态

**这次认证快照实际已经到达 PC2，且 NAS 已确认该恢复任务成功。** 原界面把等待领取、导入、浏览器重启等多个阶段合并显示，又在每次轮询开始时覆盖文案，因此看起来像反复提交或始终未被接收。

界面与本机状态解释代码已修复，测试和新版桌面 EXE 构建均已完成。**用户授权后，已安装并启动 `20260908-auth-receipts`，安装清单状态为 `activated`。** 激活时没有旧 Crow 进程，因此本次实际执行的是备份、替换和启动新版，而非关闭一个仍在运行的旧窗口。

后续每次完成并验证 Crow 修改后，自动更新并重启本机 Crow 的约定已写入 [项目规则](C:/Users/Public/nas_home/crow/AGENTS.md)。仅重启 Crow 程序，不重启电脑，也不扩大到 PC2/NAS 或人工认证浏览器。

本轮未部署、重启或修改 PC2/NAS 服务，没有提交认证任务、重新发布 Cookie、解除挑战或改动数据库。排查期间 PC2 的浏览器重启属于原有认证恢复流程的自动动作，不是本轮工具执行的重启动作。

## 实际链路证据

核验的同一任务：

`auth-recovery-aa4442ac06534d09a36498a4ae8d31ba`

| 时间/位置 | 证据 |
| --- | --- |
| PC1 共享快照 | 文件存在，44890 字节；SHA-256 与 NAS 登记的一致。未输出 Cookie 内容。 |
| PC2 02:05:16 | `nas_auth_recovery / restart_requested`，同一任务，已导入 118 条 Cookie。 |
| PC2 02:08 左右 | 原认证浏览器重启过程中出现 CDP `WebSocketTimeoutException`，随后进程由既有运行机制恢复。 |
| PC2 02:09:05 | `nas_auth_recovery / recovery_confirmed`，同一任务，118 条 Cookie。 |
| NAS 02:17:49 左右 | `last_result.status=succeeded`，原因 `captured_count_advanced`；基线 107957，完成时 107965。 |
| 后续只读查询 | 详情采集计数继续达到 107975；新版 bundle 对同一任务返回 `phase=succeeded / code=recovery_finished`。 |

PC2 本地快照、PC1 文件和 NAS 登记的 SHA-256 相同：

`e15799cc3a2fda9d12438b3aa2bbbb91e5cdde5967da877cead3d4d8a81f0042`

这排除了“快照只在 PC1、PC2 从未拿到”的解释。PC2 消费者实际已启用，运行在 `tools/pc2_local_solver.py` 进程内部，并非缺少一个独立服务。

需要区分：**接收 Cookie 不等于立即恢复采集。** 当前协议在导入、重启并向 NAS 确认后，还需要观察详情采集数量增长，才显示完成；本次总等待确实较长。核验时链接阶段仍显示挑战状态，不能把某次认证任务完成等同于所有采集阶段永久不再遇到挑战。

## 修复内容

### 1. 阶段显示准确

[本机恢复状态解释](C:/Users/Public/nas_home/crow/tools/pc1_desktop_recovery.py) 与 [桌面状态文案](C:/Users/Public/nas_home/crow/collector-desktop/src/desktop_auth_contract.ts) 现在区分：

- `snapshot_ready`：认证快照已提交，等待 PC2 领取。
- `pc2_claimed`：PC2 已领取认证快照，正在导入会话。
- `restarting`：PC2 已导入认证会话，正在重启认证浏览器。
- `verifying`：PC2 已接收会话，正在确认采集恢复。
- NAS 最终失败：分别提示领取、导入、重启或采集验证超时；不回显未知原始错误。

仅匹配任务的 NAS 成功结果会判定完成。没有把导入完成、浏览器重启或等待超时冒充采集恢复成功。

### 2. 不再轮询闪烁

[桌面认证交互](C:/Users/Public/nas_home/crow/collector-desktop/src/desktop_auth.js) 在后台查询时保留最近一次已确认阶段，不再每隔几秒改成“正在确认 PC2 接收结果”，然后又改回“认证快照已提交”。

### 3. 自动查询有上限，手动查询仍可用

- 连续等待达到 15 分钟，停止自动轮询并给出明确提示。
- 保持任务身份和“已完成挑战”按钮可用；点击后只查询原任务，不重新导出或发布 Cookie。
- 不因本机停止轮询就宣称 NAS 任务失败，也不把它标记成功。
- 等待期间关闭再打开弹窗，会继续查询同一任务；不会仅因关闭弹窗就重开认证任务。

## 验证

| 检查 | 结果 |
| --- | --- |
| Python 认证、bundle、运行配置及桌面相关测试 | 87 passed |
| TypeScript/Node 前端测试 | 21 passed |
| 严格 TypeScript 检查 | 通过 |
| Chromium 真实界面、模拟 native bridge | 21 项检查通过，0 个页面异常 |
| 轮询行为 | 挂起一次状态请求时文案不被覆盖；模拟超过 15 分钟后自动查询停止；手动查询不重新提交；仅成功结果关闭弹窗 |
| Vite 与 Tauri release EXE 构建 | 通过 |
| 有效代码行检查器测试 | 19 passed |
| 有效代码行 ratchet | 通过，941 个文件；未修改基线 |
| Git diff 检查 | 通过；保留既有脏工作区改动 |
| 新 bundle | 31 个文件复制与哈希核验通过 |
| 新 bundle 的实际只读 NAS 查询 | 同一任务返回 `succeeded`，子进程退出 0，stderr 为空 |
| 本机新版激活 | 安装清单 `activated`；31 个安装文件哈希匹配；仅替换 EXE 和恢复状态解释模块 |
| 新版进程 | PID 28356，03:20:55 启动；路径为当前安装根目录的 EXE；窗口已建立且响应正常 |
| 数据与认证环境保留 | 运行配置哈希未变，4 个原有认证浏览器相关进程仍在；未操作数据库 |

浏览器测试使用回环地址及测试数据，不打开真实挑战页面、不发送 Cookie、不操作线上采集。测试浏览器与预览服务已关闭。

## 当前运行版本与备份

当前运行程序：

[fapaifang_collector_desktop.exe](C:/Users/vmjcv/AppData/Local/FapaiFangCollectorDesktop/fapaifang_collector_desktop.exe)

激活核验时间为北京时间 2026-09-08 03:20:55，PID 为 28356，窗口标题为 `FapaiFang 运维观察台（PC2 采集）`。进程路径与安装清单一致，安装 EXE 哈希与下方已验证候选一致。

完整候选目录：

[20260908-auth-receipts](C:/Users/vmjcv/AppData/Local/FapaiFangCollectorDesktop/updates/20260908-auth-receipts)

候选 EXE：

[fapaifang_collector_desktop.exe](C:/Users/vmjcv/AppData/Local/FapaiFangCollectorDesktop/updates/20260908-auth-receipts/fapaifang_collector_desktop.exe)

EXE SHA-256：

`2ca5b72d863cc10ab20535b295f883f6034df186027c3076525bdd88ac10ac40`

[准备回执](C:/Users/Public/nas_home/crow/.debug/auth-receipts-20260908/candidate-receipt.json) 保留准备阶段的历史状态 `prepared-not-activated`；当前激活结果以 [激活回执](C:/Users/Public/nas_home/crow/.debug/auth-receipts-20260908/activation-receipt.json) 和现安装清单为准。仅替换最新 EXE 和 `tools/pc1_desktop_recovery.py`；其余 29 个文件未改动，现有认证凭据及浏览器配置仍通过原路径使用。

旧的两个程序文件及安装清单已保存到 [本次备份](C:/Users/vmjcv/AppData/Local/FapaiFangCollectorDesktop/backups/20260907-192055-auth-receipts)。没有重启电脑、认证 Chrome、PC2 或 NAS，也没有改动数据库。

现在可以在已启动的新版 Crow 中手动测试认证交互。本次激活仅证明新版程序已运行；未代替用户执行新的人工挑战，也不宣称所有采集阶段已经解除挑战。
