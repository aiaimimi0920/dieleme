# FapaiFang 运维观察台桌面版

这是一个 **Rust + Tauri** 独立桌面应用，用来观察和少量修正当前采集模块的实际数据。
它不在 PC1 运行 seed/detail/analysis worker；PC1 只承担人工认证，采集和分析 worker 均部署在 PC2。

它不复制采集逻辑，不包含房价分析引擎。默认浏览、翻页、查看详情都是读取现有采集 API；只有用户显式点击 **暂停/开始**、**认证**、**AI 再分析** 或 **手动更新** 时，才会通过 API 改变运行状态、提交认证任务、写入数据库或重新加入 AI 分析队列。

## 依赖

- Rust / Cargo
- Node.js / npm
- 正在运行的 `fapaifang-api`
  - 默认地址：`http://127.0.0.1:8001`
  - 如需覆盖，设置环境变量：`FAPAI_COLLECTOR_API_BASE`

## 开发运行

```powershell
cd collector-desktop
npm install
npm run tauri:dev
```

如果当前仓库路径是 UNC 路径，例如 `\\192.168.15.200\...`，Windows `cmd.exe` 不能直接把 UNC 当当前目录。此时使用：

```powershell
cmd /c "pushd \\192.168.15.200\home\project\project\fapaifang\collector-desktop && npm run tauri:dev && popd"
```

## 打包

```powershell
cd collector-desktop
npm install
npm run tauri:build
```

UNC 路径下对应使用：

```powershell
$env:CARGO_TARGET_DIR = Join-Path $env:TEMP 'fapaifang-collector-desktop-target'
cmd /c "pushd \\192.168.15.200\home\project\project\fapaifang\collector-desktop && npm run tauri:build && popd"
```

说明：`CARGO_TARGET_DIR` 指向本机临时目录，是为了避免 Windows 在 UNC/NAS 路径下写 Cargo `target` 目录时出现权限或文件锁问题。

成功后 Windows 安装包位于：

```text
%TEMP%\fapaifang-collector-desktop-target\release\bundle\msi\
%TEMP%\fapaifang-collector-desktop-target\release\bundle\nsis\
```

## 本机稳定部署

不要直接从仓库的 UNC/NAS 路径运行 `fapaifang_collector_desktop.exe`。Windows 在网络路径下运行 Tauri 可执行文件时，容易触发 `0xc0000006` 一类的访问异常。

