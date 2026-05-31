# AVM 运行手册（Runbook）

本文档给出 AVM（法拍房时空估价引擎）在工程落地中的标准流程：**构建、评估、上线、回滚**，并附上 API 请求与响应样例，便于开发、测试、运维协同。

## 1. 构建（Build）

### 1.1 输入与前置条件
- 已完成原始采集数据入库（Raw 层）。
- 已按 `docs/analysis/final-collection-contract.md` 与 `docs/analysis/final-collection-template.json` 完成字段映射到 Canonical 层。
- 训练/评估环境具备 Python 依赖（见项目根目录 `requirements.txt`）。

### 1.2 标准步骤
1. 数据抽取：从 Canonical 层拉取训练/验证时间窗样本。
2. 数据清洗：
   - 去除缺少关键字段（成交价、面积、坐标）的记录；
   - 对面积、价格、坐标做范围与单位校验；
   - 对风险标签做枚举归一化。
3. 特征构建：
   - 空间特征：3km 邻域、IDW 距离衰减权重；
   - 时间特征：板块趋势因子、时间衰减因子；
   - 属性特征：面积、楼层、装修、风险标签修正项。
4. 模型训练：
   - 主模型：时空估值模型；
   - 辅助规则：风控标签估值修正规则。
5. 模型打包：
   - 产出模型文件（`model.bin` 或等价格式）；
   - 产出版本元信息（`model_version`、训练窗口、特征版本）。

补充说明：
- 当前离线 AVM pipeline 已支持继续产出：
  - `eval_report.json`
  - `calibration_targets.json`
  - `release_gate.json`
- 因此一次完整离线流程不再只是“出预测和 alert”，还会顺带产出后续调参证据。

### 1.3 构建产物
- 模型文件（含可加载参数）。
- 特征字典版本。
- 训练摘要报告（样本量、特征覆盖、异常样本数）。

---

## 2. 评估（Evaluate）

### 2.1 评估维度
- **精度指标**：MAE、MAPE、P50/P90 误差。
- **鲁棒性指标**：各行政区/商圈分组误差是否稳定。
- **风险一致性**：高风险标签样本是否呈现预期折价。
- **可解释性**：输出是否包含可追溯因子（邻域样本、趋势修正、风险修正）。

### 2.2 评估门禁（建议）
- 整体 MAPE <= 12%。
- 任一核心区域 MAPE 不得劣化超过基线 +3%。
- 高风险样本估值方向正确率 >= 95%。

### 2.3 回归检查清单
- 同一输入多次评估结果波动在允许范围内。
- 边界样本（超大面积、坐标边界、稀疏商圈）无崩溃。
- 缺失可选字段时服务降级而非报错。

---

## 3. 上线（Deploy）

### 3.1 上线策略
- 优先使用 **灰度发布**（按流量比例或按城市分流）。
- 保留上一个稳定模型版本（N-1）可随时切换。
- 上线需绑定监控看板与报警阈值。

### 3.2 上线流程
1. 预发环境部署新模型版本（N）。
2. 执行冒烟：
   - 健康检查；
   - 核心 API 响应时间与返回结构校验；
   - 关键样本估值对齐基线。
3. 小流量灰度（5% -> 20% -> 50% -> 100%）。
4. 每个阶段观察：
   - 错误率、P95 延迟；
   - 估值偏移监控；
   - 风险标签分布漂移。

### 3.3 监控与告警
- 服务层：5xx 比例、超时率、吞吐量。
- 模型层：在线 MAPE 近似代理指标、估值漂移。
- 数据层：输入字段缺失率、异常坐标占比。

---

## 4. 回滚（Rollback）

### 4.1 回滚触发条件（任一满足即触发）
- 错误率或超时率超过阈值并持续 5~10 分钟。
- 线上估值相对基线出现异常偏移（如中位偏差 > 8%）。
- 关键城市/商圈出现明显系统性高估或低估。

### 4.2 回滚步骤
1. 立即切流至稳定版本（N-1）。
2. 冻结当前发布批次，停止继续放量。
3. 导出故障窗口样本（请求入参与输出）用于复盘。
4. 发布事故通报：影响范围、持续时间、应急动作。
5. 完成根因分析（数据/特征/模型/服务）后再发起重试上线。

### 4.3 回滚后验证
- 健康检查恢复正常。
- 核心城市估值回到基线区间。
- 告警恢复到可接受水平并稳定 30 分钟以上。

---

## 5. API 请求与响应样例

> 说明：以下为 AVM 对外接口的**建议契约样例**，用于联调与文档规范。

### 5.1 估值接口 `POST /api/avm/evaluate`

别名：
- `POST /api/analysis/evaluate`

