# 最终采集数据模板（冻结版）

> 版本：`avm_collection_contract_v1_frozen`
> 状态：**冻结版 / 采集器最终合同**
> 用途：作为后续 Tampermonkey 采集器、详情 enrich、人工修正页、批量导入脚本的统一输入合同。

这份文档不是“建议版”，而是本项目当前阶段建议**固定下来**的采集合同。

后续如果要改下面这些内容：

- authoritative key 名称
- 字段语义
- 单位规则
- `bid_count` / `bidder_count` 的定义
- `source_title` / `full_address` 的职责边界

都应视为 **breaking change**，必须升新版本，不能原地修改。

---

## 1. 冻结规则

### 1.1 允许的后续变更

只允许以下三类“非破坏性”追加：

1. 新增可选审计字段
2. 新增 legacy alias
3. 对注释和说明文字做澄清，不改变语义

### 1.2 不允许的原地变更

以下内容后续**禁止原地改**：

1. 改 authoritative key 名
2. 改字段单位
3. 把 `bid_count` 和 `bidder_count` 再混回一个字段
4. 再次允许 `title/source_title` 顶替 `full_address`
5. 重新改变 `area_sqm / gross_area_sqm / ownership_share_ratio` 的职责边界
6. 把派生字段重新变成“需要采集”的原始字段

---

## 2. authoritative key：以后采集端应以这些字段为准

## 2.1 source

```json
{
  "item_id": "",
  "source_item_id": "",
  "source_url": "",
  "source_title": "",
  "source_platform": "taobao_sf",
  "detail_archive_path": ""
}
```

### 语义
- `item_id`：规范层主键，唯一识别一套标的
- `source_item_id`：来源平台主键，当前通常与 `item_id` 相同
- `source_url`：详情页原始链接
- `source_title`：来源页面标题，**不能拿来冒充地址**
- `source_platform`：来源平台，当前建议固定 `taobao_sf`
- `detail_archive_path`：服务端归档的详情 HTML/TXT 路径

---

## 2.2 archive

```json
{
  "list_payload_path": "",
  "detail_text_path": "",
  "component_payload_path": "",
  "notice_text_path": "",
  "desc_text_path": "",
  "attachment_manifest_path": "",
  "image_manifest_path": ""
}
```

### 语义
- `list_payload_path`：列表页原始 JSON 或 sidecar 存档
- `detail_text_path`：详情页过滤后纯文本存档
- `component_payload_path`：`J_COMPONENT` / notice API 等结构化 payload 存档
- `notice_text_path`：公告正文存档
- `desc_text_path`：标的描述存档
- `attachment_manifest_path`：附件/PDF/报告链接清单
- `image_manifest_path`：图片链接或下载清单

### 为什么要现在就冻结
这组字段当前不直接进 AVM，但它们是“以后不想重抓百万条数据”的关键保险。
未来无论做：

- 新字段重抽
- PDF OCR
- 图像质量分析
- 公告/须知二次解析

都优先依赖这些归档，不应再回源补抓。

---

## 2.3 auction

```json
{
  "status": "done",
  "auction_date": "",
  "auction_start_time": "",
  "auction_round": null,
  "transaction_price": null,
  "starting_price": null,
  "actual_paid_price": null,
  "evaluation_price": null,
  "deposit": null,
  "apply_count": null,
  "bid_count": null,
  "bidder_count": null,
  "watch_count": null,
  "reminder_count": null,
  "view_count": null
}
```

### 语义
- `status`：当前只保留已成交样本，推荐归一成 `done`
- `auction_date`：北京时间 `YYYY-MM-DD HH:mm:ss`
- `auction_start_time`：开拍时间，未来可分析拍卖时长与延时行为
- `auction_round`：1=一拍，2=二拍，3=变卖，其他保留原始整数
- `transaction_price`：落槌成交价，单位=元
- `starting_price`：起拍价，单位=元
- `actual_paid_price`：真实支付总价估计值，单位=元
- `evaluation_price`：法院评估价/市场价，单位=元
- `deposit`：保证金，单位=元
- `apply_count`：报名人数
- `bid_count`：**出价次数**
- `bidder_count`：**出价人数**
- `watch_count`：围观人数
- `reminder_count`：提醒人数
- `view_count`：浏览次数

