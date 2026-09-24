"""Exercise the production shell supervisor using only short-lived dummy children."""
import os
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(os.name == "nt", reason="POSIX child signaling requires the Linux CI job")
@pytest.mark.parametrize("child_status", [0, 7])
def test_any_child_exit_stops_and_reaps_siblings(tmp_path, child_status):
    bash = shutil.which("bash")
    if not bash:
        pytest.fail("Linux supervision gate requires bash")
    supervisor = Path(__file__).resolve().parents[2] / "ops/pc2-linux/process-supervisor.sh"
    script = '''
set -euo pipefail
source "$1"
pids=()
trap crow_stop_children EXIT
export FAPAI_BROWSER_SHUTDOWN_GRACE_SECONDS=1
sleep 30 &
sibling=$!
pids+=("$sibling")
(sleep 0.1; exit "$2") &
pids+=("$!")
result=0
crow_wait_children || result=$?
test "$result" -ne 0
crow_stop_children
! kill -0 "$sibling" 2>/dev/null
test "${#pids[@]}" -eq 0
'''
    result = subprocess.run([bash, "-c", script, "supervisor-test", str(supervisor), str(child_status)],
                            cwd=tmp_path, capture_output=True, text=True, timeout=8, check=False)
    assert result.returncode == 0, result.stderr
