import json

from src.collection_api_credentials import configured_api_base
from tools.internal_api_http import fetch_json, post_json

try:
    base = configured_api_base()
    data = fetch_json(base + "/status", timeout=5)
    if isinstance(data, dict):
        print("Server Status:")
        print(json.dumps(data, indent=2, ensure_ascii=False))

        # Also check /get_tasks directly
        print("\nChecking /get_tasks...")
        tasks_data = post_json(base + "/get_tasks", {}, timeout=5)
        if isinstance(tasks_data, dict):
            print(f"Tasks Returned: {len(tasks_data.get('tasks', []))}")
            if tasks_data.get("tasks"):
                print("Sample Task:", tasks_data["tasks"][0])
        else:
            print("Invalid task response")

    else:
        print("Invalid server status response")
except Exception as e:
    print(f"Error connecting to server: {e}")
