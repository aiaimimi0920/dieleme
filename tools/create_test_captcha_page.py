"""Create a test page with real Taobao captcha iframe for testing."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Generate a simple HTML that embeds a real captcha challenge
test_html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Captcha Test Page</title>
</head>
<body>
    <h2>Testing Captcha Solver</h2>
    <div id="captcha-container">
        <!-- Real Taobao NC captcha will be loaded here -->
        <div id="nc"></div>
    </div>

    <script src="https://g.alicdn.com/sd/nch5/index.js?t=2015052012"></script>
    <script>
        var nc = NoCaptcha.init({
            renderTo: '#nc',
            appkey: 'FFFF0N00000000009A0D',
            scene: 'nc_login',
            token: ['FFFF0N00000000009A0D', (new Date()).getTime(), Math.random()].join(':'),
            trans: {"key1": "code0"},
            elementID: ["usernameID"],
            is_Opt: 0,
            language: "cn",
            isEnabled: true,
            timeout: 3000,
            times: 5,
            apimap: {},
            callback: function(data) {
                console.log('Captcha solved!', data);
                document.body.style.backgroundColor = '#90EE90';
            }
        });
    </script>
</body>
</html>"""

output_path = Path(__file__).resolve().parents[1] / "tools" / "test_captcha_page.html"
output_path.write_text(test_html, encoding='utf-8')
print(f"Created test page: {output_path}")
print(f"file:///{output_path.as_posix()}")
