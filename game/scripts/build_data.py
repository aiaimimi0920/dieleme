import json
import os
import math
from collections import defaultdict
from datetime import datetime

# Configuration
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
SOURCE_FILE = os.path.join(PROJECT_ROOT, "datas", "mock_data.json")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "game", "web-app", "public", "data")

def ensure_dir(path):
    if not os.path.exists(path):
        # Python 3.2+ os.makedirs exists_ok=True
        os.makedirs(path, exist_ok=True)

def calculate_stats(items):
    if not items:
        return None
    
    # Filter valid items
    valid_items = [i for i in items if i.get("单价") and i["单价"] > 0 and i.get("交易时间")]
    if not valid_items:
        return None

    # Calculate basic stats
    prices = [i["单价"] for i in valid_items]
    avg_price = int(sum(prices) / len(prices))
    max_price = int(max(prices))
    min_price = int(min(prices))
    
    # Calculate drop rate from peak
    drop_rate = 0
    if max_price > 0:
        drop_rate = round((max_price - avg_price) / max_price, 2)

    # Calculate trend (compare last 6 months vs older)
    # Simple logic for now: negative drop rate is the trend
    trend_factor = -drop_rate * 0.5 # Mock logic: trend continues at half speed

    return {
        "avg_price": avg_price,
        "max_price": max_price,
        "min_price": min_price,
        "drop_rate": drop_rate,
        "trend_factor": round(trend_factor, 2),
        "total_items": len(valid_items),
        "items": sorted(valid_items, key=lambda x: x["交易时间"], reverse=True)[:5] # Keep recent 5
    }

def build_data():
    print(f"Loading data from {SOURCE_FILE}...")
    if not os.path.exists(SOURCE_FILE):
        print(f"Error: Source file {SOURCE_FILE} not found. Please run mock_data_generator.py first.")
        return

    with open(SOURCE_FILE, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    # Group by City -> District -> Community
    cities = defaultdict(lambda: defaultdict(list))
    
    for item in raw_data:
        city = item.get("城市")
        district = item.get("区")
        community = item.get("所属小区")
        
        if city and district and community:
            cities[city][district].append(item)

    # Build Output
    ensure_dir(OUTPUT_DIR)
    ensure_dir(os.path.join(OUTPUT_DIR, "cities"))
    ensure_dir(os.path.join(OUTPUT_DIR, "districts"))

    global_stats = {
        "total_cities": 0,
        "total_districts": 0,
        "total_communities": 0,
        "last_updated": datetime.now().strftime("%Y-%m-%d"),
        "cities": []
    }

    for city_name, districts in cities.items():
        city_id = abs(hash(city_name)) % 1000000 # Mock ID
        global_stats["cities"].append({"name": city_name, "id": city_id})
        global_stats["total_cities"] += 1

        city_index = {
            "name": city_name,
            "districts": []
        }

        for district_name, items in districts.items():
            district_id = abs(hash(district_name)) % 1000000
            city_index["districts"].append({"name": district_name, "id": district_id})
            global_stats["total_districts"] += 1

            # Process District Data
            district_data = {
                "city": city_name,
                "district": district_name,
                "communities": {}
            }
            
            # Group items by community
            community_groups = defaultdict(list)
            for item in items:
                community_groups[item["所属小区"]].append(item)

            for comm_name, comm_items in community_groups.items():
                stats = calculate_stats(comm_items)
                if stats:
                    district_data["communities"][comm_name] = stats
                    global_stats["total_communities"] += 1
            
            # Rank communities by drop rate
            # (In a real app, we might add a 'rank' field to each community here)

            # Save District JSON
            # In production, use hashed IDs. For now, use names for readability (sanitize?)
            # Or use the hash IDs we generated
            district_filename = f"{city_id}_{district_id}.json"
            with open(os.path.join(OUTPUT_DIR, "districts", district_filename), 'w', encoding='utf-8') as f:
                json.dump(district_data, f, ensure_ascii=False)
        
        # Save City Index
        city_filename = f"{city_id}.json"
        with open(os.path.join(OUTPUT_DIR, "cities", city_filename), 'w', encoding='utf-8') as f:
            json.dump(city_index, f, ensure_ascii=False)

    # Save Meta
    with open(os.path.join(OUTPUT_DIR, "meta.json"), 'w', encoding='utf-8') as f:
        json.dump(global_stats, f, ensure_ascii=False, indent=2)

    print("Data build complete!")
    print(f"Cities: {global_stats['total_cities']}")
    print(f"Districts: {global_stats['total_districts']}")
    print(f"Communities: {global_stats['total_communities']}")

if __name__ == "__main__":
    build_data()
