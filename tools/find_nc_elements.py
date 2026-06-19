import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.captcha_solver import CaptchaSolver

test_page = Path(__file__).resolve().parents[1] / "tools" / "test_captcha_page.html"
target_url = f"file:///{test_page.as_posix()}"

solver = CaptchaSolver(port=9223, target_url=target_url)

if not solver.connect_tab():
    print("Failed to connect")
    sys.exit(1)

print("Inspecting NC captcha DOM structure...")

# Get all elements that might be the slider
js_find_all = """
(function() {
    var result = [];

    // Find all elements with various attributes
    var all = document.querySelectorAll('*');
    for (var i = 0; i < all.length; i++) {
        var el = all[i];
        var id = el.id || '';
        var cls = el.className || '';
        var tag = el.tagName.toLowerCase();

        // Look for slider-like elements
        if (id.indexOf('nc') >= 0 || cls.indexOf('nc') >= 0 ||
            cls.indexOf('slide') >= 0 || cls.indexOf('btn') >= 0) {
            var rect = el.getBoundingClientRect();
            if (rect.width > 10 && rect.height > 10) {
                result.push({
                    tag: tag,
                    id: id,
                    class: cls,
                    text: el.innerText ? el.innerText.substring(0, 50) : '',
                    visible: el.offsetParent !== null,
                    width: rect.width,
                    height: rect.height
                });
            }
        }
    }

    return result.slice(0, 20);
})()
"""

ret = solver._send_cdp("Runtime.evaluate", {
    "expression": js_find_all,
    "returnByValue": True
})

if ret and "result" in ret:
    import json
    data = ret["result"].get("value", [])
    print(f"\nFound {len(data)} potential elements:")
    for item in data:
        print(f"\n  Tag: {item['tag']}")
        print(f"  ID: {item['id']}")
        print(f"  Class: {item['class']}")
        print(f"  Size: {item['width']}x{item['height']}")
        print(f"  Visible: {item['visible']}")
        print(f"  Text: {item['text']}")

solver.ws.close()
