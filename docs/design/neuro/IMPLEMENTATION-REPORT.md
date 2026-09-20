# 运维观察台 Neuro UI 改造交付

日期：2026-09-05。

## 结论与边界

已把 Neuro 当前设计规范及 Loom 的实际壳层风格应用到 Crow 的
`collector-desktop` 观察台，完成源码实现、生产前端构建和独立浏览器离线验证。
本报告截图全部使用合成测试数据，不能当作 PC2/NAS 当前运行状态或采集结果。

本次 UI 阶段没有部署、同步、重启或控制 PC2/NAS，没有读写生产数据库，没有替换
本机已安装的桌面程序，没有操作 PC1 人工认证 Chrome/CDP 或其用户配置。
Neuro 和 Loom 原项目只读，原有工作区修改保留。

## 设计来源先归档

- [Crow 适配说明](README.md)：范围、语义角色、页面行为和验收约束。
- [原始设计规范](DESIGN_SYSTEM.md)、[原始 AI 提示词](AI_PROMPT.md)。
- [原始颜色 token](tokens.json)、[原始 CSS token](tokens.css)。
- [来源与 SHA-256 清单](source-manifest.json)。

这四份原始规范快照与 Neuro 当前源文件逐字节一致；编码为 UTF-8，无 BOM。
实现交叉核对了 Loom 的 `apps/desktop/src/styles/foundation.css`、
`shell.css` 和实际截图。历史截图中的渐变主按钮没有作为新标准照搬。

## 已实现的视觉与交互

| 部分 | 处理 |
| --- | --- |
| 应用壳层 | 近黑背景、紧凑左导航、细分隔线；窄屏改为顶部三阶段导航 |
| 阶段导航 | 仅链接采集、详情采集、AI 归档；不虚构新的分析/预测引擎 |
| 运行总览 | 六块统计整合为连续运行板，保留真实 API 数据入口 |
| 颜色角色 | 黄色用于激活/焦点/主操作，绿色用于品牌/运行/完成，青色用于链接，红色用于失败/危险动作 |
| 地区与列表 | 紧凑筛选、文字加颜色状态、内部滚动、明确的分页禁用边界 |
| 详情与 AI 字段 | 选中行白底深色文本，长原文和长字段内部滚动；保留编辑、更新、再分析 |
| 认证与重置 | 统一深色对话框、Escape、Tab 循环、焦点恢复、背景 inert 和滚动锁 |
| 加载与故障 | 刷新按钮防重复、空列表 0-0、失败反馈、旧指标明确标注为上次快照 |
| 异步响应 | 旧列表请求不能覆盖新阶段；旧详情响应不能覆盖新选中商品 |
| 无障碍 | 行支持 Enter/Space，可见键盘焦点、ARIA 状态/标签、减少动态效果 |

样式拆分为 `theme / controls / shell / overview / collection / dialogs` 六个责任文件，
通过原有 `src/styles.css` 入口引入，没有增加前端依赖。

标准化字段标签及 29 组新旧字段别名被原样提取为
`src/desktop_standardized_fields.json`，保持中文旧字段和英文新字段读取兼容。
没有修改采集协议、数据库结构、认证恢复策略或后台重试策略。

## 实际产品页面

### 桌面总览，1440 × 1000

![桌面总览，合成测试数据](../../../output/playwright/neuro-ui/01-overview-desktop.png)

### AI 归档和长字段

![AI 归档，合成测试数据](../../../output/playwright/neuro-ui/03-analysis-desktop.png)

### 完整截图索引

| 场景 | 截图 |
| --- | --- |
| 桌面总览 | [01-overview-desktop.png](../../../output/playwright/neuro-ui/01-overview-desktop.png) |
| HTML 原文详情 | [02-detail-desktop.png](../../../output/playwright/neuro-ui/02-detail-desktop.png) |
| AI 标准化字段 | [03-analysis-desktop.png](../../../output/playwright/neuro-ui/03-analysis-desktop.png) |
| 手动编辑 | [04-analysis-edit.png](../../../output/playwright/neuro-ui/04-analysis-edit.png) |
| 地区重置确认 | [05-reset-confirmation.png](../../../output/playwright/neuro-ui/05-reset-confirmation.png) |
| 认证对话框 | [06-auth-dialog.png](../../../output/playwright/neuro-ui/06-auth-dialog.png) |
| 390 × 844 窄屏总览 | [07-narrow-overview.png](../../../output/playwright/neuro-ui/07-narrow-overview.png) |
| 窄屏长字段 | [08-narrow-analysis.png](../../../output/playwright/neuro-ui/08-narrow-analysis.png) |
| 首次连接失败 | [09-initial-error.png](../../../output/playwright/neuro-ui/09-initial-error.png) |
| 空列表 | [10-empty.png](../../../output/playwright/neuro-ui/10-empty.png) |
| 慢请求加载 | [11-loading.png](../../../output/playwright/neuro-ui/11-loading.png) |
| 旧指标失效提示 | [12-stale-error.png](../../../output/playwright/neuro-ui/12-stale-error.png) |

