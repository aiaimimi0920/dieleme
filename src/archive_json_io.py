"""Fail closed on unreadable archives and publish complete JSON atomically."""

import json

from src.runtime_json import load_json_file
import os
import tempfile
from pathlib import Path


def read_records(path):
    try:
        payload = load_json_file(path)
    except FileNotFoundError:
        return []
    if not isinstance(payload, list) or any(
        not isinstance(row, dict) for row in payload
    ):
        raise ValueError("Archive must contain a list of record objects")
    return payload


def write_records(path, records, *, indent=4):
    write_json(path, records, indent=indent)


def write_json(path: str | Path, value: object, *, indent: int = 4) -> None:
    target = Path(path)
    serialized = json.dumps(value, ensure_ascii=False, indent=indent)
    # Retain an incomplete/failed temporary snapshot for recovery; never truncate
    # the confirmed archive before serialization, flush and fsync all succeed.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="\n",
        prefix="." + target.name + ".pending-",
        suffix=".tmp",
        dir=target.parent,
        delete=False,
    ) as handle:
        handle.write(serialized)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = handle.name
    os.replace(temporary, target)
