# 本机认证助手启动失败修复

日期：2026-09-08（北京时间）

## 结论

已修复并应用到当前正在运行的本机 Crow 桌面安装目录。无需重启桌面程序；下一次点击认证按钮会加载新脚本。

本次修复的是认证助手的**本机启动与依赖打包**，不是模拟认证成功。真实的人工作业、Cookie 交接及 PC2 恢复采集仍需由用户完成挑战后确认。本次没有提交线上认证任务，没有操作 PC2、NAS 或数据库。

## 原因与复现证据

用户看到的“本机认证助手执行失败，请检查 Python 和运行文件”，来自 Rust 将 PowerShell 子进程的所有非零退出统一映射为同一提示。它不代表 Python 必然未安装。

发现并复现了两个问题：

1. **安装包漏掉拆分后的 Python 依赖。**
   - 已安装的 `browserless_seed_probe.py`、`taobao_login_health.py` 是动态加载实现模块的入口。
   - 原打包清单只复制入口，没有复制其必需的 6 + 7 个实现模块。
   - 从独立安装目录运行真实助手，实际报错为：

     ```text
     ModuleNotFoundError: No module named 'tools.browserless_seed_probe_context'
     ```

   - 调用链：`pc1_desktop_auth` → `taobao_inplace_auth_handoff` → `browserless_seed_probe` → 缺失模块。
   - 从仓库目录运行时，Python 的模块搜索会优先命中仓库文件，掩盖安装包不完整。这也解释了表现可能随启动方式、工作目录而不同。

2. **启动脚本忽略已保存的解释器路径。**
   - 本机 `crow-desktop.runtime.json` 已配置存在且可运行的 Python 3.10.11。
   - 旧脚本却执行裸 `python`，依赖 GUI 进程继承的 `PATH`。
   - 保留系统目录、移除 `PATH` 中的 Python 后，旧脚本退出码为 1，没有返回结果，错误类型为 `CommandNotFoundException`，会触发同一条界面提示。

没有找到用户此前失败时的认证助手专用日志，因此不能把每次历史偶发失败都归为同一原因；以上两条均有本轮实际复现证据。

## 修改范围

| 文件 | 修改 |
| --- | --- |
| [认证启动脚本](C:/Users/Public/nas_home/crow/scripts/desktop-auth-challenge.ps1) | 优先使用环境变量或当前 bundle 配置的绝对 Python 路径；无效配置不静默回退；固定工作目录和模块路径；指定 UTF-8；按子进程退出码而非 stderr 警告判断成败。 |
| [桌面部署脚本](C:/Users/Public/nas_home/crow/scripts/deploy-collector-desktop-local.ps1) | 补齐 13 个 Python 实现模块及浏览器启动脚本的两个 PowerShell 子模块，避免后续完整打包再次遗漏。没有执行该完整部署脚本。 |
| [启动回归测试](C:/Users/Public/nas_home/crow/tools/test/test_desktop_auth_launcher.py) | 新增 11 项 Windows 测试，覆盖无 Python PATH、错误工作目录、配置优先级、非零退出、stderr 警告和参数边界。 |
| [真实安装包回归测试](C:/Users/Public/nas_home/crow/tools/test/test_desktop_auth_bundle.py) | 新增 5 项测试，按实际部署清单构造独立目录，使用真实助手并验证依赖完整性，而非只用模拟助手。 |
| [桌面说明](C:/Users/Public/nas_home/crow/collector-desktop/README.md) | 记录解释器选择、完整依赖要求、失败记录位置与测试边界。 |

失败时会留下最近一次启动失败的元数据：

`<当前安装目录>/FPFData/desktop-auth/last-launch-failure.json`

只包含时间、操作、固定错误分类和退出码，不保存原始 stderr、目标 URL、Cookie 或凭据。它是历史失败记录，不是当前认证状态。本轮故障复现产生的历史记录保留，后续成功不会被它判定为失败。

## 本机应用结果

当前安装目录：

[FapaiFangCollectorDesktop](C:/Users/vmjcv/AppData/Local/FapaiFangCollectorDesktop)

- 替换一个现有文件：`scripts/desktop-auth-challenge.ps1`。
- 以不覆盖已有文件的方式补入 13 个此前缺失的 Python 模块。
- 原安装已有的两个浏览器 PowerShell 子模块未重复替换。
- 更新安装清单，31 个记录文件全部通过 SHA-256 核验。
- 桌面进程保持 PID `37232`，启动时间仍为 `2026-09-07 20:37:35`。
- EXE、运行配置、Cookie、认证凭据、浏览器配置与配置目录未替换。
- 未停止、启动、重启或重新部署任何 PC2/NAS 服务；未查询、迁移、重建、删除数据库内容。
- 只更新当前实际运行的安装根目录，未覆盖历史 `updates` 目录。

备份：

- [原启动脚本与原清单](C:/Users/vmjcv/AppData/Local/FapaiFangCollectorDesktop/backups/20260907-171627-auth-launcher)
- [补入依赖前的清单](C:/Users/vmjcv/AppData/Local/FapaiFangCollectorDesktop/backups/20260907-172746-auth-modules)

安装回执：

- [启动脚本回执](C:/Users/Public/nas_home/crow/.debug/auth-launcher-20260908/install-receipt.json)
- [补齐依赖回执](C:/Users/Public/nas_home/crow/.debug/auth-launcher-20260908/modules-receipt.json)

关键哈希：

| 文件 | SHA-256 |
| --- | --- |
| 新认证启动脚本，与仓库一致 | `fad1683203617141486ad26a8979d1605e0d9abf6c15d41ef86dde8ce6eeba36` |
| 桌面 EXE，未改变 | `d597c380514cf6e15f11fcfd86c9f31cbf5c17408a20c3803d54d1214d26a450` |
| 运行配置，未改变 | `ed3224e87d739e45d03530062e340fdebf38497a658abd50e2306cddba0d1d5c` |

## 最终验证

- 相关 Python 测试：**89 passed**，包含真实安装包隔离测试、Windows 启动测试、原认证交接测试及设置 bundle 测试。
- 有效代码行检查器测试：**19 passed**。
- 有效代码行 ratchet：通过，扫描 940 个文件；原有未修改超限文件仍按基线处理，未修改基线。
- 两份修改的 PowerShell 脚本：语法错误数均为 0。
- `git diff --check`：通过。保留原有脏工作区改动，未提交、回滚或清理其他工作。
- 实际已安装助手：从临时目录运行，`PATH` 仅保留系统目录，三项探测均退出 0，stderr 为空：

| 操作 | 离线输入 | 预期且实际返回 |
| --- | --- | --- |
| `status` | 无效 API | `unavailable / invalid_api` |
| `open` | 无效挑战目标 | `unavailable / invalid_target` |
| `complete` | 无效 API | `unavailable / invalid_api` |

这里故意使用无效参数，使执行在访问网络、浏览器或凭据之前结束。这证明真实安装包的启动、导入和结果返回链可用，**不代表已完成真实挑战或 PC2 已恢复采集**。

## 接下来如何使用

直接重新点击认证按钮，按原来的“打开挑战页面 → 手工完成挑战 → 已完成挑战”操作即可，不用重新填写设置或重启程序。如再次失败，可根据新增的脱敏启动记录区分启动问题；浏览器未完成挑战、NAS 不可用等业务错误仍应按其实际状态处理，不能强行标记成功。
