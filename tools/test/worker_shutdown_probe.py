"""Real POSIX SIGTERM probe. Uses only a new temporary directory and child process."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def main() -> None:
    if os.name != "posix":
        raise RuntimeError("Run this probe in an isolated Linux container")
    root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory(prefix="crow-worker-shutdown-") as temporary:
        directory = Path(temporary)
        heartbeat, receipt = directory / "heartbeat.json", directory / "released.json"
        source = (
            "from pathlib import Path; from tools.worker_lifecycle import WorkerLifecycle; "
            "import sys; "
            "lifecycle = WorkerLifecycle('probe', lambda worker: Path(sys.argv[2]).write_text(worker), Path(sys.argv[1])); "
            "lifecycle.__enter__(); lifecycle.wait(600); lifecycle.__exit__(None, None, None)"
        )
        child = subprocess.Popen([sys.executable, "-c", source, str(heartbeat), str(receipt)], cwd=root)
        try:
            deadline = time.monotonic() + 10
            while not heartbeat.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            if not heartbeat.exists():
                raise RuntimeError("worker did not publish its startup heartbeat")
            started = time.monotonic()
            child.terminate()
            code = child.wait(timeout=5)
            if code != 0 or receipt.read_text() != "probe" or json.loads(heartbeat.read_text())["stage"] != "stopped":
                raise RuntimeError("worker did not exit cooperatively and release its lease")
            print(json.dumps({"ok": True, "exit_code": code, "shutdown_seconds": round(time.monotonic() - started, 3)}))
        finally:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)


if __name__ == "__main__":
    main()
