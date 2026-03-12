import json
import os
import tempfile
import time
import unittest

from src.avm.pipeline import AVMPipelineManager, AVMPipelineConfig
from tools.build_canonical_dataset import build_canonical_dataset
from tools.build_avm_features import build_avm_features
from tools.generate_avm_alerts import generate_avm_alerts


class TestAVMPipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = os.path.join(self.tmp.name, "datas")
        os.makedirs(self.data_dir, exist_ok=True)
        with open(os.path.join(self.data_dir, "2024-01-01.json"), "w", encoding="utf-8") as f:
            json.dump([
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
            ], f, ensure_ascii=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_subtask_functions(self):
        canonical_dir = os.path.join(self.data_dir, "canonical")
        avm_dir = os.path.join(self.data_dir, "avm")

        c = build_canonical_dataset(data_dir=self.data_dir, output_dir=canonical_dir)
        self.assertTrue(os.path.exists(c["canonical_path"]))

        f = build_avm_features(
            canonical_path=os.path.join(canonical_dir, "canonical.jsonl"),
            output_path=os.path.join(avm_dir, "features.jsonl"),
            stats_path=os.path.join(avm_dir, "feature_stats.json"),
        )
        self.assertTrue(os.path.exists(f["features_path"]))

        a = generate_avm_alerts(
            data_dir=self.data_dir,
            output_path=os.path.join(avm_dir, "alerts.json"),
            threshold=0.01,
            limit=20,
        )
        self.assertTrue(os.path.exists(a["output_path"]))

    def test_unified_run_sync_and_async(self):
        mgr = AVMPipelineManager(data_dir=self.data_dir)
        config = AVMPipelineConfig(data_dir=self.data_dir, alerts_threshold=0.01, alerts_limit=20)

        sync_result = mgr.run(async_mode=False, config=config)
        self.assertEqual(sync_result["status"], "completed")
        self.assertFalse(sync_result["state"]["running"])
        self.assertEqual(sync_result["state"]["config"]["alerts_threshold"], 0.01)
        self.assertTrue(sync_result["state"]["merge_check"]["is_fully_merged"])

        merge_info = mgr.verify_merge_completeness()
        self.assertTrue(merge_info["is_fully_merged"])
        self.assertEqual(merge_info["missing_subtasks"], [])

        start = mgr.run(async_mode=True, config=config)
        self.assertIn(start["status"], {"started", "already_running"})
        for _ in range(200):
            state = mgr.status()
            if not state.get("running"):
                break
            time.sleep(0.01)
        self.assertFalse(mgr.status().get("running"))


if __name__ == "__main__":
    unittest.main()
