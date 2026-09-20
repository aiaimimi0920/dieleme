from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from tools.pc2_settings_release import ReleaseRuntime, browser_mounts, rebase
from tools.pc2_settings_runtime import write_private


def model():
    return {"services": {"pc2-browser-solver": {
        "image": "sha256:browser", "environment": {"MODE": "test"},
        "volumes": [{"source": "/host/profile", "target": "/profile"}],
        "secrets": [{"source": "vnc", "target": "/run/secrets/vnc"}],
    }}, "secrets": {"vnc": {"file": "/host/private/vnc-password"}}}


def test_file_secret_is_an_expected_read_only_bind():
    assert browser_mounts(model()) == {
        ("/host/profile", "/profile", True),
        ("/host/private/vnc-password", "/run/secrets/vnc", False),
    }


def test_browser_only_release_rejects_secret_source_migration():
    before, after = model(), model()
    after["secrets"]["vnc"]["file"] = "/different/private/password"
    with pytest.raises(ValueError, match="secret mounts"):
        rebase(before, after, browser_only=True)


@pytest.mark.parametrize("definition", [{"external": True}, {"environment": "PASSWORD"}, {"file": "relative/path"}])
def test_unresolved_or_external_secrets_fail_closed(definition):
    value = model()
    value["secrets"]["vnc"] = definition
    with pytest.raises(ValueError, match="file-backed"):
        browser_mounts(value)


@pytest.mark.parametrize("tamper", [False, True])
def test_finish_accepts_declared_secret_but_never_ignores_extra_mount(tmp_path, tamper):
    root = tmp_path.resolve()
    directory = root / "release-test"
    directory.mkdir()
    after = model()
    write_private(directory / "after.json", after)
    write_private(root / "release-operation.json", {"directory": str(directory)})
    row = {"Image": "sha256:browser", "Config": {"Env": ["MODE=test"]},
           "State": {"Running": True, "Health": {"Status": "healthy"}},
           "Mounts": [{"Source": source, "Destination": target, "RW": rw}
                      for source, target, rw in browser_mounts(after)]}
    if tamper:
        row["Mounts"].append({"Source": "/unexpected", "Destination": "/unexpected", "RW": True})
    runtime = SimpleNamespace(root=root, active=root / "active.json", wait_ready=lambda _: True,
                              run=lambda _: json.dumps([row]))
    if tamper:
        with pytest.raises(RuntimeError, match="drifted"):
            ReleaseRuntime(runtime).finish()
        assert (root / "release-operation.json").exists()
    else:
        assert "healthy" in ReleaseRuntime(runtime).finish()
        assert json.loads(runtime.active.read_text()) == after
        assert not (root / "release-operation.json").exists()
