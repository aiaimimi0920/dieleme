from tools.test.server_collection_api_status_test_context import *  # noqa: F401,F403


def test_api_status_uses_lightweight_payload_when_collection_api_mode_is_enabled(monkeypatch) -> None:
    from src import server

    class FakeRepository:
        enabled = True

        def seed_queue_counts(self):
            return {
                "seed_scan_job_pending": 1,
                "seed_scan_job_completed": 2,
                "seed_item_pending_detail": 4,
                "seed_item_in_progress": 1,
                "seed_item_detail_completed": 3,
                "seed_item_detail_failed": 2,
                "seed_item_detail_blocked": 1,
                "seed_occurrence_total": 12,
            }

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("full AVM/database status path should not run in collection API mode")

    monkeypatch.setattr(server, "DB_REPOSITORY", FakeRepository())
    monkeypatch.setattr(server, "PAUSED", False)
    monkeypatch.setattr(server, "_db_counts_snapshot", fail_if_called)
    monkeypatch.setattr(server, "_db_pending_task_candidates", fail_if_called)
    monkeypatch.setattr(server, "_db_collection_stage_snapshot", fail_if_called)
    monkeypatch.setenv("FAPAI_COLLECTION_API_LIGHTWEIGHT_STATUS", "1")

    httpd = server.ReusableTCPServer(("127.0.0.1", 0), server.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status", timeout=5) as resp:
            assert resp.status == 200
            payload = json.loads(resp.read().decode("utf-8"))
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert payload["collection_api_lightweight"] is True
    assert payload["total_ids"] == 11
    assert payload["seed_scan_job_pending"] == 1
    assert payload["seed_scan_job_completed"] == 2
    assert payload["seed_scan_progress_pending"] == 0
    assert payload["collection_stage"]["seed_queue"]["seed_occurrence_total"] == 12
