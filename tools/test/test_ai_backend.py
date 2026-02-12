import requests
import json
import time

API_URL = "http://127.0.0.1:8001/api/analyze_html"
ITEM_ID = "1010786604345"

html_content = """
<html>
<body>
    <h1>标的物名称: 杭州市西湖区某房产 (REAL AI TEST)</h1>
    <div class="pm-current-price">
        <em>2,000,000</em>
    </div>
    <div id="itemAddressDetail">杭州市某某路123号</div>
    <table>
        <tr><td>建筑面积</td><td>123.45平方米</td></tr>
        <tr><td>评估价</td><td>2,500,000</td></tr>
        <tr><td>保证金</td><td>300,000</td></tr>
    </table>
    <div>加价幅度: 5,000</div>
    <div>咨询电话: 13800138000</div>
</body>
</html>
"""

payload = {
    "id": ITEM_ID,
    "html": html_content
}

print(f"Sending request to {API_URL} for ID {ITEM_ID}...")
try:
    response = requests.post(API_URL, json=payload)
    print(f"Status Code: {response.status_code}")
    print("Response Body:")
    print(response.text)
    
    if response.status_code == 200:
        data = response.json()
        if data.get("status") == "ok":
            print("SUCCESS: specific keys found in response:")
            print(json.dumps(data.get("data"), indent=2, ensure_ascii=False))
        else:
            print("FAILED: status not ok")
    else:
        print("FAILED: HTTP error")

except Exception as e:
    print(f"ERROR: {e}")
