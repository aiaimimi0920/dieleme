import json
import os

target_names = ['佛山','郑州','苏州','海南','重庆','兰州','厦门','杭州','天津','大连','济南','昆明']

def find_locations():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    json_path = os.path.join(base_dir, 'datas', 'all_locations.json')
    
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    results = {}
    
    with open('city_codes_result.txt', 'w', encoding='utf-8') as f:
        f.write("[\n")
        # Reuse traverse but redirect print? No, let's just pass the file handle
        def output(s):
            f.write(s + "\n")
            print(s)
            
        def traverse_refined(node):
            if isinstance(node, list):
                for item in node:
                    traverse_refined(item)
                return

            name = node.get('name', '')
            code = node.get('id', '')
            
            matched = next((t for t in target_names if t in name), None)
            
            if matched:
                output(f'  // {matched} - {name} ({code})')
                if 'children' in node:
                     for c in node['children']:
                         cid = c.get('id') or c.get('code')
                         if cid:
                             output(f'  "{cid}", // {c.get("name")}')
                
            if 'children' in node:
                traverse_refined(node['children'])

        traverse_refined(data)
        f.write("]\n")

if __name__ == '__main__':
    find_locations()

if __name__ == '__main__':
    find_locations()
