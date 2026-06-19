import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.captcha_solver import CaptchaSolver

test_page = Path(__file__).resolve().parents[1] / "tools" / "test_captcha_page.html"
target_url = f"file:///{test_page.as_posix()}"

solver = CaptchaSolver(port=9223, target_url=target_url)
if not solver.connect_tab():
    sys.exit(1)

# Find the draggable element (usually has specific classes or cursor style)
js_find_draggable = """
(function() {
    var slider = document.querySelector('.slider');
    if (!slider) return {error: 'no slider'};

    var btn = slider.querySelector('.nc-iconfont, .btn_slide, [class*="btn"], span');
    if (!btn) {
        // Try finding by position - rightmost child
        var children = slider.children;
        for (var i = children.length - 1; i >= 0; i--) {
            if (children[i].offsetParent !== null) {
                btn = children[i];
                break;
            }
        }
    }

    if (!btn) return {error: 'no button'};

    var rect = btn.getBoundingClientRect();
    return {
        tag: btn.tagName,
        id: btn.id,
        class: btn.className,
        x: rect.left,
        y: rect.top,
        width: rect.width,
        height: rect.height,
        html: btn.outerHTML.substring(0, 200)
    };
})()
"""

ret = solver._send_cdp("Runtime.evaluate", {
    "expression": js_find_draggable,
    "returnByValue": True
})

if ret and "result" in ret:
    import json
    data = ret["result"].get("value", {})
    print("Draggable element:")
    print(json.dumps(data, indent=2))

solver.ws.close()
