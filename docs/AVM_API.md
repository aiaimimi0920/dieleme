# AVM API 接口文档（可直接供前端/脚本消费）

本文档定义 AVM 读接口与批量筛选接口，包含请求/响应字段与落盘告警约定。

## 1) 单条估值接口（只读）

- **Method**: `GET`
- **Path**: `/api/avm/predict?id=<item_id>`
- **Alias**: `/api/analysis/predict?id=<item_id>`
- **用途**: 查询单个标的的估值结果与主要风险说明。

### 请求参数

| 参数 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `id` | string | 是 | 标的 ID |

### 返回示例

```json
{
  "id": "4873096974090",
  "predicted_price": 25522250.0,
  "starting_price": 17865575.0,
  "margin": 0.300000019590589,
  "is_malignant_risk": false,
  "major_risks": [],
  "risk_summary": "未发现恶性风控标签",
  "risk_validation": {
    "ok": false,
    "missing_required_count": 6,
    "invalid_field_count": 0,
    "feature_completeness": 0.75
  },
  "trace": {
    "valuation_mode": "current_market"
  }
}
```

### 错误码

- `400`: 缺少 `id`
- `404`: 标的不存在
- `422`: 缺少估值或起拍价格，无法计算

### 响应补充说明

`GET /api/avm/predict` 现在也会直接带出：

- `risk_validation`
  - 当前标的风险字段的完整度/合法性摘要
- `trace.valuation_mode`
  - 当前主链默认是 `current_market`

---

## 1.5) 健康检查接口

- **Method**: `GET`
- **Path**: `/api/avm/health`

当前除了数据集级摘要外，还会补充：

- `coordinate_strategy_counts`
- `active_risk_discount_factor`
- `active_weighting`
- `calibration_guidance`
- `calibration_target_counts`
- `top_calibration_target`
- `top_calibration_target_hint`
- `coordinate_strategy_watchlist`
- `top_coordinate_strategy_group`

其中：

- `calibration_guidance`
  - 用于快速表达当前更像：
    - 参数调优问题
    - 坐标质量问题
    - 风险字段质量问题
- `calibration_target_counts` / `top_calibration_target`
  - 用于补充当前最值得先看的具体调参 target
  - 当前 target counts 还会区分：
    - `global_risk`
    - `risk_factor`
    - `temporal`
    - `strategy`
- `top_calibration_target_hint`
  - 用于把这个 top target 继续翻译成更直接的下一步动作
  - 并会补充：
    - `suggested_commands`
    - `suggested_bundle_commands`
    - `playbook_id`
    - `runbook_refs`
  - 如果 `suggested_bundle_commands` 当前只显式给了 preview command，
    pipeline / offline / HTTP summary 里的 `recommended_bundle_write_command`
    现在也会继续按这条 preview command 自动补成对应的 `... --write`。
  - 反过来，如果 `suggested_bundle_commands` 当前只显式给了 bona fide `write ... --write`，
    pipeline / offline / HTTP summary 里的 `recommended_bundle_preview_command`
    现在也会继续通过去掉尾部 `--write` 自动补回 preview command。
  - 如果 `recommended_bundle` 本身已经给出了 `target_types` / `target_names`，
    但 `suggested_bundle_commands` 整段缺失，
    pipeline / offline / HTTP summary 现在也会直接按这组 target filter
    自动合成 canonical preview / write commands。
- `top_calibration_patch_preview`
  - 用于只预览当前 `top_calibration_target` 对应的那部分 patch
  - 当前会补充：
    - `applied_filter`
    - `matched_targets`
    - `changed_paths`
    - `rollback_patch`
- `recommended_bundle_patch_preview`
  - 用于只预览 `top_calibration_target_hint.recommended_bundle` 对应的那组 patch
  - 当前会补充：
    - `bundle_id`
    - `applied_filter`
    - `matched_targets`
    - `changed_paths`
    - `rollback_patch`
- `recommended_bundle_risk_level` / `recommended_bundle_risk_reasons`
  - 用于快速表达这组 recommended bundle 更像：
    - `low`
    - `medium`
    - `high`
  - 当前会基于：
    - changed key 数量
    - 是否同时涉及 `risk_discount_factor` 与 `weighting.*`
    - 是否一次性改多个 `risk_factor_overrides.*`
    做轻量风险归类
- `recommended_bundle_next_action` / `recommended_bundle_next_action_reasons`
  - 用于在风险归类之上继续表达：
    - `no_action_required`
    - `safe_to_write_then_verify`
    - `preview_only_first`
    - `split_bundle_or_single_target_first`
  - 让 operator 先看出这组 bundle 更适合：
    - 直接写回再验证
    - 还是先只做 preview
  - 对于弱输入 preview payload，
    如果 `changed_key_count` 暂时缺失，但 `changed_keys` 已知，
    next action 现在也会继续按 `changed_keys` 推导，
    避免被错误降成 `no_action_required`
- `recommended_bundle_next_action_command` / `recommended_bundle_next_action_command_kind`
  - 用于把这层 next action 进一步收敛成：
    - 当前建议优先执行的单条命令
    - 以及它属于 `preview` / `write` / `none` 哪一类
