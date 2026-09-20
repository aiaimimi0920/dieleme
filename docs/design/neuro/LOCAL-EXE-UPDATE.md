# 由用户在本机更新并启动观察台

日期：2026-09-06。

2026-09-08 更新：成功安装后会自动刷新桌面 `Crow.lnk`；本页原构建哈希和 UI 验证记录属于历史版本，未来更新应使用当次已验证构建的哈希，不应直接复用旧哈希。

**当前本机更新已由代理执行，程序已成功启动，见 [完成记录](NATIVE-INSTALL-REPORT.md)。**
以下步骤保留供以后自行更新或回退，本次不需要用户再运行。

## 最短操作路径

不需要重新部署 PC2/NAS，不需要改 Codex 配置，也不需要关闭 Windows 安全机制。
这里由你在本机主动执行文件更新，然后使用自动生成的 `Crow.lnk` 打开程序。
这是本机操作说明，不表示 Codex 的原生启动工具拒绝已经修复。

### 1. 打开 PowerShell 并检查

用资源管理器打开本仓库的 `scripts` 文件夹，在地址栏输入 `powershell` 并回车。
无需以管理员身份运行。在出现的窗口粘贴：

```powershell
$expected = 'fe0471ef217d55441fe2505201b9cfa66d4666b8341e4f1e6cc689196cf077d9'
.\update-collector-desktop-exe-only.ps1 -ExpectedSha256 $expected
```

看到 `CHECK ONLY. No files changed.` 表示检查成功，尚未更新。
脚本会显示源文件、已安装文件以及双方 SHA-256。当前已确认：

- 新 exe：`%TEMP%\crow-observer-neuro-ui-target\release\fapaifang_collector_desktop.exe`。
- 本机安装：`%LOCALAPPDATA%\FapaiFangCollectorDesktop\fapaifang_collector_desktop.exe`。
- 这两个文件当前分别为 8,618,496 和 8,654,848 字节。

### 2. 关闭观察台并更新

先通过窗口关闭按钮正常退出观察台，完成或放弃未保存的编辑。
在上一步同一个 PowerShell 窗口粘贴：

```powershell
.\update-collector-desktop-exe-only.ps1 -Apply -ExpectedSha256 $expected
```

成功时必须出现：

```text
Verified backup: ...
UPDATED AND HASH VERIFIED. Desktop shortcut refreshed: ...\Crow.lnk
```

脚本先备份旧 exe 并验证备份，再暂存和校验新 exe，最后进行同卷原子替换与安装后
哈希校验。备份位于安装目录的 `backup\exe-only-日期时间-唯一标识\`，完整路径会打印。
不会清理旧备份，不会删除数据库，不会修改启动脚本、认证辅助脚本或浏览器配置。
成功校验安装文件后，只创建或替换桌面上的 `Crow.lnk`，并核验目标、工作目录和图标；不会删除其他桌面文件。
若 EXE 已是相同版本，使用 `-Apply` 和正确的预期哈希仍会修复快捷方式，不会重复备份或替换 EXE。
如果仍检测到观察台进程，脚本会拒绝更新，要求你先关闭；不会强杀进程。

### 3. 双击桌面的 Crow 快捷方式

使用桌面的 `Crow.lnk`。当前安装直接运行本地 EXE，并沿用安装目录内既有的 API 地址和认证配置；只有尚无运行配置文件的旧安装才通过原启动器运行。
不要用完整部署脚本替代这次 exe-only 更新，也不要重新安装 PC2/NAS 服务。

打开后检查：

1. 默认是紧凑运行总览，有“展开运行细节”入口。
2. API 连接设置、地区筛选可展开，连接状态和当前地区摘要直接可见。
3. 原有列表和详情可正常读取，窗口没有空白或异常退出。

先只浏览页面，不必点击认证、暂停/开始、AI 再分析或手动更新来证明 UI 已升级；
这些按钮仍是生产写操作。数据连接失败和窗口启动失败是不同问题，请分别保留错误截图。

## 如果脚本不能执行

- `Close the observer normally`：正常关闭仍在运行的观察台后重试，不要强杀其他进程。
- `Source SHA-256 does not match`：停止更新，说明源文件与这份交付不是同一构建；不要去掉哈希校验强行安装。
- `Build executable missing`：临时构建目录可能已被清理，需要重新构建并重新确认哈希。
- PowerShell 提示脚本执行策略限制：不要关闭安全机制。可以用资源管理器完成同样的文件操作：先关闭观察台，在安装目录新建一个唯一命名的备份文件夹，复制旧 exe 到该备份文件夹，然后把新 exe 复制到安装目录并确认仅替换这个同名文件。不要剪切或删除安装目录，也不要触碰任何数据库、配置文件或辅助脚本。复制后仍应核对安装文件的 SHA-256 是否等于本页给出的新版本哈希。

需要单独核对安装文件时，在 PowerShell 运行：

```powershell
Get-FileHash -LiteralPath (Join-Path $env:LOCALAPPDATA 'FapaiFangCollectorDesktop\fapaifang_collector_desktop.exe') -Algorithm SHA256
```

## 如何退回旧版本

如果新 exe 无法正常打开，先关闭其窗口，在资源管理器中从脚本打印的备份目录
把旧 `fapaifang_collector_desktop.exe` 复制回安装目录，确认仅覆盖 exe，再用原快捷方式启动。
不要删除整个安装目录，也不要改数据库。保留失败截图或错误文字，以便后续定位。

## 已验证与未验证

以下是 2026-09-06 的历史验证记录，不能作为后续版本的构建或安装证明。

- 更新脚本 [update-collector-desktop-exe-only.ps1](../../../scripts/update-collector-desktop-exe-only.ps1) 已对真实本机路径执行检查模式，确认源文件哈希匹配，未修改安装。
- [6 项安全回归测试](../../../scripts/tests/update-collector-desktop-exe-only.test.mjs) 全部通过：检查模式不写文件、备份与替换、保留数据/启动脚本、重复执行、错误哈希与缺失安装等；测试只使用临时合成文件，不运行 exe。
- 有效代码行数检查器 19 项测试通过；首次测试发现的 PowerShell 5.1 空字符串参数兼容问题已修复并复测。
- 全仓有效代码行数 ratchet 扫描 866 文件，0 违规；既有未修改的超大文件债务仍保留，未更新基线。
- 新 UI 已通过前端浏览器回归和 Windows release 编译；由你执行更新和启动之前，不能将其称为已安装或原生运行验收通过。
