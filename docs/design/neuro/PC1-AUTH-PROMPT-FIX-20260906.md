# PC1 人工认证重复弹窗修复

核验时间：2026-09-06 10:16（Asia/Shanghai）。

## 结果

**已修复并部署到正在使用的 PC1 后台认证任务，无需重启 Crow 桌面程序。**

删除截图中的 `Crow - PC2 manual authentication required` 模态提示框。同一次认证任务不再按时间重复抢焦点；新认证任务仍可首次显示专用 Chrome 窗口。真实认证未通过时，仍保持待认证，不伪造成功或发布未经验证的 cookies。

## 根因

- 提示框来自 `scripts/pc1-auth-recovery-policy.ps1` 的 `WScript.Shell.Popup`，不是桌面应用异常堆栈。
- PC1 计划任务 `\FapaiFang\FapaiFangNasAuthRecovery` 每分钟执行一次。
- 原策略会在同一认证任务尚未完成时，每隔至少 300 秒重新提醒。
- 每次提醒都会显示 8 秒模态框，并重复尝试将认证浏览器置前，因此持续未完成的认证会不断打断用户。
- 本次运行检查没有发现重复 watcher 进程；不能因采样时没有弹窗进程，就推断弹窗来自 WebView。

## 修改范围

仅修改两个生产脚本：

1. `scripts/pc1-auth-recovery-policy.ps1`
   - 删除 COM 模态弹窗及第二次浏览器置前。
   - 同一 recovery 一旦记录提醒尝试，就不再因时间到期、时钟变化或旧时间戳格式异常重复提醒。
2. `scripts/watch-pc1-nas-auth-recovery.ps1`
   - 显示窗口前先持久化本次尝试，避免置前失败导致每次轮询都重试。
   - 保留真实认证检查、待认证状态和验证通过后的原有交接逻辑。

没有修改 NAS/PC2 服务、SSH 转发权限、数据库、浏览器 profile 或 cookies；没有终止桌面程序或 Chrome。

## 实际部署

新发布：

```text
C:\Users\Public\FapaiFangAuthRecovery\releases\20260906-pc1-auth-quiet
```

旧发布保留：

```text
C:\Users\Public\FapaiFangAuthRecovery\releases\20260905-pc1-human-handoff-v3
```

任务备份：

```text
C:\Users\Public\FapaiFangAuthRecovery\backups\20260906-pc1-auth-quiet
```

- 先核对旧发布的 11 个 payload 文件哈希，再复制到新发布，仅覆盖上述两个脚本；其余 9 个文件未变。
- 短暂禁用任务并等待旧 watcher 自然退出，没有强杀进程。
- 仅切换任务执行脚本及工作目录。触发器、运行身份和任务设置的 XML 对比均未变化，任务已恢复启用。
- 活跃发布的两个脚本与仓库修复版本字节及 SHA-256 完全一致，均为 UTF-8 无 BOM。
- 桌面程序仍为原 PID 60392，没有因本次修复重启。

## 验证

- 新增回归测试先在旧实现上复现 4 项失败，覆盖重复提醒、异常时间戳和 COM 弹窗调用。
- 修复后相关认证交接及连续采集脚本测试：**79 passed**。
- 另外验证：即使窗口置前失败，提醒尝试也先被记录，三次后续模拟轮询不会重复置前。
- 有效代码行检查器：19 passed；ratchet 通过。
- 相关路径 `git diff --check` 通过。
- 实际计划任务在 10:15:05 和 10:16:05 正常运行并以退出码 0 完成。
- 约 130 秒、64 次实际窗口采样：匹配该标题的弹窗最大数量为 0。
- 使用活跃发布的策略函数与现有状态核验：同一任务 `same_request_will_refocus=false`。

运行观察回执：`.debug/pc1-auth-prompt-20260906/runtime-observation.json`。

此次运行观察没有证明网站人工认证已经成功；观察期间本地上次认证探测状态仍为待验证，未改写成成功。未来新一轮认证的无模态框行为由删除唯一生产者及离线回归测试证明，没有为了验收而主动制造网站挑战。
