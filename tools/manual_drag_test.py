import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.captcha_solver import CaptchaSolver

test_page = Path(__file__).resolve().parents[1] / "tools" / "test_captcha_page.html"
target_url = f"file:///{test_page.as_posix()}"

solver = CaptchaSolver(port=9223, target_url=target_url)
if not solver.connect_tab():
    sys.exit(1)

solver._bring_to_front()
time.sleep(2)

# Find slider
slider_info = solver._find_slider()
if not slider_info:
    print("No slider found")
    sys.exit(1)

print(f"Slider: {slider_info}")

start_x = slider_info["x"] + (slider_info["width"] / 2)
start_y = slider_info["y"] + (slider_info["height"] / 2)

track_width = solver._get_track_width()
distance = track_width - slider_info["width"]

print(f"\nDragging from ({start_x}, {start_y}), distance: {distance}px")

# Do the drag
solver._do_drag(start_x, start_y, distance)

print("\nWaiting for result...")
time.sleep(4)

# Check page state
js_check = """
(function() {
    var body = document.body.innerText;
    var slider = document.querySelector('#nc_1_n1t, .icon-slide-arrow');
    var container = document.querySelector('.nc-container');

    return {
        bodyText: body.substring(0, 300),
        sliderExists: !!slider,
        sliderVisible: slider ? slider.offsetParent !== null : false,
        containerClass: container ? container.className : '',
        hasSuccess: body.indexOf('验证通过') >= 0 || body.indexOf('通过') >= 0,
        hasError: body.indexOf('失败') >= 0 || body.indexOf('错误') >= 0 || body.indexOf('再试') >= 0
    };
})()
"""

ret = solver._send_cdp("Runtime.evaluate", {"expression": js_check, "returnByValue": True})
if ret and "result" in ret:
    import json
    result = ret["result"].get("value", {})
    print("\nPage state after drag:")
    print(json.dumps(result, indent=2, ensure_ascii=False))

solver.ws.close()
