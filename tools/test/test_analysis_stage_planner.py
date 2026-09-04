from tools.test.analysis_stage_planner_test_context import *
from tools.test.analysis_stage_planner_test_part_01 import *
from tools.test.analysis_stage_planner_test_part_02 import *
from tools.test.analysis_stage_planner_test_part_03 import *

from tools import analysis_stage_planner as planner_module


def test_analysis_stage_planner_facade_preserves_receipt_store_monkeypatch(
    monkeypatch,
    tmp_path,
) -> None:
    receipt_path = tmp_path / "receipts.json"
    calls = []

    def fake_list_manual_review_receipts(path, *, repository=None):
        calls.append((path, repository))
        return {"receipts": [{"action": "manual_location_review"}]}

    monkeypatch.setattr(
        planner_module,
        "list_manual_review_receipts",
        fake_list_manual_review_receipts,
    )

    assert planner_module.load_manual_review_receipt_snapshot(
        receipt_path,
        repository="repo",
    ) == {"receipts": [{"action": "manual_location_review"}]}
    assert calls == [(receipt_path, "repo")]
