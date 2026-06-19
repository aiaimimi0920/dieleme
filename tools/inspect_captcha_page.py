import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.captcha_solver import CaptchaSolver

test_page = Path(__file__).resolve().parents[1] / "tools" / "test_captcha_page.html"
target_url = f"file:///{test_page.as_posix()}"

solver = CaptchaSolver(port=9223, target_url=target_url)

# Connect and inspect
if not solver.connect_tab():
    print("Failed to connect")
    sys.exit(1)

print("Connected. Inspecting page...")

# Check what's on the page
js_inspect = """
(function() {
    var result = {
        title: document.title,
        bodyText: document.body ? document.body.innerText.substring(0, 200) : '',
        iframes: [],
        sliderElements: []
    };

    // Check for slider in main doc
    var selectors = ['#nc_1_n1z', '.btn_slide', '.nc-slider-btn', '#mock-slider-handle'];
    for (var i = 0; i < selectors.length; i++) {
        var el = document.querySelector(selectors[i]);
        if (el) {
            result.sliderElements.push({context: 'main', selector: selectors[i], visible: el.offsetParent !== null});
        }
    }

    // Check iframes
    var frames = document.getElementsByTagName('iframe');
    for (var i = 0; i < frames.length; i++) {
        try {
            var iframe = frames[i];
            result.iframes.push({
                src: iframe.src || '',
                id: iframe.id || '',
                accessible: false
            });
            var doc = iframe.contentDocument;
            if (doc) {
                result.iframes[i].accessible = true;
                for (var j = 0; j < selectors.length; j++) {
                    var el = doc.querySelector(selectors[j]);
                    if (el) {
                        result.sliderElements.push({context: 'iframe_' + i, selector: selectors[j], visible: el.offsetParent !== null});
                    }
                }
            }
        } catch(e) {
            result.iframes[i].error = e.toString();
        }
    }

    return result;
})()
"""

ret = solver._send_cdp("Runtime.evaluate", {
    "expression": js_inspect,
    "returnByValue": True
})

if ret and "result" in ret:
    import json
    data = ret["result"].get("value", {})
    print("\nPage inspection:")
    print(json.dumps(data, indent=2, ensure_ascii=False))
else:
    print("Failed to inspect page")

solver.ws.close()
