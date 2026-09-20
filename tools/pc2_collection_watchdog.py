"""Host-side browser liveness recovery, independent of NAS availability.

Docker's unless-stopped policy supervises container exits. This covers a stuck
browser whose container remains alive. Call only under the controller's lock.
"""
import json
import os
from pathlib import Path
import time

from .pc2_container_inventory import BROWSER, PROJECT, canonical_containers
from .pc2_settings_runtime import run, write_private


class CollectionWatchdog:
    def __init__(self, root, *, runner=run, clock=time.time, grace=120, cooldown=600):
        self.path = Path(root) / "watchdog.json"
        self.run, self.clock = runner, clock
        self.grace, self.cooldown = grace, cooldown
        self.unhealthy_since = None
        self.identity = None

    def step(self):
        ids = self.run(["ps", "-aq", "--filter", "label=com.docker.compose.project=" + PROJECT]).split()
        rows = canonical_containers(json.loads(self.run(["inspect", *ids]))) if ids else {}
        row = rows.get(BROWSER)
        state = row.get("State", {}) if row else {}
        # Never resurrect deliberately stopped containers or retained backups.
        if not state.get("Running") or state.get("Health", {}).get("Status") != "unhealthy":
            self.unhealthy_since = None
            return "healthy_or_stopped"
        identity = (row["Id"], state.get("StartedAt"))
        now = self.clock()
        if self.identity != identity or self.unhealthy_since is None:
            self.identity, self.unhealthy_since = identity, now
        previous = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        if now - self.unhealthy_since < self.grace or now - previous.get("attempted_at", 0) < self.cooldown:
            return "waiting"
        receipt = {"container_id": row["Id"], "attempted_at": now, "result": "interrupted"}
        self.persist(receipt)
        # Recheck the exact identity immediately before the only permitted mutation.
        fresh = canonical_containers(json.loads(self.run(["inspect", row["Id"]]))).get(BROWSER)
        current = fresh.get("State", {}) if fresh else {}
        if (not current.get("Running") or current.get("StartedAt") != state.get("StartedAt")
                or current.get("Health", {}).get("Status") != "unhealthy"):
            return "state_changed"
        self.run(["restart", "--time", "30", row["Id"]], timeout=60)
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
