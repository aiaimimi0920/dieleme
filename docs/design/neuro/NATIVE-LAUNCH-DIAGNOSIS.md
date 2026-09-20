# 本机原生启动工具拒绝诊断

日期：2026-09-06。关联 [UI 优化交付记录](REFINEMENT-REPORT.md)。

**后续状态：已完成本机 exe 更新，并通过原有启动器正常启动，见 [完成记录](NATIVE-INSTALL-REPORT.md)。**
本文保留被拒绝测试命令的历史诊断，不再表示本机安装或正常启动尚未完成。

用户需要立即自行操作时，见 [本机 exe 更新与启动步骤](LOCAL-EXE-UPDATE.md)。
该流程不修改 Codex 执行策略，且不把用户操作视为工具拒绝已修复。

## 结论

用户已明确授权本机启动验证与更新；本地 Codex 配置也确实为全文件系统访问。
本轮再次尝试了不启用 CDP、不复制程序、不调用认证脚本的原生启动，仍被
`shell_command` 在执行前拒绝，返回 `rejected: blocked by policy`。

拒绝发生在执行工具边界，不是观察台返回的错误，也没有证据表明 Windows 拒绝了
exe。具体命中的宿主规则未公开，本轮未能消除该拒绝，不能声称已修复或完成安装。

## 已排查的证据

| 检查 | 结果及结论边界 |
| --- | --- |
| 本地配置 | `%USERPROFILE%\.codex\config.toml` 为 `approval_policy = "never"`、`sandbox_mode = "danger-full-access"`；没有修改这些配置 |
| 本地 requirements | 同一 Codex HOME 下未发现 `requirements.toml`；不代表不存在宿主或管理员侧约束 |
| 原始拒绝 | 原候选复制/夹具/CDP/原生启动组合命令被整体拒绝，没有 Windows 错误码或启动 PID |
| 缩小后的重试 | 仅配置本进程的测试 API、独立 WebView2 目录并启动已构建 exe，仍被拒绝；不是仅由 CDP 或候选复制引起 |
| 本地规则静态检查 | 对同一 PowerShell 命令运行 `codex execpolicy check --rules .../rules/default.rules`，返回 `{"matchedRules":[]}`；只说明该本地规则文件没有匹配，不能代表宿主完整授权结果 |
| 重试后进程 | 观察台进程数为 0，独立测试配置目录不存在，说明没有启动成功 |
| 已安装程序 | SHA-256 保持 `27b5bf86d9ec93ffe6b756b5e566a6532a61f0699c961fd9ef491c9526ebab74`，未替换 |

本地规则检查只把目标命令作为参数交给策略检查器，没有执行目标命令。
两次失败的诊断脚本自身分别遇到日志参数提取失败、未设置 `CODEX_HOME` 环境变量；
已按实际 HOME 路径修正静态检查，最终取得上表结果。这两项是诊断脚本错误，
与此前原生启动的工具拒绝不是同一问题。

## 本轮最小复现

以下为已提交给执行工具且被拒绝的命令，保留用于诊断，不是已验证可用的启动方案：

```powershell
$env:FAPAI_COLLECTOR_API_BASE='http://127.0.0.1:8001'
$env:WEBVIEW2_USER_DATA_FOLDER=Join-Path $env:TEMP 'crow-observer-native-smoke-20260906'
Remove-Item Env:WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS -ErrorAction SilentlyContinue
$exe=Join-Path $env:TEMP 'crow-observer-neuro-ui-target\release\fapaifang_collector_desktop.exe'
$process=Start-Process -FilePath $exe -WorkingDirectory (Split-Path -Parent $exe) -WindowStyle Hidden -PassThru
$process | Select-Object Id,ProcessName
```

实际工具输入以分号连接这些语句。`Remove-Item Env:...` 只清除当前子进程环境中的
WebView2 附加参数，不是删除磁盘文件；不能在没有规则证据时断言它是拦截原因。
本轮没有逐项变形重试以寻找绕过方式。

原生程序启动时会自动读取 API，因此指定回环地址；启动前确认 8001 无监听。
没有启动生产认证、采集 worker、桥接或任何远程服务。

## 权限解释与下一步

[官方审批与安全说明](https://learn.chatgpt.com/docs/agent-approvals-security) 区分沙箱访问
范围与审批策略；[官方规则说明](https://learn.chatgpt.com/docs/agent-configuration/rules)
描述独立的执行规则检查。本地全访问配置与本轮实际工具拒绝之间存在差异，
不能只凭配置值认定命令必定执行，也不能把 `never` 简单等同于所有动作均获准。

当前会话没有暴露命中的规则、规则修改接口或交互式批准入口。下一步应由当前
Codex 执行环境的维护方检查这次 `shell_command` 拒绝的内部原因，并通过其正式的
授权流程处理该具体本机启动请求。建议反馈材料包含本报告的命令、完整拒绝文本、
配置值和本地规则检查结果；不要上传认证文件、Cookie 或完整配置中的密钥。

本轮没有扩大 allowlist、改写审批/沙箱设置、关闭安全机制，也没有使用其他工具或
编码命令执行被拒绝动作。产品源码不需要为这条工具拒绝作猜测性改动。

后续获得正常执行结果后，仍需依次完成离线原生 WebView2 验收、备份现有 exe、
仅替换本机 exe 并复核哈希。不能使用完整部署脚本顺带改写认证桥接配置，
不能删除数据库。PC2/NAS 部署不属于此次授权范围。
