import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.captcha_solver import CaptchaSolver

test_page = Path(__file__).resolve().parents[1] / "tools" / "test_captcha_page.html"
solver = CaptchaSolver(port=9223, target_url=f"file:///{test_page.as_posix()}")

if not solver.connect_tab():
    sys.exit(1)

solver._bring_to_front()
time.sleep(2)

# Get initial slider position
js_get_pos = """
(function() {
    var slider = document.querySelector('#nc_1_n1t');
    if (!slider) return {error: 'no slider'};
    var rect = slider.getBoundingClientRect();
    return {x: rect.left, y: rect.top, width: rect.width, height: rect.height};
})()
"""

ret = solver._send_cdp("Runtime.evaluate", {"expression": js_get_pos, "returnByValue": True})
before = ret["result"]["value"] if ret and "result" in ret else {}
print(f"Before drag: {before}")

# Do drag
slider_info = solver._find_slider()
if slider_info:
    start_x = slider_info["x"] + slider_info["width"] / 2
    start_y = slider_info["y"] + slider_info["height"] / 2
    track_width = solver._get_track_width()
    distance = track_width - slider_info["width"] - 4

    print(f"\nDragging {distance}px from ({start_x}, {start_y})")
    solver._do_drag(start_x, start_y, distance)
    time.sleep(3)

    # Check final position
    ret2 = solver._send_cdp("Runtime.evaluate", {"expression": js_get_pos, "returnByValue": True})
    after = ret2["result"]["value"] if ret2 and "result" in ret2 else {}
    print(f"\nAfter drag: {after}")
    print(f"Position delta: {after.get('x', 0) - before.get('x', 0)}px")

solver.ws.close()
