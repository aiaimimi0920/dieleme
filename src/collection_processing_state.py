"""Thread-safe ownership of files currently being processed by collection workers."""

from __future__ import annotations

from _thread import LockType
from collections.abc import Iterator, MutableSet
from threading import Lock


class CollectionProcessingState(MutableSet[str]):
    """Set-compatible processing registry with atomic claim and release."""

    def __init__(self) -> None:
        self._lock: LockType = Lock()
        self._paths: set[str] = set()

    def __contains__(self, value: object) -> bool:
        with self._lock:
            return value in self._paths

    def __iter__(self) -> Iterator[str]:
        with self._lock:
            return iter(tuple(self._paths))

    def __len__(self) -> int:
        with self._lock:
            return len(self._paths)

    def add(self, value: str) -> None:
        with self._lock:
            self._paths.add(value)

    def discard(self, value: str) -> None:
        with self._lock:
            self._paths.discard(value)

    def claim(self, value: str) -> bool:
        """Claim a path once; return ``False`` when another worker owns it."""

        with self._lock:
            if value in self._paths:
                return False
            self._paths.add(value)
            return True

    def release(self, value: str) -> None:
        self.discard(value)

    def snapshot(self) -> frozenset[str]:
        with self._lock:
            return frozenset(self._paths)
