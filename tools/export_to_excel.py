import os
import json
import glob
import pandas as pd
from datetime import datetime

# Configuration
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATAS_DIR = os.path.join(BASE_DIR, 'datas')
ARCHIVE_DIR = os.path.join(DATAS_DIR, 'archive')
OUTPUT_FILE = os.path.join(BASE_DIR, f'fapaifang_data_{datetime.now().strftime("%Y%m%d")}.xlsx')

# Column Order (matching data_fixer.py schema)
COLUMNS = [
    'id', 'title', 
    '评估价', '起拍价', '成交价', '面积', '单价',
    '省份', '城市', '区', '地点', '所属小区', '最靠近商圈',
    '交易时间', '竞拍人数', '出价人数', 
    'url', 'json_file'
]

# Column Mapping: {JSON_Key: Excel_Column_Name}
COLUMN_MAPPING = {
    '市场评估价': '评估价',
    '起拍价格': '起拍价',
    '成交价格': '成交价',
    '建筑面积': '面积'
}

def load_data():
    """Load all JSON files from datas/archive recursively."""
    all_items = []
    seen_ids = set()
    
    # 1. Scan archive (recursive)
    archive_files = glob.glob(os.path.join(ARCHIVE_DIR, '**', '*.json'), recursive=True)
    # 2. Scan root datas/*.json (optional, but data_fixer does it)
    root_files = glob.glob(os.path.join(DATAS_DIR, '*.json'))
    
    files_to_scan = root_files + archive_files
    print(f"[INFO] Found {len(files_to_scan)} JSON files.")

    for file_path in files_to_scan:
        # Skip config files
        if any(x in file_path for x in ['model_config.json', 'monitor_state.json', 'all_locations.json', 'collected_locations.json', 'mock_data.json', 'mock_json']):
            continue
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = json.load(f)
                
            items = content if isinstance(content, list) else [content]
            
            for item in items:
                # Basic validation
                if not isinstance(item, dict): continue
                
                item_id = item.get('id')
                if not item_id: continue
                
                # De-duplication
                if item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                
                # Add file source for reference
                item['json_file'] = os.path.relpath(file_path, BASE_DIR)
                
                # 1. URL Priority: '原始网站' > 'url'
                item['url'] = item.get('原始网站') or item.get('url')
                
                # 2. Title from Location
                if item.get('地点'):
                    item['title'] = item.get('地点')
                
                # 3. Handle Unit Price & Validation
                try:
                    price = float(item.get('成交价格') or item.get('起拍价格') or 0)
                    area = float(item.get('建筑面积') or 0)
                    
                    # Filter incomplete data: Area, Price, Location
                    if not item.get('地点') or area <= 0 or price <= 0:
                        continue
                        
                    # Calculate Unit Price if executed
                    item['单价'] = round(price / area, 2)
                except:
                    continue

                all_items.append(item)
                
        except Exception as e:
            print(f"[WARN] Failed to read {file_path}: {e}")

    return all_items

def main():
    print("Starting data export...")
    data = load_data()
    print(f"[INFO] Loaded {len(data)} unique items.")
    
    if not data:
        print("[WARN] No data found to export.")
        return

    # Convert to DataFrame
    df = pd.DataFrame(data)
    
    # RENAME columns based on mapping
    df.rename(columns=COLUMN_MAPPING, inplace=True)
    
    # Filter and Reorder columns based on user's COLUMNS list
    # Use list comprehension to select only columns that exist in df
    final_cols = [c for c in COLUMNS if c in df.columns]
    
    # Warn about missing columns
    missing_cols = set(COLUMNS) - set(final_cols)
    if missing_cols:
        print(f"[INFO] Skipped missing columns: {missing_cols}")
        
    df = df[final_cols]
    
    # Export to Excel
    try:
        print(f"[INFO] Saving to {OUTPUT_FILE}...")
        df.to_excel(OUTPUT_FILE, index=False, engine='openpyxl')
        print(f"[SUCCESS] Export complete! File saved at: {OUTPUT_FILE}")
    except ImportError:
        print("[ERROR] 'openpyxl' or 'pandas' library missing.")
        print("Please install them using: pip install pandas openpyxl")
    except Exception as e:
        print(f"[ERROR] Export failed: {e}")

if __name__ == '__main__':
    main()
