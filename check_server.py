
import requests
import json

try:
    response = requests.get("http://127.0.0.1:8001/api/status", timeout=5)
    if response.status_code == 200:
        data = response.json()
        print("Server Status:")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        
        # Also check /get_tasks directly
        print("\nChecking /get_tasks...")
        tasks_resp = requests.post("http://127.0.0.1:8001/api/get_tasks", json={}, timeout=5)
        if tasks_resp.status_code == 200:
            tasks_data = tasks_resp.json()
            print(f"Tasks Returned: {len(tasks_data.get('tasks', []))}")
            if tasks_data.get('tasks'):
                print("Sample Task:", tasks_data['tasks'][0])
        else:
            print(f"Error calling /get_tasks: {tasks_resp.status_code}")
            
    else:
        print(f"Error: Server returned {response.status_code}")
except Exception as e:
    print(f"Error connecting to server: {e}")
