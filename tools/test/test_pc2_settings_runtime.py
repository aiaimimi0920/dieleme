from copy import deepcopy

from tools.pc2_settings_controller import SettingsController, validate_command, SettingsClient
from tools.pc2_engine_controller import ControllerError
from tools.pc2_settings_model import inventory, render, workers
from tools.pc2_settings_runtime import SettingsRuntime
from tools.test.collection_settings_fixtures import FakeDocker, config_fixture, model_fixture
import pytest


def command():
    config = config_fixture()
    config["workers"].update(details=2, analysis=5)
    config["ai"]["model"] = "deepseek-new-fixture"
    return {"request_id": "settings-request-0001", "revision": 1, "claim": "a" * 64,
            "config": config, "previous": config_fixture(), "api_key": "new-synthetic-key"}


def test_pure_plan_keeps_browser_mounts_and_unrelated_environment():
    before = model_fixture()
    assert render(before, inventory(before)["effective"]) == before
    requested = command()
    after = render(before, requested["config"], requested["api_key"])
    assert after["services"]["pc2-browser-solver"] == before["services"]["pc2-browser-solver"]
    assert inventory(after)["effective"] == requested["config"]
    new = after["services"]["pc2-analysis-5"]
    assert new["volumes"] == before["services"]["pc2-analysis-1"]["volumes"]
    assert new["environment"]["KEEP_UNRELATED"] == "literal-$fixture"
    assert new["environment"]["FAPAI_DETAIL_WORKER_ID"] == "analysis-5"
    assert new["environment"]["FAPAI_OUTPUT_DIR"] == "/data/output/detail_analysis_worker_5"
    assert before == model_fixture()


@pytest.mark.parametrize("fail_new,fail_rollback,expected", [(False, False, "applied"), (True, False, "rolled_back"), (True, True, "interrupted")])
def test_scoped_recreate_and_health_checked_rollback(tmp_path, fail_new, fail_rollback, expected):
    docker = FakeDocker(fail_new=fail_new, fail_rollback=fail_rollback)
    runtime = SettingsRuntime(tmp_path, [], runner=docker, clock=lambda: docker.time, sleep=docker.sleep)
    assert runtime.apply(command()) == expected
    calls = str(docker.calls)
    assert "new-synthetic-key" not in calls
    assert "pc2-browser-solver" not in calls
    assert all(not {"--remove-orphans", "down", "rm"}.intersection(call) for call in docker.calls)
    if expected == "applied":
        assert runtime.snapshot()["effective"] == command()["config"]
    if expected == "rolled_back":
        assert runtime.snapshot()["effective"] == config_fixture()


def test_runtime_drift_prevents_mutation(tmp_path):
    docker = FakeDocker()
    docker.rows["pc2-detail-1"]["Config"]["Env"].append("FAPAI_DETAIL_MAX_ATTEMPTS=999")
    docker.rows["pc2-detail-1"]["Mounts"][0]["Source"] = "/unexpected"
    runtime = SettingsRuntime(tmp_path, [], runner=docker)
    assert runtime.apply(command()) == "rejected"
    assert all(call[0] not in ("stop", "restart") and "up" not in call for call in docker.calls)


def test_restart_after_uncertain_action_only_sends_receipt(tmp_path):
    docker = FakeDocker()
    runtime = SettingsRuntime(tmp_path, [], runner=docker)
    posts = []
    class Client:
        def post(self, action, body):
            posts.append(action)
            return {"command": command()} if action == "poll" else {"ok": True}
    first = SettingsController(Client(), runtime)
    first.persist({"request_id": "settings-request-0001", "claim": "a" * 64,
                   "result": "interrupted", "effective": None, "api_key_configured": False})
    SettingsController(Client(), runtime).step()
    assert posts == ["result"] and docker.calls == []


def test_secret_transport_and_commands_fail_closed(tmp_path):
    with pytest.raises(ControllerError):
        SettingsClient("http://192.0.2.1:8001", tmp_path / "unused-key")
    unsafe = command()
    unsafe["request_id"] = "../../outside-root"
    with pytest.raises(Exception):
        validate_command(unsafe)


def test_inventory_uses_worker_parser_defaults_and_rejects_mixed_stage():
    model = model_fixture()
    config = inventory(model)["effective"]
    assert config["intervals"]["links"] == config["intervals"]["links_idle"] == 1800
    assert config["intervals"]["details"] == config["intervals"]["details_idle"] == 900
    assert config["retries"]["detail_batch_attempts"] == 20
    model["services"]["pc2-detail-2"]["environment"]["FAPAI_DETAIL_MAX_ATTEMPTS"] = "5"
    with pytest.raises(ValueError, match="share"):
        inventory(model)


def test_custom_worker_identity_and_output_remain_untouched():
    model = model_fixture()
    env = model["services"]["pc2-detail-2"]["environment"]
    env.update(FAPAI_DETAIL_WORKER_ID="custom-detail", FAPAI_OUTPUT_DIR="/data/output/custom")
    config = inventory(model)["effective"]
    config["intervals"]["details"] = 35
    after = render(model, config)
    changed = after["services"]["pc2-detail-2"]["environment"]
    assert changed["FAPAI_DETAIL_WORKER_ID"] == "custom-detail"
    assert changed["FAPAI_OUTPUT_DIR"] == "/data/output/custom"
    for name in ("pc2-seed-1", "pc2-analysis-1"):
        assert after["services"][name] == model["services"][name]


@pytest.mark.parametrize("change", [
    lambda model: model["services"].update({"pc2-detail-9": deepcopy(model["services"]["pc2-detail-1"])}),
    lambda model: model["services"].pop("pc2-detail-2"),
])
def test_unsupported_or_sparse_worker_sets_are_rejected(change):
    model = model_fixture()
    change(model)
    with pytest.raises(ValueError):
        inventory(model)


def test_named_mounts_and_changed_baseline_cannot_trigger_recreate(tmp_path):
    docker = FakeDocker()
    runtime = SettingsRuntime(tmp_path, [], runner=docker)
    request = command()
    request["previous"]["workers"]["details"] = 2
    assert runtime.apply(request) == "rejected"
    assert not any("up" in call or call[0] == "stop" for call in docker.calls)
    docker.model["services"]["pc2-detail-1"]["volumes"][0]["type"] = "volume"
    assert not runtime.matches(docker.model, docker.rows, healthy=False)