#### 请求示例
```bash
curl -X POST "http://127.0.0.1:8001/api/avm/evaluate" \
  -H "Content-Type: application/json" \
  -d '{
    "request_id": "req_20260312_0001",
    "subject": {
      "city": "shanghai",
      "district": "pudong",
      "latitude": 31.224361,
      "longitude": 121.544346,
      "area_sqm": 89.2,
      "floor": "12/18",
      "build_year": 2014
    },
    "auction": {
      "starting_price": 4180000,
      "deposit": 400000,
      "auction_date": "2026-03-20"
    },
    "risk_flags": {
      "has_long_lease": false,
      "is_occupied": true,
      "has_property_fee_arrears": true
    },
    "options": {
      "valuation_mode": "current_market"
    }
  }'
```

说明：
- `current_market` 是在线默认模式，估值语义偏“今天的公允价”。
- `historical_strict` 用于历史严格回测，会剔除晚于标的时间的 future comparables。

#### 响应示例
```json
{
  "request_id": "req_20260312_0001",
  "model_version": "avm_st_v0.9.3",
  "valuation": {
    "estimated_fair_price": 4625000,
    "estimated_unit_price": 51850,
    "price_confidence": 0.84,
    "confidence_interval": {
      "p10": 4410000,
      "p90": 4850000
    }
  },
  "margin_of_safety": {
    "amount": 445000,
    "ratio": 0.0962,
    "level": "MEDIUM"
  },
  "risk_adjustments": [
    {
      "tag": "is_occupied",
      "impact": -0.035,
      "description": "存在占用，流拍与处置周期风险上升"
    },
    {
      "tag": "has_property_fee_arrears",
      "impact": -0.012,
      "description": "潜在欠费影响实际支付总价"
    }
  ],
  "risk_validation": {
    "ok": false,
    "missing_required_count": 8,
    "invalid_field_count": 0,
    "feature_completeness": 0.65
  },
  "trace": {
    "neighbor_sample_count": 126,
    "strategy": "spatial",
    "valuation_mode": "current_market",
    "temporal_reference_mode": "current_time",
    "temporal_target_date": "2026-05-15 09:30:00",
    "future_dated_comparable_count_excluded": 0
  }
}
```

补充说明：
- `risk_validation` 是非阻断信号，不会因为风险字段缺失就拒绝估值，但会降低 confidence，并推动 manual review。
- 如果需要做真正的历史回测，请优先使用 `tools/evaluate_avm.py`，它默认走 `historical_strict` 语义。
- 当前评估报告里，`historical_strict` 仍是主门禁语义；`current_market` 作为参考模式同时输出，便于对比“历史严格回测结果”和“当前市场估值语义”的偏差。
- 当前评估报告也会输出 cohort-aware 诊断，例如：
  - `valuation_mode_metrics`
  - `strategy_metrics`
  - `coordinate_strategy_metrics`
  - `risk_validation_metrics`
  - `risk_flag_metrics`
- 离线回测现在也会在进入 `predict_fair_price(...)` 前，按和在线服务一致的 centroid 逻辑尝试补齐 subject 坐标；
  因此 `coordinate_strategy_metrics` 不再只是“标签统计”，而更接近真实 runtime 行为。
- release gate 的 `evaluation` 段现在还会给出 `calibration_targets`，用于提示：
  - 哪个风险标签最值得先校准
  - 是否已经出现适合优先调整全局 `risk_discount_factor` 的系统性风险偏差
  - 哪个 strategy 更像样本覆盖问题
  - 时间趋势的 `time_decay` 是否值得收紧/放松
  - 对于风险标签，还会附带保守的：
    - `suggested_factor_step_pct`
    - `suggested_next_factor`
    作为下一轮手工调参起点，而不是直接自动改权重。
  - 对于 temporal target，则会附带：
    - `suggested_action`
    - `suggested_factor_step_pct`
    - `suggested_next_value`
    并通过 `config_patch.weighting.time_decay` 给出建议配置草案。
- `/api/avm/release_gate` / `/api/analysis/release_gate` 现在除了原始 gate report 外，
  也会继续把这段 calibration context flatten 成 operator-facing 摘要字段，例如：
  - `calibration_guidance`
  - `calibration_target_counts`
  - `top_calibration_target`
  - `top_calibration_target_hint`
  - `recommended_bundle_*`
  - `coordinate_strategy_watchlist`
  - `top_coordinate_strategy_group`
  这样消费方不需要自己再从 `evaluation.calibration_targets` 里做二次整理。
  - 这层 flatten 摘要现在也会优先跟随**当前请求刚生成出来的 gate report**，
    而不是依赖请求前遗留在磁盘上的旧 `release_gate.json`。
- `calibration_targets` 现在还会附带一个高层 `guidance`：
  - `tune_risk_factors`
  - `tune_temporal_decay`
  - `improve_candidate_coverage`
  - `review_weighting_and_filters`
  - `fix_coordinate_quality`
  - `fix_risk_data_quality`
  - `no_action_required`
  用于帮助 operator 先区分“这是参数问题、坐标质量问题、覆盖问题，还是输入质量问题”。
