"""Fake Docker only: these tests never launch or restart a service."""

import copy
import json
import subprocess
from types import SimpleNamespace

import pytest

from tools.pc2_engine_controller import ControllerError, EngineController, MailboxClient, PROJECT, run_loop, validate_command

SERVICES = ["pc2-seed-1", *(f"pc2-detail-{i}" for i in range(1, 4)), *(f"pc2-analysis-{i}" for i in range(1, 5))]


def output(arguments, rows):
    return SimpleNamespace(stdout=" ".join(row["Id"] for row in rows) if arguments[0] == "ps" else json.dumps(rows))


def containers(*, started="before", health="healthy"):
    return [{"Id": f"{n:064x}", "Name": "/fapaifang-" + service, "Config": {"Labels": {"com.docker.compose.project": PROJECT, "com.docker.compose.service": service}},
             "State": {"Running": True, "StartedAt": started, "Health": {"Status": health}}} for n, service in enumerate(SERVICES, 1)]


def test_controller_restarts_only_active_workers_and_verifies_new_health():
    calls = []
    restarted = False

    def run(arguments, *, timeout):
        nonlocal restarted
        calls.append(arguments)
        if arguments[0] == "restart":
            restarted = True
            return SimpleNamespace(stdout="")
        return output(arguments, containers(started="after" if restarted else "before"))

    assert EngineController(run=run).restart() == "workers_ready"
    mutations = [call for call in calls if call[0] not in {"inspect", "ps"}]
    assert sorted(mutations) == sorted(
        ["restart", "--time", "30", f"{n:064x}"] for n in range(1, len(SERVICES) + 1)
    )
    assert all("browser" not in argument for call in calls for argument in call)


@pytest.mark.parametrize("problem", ["project", "service", "missing", "duplicate"])
def test_mismatched_container_identity_never_mutates(problem):
    rows = containers()
    if problem == "project":
        rows[0]["Config"]["Labels"]["com.docker.compose.project"] = "different-project"
    elif problem == "service":
        rows[0]["Config"]["Labels"]["com.docker.compose.service"] = "pc2-browser-solver"
    elif problem == "missing":
        rows.pop(-2)
    else:
        rows[1] = copy.deepcopy(rows[0])
    calls = []

    def run(arguments, *, timeout):
        calls.append(arguments)
        return output(arguments, rows)

    assert EngineController(run=run).restart() == "restart_failed"
    assert all(call[0] in {"inspect", "ps"} for call in calls)


def test_failure_after_docker_attempt_is_unknown_not_success():
    def run(arguments, *, timeout):
        if arguments[0] == "restart":
            raise subprocess.CalledProcessError(1, "docker")
        return output(arguments, containers())
    assert EngineController(run=run).restart() == "controller_interrupted"


def test_old_started_at_never_counts_as_success():
    clock = [0]

    def sleep(seconds):
        clock[0] += seconds

    def run(arguments, *, timeout):
        return output(arguments, containers())

    controller = EngineController(run=run, clock=lambda: clock[0], sleep=sleep)
    assert controller.restart() == "health_timeout"


def test_client_rejects_credential_urls_redirect_targets_and_unapproved_http(tmp_path):
    token = tmp_path / "unused.token"
    for url in ("http://user:password@localhost", "file:///etc/passwd", "https://nas/api?token=x", "https://nas/arbitrary", "http://nas"):
        with pytest.raises(ControllerError):
            MailboxClient(url, token)
    assert MailboxClient("https://nas/api", token).url == "https://nas/api/collection/control/restart"
    assert MailboxClient("http://nas", token, allow_insecure_http=True).url.startswith("http://nas/")


def test_command_cannot_inject_targets_or_shell():
    valid = {"request_id": "request-controller-001", "claim": "a" * 64, "action": "restart_collection_workers"}
    assert validate_command(valid) == valid
    for payload in ({**valid, "targets": ["nas"]}, {**valid, "action": "shutdown"}, {**valid, "request_id": "$(reboot)"}):
        with pytest.raises(ControllerError):
            validate_command(payload)


def test_receipt_timeout_retries_reporting_without_restarting_again():
    class StopLoop(Exception):
        pass

    command = {"request_id": "request-controller-001", "claim": "a" * 64, "action": "restart_collection_workers"}
    reports, restarts, polls = [], [], []

    class Client:
        def post(self, action, payload):
            if action == "poll":
                polls.append(True)
                return {"ok": True, "command": command if len(polls) == 1 else None}
            reports.append(dict(payload))
            if len(reports) == 1:
                raise OSError("Synthetic receipt timeout")
            return {"ok": True}

    controller = SimpleNamespace(inspect=lambda: None, restart=lambda: restarts.append(True) or "workers_ready")

    def sleep(_):
        if len(reports) == 2:
            raise StopLoop()

    with pytest.raises(StopLoop):
        run_loop(Client(), controller, sleep=sleep)
    assert restarts == [True]
    assert len(reports) == 2 and reports[0] == reports[1]
    assert reports[0]["claim"] == command["claim"]


def test_poll_loop_validates_command_before_any_docker_restart():
    class StopLoop(Exception):
        pass

    restarts = []
    client = SimpleNamespace(post=lambda *_: {"ok": True, "command": {"action": "reboot"}})
    controller = SimpleNamespace(inspect=lambda: None, restart=lambda: restarts.append(True))

    def sleep(_):
        raise StopLoop()

    with pytest.raises(StopLoop):
        run_loop(client, controller, sleep=sleep)
    assert not restarts
