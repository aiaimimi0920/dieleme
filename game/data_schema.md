# 游戏数据结构设计 (Game Data Schema)

## 1. 目录结构 (Directory Structure)
```
/game/data/
  ├── config.json           # 全局配置 (等价物、称号、轮盘吉祥话)
  ├── cities/
  │   ├── beijing.json      # 城市级索引
  │   └── ...
  └── districts/
      ├── beijing_chaoyang.json  # 核心数据
      └── ...
```

## 2. 数据模型 (Data Models)

### 2.1 全局配置 `config.json`
增加轮盘数据支持。

```json
{
  "equivalents": [ // 虚无天平
    { "id": "milk_tea", "name": "喜茶", "price": 20 },
    { "id": "tesla_3", "name": "特斯拉 Model 3", "price": 245900 },
    { "id": "year_of_youth", "name": "打工人的一年青春", "price": 120000 }
  ],
  "wheel_phrases": [ // 命运轮盘吉祥话 (90% 概率)
    "时来运转", "财源滚滚", "利空出尽", 
    "触底反弹", "家和万事兴", "稳字当头",
    "未来可期", "平安喜乐", "大吉大利"
  ],
  "doom_phrases": [ // 真实预言前缀 (10% 概率)
    "明年再跌", "腰斩在即", "还得跌", "深不见底"
  ]
}
```

### 2.2 区域数据 `districts/{city}_{district}.json`
增加趋势预测字段。

```json
{
  "city": "上海",
  "district": "浦东新区",
  "communities": {
    "世茂滨江花园": {
      "avg_price": 85000,
      "max_price": 140000,
      "trend_factor": -0.15, // 预测明年跌幅 (基于贝塔系数/挂牌量计算)
      "liquidity_score": 0.3, // 流动性评分 (0-1, 用于决定轮盘'中奖'概率调整)
      "items": [...]
    }
  }
}
```

## 3. 前端计算逻辑 (Frontend Logic)

### 3.1 切蜡烛 (Candle)
- **输入**: 买入价 vs 当前价。
- **反馈**: 比例感知偏差。

### 3.2 虚无天平 (Scale)
- **输入**: 亏损总额。
- **输出**: 等价实物清单。

### 3.3 命运轮盘 (Wheel)
- **逻辑**:
  - 默认 90% 概率转到 `wheel_phrases` 中的随机一句。
  - 10% 概率转到 **真实预言** (或者基于 `liquidity_score` 动态调整 probabilities)。
  - **真实预言内容**: `doom_phrases` + `trend_factor` (e.g. "明年再跌 15%")。
- **海报输出**:
  - **Title**: 转到的短语 (e.g. "财源滚滚" 或 "明年再跌 15%")。
  - **Prediction (Small Print)**: 无论转到什么，海报角落都会用小字印上真实预测："AI 预测: 明年跌幅 15%"。