- `run_avm_pipeline.py` 的离线 calibration / gate stage summary 现在也会直接暴露：
  - `has_recommendations`
  - `global_risk_target_count`
  - `risk_factor_target_count`
  - `temporal_target_count`
  - `strategy_target_count`
  - `guidance_status`
  - `coordinate_strategy_watchlist`
  - `top_coordinate_strategy_group`
  - `top_target_name`
  - `top_target_hint_status`
  - `top_target_playbook_id`
  - `recommended_bundle_id`
  - `recommended_bundle_changed_key_count`
  - `recommended_bundle_primary_change`
  - `recommended_bundle_secondary_changes`
  - `recommended_bundle_preview_command`
  - `recommended_bundle_write_command`
  - `recommended_bundle_verify_command`
  - `recommended_bundle_gate_command`
  便于在不打开完整 JSON 报告的情况下，先看这一轮更像哪类问题。
  - 如果 `suggested_bundle_commands` 当前只显式给了 preview command，
    这层 offline / HTTP summary 里的 `recommended_bundle_write_command`
    现在也会继续按该 preview command 自动补成对应的 `... --write`。
  - 反过来，如果 `suggested_bundle_commands` 当前只显式给了 bona fide `write ... --write`，
    这层 offline / HTTP summary 里的 `recommended_bundle_preview_command`
    现在也会继续通过去掉尾部 `--write` 自动补回 preview command。
  - 如果 `recommended_bundle` 本身已经给出了 `target_types` / `target_names`，
    但 `suggested_bundle_commands` 整段缺失，
    这层 offline / HTTP summary 现在也会直接按这组 target filter
    自动合成 canonical preview / write commands。
- 如果要在不改源码的情况下试调风险折价/溢价系数，现在可以在：
  - `datas/avm/config.json`
  中提供可选的 `risk_factor_overrides`。
- 当前还新增了一个正式的 calibration patch applier：
  - `python tools/apply_avm_calibration_patch.py`
  - 默认 dry-run 预览 `calibration_targets.json -> config_patch -> merged_config`
  - 如只想应用某一类或某一个 calibration target，
    现在还支持：
    - `--target-type temporal|global_risk|risk_flag`
    - `--target-name <target_name>`
  - 这两个参数都可以重复传入，
    因此也支持只对一小组 target bundle 做 preview / apply
  - 当前还会输出：
    - `changed_paths`
    - `rollback_patch`
  - 如需真正写回 `datas/avm/config.json`，再显式加：
    - `--write`
- 当前同一份配置还会继续影响：
  - engine 的 `radius_km`
  - engine 的 `weighting.distance_power`
  - shared temporal 的 `weighting.time_decay`
  - engine 的 `weighting.community_boost`
  - engine 的 `risk_discount_factor`
  - `screen` / `generate_avm_alerts` 的默认 `alert_threshold`
- 当前数值语义补充：
  - `alert_threshold` 允许配置为 `0.0`，表示只要 margin 为正且未被其它 blocker 挡住，就可以进入 alert 候选
  - `weighting.time_decay` 会按有效运行态收敛到 `0.0 ~ 1.0` 区间
  - `risk_discount_factor`
    以当前默认 `0.9` 为中性基线；低于它会整体减弱风险/正向修正强度，高于它会整体增强
- 其中：
  - `distance_power` / `community_boost` 已进入当前空间权重主链
  - `time_decay` 已进入 shared temporal 主链，用于把更远时间跨度的趋势外推逐步衰减回 1.0 附近
  - `risk_discount_factor` 已进入风险修正主链，并会同时作用于：
    - 标的风险折价
    - 可比样本去风险归一化
- 当前运行态也会显式暴露这层 override 是否生效：
  - `trace.risk_factor_override_count`
  - `trace.active_risk_discount_factor`
  - `trace.weighting_distance_power`
  - `trace.weighting_time_decay`
  - `trace.weighting_community_boost`
  - `/api/avm/health` 中的 `active_risk_discount_factor`
  - `/api/avm/health` 中的 `active_risk_factor_override_count`
  - `/api/avm/health` 中的 `active_risk_factor_overrides`
  - `/api/avm/health` 中的 `active_weighting`
- `/api/avm/screen` 的高优 alert 现在也会参考这层信号：
  - 如果 `manual_review` 已被推荐
  - 或 `risk_validation` 不通过
  - 则不会被直接写入高优告警。
- 离线告警链也已对齐到同一套资格标准：
  - `tools/generate_avm_alerts.py`
  - `tools/run_avm_pipeline.py` 的 alert stage
  现在也会输出 `blocked_reason_counts`，用于解释哪些样本因为 `manual_review` / `risk_validation` 被挡在高优告警之外。

