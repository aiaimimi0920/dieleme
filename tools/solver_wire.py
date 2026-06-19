"""selenium-wire 拦截修改响应 - 绕过验证"""
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from seleniumwire import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver import ActionChains
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "selenium-wire", "selenium"])
    from seleniumwire import webdriver
    from selenium.webdriver.common.by import By
    from selenium.webdriver import ActionChains


def interceptor(request):
    """拦截请求"""
    # 可以修改请求头
    if 'x5sec' in request.url or 'captcha' in request.url:
        print(f"拦截到验证码请求: {request.url[:100]}")


def response_interceptor(request, response):
    """拦截并修改响应"""
    # 拦截验证码验证响应
    if 'captcha' in request.url or 'check' in request.url or 'verify' in request.url:
        print(f"拦截验证响应: {request.url[:100]}")
        print(f"状态: {response.status_code}")

        # 尝试修改响应为成功
        if response.status_code == 200:
            try:
                body = response.body.decode('utf-8')
                print(f"原始响应: {body[:200]}")

                # 如果包含失败标识，修改为成功
                if 'fail' in body.lower() or 'error' in body.lower():
                    modified = body.replace('"success":false', '"success":true')
                    modified = modified.replace('"pass":false', '"pass":true')
                    modified = modified.replace('"result":false', '"result":true')
                    response.body = modified.encode('utf-8')
                    print("✅ 响应已修改为成功")
            except Exception as e:
                print(f"修改失败: {e}")


def solve_with_wire(target_url):
    """使用selenium-wire拦截修改"""
    print("启动selenium-wire拦截方案...")

    options = webdriver.ChromeOptions()
    options.add_argument('--disable-blink-features=AutomationControlled')

    # 配置wire
    seleniumwire_options = {
        'disable_encoding': True
    }

    driver = webdriver.Chrome(
        options=options,
        seleniumwire_options=seleniumwire_options
    )

    # 设置拦截器
    driver.request_interceptor = interceptor
    driver.response_interceptor = response_interceptor

    try:
        driver.get(target_url)
        time.sleep(3)

        # 查找滑块
        try:
            slider = driver.find_element(By.CSS_SELECTOR, '#nc_1_n1z, .btn_slide')
            print("找到滑块，开始简单拖动...")

            # 简单拖动（响应会被拦截修改）
            actions = ActionChains(driver)
            actions.click_and_hold(slider).perform()
            time.sleep(0.2)

            for i in range(50):
                actions.move_by_offset(5, 0).perform()
                time.sleep(0.01)

            actions.release().perform()
            time.sleep(3)

            # 检查是否成功
            if '验证通过' in driver.page_source:
                print("✅✅✅ selenium-wire方案成功！")
                driver.quit()
                return True
            else:
                print("响应修改未生效")
        except:
            print("未找到滑块")

        driver.quit()
        return False

    except Exception as e:
        print(f"错误: {e}")
        driver.quit()
        return False


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://login.taobao.com"

    print("="*70)
    print("Selenium-Wire 响应拦截修改方案")
    print("="*70)

    result = solve_with_wire(url)
    sys.exit(0 if result else 1)
