import os
import json
import glob
from collections import defaultdict

DATA_DIR = r"c:\Users\Public\nas_home\project\fapaifang\datas\archive"

def analyze_progress():
    stats = defaultdict(lambda: {"total": 0, "processed": 0, "processed_items": 0})
    
    # Also check root for legacy files
    root_dir = r"c:\Users\Public\nas_home\project\fapaifang\datas"
    
    files = glob.glob(os.path.join(DATA_DIR, "**", "*.json"), recursive=True)
    files += glob.glob(os.path.join(root_dir, "*.json"))
    
    print(f"Scanning {len(files)} files...")
    
    unique_ids = set()
    
    for f_path in files:
        if "all_locations" in f_path or "collected_locations" in f_path: continue
        
        try:
            with open(f_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            if isinstance(data, dict): data = [data]
            
            for item in data:
                item_id = item.get("id")
                if not item_id or item_id in unique_ids: continue
                unique_ids.add(item_id)
                
                province = item.get("省份", "未知省份")
                city = item.get("城市", "未知城市")
                # district = item.get("区", "未知区")
                
                key = f"{province} - {city}"
                
                stats[key]["total"] += 1
                if item.get("is_processed"):
                    stats[key]["processed"] += 1
                
        except Exception as e:
            pass

    with open('report.txt', 'w', encoding='utf-8') as f:
        f.write("DATA COVERAGE REPORT (Total Unique: {})\n".format(len(unique_ids)))
        f.write("="*50 + "\n")
        f.write(f"{'Region':<30} | {'Total':<8} | {'Processed':<8} | {'Progress':<8}\n")
        f.write("-" * 60 + "\n")
        
        sorted_stats = sorted(stats.items(), key=lambda x: x[1]['total'], reverse=True)
        
        for region, counts in sorted_stats:
            total = counts['total']
            processed = counts['processed']
            pct = (processed / total * 100) if total > 0 else 0
            f.write(f"{region:<30} | {total:<8} | {processed:<8} | {pct:.1f}%\n")
            
    print("Report generated to report.txt")

if __name__ == "__main__":
    analyze_progress()
