"""Process-local store reuse and cancellable qualification waits."""
from collections import OrderedDict
import os
import threading

from src.llm_model_selector import LLMBackendUnavailableError
from src.llm_qualification_store import QualificationStore

_LOCK = threading.Lock()
_STORES = OrderedDict()
_MAX_STORES = 16


class QualificationCancelled(LLMBackendUnavailableError):
    def __init__(self):
        super().__init__("LLM backend unavailable: qualification request cancelled")


def shared_store(config):
    path = QualificationStore.resolve_path()
    # Cache only digests, never credentials. Include PID for forked workers.
    key = (os.getpid(), path, QualificationStore.identity(config))
    with _LOCK:
        store = _STORES.get(key)
        if store is None:
            store = QualificationStore(config, path)
            _STORES[key] = store
        _STORES.move_to_end(key)
        while len(_STORES) > _MAX_STORES:
            _STORES.popitem(last=False)
        return store


def check_cancelled(event):
    if event.is_set():
        raise QualificationCancelled()


def wait_for_slot(event, seconds):
    if event.wait(seconds):
        raise QualificationCancelled()