- `recommended_bundle_follow_up_command` / `recommended_bundle_follow_up_command_kind`
  - 用于补充：
    - 当前 first command 跑完之后，下一条更自然的 follow-up 命令
    - 以及它属于 `write` / `verify` / `none` 哪一类
- `recommended_bundle_command_chain`
  - 用于把这些离散字段再收成一份结构化命令链
  - 当前会按顺序组合：
    - first command
    - follow-up command
    - verify command
    - gate command
  - 但如果当前 flow 还停在高风险的：
    - `split_bundle_or_single_target_first`
    且还没有 `write` / `verify` 路径，
    这条链现在会停在 `preview`，
    不再过早广告 downstream `verify` / `gate`
  - 同时这类 high-risk preview step 自己也不会再继续广告：
    - `step_ready_follow_up_command = write`
    而是会把内部 follow-up 一并清空，
    保持“先 preview / 先 split，再决定是否写回”的真实语义
  - 每一步当前还会补充：
    - `expected_signal`
    - `success_criterion`
    - `surface`
    - `artifact_kind`
    - `artifact_owner`
    - `artifact`
    - `artifact_resolved_path`
    - `artifact_check_command`
    - `artifact_check_timing`
    - `artifact_freshness`
    - `artifact_freshness_reason`
    - `artifact_next_expected_transition`
    - `artifact_ready_for_step`
    - `step_ready_summary`
    - `step_ready_recommended_action`
    - `step_ready_action_command`
    - `step_ready_follow_up_command`
    - `step_ready_follow_up_expected_signal`
    - `step_ready_follow_up_success_criterion`
    - `step_ready_terminal_outcome`
    - `step_ready_stage_span`
    - `step_ready_priority`
    - `step_ready_badge`
    - `step_ready_group_id`
    - `step_ready_group_label`
    - `step_ready_sort_key`
    - `step_ready_display_order`
    - `step_ready_lane`
    - `step_ready_lane_label`
    - `artifact_state`
    - `artifact_state_reason`
  - 便于 operator / UI 继续知道这一步执行后应重点观察什么
  - 对于离线 `run_avm_pipeline.py` 的 gate-stage summary，
    如果 release gate report 本身没有回填 `evaluation.calibration_targets`，
    当前也会回退读取 `datas/avm/calibration_targets.json`，
    继续补全这组 `recommended_bundle_*` 字段。
  - `GET /api/avm/release_gate` / `GET /api/analysis/release_gate`
    现在除了原始 gate report 外，
    也会继续把这段 calibration context flatten 成更直接的 operator 字段，例如：
    - `calibration_guidance`
    - `calibration_target_counts`
    - `top_calibration_target`
    - `top_calibration_target_hint`
    - `recommended_bundle_*`
    - `coordinate_strategy_watchlist`
    - `top_coordinate_strategy_group`
    避免调用方自己再从 `evaluation.calibration_targets` 做一层手工拆解。
    这层 flatten 摘要现在也会优先跟随**当前请求刚生成出来的 gate report**，
    而不是依赖请求前磁盘上遗留的旧 `release_gate.json`。
  - 对于离线 `run_avm_pipeline.py` 的 calibration / gate stage summary，
    当前也会继续直接暴露：
    - `has_recommendations`
    - `global_risk_target_count`
    - `risk_factor_target_count`
    - `temporal_target_count`
    - `strategy_target_count`
    - `top_coordinate_strategy_group`
    便于 operator 在不展开完整 calibration payload 的情况下先看各类 target 的规模。
  - 对于离线 `run_avm_pipeline.py` 的 calibration-stage summary，
    即使 `suggest_calibration_targets(...)` 返回的是一个不完整的弱输入 payload，
    只要 target lists 本身还在，
    当前也会继续按：
    - `global_risk_targets`
    - `risk_factor_targets`
    - `temporal_targets`
    - `strategy_targets`
    推导 `has_recommendations` 和各 target count，
    避免因为缺少顶层 `has_recommendations` / count metadata 而直接掉成异常。
  - 同样的弱输入规范化现在也会继续应用到：
    - `src/avm/pipeline.py` 写出的 `calibration_targets.json`
    - release gate `evaluation.calibration_targets`
    - `src/server.py` 读取的 file-backed `calibration_targets.json`
    避免这两条 producer path 把缺失的 target lists / guidance / `has_recommendations`
    原样暴露成一个不完整 contract。
  - 如果 `src/server.py` 读到的 `calibration_targets.json` 虽然存在，
    但底层已经不是 JSON object（例如历史脏数据写成了 `[]`），
    当前也会退回到一份临时的 normalized calibration payload 做 preview / summary，
    避免 `/api/status` / `/api/avm/health` 因这类坏文件直接崩掉。
  - 如果 `src/server.py` 读到的 `datas/avm/config.json` 虽然路径存在，
    但底层已经不是 JSON object（例如历史脏数据写成了 `[]`），
    或 JSON 语法本身已经损坏，
    或虽然是 object 但结构/数值校验已经不合法，
    当前也会在 AVM operator summary preview path 上退回到一份临时的默认 config payload，
    避免 `/api/status` / `/api/avm/health` / release-gate HTTP route 因这类坏文件直接崩掉。
  - 同样地，对于离线 `src/avm/pipeline.py::_write_calibration_targets(...)`
    以及 `tools/run_avm_pipeline.py` 的 calibration / gate stage summary preview path，
    如果 `datas/avm/config.json` 虽然存在但底层不是 JSON object，
    或 JSON 语法本身已经损坏，
    或虽然是 object 但结构/数值校验已经不合法，
    当前也会退回到一份临时的默认 config payload，
    避免离线 summary / bundle preview 因这类坏文件直接崩掉。
  - 对于直接运行的 `python tools/apply_avm_calibration_patch.py` preview / write path，
    如果 `datas/avm/config.json` 虽然存在但底层不是 JSON object，
    或 JSON 语法本身已经损坏，
    或虽然是 object 但结构/数值校验已经不合法，
    当前也会把它按“缺失 config”语义回落到默认 AVM 配置，
    避免 direct applier 因这类坏文件直接抛异常。
  - 对于运行态主配置加载器 `src/avm_config.py::AvmConfigManager`，
    如果 `datas/avm/config.json` 在 startup / hot reload 时：
    - 不是 JSON object
    - JSON 语法损坏
    - 或虽然是 object，但结构/数值校验失败
    当前也会统一回退到 `DEFAULT_AVM_CONFIG`，
    避免 runtime 主链继续带着半合法坏配置运行。
  - 但 `datas/avm/calibration_targets.json` 仍保持 strict contract：
    如果它本身不是合法 JSON object，
    direct applier 当前会明确抛出带路径的
    `ValueError("invalid JSON object at .../calibration_targets.json")`，
    而不是静默回退成空 patch。
  - 对于 `src/server.py` 的 `/api/status` / `/api/avm/health` / `/api/analysis/health` / `/api/analysis/status` AVM summary，
    如果独立的 `calibration_targets.json` 缺失，
    但 `release_gate.json.evaluation.calibration_targets` 仍然存在，
    当前也会继续回退到这段 embedded calibration context，
    保持 guidance / target counts / bundle commands / patch preview 可见。
  - 如果 `release_gate.json.evaluation.calibration_targets` 只回填了一个稀疏片段，
    `src/server.py` 当前也会继续把这段 embedded fragment 和 file-backed
    `calibration_targets.json` 做补齐合并，
    避免一个 partial embedded payload 反向抹掉更完整的 file-backed calibration context。
  - 如果 release gate report 只回填了一个不完整的
    `evaluation.calibration_targets` 片段，
    当前也会继续与 `datas/avm/calibration_targets.json` 做补齐合并，
    避免把已有的 bundle context 错误降成 `none/no_action_required`。
  - 当前 `artifact_state` 会区分：
    - `present`
    - `missing`
    - `not_ready_yet`
    - `stale`
  - 当前 `artifact_freshness` 会区分：
    - `current`
    - `stale`
    - `pending_write`
    - `pending_rerun`
  - `artifact_freshness_reason` 用于继续解释：
    - 为什么当前是 stale
    - 为什么当前仍在等待 write / rerun
  - `artifact_next_expected_transition` 用于补充：
    - 当前 artifact 下一步最自然会从什么状态转成什么状态
  - `artifact_check_command` 用于补充：
    - 如果现在要直接检查这个 artifact，对应应执行哪条命令
  - `artifact_check_timing` 用于补充：
    - 当前这类 artifact 更适合在 step 前还是 step 后观察
    - 当前已知 AVM step kind 会区分：
      - `preview` -> `pre_step`
      - `write` / `verify` / `gate` -> `post_step`
  - 如果某个已知 AVM step kind 没有显式携带 artifact 元数据，
    resolver 现在也会按 step kind 自动补默认的：
    - `expected_signal`
    - `success_criterion`
    - `surface`
    - `artifact_kind`
    - `artifact_owner`
    - `artifact`
    - `artifact_resolved_path`
    - `artifact_check_command`
  - 如果调用方已经提供了 `artifact` 路径、但漏掉了：
    - `artifact_kind`
    - `artifact_owner`
    resolver 也会继续按已知 step kind 自动补齐这两层 metadata。
  - 同理，如果调用方漏掉了：
    - `expected_signal`
    - `success_criterion`
    - `surface`
    resolver 现在也会继续按已知 step kind 自动补齐这些 step contract 字段。
  - 对于当前已知且默认命令稳定的 step（例如 `verify` / `gate`），
    如果调用方漏掉了 `command`，
    resolver 现在也会按已知 step kind 自动补齐默认 command。
  - 对于 `write`，如果同一条 chain 里已经有可执行的 `preview` command，
    resolver 现在也会优先按这条 preview command 自动合成对应的 `--write` 命令。
  - 反过来，如果同一条 chain 里已经有可执行的 `write` command，
    但 `preview` 缺失，
    resolver 现在也会优先通过去掉尾部 `--write` 来补回 preview command。
  - 如果调用方把带 `--write` 的命令误塞进了 `preview` step，
    resolver 现在也会优先把它规范化回 dry-run preview 形式，再继续推导后续 write。
  - `summarize_patch_command_chain(...)` 这层原始 step builder 现在也会做同样的 preview/write command 规范化，
    避免 raw command chain 一开始就带着 side-effecting preview 或缺失 `--write` 的 write 形式流入后续 surface。
  - `summarize_patch_follow_up_command(...)` 现在也会先对 preview/write-like 输入做同样的规范化，
    避免 `recommended_bundle_follow_up_command` 暴露出：
    - `... --write --write`
    - 或缺失 `--write` 的 malformed write follow-up
  - 对于低风险的 `safe_to_write_then_verify` 场景，
    如果 `verify` command 暂时缺失，
    follow-up 现在会直接回落成 `none`，
    command chain 也不会再错误从 `write` 直接跳到 `gate`。
  - `summarize_patch_next_action_command(...)` 现在也会先对 preview/write-like 输入做同样的规范化，
    避免 `recommended_bundle_next_action_command` 暴露出：
    - side-effecting preview command
    - 或缺失 `--write` 的 malformed write next action
  - 对于低风险的 `safe_to_write_then_verify` 场景，
    如果 `write` command 缺失，但 `preview` command 已知，
    next action 现在也会直接按 preview command 合成对应的 `... --write`。
  - 如果 preview command 缺失，但已经有一条真实的 `write ... --write` 命令，
    next action 现在也会优先通过去掉尾部 `--write` 来补回 preview command，
    同时继续保留“不要从 malformed write 单独反推 preview”的边界。
  - 如果 raw chain 已经显式声明了 `preview` / `write` 这两个 step kind，
    但只给了其中一边的 command，
    builder 现在也会优先按同样的 preview<->write 规则补齐另一边。
  - `resolve_command_chain_artifacts(...)` 现在也会继续对显式传入的 raw `write` command 做同样的 `--write` 规范化，
    避免 builder 外部直接传入的 malformed write 形式漏过这层收口。
  - 如果同一条 chain 里同时存在 `preview` 和 malformed `write` item，
    resolver 现在也会先把这条 `write` command 规范化，
    避免 preview step 继续广告一个缺失 `--write` 的 follow-up command。
  - 这条反向补全只会在 `write` command 本身确实带有尾部 `--write` 时触发，
    避免把一个格式不完整的 write command 误当成可安全回推的 preview。
  - 反过来，如果某个已知 step 当前没有可安全推导的默认 command（例如缺少 target 上下文的 `preview` / `write`），
    resolver 不会再把它错误标成 `ready_now/proceed_now`，而会保留为非 runnable 状态。
  - 这类 non-runnable step 现在也不会继续广告下游 follow-up command；
    `step_ready_follow_up_*` 会被清空，并把 `step_ready_terminal_outcome` 回落到当前 step 自己的 success criterion。
  - `artifact_ready_for_step` 用于直接表达：
    - 当前这个 artifact 是否已经 ready 到可以支撑这一 step 的判断或执行
  - `step_ready_summary` 用于把上述 readiness 信息继续压缩成：
    - `ready_now`
    - `blocked_by_bundle_write`
    - `blocked_by_eval_rerun`
    - `blocked_by_gate_rerun`
  - `step_ready_recommended_action` 用于继续给出：
    - `proceed_now`
    - `run_bundle_write`
    - `rerun_evaluate`
    - `rerun_release_gate`
  - `step_ready_action_command` 用于把上述动作继续落成：
    - 当前最应执行的那条具体命令
  - `step_ready_follow_up_command` 用于补充：
    - 执行完当前 readiness action 之后，下一条最自然的命令
    - 当前这层语义会按真实下一步流程保留：
      - `preview -> write`
      - `write -> verify`
      - `verify -> gate`
    - 因此 preview 的 follow-up signal / success criterion 现在也对应 write：
      - `config_patch_applied`
      - `ready_for_eval_rerun`
  - `step_ready_follow_up_expected_signal` 用于补充：
    - 执行完 follow-up command 之后最值得观察的信号
  - `step_ready_follow_up_success_criterion` 用于补充：
    - 看到什么结果，才算 follow-up command 已经完成且可以继续往下
  - `step_ready_terminal_outcome` 用于补充：
    - 这一整小段 readiness action + follow-up 完成后，最终应落到哪个 operator outcome
  - `step_ready_stage_span` 用于继续压缩成更高层阶段：
    - `preview_then_split`
    - `write_then_evaluate`
    - `evaluate_then_gate`
    - `gate_only`
  - `step_ready_priority` 用于继续表达 operator 排序层级：
    - `now`
    - `next`
    - `later`
  - `step_ready_badge` 用于把阶段和优先级再压成更适合前端直接渲染的小标签：
    - `now-preview-then-split`
    - `now-write-then-evaluate`
    - `next-evaluate-then-gate`
    - `later-gate-only`
  - `step_ready_group_id` 用于补充一个更稳定的分组 key：
    - `preview-and-split`
    - `bundle-write-and-evaluate`
    - `evaluate-and-gate`
    - `gate-rerun-only`
  - `step_ready_group_label` 用于补充一个更适合直接展示的分组名称：
    - `Preview and split`
    - `Bundle write and evaluate`
    - `Evaluate and gate`
    - `Gate rerun only`
  - `step_ready_sort_key` 用于补充一个更适合前端直接排序的 key：
    - `0-preview-then-split`
    - `1-write-then-evaluate`
    - `2-evaluate-then-gate`
    - `3-gate-only`
  - `step_ready_display_order` 用于补充一个更直接的数值排序位：
    - `0`
    - `1`
    - `2`
    - `3`
  - `step_ready_lane` 用于继续把这些排序层级压成更适合 UI 分栏的字段：
    - `current`
    - `upcoming`
    - `deferred`
  - `step_ready_lane_label` 用于补充一个更适合直接展示给 operator 的 lane 名称：
    - `Current`
    - `Upcoming`
    - `Deferred`
  - 即使某个 step 当前没有可解析的 `artifact` 路径，
    这套 `follow_up` / `stage_span` / `priority` / `lane` 语义仍会尽量按 step kind 继续保留，
    避免 operator surface 因 artifact 缺位而丢掉整段 playbook 结构。
  - 对于这类 `artifact` 缺位、但 `step kind` 本身明确的步骤：
    - `preview` / `write` 会继续走 command-driven 语义：
      - `step_ready_summary = "ready_now"`
      - `step_ready_recommended_action = "proceed_now"`
      - `step_ready_action_command = 当前 step 自己的 command`
    - `verify` / `gate` 若缺少各自 report artifact，则仍然会继续保留 rerun-blocked 语义：
      - `blocked_by_eval_rerun`
      - `blocked_by_gate_rerun`
  - 对于 `preview` / `write` 这类配置步骤，即使 `datas/avm/config.json` 当前不存在，
    readiness 现在也会继续视为可直接执行：
    - `preview` 会基于默认 AVM 配置做 dry-run
    - `write` 会在需要时直接创建配置文件
  - 即使这条 `datas/avm/config.json` 是 resolver 按 known step defaults 自动补出来的，
    这类缺文件场景现在也会继续统一归到：
    - `artifact_freshness = pending_write`
    - `artifact_state_reason = config_not_written_yet`
