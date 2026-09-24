"""Collection runtime state with an explicit, shared control transaction lock."""

import time
from _thread import LockType, RLock
from dataclasses import dataclass, field
from threading import Lock

from src.auth_cookie_snapshot_state import AuthCookieSnapshotState
from src.collection_control_state import CollectionControlState
from src.collection_processing_state import CollectionProcessingState
from src.collection_runtime_index import CollectionRuntimeIndex
from src.solver_execution_state import SolverExecutionState
from src.solver_recovery_state import SolverRecoveryState


@dataclass
class RuntimeState:
    lock: RLock = field(default_factory=RLock, repr=False)
    retry_lock: LockType = field(default_factory=Lock, repr=False)
    initialization_lock: LockType = field(default_factory=Lock, repr=False)
    file_lock: LockType = field(default_factory=Lock, repr=False)
    started_at: float = field(default_factory=time.time)
    initialized: bool = False
    solver: SolverExecutionState = field(init=False)
    recovery: SolverRecoveryState = field(init=False)
    control: CollectionControlState = field(init=False)
    processing: CollectionProcessingState = field(init=False)
    cookie_snapshot: AuthCookieSnapshotState = field(init=False)
    collection: CollectionRuntimeIndex = field(init=False)

    def __post_init__(self) -> None:
        self.solver = SolverExecutionState(lock=self.lock)
        self.recovery = SolverRecoveryState(lock=self.lock)
        self.control = CollectionControlState(lock=self.lock)
        self.processing = CollectionProcessingState()
        self.cookie_snapshot = AuthCookieSnapshotState(lock=self.lock)
        self.collection = CollectionRuntimeIndex()