统一使用仓库根目录脚本部署到本机：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\deploy-collector-desktop-local.ps1
```

该脚本会：

- 在 `%TEMP%\fapaifang-collector-desktop-target` 下执行 `npm run tauri:build`
- 把可执行文件复制到 `%LOCALAPPDATA%\FapaiFangCollectorDesktop`
- 同步本地 runtime 所需脚本：
  - `open-remote-auth-browser.ps1`
  - `start-pc1-manual-auth-session.ps1`
  - `start-pc1-auth-bridge.ps1`
  - `start-pc1-analysis-proxy-bridge.ps1`
  - `register-pc1-analysis-proxy-bridge-task.ps1`
  - `start-taobao-cdp-browser.ps1`
  - `export-taobao-cookie-snapshot.ps1`
- 同步 cookie 导出依赖的 Python helper：
  - `browserless_seed_probe.py`
  - `taobao_login_health.py`
  - `internal_api_http.py`
- 生成本地启动器：
  - `%LOCALAPPDATA%\FapaiFangCollectorDesktop\start-fapaifang-collector.ps1`
- 更新桌面快捷方式：
  - `FapaiFang 运维观察台.lnk`

这样桌面应用在打开认证窗口、导出 cookie 快照时，会优先使用 `%LOCALAPPDATA%\FapaiFangCollectorDesktop` 下的本地脚本与 helper，而不是再次回退到仓库 UNC 路径。

### PC1 人工认证、PC2 继续采集

本机部署默认使用 `local-bridge` 认证模式：

1. 点击 **认证** 后，桌面端先等待中央 API 进入暂停状态，再在 PC1 的专用 CDP
   Chrome `127.0.0.1:9225` 中打开实际受阻的详情页。
2. 人工认证必须在同一浏览器进程、同一详情页完成；成功显示详情后不要关闭、刷新或
   重新导航页面。
3. 点击 **认证完成** 后，桌面端原地读取当前详情 DOM，并从同一进程导出 Cookie；
   不会关闭或重启 Chrome。
4. `start-pc1-auth-bridge.ps1` 建立 SSH reverse tunnel，把 PC2 的
   `127.0.0.1:9225` 转发到 PC1 的 `127.0.0.1:9225`。
5. PC2 的 `192.168.15.104:9224` 仅是健康检查入口；它通过 Windows
   `portproxy` 指向 PC2 回环的 `9225`。CDP 不直接暴露 PC1 的监听端口。
6. 桌面应用同时验证列表和本次详情的 Cookie HTTP 请求；两者通过后才发布正式
   snapshot 并通知中央 API 清除暂停。失败不会覆盖正式 snapshot，也不会恢复 PC2 采集。

当 PC2 无法直连分析提供商时，`start-pc1-analysis-proxy-bridge.ps1` 会动态发现
PC1 当前 Windows 代理，把 PC2 的 `127.0.0.1:42345` 反向转发到 PC1 的 IPv6
回环代理。PC2 的 `OPENAI_PROXY` 只指向这个回环端口；需要开机自启时，使用
`register-pc1-analysis-proxy-bridge-task.ps1`，该操作需要一次管理员权限确认。

人工拖动期间，PC2 不应同时控制同一个标签页。使用共享的 PC1 人工浏览器时，
PC2 host-direct worker 应配置：

```text
FAPAI_CAPTCHA_SOLVER_ENABLED=0
FAPAI_LIST_BROWSER_FALLBACK=0
FAPAI_DETAIL_BROWSER_FALLBACK=0
FAPAI_DETAIL_LOAD_OPEN_BROWSER_PAGES=0
FAPAI_COOKIE_SNAPSHOT_PREFER=1
FAPAI_CDP_EXTERNAL=1
```

中央暂停期间 seed/detail worker 不运行，analysis worker 可以继续处理已有原始详情；
因此不会在人工拖动时合成鼠标事件、刷新或导航 PC1 页面。需要恢复浏览器 fallback 时，必须先确认人工
认证和 cookie 导出已完成，再把相应 fallback 改回 `1` 并重启 worker；不要在人工
滑块仍显示时恢复。

## 展示范围

- 运行状态：显示 **暂停中 / 运行中 / 待认证 / 已完成**，并提供 **暂停/开始** 与 **认证** 按钮。
  - 点击 **开始** 时会强制清除暂停、待认证、`force_unlock.flag` 等人工认证阻塞标记，然后让采集重新尝试一轮；这用于覆盖“用户已经在其他窗口完成认证”的情况。
  - **待认证** 只代表确实需要人工介入（`manual_required` 或 `force_unlock.flag`），不会因为后台 solver 正在运行就误报。
  - **认证** 按钮先暂停采集，再打开 PC1 上的外部 Taobao CDP 浏览器窗口并维持到 PC2 的反向隧道；不在桌面应用内嵌淘宝页面，避免官方页面阻止 iframe 嵌入导致卡顿或空白。
- 商品链接采集：总链接数、唯一商品数、逐条商品链接和列表来源。
- 商品详情页采集：已采集详情页、待抓、失败、阻塞，以及详情 HTML/文本文件。
- 商品详情页 AI 分析：已标准化商品列表，点击商品查看数据库标准化字段表、AI 分析次数，并支持：
  - **AI 再分析**：把该商品重新加入详情页 AI 分析队列，由现有 worker 重新分析并更新结果。
  - **手动编辑 / 取消编辑 / 手动更新**：把标准化字段切换为可编辑状态；手动更新会将编辑后的字段写入数据库，取消编辑会丢弃本次未提交修改并恢复数据库当前值。

该应用是 operator 观察台，不会删除任何采集任务或采集数据；写操作仅限上述明确按钮。
