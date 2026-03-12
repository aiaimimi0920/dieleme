# AVM API 接口文档（可直接供前端/脚本消费）

本文档定义 AVM 读接口与批量筛选接口，包含请求/响应字段与落盘告警约定。

## 1) 单条估值接口（只读）

- **Method**: `GET`
- **Path**: `/api/avm/predict?id=<item_id>`
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
  "risk_summary": "未发现恶性风控标签"
}
```

### 错误码

- `400`: 缺少 `id`
- `404`: 标的不存在
- `422`: 缺少估值或起拍价格，无法计算

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
      "meets_alert_threshold": true
    }
  ]
}
```

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

