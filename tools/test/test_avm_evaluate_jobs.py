from __future__ import annotations

import threading
from unittest import mock

import src.server as server_module
from tools.test.avm_http_contract_base import AVMHttpContractBase


class TestAVMEvaluateJobs(AVMHttpContractBase):
    def test_async_evaluation_returns_before_work_finishes(self):
        started = threading.Event()
        release = threading.Event()
        expected = {
            "request_id": "req-async",
            "valuation": {"estimated_fair_price": 123},
        }
        payload = {
            "request_id": "req-async",
            "execution_mode": "async",
            "subject": {"area_sqm": 90},
            "options": {"valuation_mode": "historical_strict"},
        }

        def evaluate(request_payload):
            started.set()
            if not release.wait(timeout=5):
                raise RuntimeError("test work was not released")
            return expected

        with mock.patch.object(
            server_module.AVM_SERVICE, "evaluate_request", side_effect=evaluate
        ) as evaluate_request:
            try:
                status, accepted = self._post_json("/api/avm/evaluate", payload)
                self.assertEqual(status, 202)
                self.assertEqual(accepted["status"], "accepted")
                self.assertEqual(accepted["execution_mode"], "async")
                self.assertEqual(accepted["request_id"], "req-async")
                self.assertTrue(started.wait(timeout=2))
                self.assertFalse(release.is_set())
            finally:
                release.set()
            job = self._wait_for_collection_job(status, accepted)

        self.assertEqual(job["operation"], "avm_evaluate")
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["result"], expected)
        evaluate_request.assert_called_once()
        self.assertEqual(
            evaluate_request.call_args.args[0]["options"], payload["options"]
        )
        self.assertNotIn("execution_mode", evaluate_request.call_args.args[0])

    def test_async_evaluation_alias_uses_same_job_contract(self):
        payload = {
            "request_id": "req-alias",
            "execution_mode": "async",
            "subject": {"area_sqm": 80},
        }
        expected = {
            "request_id": "req-alias",
            "valuation": {"estimated_fair_price": 456},
        }

        with mock.patch.object(
            server_module.AVM_SERVICE, "evaluate_request", return_value=expected
        ):
            status, accepted = self._post_json("/api/analysis/evaluate", payload)
            job = self._wait_for_collection_job(status, accepted)

        self.assertEqual(job["operation"], "avm_evaluate")
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["result"], expected)

    def test_async_failure_is_reported_by_job_receipt(self):
        payload = {"execution_mode": "async", "subject": {"area_sqm": 80}}
        with mock.patch.object(
            server_module.AVM_SERVICE,
            "evaluate_request",
            side_effect=RuntimeError("evaluation failed"),
        ):
            status, accepted = self._post_json("/api/avm/evaluate", payload)
            job = self._assert_collection_job_failed(
                status,
                accepted,
                "AVM_EVALUATE_ASYNC_FAILED",
            )

        self.assertEqual(job["operation"], "avm_evaluate")

    def test_sync_mode_preserves_valuation_mode_and_response(self):
        payload = {
            "request_id": "req-sync",
            "execution_mode": "sync",
            "subject": {"area_sqm": 90},
            "options": {"valuation_mode": "historical_strict"},
        }
        expected = {
            "request_id": "req-sync",
            "trace": {"valuation_mode": "historical_strict"},
        }

        with mock.patch.object(
            server_module.AVM_SERVICE, "evaluate_request", return_value=expected
        ) as evaluate_request:
            status, response = self._post_json("/api/avm/evaluate", payload)

        self.assertEqual(status, 200)
        self.assertEqual(response, expected)
        evaluate_request.assert_called_once_with(
            {
                "request_id": "req-sync",
                "subject": {"area_sqm": 90},
                "options": {"valuation_mode": "historical_strict"},
            }
        )

    def test_invalid_execution_mode_and_invalid_subject_do_not_enqueue(self):
        with mock.patch.object(self.httpd, "collection_jobs") as collection_jobs:
            self._assert_http_error_code(
                "/api/avm/evaluate",
                400,
                "AVM_INVALID_EXECUTION_MODE",
                method="POST",
                payload={"execution_mode": "background", "subject": {"area_sqm": 90}},
            )
            self._assert_http_error_code(
                "/api/avm/evaluate",
                400,
                "AVM_MISSING_AREA",
                method="POST",
                payload={"execution_mode": "async", "subject": {"city": "上海市"}},
            )

        collection_jobs.assert_not_called()
