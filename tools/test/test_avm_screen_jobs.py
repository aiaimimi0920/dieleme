from __future__ import annotations

import threading
from unittest import mock

import src.server as server_module
from tools.test.avm_http_contract_base import AVMHttpContractBase


class TestAVMScreenJobs(AVMHttpContractBase):
    def test_async_screen_returns_before_work_and_persists_result_and_alerts(self):
        started = threading.Event()
        release = threading.Event()
        prediction = {
            "predicted_price": 1_000_000.0,
            "predicted_unit_price": 10_000.0,
            "confidence": 0.8,
            "comparable_count": 3,
            "strategy": "spatial",
            "trace": {
                "valuation_mode": "current_market",
                "subject_coordinate_strategy": "observed",
            },
            "top_factors": [],
            "manual_review_recommended": False,
            "manual_review_reasons": [],
            "risk_validation": {
                "ok": True,
                "missing_required_count": 0,
                "invalid_field_count": 0,
                "feature_completeness": 1.0,
                "missing_required_fields": [],
                "invalid_fields": [],
            },
        }

        def predict(_item):
            started.set()
            if not release.wait(timeout=5):
                raise RuntimeError("test work was not released")
            return prediction

        payload = {
            "execution_mode": "async",
            "margin_threshold": 0.0,
            "items": [{"id": "3001", "starting_price": 820_000}],
        }
        with mock.patch.object(
            server_module.AVM_SERVICE, "predict_by_item_data", side_effect=predict
        ) as predict_by_item_data, mock.patch.object(
            server_module, "write_avm_alerts"
        ) as write_avm_alerts:
            try:
                status, accepted = self._post_json("/api/avm/screen", payload)
                self.assertEqual(status, 202)
                self.assertEqual(accepted["status"], "accepted")
                self.assertEqual(accepted["execution_mode"], "async")
                self.assertTrue(started.wait(timeout=2))
                self.assertFalse(release.is_set())
            finally:
                release.set()
            job = self._wait_for_collection_job(status, accepted)

        self.assertEqual(job["operation"], "avm_screen")
        self.assertEqual(job["status"], "completed")
        self.assertEqual(job["result"]["total"], 1)
        self.assertIn("summary", job["result"])
        self.assertEqual(job["result"]["alerts_written"], 1)
        predict_by_item_data.assert_called_once()
        write_avm_alerts.assert_called_once()
        self.assertEqual(len(write_avm_alerts.call_args.args[0]), 1)

    def test_async_screen_failure_is_reported_by_job_receipt(self):
        with mock.patch.object(
            server_module, "write_avm_alerts", side_effect=RuntimeError("disk full")
        ):
            status, accepted = self._post_json(
                "/api/avm/screen", {"execution_mode": "async", "items": []}
            )
            job = self._assert_collection_job_failed(
                status, accepted, "AVM_SCREEN_ASYNC_FAILED"
            )

        self.assertEqual(job["operation"], "avm_screen")

    def test_invalid_async_screen_requests_do_not_enqueue(self):
        with mock.patch.object(self.httpd, "collection_jobs") as collection_jobs:
            self._assert_http_error_code(
                "/api/avm/screen",
                400,
                "AVM_INVALID_EXECUTION_MODE",
                method="POST",
                payload={"execution_mode": "background", "items": []},
            )
            self._assert_http_error_code(
                "/api/avm/screen",
                400,
                "AVM_INVALID_SCREEN_ITEMS",
                method="POST",
                payload={"execution_mode": "async", "items": {"id": "3001"}},
            )

        collection_jobs.assert_not_called()
