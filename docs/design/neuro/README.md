# Crow 运维观察台的 Neuro 设计基线

## 来源与权威性

2026-09-05 按用户要求归档 Neuro 的跨项目设计规范。`AI_PROMPT.md`、`DESIGN_SYSTEM.md`、`tokens.json`、`tokens.css` 是原始文件快照，不在这里另造颜色体系。

- 原始目录：`Neuro/docs/UI设计与颜色方案/`。
- 视觉参考：原目录 `screenshots/neuro-design-shell.png`。
- 实现参考：`Neuro/Loom/apps/desktop/src/styles/foundation.css`、`shell.css`，以及 `components/app/appShell.tsx`。
- Loom 的旧截图可能包含渐变主按钮或旧导航；以当前规范和实际主题变量为准，不复制历史差异。
- 此目录没有复制原参考网页与截图资产。上游 AI 提示词中 `index.html` / `screenshots/` 的引用指原始目录；Crow 产品页面自身才是本项目的验收对象。

## 适用范围

目标是 `collector-desktop` 的运维观察台，以及使用同一构建产物的 `/collection` 页面。不是 `game/web-app` 小游戏，不修改 Neuro/Loom 原项目，不改采集协议、数据库、新旧数据格式或认证恢复策略，不自动部署 PC2/NAS。

## 语义映射

| Neuro 角色 | Crow 用途 |
| --- | --- |
| background / surface / rail / panel / control | 应用壳层、左导航、连续运行板、表格与控件 |
| signalYellow | 当前采集阶段、键盘焦点、当前上下文的唯一主操作 |
| signalGreen | Crow 品牌、运行中、完成、认证恢复成功 |
| infoBlue | 商品链接、技术提示；不再用蓝色承担主按钮 |
| dangerRed | 失败、阻塞、危险动作和错误反馈 |
| focusSurface / focusInk / focusMuted | 当前选中商品行；白底必须使用深色文本 |

运行时保留既有 `--bg`、`--panel`、`--line`、`--text`、`--muted`、`--primary`、`--ok`、`--warn`、`--bad` 语义接口；新样式按主题、控件、壳层、运行板、数据内容和对话框拆分。

## 页面与行为

- 左导航只列真实的链接采集、详情采集、AI 归档三个采集阶段。AI 归档仍是采集引擎第三阶段，不宣称独立分析/预测引擎已成熟。
- 顶栏展示产品与当前上下文；API 连接信息和真实后台运行状态分开，不能把“API 已连接”画成“所有 worker 正常”。
- 运行总览、挑战触发率、PC1 认证状态及各阶段统计都来自现有 API，不复制 Neuro/MCP 示例数据。
- 地区筛选、分页、HTML 原文、标准化字段、再分析、手动编辑和认证动作保留。高风险动作不能仅靠颜色解释。
- 长表格和原文保留内部滚动，窄屏可堆叠，选中/禁用/错误同时有文字或结构区分。
- 对话框支持 Escape、焦点恢复和背景滚动锁定；所有按钮都有可见键盘焦点；尊重 reduced motion。

## 验收

核对规范快照与来源一致；检查实际产品桌面/窄屏、长文本、选择、空态、错误、加载、禁用和认证弹窗；测试数据只存在于离线测试夹具，禁止 UI 验证连接或控制生产采集服务。运行观察台构建、相关回归与项目有效代码行数门禁。构建成功不代表桌面安装包或线上部署已完成。