### 5.2 健康检查接口 `GET /api/avm/health`

#### 请求示例
```bash
curl "http://127.0.0.1:8001/api/avm/health"
```

#### 响应示例
```json
{
  "status": "ok",
  "service": "avm",
  "model_version": "avm_st_v0.9.3",
  "uptime_sec": 86420,
  "risk_validation_counts": {
    "ok": 1200,
    "incomplete": 340,
    "invalid": 0
  },
  "risk_feature_completeness_avg": 0.81,
  "coordinate_strategy_counts": {
    "observed": 1200,
    "community_centroid": 180,
    "district_centroid": 40,
    "missing": 12
  },
  "active_risk_discount_factor": 0.9,
  "active_weighting": {
    "distance_power": 2.0,
    "time_decay": 0.85,
    "community_boost": 1.3
  },
  "calibration_guidance": {
    "status": "fix_coordinate_quality",
    "priority": "high",
    "recommended_actions": ["review_coordinate_strategy_cohorts"],
    "top_reason": "district_centroid"
  },
  "calibration_target_counts": {
    "risk_factor": 1,
    "temporal": 1,
    "strategy": 0
  },
  "top_calibration_target": {
    "target_type": "temporal",
    "name": "time_decay"
  },
  "top_calibration_target_hint": {
    "status": "tune_temporal_decay",
    "target_type": "temporal",
    "target_name": "time_decay",
    "playbook_id": "tune-temporal-decay",
    "runbook_refs": ["tools/evaluate_avm.py"],
    "recommended_actions": ["adjust_weighting_time_decay"],
    "suggested_commands": ["python tools/evaluate_avm.py"]
  },
  "calibration_patch_preview": {
    "patch_ready": true,
    "changed_key_count": 1,
    "changed_keys": ["weighting.time_decay"],
    "changed_paths": {
      "weighting.time_decay": {"before": 0.85, "after": 0.72}
    },
    "rollback_patch": {
      "weighting": {"time_decay": 0.85}
    }
  },
  "coordinate_strategy_watchlist": ["district_centroid"],
  "top_coordinate_strategy_group": "district_centroid"
}
```

补充说明：
- `risk_validation_counts` 反映当前 AVM 特征数据集里，风险字段整体是完整、缺失，还是存在非法值。
- `risk_feature_completeness_avg` 可以作为线上数据治理质量的快速代理指标。
- `coordinate_strategy_counts` 反映当前数据集中：
  - 真实坐标
  - 各层 centroid 补齐
  - 仍然缺坐标
  的分布情况。
- `active_weighting` 反映当前 engine 正在使用的距离/同小区权重配置，便于在试调 `config.json` 后快速确认运行态是否吃到新值。
- 其中 `active_weighting.time_decay` 反映的是 runtime 真正使用的有效值；如果配置超出 `0.0 ~ 1.0`，运行态会按该区间收敛。
- `calibration_guidance` 用于直接表达这一轮更像：
  - 参数调优问题
  - 坐标质量问题
  - 风险字段质量问题
- `calibration_target_counts` / `top_calibration_target` 用于补充：
  - 当前到底有多少 global-risk / risk / temporal / strategy 调参候选
  - 以及当前最值得先看的单个 target 是谁
- 当多个风险 cohort 呈现同方向系统性偏差时，`top_calibration_target`
  现在也可能直接指向：
  - `risk_discount_factor`
  而不只是单个 `risk_factor_overrides`。
- `top_calibration_target_hint` 则进一步把这个 top target 翻译成更直接的下一步动作。
- `top_calibration_target_hint.suggested_commands` 则继续补充：
  - 当前建议优先执行的 CLI 命令族
  - 便于 operator 从状态面直接跳到下一步操作
- 当系统识别到一个更适合一起试调的小 bundle（例如 `temporal + global_risk`）时，
  `top_calibration_target_hint.suggested_bundle_commands` 还会继续补充：
  - bundle 级 preview / write 命令
  - 便于 operator 直接对一小组 target 做保守联调
- 对于真正带 `config_patch` 的参数型 target（如 `risk_factor_overrides` / `time_decay`），
  当前建议命令现在会优先包含：
  - `python tools/apply_avm_calibration_patch.py --target-type <target_type> --target-name <target_name>`
  - `python tools/apply_avm_calibration_patch.py --target-type <target_type> --target-name <target_name> --write`
  让 operator 先 preview/apply patch，再回跑评估与 gate。
- `top_calibration_target_hint.playbook_id` / `runbook_refs` 则继续补充：
  - 更稳定的 playbook 锚点
  - 便于后续把 operator 动作继续收敛成更结构化的操作入口
- `calibration_patch_preview` 则继续补充：
  - 当前 `config_patch` 是否真的还会改动本地 `config.json`
  - 以及会影响哪些配置路径
  - 以及最小回滚预览
