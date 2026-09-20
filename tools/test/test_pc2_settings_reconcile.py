from contextlib import nullcontext
from copy import deepcopy
import hashlib
import json

import pytest

from tools import pc2_settings_reconcile as reconcile
from tools.pc2_settings_runtime import SettingsRuntime, write_private
from tools.test.collection_settings_fixtures import FakeDocker


def fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(reconcile, 'operation_lock', lambda _: nullcontext())
    docker = FakeDocker()
    browser = {'Image': 'sha256:' + 'c' * 64,
               'Config': {'Env': ['KEEP_BROWSER=yes']},
               'State': {'Running': True, 'Health': {'Status': 'healthy'}}, 'Mounts': []}
    def run(args, **kwargs):
        if args == ['inspect', 'fapaifang-pc2-browser-solver']:
            return json.dumps([browser])
        return docker(args, **kwargs)
    runtime = SettingsRuntime(tmp_path, [], runner=run)
    write_private(runtime.active, docker.model)
    checksum = hashlib.sha256(runtime.active.read_bytes()).hexdigest()
    docker.rows['pc2-seed-1']['Image'] = 'sha256:' + 'b' * 64
    images = {'pc2-seed-1': 'sha256:' + 'b' * 64, 'pc2-browser-solver': browser['Image']}
    return runtime, docker, browser, checksum, images


def test_explicit_image_reconciliation_preserves_settings_and_never_restarts(tmp_path, monkeypatch):
    runtime, docker, _, checksum, images = fixture(tmp_path, monkeypatch)
    before = deepcopy(docker.model)
    result = reconcile.reconcile_images(runtime, expected_sha256=checksum, images=images)
    assert result['ok']
    after = json.loads(runtime.active.read_text())
    for name, image in images.items():
        before['services'][name]['image'] = image
    assert before == after
    assert runtime.snapshot()['effective']
    assert all(call[0] in ('ps', 'inspect') for call in docker.calls)


@pytest.mark.parametrize('bad', ['checksum', 'env', 'mount', 'browser', 'journal', 'mutable'])
def test_reconciliation_fails_closed_for_non_image_drift(tmp_path, monkeypatch, bad):
    runtime, docker, browser, checksum, images = fixture(tmp_path, monkeypatch)
    original = runtime.active.read_bytes()
    if bad == 'checksum': checksum = '0' * 64
    if bad == 'env': docker.rows['pc2-seed-1']['Config']['Env'].append('KEEP_UNRELATED=changed')
    if bad == 'mount': docker.rows['pc2-seed-1']['Mounts'][0]['Source'] = '/unexpected'
    if bad == 'browser': browser['Mounts'].append({'Source': '/other', 'Destination': '/profile', 'RW': True})
    if bad == 'journal': (tmp_path / 'pending-receipt.json').write_text('{}')
    if bad == 'mutable': images['pc2-seed-1'] = 'worker:latest'
    with pytest.raises(ValueError):
        reconcile.reconcile_images(runtime, expected_sha256=checksum, images=images)
    assert runtime.active.read_bytes() == original
