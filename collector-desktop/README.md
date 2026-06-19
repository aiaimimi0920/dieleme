# FapaiFang 采集观察台桌面版

这是一个 **Rust + Tauri** 独立桌面应用，用来观察和少量修正当前采集模块的实际数据。

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

## 展示范围

- 运行状态：显示 **暂停中 / 运行中 / 待认证 / 已完成**，并提供 **暂停/开始** 与 **认证** 按钮。
  - 点击 **开始** 时会强制清除暂停、待认证、`force_unlock.flag` 等人工认证阻塞标记，然后让采集重新尝试一轮；这用于覆盖“用户已经在其他窗口完成认证”的情况。
  - **待认证** 只代表确实需要人工介入（`manual_required` 或 `force_unlock.flag`），不会因为后台 solver 正在运行就误报。
  - **认证** 按钮只打开/刷新外部 Taobao CDP 浏览器窗口，不在桌面应用内嵌淘宝页面，避免官方页面阻止 iframe 嵌入导致卡顿或空白。
- 商品链接采集：总链接数、唯一商品数、逐条商品链接和列表来源。
- 商品详情页采集：已采集详情页、待抓、失败、阻塞，以及详情 HTML/文本文件。
- 商品详情页 AI 分析：已标准化商品列表，点击商品查看数据库标准化字段表、AI 分析次数，并支持：
  - **AI 再分析**：把该商品重新加入详情页 AI 分析队列，由现有 worker 重新分析并更新结果。
  - **手动编辑 / 取消编辑 / 手动更新**：把标准化字段切换为可编辑状态；手动更新会将编辑后的字段写入数据库，取消编辑会丢弃本次未提交修改并恢复数据库当前值。

该应用是 operator 观察台，不会删除任何采集任务或采集数据；写操作仅限上述明确按钮。