- `calibration_patch_preview`
  - 用于快速表达当前 `config_patch` 是否还会真实改动本地配置
  - 并会补充：
    - `changed_paths`
    - `rollback_patch`
  - 对于真正带 `config_patch` 的参数型 target，`suggested_commands`
    现在通常会优先包含：
    - `python tools/apply_avm_calibration_patch.py --target-type <target_type> --target-name <target_name>`
    - `python tools/apply_avm_calibration_patch.py --target-type <target_type> --target-name <target_name> --write`
  - 如果只想预览或应用当前 top target 对应的那一小部分 patch，
    可以直接复用 `top_calibration_target_hint.suggested_commands` 里的
    `--target-type` / `--target-name` 过滤参数
  - `--target-type` / `--target-name` 现在都支持重复传入，
    因此也可以预览/应用一个小的 target bundle，而不必一次性吃完整份 patch
- `coordinate_strategy_watchlist`
  - 用于快速标记：
    - 哪类 `community_centroid` / `district_centroid` / `missing`
      样本正在显著拉高误差
- `coordinate_strategy_counts`
  - 用于补充当前数据集里这些样本到底占多少
- `active_risk_discount_factor`
  - 用于表达当前风险修正主链正在使用的全局折价强度

---

## 2) 批量筛选接口

