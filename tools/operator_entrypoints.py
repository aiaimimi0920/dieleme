from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


_BATCH_PYTHON_TARGET_PATTERN = re.compile(
    r'"%PYTHON_CMD%"\s+([^\r\n]+?\.py)(?:\s|$)',
    re.IGNORECASE | re.MULTILINE,
)


@dataclass(frozen=True)
class BatchPythonEntrypoint:
    script_path: Path
    target_path: Path
    uses_repo_root_pushd: bool


def parse_batch_python_target(text: str) -> Path | None:
    match = _BATCH_PYTHON_TARGET_PATTERN.search(text)
    if match is None:
        return None
    return Path(match.group(1).strip())


def repo_operator_entrypoints(repo_root: Path) -> list[Path]:
    auto_dir = repo_root / "auto"
    if not auto_dir.exists():
        return []
    return sorted(auto_dir.glob("*.bat"))


def collect_batch_python_entrypoints(repo_root: Path) -> list[BatchPythonEntrypoint]:
    records: list[BatchPythonEntrypoint] = []
    for script_path in repo_operator_entrypoints(repo_root):
        text = script_path.read_text(encoding="utf-8")
        target_path = parse_batch_python_target(text)
        if target_path is None:
            continue
        uses_repo_root_pushd = 'pushd "%~dp0.."' in text
        records.append(
            BatchPythonEntrypoint(
                script_path=script_path,
                target_path=target_path,
                uses_repo_root_pushd=uses_repo_root_pushd,
            )
        )
    return records
