from tools.test.run_hybrid_seed_collection_test_context import *  # noqa: F401,F403


def test_run_once_omits_unknown_collection_decision_and_reason():
    result = run_hybrid_seed_collection.run_once(
        api_base="http://127.0.0.1:8001/api",
        session_id="runner-a",
        cdp_endpoint="http://127.0.0.1:9223",
        submit=True,
        claim_task_fn=lambda **_: {"task": {"url": "https://sf.taobao.com/list/50025969__2.htm?page=1"}, "message": "ok"},
        export_cookies_fn=lambda *_args, **_kwargs: [{"name": "cookie2", "value": "abc"}],
        hybrid_collect_fn=lambda *_args, **_kwargs: {
            "decision": " unknown ",
            "reason": " unknown ",
        },
    )

    assert result["decision"] is None
    assert result["reason"] is None
    assert result["collection_result"] == {"decision": None, "reason": None}
    assert "unknown" not in json.dumps(result)

def test_run_once_omits_unknown_collection_error_message():
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
            "error": " unknown ",
            "message": " unknown ",
        },
    )

    assert result["collection_result"]["error"] is None
    assert result["collection_result"]["message"] is None
    assert "unknown" not in json.dumps(result)

def test_run_once_omits_unknown_collection_cookie_count():
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
            "cookie_count": "unknown",
        },
    )

    assert result["collection_result"]["cookie_count"] is None
    assert "unknown" not in json.dumps(result)

def test_run_once_omits_unknown_probe_summary_url_fields():
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
            "probe_summary": {
                "final_url": " unknown ",
                "first_urls": [" unknown ", "https://sf.taobao.com/item/1"],
            },
        },
    )

    probe_summary = result["collection_result"]["probe_summary"]
    assert probe_summary["final_url"] is None
    assert probe_summary["first_urls"] == [None, "https://sf.taobao.com/item/1"]
    assert "unknown" not in json.dumps(result)

def test_run_once_omits_unknown_probe_summary_first_ids():
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
            "probe_summary": {
                "first_ids": [" unknown ", "12345"],
            },
        },
    )

    assert result["collection_result"]["probe_summary"]["first_ids"] == [None, "12345"]
    assert "unknown" not in json.dumps(result)

def test_run_once_treats_unknown_probe_summary_list_fields_as_empty():
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
            "probe_summary": {
                "first_ids": "unknown",
                "first_urls": "unknown",
            },
        },
    )

    probe_summary = result["collection_result"]["probe_summary"]
    assert probe_summary["first_ids"] == []
    assert probe_summary["first_urls"] == []
    assert "unknown" not in json.dumps(result)

def test_run_once_omits_malformed_probe_summary_list_elements():
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
            "probe_summary": {
                "first_ids": [True, 123, 123.5, " unknown ", float("nan"), {"bad": "id"}],
                "first_urls": [False, 123, " https://sf.taobao.com/item/1 "],
            },
        },
    )

    probe_summary = result["collection_result"]["probe_summary"]
    assert probe_summary["first_ids"] == [None, 123, None, None, None, None]
    assert probe_summary["first_urls"] == [None, None, "https://sf.taobao.com/item/1"]

def test_run_once_omits_unknown_probe_summary_scalar_fields():
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
            "probe_summary": {
                "status": " unknown ",
                "item_count": "unknown",
                "cookie_count": "unknown",
                "has_script": "unknown",
                "body_has_login": "unknown",
                "body_has_captcha": "unknown",
                "body_has_punish": "unknown",
                "body_has_challenge": "unknown",
                "body_snippet": " unknown ",
            },
        },
    )

    probe_summary = result["collection_result"]["probe_summary"]
    assert probe_summary["status"] is None
    assert probe_summary["item_count"] is None
    assert probe_summary["cookie_count"] is None
    assert probe_summary["has_script"] is None
    assert probe_summary["body_has_login"] is None
    assert probe_summary["body_has_captcha"] is None
    assert probe_summary["body_has_punish"] is None
    assert probe_summary["body_has_challenge"] is None
    assert probe_summary["body_snippet"] is None
    assert "unknown" not in json.dumps(result)

def test_run_once_omits_non_finite_probe_summary_integer_fields():
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
            "probe_summary": {
                "status": float("inf"),
                "item_count": float("-inf"),
                "cookie_count": float("nan"),
            },
        },
    )

    probe_summary = result["collection_result"]["probe_summary"]
    assert probe_summary["status"] is None
    assert probe_summary["item_count"] is None
    assert probe_summary["cookie_count"] is None

def test_run_once_omits_fractional_probe_summary_integer_fields():
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
            "probe_summary": {
                "status": 200.5,
                "item_count": 2.5,
                "cookie_count": 1.5,
            },
        },
    )

    probe_summary = result["collection_result"]["probe_summary"]
    assert probe_summary["status"] is None
    assert probe_summary["item_count"] is None
    assert probe_summary["cookie_count"] is None

