
import os
import json
import glob

DATA_DIR = r"c:\Users\Public\nas_home\project\fapaifang\datas"

def analyze_data_quality():
    json_files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    
    total_items = 0
    missing_area = 0
    missing_community = 0
    missing_price = 0
    
    # Track daily stats for recent trend analysis
    daily_stats = {}

    print(f"Scanning {len(json_files)} files in {DATA_DIR}...")
    
    for file_path in json_files:
        filename = os.path.basename(file_path)
        if filename in ["collected_locations.json", "sniff_done.json", "sniff_queue.json", "sniff_progress.json"]:
            continue
            
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content: continue
                try:
                    data = json.loads(content)
                except json.JSONDecodeError:
                    print(f"Skipping malformed JSON: {filename}")
                    continue
                
                # Check format: dict of items or list of items?
                # Data structure assumed: { "item_id": { ... }, ... }
                items = []
                if isinstance(data, dict):
                    items = data.values()
                elif isinstance(data, list):
                    items = data
                
                day_total = 0
                day_missing_area = 0
                
                for item in items:
                    if not isinstance(item, dict): continue
                    
                    # Filter only processed items? Or all? Let's check all with 'id'
                    if not item.get("id"): continue
                    
                    total_items += 1
                    day_total += 1
                    
                    # Check fields
                    has_area = item.get("建筑面积") and item.get("建筑面积") != 0
                    has_comm = item.get("所属小区")
                    has_price = item.get("单价") and item.get("单价") != 0
                    
                    if not has_area:
                        missing_area += 1
                        day_missing_area += 1
                    if not has_comm:
                        missing_community += 1
                    if not has_price:
                        missing_price += 1
                
                if day_total > 0:
                    daily_stats[filename] = {
                        "total": day_total,
                        "missing_area": day_missing_area,
                        "rate": (day_missing_area / day_total),
                        "mtime": os.path.getmtime(file_path)
                    }

        except Exception as e:
            print(f"Error reading {filename}: {e}")

    with open("analysis_result.txt", "w", encoding="utf-8") as f:
        f.write("-" * 40 + "\n")
        f.write(f"Total Items: {total_items}\n")
        if total_items > 0:
            f.write(f"Missing Area: {missing_area} ({missing_area/total_items:.1%})\n")
            f.write(f"Missing Community: {missing_community} ({missing_community/total_items:.1%})\n")
            f.write(f"Missing Unit Price: {missing_price} ({missing_price/total_items:.1%})\n")
        f.write("-" * 40 + "\n")
        
        # Show recent top 5 files by MODIFICATION TIME (Newest First)
        f.write("Recent Updated Files Analysis:\n")
        sorted_files = sorted(daily_stats.items(), key=lambda x: x[1]["mtime"], reverse=True)[:5]
        for fname, stats in sorted_files:
             f.write(f"{fname}: {stats['missing_area']}/{stats['total']} missing area ({stats['rate']:.1%})\n")

    print(f"Analysis saved to analysis_result.txt")

if __name__ == "__main__":
    analyze_data_quality()