### 强约束
- 所有价格统一存**元**
- `bid_count != bidder_count`
  - `bid_count` 是次数
  - `bidder_count` 是人数

---

## 2.4 location

```json
{
  "full_address": "",
  "province": "",
  "city": "",
  "district": "",
  "business_area": "",
  "community_name": "",
  "latitude": null,
  "longitude": null,
  "coordinate_source": ""
}
```

### 语义
- `full_address`：完整地址原文或尽可能完整的位置描述
- `province/city/district`：行政区解析结果
- `business_area`：商圈/镇街/板块
- `community_name`：标准化小区/楼盘名
- `latitude/longitude`：中国范围合法坐标
- `coordinate_source`：如 `list/html/meta/script/llm/centroid`

### 强约束
- `full_address` 和 `source_title` 必须严格拆开
- 地址缺失时允许 `full_address=""` 或 `null`，**禁止**把标题原样抄进去
- `latitude`=纬度，`longitude`=经度，禁止反置

---

## 2.5 property

```json
{
  "housing_type": "",
  "area_sqm": null,
  "gross_area_sqm": null,
  "interior_area_sqm": null,
  "land_area_sqm": null,
  "ownership_share_ratio": 1.0,
  "layout": "",
  "build_year": null,
  "total_floors": null,
  "floor_level": "",
  "has_elevator": null,
  "orientation": "",
  "includes_parking": null,
  "special_school_tag": null,
  "has_keys": null
}
```

### 语义
- `housing_type`：必须归一为
  `住宅 / 别墅 / 商业 / 办公 / 工业 / 车位 / 其他`
- `area_sqm`：最终用于估值的**有效可交易面积**，单位=平方米
- `gross_area_sqm`：产权证或公告中写明的**原始建筑面积**
- `interior_area_sqm`：套内面积
- `land_area_sqm`：土地/占地面积，尤其适合别墅/工业/独栋
- `ownership_share_ratio`：产权份额比例，0~1；全产权=1.0，1/2产权=0.5
- `layout`：如 `3室2厅1卫`
- `build_year`：建成年份
- `total_floors`：总楼层
- `floor_level`：建议归一为
  `底层 / 低区 / 中区 / 高区 / 顶层 / 独栋`
- `has_elevator`：是否有电梯
- `orientation`：朝向
- `includes_parking`：拍品是否附带真实车位/车库
- `special_school_tag`：是否明确学区/学位卖点
- `has_keys`：法院是否持钥匙/可看样

### 强约束
- 如果存在部分产权：
  - `gross_area_sqm` 记录原始产权面积
  - `ownership_share_ratio` 记录份额比例
  - `area_sqm` 记录最终可交易有效面积
- 如果是完整产权：
  - `ownership_share_ratio = 1.0`
  - `area_sqm = gross_area_sqm`

---

## 2.6 legal_context

```json
{
  "court_name": "",
  "case_number": "",
  "appraisal_agency_name": "",
  "appraisal_benchmark_date": "",
  "appraisal_report_urls": [],
  "announcement_attachment_urls": []
}
```

### 语义
- `court_name`：执行法院
- `case_number`：案号
- `appraisal_agency_name`：评估机构
- `appraisal_benchmark_date`：评估基准日
- `appraisal_report_urls`：评估报告链接列表
- `announcement_attachment_urls`：公告附件/须知/PDF/视频等链接列表

### 为什么值得纳入冻结版
这组字段当前不一定直接参与价格计算，但对未来这些场景非常重要：

- 评估价偏差分析
- PDF 下载与 OCR
- 案件追踪
- 同案多标的去重
- 法院/区域风格偏差分析

---

## 2.7 risk_flags

```json
{
  "land_right_type": "",
  "is_occupied": null,
  "has_long_lease": null,
  "clear_delivery": null,
  "tax_burden": "",
  "property_fee_owed": null,
  "is_restricted_purchase": null,
  "is_fractional_share": null,
  "tax_is_company_owned": null,
  "is_haunted": null,
  "has_lease_before_mortgage": null
}
```