## 验证结果

| 门禁 | 结果 |
| --- | --- |
| 观察台契约、主题、静态 Web 控制台、JS 清单与 Node 语法检查 | 41 passed，82.64 秒 |
| 有效代码行数检查器单元测试 | 19 passed |
| 全仓有效代码行数 ratchet | 864 文件，0 violations；未再生基线 |
| `npm --prefix collector-desktop run build` | Vite 8.0.16 构建通过，15 modules |
| 本次 26 个代码/规范文件编码检查 | UTF-8，无 BOM |
| 本次范围 `git diff --check` | 通过 |
| 独立只读源码复核 | 未发现发布阻断级 UI 回归 |

ratchet 保留仓库原有未修改的 1909 有效行 userscript 债务；它不是本次新增豁免。
构建产物在 `collector-desktop/dist/`：CSS 12.30 kB，JS 42.77 kB。

浏览器验证使用独立会话 `crow-neuro-ui` 和仅监听 `127.0.0.1:1436` 的
离线夹具服务。外部请求被阻断，认证弹窗测试模拟浏览器阻止外部弹窗。
没有执行真实认证、Cookie 导出或生产恢复操作。

已实测的行为包括：

- 最后一页 11-12 禁用下一页；空数据显示 0-0 并禁用翻页。
- Enter 打开详情，关闭后焦点回到商品行；选中行计算样式为
  `rgb(243,245,241)` 背景与 `rgb(32,37,43)` 文本。
- 长 HTML 内部滚动；390px 和 768px 宽度没有页面级横向溢出；
  reduced motion 下按钮过渡时长为 0 秒。
- 字段更新提交数值类型并重新展示返回值；再分析请求携带选中商品 ID。
- 地区重置默认焦点在取消；Escape 不产生写请求；确认仅对选中地区发出一次请求。
- 认证弹窗双向 Tab 循环；关闭后背景恢复，焦点回到被总览刷新替换后的认证按钮。
- 2 秒慢请求期间刷新按钮禁用；失败和恢复均有正确状态。
- 人为延迟旧阶段/旧商品请求，新阶段列表和新详情不被旧结果覆盖。

首次失败检查发现的加载占位残留问题已修复并重建复测。最终浏览器控制台检查只有
故障夹具主动返回的 HTTP 503，没有产品 JavaScript 异常。初次打开的 favicon 404
不影响页面，测试过程中已与产品异常区分。

### 可复核的原始证据

- [浏览器命令与断言记录](../../../output/playwright/neuro-ui/browser-verification.log)。
- [41 项测试日志](../../../output/playwright/neuro-ui/gate-0.log)。
- [19 项行数检查器测试日志](../../../output/playwright/neuro-ui/gate-1.log)。
- [ratchet 日志](../../../output/playwright/neuro-ui/gate-2.log)。
- [构建日志](../../../output/playwright/neuro-ui/build.log)。
- [来源、编码和范围核验](../../../output/playwright/neuro-ui/scope-verification.json)。

## 如何查看与尚未执行的范围

按照 [桌面项目 README](../../../collector-desktop/README.md) 的“UI 设计基线与离线预览”
启动夹具即可查看构建后的真实前端。夹具所有写操作只保存在进程内存。
本轮专用浏览器已关闭，预览进程已停止，1436 端口已确认关闭。

- 已安装桌面程序不会因为修改源码或构建 Web 前端而自动更新。
- 未制作/验证新的 Tauri 原生安装包，未替换本机运行中的 exe。
- 未上线到 NAS/PC2，未对生产数据或当前采集吞吐作新结论。
- 使用该构建产物的 `/collection` 页面可获得相同主题；后端在找不到构建产物时的
  旧内联 fallback 页面不在本次视觉迁移范围。
- 参考截图、浏览器运行截图和构建产物是本地验收材料，不能代替原生 WebView2 与
  正式安装包的后续验收。
