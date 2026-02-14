import json
import re
import os

def update_priority():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    priority_path = os.path.join(base_dir, 'jobs', 'priority.json')
    codes_path = os.path.join(base_dir, 'city_codes_result.txt')
    
    # Load existing priority
    with open(priority_path, 'r', encoding='utf-8') as f:
        priority_list = json.load(f)
        
    print(f"Original count: {len(priority_list)}")
    
    # Read generated codes
    new_codes = []
    with open(codes_path, 'r', encoding='utf-8') as f:
        content = f.read()
        # Find all quoted digit strings
        matches = re.findall(r'"(\d+)"', content)
        new_codes = matches
        
    print(f"Found {len(new_codes)} new codes.")
    
    # Append unique
    added_count = 0
    for code in new_codes:
        if code not in priority_list:
            priority_list.append(code)
            added_count += 1
            
    print(f"Added {added_count} unique codes.")
    
    # Save back
    with open(priority_path, 'w', encoding='utf-8') as f:
        json.dump(priority_list, f, indent=2, ensure_ascii=False)
        
    print(f"Updated priority.json with total {len(priority_list)} codes.")

if __name__ == '__main__':
    update_priority()