### 语义
- `land_right_type`：`出让 / 划拨 / 未知`
- `is_occupied`：是否被占用/有人居住
- `has_long_lease`：是否存在长期租约
- `clear_delivery`：法院是否负责清场交付
- `tax_burden`：`买受人承担全部 / 各自承担 / 未知`
- `property_fee_owed`：是否有物业/水电欠费
- `is_restricted_purchase`：是否受限购约束
- `is_fractional_share`：是否部分产权/共有份额
- `tax_is_company_owned`：原产权人是否公司
- `is_haunted`：是否凶宅/刑案
- `has_lease_before_mortgage`：是否属于先抵后租可清场假租约

---

## 2.8 audit

```json
{
  "extraction_confidence": null,
  "evidence_span": "",
  "evidence_source": "",
  "extraction_version": "",
  "is_processed": false,
  "detail_captured": false
}
```

### 语义
- `extraction_confidence`：LLM 抽取置信度
- `evidence_span`：命中的证据片段
- `evidence_source`：如 `公告 / 须知 / 评估报告 / html`
- `extraction_version`：抽取器版本
- `is_processed`：是否完成当前流水线处理
- `detail_captured`：是否已经拿到详情页完整输入

---

## 3. 最终最小必采字段

如果后续你们需要严格区分“必须采到”和“可以后补”，我建议以这组作为**最终最小必采集合**。

### 3.1 列表页必须采到

- `item_id`
- `source_item_id`
- `source_url`
- `source_title`
- `source_platform`
- `detail_archive_path`
- `list_payload_path`
- `status`
- `auction_date`
- `auction_start_time`
- `transaction_price`
- `starting_price`
- `deposit`
- `auction_round`
- `apply_count`
- `bid_count`
- `bidder_count`（拿得到就采；拿不到允许空）
- `watch_count` / `reminder_count` / `view_count`（拿得到就采）
- `full_address`
- `city`
- `district`
- `business_area`
- `latitude`
- `longitude`
- `coordinate_source`
- `housing_type`

### 3.2 详情页结构化必须补到

- `area_sqm`
- `gross_area_sqm`
- `interior_area_sqm`
- `land_area_sqm`
- `ownership_share_ratio`
- `community_name`
- `evaluation_price`
- `deposit`
- `detail_archive_path`
- `detail_text_path`
- `component_payload_path`
- `notice_text_path`
- `desc_text_path`
- `attachment_manifest_path`
- `image_manifest_path`
- `court_name`
- `case_number`
- `appraisal_report_urls`
- `announcement_attachment_urls`

### 3.3 LLM / 规则抽取必须补到

- `layout`
- `build_year`
- `total_floors`
- `floor_level`
- `has_elevator`
- `orientation`
- `includes_parking`
- `special_school_tag`
- `has_keys`
- `land_right_type`
- `is_occupied`
- `has_long_lease`
- `clear_delivery`
- `tax_burden`
- `property_fee_owed`
- `is_restricted_purchase`
- `is_fractional_share`
- `tax_is_company_owned`
- `is_haunted`
- `has_lease_before_mortgage`
- `extraction_confidence`
- `evidence_span`
- `evidence_source`
- `extraction_version`

---

## 4. 兼容 alias：旧字段仍可接受，但不再是主字段