- **Method**: `POST`
- **Path**: `/api/avm/screen`
- **用途**: 批量评估候选标的，按安全垫（margin）降序返回结果。

### 请求体

```json
{
  "margin_threshold": 0.15,
  "items": [
    {"id": "4873096974090"},
    {"id": "8547959975724", "starting_price": 12000000}
  ]
}
```

- `items` 支持两种输入：
  1. `{"id": "xxx"}` 对象（可覆盖补充字段）
  2. 纯 ID 字符串列表（例如 `"4873096974090"`）

### 返回示例

```json
{
  "margin_formula": "(predicted_price - starting_price) / predicted_price",
  "margin_threshold": 0.15,
  "total": 2,
  "alerts_written": 1,
  "results": [
    {
      "id": "4873096974090",
      "predicted_price": 25522250.0,
      "starting_price": 17865575.0,
      "margin": 0.300000019590589,
      "is_malignant_risk": false,
      "major_risks": [],
      "risk_summary": "未发现恶性风控标签",
      "risk_validation": {
        "ok": true,
        "missing_required_count": 0,
        "invalid_field_count": 0,
        "feature_completeness": 1.0
      },
      "manual_review_recommended": false,
      "manual_review_reasons": [],
      "meets_alert_threshold": true,
      "alert_blockers": []
    }
  ]
}
```