- `top_calibration_patch_preview` 则进一步把这层 patch preview 收窄到：
  - 当前 `top_calibration_target` 对应的那一小部分 patch
  - 便于 operator 不受整份 `config_patch` 里其它候选项干扰
- `recommended_bundle_patch_preview` 则继续把这层 preview 扩到：
  - `top_calibration_target_hint.recommended_bundle`
  - 适合 operator 想先对一小组 target 做保守联调时直接查看 bundle 级 diff
- `recommended_bundle_risk_level` / `recommended_bundle_risk_reasons` 则继续补充：
  - 这组 bundle 当前更像低风险、中风险还是高风险调整
  - 用于帮助 operator 决定是否先单 target 调参，再扩大到 bundle 联调
- `recommended_bundle_next_action` / `recommended_bundle_next_action_reasons` 则继续在这层基础上表达：
  - 当前更适合先 preview
  - 还是可以直接 write 后再 verify/gate
  - 如果 preview payload 里 `changed_key_count` 暂时缺失，
    但 `changed_keys` 已知，
    当前这层 next action 也会继续按 `changed_keys` 推导，
    避免把有真实改动的 bundle 错误降成 `no_action_required`
- `recommended_bundle_next_action_command` / `recommended_bundle_next_action_command_kind` 则继续把这层建议压成：
  - 当前最值得先执行的那一条命令
  - 以及它属于 preview 还是 write 路径
- `recommended_bundle_follow_up_command` / `recommended_bundle_follow_up_command_kind` 则继续补充：
  - first command 执行后，下一条最自然的 follow-up 命令
  - 以及它更像 write 还是 verify 路径
