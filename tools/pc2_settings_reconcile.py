"""Explicit image-only release reconciliation; never accept arbitrary drift."""
from copy import deepcopy
import hashlib
import json
import os
import re
import uuid

from .collection_control_lock import operation_lock
from .pc2_settings_release import browser_mounts
from .pc2_settings_runtime import write_private


def reconcile_images(runtime, *, expected_sha256, images):
    """Run only for an authorized deployment with an explicit image manifest."""
    with operation_lock(runtime.root):
        for name in ('release-operation.json', 'pending-receipt.json', 'restart-receipt.json'):
            if (runtime.root / name).exists():
                raise ValueError('An operation needs reconciliation before image adoption')
        raw = runtime.active.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_sha256:
            raise ValueError('Active configuration changed')
        before = json.loads(raw)
        if not images or set(images) - set(before['services']):
            raise ValueError('Invalid release image scope')
        after = deepcopy(before)
        for name, image in images.items():
            if not isinstance(image, str) or not re.fullmatch(r'sha256:[a-f0-9]{64}', image):
                raise ValueError('Release images must be immutable IDs')
            after['services'][name]['image'] = image
        rows = runtime.inspect()
        if not runtime.matches(after, rows, healthy=True):
            raise ValueError('Worker drift is not an image-only healthy release')
        browser = json.loads(runtime.run(['inspect', 'fapaifang-pc2-browser-solver']))[0]
        service = after['services']['pc2-browser-solver']
        env = dict(v.split('=', 1) for v in browser['Config']['Env'])
        mounts = {(m['Source'], m['Destination'], m['RW']) for m in browser['Mounts']}
        if (service['image'] not in (browser['Image'], browser['Config'].get('Image'))
                or not browser['State']['Running']
                or browser['State'].get('Health', {}).get('Status') != 'healthy'
                or any(env.get(k) != str(v) for k, v in service.get('environment', {}).items())
                or mounts != browser_mounts(after)):
            raise ValueError('Browser release contract does not match')
        directory = runtime.root / ('release-reconcile-' + uuid.uuid4().hex)
        directory.mkdir(mode=0o700)
        write_private(directory / 'before.json', before)
        write_private(directory / 'after.json', after)
        staged = directory / 'active.json'
        write_private(staged, after)
        # Compare again immediately before publication; never overwrite edits.
        if runtime.active.read_bytes() != raw:
            raise ValueError('Active configuration changed before publication')
        os.replace(staged, runtime.active)
        return {'ok': True, 'services': sorted(images), 'backup': str(directory / 'before.json')}


def main():
    import argparse
    from pathlib import Path
    from .pc2_settings_runtime import SettingsRuntime
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    if not isinstance(manifest, dict) or set(manifest) != {'expected_sha256', 'images'}:
        parser.error('Expected a checksum and explicit image manifest')
    print(json.dumps(reconcile_images(SettingsRuntime(args.runtime_root.resolve(), []), **manifest)))


if __name__ == '__main__':
    main()
