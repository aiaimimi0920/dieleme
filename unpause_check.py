
import requests
import json
import time

BASE_URL = "http://127.0.0.1:8001"

def check():
    print("Attempting to unpause server...")
    try:
        # 1. Resume
        resp = requests.get(f"{BASE_URL}/api/resume", timeout=5)
        print(f"Resume Response: {resp.status_code} {resp.text}")
        
        time.sleep(1)
        
        # 2. Check Status
        resp = requests.get(f"{BASE_URL}/api/status", timeout=5)
        status_data = resp.json()
        print(f"Server Paused: {status_data.get('paused')}")
        
        # 3. Get Tasks (GET)
        resp = requests.get(f"{BASE_URL}/api/get_tasks", timeout=5)
        tasks_data = resp.json()
        tasks = tasks_data.get('tasks', [])
        print(f"Tasks Returned: {len(tasks)}")
        if tasks:
            print(f"Sample Task: {tasks[0]}")
            
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    check()
