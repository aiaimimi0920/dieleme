# src/ — 遗留模块

> ⚠️ 本目录为项目早期开发的模块，功能已被 `tb_adapter/` 中的实现替代。

## 模块说明

| 文件 | 原功能 | 替代方案 |
|------|--------|----------|
| `scraper_ali.py` | Playwright 列表页爬虫 | `tb_adapter/taobao_monitor.user.js` 嗅探模式 |
| `scraper_detail.py` | Playwright 详情页爬虫 | `tb_adapter/taobao_monitor.user.js` + `taobao_fast_worker.user.js` |
| `processor.py` | 成本计算器 (CostCalculator) | 可复用，暂时未活跃调用 |
| `custom_browser.py` | 反检测浏览器会话 (WebKit) | 仅 `scraper_ali.py` 依赖 |
| `db.py` | SQLite 数据库初始化 | 数据存储已改用 `datas/` JSON 文件 |
| `query.py` | 估值查询 | 暂时未活跃调用 |
| `scraper.py` | 基础爬虫类 | 被 `scraper_ali.py` 继承 |

## 入口

根目录的 `main.py` 编排 `AliScraper → DetailScraper → Processor` 流程，是这些模块的调用入口。

## 注意

保留这些模块是因为 `processor.py` 的成本计算逻辑未来可能复用，且 `main.py` 仍然引用它们。
