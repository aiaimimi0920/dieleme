"""2Captcha付费服务集成 - 95%+成功率"""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from twocaptcha import TwoCaptcha
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "2captcha-python", "playwright", "playwright-stealth"])
    from twocaptcha import TwoCaptcha
    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth


def solve_with_2captcha(target_url, api_key):
    """使用2Captcha付费服务 - 95%+成功率"""
    print("启动2Captcha付费服务...")

    solver = TwoCaptcha(api_key)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        stealth = Stealth()
        stealth.apply_stealth_sync(page)

        page.goto(target_url, timeout=60000)
        time.sleep(3)

        # 查找验证码图片
        slider = page.query_selector('#nc_1_n1z, .btn_slide')
        if not slider:
            print("未找到滑块")
            browser.close()
            return False

        print("发现滑块，截图并发送到2Captcha...")

        # 截取验证码区域
        try:
            captcha_area = page.query_selector('.nc_wrapper')
            if captcha_area:
                screenshot = captcha_area.screenshot()

                # 发送到2Captcha识别
                print("正在识别中（人工识别，通常10-30秒）...")
                result = solver.coordinates({
                    'body': screenshot,
                    'textinstructions': 'Drag slider to fit puzzle',
                })

                # 获取坐标
                coords = result['code']
                print(f"✅ 2Captcha返回坐标: {coords}")

                # 解析x坐标
                x_offset = int(coords.split('=')[1].split(',')[0])

                # 拖动
                box = slider.bounding_box()
                start_x = box['x'] + box['width']/2
                start_y = box['y'] + box['height']/2

                page.mouse.move(start_x, start_y)
                time.sleep(0.3)
                page.mouse.down()
                time.sleep(0.2)
                page.mouse.move(start_x + x_offset, start_y)
                time.sleep(0.5)
                page.mouse.up()

                print("拖动完成，等待验证...")
                time.sleep(3)

                if '验证通过' in page.content():
                    print("✅✅✅ 2Captcha方案成功！")
                    browser.close()
                    return True
                else:
                    print("❌ 验证失败")
            else:
                print("未找到验证码区域")
        except Exception as e:
            print(f"2Captcha错误: {e}")

        browser.close()
        return False


if __name__ == "__main__":
    # 需要2Captcha API Key
    api_key = input("请输入2Captcha API Key: ")
    url = sys.argv[1] if len(sys.argv) > 1 else "https://login.taobao.com"

    print("="*70)
    print("2Captcha付费服务 - 95%+成功率")
    print("="*70)

    result = solve_with_2captcha(url, api_key)
    sys.exit(0 if result else 1)
