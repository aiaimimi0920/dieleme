from __future__ import annotations

import json
import random
import threading

from src.llm_config import CONFIG_FILE, MODEL_POOL


AUTH_INVALID_ERROR_CODES = {11200}


class LLMBackendUnavailableError(RuntimeError):
    """Raised when no configured LLM backend is currently usable."""


class ModelSelector:
    """
    Counter-based model selector with RUNTIME-ADJUSTABLE concurrency limits.
    - Uses counters + Condition variables instead of pre-allocated queues
    - Limits can be changed at runtime without restart
    - Supports task-type based routing and statistics tracking
    """
    def __init__(self, pool):
        self.pool = pool
        self.lock = threading.Lock()
        self.condition = threading.Condition(self.lock)

        # Per-model active counts and limits (can be changed at runtime)
        self.active_counts = {m["name"]: 0 for m in pool}
        self.limits = {m["name"]: m.get("max_concurrent", 5) for m in pool}

        # Statistics tracking
        self.stats = {m["name"]: {"success": 0, "error": 0, "concurrency_error": 0, "active": 0} for m in pool}
        self.stats_lock = threading.Lock()
        self.disabled_models = {}

        # Track base models for community search
        self.base_models = [m for m in pool if "Base" in m.get("base_name", m["name"])]

        total = sum(self.limits.values())
        print(f"[ModelSelector] Counter-based init: {len(pool)} models, Total concurrency: {total}")

    def get_next(self, task_type=None):
        """
        Get next model config.
        - task_type='community_search': Returns one of the GLM-4.7-Base models (round-robin or random)
        - task_type=None: Returns None to signal use of acquire_any()
        """
        if task_type == 'community_search':
            # Random choice from available base models
            available = []
            for m in self.base_models:
                name = m["name"]
                if self.active_counts.get(name, 0) < self.limits.get(name, 0):
                    available.append(m)

            if available:
                return random.choice(available)

            # If all full, just return a random one and let it block to distribute wait time
            return random.choice(self.base_models) if self.base_models else self.pool[0]
        return None

    def _find_available_model(self):
        """Find any model with available capacity. Must hold lock."""
        # Random heuristic: find all available and pick one
        # This ensures load is distributed across accounts
        available = []
        for model in self.pool:
            name = model["name"]
            if name in self.disabled_models:
                continue
            if self.active_counts.get(name, 0) < self.limits.get(name, 0):
                available.append(model)

        if available:
            return random.choice(available)
        return None

    def acquire_any(self):
        """
        Get any available model slot.
        INSTANT if slots available, blocks only if ALL slots are busy.
        Returns (model_config, acquired).
        """
        with self.condition:
            # Wait until a slot is available
            while True:
                enabled_model_names = [m["name"] for m in self.pool if m["name"] not in self.disabled_models]
                if not enabled_model_names:
                    raise LLMBackendUnavailableError("All configured models are disabled or unavailable")
                model = self._find_available_model()
                if model:
                    name = model["name"]
                    self.active_counts[name] = self.active_counts.get(name, 0) + 1
                    with self.stats_lock:
                        self.stats[name]["active"] = self.active_counts[name]
                    return model, True
                # No slots available, wait for a release
                self.condition.wait()

    def acquire(self, model_name):
        """Acquire a connection slot for a SPECIFIC model. Blocks if at limit."""
        with self.condition:
            if model_name in self.disabled_models:
                raise LLMBackendUnavailableError(
                    f"Model '{model_name}' is disabled: {self.disabled_models.get(model_name) or 'unavailable'}"
                )
            while self.active_counts.get(model_name, 0) >= self.limits.get(model_name, 5):
                self.condition.wait()

            self.active_counts[model_name] = self.active_counts.get(model_name, 0) + 1
            with self.stats_lock:
                self.stats[model_name]["active"] = self.active_counts[model_name]
            return True

    def disable_model(self, model_name, reason):
        """Disable a model for the current process when auth/config is invalid."""
        with self.condition:
            if model_name in self.disabled_models:
                return
            self.disabled_models[model_name] = str(reason or "unavailable")
            print(f"[MODEL-DISABLE] Disabled '{model_name}': {self.disabled_models[model_name]}")
            self.condition.notify_all()

    def release(self, model_name, model_config=None, from_queue=False):
        """
        Release a connection slot for the model.
        Notifies waiting threads that a slot is available.
        """
        with self.condition:
            if model_name in self.active_counts:
                self.active_counts[model_name] = max(0, self.active_counts[model_name] - 1)
                with self.stats_lock:
                    self.stats[model_name]["active"] = self.active_counts[model_name]
            # Notify all waiters that a slot may be available
            self.condition.notify_all()

    def record_success(self, model_name):
        """Record a successful API call."""
        with self.stats_lock:
            if model_name in self.stats:
                self.stats[model_name]["success"] += 1

    def record_error(self, model_name, is_concurrency_error=False):
        """Record an error. is_concurrency_error=True for rate limit/concurrency errors."""
        with self.stats_lock:
            if model_name in self.stats:
                self.stats[model_name]["error"] += 1
                if is_concurrency_error:
                    self.stats[model_name]["concurrency_error"] += 1

    def get_stats(self):
        """Get current statistics for all models."""
        with self.stats_lock:
            result = {}
            for model in self.pool:
                name = model["name"]
                s = self.stats[name]
                total = s["success"] + s["error"]
                error_rate = (s["error"] / total * 100) if total > 0 else 0
                result[name] = {
                    "max_concurrent": self.limits.get(name, 5),
                    "active": s["active"],
                    "success": s["success"],
                    "error": s["error"],
                    "concurrency_error": s["concurrency_error"],
                    "error_rate": f"{error_rate:.1f}%"
                }
            return result

    def save_config(self):
        """Save current config to file for persistence."""
        config = {}
        for model in self.pool:
            name = model["name"]
            config[name] = {"max_concurrent": self.limits.get(name, 5)}
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            print(f"[CONFIG] Saved to {CONFIG_FILE}")
        except Exception as e:
            print(f"[CONFIG] Save error: {e}")

    def update_limit(self, model_name, new_limit):
        """
        Update concurrency limit for a model AT RUNTIME.
        Takes effect immediately without restart!
        """
        with self.condition:
            if model_name in self.limits:
                old_limit = self.limits[model_name]
                self.limits[model_name] = new_limit
                # Also update MODEL_POOL for consistency
                for model in self.pool:
                    if model["name"] == model_name:
                        model["max_concurrent"] = new_limit
                        break
                print(f"[CONFIG] Runtime update: {model_name} {old_limit} -> {new_limit}")
                # If limit increased, wake up waiters
                if new_limit > old_limit:
                    self.condition.notify_all()
                self.save_config()
                return True
        return False

    def get_total_capacity(self):
        """Get total concurrency capacity across all models."""
        return sum(self.limits.values())


model_selector = ModelSelector(MODEL_POOL)


def get_model_for_task(task_type=None):
    """
    Get appropriate model config for a specific task type.
    - 'community_search': Returns GLM-4.7-Base only
    - None: Returns next model in round-robin
    """
    return model_selector.get_next(task_type)


__all__ = ['AUTH_INVALID_ERROR_CODES', 'LLMBackendUnavailableError', 'ModelSelector', 'model_selector', 'get_model_for_task']
