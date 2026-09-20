# 运维观察台 Neuro UI 紧凑布局优化交付

日期：2026-09-06。工作承接 [首轮设计迁移](IMPLEMENTATION-REPORT.md)。

**后续状态：本机 exe 已更新并成功启动，见 [原生安装完成记录](NATIVE-INSTALL-REPORT.md)。**
下面保留本轮优化交付时的阶段状态；其中“未安装”的描述已被后续完成记录更新。

## 当前结论

已完成前端源码优化、离线浏览器回归和 Windows 原生 release 可执行文件构建。
本机已安装的观察台仍为旧版，未替换；新 exe 尚未通过原生 WebView2 启动验收。
这三种状态不能混同为“已经安装上线”。

本轮没有部署、同步、重启或重新配置 PC2/NAS，没有操作生产数据库、Cookie、
人工认证浏览器或生产用户配置。截图和交互测试使用合成数据，不代表生产运行状态。
未修改 Neuro/Loom 原项目、采集 API、数据库格式或后台重试策略；原有工作区修改保留。

## 优化范围

| 部分 | 实现与约束 |
| --- | --- |
| 首屏信息密度 | 默认六列紧凑运行板，减少标题区与面板留白；可展开完整运行细节 |
| 关键运行指标 | 紧凑模式仍展示待处理、失败、阻塞提示，不以折叠隐藏异常 |
| 连接设置 | 使用可键盘操作的原生 `details`；默认折叠设置，连接状态始终可见 |
| 地区筛选 | 默认折叠筛选器，保留选中地区摘要、刷新和重置入口；未选定区县时明确说明尚需选择，避免把省市选择误呈现为已生效筛选 |
| 编辑上下文 | 手动编辑时保存是唯一高亮主操作；显示未保存提示，详情加载期间禁用相关操作 |
| 操作反馈 | 独立状态区提供 `role=status` 和 `aria-live=polite`，不再用结果文件路径区域承载提交反馈 |
| 写入与刷新 | 区分提交失败与提交后刷新失败；后者明确提示不必重复提交，失败时保留可编辑草稿 |
| 异步详情 | 使用请求代次防止 A → B → A 的旧详情覆盖，也防止已切换商品后旧写入响应污染当前详情 |
| 视觉规范 | 沿用归档的 Neuro token、语义颜色与现有样式责任拆分，不引入新配色体系或前端依赖 |

本轮没有扩大到所有总览异步请求的统一改造，也未改变地区过滤的后端语义。

## 页面与浏览器实测

### 1280 × 800 紧凑桌面总览

![紧凑桌面总览，离线合成数据](../../../output/playwright/neuro-ui-refinement/01-compact-desktop.png)

在最终构建上，列表表格顶部约为 548 px，首屏可以直接看到商品行；没有页面级横向溢出。
这是浏览器前端验证，不是原生 WebView2 截图。

### 手动编辑上下文

![编辑主操作与未保存提示，离线合成数据](../../../output/playwright/neuro-ui-refinement/02-edit-context.png)

编辑截图取自本轮末次小幅字体及地区提示调整前；最终紧凑总览、窄屏与写入错误截图
取自最终构建。编辑主操作及反馈逻辑在最终构建中保持一致。

### 本轮六张截图

| 场景 | 证据 |
| --- | --- |
| 紧凑桌面总览 | [01-compact-desktop.png](../../../output/playwright/neuro-ui-refinement/01-compact-desktop.png) |
| 编辑与未保存提示 | [02-edit-context.png](../../../output/playwright/neuro-ui-refinement/02-edit-context.png) |
| 已提交但状态刷新失败 | [03-save-refresh-warning.png](../../../output/playwright/neuro-ui-refinement/03-save-refresh-warning.png) |
| 390 × 844 窄屏总览 | [04-compact-narrow.png](../../../output/playwright/neuro-ui-refinement/04-compact-narrow.png) |
| 提交失败并保留草稿 | [05-write-error.png](../../../output/playwright/neuro-ui-refinement/05-write-error.png) |
| 窄屏初次连接失败 | [06-narrow-error.png](../../../output/playwright/neuro-ui-refinement/06-narrow-error.png) |

已实测的交互：

