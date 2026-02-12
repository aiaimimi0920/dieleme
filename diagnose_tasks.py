
import json
import os
import glob
import datetime

DATA_DIR = "datas"

def diagnose():
    print("Diagnosing task availability...")
    
    if not os.path.exists(DATA_DIR):
        print(f"Directory {DATA_DIR} does not exist.")
        return

    # 1. Scan root JSONs
    try:
        root_files = glob.glob(os.path.join(DATA_DIR, '*.json'))
    except:
        root_files = []

    # 2. Scan Archive JSONs (Recursive)
    try:
        archive_pattern = os.path.join(DATA_DIR, 'archive', '**', '*.json')
        archive_files = glob.glob(archive_pattern, recursive=True)
    except:
        archive_files = []
        
    files = root_files + archive_files

    # Skip list from server.py
    skip_files = [
        "all_locations.json", "sniff_queue", "sniff_status", "sniff_history", "sniff_done",
        "manual_priority_locations.json", "sniff_progress.json", "collected_locations.json",
        "model_config.json", "tuning_history.json", "seen_ids.json"
    ]
    files = [f for f in files if not any(skip in os.path.basename(f) for skip in skip_files)]
    
    print(f"Found {len(files)} data files.")
    
    total_items = 0
    pending_items = []
    
    status_counts = {}
    
    for file_path in files:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = json.load(f)
                
            items = []
            if isinstance(content, list):
                items = content
            elif isinstance(content, dict):
                items = [content]

            for item in items:
                item_id = str(item.get("id"))
                if not item_id:
                    continue
                
                total_items += 1
                status = item.get("status")
                is_processed = item.get("is_processed", False)
                is_sold = item.get("是否成交")
                
                status_key = f"{status}|{is_processed}"
                status_counts[status_key] = status_counts.get(status_key, 0) + 1
                
                # Logic from server.py
                is_done = status in ["done", "成交", "failure", "failed_timeout"] or is_sold is True
                
                if is_done and not is_processed:
                    pending_items.append({
                        "id": item_id,
                        "file": file_path,
                        "status": status,
                        "url": item.get("url")
                    })
        except Exception as e:
            pass
            
    print(f"Total Items Scanned: {total_items}")
    print("Status Breakdown (status|is_processed):")
    for k, v in sorted(status_counts.items(), key=lambda x: -x[1]): # Sort by count desc
        print(f"  {k}: {v}")
        
    print(f"\nPending Tasks (matches criteria): {len(pending_items)}")
    if len(pending_items) > 0:
        print("Sample pending tasks:")
        for t in pending_items[:5]:
            print(f"  ID: {t['id']} | Status: {t['status']} | File: {t['file']}")
    else:
        print("NO PENDING TASKS FOUND. This explains why detection gets no tasks.")

if __name__ == "__main__":
    diagnose()
