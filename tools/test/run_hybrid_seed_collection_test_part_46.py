from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_run_once_omits_unknown_submit_result_typed_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "submit_result": {
                "batch": {"status": "ok", "new": "unknown"},
                "progress": {"status": "ok", "updated": "unknown"},
            },
        },
    )

    submit_result = result["collection_result"]["submit_result"]
    assert submit_result["batch"]["new"] is None
    assert submit_result["progress"]["updated"] is None
    assert "unknown" not in json.dumps(result)

def test_run_once_omits_unknown_collection_progress_payload_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {"source_page_url": " unknown ", "items": []},
            "progress_payload": {
                "url": " unknown ",
                "page_num": "unknown",
                "total_pages": "unknown",
                "has_next": "unknown",
            },
        },
    )

    collection_result = result["collection_result"]
    assert collection_result["batch_payload"]["source_page_url"] is None
    assert collection_result["progress_payload"]["url"] is None
    assert collection_result["progress_payload"]["page_num"] is None
    assert collection_result["progress_payload"]["total_pages"] is None
    assert collection_result["progress_payload"]["has_next"] is None
    assert "unknown" not in json.dumps(result)

def test_run_once_omits_unknown_batch_payload_url_alias_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {
                "source_page_url": " unknown ",
                "page_url": " unknown ",
                "url": " unknown ",
                "items": [],
            },
        },
    )

    batch_payload = result["collection_result"]["batch_payload"]
    assert batch_payload["source_page_url"] is None
    assert batch_payload["page_url"] is None
    assert batch_payload["url"] is None
    assert "unknown" not in json.dumps(result)

def test_run_once_treats_unknown_batch_payload_items_as_empty():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": "unknown",
            },
        },
    )

    assert result["collection_result"]["batch_payload"]["items"] == []
    assert "unknown" not in json.dumps(result)

def test_run_once_omits_unknown_batch_payload_item_metadata_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [
                    "unknown",
                    {
                        "id": "unknown",
                        "title": " unknown ",
                        "source_title": " unknown ",
                        "url": " unknown ",
                        "status": " unknown ",
                        "location": " unknown ",
                        "full_address": " unknown ",
                        "city": " unknown ",
                        "district": " unknown ",
                        "currentPrice": "unknown",
                        "initialPrice": "unknown",
                        "transaction_price": "unknown",
                        "starting_price": "unknown",
                        "deposit": "unknown",
                        "auction_date": " unknown ",
                        "auction_start_time": " unknown ",
                        "startTime": " unknown ",
                        "end": " unknown ",
                        "bidCount": "unknown",
                        "bid_count": "unknown",
                        "bidderCount": "unknown",
                        "bidder_count": "unknown",
                        "applyCount": "unknown",
                        "apply_count": "unknown",
                        "watchCount": "unknown",
                        "watch_count": "unknown",
                        "remindCount": "unknown",
                        "reminder_count": "unknown",
                        "viewCount": "unknown",
                        "view_count": "unknown",
                        "latitude": "unknown",
                        "longitude": "unknown",
                        "coordinate_source": "unknown",
                        "auction_round": " unknown ",
                        "housing_type": " unknown ",
                        "source_page_url": " unknown ",
                        "page_url": " unknown ",
                        "source_url": " unknown ",
                        "source_platform": " unknown ",
                        "source_item_id": "unknown",
                        "list_payload_path": " unknown ",
                        "is_processed": "unknown",
                    },
                ],
            },
        },
    )

    items = result["collection_result"]["batch_payload"]["items"]
    assert items[0] == {}
    assert items[1]["id"] is None
    assert items[1]["title"] is None
    assert items[1]["source_title"] is None
    assert items[1]["url"] is None
    assert items[1]["status"] is None
    assert items[1]["location"] is None
    assert items[1]["full_address"] is None
    assert items[1]["city"] is None
    assert items[1]["district"] is None
    assert items[1]["currentPrice"] is None
    assert items[1]["initialPrice"] is None
    assert items[1]["transaction_price"] is None
    assert items[1]["starting_price"] is None
    assert items[1]["deposit"] is None
    assert items[1]["auction_date"] is None
    assert items[1]["auction_start_time"] is None
    assert items[1]["startTime"] is None
    assert items[1]["end"] is None
    assert items[1]["bidCount"] is None
    assert items[1]["bid_count"] is None
    assert items[1]["bidderCount"] is None
    assert items[1]["bidder_count"] is None
    assert items[1]["applyCount"] is None
    assert items[1]["apply_count"] is None
    assert items[1]["watchCount"] is None
    assert items[1]["watch_count"] is None
    assert items[1]["remindCount"] is None
    assert items[1]["reminder_count"] is None
    assert items[1]["viewCount"] is None
    assert items[1]["view_count"] is None
    assert items[1]["latitude"] is None
    assert items[1]["longitude"] is None
    assert items[1]["coordinate_source"] is None
    assert items[1]["auction_round"] is None
    assert items[1]["housing_type"] is None
    assert items[1]["source_page_url"] is None
    assert items[1]["page_url"] is None
    assert items[1]["source_url"] is None
    assert items[1]["source_platform"] is None
    assert items[1]["source_item_id"] is None
    assert items[1]["list_payload_path"] is None
    assert items[1]["is_processed"] is None
    assert "unknown" not in json.dumps(result)

