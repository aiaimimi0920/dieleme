"""Only an explicit JSON false may activate a maintenance write."""

import json
from types import SimpleNamespace

import pytest

from src import server
from tools.test.collection_job_checks import wait_for_job
from tools.test.test_http_write_access import OPERATOR
from tools.test.test_http_write_access import configured_api as configured_api
from tools.test.test_quality_http_guards import api as api


@pytest.mark.parametrize(
    "path",
    [
        "/api/avm/recent_detail_replay",
        "/api/collection/details/prepare_replay",
        "/api/collection/details/fetch_missing",
    ],
)
@pytest.mark.parametrize("dry_run", [None, 0, "", "false", False])
def test_maintenance_requires_explicit_write_opt_in(
    configured_api, monkeypatch, path, dry_run, tmp_path
):
    calls = []
    reloads = []
    monkeypatch.setattr(server, "AVM_SERVICE", SimpleNamespace(data_dir=str(tmp_path)))

    def run(**options):
        calls.append(options)
        return {"prepared_count": 1, "fetched_count": 1}

    monkeypatch.setattr(
        server,
        "_detail_collection_service",
        lambda _: SimpleNamespace(prepare_replay=run, fetch_missing_archives=run),
    )
    monkeypatch.setattr(server, "load_data", lambda *_: reloads.append(True))
    status, _, raw = configured_api(
        "POST",
        path,
        json.dumps({"dry_run": dry_run, "limit": 0}),
        {"X-FAPAI-Control-Token": OPERATOR},
    )
    assert status == 202, raw

    def fetch(url):
        status, _, raw = configured_api(
            "GET", url, headers={"X-FAPAI-Control-Token": OPERATOR}
        )
        assert status == 200, raw
        return json.loads(raw)

    assert wait_for_job(fetch, json.loads(raw)["status_url"])["status"] == "completed"
    assert len(calls) == 1
    assert calls[0]["dry_run"] is (dry_run is not False)
    assert calls[0]["limit"] == 0
    assert reloads == ([True] if dry_run is False else [])
