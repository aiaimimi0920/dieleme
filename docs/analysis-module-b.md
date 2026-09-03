# 分析模块 B 运行说明

## 目标与边界

分析模块 B 在现有单模型分析模块 A 之上增加多模型一致性校验，但不改变原始网页归档，也不复用采集任务的运行状态。

- 模块 A 保持原样，可继续单独运行。
- 模块 B 对同一份脱敏分析输入并行执行三次模块 A，每次固定到一个明确且互不相同的模型路由。
- 三份候选结果按字段做确定性归一化和一致性计算。
- 只有 `3/3` 一致并且能在原始证据中找到支持的字段才会锁定。
- 有分歧或证据不足的字段，连同原始证据和三份完整候选结果交给仲裁模型处理。
- 仲裁模型不能改写锁定字段，任何非空结论都必须引用原文片段。
- 价格、面积等派生字段不采用模型投票；例如单价由最终成交价和建筑面积重新计算。

## 发布模式

通过 `FAPAI_ANALYSIS_MODULE_B_MODE` 控制：

| 值 | 行为 |
| --- | --- |
| `off` | 默认值。只运行模块 A，不增加模型调用或发布行为变化。 |
| `shadow` | 模块 A 仍是正式结果；模块 B 生成旁路审计产物，任何 B 失败都不会阻断 A。 |
| `primary` | 模块 B 成为正式结果。只有状态为 `finalized` 才写入正式 `extracted.json` / `final.json`；其他状态回到可重试分析队列。 |

推荐发布顺序固定为 `off -> shadow -> primary`，不得跳过 shadow 质量评估。

## 模型配置

```dotenv
FAPAI_ANALYSIS_MODULE_B_MODE=off
FAPAI_ANALYSIS_MODULE_B_CANDIDATE_MODELS=DeepSeek-V4-Flash,DeepSeek-V4-Pro-0813,gemini-3.1-flash
FAPAI_ANALYSIS_MODULE_B_ARBITER_MODEL=grok-4.6
FAPAI_ANALYSIS_MODULE_B_MAX_PARALLEL=3
FAPAI_ANALYSIS_MODULE_B_CANDIDATE_ATTEMPTS=3
FAPAI_ANALYSIS_MODULE_B_CANDIDATE_RETRY_SECONDS=10
FAPAI_ANALYSIS_MODULE_B_SHADOW_SAMPLE_RATE=0.01
```

约束：

1. 候选模型必须恰好为三个互不相同的路由。
2. 每次候选调用会强制使用指定路由，禁止网关静默回退到其他候选模型。
3. 对存在冲突的项目，仲裁模型必须独立于三个候选模型。若 shadow 配置临时复用候选模型，系统不会再次付费调用这个非独立模型，而是直接标记为 `needs_review`；`primary` 模式会在任何模型调用前拒绝该配置。
4. 没有冲突时不会调用仲裁模型。
5. 示例中的四个精确路由已通过真实网关的多样本结构化提取初筛；模块 B 仍默认关闭，必须先完成现网 `shadow` 质量评估才能启用 `primary`。
6. `shadow` 抽样率按 `item_id` 的稳定哈希确定，范围为 `0..1`；例如 `0.01` 表示约 1% 的项目运行模块 B，其余项目仍只运行模块 A。`primary` 不受抽样率影响。
7. 每个候选模型固定原路由重试，默认最多三次并按 10 秒、20 秒退避；只重试限流、服务端错误、网络错误和模型输出格式瞬态错误，禁止在候选之间静默回退。
8. `DeepSeek-V4-Flash` 是当前候选一的精确可用路由。2026-09-02 的现网验证中，该路由完成了完整模块 B 候选调用；`DeepSeek-V4-Flash-0731-think` 在自然 shadow 样本中多次达到 180 秒超时，而旧路由 `DeepSeek-V4-Flash-0731` 返回 `503 auth_unavailable`，两者均不得继续用于新运行。

## 一致性与证据规则

字段会先做类型化归一化，再比较：

- 金额统一为元，支持元、万、亿。
- 面积保留两位小数。
- 比例统一到固定精度。
- 计数统一为整数。
- 日期时间按数字组成部分归一化。
- 文本执行 Unicode NFKC、空白和常见标点归一化。

系统拥有的标识、原始 URL、可信种子标题、原始状态、坐标和采集标记不会由模型投票覆盖，而是在最终发布前由现有 `DetailCollectionService._preserve_seed_values` 恢复。

## 版本化审计产物

每个项目的模块 B 产物位于：

```text
<output>/<item-id>/analysis-b/
  latest.json
  analysis_module_b_v1/<input-sha256-prefix>/
    candidate-1.json
    candidate-2.json
    candidate-3.json
    consensus.json
    conflicts.json
    adjudication.json
    final.json
    receipt.json
```