- `recommended_bundle_command_chain` 则继续把这条两步/多步语义收成：
  - 一个更适合 UI / operator summary 直接消费的结构化命令序列
  - 如果当前 flow 还是高风险的：
    - `split_bundle_or_single_target_first`
    且还没有进入 `write` / `verify` 路径，
    当前这条链会先停在 `preview`，
    不再过早把 `verify` / `gate` 广告成紧接着的下一串命令
  - 同时这个 high-risk preview step 自己也不会再继续补出：
    - `step_ready_follow_up_command = write`
    而会把内部 follow-up 一并清空，
    保持“先 preview / 先 split，再决定是否写回”的 operator 语义
  - 当前每个 step 还会补：
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
  - 对于离线 `run_avm_pipeline.py` 的 gate stage summary，
    如果 release gate report 本身没有回填 `evaluation.calibration_targets`，
    当前也会回退读取 `datas/avm/calibration_targets.json`，
    继续补全这组 `recommended_bundle_*` contract 字段。
  - 对于离线 `run_avm_pipeline.py` 的 calibration stage summary，
    即使 `suggest_calibration_targets(...)` 只返回了一个不完整的弱输入 payload，
    只要各 target list 还在，
    当前也会继续按：
    - `global_risk_targets`
    - `risk_factor_targets`
    - `temporal_targets`
    - `strategy_targets`
    推导 `has_recommendations` 和各 target count，
    避免因为缺失顶层 `has_recommendations` / count metadata 而直接抛异常。
  - 同样的弱输入规范化现在也会继续应用到：
    - `src/avm/pipeline.py` 写出的 `calibration_targets.json`
    - release gate `evaluation.calibration_targets`
    - `src/server.py` 读取的 file-backed `calibration_targets.json`
    避免这两条 producer path 继续把缺失 target lists / guidance / `has_recommendations`
    的半成品 payload 原样暴露出去。
  - 如果 `src/server.py` 读到的 `calibration_targets.json` 虽然存在，
    但底层已经不是 JSON object（例如历史脏数据变成了 `[]`），
    当前也会继续退回到一份临时的 normalized calibration payload 做 preview / summary，
    避免 `/api/status` / `/api/avm/health` 因这类坏文件直接崩掉。
  - 如果 `src/server.py` 读到的 `datas/avm/config.json` 虽然路径存在，
    但底层已经不是 JSON object（例如历史脏数据变成了 `[]`），
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
    维持 guidance / target counts / bundle commands / patch preview 的可见性。
  - 如果 `release_gate.json.evaluation.calibration_targets` 只回填了一个稀疏片段，
    `src/server.py` 当前也会继续把这段 embedded fragment 和 file-backed
    `calibration_targets.json` 做补齐合并，
    避免 partial embedded payload 反向覆盖掉更完整的 file-backed calibration context。
  - 如果 release gate report 只回填了一个不完整的
    `evaluation.calibration_targets` 片段，
    当前也会继续与 `datas/avm/calibration_targets.json` 做补齐合并，
    避免把已有的 bundle context 错误降成 `none/no_action_required`。
  用于提示该命令执行后最值得先看的结果信号
  - `artifact_state` 当前用来表达：
    - 本地 artifact 已存在
    - 本地 artifact 缺失
    - 这一步之前本来就还不该出现
    - 本地 artifact 已存在但在当前 rerun 语义下已过期
  - `artifact_freshness` 当前用来表达：
    - 本地 artifact 当前可直接使用
    - 本地 artifact 已过期
    - 本地 artifact 还要等 write 产生
    - 本地 artifact 还要等 verify / gate rerun 产生
  - `artifact_freshness_reason` 则继续解释：
    - 是 bundle write 还没发生
    - 还是 eval / gate 还没 rerun
    - 还是当前文件属于 pre-bundle 的旧产物
  - `artifact_next_expected_transition` 则继续补充：
    - 这一步之后当前 artifact 最自然应从什么状态变成什么状态
  - `artifact_check_command` 则继续补充：
    - 如果现在要直接检查这个 artifact，对应应执行哪条命令
  - `artifact_check_timing` 则继续补充：
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
  - `artifact_ready_for_step` 则继续压缩成一个快速信号：
    - 当前 artifact 是否已经 ready 到足以支撑这一 step
  - `step_ready_summary` 则继续收口成更适合 operator 快读的状态：
    - `ready_now`
    - `blocked_by_bundle_write`
    - `blocked_by_eval_rerun`
    - `blocked_by_gate_rerun`
  - `step_ready_recommended_action` 则继续把它翻成更直接的动作：
    - `proceed_now`
    - `run_bundle_write`
    - `rerun_evaluate`
    - `rerun_release_gate`
  - `step_ready_action_command` 则继续把动作翻成：
    - 当前这一 step 最推荐直接执行的命令
  - `step_ready_follow_up_command` 则继续补充：
    - 这条 readiness action 执行后最自然的下一条命令
    - 当前这层语义会按真实下一步流程保留：
      - `preview -> write`
      - `write -> verify`
      - `verify -> gate`
    - 因此 preview 的 follow-up signal / success criterion 现在也对应 write：
      - `config_patch_applied`
      - `ready_for_eval_rerun`
  - `step_ready_follow_up_expected_signal` 则继续补充：
    - follow-up command 执行后最值得先看的结果信号
  - `step_ready_follow_up_success_criterion` 则继续补充：
    - 哪种结果算 follow-up command 已完成且可以继续下一步
  - `step_ready_terminal_outcome` 则继续补充：
    - 当前这一小段 readiness playbook 结束后应落到的最终 operator outcome
  - `step_ready_stage_span` 则继续把这段语义压成更高层阶段：
    - `preview_then_split`
    - `write_then_evaluate`
    - `evaluate_then_gate`
    - `gate_only`
  - `step_ready_priority` 则继续把这些阶段压成更适合排序的优先级：
    - `now`
    - `next`
    - `later`
  - `step_ready_badge` 则继续压成更适合前端直接渲染的小标签：
    - `now-preview-then-split`
    - `now-write-then-evaluate`
    - `next-evaluate-then-gate`
    - `later-gate-only`
  - `step_ready_group_id` 则继续补成更稳定的分组 key：
    - `preview-and-split`
    - `bundle-write-and-evaluate`
    - `evaluate-and-gate`
    - `gate-rerun-only`
  - `step_ready_group_label` 则继续补成更适合直接展示的分组名称：
    - `Preview and split`
    - `Bundle write and evaluate`
    - `Evaluate and gate`
    - `Gate rerun only`
  - `step_ready_sort_key` 则继续补成更适合前端直接排序的 key：
    - `0-preview-then-split`
    - `1-write-then-evaluate`
    - `2-evaluate-then-gate`
    - `3-gate-only`
  - `step_ready_display_order` 则继续补成更直接的数值排序位：
    - `0`
    - `1`
    - `2`
    - `3`
  - `step_ready_lane` 则继续把这些排序层级压成更适合 UI 分栏的字段：
    - `current`
    - `upcoming`
    - `deferred`
  - `step_ready_lane_label` 则继续补成更适合直接展示给 operator 的 lane 名称：
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
- 如果 operator 希望先一起处理一小组 target（例如 `temporal + global_risk`），
  现在也可以通过重复传入：
  - `--target-type`
  - `--target-name`
  来构造一个小的 patch bundle
- `coordinate_strategy_watchlist` / `top_coordinate_strategy_group` 用于快速提示：
  - 当前是不是某类 centroid / missing 坐标样本正在显著拉高误差
- `/api/status` 现在也新增了 `avm` 子对象，
  会聚合：
  - AVM service health 摘要
  - `calibration_guidance`
  - `calibration_target_counts`
  - `top_calibration_target`
  - `top_calibration_target_hint`
  - `coordinate_strategy_watchlist`
  - `top_coordinate_strategy_group`
  便于在总状态面直接看到 AVM 主链当前更像哪类问题。

---

## 6. Manual Review Receipt 提交与恢复