### 告警资格补充说明

`/api/avm/screen` 现在不仅要求：

- `margin >= margin_threshold`
- 无恶性风险

还会继续要求：

- 不处于 `manual_review_required`
- `risk_validation` 必须通过

如果未满足，会在结果中通过 `alert_blockers` 解释原因，例如：

- `manual_review_required`
- `risk_validation_incomplete`
- `risk_validation_invalid`

同时，screen 结果顶层也会直接补充：

- `risk_validation`
- `manual_review_recommended`
- `manual_review_reasons`

这样消费方不需要再深入 `prediction` 嵌套结构才能判断一条候选是否可靠。

`summary` 中现在也会补充：

- `blocked_reason_counts`

用于快速查看一批候选里，哪些 blocker 最常见。

---

## 2.5) 在线估值接口

- **Method**: `POST`
- **Path**: `/api/avm/evaluate`
- **Alias**: `/api/analysis/evaluate`
- **用途**: 对单个 subject 做在线估值，并返回风险修正、manual review 建议、以及估值 trace。

### 请求体补充约定

`/api/avm/evaluate` 现在支持可选的估值模式：

```json
{
  "request_id": "req-1",
  "subject": {
    "city": "上海市",
    "district": "浦东新区",
    "area_sqm": 89.2
  },
  "auction": {
    "starting_price": 4180000,
    "auction_date": "2026-03-20"
  },
  "options": {
    "valuation_mode": "current_market"
  }
}
```

