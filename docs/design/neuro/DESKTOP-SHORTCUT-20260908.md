# Crow 本机安装位置与桌面快捷方式

日期：2026-09-08，北京时间。已实际创建快捷方式并通过它启动验证。

## 安装位置

- 安装目录：[C:\Users\vmjcv\AppData\Local\FapaiFangCollectorDesktop](C:/Users/vmjcv/AppData/Local/FapaiFangCollectorDesktop)
- 主程序：[fapaifang_collector_desktop.exe](C:/Users/vmjcv/AppData/Local/FapaiFangCollectorDesktop/fapaifang_collector_desktop.exe)
- 桌面快捷方式：[C:\Users\vmjcv\Desktop\Crow.lnk](C:/Users/vmjcv/Desktop/Crow.lnk)

这是已经核对过的实际运行位置，不是仓库中的构建输出目录。当前快捷方式直接指向这个 EXE，工作目录是安装目录，图标使用该 EXE 的图标。

## 今后的默认行为

完整本地部署和仅更新 EXE 的脚本都已接入同一个快捷方式更新逻辑：

1. 成功更新并确认安装后的 EXE 哈希正确后，自动创建或刷新桌面 `Crow.lnk`。
2. 始终使用这一个名称，指向当前安装版本；不按版本号堆积旧快捷方式。
3. 快捷方式被删除或指向旧位置时，下一次成功更新会修复。
4. EXE 已是相同版本时，显式使用 `-Apply` 和正确的预期哈希，也会补回或刷新快捷方式，不会重复替换 EXE。
5. 检查模式不修改任何桌面文件，错误哈希不会覆盖现有快捷方式。
6. 不删除桌面其他文件。完整部署原有的显式 `-SkipShortcut` 仍可用于特殊用途，默认不跳过。

当前程序会读取安装目录内已有的运行配置，所以快捷方式不需要经过 PowerShell，也不会因旧启动器的环境变量覆盖当前配置。只有缺少运行配置文件的旧安装才沿用原启动器。

相关实现：

- [共用快捷方式更新脚本](C:/Users/Public/nas_home/crow/scripts/update-collector-desktop-shortcut.ps1)
- [仅更新 EXE](C:/Users/Public/nas_home/crow/scripts/update-collector-desktop-exe-only.ps1)
- [完整本地部署](C:/Users/Public/nas_home/crow/scripts/deploy-collector-desktop-local.ps1)
- [本地更新约定](C:/Users/Public/nas_home/crow/AGENTS.md)

## 本次验证

- 快捷方式和 EXE 更新回归：**12 项通过**，使用临时目录和合成文件，不运行合成 EXE。
- 桌面与认证 bundle 回归：**34 项通过**。
- 有效代码行检查器：**19 项通过**；ratchet 扫描 944 文件，通过，未修改基线。
- PowerShell 语法解析、相关差异检查、UTF-8 无 BOM 检查通过。
- 独立只读复核未发现本次范围内的明确安全或正确性回归。
- 真实桌面的 `Crow.lnk` 已创建，并核对目标、工作目录、图标和无额外参数。
- **06:12:59 已通过这个快捷方式重启 Crow**：旧 PID 22456，新 PID **29356**，进程响应正常，窗口句柄有效。
- 当前安装版本为 `20260908-manual-auth`，31 个安装文件哈希通过。本次修改的是更新脚本，不涉及桌面 EXE 或前端载荷，因此没有不必要地重新构建或替换已验证的程序。
- 运行配置保持不变，认证浏览器保留，没有重启电脑，没有操作 PC2/NAS 服务或数据库。

证据：[本机快捷方式与启动验证回执](C:/Users/Public/nas_home/crow/.debug/crow-desktop-shortcut-20260908/activation-receipt.json)。
