import json

import os

import tempfile

import time

import unittest

from pathlib import Path

from unittest import mock

from src.avm.pipeline import AVMPipelineManager, AVMPipelineConfig, _write_calibration_targets

from tools.build_canonical_dataset import build_canonical_dataset

from tools.build_avm_features import build_avm_features

from tools.generate_avm_alerts import generate_avm_alerts

from tools.run_avm_pipeline import _run_alert_stage, _run_calibration_stage, _run_gate_stage, run_pipeline

if __name__ == "__main__":
    unittest.main()


class AvmPipelineTestBase(unittest.TestCase):
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


__all__ = [name for name in globals() if not name.startswith("__")]
