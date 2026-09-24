from __future__ import annotations

import ctypes

import json

import sys

import types

from src import captcha_solver

import threading
import pytest


@pytest.fixture(autouse=True)
def _inject_solver_test_waits(monkeypatch):
    """Keep legacy mocked sleep clocks explicit; deadline tests use the real Event."""
    class TestWaitEvent(threading.Event):
        def wait(self, timeout=None):
            if not self.is_set():
                captcha_solver.time.sleep(timeout or 0)
            return self.is_set()

    monkeypatch.setattr("src.captcha_budget.Event", TestWaitEvent)

__all__ = [name for name in globals() if not name.startswith("__")]
