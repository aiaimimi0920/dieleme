# 桌面认证凭据与可编辑设置修复

日期：2026-09-06。

## 当前结论

| 用户问题 | 本轮结果 |
| --- | --- |
| 本机缺少认证同步凭据 | 已定位并修复直接启动 EXE 时的数据目录丢失问题；已安装的认证组件能使用原凭据通过 NAS 授权检查。 |
| 采集运行配置无法编辑 | 已改为可编辑、可保存本机草稿，已构建并更新本机桌面。 |
| 保存后实际应用到线上 PC2 | **尚未完成上线。** 桌面提交与回执流程通过离线回归，但当前 NAS 设置接口仍返回 HTTP 404，PC2 设置控制器未启用。不会把本机保存标记为线上生效。 |

本轮没有部署、重启或重新配置 PC2/NAS，没有执行数据库写入、迁移、还原或数据清理。

## 1. 凭据报错的原因与修复

用户运行的是 `updates/20260906-manual-auth` 下直接启动的 EXE。之前只有 PowerShell
启动器设置数据目录、Cookie 路径和浏览器 profile；直接启动 EXE 不经过启动器，认证
helper 因而退回安装目录自己的 `FPFData/`，在那里找不到凭据。原来的凭据文件仍存在，
不是凭据被 NAS 作废，也不是数据库内容丢失。

修复包括：

- 安装目录新增 `crow-desktop.runtime.json`，只记录非敏感参数和文件路径，不包含 token、
  Cookie 或 AI 密钥内容。
- 每个 bundle 只读取自己的配置，明确环境变量仍优先，不扫描其他安装或父目录猜测凭据。
- 认证 helper 从持久配置读取数据目录、凭据路径、Cookie 路径、Chrome/profile 和 CDP 端口。
- Tauri 的默认 API 地址也读取同一 bundle 配置，避免自定义 API 地址只在 helper 生效。
- 安装脚本生成配置并备份旧配置；EXE-only 更新保留配置不动。
- 原有 API origin 校验、明确人工认证、目标页绑定和不可变快照交接继续保留。

### 实际验证

清空全部 `FAPAI_*` 启动环境变量后，修复前已安装 helper 的只读状态调用返回：

```text
phase=unavailable, code=token_unavailable
```

修复后，在正式安装、用户原来直接启动的旧 updates 目录、新候选目录分别运行同一套
已安装认证组件，三个目录均取得：

```text
authenticated=true
enabled=true
token_file_exists=true
```

这证明当前凭据发现与 NAS 授权边界已恢复。验证只查询状态，**没有代替用户完成真实
挑战、导出或发布 Cookie，也没有据此宣称 PC2 已恢复采集**。真实人工挑战后的 Cookie
可复用性和 PC2 恢复仍须实际操作确认。

## 2. 设置现在如何工作

1. 配置字段不再因未连接控制器、读取失败或等待应用而全部变灰。
2. **保存草稿**：校验后保存到本机，按 NAS API origin 隔离；重开程序可以恢复。
3. **保存并应用**：先保存草稿，再读取真实线上版本与控制器状态，确认后提交包含
   `expected_revision` 的请求；后续查询 PC2 回执，不把 HTTP 请求被接受当作生效成功。
4. 接口未启用或控制器离线时，明确显示 **草稿已保存，未应用**，保留编辑内容。
5. AI 密钥不写入草稿，空值表示保留线上密钥；变更控制授权会清空尚未提交的密钥。
6. 读取线上配置替换草稿前要求确认；线上版本或控制地址变化会拒绝覆盖。
7. 等待中和结果未知时禁止重复应用，但仍能编辑下一版草稿。
8. 提交响应丢失后自动查询状态，不自动重发 POST；连续五次状态查询失败后停自动查询，
   保留手动刷新入口。改 token 也不能解除仍在传输中的请求锁。
9. 异步读取本机 API 配置后，会恢复该 NAS 对应的草稿，不误用默认 NAS 的草稿。

默认值仍来自已有部署快照，不是测试 fixture；界面区分本地默认、草稿与线上生效配置。

### 为什么线上应用仍未完成

本轮重新查询 `http://192.168.15.200:8001/api/collection/settings`，返回 HTTP 404。
此外，[运行配置启用条件](../../runbooks/collection-runtime-settings.md) 中这些条件仍未闭合：

- 需要批准并验证安全控制入口。不能把控制授权和 AI 密钥改为经远程明文 HTTP 发送。
- PC2 实际配置与旧 Compose 解析结果有漂移，必须重新建立精确运行基线。
- 旧固定八 Worker 重启控制器需要与设置控制器共享互斥和动态实例清单。
- 已应用配置需要纳入后续部署/回滚流程，防止更新镜像后丢失设置。

本轮已询问是否允许增加 NAS HTTPS 控制入口，保持现有 HTTP 查询地址和 SSH 策略不变；
尚未据此更改任何线上策略。**不是只需输入一个控制 token 就已能上线应用。**
人工认证失败次数阈值也仍未接入，界面继续明确说明。

## 3. 已交付安装

版本标识：`20260906-runtime-settings-editable`。

正式入口：

```text
%LOCALAPPDATA%\FapaiFangCollectorDesktop\fapaifang_collector_desktop.exe
```

以下两个目录也同步为同一最终 EXE 和认证 bundle，避免继续点到旧路径复现凭据问题：

```text
%LOCALAPPDATA%\FapaiFangCollectorDesktop\updates\20260906-manual-auth
%LOCALAPPDATA%\FapaiFangCollectorDesktop\updates\20260906-runtime-settings-editable
```

最终 EXE SHA-256：

```text
1bcf75a99297f19bdf331c955944215775e570fe7f0dc101024f55a0abe5a9d0
```

每个目录的 14 个交付文件逐一做哈希校验。候选目录中的 `manifest.json` 记录最终文件清单。
原安装与原 updates 的旧文件备份保存在：

```text
%LOCALAPPDATA%\FapaiFangCollectorDesktop\backups\20260906-runtime-settings-editable
```

EXE 的最后一次细化更新另外保留了各目录的 `backup/exe-only-*` 备份；没有清理旧备份。
更新只正常关闭 Crow 桌面，没有强制终止 Chrome、认证浏览器或 PC2/NAS 进程。
最终通过 Explorer 直接启动正式 EXE，独立复核进程 PID 为 `22872`、`Responding=true`；
本轮创建的 Playwright 会话和本机离线预览服务已关闭，未停止用户的认证浏览器。

## 4. 验证记录

- Python：认证、运行配置、桌面静态契约等 **116 passed**。
- Node：有效代码行检查器、EXE-only 更新器、设置草稿和前端契约 **36 passed**。
- Rust：`cargo fmt --check` 通过；`cargo test --lib --quiet` **4 passed**。
- TypeScript：相关入口及依赖 `tsc --noEmit --strict` 通过。
- Vite 与 `tauri build --no-bundle` 构建通过，正式安装 EXE 与最终构建哈希一致。
- 实际 Chromium、离线 API/native fixtures：设置 30 项、提交竞态 7 项、启动草稿 1 项、
  人工认证 15 项、采集面板 22 项，共 **75 项检查通过**；请求不转发到生产系统。
- 设置截图检查：1120px 和 800px 下无横向页面溢出，编辑框和保存按钮可见。
- 有效代码行 ratchet 通过；遗留超大文件未被本轮修改。
- `git diff --check` 通过；修改文件保持 UTF-8 无 BOM；未提交或回退原有工作区变更。

以上浏览器测试不是线上 PC2 配置应用成功的证明。线上设置上线和真实人工认证恢复的
未完成边界已在前文明确列出。