| authoritative key | legacy alias |
|---|---|
| `item_id` | `id`, `唯一id` |
| `source_url` | `url`, `原始网站` |
| `source_title` | `title`, `标题`, `标的物名称` |
| `source_platform` | `source_platform`, `platform` |
| `auction_start_time` | `auction_start_time`, `startTime`, `开拍时间` |
| `auction_date` | `交易时间`, `end` |
| `transaction_price` | `成交价格`, `currentPrice` |
| `starting_price` | `起拍价格`, `initialPrice` |
| `actual_paid_price` | `实际支付总价` |
| `evaluation_price` | `市场评估价` |
| `deposit` | `保证金` |
| `apply_count` | `applyCount`, `竞拍人数`, `报名人数` |
| `bid_count` | `bidCount`, `出价次数` |
| `bidder_count` | `bidderCount`, `bidUserNumber`, `出价人数` |
| `watch_count` | `watchCount`, `围观人数` |
| `reminder_count` | `remindCount`, `提醒人数` |
| `view_count` | `viewCount`, `浏览次数` |
| `full_address` | `地点`, `location`, `完整地址` |
| `district` | `区`, `行政区` |
| `business_area` | `最靠近商圈`, `business_area_name` |
| `community_name` | `所属小区`, `小区`, `小区名称` |
| `latitude` | `纬度`, `lat` |
| `longitude` | `经度`, `lng` |
| `housing_type` | `房屋用途`, `housingType` |
| `gross_area_sqm` | `产权建筑面积`, `原始建筑面积` |
| `interior_area_sqm` | `套内面积` |
| `land_area_sqm` | `土地面积`, `占地面积` |
| `ownership_share_ratio` | `产权份额比例` |
| `court_name` | `法院名称`, `执行法院` |
| `case_number` | `案号` |
| `appraisal_agency_name` | `评估机构` |
| `appraisal_benchmark_date` | `评估基准日` |
| `appraisal_report_urls` | `评估报告链接` |
| `announcement_attachment_urls` | `附件链接` |

---

## 5. 明确不采、只派生的字段

以下字段以后不要再当成“采集字段”设计：

- `unit_price`
- `auction_month_index`
- `predicted_price`
- `predicted_unit_price`
- `margin_of_safety`
- `coordinate_strategy`
- `manual_review_recommended`
- `manual_review_reasons`

这些都应该由后端根据原始数据推导。

---

## 6. 最终推荐的最小 JSON 模板

```json
{
  "source": {
    "item_id": "",
    "source_item_id": "",
    "source_url": "",
    "source_title": "",
    "source_platform": "taobao_sf",
    "detail_archive_path": ""
  },
  "archive": {
    "list_payload_path": "",
    "detail_text_path": "",
    "component_payload_path": "",
    "notice_text_path": "",
    "desc_text_path": "",
    "attachment_manifest_path": "",
    "image_manifest_path": ""
  },
  "auction": {
    "status": "done",
    "auction_date": "",
    "auction_start_time": "",
    "auction_round": null,
    "transaction_price": null,
    "starting_price": null,
    "actual_paid_price": null,
    "evaluation_price": null,
    "deposit": null,
    "apply_count": null,
    "bid_count": null,
    "bidder_count": null,
    "watch_count": null,
    "reminder_count": null,
    "view_count": null
  },
  "location": {
    "full_address": "",
    "province": "",
    "city": "",
    "district": "",
    "business_area": "",
    "community_name": "",
    "latitude": null,
    "longitude": null,
    "coordinate_source": ""
  },
  "property": {
    "housing_type": "",
    "area_sqm": null,
    "gross_area_sqm": null,
    "interior_area_sqm": null,
    "land_area_sqm": null,
    "ownership_share_ratio": 1.0,
    "layout": "",
    "build_year": null,
    "total_floors": null,
    "floor_level": "",
    "has_elevator": null,
    "orientation": "",
    "includes_parking": null,
    "special_school_tag": null,
    "has_keys": null
  },
  "legal_context": {
    "court_name": "",
    "case_number": "",
    "appraisal_agency_name": "",
    "appraisal_benchmark_date": "",
    "appraisal_report_urls": [],
    "announcement_attachment_urls": []
  },
  "risk_flags": {
    "land_right_type": "",
    "is_occupied": null,
    "has_long_lease": null,
    "clear_delivery": null,
    "tax_burden": "",
    "property_fee_owed": null,
    "is_restricted_purchase": null,
    "is_fractional_share": null,
    "tax_is_company_owned": null,
    "is_haunted": null,
    "has_lease_before_mortgage": null
  },
  "audit": {
    "extraction_confidence": null,
    "evidence_span": "",
    "evidence_source": "",
    "extraction_version": "",
    "is_processed": false,
    "detail_captured": false
  }
}
```

---

## 7. 实现锚点

当前仓库里，这份冻结版已经有两个实现锚点：

- 机读契约：
  - `src/avm/collection_template.py`
- 服务接口：
  - `GET /api/avm/collection_template`

后续采集器、详情 enrich、人工修正页、导入脚本，都应围绕这份冻结版对齐。
