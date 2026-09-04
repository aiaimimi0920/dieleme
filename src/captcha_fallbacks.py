from __future__ import annotations

from .captcha_context import *  # noqa: F401,F403


class CaptchaFallbacksMixin:
    def _solve_with_playwright(self):
        """Solve using Playwright."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return False

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False, args=['--disable-blink-features=AutomationControlled'])
                context = browser.new_context(viewport={'width': 1920, 'height': 1080})
                context.add_init_script('Object.defineProperty(navigator, "webdriver", {get: () => undefined});')
                page = context.new_page()
                page.goto(self.target_url, timeout=30000)
                time.sleep(2)

                slider = page.query_selector('#nc_1_n1z, .btn_slide')
                if not slider:
                    browser.close()
                    return False

                box = slider.bounding_box()
                track = page.query_selector('#nc_1_n1t, .nc_scale')
                distance = track.bounding_box()['width'] - box['width'] - 10 if track else 260

                tracks = []
                current, mid, v = 0, distance * 4/5, 0
                while current < distance:
                    import random
                    a = random.randint(2,4) if current < mid else -random.randint(3,5)
                    s = v * 0.2 + 0.5 * a * 0.04
                    current += s
                    tracks.append(round(s))
                    v += a * 0.2
                tracks.extend([-random.randint(1,2) for _ in range(3)])

                start_x, start_y = box['x'] + box['width']/2, box['y'] + box['height']/2
                page.mouse.move(start_x, start_y)
                time.sleep(0.3)
                page.mouse.down()
                time.sleep(0.2)

                cx = start_x
                for t in tracks:
                    cx += t
                    page.mouse.move(cx, start_y + random.uniform(-1, 1))
                    time.sleep(0.01)

                time.sleep(0.5)
                page.mouse.up()
                time.sleep(3)

                success = '验证通过' in page.content()
                browser.close()
                return success
        except:
            return False

    def _solve_with_userscript(self):
        """Try to solve using injected userscript."""
        if not self.connect_tab():
            return False

        self._bring_to_front()
        time.sleep(1)

        # Check if slider exists
        slider_check = self._find_slider()
        if not slider_check:
            return False

        print("[SOLVER] Injecting userscript...")

        # Read userscript
        import os
        script_path = os.path.join(os.path.dirname(__file__), "..", "userscripts", "nc_captcha_solver.user.js")

        try:
            with open(script_path, 'r', encoding='utf-8') as f:
                userscript = f.read()
                # Remove userscript header
                userscript = '\n'.join([line for line in userscript.split('\n')
                                       if not line.strip().startswith('// @')])
        except:
            print("[SOLVER] Userscript file not found")
            return False

        # Inject script
        self._send_cdp("Runtime.evaluate", {
            "expression": userscript
        })

        time.sleep(0.5)

        # Trigger solve
        trigger_js = "window.solveNCCaptcha ? window.solveNCCaptcha() : false"
        ret = self._send_cdp("Runtime.evaluate", {
            "expression": trigger_js,
            "returnByValue": True
        })

        print("[SOLVER] Userscript triggered, waiting for result...")
        time.sleep(4)

        # Check success
        result = self._verify_success()

        if self.ws:
            try:
                self.ws.close()
            except:
                pass

        if result:
            print("[SOLVER] [OK] Userscript method succeeded!")

        return result

    def _solve_with_playwright_stealth(self):
        """Playwright Stealth - the method that worked before!"""
        try:
            from playwright.sync_api import sync_playwright
            from playwright_stealth import Stealth
            import random
        except ImportError:
            return False

        print("[SOLVER] Starting Playwright Stealth...")

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                page = browser.new_page()

                # Apply stealth - KEY!
                stealth = Stealth()
                stealth.apply_stealth_sync(page)

                page.goto(self.target_url, timeout=60000)
                time.sleep(3)

                slider = page.query_selector('#nc_1_n1z, .btn_slide, .nc-slider-btn')
                if not slider:
                    browser.close()
                    return False

                box = slider.bounding_box()
                track = page.query_selector('#nc_1_n1t, .nc_scale')
                distance = track.bounding_box()['width'] - box['width'] - 10 if track else 260

                print(f"[SOLVER] Playwright Stealth drag: {distance}px")

                tracks = []
                current, mid, v = 0, distance * 4/5, 0
                while current < distance:
                    a = random.randint(2,4) if current < mid else -random.randint(3,5)
                    s = v * 0.2 + 0.5 * a * 0.04
                    current += s
                    tracks.append(round(s))
                    v += a * 0.2
                tracks.extend([-random.randint(1,2) for _ in range(3)])

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
                browser.close()

                if success:
                    print("[SOLVER] [OK] Playwright Stealth succeeded!")
                return success
        except Exception as e:
            print(f"[SOLVER] Playwright Stealth error: {e}")
            return False

    def _solve_with_ddddocr(self):
        """AI识别距离"""
        try:
            import ddddocr
            from playwright.sync_api import sync_playwright
            from playwright_stealth import Stealth
        except ImportError:
            return False

        try:
            det = ddddocr.DdddOcr(det=False, ocr=False, show_ad=False)

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=False)
                page = browser.new_page()
                stealth = Stealth()
                stealth.apply_stealth_sync(page)

                page.goto(self.target_url, timeout=60000)
                time.sleep(3)

                slider = page.query_selector('#nc_1_n1z, .btn_slide')
                if not slider:
                    browser.close()
                    return False

                # 截图识别
                bg = page.query_selector('.nc_bg, canvas')
                slider_img = page.query_selector('.nc_slider')

                if bg and slider_img:
                    bg_bytes = bg.screenshot()
                    slider_bytes = slider_img.screenshot()
                    distance = det.slide_match(slider_bytes, bg_bytes)
                    print(f"[SOLVER] ddddocr识别距离: {distance}px")
                else:
                    track = page.query_selector('#nc_1_n1t')
                    box = slider.bounding_box()
                    distance = track.bounding_box()['width'] - box['width'] - 10 if track else 260

                # 拖动
                import random
                box = slider.bounding_box()
                start_x, start_y = box['x'] + box['width']/2, box['y'] + box['height']/2
                page.mouse.move(start_x, start_y)
                time.sleep(0.3)
                page.mouse.down()
                time.sleep(0.2)

                cx = start_x
                for i in range(int(distance/5)):
                    cx += 5
                    page.mouse.move(cx, start_y + random.uniform(-1, 1))
                    time.sleep(0.015)

                page.mouse.up()
                time.sleep(3)

                success = '验证通过' in page.content()
                browser.close()

                if success:
                    print("[SOLVER] [OK] ddddocr AI识别成功!")
                return success
        except Exception as e:
            print(f"[SOLVER] ddddocr error: {e}")
            return False


    def _solve_with_opencv(self):
        """OpenCV边缘检测找缺口 - 从博客学到的方案"""
        try:
            import cv2
            import numpy as np
            from playwright.sync_api import sync_playwright
            from playwright_stealth import Stealth
        except ImportError:
            return False

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                stealth = Stealth()
                stealth.apply_stealth_sync(page)

                page.goto(self.target_url, timeout=60000)
                time.sleep(3)

                slider = page.query_selector('#nc_1_n1z, .btn_slide')
                if not slider:
                    browser.close()
                    return False

                # 截图并用OpenCV找缺口
                bg_area = page.query_selector('.nc_wrapper')
                if bg_area:
                    bg_bytes = bg_area.screenshot()
                    nparr = np.frombuffer(bg_bytes, np.uint8)
                    bg = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
                    bg = cv2.GaussianBlur(bg, (3,3), 0)
                    edges = cv2.Canny(bg, 100, 200)

                    height, width = edges.shape
                    gap_x = None
                    for x in range(50, width-50):
                        if np.sum(edges[:, x:x+1]) > height * 20:
                            left = np.mean(bg[:, max(0,x-10):x])
                            right = np.mean(bg[:, x:min(width,x+10)])
                            if abs(left-right) > 30:
                                gap_x = x
                                break

                    distance = gap_x - 40 if gap_x else 260
                    print(f"[SOLVER] OpenCV检测距离: {distance}px")
                else:
                    distance = 260

                # 拖动
                import random
                box = slider.bounding_box()
                start_x, start_y = box['x'] + box['width']/2, box['y'] + box['height']/2
                page.mouse.move(start_x, start_y)
                time.sleep(0.4)
                page.mouse.down()
                time.sleep(0.2)

                cx = start_x
                for i in range(int(distance/5)):
                    cx += 5
                    page.mouse.move(cx, start_y + random.uniform(-1,1))
                    time.sleep(0.015)

                page.mouse.up()
                time.sleep(3)

                success = '验证通过' in page.content()
                browser.close()

                if success:
                    print("[SOLVER] [OK] OpenCV边缘检测成功!")
                return success
        except Exception as e:
            print(f"[SOLVER] OpenCV error: {e}")
            return False


__all__ = ["CaptchaFallbacksMixin"]
