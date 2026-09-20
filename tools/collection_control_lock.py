"""One lock for settings, restarts and release changes on the PC2 host."""
from contextlib import contextmanager
import os
from pathlib import Path


def private_root(root):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == "posix" and (root.is_symlink() or root.stat().st_uid != os.geteuid() or root.stat().st_mode & 0o077):
        raise RuntimeError("Collection control directory must be owner-only")
    return root


@contextmanager
def operation_lock(root, *, name="operation.lock"):
    import fcntl
    root = private_root(root)
    descriptor = os.open(root / name, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "a") as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            fcntl.flock(stream, fcntl.LOCK_UN)
