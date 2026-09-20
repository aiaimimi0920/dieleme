# Crow / Loom 壳层对齐

本文保留首轮壳层对齐的历史验证记录；其中四栏总览、运行细节和原生产物哈希不再代表
当前版本。后续五栏总览及阶段筛选见 [采集控制改版](COLLECTION-CONTROLS.md)。

## 本次结果

仅修改 Crow 桌面观察台源码、相关测试与说明。Loom 只读参考；保留进入任务时已有的
未提交改动，不更新或重启 PC2、NAS，不替换本机已安装的观察台。

| 项目 | 当前实现 |
| --- | --- |
| 默认窗口 | 1120×760；保留原有 980×680 最小窗口约束 |
| 侧栏 | 186px；折叠为 52px；820px 以下自动使用紧凑侧栏 |
| 顶栏 | 50px；原生窗口关闭系统装饰，使用应用内窗口控制 |
| 左上角 | 侧栏折叠按钮、Crow 标记、Crow 名称；折叠后只保留标记 |
| 右上角 | 刷新、最小化、最大化/还原、关闭；普通浏览器只保留刷新 |
| 左下角 | 设置入口固定到底部，窄屏和折叠时仍可访问 |
| 设置页 | API 连接、数据刷新分组；顶部返回；Escape 返回并恢复焦点 |

Loom 参考：`apps/desktop/src-tauri/tauri.conf.json`、`src/styles/shell.css`、
`src/App.tsx` 及 `components/settings/SettingsPanel.tsx`。
精确颜色仍沿用已归档的 Neuro 规范，不新建颜色体系。

## 信息删减与保留

- 删除品牌下的 COLLECTION CONSOLE、导航阶段编号和重复说明、COLLECTION / OPERATIONS、
  FapaiFang / Crow、常驻机器分工以及“采集运行总览”等重复标题。
- 每个采集阶段只有一个页面标题。表头缩短为商品编号、链接、地区、状态。
- API 地址和自动刷新时间移入设置页，不再占用日常采集页面。
- 默认总览只显示运行状态和三个阶段统计；挑战和续跑诊断通过“运行细节”展开。
- 待处理、失败、阻塞计数继续显示。认证续跑错误在紧凑状态下仍直接显示。
- 保留认证、暂停/开始、地区筛选与重置、分页、详情、再分析、手动编辑及结果反馈。
- 设置页切换不销毁采集 DOM，保留阶段、筛选、分页、详情、编辑内容和页面滚动位置。

## 验证证据

所有浏览器验证使用 `tools/test/collector_ui_preview.py` 的内存合成数据，浏览器请求
限制在 `http://127.0.0.1:1436/`。认证外部导航被阻断；暂停和恢复只修改夹具内存。

- 相关 Python 回归：43 passed，包括新增的壳层、设置页和窗口权限契约测试。
- 四个修改过的 JavaScript 模块：`node --check` 全部通过。
- 两个新增 TypeScript 模块：严格 `tsc --noEmit` 检查通过。
- 有效代码行检查器测试：19 passed；ratchet 无新增违规。
- Vite 生产构建通过；Tauri `tauri:build -- --no-bundle` 构建通过。
- `git diff --check` 通过；现有 Git LF/CRLF 提示不作为代码错误，未修改 Git 配置。
- 浏览器实测：1120px 宽时侧栏 186px、顶栏 50px、设置按钮底部距窗口底部 9px。
- 1600、980、760、390px 宽度均无页面横向溢出，底部设置始终可见。
- 设置进入/返回/Escape/焦点、侧栏折叠、阶段切换、详情保留、地区筛选、分页、手动编辑、
  认证对话框、空数据、断连、旧快照警告、重连、紧凑模式认证错误显示均通过离线浏览器检查。

扩展运行全仓库 `test_js_surface.py` 时达到 120 秒超时，未把这项记为通过；随后重新运行
上述 43 项聚焦回归并直接检查修改模块的语法，均通过。未发现该超时测试的残留 Python 进程。

## 截图

截图来自真实构建产物的离线浏览器运行，不是设计稿；数据为合成夹具。
浏览器不具备原生窗口能力，因此截图右上仅显示刷新，不伪造其余窗口按钮。

- [采集页，1120×760](../../../output/playwright/crow-loom-shell/collection.png)
- [设置页，1120×760](../../../output/playwright/crow-loom-shell/settings.png)
- [窄屏采集页，390×760](../../../output/playwright/crow-loom-shell/narrow.png)
- [窄屏设置页](../../../output/playwright/crow-loom-shell/narrow-settings.png)
- [空数据](../../../output/playwright/crow-loom-shell/empty.png)
- [断连和旧快照警告](../../../output/playwright/crow-loom-shell/error.png)

## 原生构建与未验证边界

构建产物：`%TEMP%/fapaifang-collector-desktop-target/release/fapaifang_collector_desktop.exe`。

- 文件大小：8,634,880 字节。
- SHA-256：`feba0fcb85b5b430fe2a458d3a9790e5bcae6a0a3760f515ffe3b1dab223b9d6`。
- [构建日志](../../../output/playwright/crow-loom-shell/native-build.log)。

尝试启动新构建产物进行原生窗口按钮验证时，执行工具返回 `blocked by policy`。
没有绕过限制；不能把编译通过表述为原生 WebView2 的拖动、最小化、最大化、关闭已实测。
为该检查临时启动的 8001 回环夹具已关闭，未使用现有服务。

API 地址仍受原有 Tauri CSP 允许列表约束；本次未放宽网络权限。设置页沿用原先的
内存 API 地址行为，不新增跨启动持久化。不修改已安装 EXE、启动器或快捷方式。