def test_run_once_omits_decimal_fractional_integer_fields():
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
            "cookie_count": Decimal("4.5"),
            "probe_summary": {
                "status": Decimal("200.5"),
                "item_count": Decimal("2.5"),
                "cookie_count": Decimal("1.5"),
            },
            "batch_payload": {
                "source_page_url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "items": [{"id": "item-1", "bidCount": Decimal("1.5"), "auction_round": Decimal("2.5")}],
            },
            "progress_payload": {
                "url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "page_num": Decimal("1.5"),
                "total_pages": Decimal("2.5"),
            },
            "submit_result": {
                "batch": {"status": "ok", "new": Decimal("3.5")},
            },
        },
    )

    collection_result = result["collection_result"]
    probe_summary = collection_result["probe_summary"]
    assert collection_result["cookie_count"] is None
    assert probe_summary["status"] is None
    assert probe_summary["item_count"] is None
    assert probe_summary["cookie_count"] is None
    item = collection_result["batch_payload"]["items"][0]
    assert item["bidCount"] is None
    assert item["auction_round"] is None
    assert collection_result["progress_payload"]["page_num"] is None
    assert collection_result["progress_payload"]["total_pages"] is None
    assert collection_result["submit_result"]["batch"]["new"] is None

def test_run_once_omits_non_finite_probe_summary_bool_fields():
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
            "probe_summary": {
                "has_script": float("nan"),
                "body_has_login": float("inf"),
                "body_has_captcha": float("-inf"),
            },
        },
    )

    probe_summary = result["collection_result"]["probe_summary"]
    assert probe_summary["has_script"] is None
    assert probe_summary["body_has_login"] is None
    assert probe_summary["body_has_captcha"] is None

def test_run_once_omits_ambiguous_numeric_probe_summary_bool_fields():
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
            "probe_summary": {
                "has_script": 2,
                "body_has_login": -1,
                "body_has_captcha": 0.5,
                "body_has_punish": 1,
                "body_has_challenge": 0,
            },
        },
    )

    probe_summary = result["collection_result"]["probe_summary"]
    assert probe_summary["has_script"] is None
    assert probe_summary["body_has_login"] is None
    assert probe_summary["body_has_captcha"] is None
    assert probe_summary["body_has_punish"] is True
    assert probe_summary["body_has_challenge"] is False

def test_run_once_normalizes_decimal_bool_fields():
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
            "probe_summary": {
                "has_script": Decimal("1"),
                "body_has_login": Decimal("0"),
                "body_has_captcha": Decimal("0.5"),
            },
            "progress_payload": {
                "url": "https://sf.taobao.com/list/50025969__2.htm?page=1",
                "has_next": Decimal("1"),
                "is_empty": Decimal("0"),
                "zero_bid_detected": Decimal("2"),
            },
            "submit_result": {"progress": {"status": "ok", "updated": Decimal("1")}},
        },
    )

    collection_result = result["collection_result"]
    probe_summary = collection_result["probe_summary"]
    assert probe_summary["has_script"] is True
    assert probe_summary["body_has_login"] is False
    assert probe_summary["body_has_captcha"] is None
    progress_payload = collection_result["progress_payload"]
    assert progress_payload["has_next"] is True
    assert progress_payload["is_empty"] is False
    assert progress_payload["zero_bid_detected"] is None
    assert collection_result["submit_result"]["progress"]["updated"] is True

def test_run_once_omits_unknown_probe_summary_nested_batch_payload_fields():
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
            "probe_summary": {
                "batch_payload": {
                    "source_page_url": " unknown ",
                    "items": "unknown",
                },
            },
        },
    )

    batch_payload = result["collection_result"]["probe_summary"]["batch_payload"]
    assert batch_payload["source_page_url"] is None
    assert batch_payload["items"] == []
    assert "unknown" not in json.dumps(result)

def test_run_once_omits_unknown_submit_result_status_fields():
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
                "batch": {
                    "status": " unknown ",
                    "message": " unknown ",
                    "error": " unknown ",
                },
                "progress": {
                    "status": "ok",
                    "message": "done",
                    "error": " unknown ",
                },
            },
        },
    )

    submit_result = result["collection_result"]["submit_result"]
    assert submit_result["batch"]["status"] is None
    assert submit_result["batch"]["message"] is None
    assert submit_result["batch"]["error"] is None
    assert submit_result["progress"]["status"] == "ok"
    assert submit_result["progress"]["message"] == "done"
    assert submit_result["progress"]["error"] is None
    assert "unknown" not in json.dumps(result)
