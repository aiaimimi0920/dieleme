"""Canvas fingerprint anti-detection + enhanced stealth."""
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
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "undetected-chromedriver", "selenium"])
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By
    from selenium.webdriver import ActionChains


# Canvas fingerprint randomization script
CANVAS_DEFENDER = """
(function() {
    const toBlob = HTMLCanvasElement.prototype.toBlob;
    const toDataURL = HTMLCanvasElement.prototype.toDataURL;
    const getImageData = CanvasRenderingContext2D.prototype.getImageData;

    const noisify = function(canvas, context) {
        const imageData = getImageData.apply(context, [0, 0, canvas.width, canvas.height]);
        for (let i = 0; i < imageData.data.length; i += 4) {
            imageData.data[i] = imageData.data[i] + Math.floor(Math.random() * 10) - 5;
            imageData.data[i + 1] = imageData.data[i + 1] + Math.floor(Math.random() * 10) - 5;
            imageData.data[i + 2] = imageData.data[i + 2] + Math.floor(Math.random() * 10) - 5;
        }
        context.putImageData(imageData, 0, 0);
    };

    Object.defineProperty(HTMLCanvasElement.prototype, 'toBlob', {
        value: function() {
            noisify(this, this.getContext('2d'));
            return toBlob.apply(this, arguments);
        }
    });

    Object.defineProperty(HTMLCanvasElement.prototype, 'toDataURL', {
        value: function() {
            noisify(this, this.getContext('2d'));
            return toDataURL.apply(this, arguments);
        }
    });

    Object.defineProperty(CanvasRenderingContext2D.prototype, 'getImageData', {
        value: function() {
            const imageData = getImageData.apply(this, arguments);
            for (let i = 0; i < imageData.data.length; i += 4) {
                imageData.data[i] = imageData.data[i] + Math.floor(Math.random() * 10) - 5;
                imageData.data[i + 1] = imageData.data[i + 1] + Math.floor(Math.random() * 10) - 5;
                imageData.data[i + 2] = imageData.data[i + 2] + Math.floor(Math.random() * 10) - 5;
            }
            return imageData;
        }
    });

    // WebGL fingerprint randomization
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    Object.defineProperty(WebGLRenderingContext.prototype, 'getParameter', {
        value: function(param) {
            if (param === 37445) {
                return 'Intel Inc.';
            }
            if (param === 37446) {
                return 'Intel Iris OpenGL Engine';
            }
            return getParameter.apply(this, arguments);
        }
    });

    // AudioContext fingerprint
    const audioContext = window.AudioContext || window.webkitAudioContext;
    if (audioContext) {
        const OriginalAudioContext = audioContext;
        window.AudioContext = window.webkitAudioContext = function() {
            const context = new OriginalAudioContext();
            const originalCreateOscillator = context.createOscillator;
            context.createOscillator = function() {
                const oscillator = originalCreateOscillator.apply(this, arguments);
                const originalStart = oscillator.start;
                oscillator.start = function() {
                    oscillator.frequency.value = oscillator.frequency.value + (Math.random() * 0.0001 - 0.00005);
                    return originalStart.apply(this, arguments);
                };
                return oscillator;
            };
            return context;
        };
    }

    console.log('[AntiDetect] Canvas/WebGL/Audio fingerprint randomization enabled');
})();
"""


def solve_with_enhanced_stealth(target_url):
    """Enhanced anti-detection with fingerprint randomization."""
    print("Starting enhanced stealth solver...")

    options = uc.ChromeOptions()
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--no-sandbox')

    # Random user agent
    user_agents = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    ]
    options.add_argument(f'--user-agent={random.choice(user_agents)}')

    driver = uc.Chrome(options=options, use_subprocess=True, version_main=None)

    # Inject canvas defender before page load
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {'source': CANVAS_DEFENDER})

    # Additional stealth
    driver.execute_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
        Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
        window.chrome = {runtime: {}};
    """)

    try:
        driver.get(target_url)
        time.sleep(3)

        # Find slider
        slider = None
        for sel in ['#nc_1_n1z', '.btn_slide', '.nc-slider-btn']:
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

        # Calculate distance
        try:
            track = driver.find_element(By.CSS_SELECTOR, '#nc_1_n1t, .nc_scale')
            distance = track.size['width'] - slider.size['width'] - 10
        except:
            distance = 260

        print(f"Drag distance: {distance}px")

        # Human-like drag
        actions = ActionChains(driver)

        # Move to slider first (human behavior)
        actions.move_to_element(slider).perform()
        time.sleep(random.uniform(0.3, 0.6))

        actions.click_and_hold(slider).perform()
        time.sleep(random.uniform(0.15, 0.25))

        # Generate realistic track
        current = 0
        while current < distance:
            step = random.randint(5, 15)
            if current + step > distance:
                step = distance - current

            actions.move_by_offset(step, random.randint(-2, 2)).perform()
            current += step
            time.sleep(random.uniform(0.01, 0.03))

            # Random pause (human-like)
            if random.random() < 0.2:
                time.sleep(random.uniform(0.05, 0.15))

        # Overshoot and correct
        actions.move_by_offset(random.randint(5, 10), 0).perform()
        time.sleep(0.1)
        actions.move_by_offset(-random.randint(2, 5), 0).perform()

        time.sleep(random.uniform(0.4, 0.7))
        actions.release().perform()

        print("Drag completed")
        time.sleep(4)

        # Check result
        page_text = driver.page_source
        success = '验证通过' in page_text or '成功' in page_text or 'success' in page_text.lower()

        if success:
            print("✅ SUCCESS with enhanced stealth!")
        else:
            print("❌ Failed")

        time.sleep(3)
        driver.quit()
        return success

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        driver.quit()
        return False


if __name__ == "__main__":
    url = sys.argv[1] if len(sys.argv) > 1 else "https://login.taobao.com/member/login.jhtml"

    print("Enhanced Stealth Solver with Canvas/WebGL/Audio Fingerprint Randomization")
    print("="*70)

    result = solve_with_enhanced_stealth(url)
    sys.exit(0 if result else 1)
