import json
import os
import tempfile
import unittest

from tools.run_avm_pipeline import run_pipeline


class TestRunAVMPipelineScript(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self.tmp.name, "datas")
        os.makedirs(self.data_dir, exist_ok=True)
        with open(os.path.join(self.data_dir, "2024-01-01.json"), "w", encoding="utf-8") as f:
            json.dump(
                [
                    {
                        "id": "1001",
                        "成交价格": "120万",
                        "起拍价格": "100万",
                        "建筑面积": "80㎡",
                        "交易时间": "2024-01-01",
                        "城市": "上海市",
                        "区": "浦东新区",
                        "所属小区": "测试小区",
                        "最靠近商圈": "张江",
                        "纬度": 31.2,
                        "经度": 121.5,
                    }
                ],
                f,
                ensure_ascii=False,
            )

    def tearDown(self):
        self.tmp.cleanup()

    def test_pipeline_stages_and_idempotent_outputs(self):
        first = run_pipeline(data_dir=self.data_dir, alerts_threshold=0.01, alerts_limit=20)
        second = run_pipeline(data_dir=self.data_dir, alerts_threshold=0.01, alerts_limit=20)

        self.assertTrue(first["idempotent"])
        self.assertEqual([s["name"] for s in first["stages"]], ["canonical", "risk", "feature", "predict", "alert"])
        for stage in first["stages"]:
            for path in stage["artifacts"].values():
                self.assertTrue(os.path.exists(path))

        first_counts = {s["name"]: s["summary"].get("count", s["summary"].get("total_records")) for s in first["stages"]}
        second_counts = {s["name"]: s["summary"].get("count", s["summary"].get("total_records")) for s in second["stages"]}
        self.assertEqual(first_counts, second_counts)


if __name__ == "__main__":
    unittest.main()