当 operator 需要把人工补齐结果重新交还给自动链时，统一使用 receipt control-plane。

说明：
- repository / DB enabled 时，receipt / job / operation state 会优先落数据库
- repository disabled 时，系统会回退到本地 JSON / JSONL 持久化

### 6.1 提交 receipt

推荐使用：

```bash
curl -X POST "http://127.0.0.1:8001/api/avm/manual_review_receipts" \
  -H "Content-Type: application/json" \
  -H "X-FAPAI-Control-Token: <token>" \
  -d '{
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
  }'
```

说明：
- `mode=sync`：提交后同步执行一轮 `recent_enrich_maintenance`
- `mode=async`：提交后创建后台 maintenance job，异步执行恢复链
- 重复提交同一 `action + ready_signal` 时会覆盖旧记录
- 如果环境变量 `FAPAI_CONTROL_PLANE_TOKEN` 已配置，则 `POST / DELETE` 必须带 `X-FAPAI-Control-Token`

### 6.2 查看当前 receipt

```bash
curl "http://127.0.0.1:8001/api/avm/manual_review_receipts"
```

用于确认：
- 当前 receipt 原始内容
- 是否已经被 operator 更新

### 6.3 删除错误 receipt

```bash
curl -X DELETE "http://127.0.0.1:8001/api/avm/manual_review_receipts" \
  -H "Content-Type: application/json" \
  -d '{
    "action": "manual_location_review",
    "ready_signal": "location_artifacts_complete"
  }'
```

适用场景：
- 错误提交
- 旧 receipt 已无效
- recovered item 的 stale receipt 清理

### 6.4 查看异步 job

如果使用 `mode=async`，提交后继续查询：

```bash
curl "http://127.0.0.1:8001/api/avm/manual_review_receipt_jobs"
curl "http://127.0.0.1:8001/api/avm/manual_review_receipt_jobs?job_id=<job_id>"
```

重点看：
- `status`：`queued / running / completed / failed`
- `result_summary`
- `manual_review_receipt_summary`
- `operator_overview`

### 6.5 查看 control-plane 后端状态

如果需要单独确认：
- 当前 control-plane 是从 DB 还是 JSON 读取
- warm JSON backup 是否存在、是否同步、是否刚被自动修复

直接请求：

```bash
curl "http://127.0.0.1:8001/api/avm/manual_review_control_plane_status"
```

重点看：
- `manual_review_control_plane_storage.state_source`
- `manual_review_control_plane_storage.bootstrap_reason`
- `manual_review_control_plane_backup.backup_state`
- `manual_review_control_plane_backup.backup_reason`
- `manual_review_control_plane_backup_repairs_summary.repair_count`
- `manual_review_control_plane_backup_repairs_summary.last_repair_reason`
- `manual_review_control_plane_backup_repairs_summary.top_repair_reason`
- `manual_review_control_plane_integrity.integrity_status`
- `manual_review_control_plane_integrity.attention_required`
- `manual_review_control_plane_integrity.follow_up_recommended`
- `manual_review_control_plane_stability.stability_status`
- `manual_review_control_plane_guidance.guidance_status`
- `manual_review_control_plane_guidance.priority`
- `manual_review_control_plane_guidance.recommended_actions`

这是当前最适合 operator / maintainer 快速排查 control-plane 迁移态的单一入口。

### 6.6 查看 backup repair 历史

如果需要查看完整 repair 历史而不是只看 summary，直接请求：

```bash
curl "http://127.0.0.1:8001/api/avm/manual_review_control_plane_backup_repairs"
curl "http://127.0.0.1:8001/api/avm/manual_review_control_plane_backup_repairs?limit=20"
```

重点看：
- `repair_count`
- `repairs[*].reason`
- `repairs[*].repaired_at`
- `manual_review_control_plane_backup_repairs_summary`

### 6.7 查看 integrity 历史

如果需要查看 control-plane 从 `healthy_*` 到 `repaired_recently` / `degraded_*` 的历史转换，直接请求：

```bash
curl "http://127.0.0.1:8001/api/avm/manual_review_control_plane_integrity_history"
curl "http://127.0.0.1:8001/api/avm/manual_review_control_plane_integrity_history?limit=20"
```

重点看：
- `history[*].integrity_status`
- `history[*].recorded_at`
- `manual_review_control_plane_integrity_history_summary`

### 6.8 查看操作历史

如果需要追踪最近是谁提交了什么 receipt、是否发生过覆盖更新或删除，可直接查询：

```bash
curl "http://127.0.0.1:8001/api/avm/manual_review_receipt_operations"
curl "http://127.0.0.1:8001/api/avm/manual_review_receipt_operations?action=manual_location_review&ready_signal=location_artifacts_complete&limit=20"
```

重点看：
- `operation`
- `requested_at`
- `execution_mode`
- `maintenance_job_id`
- `payload_fingerprint`

