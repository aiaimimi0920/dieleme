"""Undetected ChromeDriver solver - best chance to bypass detection."""
import sys
import time
import random
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver import ActionChains
except ImportError:
    print("Installing undetected-chromedriver...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "undetected-chromedriver", "selenium"])
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver import ActionChains


def solve_with_undetected(target_url):
    """Use undetected-chromedriver to bypass detection."""
    print("Starting undetected-chromedriver solver...")

    # Setup options
    options = uc.ChromeOptions()
    options.add_argument('--disable-blink-features=AutomationControlled')

    # Create driver
    driver = uc.Chrome(options=options, use_subprocess=True)

    try:
        driver.get(target_url)
        time.sleep(3)

        # Find slider
        slider_selectors = ['#nc_1_n1z', '.btn_slide', '.nc-slider-btn']
        slider = None

        for sel in slider_selectors:
            try:
                slider = driver.find_element(By.CSS_SELECTOR, sel)
                if slider:
                    print(f"Found slider: {sel}")
                    break
            except:
                continue

        if not slider:
            print("No slider found")
            driver.quit()
            return False

        # Get track width
        try:
            track = driver.find_element(By.CSS_SELECTOR, '#nc_1_n1t, .nc_scale')
            track_width = track.size['width']
        except:
            track_width = 300

        distance = track_width - slider.size['width'] - 10
        print(f"Will drag {distance}px")

        # Generate human-like track
        tracks = []
        current, mid, v = 0, distance * 4/5, 0
        while current < distance:
            a = random.randint(2, 4) if current < mid else -random.randint(3, 5)
            s = v * 0.2 + 0.5 * a * 0.04
            current += s
            tracks.append(round(s))
            v += a * 0.2

        # Add correction
        for _ in range(3):
            tracks.append(-random.randint(1, 2))

        # Execute drag
        actions = ActionChains(driver)
        actions.click_and_hold(slider).perform()
        time.sleep(random.uniform(0.1, 0.2))

        for track in tracks:
            actions.move_by_offset(track, random.randint(-2, 2)).perform()
            time.sleep(random.uniform(0.01, 0.02))

        time.sleep(random.uniform(0.3, 0.5))
        actions.release().perform()

        print("Drag completed, checking result...")
        time.sleep(3)

        # Check success
        page_text = driver.page_source
        success = '验证通过' in page_text or '成功' in page_text

        if success:
            print("✅ SUCCESS with undetected-chromedriver!")
        else:
            # Check for error
            try:
                error_elem = driver.find_element(By.CSS_SELECTOR, '.errloading, .nc-lang-cnt')
                print(f"Error: {error_elem.text}")
            except:
                pass
            print("❌ Failed")

        time.sleep(3)
        driver.quit()
        return success

    except Exception as e:
        print(f"Error: {e}")
        driver.quit()
        return False


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://login.taobao.com/member/login.jhtml"

    print(f"Testing URL: {url}")
    result = solve_with_undetected(url)

    sys.exit(0 if result else 1)
