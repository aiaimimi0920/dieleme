"""Real mouse control solver using pyautogui for NC captcha."""
import sys
import time
import random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import pyautogui
except ImportError:
    print("Installing pyautogui...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "pyautogui", "pillow"])
    import pyautogui

from src.captcha_solver import CaptchaSolver

def solve_with_real_mouse(target_url, port=9223):
    """Use real OS-level mouse to drag slider."""

    # Connect to get slider position
    solver = CaptchaSolver(port=port, target_url=target_url)

    if not solver.connect_tab():
        print("Failed to connect")
        return False

    solver._bring_to_front()
    time.sleep(2)

    # Find slider
    slider_info = solver._find_slider()
    if not slider_info:
        print("Slider not found")
        return False

    # Get browser window position
    js_window = """
    (function() {
        return {
            screenX: window.screenX,
            screenY: window.screenY,
            innerWidth: window.innerWidth,
            innerHeight: window.innerHeight
        };
    })()
    """

    ret = solver._send_cdp("Runtime.evaluate", {
        "expression": js_window,
        "returnByValue": True
    })

    if not ret or "result" not in ret:
        print("Failed to get window position")
        return False

    window_info = ret["result"].get("value", {})

    # Calculate absolute screen position
    screen_x = window_info.get("screenX", 0) + slider_info["x"] + slider_info["width"] / 2
    screen_y = window_info.get("screenY", 0) + slider_info["y"] + slider_info["height"] / 2 + 80  # +80 for browser chrome

    track_width = solver._get_track_width()
    distance = track_width - slider_info["width"] - 4

    print(f"Window at: ({window_info.get('screenX')}, {window_info.get('screenY')})")
    print(f"Slider at viewport: ({slider_info['x']}, {slider_info['y']})")
    print(f"Screen position: ({screen_x:.0f}, {screen_y:.0f})")
    print(f"Will drag {distance:.0f}px")

    # Use pyautogui for real mouse movement
    pyautogui.PAUSE = 0.05
    pyautogui.FAILSAFE = True

    # Move to start
    pyautogui.moveTo(screen_x, screen_y, duration=random.uniform(0.3, 0.6))
    time.sleep(random.uniform(0.2, 0.4))

    # Press and hold
    pyautogui.mouseDown()
    time.sleep(random.uniform(0.1, 0.3))

    # Drag with realistic movement
    duration = random.uniform(1.2, 2.0)
    steps = int(distance / 5)  # ~5px per step

    for i in range(steps):
        progress = (i + 1) / steps
        # Ease-out curve
        ease = 1 - (1 - progress) ** 2

        dx = distance * ease
        dy = random.uniform(-3, 3) * (1 - progress)  # Less jitter near end

        target_x = screen_x + dx
        target_y = screen_y + dy

        pyautogui.moveTo(target_x, target_y, duration=duration / steps)

        # Random micro-pause
        if random.random() < 0.1:
            time.sleep(random.uniform(0.02, 0.08))

    # Hold at end
    time.sleep(random.uniform(0.4, 0.8))

    # Release
    pyautogui.mouseUp()
    time.sleep(2)

    # Check result
    result = solver._verify_success()
    solver.ws.close()

    return result


if __name__ == "__main__":
    punish_url = sys.argv[1] if len(sys.argv) > 1 else "https://sf-item.taobao.com/sf_item/738888888888.htm/_____tmd_____/punish?x5secdata=test&x5step=1"

    print("Testing with REAL MOUSE control...")
    print("Make sure browser window is visible!")
    time.sleep(3)

    result = solve_with_real_mouse(punish_url)

    if result:
        print("\n✅ SUCCESS - Captcha solved with real mouse!")
    else:
        print("\n❌ FAILED - Even real mouse didn't work")
