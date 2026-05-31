import json
import urllib.request


HEADERS = {
    "Referer": "https://sf.taobao.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
}

TESTS = [
    ("Without project_id", "https://detail-ext.taobao.com/json/get_project_desc_content.do?id=998463796014"),
    ("With project_id=0", "https://detail-ext.taobao.com/json/get_project_desc_content.do?project_id=0&id=998463796014"),
    ("sf item detail API", "https://sf.taobao.com/json/get_sf_item_detail.do?id=998463796014"),
]


def main():
    for name, url in TESTS:
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            resp = urllib.request.urlopen(req, timeout=10)
            raw = resp.read().decode("utf-8", errors="replace")
            print(f"=== {name} ===")
            print(f"Status: {resp.status}, Length: {len(raw)}")

            if raw.strip():
                try:
                    data = json.loads(raw)
                    content = data.get("content", "")
                    print(f"Keys: {list(data.keys())}")
                    if content:
                        print(f"Content length: {len(content)}")
                        print("Has real data: YES")
                    else:
                        print("Content: EMPTY or missing")
                    display = {k: v for k, v in data.items() if k != "content"}
                    print(f"Other fields: {json.dumps(display, ensure_ascii=False)}")
                except Exception:
                    print(f"Raw (first 500): {raw[:500]}")
            print()
        except Exception as e:
            print(f"=== {name} === FAILED: {e}\n")


if __name__ == "__main__":
    main()
