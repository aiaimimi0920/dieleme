import logging
import unittest
from unittest import mock

from src.avm_batch_runner import AVMService, batch_evaluate_item_ids


class FakeAVMService:
    def __init__(self, mapping):
        self.mapping = mapping

    def evaluate(self, item_id):
        return self.mapping[item_id]


class TestBatchAvmRunner(unittest.TestCase):
    def test_avm_service_evaluate_uses_predict_endpoint(self):
        response = mock.Mock()
        response.json.return_value = {"item_id": "3001", "margin_of_safety": 0.25}
        with mock.patch("src.avm_batch_runner.requests.get", return_value=response) as mocked_get:
            result = AVMService("http://127.0.0.1:8001/").evaluate("3001")

        mocked_get.assert_called_once_with(
            "http://127.0.0.1:8001/api/avm/predict",
            params={"id": "3001"},
            timeout=10,
        )
        response.raise_for_status.assert_called_once()
        self.assertEqual(result["margin_of_safety"], 0.25)

    def test_sort_by_margin_of_safety_desc(self):
        service = FakeAVMService(
            {
                "a": {"margin_of_safety": 0.1},
                "b": {"margin_of_safety": 0.35},
                "c": {"margin_of_safety": 0.2},
            }
        )

        results = batch_evaluate_item_ids(
            item_ids=["a", "b", "c"],
            avm_service=service,
            logger=logging.getLogger("test"),
        )

        self.assertEqual([r.item_id for r in results], ["b", "c", "a"])

    def test_batch_size_limit(self):
        service = FakeAVMService({"1": {"margin_of_safety": 0.1}, "2": {"margin_of_safety": 0.2}})

        with self.assertRaises(ValueError):
            batch_evaluate_item_ids(
                item_ids=["1", "2"],
                avm_service=service,
                max_batch_size=1,
                logger=logging.getLogger("test"),
            )


if __name__ == "__main__":
    unittest.main()
