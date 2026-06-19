"""ddddocr AI识别滑块距离 - 新方案！"""
import sys
import time
import random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import ddddocr
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "ddddocr", "playwright", "playwright-stealth"])
    import ddddocr
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth


def solve_with_ddddocr(target_url):
    """使用ddddocr AI识别距离"""
    print("启动ddddocr AI Solver...")

    # 初始化ddddocr
    det = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        # 应用stealth
        stealth = Stealth()
        stealth.apply_stealth_sync(page)

        page.goto(target_url, timeout=60000)
        time.sleep(3)

        # 查找滑块和背景图
        slider = page.query_selector('#nc_1_n1z, .btn_slide')
        if not slider:
            print("未找到滑块")
            browser.close()
            return False

        # 截取背景图和滑块图
        # 淘宝NC验证码的图片通常在canvas或img标签中
        bg_img = page.query_selector('.nc_bg, canvas')
        slider_img = page.query_selector('.nc_slider, .slider-img')

        if bg_img and slider_img:
            print("找到背景和滑块图片，使用ddddocr计算距离...")

            try:
                # 截图
                bg_bytes = bg_img.screenshot()
                slider_bytes = slider_img.screenshot()

                # AI识别距离
                distance = det.slide_match(slider_bytes, bg_bytes)
                print(f"✅ ddddocr识别距离: {distance}px")
            except Exception as e:
                print(f"ddddocr识别失败: {e}")
                # 回退到默认距离
                track = page.query_selector('#nc_1_n1t')
                if track:
                    box = slider.bounding_box()
                    distance = track.bounding_box()['width'] - box['width'] - 10
                else:
                    distance = 260
                print(f"使用默认距离: {distance}px")
        else:
            print("未找到图片元素，使用默认距离")
            track = page.query_selector('#nc_1_n1t')
            box = slider.bounding_box()
            distance = track.bounding_box()['width'] - box['width'] - 10 if track else 260

        # 生成轨迹
        tracks = []
        current, v = 0, 0
        while current < distance:
            a = random.randint(2,4) if current < distance*0.8 else -random.randint(3,5)
            s = v * 0.2 + 0.5 * a * 0.04
            current += s
            tracks.append(round(s))
            v += a * 0.2
        for _ in range(3):
            tracks.append(-random.randint(1,2))

        # 拖动
        box = slider.bounding_box()
        start_x, start_y = box['x'] + box['width']/2, box['y'] + box['height']/2

        page.mouse.move(start_x, start_y)
        time.sleep(0.4)
        page.mouse.down()
        time.sleep(0.2)

        cx = start_x
        for t in tracks:
            cx += t
            page.mouse.move(cx, start_y + random.uniform(-1.5, 1.5))
            time.sleep(0.015)

        time.sleep(0.5)
        page.mouse.up()
        time.sleep(3)

        success = '验证通过' in page.content()

        if success:
            print("✅✅✅ ddddocr方案成功！")
        else:
            print("❌ 失败")

        browser.close()
        return success


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://login.taobao.com"

    print("="*70)
    print("ddddocr AI Solver - 中国专业验证码识别方案")
    print("="*70)

    result = solve_with_ddddocr(url)
    sys.exit(0 if result else 1)
