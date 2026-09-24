import time

from src.collection_api_credentials import configured_api_base
from src.collection_engine_restart import token
from tools.internal_api_http import fetch_json, post_json


def check():
    print("Attempting to unpause server...")
    try:
        base = configured_api_base()
        operator = token("operator")
        if not operator:
            raise OSError("An operator token file is required")
        headers = {"X-FAPAI-Control-Token": operator}
        result = post_json(
            base + "/collection/control/resume", {}, timeout=5, headers=headers
        )
        print(f"Resume Response: {result}")

        time.sleep(1)

        # 2. Check Status
        status_data = fetch_json(base + "/status", timeout=5)
        print(f"Server Paused: {status_data.get('paused')}")

        # Task claims are authenticated writes.
        tasks_data = post_json(base + "/get_tasks", {}, timeout=5, headers=headers)
        tasks = tasks_data.get("tasks", [])
        print(f"Tasks Returned: {len(tasks)}")
        if tasks:
            print(f"Sample Task: {tasks[0]}")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    check()