允许值：

- `current_market`
  - 在线默认模式
  - 目标语义是“今天看，这套资产当前大概值多少”
- `historical_strict`
  - 历史严格模式
  - 会剔除晚于标的时间的 future comparables，避免历史回测泄漏

### 响应补充字段

`trace` 现在会显式暴露：

- `valuation_mode`
- `temporal_reference_mode`
- `temporal_target_date`
- `future_dated_comparable_count_excluded`
- `spatial_radius_km`
- `weighting_distance_power`
- `weighting_time_decay`
- `weighting_community_boost`

并新增：

- `risk_validation`
  - `ok`
  - `missing_required_count`
  - `invalid_field_count`
  - `feature_completeness`

---

## 3) 安全垫计算口径

```
margin = (predicted_price - starting_price) / predicted_price
```

- `predicted_price <= 0` 或价格字段缺失时，`margin = null`。
- 批量结果按 `margin` 从高到低排序。

---

## 4) 恶性风控判定与高优告警

### 恶性风控字段（任一为真即判定恶性）

- `is_haunted`
- `is_occupied`
- `has_long_lease`
- `is_fractional_share`
- `tax_is_company_owned`
- 或 `clear_delivery == false`
- 或 `land_right_type == "划拨"`

### 高优候选入库规则

满足以下条件写入 `datas/avm/alerts.json`：

1. `margin >= margin_threshold`（默认 `0.15`）
2. `is_malignant_risk == false`

写入内容包含：
- 估值与价格字段
- `margin`
- 风险摘要
- `created_at`
- `margin_threshold`

---

## 5) 字段定义（前端/脚本直接使用）

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | string | 标的 ID |
| `predicted_price` | number\|null | 估值结果（元） |
| `starting_price` | number\|null | 起拍价（元） |
| `margin` | number\|null | 安全垫比率 |
| `is_malignant_risk` | boolean | 是否命中恶性风控 |
| `major_risks` | string[] | 风险列表（可直接渲染） |
| `risk_summary` | string | 风险摘要（可直接展示） |
| `meets_alert_threshold` | boolean | 仅在 `/api/avm/screen` 结果中提供 |

---

## 6) Manual Review Receipt Control Plane

- **GET** `/api/avm/manual_review_receipts`
- **GET** `/api/analysis/manual_review_receipts`
- **POST** `/api/avm/manual_review_receipts`
- **POST** `/api/analysis/manual_review_receipts`
- **DELETE** `/api/avm/manual_review_receipts`
- **DELETE** `/api/analysis/manual_review_receipts`
- **GET** `/api/avm/manual_review_receipt_jobs`
- **GET** `/api/analysis/manual_review_receipt_jobs`
- **GET** `/api/avm/manual_review_receipt_operations`
- **GET** `/api/analysis/manual_review_receipt_operations`
- **GET** `/api/avm/manual_review_control_plane_status`
- **GET** `/api/analysis/manual_review_control_plane_status`
- **GET** `/api/avm/manual_review_control_plane_backup_repairs`
- **GET** `/api/analysis/manual_review_control_plane_backup_repairs`
- **GET** `/api/avm/manual_review_control_plane_integrity_history`
- **GET** `/api/analysis/manual_review_control_plane_integrity_history`

