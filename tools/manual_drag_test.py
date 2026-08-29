from __future__ import annotations

import json
import sys
import time
from pathlib import Path


def main() -> int:
    # This is an operator tool, not an auto-run pytest module. Keeping all
    # browser work behind main() makes collection and imports side-effect free.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from src.captcha_solver import CaptchaSolver

    test_page = Path(__file__).resolve().parents[1] / "tools" / "test_captcha_page.html"
    target_url = f"file:///{test_page.as_posix()}"
    solver = CaptchaSolver(port=9223, target_url=target_url)
    if not solver.connect_tab():
        return 1

    try:
        solver._bring_to_front()
        time.sleep(2)

        slider_info = solver._find_slider()
        if not slider_info:
            print("No slider found")
            return 1

        print(f"Slider: {slider_info}")
        start_x = slider_info["x"] + (slider_info["width"] / 2)
        start_y = slider_info["y"] + (slider_info["height"] / 2)
        track_width = solver._get_track_width()
        distance = track_width - slider_info["width"]
        print(f"\nDragging from ({start_x}, {start_y}), distance: {distance}px")
        solver._do_drag(start_x, start_y, distance)

        print("\nWaiting for result...")
        time.sleep(4)

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
            result = ret["result"].get("value", {})
            print("\nPage state after drag:")
            print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    finally:
        if solver.ws is not None:
            solver.ws.close()


if __name__ == "__main__":
    raise SystemExit(main())
