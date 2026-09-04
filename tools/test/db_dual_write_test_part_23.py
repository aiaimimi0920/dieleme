from tools.test.db_dual_write_test_context import *  # noqa: F401,F403


def test_http_endpoints_can_read_pending_and_item_data_from_database(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9401", title="DB Pending", url="https://x/9401"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "empty-datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/get_item?id=9401") as resp:
            item_body = json.loads(resp.read().decode("utf-8"))
        assert item_body["item_id"] == "9401"
        assert item_body["source_title"] == "DB Pending"
        assert server_module.SEEN_IDS == {}

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/get_tasks") as resp:
            task_body = json.loads(resp.read().decode("utf-8"))
        assert task_body["total"] == 1
        assert len(task_body["tasks"]) == 1
        assert task_body["tasks"][0]["id"] == "9401"
        assert task_body["tasks"][0]["url"] == "https://x/9401"
        assert server_module.SEEN_IDS == {}
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_status_and_next_task_can_use_database_pending_counts(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9451", title="DB Pending A", url="https://x/9451"), event_type="seed")
    repo.upsert_flat_item(_make_flat_item(id="9452", title="DB Pending B", url="https://x/9452"), event_type="seed")

    with repo.session_factory.begin() as session:
        audit_row = session.get(PropertyAudit, "9452")
        audit_row.detail_captured = True

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "empty-datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status") as resp:
            status_body = json.loads(resp.read().decode("utf-8"))
        assert status_body["total_ids"] == 2
        assert status_body["ai_finalized_count"] == 0
        assert status_body["captured_count"] == 1
        assert status_body["db_mode"] is True
        assert status_body["db_total_ids"] == 2
        assert status_body["db_processed_ids"] == 0
        assert status_body["db_pending_ids"] == 2
        assert status_body["db_detail_captured_ids"] == 1
        assert len(status_body["next_batch_preview"]) >= 1
        assert server_module.SEEN_IDS == {}

        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/next_task") as resp:
            next_body = json.loads(resp.read().decode("utf-8"))
        assert next_body["url"] in {"https://x/9451", "https://x/9452"}
        assert server_module.SEEN_IDS == {}
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_get_next_task_can_use_database_pending_counts(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9461", title="DB Pending Visit", url="https://x/9461"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/get_next_task",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert body["task_type"] == "visit"
        assert body["id"] == "9461"
        assert body["url"] == "https://x/9461"
        assert server_module.SEEN_IDS == {}
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_http_update_and_analyze_can_on_demand_cache_item_from_database(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9601", title="DB Analyze", url="https://x/9601"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    submitted = []
    monkeypatch.setattr(server_module, "submit_task", lambda path: submitted.append(path))

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/update_item",
            data=json.dumps({"id": "9601", "status": "failed_timeout"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            update_body = json.loads(resp.read().decode("utf-8"))
        assert update_body["status"] == "updated"
        assert "9601" not in server_module.SEEN_IDS
        stored = repo.get_flat_item("9601")
        assert stored["status"] == "failed_timeout"

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/analyze_html",
            data=json.dumps({"id": "9601", "html": "<html>ok</html>", "status": "done"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            analyze_body = json.loads(resp.read().decode("utf-8"))
        assert analyze_body["status"] == "queued"
        assert submitted
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_analyze_html_failed_timeout_persists_without_runtime_residency(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9602", title="DB Analyze Timeout", url="https://x/9602"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    submitted = []
    monkeypatch.setattr(server_module, "submit_task", lambda path: submitted.append(path))

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/analyze_html",
            data=json.dumps({"id": "9602", "html": "<html>ok</html>", "status": "failed_timeout"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            analyze_body = json.loads(resp.read().decode("utf-8"))
        assert analyze_body["status"] == "queued"
        assert submitted == []
        stored = repo.get_flat_item("9602")
        assert stored["status"] == "failed_timeout"
        assert "9602" not in server_module.SEEN_IDS
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_area_result_persists_to_db_and_evicts_runtime_cache_in_db_first_mode(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9801", title="DB Area", url="https://x/9801"), event_type="seed")

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/area_result",
            data=json.dumps({"id": "9801", "建筑面积": 88.8}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "ok"
        assert "9801" not in server_module.SEEN_IDS
        stored = repo.get_flat_item("9801")
        assert stored["建筑面积"] == pytest.approx(88.8)
        assert stored["is_processed"] is True
    finally:
        httpd.shutdown()
        httpd.server_close()

def test_api_save_and_screen_can_pull_existing_item_from_database(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        _make_flat_item(id="9701", title="DB Existing", url="https://x/9701", currentPrice="1000000"),
        event_type="seed",
    )

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []
    server_module.DISPATCHED_TASKS = {}
    server_module.PAUSED = False
    original_service = server_module.AVM_SERVICE
    original_start_time = server_module.AVM_SERVICE_START_TIME
    server_module.AVM_SERVICE = AVMService(data_dir=server_module.DATA_DIR, repository=repo)
    server_module.AVM_SERVICE_START_TIME = 0

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/save",
            data=json.dumps(
                {
                    "items": [
                        {
                            "id": "9701",
                            "title": "New Scan Title",
                            "url": "https://x/9701",
                            "status": "done",
                            "currentPrice": "100万",
                            "initialPrice": "80万",
                            "auction_date": "2026-05-11 10:00:00",
                        }
                    ]
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            save_body = json.loads(resp.read().decode("utf-8"))
        assert save_body["status"] == "ok"
        assert "9701" not in server_module.SEEN_IDS

        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/avm/screen",
            data=json.dumps({"items": [{"id": "9701"}], "margin_threshold": 0.01}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as resp:
            screen_body = json.loads(resp.read().decode("utf-8"))
        assert screen_body["total"] == 1
        assert screen_body["results"][0]["id"] == "9701"
        assert "9701" not in server_module.SEEN_IDS
    finally:
        httpd.shutdown()
        httpd.server_close()
        server_module.AVM_SERVICE = original_service
        server_module.AVM_SERVICE_START_TIME = original_start_time

def test_process_single_file_can_work_from_database_without_runtime_preload(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(
        _make_flat_item(id="9901", title="DB HTML", url="https://x/9901", currentPrice="1000000"),
        event_type="seed",
    )

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")
    server_module.SEEN_IDS = {}
    server_module.PENDING_TASKS = []

    monkeypatch.setattr(
        server_module.llm_helper,
        "extract_auction_data",
        lambda content, item_id=None: json.dumps(
            {
                "id": 9901,
                "status": "done",
                "交易时间": "2026-05-11 10:00:00",
                "成交价格": "100万",
                "起拍价格": "80万",
                "建筑面积": "88.8㎡",
                "地点": "上海市浦东新区测试路99号",
            },
            ensure_ascii=False,
        ),
    )
    monkeypatch.setattr(server_module.llm_helper, "extract_avm_risk_features", lambda content, item_id=None: {})
    monkeypatch.setattr(server_module.llm_helper, "log_prediction_event", lambda **kwargs: None)

    html_path = Path(server_module.DATA_DIR) / "item-9901.html"
    html_path.write_text("<html><body>mock</body></html>", encoding="utf-8")

    server_module.process_single_file(str(html_path))

    stored = repo.get_flat_item("9901")
    assert stored["is_processed"] is True
    assert stored["建筑面积"] == pytest.approx(88.8)
    assert "9901" not in server_module.SEEN_IDS
    assert not html_path.exists()

def test_load_data_db_first_uses_lazy_runtime_cache_for_pending_items(tmp_path: Path, monkeypatch):
    repo = _make_repo(tmp_path)
    repo.upsert_flat_item(_make_flat_item(id="9501", title="Pending", url="https://x/9501"), event_type="seed")
    repo.upsert_flat_item(_make_flat_item(id="9502", title="Processed", url="https://x/9502"), event_type="seed")

    with repo.session_factory.begin() as session:
        audit_row = session.get(PropertyAudit, "9502")
        audit_row.is_processed = True

    server_module = importlib.import_module("src.server")
    monkeypatch.setattr(server_module, "DB_REPOSITORY", repo)
    monkeypatch.setattr(server_module, "DATA_DIR", str(tmp_path / "empty-datas"))
    Path(server_module.DATA_DIR).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("FAPAI_DB_PREFER_RUNTIME_INDEX", "1")

    server_module.load_data()

    assert server_module.SEEN_IDS == {}
    assert server_module.PENDING_TASKS == []
    assert repo.count_pending_task_items() == 1