- `candidate_input_sha256` 标识三次模块 A 共用的脱敏输入。
- `evidence_sha256` 标识仲裁所见的脱敏原始证据。
- `raw_html_sha256` 标识原始 HTML 内容，但不会把 HTML 写入数据库回执。
- `model_routing_sha256` 标识三个候选模型和独立仲裁模型的精确路由组合。
- `input_sha256` 是以上输入和模型路由哈希的组合指纹；任一内容或模型变化都会创建新的版本化运行目录和回执，禁止复用旧候选或旧仲裁。
- `run_id` 由项目 ID、流程版本和输入哈希确定性生成。
- 已成功的候选文件按模型和输入哈希复用；重试只调用缺失的候选模型。
- 原始 `detail.html`、`description-data.json`、采集时的 `selected.json` 继续保留，不会被模块 B 删除。

### A/B 结果来源标记

模块 B 的 `final.json`、`receipt.json`、`latest.json`、`selected.json` 中的
`analysis_module_b` 回执以及数据库 `fapai_analysis_run.receipt` 都包含同一份：

```json
{
  "analysis_provenance": {
    "module": "B",
    "pipeline_version": "analysis_module_b_v1",
    "run_id": "<deterministic-run-id>",
    "input_sha256": "<combined-input-hash>",
    "model_routing_sha256": "<candidate-and-arbiter-route-hash>"
  }
}
```

- `shadow` 模式只标记模块 B 的旁路产物和回执，模块 A 的正式 `extracted.json` / `final.json` 不带该标记。
- `primary` 模式发布成功后，正式 `extracted.json` / `final.json` 会保留该标记。
- 对正式结果而言，`analysis_provenance.module == "B"` 表示由模块 B 发布；没有该标记的历史正式结果视为模块 A/旧版结果，因此可以筛选出来重新进入分析队列，由模块 B 在不重采原始网页的前提下再次分析。
- 重新分析只复用已保存的 `detail.html`、`description-data.json` 和种子数据；不得删除或覆盖原始采集产物。

## 状态和失败隔离

| 状态 | 含义 | primary 发布 |
| --- | --- | --- |
| `finalized` | 所有字段已锁定或完成有证据的独立仲裁。 | 允许 |
| `needs_review` | 存在原文不足、仲裁缺失或仲裁模型不独立。 | 拒绝 |
| `candidate_partial` | 三个候选中至少一个失败；成功候选已缓存。 | 拒绝并重试 |
| `adjudication_failed` | 三个候选完成，但仲裁调用或校验失败。 | 拒绝并重试 |
| `failed` | shadow 旁路在建立完整回执前失败。 | 不适用 |

shadow 模式始终以模块 A 的完成为准，因此 B 的部分失败只记录审计回执，不会把 A 重新排队。primary 模式的非 `finalized` 结果会保留原始采集数据并进入现有可重试分析状态；再次处理相同输入时会复用成功候选。

## 数据库

Alembic 版本 `20260901_0009` 创建 `fapai_analysis_run`：

- 保存流程版本、输入哈希、模式、状态、候选模型、仲裁模型、产物路径和精简回执。
- 不写入或覆盖 `fapai_seed_item.source_payload`。
- 不把原始 HTML 或模型完整输出复制到数据库；完整内容保留在文件审计目录。

PC2 设置了 `FAPAI_DB_AUTO_CREATE=0`，因此任何实际启用前都必须先在 NAS 数据库执行正式 Alembic 升级。

## 上线检查

1. 执行数据库迁移并确认 Alembic head 为 `20260901_0009`。
2. 验证三个候选路由和第四仲裁路由均可调用，且不包含 GPT 路由。
3. 先启用 `shadow`，统计字段一致率、冲突率、`needs_review` 比例和每项目成本。
4. 人工抽查高风险字段：价格、面积、成交状态、法院、案号、租赁、占用、腾退、税费和产权份额。
5. 只有在第四模型独立、shadow 质量达标且回滚测试通过后，才切换到 `primary`。
6. 回滚只需把模式改回 `shadow` 或 `off`；原始数据和模块 A 路径不受影响。

### primary 切换门槛

以下条件应同时满足；进程健康或少量模型调用成功不能替代质量门禁：

1. 至少积累 50 个自然产生的 shadow 样本，并覆盖价格、面积、成交状态、法院、案号、租赁、占用、腾退、税费和产权份额等高风险字段。
2. 三候选完整率不低于 98%，独立仲裁技术完成率不低于 98%。
3. `finalized` 比例不低于 90%，`candidate_partial` 与 `adjudication_failed` 合计不高于 2%。
4. 人工复核至少 20 个包含高风险字段差异的样本，确认不存在已证实的高风险事实错误。
5. 验证 `analysis_provenance` 在旁路文件、正式文件和数据库回执中的语义一致，并完成一次 `primary -> shadow` 回滚演练。