> 如果环境变量 `FAPAI_CONTROL_PLANE_TOKEN` 已配置，则所有 **POST / DELETE** receipt 变更请求都必须携带请求头：
>
> `X-FAPAI-Control-Token: <token>`
>
> 当 repository / DB 已启用时，这套 control-plane 状态会优先持久化到数据库；repository disabled 时回退到本地 JSON / JSONL 文件。
>
> 当前没有单独的 HTTP 导出接口；如果需要把 repository-backed 当前状态导出成 JSON 备份，请使用：
>
> `python tools/export_manual_review_control_plane_to_json.py --data-root datas --db-url "<your-db-url>"`
>
> 另外，repository-backed 的 receipt CRUD、operation append、async job enqueue / completion 也会自动刷新这三份 JSON / JSONL 备份文件。
>
> 所有 control-plane 相关读接口现在还会补充：
>
> - `manual_review_control_plane_storage`
> - `manual_review_control_plane_backup`
> - `manual_review_control_plane_backup_repairs_summary`
> - `manual_review_control_plane_integrity`
> - `manual_review_control_plane_stability`
> - `manual_review_control_plane_guidance`
>
> 其中 `manual_review_control_plane_backup.backup_state` 用于表达当前 warm JSON backup 的状态：
>
> - `runtime_json`
> - `in_sync`
> - `missing_backup`
> - `count_mismatch`
>
> `manual_review_control_plane_backup.backup_reason` 用于解释当前状态是如何得到的，例如：
>
> - `repository_disabled`
> - `already_in_sync`
> - `repaired_missing_backup`
> - `repaired_count_mismatch`
>
> `manual_review_control_plane_backup_repairs_summary` 用于表达这种自动修复是否已经发生过多次，例如：
>
> - `repair_count`
> - `last_repair_at`
> - `last_repair_reason`
> - `top_repair_reason`
>
> `manual_review_control_plane_integrity` 用于把这些低层信号收口成一个更直接的 operator 判断，例如：
>
> - `healthy_json_runtime`
> - `healthy_repository`
> - `repaired_recently`
> - `degraded_missing_backup`
> - `degraded_count_mismatch`
>
> `manual_review_control_plane_stability` 则在 integrity 之上再给一个更偏运行态的归类，例如：
>
> - `stable_json_runtime`
> - `stable_repository`
> - `watch_repaired_repository`
> - `unstable_repository`
>
> `manual_review_control_plane_guidance` 会进一步把这些状态翻译成 operator 更可执行的建议，例如：
>
> - `no_action_required`
> - `monitor_recent_repair`
> - `repair_backup_immediately`
> - `investigate_backup_mismatch`

### 6.8 GET integrity history

用途：
- 查看 control-plane 高层完整性状态的历史转换，而不只是看当前这一帧

支持 query 参数：
- `limit`（默认 `50`）

示例：

```json
{
  "transition_count": 2,
  "history": [
    {
      "integrity_status": "repaired_recently",
      "recorded_at": "2026-05-15 12:05:00"
    },
    {
      "integrity_status": "healthy_json_runtime",
      "recorded_at": "2026-05-15 12:00:00"
    }
  ],
  "manual_review_control_plane_integrity_history_summary": {
    "transition_count": 2,
    "last_integrity_status": "repaired_recently"
  }
}
```

适用场景：
- operator 想看 control-plane 是什么时候从 healthy 进入 repaired/degraded 的
- 需要确认这种变化是不是偶发一次还是多次切换

### 6.1 GET

用途：
- 读取当前原始 receipt 列表

返回示例：

```json
{
  "receipt_count": 1,
  "receipts": [
    {
      "action": "manual_location_review",
      "ready_signal": "location_artifacts_complete",
      "status": "ready_for_reentry",
      "payload": {
        "full_address": "上海市浦东新区测试路 1 号",
        "community_name": "测试小区",
        "business_area": "陆家嘴",
        "latitude": 31.2,
        "longitude": 121.5
      },
      "updated_at": "2026-05-14 20:00:00",
      "source": "operator_api"
    }
  ]
}
```

### 6.2 POST

用途：
- 新建或覆盖更新一条 receipt

请求示例：

```json
{
  "action": "manual_location_review",
  "ready_signal": "location_artifacts_complete",
  "status": "ready_for_reentry",
  "payload": {
    "full_address": "上海市浦东新区测试路 1 号",
    "community_name": "测试小区",
    "business_area": "陆家嘴",
    "latitude": 31.2,
    "longitude": 121.5
  },
  "resolution_notes": "已人工核对地址与坐标",
  "source": "operator_api",
  "mode": "sync"
}
```

说明：
- `action + ready_signal` 作为唯一键
- 同键再次提交时会覆盖旧 receipt
- `mode` 支持：
  - `sync`：提交后同步触发一轮 maintenance
  - `async`：提交后创建后台 maintenance job，异步执行恢复链

返回示例：

```json
{
  "status": "ok",
  "operation": "created",
  "execution_mode": "async",
  "maintenance_triggered": true,
  "maintenance_job_id": "job-123",
  "maintenance_job_status": "queued",
  "receipt": {
    "action": "manual_location_review",
    "ready_signal": "location_artifacts_complete",
    "status": "ready_for_reentry",
    "payload": {
      "full_address": "上海市浦东新区测试路 1 号"
    },
    "updated_at": "2026-05-14 20:00:00"
  },
  "manual_review_receipt_summary": {
    "top_receipt_status": "ready_for_reentry"
  },
  "operator_overview": {
    "handoff_lifecycle_state": "receipt_ready_for_reentry"
  },
  "manual_review_receipt_jobs_summary": {
    "queued_count": 1,
    "running_count": 0,
    "failed_count": 0,
    "last_job_status": "queued"
  }
}
```

