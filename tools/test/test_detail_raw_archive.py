"""raw detail 捕获阶段的持久归档。

生产路径 `tools/detail_worker.py` 只把 detail.html 写进 `output_dir/{item_id}/`
这个按 item 的临时工作目录，从不调用 `DetailService` 里的 html_archive 归档代码。
线上后果：228,959 行 `property_audit.detail_archive_path` 全为 ''，磁盘上不留
原始 HTML，风险字段抽取一旦改进也无法回填——原料已经没了。

这里固化的预期是：raw 捕获成功后落一份日期分区的持久归档，路径确定性可推导，
未来回填工具能按 item_id 直接定位，不依赖 DB 里的路径字段。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.test.test_detail_worker import _make_repo, _seed_one_item  # noqa: E402

RAW_HTML = "<html><body>公告正文 房屋现由被执行人占用</body></html>"


def _process_item_writing_raw(_http, seed, _browser_pages, *, config):
    item_dir = config.output_dir / str(seed["id"])
    item_dir.mkdir(parents=True, exist_ok=True)
    (item_dir / "detail.html").write_text(RAW_HTML, encoding="utf-8")
    (item_dir / "description-data.json").write_text("{}", encoding="utf-8")
    (item_dir / "selected.json").write_text(
        json.dumps({"item_id": seed["id"], "detail_capture_mode": "raw"}, ensure_ascii=False),
        encoding="utf-8",
    )
    return {"item_id": seed["id"], "detail_capture_mode": "raw"}


def _run_raw_capture(tmp_path: Path, *, archive_root: Path | None):
    from tools import detail_worker

    repo = _make_repo(tmp_path)
    _seed_one_item(repo)

    kwargs = {}
    if archive_root is not None:
        kwargs["detail_archive_root"] = archive_root

    summary = detail_worker.run_detail_worker_once(
        detail_worker.DetailWorkerConfig(
            output_dir=tmp_path / "work",
            cdp_endpoint="http://127.0.0.1:9223",
            target_success=1,
            max_attempts=1,
            worker_id="detail-archive-test",
            do_risk=False,
            raw_only=True,
            **kwargs,
        ),
        repository=repo,
        http_session=object(),
        browser_pages={},
        process_item_func=_process_item_writing_raw,
    )
    return repo, summary


def test_raw_capture_writes_durable_archive_copy(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"

    _repo, summary = _run_raw_capture(tmp_path, archive_root=archive_root)

    assert summary["decision"] == "detail_item_raw_captured"

    archived = list(archive_root.rglob("item-3001.html"))
    assert archived, f"未找到持久归档，archive_root 下内容={list(archive_root.rglob('*'))}"
    assert archived[0].read_text(encoding="utf-8") == RAW_HTML


def test_durable_archive_path_is_date_partitioned(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"

    _run_raw_capture(tmp_path, archive_root=archive_root)

    archived = list(archive_root.rglob("item-3001.html"))[0]
    relative = archived.relative_to(archive_root)
    # 期望形如 html_archive/2026/2026-08-07/item-3001.html
    assert relative.parts[0] == "html_archive"
    year = relative.parts[1]
    day = relative.parts[2]
    assert len(year) == 4 and year.isdigit()
    assert day.startswith(year) and len(day) == 10


def test_archive_path_is_reported_in_summary(tmp_path: Path) -> None:
    archive_root = tmp_path / "archive"

    _repo, summary = _run_raw_capture(tmp_path, archive_root=archive_root)

    assert "detail_archive_path" in summary
    assert summary["detail_archive_path"]
    assert Path(summary["detail_archive_path"]).is_file()


def test_transient_working_copy_is_still_written(tmp_path: Path) -> None:
    """归档是新增的一份，不能取代分析阶段依赖的临时工作副本。"""
    archive_root = tmp_path / "archive"

    _run_raw_capture(tmp_path, archive_root=archive_root)

    assert (tmp_path / "work" / "3001" / "detail.html").is_file()


def test_missing_archive_root_falls_back_without_breaking_capture(tmp_path: Path) -> None:
    """未配置归档根目录时，捕获必须照常成功（归档是增强，不是新的失败点）。"""
    repo, summary = _run_raw_capture(tmp_path, archive_root=None)

    assert summary["decision"] == "detail_item_raw_captured"
    assert repo.seed_queue_counts()["seed_item_raw_detail_captured"] == 1


def test_archive_root_is_wired_from_cli_flag() -> None:
    from tools import detail_worker

    config, _loop = detail_worker.config_from_env_and_args(
        ["--raw-only", "--detail-archive-root", "/data/archive"]
    )

    assert config.detail_archive_root == Path("/data/archive")


def test_archive_root_is_wired_from_env(monkeypatch) -> None:
    from tools import detail_worker

    monkeypatch.setenv("FAPAI_DETAIL_ARCHIVE_ROOT", "/data/from-env")

    config, _loop = detail_worker.config_from_env_and_args(["--raw-only"])

    assert config.detail_archive_root == Path("/data/from-env")


def test_archive_root_defaults_to_none_when_unset(monkeypatch) -> None:
    from tools import detail_worker

    monkeypatch.delenv("FAPAI_DETAIL_ARCHIVE_ROOT", raising=False)

    config, _loop = detail_worker.config_from_env_and_args(["--raw-only"])

    assert config.detail_archive_root is None


def test_archive_failure_does_not_fail_the_capture(tmp_path: Path, monkeypatch) -> None:
    """归档写盘异常（磁盘满/权限）不应把已成功的抓取判为失败。"""
    from tools import detail_worker

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(detail_worker, "_write_durable_detail_archive", _boom)

    repo, summary = _run_raw_capture(tmp_path, archive_root=tmp_path / "archive")

    assert summary["decision"] == "detail_item_raw_captured"
    assert repo.seed_queue_counts()["seed_item_raw_detail_captured"] == 1
