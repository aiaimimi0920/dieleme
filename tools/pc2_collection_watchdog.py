"""Host-side browser liveness recovery, independent of NAS availability.

Docker's unless-stopped policy supervises container exits. This covers a stuck
browser whose container remains alive. Call only under the controller's lock.
"""
import json
import logging
import math
import os
from pathlib import Path
import time

from .pc2_container_inventory import BROWSER, PROJECT, canonical_containers
from .pc2_settings_runtime import run, write_private


class CollectionWatchdog:
    def __init__(self, root, *, runner=run, clock=time.time, grace=120, cooldown=600, max_attempts=3):
        self.path = Path(root) / "watchdog.json"
        self.run, self.clock = runner, clock
        self.grace, self.cooldown = grace, cooldown
        self.max_attempts = max(1, int(max_attempts))
        self.unhealthy_since = None
        self.identity = None

    def _read_state(self):
        try:
            previous = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        if not isinstance(previous, dict):
            raise ValueError("watchdog state must be an object")
        attempts = previous.get("consecutive_attempts", 0)
        attempted_at = previous.get("attempted_at", 0)
        if type(attempts) is not int or attempts < 0:
            raise ValueError("invalid watchdog restart count")
        if type(attempted_at) not in (int, float) or not math.isfinite(attempted_at) or attempted_at < 0:
            raise ValueError("invalid watchdog restart timestamp")
        return previous

    def step(self):
        ids = self.run(["ps", "-aq", "--filter", "label=com.docker.compose.project=" + PROJECT]).split()
        rows = canonical_containers(json.loads(self.run(["inspect", *ids]))) if ids else {}
        row = rows.get(BROWSER)
        state = row.get("State", {}) if row else {}
        try:
            previous = self._read_state()
        except (OSError, ValueError, OverflowError):
            # Preserve unreadable state; resetting it would reset the restart cap.
            logging.getLogger(__name__).error("Watchdog state unavailable; automatic restart suspended")
            return "state_unavailable"
        # Never resurrect deliberately stopped containers or retained backups.
        if not state.get("Running") or state.get("Health", {}).get("Status") != "unhealthy":
            self.unhealthy_since = None
            if state.get("Running") and state.get("Health", {}).get("Status") == "healthy" and previous.get("consecutive_attempts"):
                self.persist({**previous, "consecutive_attempts": 0, "result": "healthy", "alert": None})
            return "healthy_or_stopped"
        identity = (row["Id"], state.get("StartedAt"))
        now = self.clock()
        if self.identity != identity or self.unhealthy_since is None:
            self.identity, self.unhealthy_since = identity, now
        attempts = int(previous.get("consecutive_attempts", 0)) if previous.get("container_id") == row["Id"] else 0
        if attempts >= self.max_attempts:
            if previous.get("result") != "restart_limit_reached":
                self.persist({**previous, "result": "restart_limit_reached", "alert": "manual_intervention_required"})
                print("Collection watchdog restart limit reached; manual intervention required", flush=True)
            return "restart_limit_reached"
        cooldown = min(3600, self.cooldown * 2 ** max(0, attempts - 1))
        if now - self.unhealthy_since < self.grace or now - previous.get("attempted_at", 0) < cooldown:
            return "waiting"
        # Recheck the exact identity immediately before the only permitted mutation.
        fresh = canonical_containers(json.loads(self.run(["inspect", row["Id"]]))).get(BROWSER)
        current = fresh.get("State", {}) if fresh else {}
        if (not current.get("Running") or current.get("StartedAt") != state.get("StartedAt")
                or current.get("Health", {}).get("Status") != "unhealthy"):
            return "state_changed"
        receipt = {"container_id": row["Id"], "attempted_at": now, "result": "interrupted", "consecutive_attempts": attempts + 1}
        self.persist(receipt)
        try:
            self.run(["restart", "--time", "30", row["Id"]], timeout=60)
        except Exception:
            self.persist({**receipt, "result": "restart_failed", "alert": "restart_command_failed"})
            raise
        self.persist({**receipt, "result": "restart_requested"})
        self.unhealthy_since = None
        print("Collection watchdog restarted unhealthy PC2 browser; readiness pending", flush=True)
        return "restart_requested"

    def persist(self, value):
        staged = self.path.with_suffix(".new")
        if staged.exists():
            staged.unlink()
        write_private(staged, value)
        os.replace(staged, self.path)