### 6.3 DELETE

用途：
- 删除指定 `action + ready_signal` 的 receipt

请求示例：

```json
{
  "action": "manual_location_review",
  "ready_signal": "location_artifacts_complete"
}
```

返回示例：

```json
{
  "status": "ok",
  "deleted": true,
  "receipt_count": 0,
  "manual_review_receipt_summary": {
    "receipt_count": 0
  },
  "operator_overview": {
    "handoff_lifecycle_state": "awaiting_human_receipt_hard_stop"
  }
}
```

### 6.4 GET jobs

用途：
- 查看异步 maintenance job 队列与执行结果

示例：

```json
{
  "job_count": 1,
  "jobs": [
    {
      "job_id": "job-123",
      "status": "completed",
      "receipt_key": {
        "action": "manual_location_review",
        "ready_signal": "location_artifacts_complete"
      },
      "created_at": "2026-05-14 20:00:00",
      "started_at": "2026-05-14 20:00:01",
      "finished_at": "2026-05-14 20:00:04",
      "result_summary": {
        "generated_at": "2026-05-14 20:00:04",
        "reentry_applied": true,
        "reentry_confirmed": false,
        "handoff_lifecycle_state": "reentry_applied"
      }
    }
  ],
  "running_job": null,
  "queued_jobs": []
}
```

按 `job_id` 查询单个任务时：

- 请求：`GET /api/avm/manual_review_receipt_jobs?job_id=<job_id>`
- 返回会额外带：
  - `job`
  - `manual_review_receipt_summary`
  - `operator_overview`

### 6.5 GET operations

用途：
- 读取 manual review receipt 的操作审计历史

支持 query 参数：
- `action`
- `ready_signal`
- `limit`（默认 `50`）

示例：

```json
{
  "operation_count": 3,
  "operations": [
    {
      "operation_id": "op-3",
      "operation": "deleted",
      "action": "manual_location_review",
      "ready_signal": "location_artifacts_complete",
      "status": "",
      "payload_fingerprint": "sha256...",
      "execution_mode": "delete",
      "requested_at": "2026-05-14 20:10:00",
      "deleted": true
    },
    {
      "operation_id": "op-2",
      "operation": "updated",
      "action": "manual_location_review",
      "ready_signal": "location_artifacts_complete",
      "status": "ready_for_reentry",
      "payload_fingerprint": "sha256...",
      "execution_mode": "sync",
      "requested_at": "2026-05-14 20:05:00"
    }
  ],
  "applied_filters": {
    "action": "manual_location_review",
    "ready_signal": "location_artifacts_complete",
    "limit": 50
  }
}
```

### 6.6 GET control-plane status

用途：
- 在一个单独接口里直接查看 control-plane 当前后端模式与 warm backup 健康状态
- 不需要再去翻大块 `/api/status` 或 release gate payload

示例：

```json
{
  "manual_review_receipt_summary": {
    "receipt_count": 1
  },
  "manual_review_receipt_jobs_summary": {
    "queued_count": 0,
    "running_count": 0
  },
  "manual_review_receipt_operations_summary": {
    "operation_count": 3
  },
  "manual_review_control_plane_storage": {
    "repository_enabled": true,
    "state_source": "repository",
    "bootstrap_reason": "repository_not_empty"
  },
  "manual_review_control_plane_backup": {
    "backup_state": "in_sync",
    "backup_reason": "already_in_sync"
  },
  "manual_review_control_plane_backup_repairs_summary": {
    "repair_count": 1,
    "last_repair_reason": "repaired_missing_backup"
  }
}
```

适用场景：
- operator 想快速确认当前 control-plane 是从 DB 还是 JSON 读取
- 运维想确认 warm JSON backup 是否存在、是否同步、是否刚被自动修复
- 需要区分：
  - `backup_reason = already_in_sync`
  - 还是 `backup_reason = repaired_missing_backup / repaired_count_mismatch`
- 想看这种自动修复是不是偶发一次，还是已经发生过多次

### 6.7 GET backup repairs history

用途：
- 读取完整的 backup self-healing 历史，而不是只看 summary

支持 query 参数：
- `limit`（默认 `50`）

示例：

```json
{
  "repair_count": 1,
  "repairs": [
    {
      "repair_id": "repair-1",
      "reason": "repaired_missing_backup",
      "repaired_at": "2026-05-15 12:00:00"
    }
  ],
  "applied_filters": {
    "limit": 50
  },
  "manual_review_control_plane_backup_repairs_summary": {
    "repair_count": 1,
    "last_repair_reason": "repaired_missing_backup"
  }
}
```

适用场景：
- operator 想确认 backup self-healing 是否在反复发生
- 需要比 summary 更细的历史排查证据

