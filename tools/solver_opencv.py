"""OpenCV边缘检测找缺口 - 图像识别方案"""
import sys
import time
import random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import cv2
    import numpy as np
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "opencv-python", "playwright", "playwright-stealth"])
    import cv2
    import numpy as np
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth


def find_gap_position(bg_img_bytes, slider_img_bytes=None):
    """使用边缘检测找缺口位置"""
    # 转换为OpenCV格式
    nparr = np.frombuffer(bg_img_bytes, np.uint8)
    bg = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)

    # 高斯模糊
    bg = cv2.GaussianBlur(bg, (3, 3), 0)

    # Canny边缘检测
    edges = cv2.Canny(bg, 100, 200)

    # 查找垂直边缘（缺口位置）
    height, width = edges.shape

    for x in range(50, width - 50):  # 排除边缘
        col = edges[:, x:x+1]
        edge_sum = np.sum(col)

        # 强垂直边缘 = 缺口
        if edge_sum > height * 20:  # 阈值
            # 检查左右是否有明显差异（缺口特征）
            left = np.mean(bg[:, max(0, x-10):x])
            right = np.mean(bg[:, x:min(width, x+10)])

            if abs(left - right) > 30:
                return x

    return None


def solve_with_opencv(target_url):
    """使用OpenCV边缘检测"""
    print("启动OpenCV边缘检测方案...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        stealth = Stealth()
        stealth.apply_stealth_sync(page)

        page.goto(target_url, timeout=60000)
        time.sleep(3)

        slider = page.query_selector('#nc_1_n1z, .btn_slide')
        if not slider:
            print("未找到滑块")
            browser.close()
            return False

        print("找到滑块，截图分析...")

        # 截取背景图
        bg_area = page.query_selector('.nc_wrapper, #nc_1__scale_text')
        if bg_area:
            bg_bytes = bg_area.screenshot()

            # 使用边缘检测找缺口
            gap_x = find_gap_position(bg_bytes)

            if gap_x:
                print(f"✅ OpenCV检测到缺口位置: {gap_x}px")
                distance = gap_x - 40  # 减去滑块起始位置
            else:
                print("未检测到缺口，使用默认距离")
                track = page.query_selector('#nc_1_n1t')
                box = slider.bounding_box()
                distance = track.bounding_box()['width'] - box['width'] - 10 if track else 260
        else:
            distance = 260

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
            print("✅✅✅ OpenCV方案成功！")
        else:
            print("❌ 失败")

        browser.close()
        return success


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://login.taobao.com"

    print("="*70)
    print("OpenCV边缘检测方案 - 图像识别找缺口")
    print("="*70)

    result = solve_with_opencv(url)
    sys.exit(0 if result else 1)
