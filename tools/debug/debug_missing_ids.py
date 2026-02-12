import json
import os
import glob
import re

DATA_DIR = "datas"

def load_all_status():
    items_map = {} # id -> {url, is_processed, status}
    json_files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    for jf in json_files:
        if "sniff_queue" in jf or "all_locations" in jf: continue
        try:
            with open(jf, "r", encoding="utf-8") as f:
                data = json.load(f)
                items = data if isinstance(data, list) else data.get("items", [])
                for item in items:
                    if "id" in item:
                        tid = str(item["id"])
                        items_map[tid] = {
                            "url": item.get("url", ""),
                            "is_processed": item.get("is_processed", False),
                            "status": item.get("status", "")
                        }
        except Exception as e:
            print(f"Error reading {jf}: {e}")
    return items_map

def main():
    print("--- Diagnostic Start (Status Check) ---")
    all_items = load_all_status()
    total = len(all_items)
    print(f"Total Unique IDs found: {total}")

    processed_count = sum(1 for item in all_items.values() if item.get("is_processed"))
    print(f"Processed (AI Done): {processed_count}")
    
    pending_items = {k: v for k, v in all_items.items() if not v.get("is_processed")}
    print(f"Pending/Missing: {len(pending_items)}")

    if pending_items:
        print("\n--- Pending Items Details ---")
        for i, (mid, info) in enumerate(pending_items.items()):
            # Only print key info cleanly
            print(f"ID: {mid} | Status: {info.get('status', 'N/A')}")
            if i >= 35: break # Show all 33 items
        
        if len(pending_items) > 20:
            print(f"... and {len(pending_items)-20} more.")

    print("--- Diagnostic End ---")

if __name__ == "__main__":
    main()
