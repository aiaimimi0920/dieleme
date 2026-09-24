from __future__ import annotations

from unittest import mock

import src.server as server_module
from tools.test.avm_http_contract_base import AVMHttpContractBase


class TestDetailLocationJobs(AVMHttpContractBase):
    def test_async_location_inference_returns_result_in_job_receipt(self):
        payload = {
            "id": "3001",
            "address": "上海市浦东新区测试路 99 号",
            "title": "测试标题",
            "execution_mode": "async",
        }
        expected = {"所属小区": "测试小区", "城市": "上海市"}
        fake_service = mock.Mock()
        fake_service.infer_location.return_value = expected

        with mock.patch.object(
            server_module,
            "_detail_collection_service",
            return_value=fake_service,
        ):
            status, accepted = self._post_json(
                "/api/collection/details/infer_location", payload
            )
            job = self._complete_collection_job(status, accepted)

        self.assertEqual(accepted["execution_mode"], "async")
        self.assertEqual(accepted["item_id"], "3001")
        self.assertEqual(job, expected)
        fake_service.infer_location.assert_called_once()
        arguments = fake_service.infer_location.call_args.kwargs
        self.assertEqual(arguments["address"], payload["address"])
        self.assertEqual(arguments["title"], payload["title"])
        self.assertEqual(arguments["item_id"], payload["id"])

    def test_async_location_inference_failure_is_reported_by_job_receipt(self):
        payload = {
            "execution_mode": "async",
            "address": "测试地址",
            "title": "测试标题",
        }
        fake_service = mock.Mock()
        fake_service.infer_location.side_effect = RuntimeError("model unavailable")

        with mock.patch.object(
            server_module,
            "_detail_collection_service",
            return_value=fake_service,
        ):
            status, accepted = self._post_json("/api/infer_location", payload)
            job = self._assert_collection_job_failed(
                status,
                accepted,
                "AVM_DETAIL_INFER_LOCATION_ASYNC_FAILED",
            )

        self.assertEqual(job["operation"], "infer_location")
