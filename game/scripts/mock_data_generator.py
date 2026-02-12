import json
import random
import os
from datetime import datetime, timedelta

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
OUTPUT_FILE = os.path.join(PROJECT_ROOT, "datas", "mock_data.json")
NUM_RECORDS = 1000  # Generate 1000 records for testing
CITIES = {
    "上海市": ["浦东新区", "徐汇区", "闵行区", "静安区"],
    "北京市": ["朝阳区", "海淀区", "丰台区", "西城区"],
    "杭州市": ["余杭区", "西湖区", "拱墅区", "在此区"]
}
COMMUNITY_PREFIXES = ["世茂", "万科", "恒大", "保利", "绿地", "中海", "融创", "龙湖"]
COMMUNITY_SUFFIXES = ["滨江花园", "城市花园", "国际社区", "一品", "悦府", "新城", "公馆"]

def generate_mock_data():
    data = []
    
    for _ in range(NUM_RECORDS):
        city = random.choice(list(CITIES.keys()))
        district = random.choice(CITIES[city])
        community = f"{random.choice(COMMUNITY_PREFIXES)}{random.choice(COMMUNITY_SUFFIXES)}"
        
        # Random dates within last 2 years
        days_ago = random.randint(0, 730)
        date = (datetime.now() - timedelta(days=days_ago)).strftime("%Y/%m/%d %H:%M:%S")
        
        # Prices
        area = random.randint(50, 300)
        market_price = random.randint(50000, 150000) * area
        discount_rate = random.uniform(0.5, 0.9) # 5-9折成交
        deal_price = int(market_price * discount_rate)
        
        record = {
            "id": random.randint(1000000000000, 9999999999999),
            "市场评估价": market_price,
            "起拍价格": int(market_price * 0.7),
            "成交价格": deal_price,
            "交易时间": date,
            "原始网站": "https://mock.taobao.com/auction/123.htm",
            "是否成交": True,
            "竞拍人数": random.randint(1, 10),
            "出价人数": random.randint(1, 50),
            "地点": f"{city}{district}{community}xx号",
            "所属小区": community,
            "省份": "MockProvince",
            "城市": city,
            "区": district,
            "最靠近商圈": "MockCircle",
            "建筑面积": area,
            "单价": int(deal_price / area),
            "is_processed": True,
            "detail_captured": True,
            "status": "done"
        }
        data.append(record)

    # Ensure output directory exists
    os.makedirs(os.path.dirname(OUTPUT_FILE), exist_ok=True)
    
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    
    print(f"Successfully generated {NUM_RECORDS} mock records to {OUTPUT_FILE}")

if __name__ == "__main__":
    generate_mock_data()
