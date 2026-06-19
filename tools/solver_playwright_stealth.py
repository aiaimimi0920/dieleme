"""Playwright Stealth - the working solution!"""
import sys
import time
import random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright", "playwright-stealth"])
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth


def solve_with_playwright_stealth(target_url):
    """Use playwright-stealth - this is what worked before!"""
    print("Starting Playwright Stealth solver...")
    print("This uses the SAME stealth library that worked before!")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

        page = context.new_page()

        # Apply stealth - THIS IS THE KEY!
        stealth = Stealth()
        stealth.apply_stealth_sync(page)

        page.goto(target_url, wait_until='networkidle')
        time.sleep(3)

        # Find slider
        slider = page.query_selector('#nc_1_n1z, .btn_slide, .nc-slider-btn')
        if not slider:
            print("No slider found")
            browser.close()
            return False

        box = slider.bounding_box()
        track = page.query_selector('#nc_1_n1t, .nc_scale')

        if track:
            track_box = track.bounding_box()
            distance = track_box['width'] - box['width'] - 10
        else:
            distance = 260

        print(f"Drag distance: {distance}px")

        # Generate human-like track
        tracks = []
        current, mid, v = 0, distance * 4/5, 0
        while current < distance:
            a = random.randint(2, 4) if current < mid else -random.randint(3, 5)
            s = v * 0.2 + 0.5 * a * 0.04
            current += s
            tracks.append(round(s))
            v += a * 0.2

        for _ in range(3):
            tracks.append(-random.randint(1, 2))

        # Execute drag
        start_x = box['x'] + box['width']/2
        start_y = box['y'] + box['height']/2

        page.mouse.move(start_x, start_y)
        time.sleep(random.uniform(0.3, 0.5))

        page.mouse.down()
        time.sleep(random.uniform(0.15, 0.25))

        cx = start_x
        for t in tracks:
            cx += t
            page.mouse.move(cx, start_y + random.uniform(-1.5, 1.5))
            time.sleep(random.uniform(0.01, 0.025))

        time.sleep(random.uniform(0.4, 0.6))
        page.mouse.up()

        print("Drag completed, checking result...")
        time.sleep(4)

        # Check success
        content = page.content()
        success = '验证通过' in content or '成功' in content

        if success:
            print("✅✅✅ SUCCESS with Playwright Stealth! ✅✅✅")
            print("This is the method that worked before!")
        else:
            print("❌ Failed")

        time.sleep(3)
        browser.close()
        return success


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://login.taobao.com/member/login.jhtml"

    print("="*70)
    print("Playwright Stealth Solver - Your Working Solution")
    print("="*70)

    result = solve_with_playwright_stealth(url)
    sys.exit(0 if result else 1)
