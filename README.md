# 法拍房数据采集与可视分析系统 (Fapaifang Data Scraper & Visualizer)

![Python](https://img.shields.io/badge/Python-3.10%2B-blue)
![Vue.js](https://img.shields.io/badge/Vue.js-3.x-green)
![Status](https://img.shields.io/badge/Status-Beta-yellow)
![Data](https://img.shields.io/badge/Data-Simulated-red)

## 📖 项目简介 (Introduction)

本项目是一个集**司法拍卖房产数据采集**、**智能清洗**、**地理可视化**以及**趣味交互分析**于一体的综合系统。旨在通过自动化的手段获取阿里拍卖等平台的法拍房数据，并利用大语言模型（LLM）进行价值分析，最终通过生动的数据可视化游戏展示房产的真实价格。

> [!WARNING]
> **免责声明 (Disclaimer)**  
> 游戏内的分析数据目前为**模拟数据 (Mock Data)**，仅用于演示功能，不代表真实市场情况。真实的 LLM 分析与全量数据采集模块仍在开发中。

主要功能模块包括：
- **全自动数据采集**：基于 Tampermonkey 脚本与 Python 后端的实时数据抓取。
- **智能数据清洗**：自动补全小区名称、修复缺失面积、标准化地址信息。
- **地理热力图**：基于 ECharts 的全国/省市/区县三级房价热力分布。
- **互动游戏**：通过具象化的物品（如咖啡、iPhone、汽车）来衡量房价下跌的"重量"。

---

## ✨ 核心功能 (Features)

### 1. 数据采集与处理 (Data Pipeline)
- **多源抓取**：支持阿里拍卖等主流司法拍卖平台。
- **增量更新**：自动识别新发布房源，避免重复抓取。
- **智能修复**：基于规则与 AI 的数据错误自动修正。

### 2. 可视化交互 (Visualization & Game)
- **房价地图**：直观展示各区域法拍房均价、历年法拍房走势图。
- **互动游戏关卡**：
  - **Level 1: 破壁 (The Cut)** 🗡️  
    玩家通过切割房产面积，切除的部分需精确匹配该房产的实际**亏损额度**。
  - **Level 2: 神之天平 (The Balance)** ⚖️  
    将被切除的"亏损面积"放置在天平一端，玩家需在另一端放置等价的消费品（如 1000 杯库迪咖啡 ☕、10 部 iPhone 📱、1 次全球旅行 ✈️、1 辆小米 SU7 🚗）。当天平达成**完美平衡**时通关。
  - **Level 3: 命运轮盘 (The Wheel)** 🎰  
    旋转命运轮盘，基于区域数据预测明年的房价走势与跌幅。

---

## �️ 开发路线图 (Roadmap)

- [ ] **数据全采集** (Data Collection)
    - [x] 阿里拍卖基础接口
    - [ ] 全量历史数据回溯
- [ ] **游戏开发** (Game Dev)
    - [x] 核心玩法原型 (Level 1 & 2)
    - [ ] 真实数据接入
    - [ ] 移动端适配优化
- [ ] **数据清洗** (Data Cleaning)
    - [x] 基础字段修复
    - [ ] LLM 深度价值分析
- [ ] **数据大屏** (Dashboard)
    - [x] 全国热力图
    - [ ] 城市下钻分析

---

## 🚀 快速开始 (Getting Started)

### 前置要求 (Prerequisites)
- Python 3.10 或更高版本
- Chrome 浏览器 + Tampermonkey 插件

### 1. 安装依赖
```bash
# 克隆项目
git clone https://github.com/your-repo/fapaifang.git
cd fapaifang

# 创建虚拟环境 (推荐)
python -m venv venv
# Windows 激活
venv\Scripts\activate
# Linux/Mac 激活
source venv/bin/activate

# 安装 Python 依赖
pip install -r requirements.txt
```

### 2. 启动数据服务
项目提供了自动化的启动脚本：

```bash
# 启动主程序 (数据接收 & API 服务)
.\auto\main.bat

# 启动数据修复服务 (后台运行)
.\auto\data_fixer.bat
```

### 3. 安装浏览器脚本
1. 打开 Chrome 浏览器，进入 Tampermonkey 管理面板。
2. 新建脚本，将 `tampermonkey_scripts/fapaifang_unified.user.js` 的内容复制进去并保存。
3. 访问阿里拍卖页面，脚本将自动运行并将数据发送至本地后端。

### 4. 启动可视化/游戏
直接用浏览器打开 `game/web-app/index.html` 即可开始体验游戏及数据大屏（注意还未完成）。

---

## 📂 目录结构 (Directory Structure)

```
fapaifang/
├── auto/                   # 自动化运行脚本 (BAT)
├── datas/                  # 数据存储目录
│   ├── archive/            # 归档数据 (按年/月分类)
│   └── ...
├── game/                   # 前端可视化项目
│   └── web-app/            # Vue3 游戏主程序
│       ├── index.html      # 游戏入口
│       └── assets/         # 资源文件
├── src/                    # Python 源代码
│   ├── data_fixer.py       # 数据清洗逻辑
│   ├── server.py           # 后端 API 服务
│   └── ...
├── tampermonkey_scripts/   # 浏览器用户脚本
│   └── fapaifang_unified.user.js
├── jobs/                   # 任务队列与状态配置
└── README.md               # 项目说明文档
```

---

## 🤝 贡献 (Contributing)

欢迎提交 Issue 或 Pull Request 来改进本项目！

1. Fork 本仓库
2. 新建分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送分支 (`git push origin feature/AmazingFeature`)
5. 提交 Pull Request

---

## ⚠️ 特别声明 (Special Statement)

1. **本项目仅供 Python 编程学习与技术交流使用，严禁用于任何商业用途**（如数据倒卖、收费服务等）。
2. 本项目所采集的数据均来源于公开网络，所有权归原网站所有。
3. 请在使用时严格遵守相关法律法规及目标网站的 robots.txt 协议。
4. 开发者不对任何因使用本项目而产生的法律后果承担责任。

---

## 📄 许可证 (License)

本项目采用 MIT 许可证。详情请参阅 [LICENSE](LICENSE) 文件。
