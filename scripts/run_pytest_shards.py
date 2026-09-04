from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ARTIFACT_ROOT = REPO_ROOT / "artifacts" / "pytest-shards"
KNOWN_FILE_WEIGHTS = {
    "tools/test/test_run_hybrid_seed_collection.py": 120,
    "tools/test/test_seed_collector.py": 100,
    "tools/test/test_db_dual_write.py": 80,
    "tools/test/test_detail_worker.py": 50,
    "tools/test/test_avm_http_contract.py": 50,
    "tools/test/test_live_batch_smoke.py": 40,
}
_TEST_NODE_PATTERN = re.compile(r"^((?:tests|tools/test)/[^:\s]+\.py)::")


def parse_collection_test_files(output: str) -> list[str]:
    files: set[str] = set()
    for line in output.splitlines():
        normalized = line.strip().replace("\\", "/")
        match = _TEST_NODE_PATTERN.match(normalized)
        if match:
            files.add(match.group(1))
    return sorted(files)


def collect_test_files() -> list[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "--disable-warnings"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env={**os.environ, "PYTHONUTF8": "1", "CROW_OFFLINE_TESTS": "1"},
        check=False,
    )
    if result.returncode:
        tail = "\n".join((result.stdout + "\n" + result.stderr).splitlines()[-80:])
        raise RuntimeError(f"pytest collection failed\n{tail}")
    files = parse_collection_test_files(result.stdout)
    if not files:
        raise RuntimeError("pytest collection returned no test files")
    missing = [path for path in files if not (REPO_ROOT / path).is_file()]
    if missing:
        raise RuntimeError(f"pytest collection returned missing test files: {missing}")
    return files


def assign_shards(files: list[str], shard_count: int) -> list[list[str]]:
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    shards: list[list[str]] = [[] for _ in range(shard_count)]
    totals = [0 for _ in range(shard_count)]
    weighted = sorted(
        files,
        key=lambda path: (-KNOWN_FILE_WEIGHTS.get(path, 10), path),
    )
    for path in weighted:
        shard_index = min(range(shard_count), key=lambda index: (totals[index], index))
        shards[shard_index].append(path)
        totals[shard_index] += KNOWN_FILE_WEIGHTS.get(path, 10)
    return [sorted(shard) for shard in shards]


def _stop_process_tree(process: subprocess.Popen[str]) -> bool:
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
        except subprocess.TimeoutExpired:
            return False
        return result.returncode == 0
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return True
    return True


def _collect_after_timeout(
    process: subprocess.Popen[str],
    partial_output: str | bytes | None,
) -> str:
    output = partial_output.decode("utf-8", errors="replace") if isinstance(
        partial_output,
        bytes,
    ) else str(partial_output or "")
    stopped = _stop_process_tree(process)
    if not stopped:
        try:
            process.kill()
        except OSError:
            pass
    try:
        completed_output, _ = process.communicate(timeout=5)
        return completed_output or output
    except subprocess.TimeoutExpired:
        try:
            process.kill()
        except OSError:
            pass
    try:
        completed_output, _ = process.communicate(timeout=5)
        return completed_output or output
    except subprocess.TimeoutExpired:
        if process.stdout is not None:
            process.stdout.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return output


def _artifact_name(path: str) -> str:
    stem = Path(path).stem
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:10]
    return f"{stem}-{digest}"


def run_test_file(
    path: str,
    *,
    timeout_seconds: int,
    artifact_root: Path,
    pytest_args: list[str],
) -> dict[str, Any]:
    artifact_root.mkdir(parents=True, exist_ok=True)
    artifact_name = _artifact_name(path)
    junit_path = artifact_root / f"{artifact_name}.xml"
    log_path = artifact_root / f"{artifact_name}.log"
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-q",
        "--disable-warnings",
        "--tb=short",
        f"--junitxml={junit_path}",
        path,
        *pytest_args,
    ]
    environment = dict(os.environ)
    environment["CROW_OFFLINE_TESTS"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["PYTHONUTF8"] = "1"
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=environment,
        start_new_session=os.name != "nt",
    )
    timed_out = False
    try:
        output, _ = process.communicate(timeout=max(timeout_seconds, 1))
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        output = _collect_after_timeout(process, exc.output)
    duration = round(time.monotonic() - started, 3)
    log_path.write_text(output, encoding="utf-8")
    status = "timeout" if timed_out else "passed" if process.returncode == 0 else "failed"
    return {
        "path": path,
        "status": status,
        "exit_code": process.returncode,
        "duration_seconds": duration,
        "junit_path": str(junit_path.relative_to(REPO_ROOT)),
        "log_path": str(log_path.relative_to(REPO_ROOT)),
        "output_tail": output.splitlines()[-40:] if status != "passed" else [],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run all collected pytest files in isolated deterministic shards.")
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--file-timeout", type=int, default=600)
    parser.add_argument("--artifact-root", type=Path, default=DEFAULT_ARTIFACT_ROOT)
    parser.add_argument("--summary", type=Path)
    parser.add_argument("--list", action="store_true", help="Print the selected files without running them.")
    parser.add_argument("pytest_args", nargs=argparse.REMAINDER)
    return parser.parse_args(argv)


def _resolve_artifact_path(path: Path) -> Path:
    artifact_root = (REPO_ROOT / "artifacts").resolve()
    candidate = path.expanduser()
    if not candidate.is_absolute():
        candidate = REPO_ROOT / candidate
    candidate = candidate.resolve()
    try:
        candidate.relative_to(artifact_root)
    except ValueError as exc:
        raise ValueError("pytest shard artifacts must stay under the repository artifacts directory") from exc
    return candidate


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not 0 <= args.shard_index < args.shard_count:
        raise ValueError("shard_index must be within shard_count")
    if args.file_timeout < 1:
        raise ValueError("file_timeout must be at least 1 second")
    pytest_args = list(args.pytest_args)
    if pytest_args[:1] == ["--"]:
        pytest_args = pytest_args[1:]
    if any(arg == "--allow-live-network" or arg.startswith("--allow-live-network=") for arg in pytest_args):
        raise ValueError("the offline shard runner cannot enable live network access")
    files = assign_shards(collect_test_files(), args.shard_count)[args.shard_index]
    if args.list:
        print(json.dumps({"shard_index": args.shard_index, "files": files}, indent=2))
        return 0
    artifact_root = _resolve_artifact_path(args.artifact_root)
    results = [
        run_test_file(
            path,
            timeout_seconds=args.file_timeout,
            artifact_root=artifact_root,
            pytest_args=pytest_args,
        )
        for path in files
    ]
    counts = {
        status: sum(result["status"] == status for result in results)
        for status in ("passed", "failed", "timeout")
    }
    summary = {
        "schema_version": "pytest_file_shard_v1",
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "file_timeout_seconds": args.file_timeout,
        "counts": counts,
        "duration_seconds": round(sum(result["duration_seconds"] for result in results), 3),
        "results": results,
    }
    summary_path = (
        _resolve_artifact_path(args.summary)
        if args.summary
        else artifact_root / f"shard-{args.shard_index}-of-{args.shard_count}.json"
    )
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**summary, "results": []}, indent=2))
    return 0 if counts["failed"] == 0 and counts["timeout"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