### 6.9 提交后的验证

提交后至少检查：

1. `GET /api/status`
   - `collection_stage.manual_review_receipt_summary`
   - `collection_stage.manual_review_receipt_jobs_summary`
   - `collection_stage.manual_review_receipt_operations_summary`
   - `collection_stage.manual_review_control_plane_storage`
   - `collection_stage.manual_review_control_plane_backup`
   - `collection_stage.manual_review_control_plane_backup_repairs_summary`
   - `collection_stage.operator_overview`
2. `GET /api/analysis/health`
   - `collection_stage.recommended_actions`
   - `collection_stage.manual_review_reentry_application_summary`
3. `GET /api/analysis/release_gate`
   - `analysis_readiness.manual_review_receipt_summary`
   - `analysis_readiness.manual_review_receipt_jobs_summary`
   - `analysis_readiness.manual_review_receipt_operations_summary`
   - `analysis_readiness.manual_review_control_plane_storage`
   - `analysis_readiness.manual_review_control_plane_backup`
   - `analysis_readiness.manual_review_control_plane_backup_repairs_summary`
   - `analysis_readiness.operator_overview`

若 receipt 结构合法但业务上不完整，系统会继续返回：
- `top_receipt_status = "receipt_incomplete"`
- `top_invalid_receipt_reason`
- `top_receipt_fix_actions`
- `receipt_validation_repair_hints`

此时应按 repair hints 修正后重新提交，而不是直接假定自动链会恢复。

### 6.10 JSON 状态导入数据库

当 repository / DB 已启用，并且需要把历史 receipt / job / operation 文件导入数据库时，使用：

```powershell
python tools/backfill_manual_review_control_plane_to_db.py --data-root datas --db-url "<your-db-url>"
```

该工具会导入：

- `datas/avm/manual_review_receipts.json`
- `datas/avm/manual_review_receipt_jobs.json`
- `datas/avm/manual_review_receipt_operations.jsonl`

适用场景：

- 新启用 DB-backed control-plane
- 需要把旧 JSON-first 状态迁移进新表
- 做本地回放 / 迁移验证

### 6.11 从数据库导出 JSON 备份

当 repository / DB 已启用，并且需要把当前 control-plane 状态导出成 JSON / JSONL 备份文件时，使用：

```powershell
python tools/export_manual_review_control_plane_to_json.py --data-root datas --db-url "<your-db-url>"
```

或使用统一工具的 export 模式：

```powershell
python tools/backfill_manual_review_control_plane_to_db.py --mode export --data-root datas --db-url "<your-db-url>"
```

该导出会覆盖更新：

- `datas/avm/manual_review_receipts.json`
- `datas/avm/manual_review_receipt_jobs.json`
- `datas/avm/manual_review_receipt_operations.jsonl`

适用场景：

- 在 DB-backed control-plane 上生成离线备份
- 迁移验证后保留一份 JSON 快照
- 需要把当前 receipt/job/audit 状态交给不连数据库的本地调试环境

说明：

- repository disabled 时，导出命令会返回 `repository_disabled`
- 运行时 source of truth 仍以 repository 为主；JSON 在这一阶段主要扮演：
  - bootstrap source
  - offline backup / export artifact
- repository-backed 的 receipt CRUD、operation append、async job enqueue / completion 现在也会自动刷新这三份 JSON / JSONL 备份文件，
  因此备份不再只能依赖人工定期执行 export 命令
- 可通过 `manual_review_control_plane_backup.backup_state` 观察当前备份状态：
  - `runtime_json`
  - `in_sync`
  - `missing_backup`
  - `count_mismatch`
- 可通过 `manual_review_control_plane_backup.backup_reason` 判断当前状态为什么会变成这样：
  - `repository_disabled`
  - `already_in_sync`
  - `repaired_missing_backup`
  - `repaired_count_mismatch`
- repository-backed 读路径现在也会在需要时自动修复 backup，因此很多场景下会直接看到：
  - `backup_state = in_sync`
  - `backup_reason = repaired_missing_backup` 或 `repaired_count_mismatch`

### 6.12 DB rollout preflight

在真正执行 live DB rollout 之前，可先生成一份**只读 preflight 报告**：

```powershell
python tools/manual_review_control_plane_rollout_preflight.py --data-root datas --db-url "<your-db-url>"
```

它会帮助判断当前更接近哪一种状态：

- `requires_database_configuration`
- `repository_disabled_by_config`
- `ready_for_backfill`
- `ready_for_backup_sync`
- `ready_for_runtime_validation`
- `ready_for_clean_start`

适用场景：

- 拿到真实 DB 环境后，先确定下一步究竟是：
  - 配库
  - 跑 migration
  - 跑 backfill
  - 先做 backup sync
  - 还是已经可以进入 runtime validation