def test_run_once_preserves_batch_payload_item_numeric_auction_round():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [{"id": "item-1", "auction_round": 2}],
            },
        },
    )

    item = result["collection_result"]["batch_payload"]["items"][0]
    assert item["auction_round"] == 2

def test_run_once_preserves_batch_payload_item_text_auction_round():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [{"id": "item-1", "auction_round": "first_round"}],
            },
        },
    )

    item = result["collection_result"]["batch_payload"]["items"][0]
    assert item["auction_round"] == "first_round"

def test_run_once_omits_fractional_batch_payload_item_integer_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [{"id": "item-1", "bidCount": 1.5, "auction_round": 2.5}],
            },
        },
    )

    item = result["collection_result"]["batch_payload"]["items"][0]
    assert item["bidCount"] is None
    assert item["auction_round"] is None

def test_run_once_omits_bool_batch_payload_item_integer_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [
                    {
                        "id": "item-1",
                        "bidCount": True,
                        "auction_round": True,
                        "latitude": True,
                        "longitude": False,
                    }
                ],
            },
        },
    )

    item = result["collection_result"]["batch_payload"]["items"][0]
    assert item["bidCount"] is None
    assert item["auction_round"] is None
    assert item["latitude"] is None
    assert item["longitude"] is None

def test_run_once_omits_bool_batch_payload_item_identifier_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [
                    {"id": True, "source_item_id": False},
                    {"id": float("nan"), "source_item_id": {"bad": "id"}},
                ],
            },
        },
    )

    items = result["collection_result"]["batch_payload"]["items"]
    assert items[0]["id"] is None
    assert items[0]["source_item_id"] is None
    assert items[1]["id"] is None
    assert items[1]["source_item_id"] is None

def test_run_once_omits_negative_numeric_identifier_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "probe_summary": {"first_ids": [-1, "-2", 3]},
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [{"id": -1, "source_item_id": -2}],
            },
        },
    )

    collection_result = result["collection_result"]
    assert collection_result["probe_summary"]["first_ids"] == [None, "-2", 3]
    item = collection_result["batch_payload"]["items"][0]
    assert item["id"] is None
    assert item["source_item_id"] is None

def test_run_once_normalizes_decimal_identifier_fields():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": "browserless_success",
            "reason": None,
            "probe_summary": {"first_ids": [Decimal("123"), Decimal("123.5"), Decimal("-1")]},
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [
                    {"id": Decimal("123"), "source_item_id": Decimal("456")},
                    {"id": Decimal("123.5"), "source_item_id": Decimal("-1")},
                ],
            },
        },
    )

    collection_result = result["collection_result"]
    assert collection_result["probe_summary"]["first_ids"] == [123, None, None]
    items = collection_result["batch_payload"]["items"]
    assert items[0]["id"] == 123
    assert items[0]["source_item_id"] == 456
    assert items[1]["id"] is None
    assert items[1]["source_item_id"] is None

def test_run_once_returns_browser_fallback_and_can_open_browser():
    opened: list[tuple[str, Path, int]] = []

    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        profile_dir=Path(r"Z:\project\project\crow\output\taobao-auth-profile"),
        open_browser_fallback=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {"decision": "browser_fallback_required", "reason": "challenge_detected"},
        open_browser_fn=lambda url, profile_dir, remote_debugging_port: opened.append((url, profile_dir, remote_debugging_port)),
    )

    assert result["decision"] == "browser_fallback_required"
    assert result["reason"] == "challenge_detected"
    assert result["fallback_url"].startswith("https://sf.taobao.com/list/50025969__2.htm?page=1")
    assert "uni_mode=SNIFF_WORKER" in result["fallback_url"]
    assert result["browser_fallback_opened"] is True
    assert opened == [
        (
            result["fallback_url"],
            Path(r"Z:\project\project\crow\output\taobao-auth-profile"),
            9223,
        )
    ]
