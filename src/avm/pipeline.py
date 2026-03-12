import os
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Dict, Any, Optional


@dataclass
class AVMPipelineConfig:
    data_dir: str = "datas"
    alerts_threshold: float = 0.15
    alerts_limit: int = 500


class AVMPipelineManager:
    """Run AVM offline subtasks and expose run/status interfaces."""

    EXPECTED_SUBTASKS = [
        "build_canonical_dataset",
        "build_avm_features",
        "generate_avm_alerts",
    ]

    def __init__(self, data_dir: str = "datas") -> None:
        self.data_dir = data_dir
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._state: Dict[str, Any] = {
            "running": False,
            "started_at": None,
            "finished_at": None,
            "current_task": None,
            "tasks": [],
            "error": None,
            "config": None,
            "merge_manifest": {"expected_subtasks": list(self.EXPECTED_SUBTASKS)},
        }

    def _run_task(self, task_name: str, fn) -> None:
        started = datetime.now().isoformat()
        with self._lock:
            self._state["current_task"] = task_name
            self._state["tasks"].append({"name": task_name, "status": "in_progress", "started_at": started})

        try:
            result = fn()
            status = "completed"
            error = None
        except Exception as exc:
            result = None
            status = "failed"
            error = str(exc)

        with self._lock:
            for task in reversed(self._state["tasks"]):
                if task["name"] == task_name and task["status"] == "in_progress":
                    task["status"] = status
                    task["finished_at"] = datetime.now().isoformat()
                    if isinstance(result, dict):
                        task["result"] = result
                    if error:
                        task["error"] = error
                    break
            if status == "failed":
                self._state["error"] = error
                raise RuntimeError(error)

    def _execute(self, config: AVMPipelineConfig) -> None:
        from tools.build_canonical_dataset import build_canonical_dataset
        from tools.build_avm_features import build_avm_features
        from tools.generate_avm_alerts import generate_avm_alerts

        try:
            canonical_dir = os.path.join(config.data_dir, "canonical")
            avm_dir = os.path.join(config.data_dir, "avm")
            canonical_path = os.path.join(canonical_dir, "canonical.jsonl")
            feature_path = os.path.join(avm_dir, "features.jsonl")
            feature_stats_path = os.path.join(avm_dir, "feature_stats.json")
            alerts_path = os.path.join(avm_dir, "alerts.json")

            self._run_task(
                "build_canonical_dataset",
                lambda: build_canonical_dataset(data_dir=config.data_dir, output_dir=canonical_dir),
            )
            self._run_task(
                "build_avm_features",
                lambda: build_avm_features(
                    canonical_path=canonical_path,
                    output_path=feature_path,
                    stats_path=feature_stats_path,
                ),
            )
            self._run_task(
                "generate_avm_alerts",
                lambda: generate_avm_alerts(
                    data_dir=config.data_dir,
                    output_path=alerts_path,
                    threshold=config.alerts_threshold,
                    limit=config.alerts_limit,
                ),
            )
        finally:
            with self._lock:
                self._state["running"] = False
                self._state["current_task"] = None
                self._state["finished_at"] = datetime.now().isoformat()

    def _begin_run(self, config: AVMPipelineConfig) -> Dict[str, Any]:
        with self._lock:
            if self._state["running"]:
                snapshot = dict(self._state)
                snapshot["tasks"] = list(self._state.get("tasks", []))
                return {"status": "already_running", "state": snapshot}

            self._state = {
                "running": True,
                "started_at": datetime.now().isoformat(),
                "finished_at": None,
                "current_task": None,
                "tasks": [],
                "error": None,
                "config": asdict(config),
                "merge_manifest": {"expected_subtasks": list(self.EXPECTED_SUBTASKS)},
            }
            snapshot = dict(self._state)
            snapshot["tasks"] = list(self._state.get("tasks", []))
            return {"status": "started", "state": snapshot}

    def run(self, async_mode: bool = False, config: Optional[AVMPipelineConfig] = None) -> Dict[str, Any]:
        run_config = config or AVMPipelineConfig(data_dir=self.data_dir)
        init = self._begin_run(run_config)
        if init["status"] == "already_running":
            return init

        if async_mode:
            self._thread = threading.Thread(target=self._execute, args=(run_config,), daemon=True)
            self._thread.start()
            return init

        try:
            self._execute(run_config)
            status = "completed"
        except Exception:
            status = "failed"
        return {"status": status, "state": self.status()}

    # Backward-compatible wrappers
    def start_all_subtasks(self) -> Dict[str, Any]:
        return self.run(async_mode=True)

    def run_all_subtasks_sync(self) -> Dict[str, Any]:
        return self.run(async_mode=False)


    def verify_merge_completeness(self) -> Dict[str, Any]:
        state = self.status()
        expected = list(self.EXPECTED_SUBTASKS)
        observed = [t.get("name") for t in state.get("tasks", [])]
        observed_unique = []
        for name in observed:
            if name not in observed_unique:
                observed_unique.append(name)

        missing = [name for name in expected if name not in observed_unique]
        unexpected = [name for name in observed_unique if name not in expected]
        completed = [t.get("name") for t in state.get("tasks", []) if t.get("status") == "completed"]
        failed = [t.get("name") for t in state.get("tasks", []) if t.get("status") == "failed"]

        return {
            "expected_subtasks": expected,
            "observed_subtasks": observed_unique,
            "missing_subtasks": missing,
            "unexpected_subtasks": unexpected,
            "completed_subtasks": completed,
            "failed_subtasks": failed,
            "is_fully_merged": len(missing) == 0 and len(unexpected) == 0,
        }

    def status(self) -> Dict[str, Any]:
        with self._lock:
            out = dict(self._state)
            out["tasks"] = list(self._state.get("tasks", []))
            # include a lightweight runtime merge completeness check
            expected = list(self.EXPECTED_SUBTASKS)
            observed = []
            for task in out["tasks"]:
                name = task.get("name")
                if name and name not in observed:
                    observed.append(name)
            missing = [name for name in expected if name not in observed]
            unexpected = [name for name in observed if name not in expected]
            out["merge_check"] = {
                "expected_subtasks": expected,
                "observed_subtasks": observed,
                "missing_subtasks": missing,
                "unexpected_subtasks": unexpected,
                "is_fully_merged": len(missing) == 0 and len(unexpected) == 0,
            }
            return out
