"""Playwright-based captcha solver using OpenCV for gap detection."""
import sys
import time
import random
import math
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from playwright.sync_api import sync_playwright
    import cv2
    import numpy as np
except ImportError:
    print("Installing required packages...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "opencv-python-headless", "numpy"])
    from playwright.sync_api import sync_playwright
    import cv2
    import numpy as np


def detect_gap_opencv(screenshot_path):
    """Use OpenCV to detect gap position in captcha image."""
    img = cv2.imread(screenshot_path)
    if img is None:
        return None

    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 100, 200)

    # Find contours
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    # Look for gap (usually a distinctive rectangular region)
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if 30 < w < 80 and 30 < h < 80:  # Slider size range
            return x

    return None


def generate_track(distance):
    """Generate human-like movement track."""
    track = []
    current = 0
    mid = distance * 4 / 5
    t = 0.2
    v = 0

    while current < distance:
        if current < mid:
            a = random.randint(2, 4)
        else:
            a = -random.randint(3, 5)

        v0 = v
        s = v0 * t + 0.5 * a * (t ** 2)
        current += s
        track.append(round(s))
        v = v0 + a * t

    # Overshoot and correct
    for _ in range(3):
        track.append(-random.randint(2, 3))

    return track


def solve_with_playwright(target_url):
    """Solve captcha using Playwright."""
    print("Starting Playwright solver...")

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled']
        )

        context = browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        )

        page = context.new_page()

        # Navigate
        page.goto(target_url, wait_until='networkidle')
        time.sleep(2)

        # Find slider
        slider = page.query_selector('#nc_1_n1z') or page.query_selector('.btn_slide')
        if not slider:
            print("Slider not found")
            browser.close()
            return False

        # Get slider position
        box = slider.bounding_box()
        if not box:
            print("Failed to get slider position")
            browser.close()
            return False

        start_x = box['x'] + box['width'] / 2
        start_y = box['y'] + box['height'] / 2

        # Take screenshot for gap detection
        page.screenshot(path='captcha_screenshot.png')

        gap_x = detect_gap_opencv('captcha_screenshot.png')
        if gap_x:
            distance = gap_x - box['x']
            print(f"Detected gap at {gap_x}, distance: {distance}px")
        else:
            # Fallback to track width
            track = page.query_selector('#nc_1_n1t') or page.query_selector('.nc_scale')
            if track:
                track_box = track.bounding_box()
                distance = track_box['width'] - box['width'] - 10
            else:
                distance = 260

        print(f"Will drag {distance}px")

        # Generate movement track
        tracks = generate_track(distance)

        # Execute drag
        page.mouse.move(start_x, start_y)
        time.sleep(random.uniform(0.2, 0.4))

        page.mouse.down()
        time.sleep(random.uniform(0.1, 0.2))

        current_x = start_x
        for move in tracks:
            current_x += move
            page.mouse.move(current_x, start_y + random.uniform(-2, 2))
            time.sleep(random.uniform(0.01, 0.03))

        time.sleep(random.uniform(0.3, 0.5))
        page.mouse.up()

        print("Drag completed, checking result...")
        time.sleep(3)

        # Check success
        content = page.content()
        success = '验证通过' in content or 'success' in content.lower()

        if success:
            print("✅ SUCCESS!")
        else:
            print("❌ Failed")

        browser.close()
        return success


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://sf-item.taobao.com//sf_item/738888888888.htm/_____tmd_____/punish?x5secdata=test"

    result = solve_with_playwright(url)
    sys.exit(0 if result else 1)
