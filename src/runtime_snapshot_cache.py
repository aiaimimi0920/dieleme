"""Bounded, copy-isolated cache for read-only JSON and JSONL status snapshots."""

from collections import OrderedDict
from copy import deepcopy
from .runtime_json import MAX_JSON_NESTING, exceeds_json_nesting, loads_bounded_json
from pathlib import Path
from threading import RLock
from typing import Any

_DEFAULT_EMPTY = object()
_MAX_JSON_NESTING = MAX_JSON_NESTING
_exceeds_json_nesting = exceeds_json_nesting


class SnapshotCache:
    def __init__(self, max_entries: int = 128, max_bytes: int = 8 * 1024 * 1024):
        self.max_entries = max_entries
        self.max_bytes = max_bytes
        self._entries: OrderedDict = OrderedDict()
        self._bytes = 0
        self._lock = RLock()

    @staticmethod
    def _signature(path: Path) -> tuple[int, int, int, int]:
        stat = path.stat()
        return stat.st_mtime_ns, stat.st_size, stat.st_ctime_ns, stat.st_ino

    def _discard(self, key: tuple[Path, bool]) -> None:
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._bytes -= previous[0][1]

    def read(
        self, path: Path, *, lines: bool = False, invalid: Any = _DEFAULT_EMPTY
    ) -> Any:
        empty = ([] if lines else {}) if invalid is _DEFAULT_EMPTY else invalid
        key = None
        try:
            path = Path(path).resolve()
            key = (path, lines)
            signature = self._signature(path)
            with self._lock:
                previous = self._entries.get(key)
                if previous is not None and previous[0] == signature:
                    self._entries.move_to_end(key)
                    return deepcopy(previous[1])
                self._discard(key)
            text = path.read_text(encoding="utf-8")
            if lines:
                payload = []
                for line in text.splitlines():
                    if not line.strip():
                        continue
                    if _exceeds_json_nesting(line):
                        raise ValueError("JSON nesting exceeds cache limit")
                    row = loads_bounded_json(line)
                    if isinstance(row, dict):
                        payload.append(row)
            else:
                if _exceeds_json_nesting(text):
                    raise ValueError("JSON nesting exceeds cache limit")
                payload = loads_bounded_json(text)
                if not isinstance(payload, dict):
                    return empty
            # Do not cache or publish a snapshot that changed while it was read.
            if self._signature(path) != signature:
                return empty
            with self._lock:
                self._discard(key)
                if self.max_entries > 0 and signature[1] <= self.max_bytes:
                    self._entries[key] = (signature, payload)
                    self._bytes += signature[1]
                    while (
                        len(self._entries) > self.max_entries
                        or self._bytes > self.max_bytes
                    ):
                        self._discard(next(iter(self._entries)))
            return deepcopy(payload)
        except (OSError, ValueError, UnicodeError, RecursionError):
            if key is not None:
                with self._lock:
                    self._discard(key)
            return empty


snapshots = SnapshotCache()
