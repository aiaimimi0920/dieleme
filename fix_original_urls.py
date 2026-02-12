import os
import json
import glob
import re

DATA_DIR = r"c:\Users\Public\nas_home\project\fapaifang\datas\archive"

def fix_urls():
    print(f"Scanning {DATA_DIR}...")
    
    # Recursively find all json files
    files = glob.glob(os.path.join(DATA_DIR, "**", "*.json"), recursive=True)
    
    total_fixed = 0
    files_changed = 0
    
    for filepath in files:
        changed = False
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if not isinstance(data, list):
                continue
                
            for item in data:
                item_id = item.get("id")
                original_url = item.get("原始网站", "")
                
                if not item_id:
                    continue
                    
                # Check if URL is malformed
                # Valid format: https://sf-item.taobao.com/sf_item/{id}.htm...
                # Bad format examples: https://sf.taobao.com/0512, empty, or missing ID
                
                expected_base = f"https://sf-item.taobao.com/sf_item/{item_id}.htm"
                
                is_valid = False
                if original_url and f"sf-item/{item_id}.htm" in original_url:
                    is_valid = True
                elif original_url and f"sf_item/{item_id}.htm" in original_url: # Handle underscore
                    is_valid = True
                    
                if not is_valid:
                    # Fix it
                    new_url = expected_base # We omit track_id as it's not essential and hard to fake consistently
                    item["原始网站"] = new_url
                    changed = True
                    total_fixed += 1
                    # print(f"Fixed {item_id}: {original_url} -> {new_url}")

            if changed:
                print(f"Updating {filepath}...")
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                files_changed += 1
                
        except Exception as e:
            print(f"Error processing {filepath}: {e}")

    print(f"Done! Fixed {total_fixed} items across {files_changed} files.")

if __name__ == "__main__":
    fix_urls()
