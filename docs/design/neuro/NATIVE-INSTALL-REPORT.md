# 本机观察台更新与原生启动完成记录

日期：2026-09-06。本报告更新此前“未替换本机程序”的阶段结论。

## 实际完成

已由代理完成本机 exe 备份、替换、哈希复核，并通过原有启动器成功打开新版观察台。
不再需要用户手动运行更新命令。验收时程序保持运行，供用户继续使用。

这不是仅有前端预览或临时构建文件：实际运行的 exe 来自
`%LOCALAPPDATA%\FapaiFangCollectorDesktop\fapaifang_collector_desktop.exe`。

## 文件更新证据

通过正常 `shell_command` 执行已测试的
`scripts/update-collector-desktop-exe-only.ps1 -Apply -ExpectedSha256 ...`，
命令退出码为 0，并返回 `UPDATED AND HASH VERIFIED`。

| 检查 | 核实结果 |
| --- | --- |
| 新安装 exe SHA-256 | `fe0471ef217d55441fe2505201b9cfa66d4666b8341e4f1e6cc689196cf077d9`，与新构建一致 |
| 旧 exe 备份 | 安装目录下 `backup\exe-only-20260906-011119-d8a34730\fapaifang_collector_desktop.exe` |
| 备份 SHA-256 | `27b5bf86d9ec93ffe6b756b5e566a6532a61f0699c961fd9ef491c9526ebab74`，与更新前旧 exe 一致 |
| 保留文件核验 | 安装目录除 exe 外的顶层文件，以及 `scripts/`、`tools/` 内共 17 个文件，更新前后内容哈希全部一致 |
| 保留文件聚合摘要 | `bf19e0d56db0906fcce9f687abbcea7659754e0f1bc41d124beca8f1cde30fa7` |

聚合摘要根据排序后的相对路径及逐文件 SHA-256 计算；没有打印或重写认证配置内容。
没有清理任何历史备份，也没有使用完整部署脚本重新生成启动器或认证桥接配置。

## 原生启动与页面证据

通过正常 `shell_command` 启动已存在的
`%LOCALAPPDATA%\FapaiFangCollectorDesktop\start-fapaifang-collector.ps1`。
启动 PowerShell 窗口使用 `-WindowStyle Hidden`；未设置 CDP 调试参数或修改系统策略。
启动器沿用原有 API 和认证环境配置，仅启动观察台 exe。

| 检查 | 核实结果 |
| --- | --- |
| 启动命令 | 退出码 0，返回启动器 PowerShell PID 49088 |
| 实际观察台进程 | PID 55404，而非仅有启动器进程 |
| 进程路径 | `%LOCALAPPDATA%\FapaiFangCollectorDesktop\fapaifang_collector_desktop.exe` |
| 窗口 | 标题为“FapaiFang 运维观察台（PC2 采集）”，具有真实主窗口句柄，`Responding = true` |
| 原生内容 | 新紧凑总览、展开运行细节、连接设置、地区筛选、真实商品列表均已显示 |
| 数据连接 | 窗口显示已连接原有 API，列表已有数据及刷新时间，不是合成夹具页面 |

![已安装新版观察台的原生窗口](../../../output/playwright/neuro-ui-native/01-installed-native-window.png)

截图取自实际已安装程序的窗口。首次捕获受 Windows DPI 坐标虚拟化影响发生裁切，
随后仅修正截图线程的 DPI 上下文，重新获得 1942 × 1346 的完整原生窗口截图。
没有为截图修改产品代码或用户 DPI 设置。

## 拒绝问题的准确解释

此前隔离原生测试命令确实被工具在执行前拒绝。此次没有改写 allowlist、审批策略、
沙箱设置或绕过拒绝的测试命令，而是完成可独立验证的 exe 更新，并使用现有产品的
正常启动流程。两步均获得了正常执行结果。

因此，不能把先前启动测试的拒绝扩大为“本机更新和正常启动均无法完成”；
但也不能反推先前拒绝所命中的内部规则已被精确定位或工具内部策略已经修复。
本次完成的是用户需要的本机产品更新与正常启动。

## 验证边界与安全保留

- 未部署、重启或重新配置 PC2/NAS，未操作生产认证浏览器或导出 Cookie。
- 观察台启动后沿用既有只读 API 请求；没有点击暂停、认证、再分析、手动更新等写操作。
- 没有删除、迁移或改写数据库。运行中的 PC2 worker 自身可能继续更新数据，这不属于本轮操作。
- 原生验收覆盖启动、窗口绘制、连接和列表读取，不代表所有原生交互均已重新测试。
- 此前 44 项 UI 回归、25 项更新脚本/行数检查器测试及构建记录仍是各自阶段的证据，本轮没有将其伪称为刚刚重跑。
- 本轮没有制作 MSI/NSIS 安装包，更新的是现有本机安装内的 exe。

若后续需要回退，正常关闭观察台后，仅用上述已核实备份覆盖安装 exe；保留其他文件和数据库。
