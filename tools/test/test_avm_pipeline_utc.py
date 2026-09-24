from datetime import datetime

from src.avm.pipeline import AVMPipelineConfig, AVMPipelineManager


def test_pipeline_run_timestamps_are_aware_utc(tmp_path):
    manager = AVMPipelineManager(data_dir=str(tmp_path))
    result = manager._begin_run(AVMPipelineConfig(data_dir=str(tmp_path)))

    started_at = datetime.fromisoformat(result["state"]["started_at"])
    assert started_at.tzinfo is not None
    assert started_at.utcoffset().total_seconds() == 0