- 总览展开/收起、API 设置 Enter 展开/收起、地区筛选折叠及选中摘要。
- 390 px 宽度的正常与错误页面均无页面级横向溢出。
- 编辑状态仅保存按钮是可见高亮主操作；慢详情请求期间编辑和再分析禁用，完成后恢复。
- 将第一次 A 请求延迟后快速选择 A → B → A，旧响应不能覆盖最新 A 详情。
- 保存 A 期间切换到 B，A 的迟到响应不会修改 B 的详情或显示错误的保存成功提示。
- 保存成功后列表刷新返回 503，提示“已提交，但状态刷新失败”，保留结果路径。
- 保存请求返回 503，明确显示失败、保留草稿并恢复保存操作。

测试使用独立浏览器会话 `crow-neuro-refinement` 与仅监听回环地址的
`tools/test/collector_ui_preview.py`。写请求仅修改夹具内存，本轮没有点击真实认证入口。
测试浏览器已关闭，专用预览进程已停止；最终只读检查确认 1436、8001、9437
均无监听，原生测试服务和候选原生程序未启动。

## 最新验证结果

| 门禁 | 结果 |
| --- | --- |
| 观察台契约、Neuro 主题、静态控制台与 JS 清单回归 | 44 passed，109.68 秒 |
| 有效代码行数检查器单元测试 | 19 passed，0 failed |
| 全仓有效代码行数 ratchet | 864 文件，0 新违规；未更新基线 |
| Vite 生产前端构建 | 15 modules，310 ms；CSS 14.66 kB，JS 45.42 kB |
| Tauri Windows release 构建 | `--no-bundle` 成功，最终增量构建 57.34 秒 |
| 修改源码编码与空白检查 | UTF-8 无 BOM；范围内 `git diff --check` 通过 |

ratchet 仍保留原有未修改的 1909 有效行 userscript 债务，并非本轮增加豁免。
本轮修改的详情/编辑模块为 492 有效行，没有借助删测试或迁移到产物目录规避限制。

可复核日志：
[44 项回归](../../../output/playwright/neuro-ui-refinement/regression-tests.log)、
[19 项检查器测试](../../../output/playwright/neuro-ui-refinement/line-check-tests.log)、
[ratchet](../../../output/playwright/neuro-ui-refinement/ratchet.log)、
[最终原生构建](../../../output/playwright/neuro-ui-refinement/native-build-final.log)。

## 原生构建产物与未执行范围

构建使用仓库内既有 Tauri 脚本，设置
`CARGO_TARGET_DIR = Join-Path $env:TEMP 'crow-observer-neuro-ui-target'`，运行
`npm --prefix collector-desktop run tauri:build -- --no-bundle`。
这会生成 exe，但不生成 MSI/NSIS 安装包，也不会更新已安装程序。

| 项目 | 已核实的状态 |
| --- | --- |
| 新 release exe | `%TEMP%\crow-observer-neuro-ui-target\release\fapaifang_collector_desktop.exe`，8,618,496 字节 |
| 新 exe SHA-256 | `fe0471ef217d55441fe2505201b9cfa66d4666b8341e4f1e6cc689196cf077d9` |
| 原安装 exe | `%LOCALAPPDATA%\FapaiFangCollectorDesktop\fapaifang_collector_desktop.exe`，8,654,848 字节，保持不变 |
| 原安装 SHA-256 | `27b5bf86d9ec93ffe6b756b5e566a6532a61f0699c961fd9ef491c9526ebab74` |

新 exe 位于临时构建目录，不是正式安装或长期归档目录。

后续候选复制、离线夹具启动与原生启动验证的组合命令被 `shell_command` 工具层
拒绝，返回 `blocked by policy`。工具没有给出命中的具体规则，因此不能判断是其中
哪一个子动作触发，也不能将其归因于用户撤销权限。该命令未执行：预定候选副本与
原生会话清单均不存在，测试端口未启动，已安装 exe 的哈希未改变。
没有通过其他工具、编码命令或其他进程绕过该拒绝。

因此本轮明确尚未完成：原生 WebView2 启动/交互验收、本机安装替换、安装包验收。
没有执行 `scripts/deploy-collector-desktop-local.ps1`，没有改动快捷方式或认证桥接。
不得将浏览器回归和原生编译成功表述为原生运行成功或安装更新完成。

用户再次明确授权后的最小重试与本地规则检查见
[原生启动工具拒绝诊断](NATIVE-LAUNCH-DIAGNOSIS.md)。该重试仍在执行前被工具拒绝，
尚未改变上述安装与原生验收状态。
