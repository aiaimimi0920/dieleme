# 2026-06-02 seed/detail 双线采集最终方案

## 目标

把采集引擎从单进程“列表 union 后立刻抓详情”改成最终双线架构：

1. **Seed collector**：按区域、品类、排序组合逐页扫描，只收集商品 `item_id/url/title`，写入数据库队列，并记录每个 `区域 + 排序 + page` 的断点。
2. **Detail worker**：独立消费数据库中的 pending 商品详情队列，抓详情页、调用 LLM、写最终 JSON/DB，并将商品标记为完成或可重试失败。

## 非目标

- 不继续强化旧 `live_batch_smoke` 作为正式常驻入口。
- 不通过文件 resume_state 作为主断点来源；它只保留 legacy/smoke 用途。
- 不把扫描页和详情页绑定在同一批次内完成。

## 实施顺序

1. 新增数据库表和 repository 方法：
   - `fapai_seed_scan_job`
   - `fapai_seed_scan_progress`
   - `fapai_seed_item`
   - `fapai_seed_occurrence`
2. 新增 `tools/seed_collector.py`：
   - 从 DB claim 下一个扫描页。
   - 按 `st_param` 排序组合从第一页扫到结束。
   - 只 upsert URL 队列和 occurrence，不抓详情。
3. 新增 `tools/detail_worker.py`：
   - 从 DB claim 一个 pending seed item。
   - 复用已验证的详情抓取/LLM 提取逻辑。
   - 成功后写最终 DB 和完成状态；失败保留可重试。
4. Docker 默认改为两个常驻服务：
   - `fapaifang-seed-collector`
   - `fapaifang-detail-worker`
   - legacy `fapaifang-collector` 仅保留到 `legacy` profile。
5. 测试和验证：
   - repository 队列/断点单测。
   - seed collector 单页扫描单测。
   - detail worker 消费单测。
   - docker entrypoint/compose 单测。
   - compose config 和最小 live smoke。
