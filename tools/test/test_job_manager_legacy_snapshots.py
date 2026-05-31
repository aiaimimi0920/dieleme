from __future__ import annotations

import json
from pathlib import Path

from jobs.job_manager import JobManager


def test_job_manager_exposes_legacy_task_snapshots(tmp_path: Path):
    jobs_dir = tmp_path / "jobs"
    data_dir = tmp_path / "datas"
    jobs_dir.mkdir()
    data_dir.mkdir()
    (jobs_dir / "priority.json").write_text(json.dumps(["310101"], ensure_ascii=False), encoding="utf-8")
    (data_dir / "all_locations.json").write_text(
        json.dumps(
            [
                {"code": "310000", "name": "上海市", "children": [{"code": "310101", "name": "黄浦区"}]},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (jobs_dir / "jobs_shanghai.json").write_text(
        json.dumps(
            {
                "310101": {
                    "50025969": {
                        "now_session_id": "session-1",
                        "last_update_time": "2026-05-01 10:00:00",
                        "all_done": False,
                        "st_param": {
                            "2": {
                                "pages": [1, 2],
                                "max_page": 5,
                                "is_done": False,
                                "need_try": True,
                                "dispatched_page": 2,
                            }
                        },
                    }
                },
                "all_done": False,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    manager = JobManager(str(jobs_dir), data_dir=str(data_dir))

    assert manager.get_priority_codes() == ["310101"]
    assert manager.get_all_location_codes() == ["310000", "310101"]
    assert manager.iter_task_snapshots() == [
        {
            "location_code": "310101",
            "category": "50025969",
            "sort_param": "2",
            "pages": [1, 2],
            "max_page": 5,
            "is_done": False,
            "need_try": True,
            "dispatched_page": 2,
            "now_session_id": "session-1",
            "last_update_time": "2026-05-01 10:00:00",
            "category_all_done": False,
        }
    ]
