from __future__ import annotations
from tools.hybrid_seed_context import *  # noqa: F401,F403
from tools.hybrid_seed_normalization import *  # noqa: F401,F403


def build_next_task_request_url(api_base: str, session_id: str) -> str:
    return f"{api_base.rstrip('/')}/collection/seeds/next_task?session_id={session_id}"

def claim_next_seed_task(
    *,
    api_base: str,
    session_id: str,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    http = http_session or requests.Session()
    response = http.get(build_next_task_request_url(api_base, session_id), timeout=timeout)
    return response.json()

@contextmanager
def hybrid_collection_status_snapshot_scope():
    previous = getattr(_HYBRID_COLLECTION_STATUS_SNAPSHOT_CACHE, "value", None)
    _HYBRID_COLLECTION_STATUS_SNAPSHOT_CACHE.value = {}
    try:
        yield
    finally:
        if previous is None:
            try:
                delattr(_HYBRID_COLLECTION_STATUS_SNAPSHOT_CACHE, "value")
            except AttributeError:
                pass
        else:
            _HYBRID_COLLECTION_STATUS_SNAPSHOT_CACHE.value = previous

def load_hybrid_collection_status_snapshot(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    cache = getattr(_HYBRID_COLLECTION_STATUS_SNAPSHOT_CACHE, "value", None)
    cache_key = (api_base.rstrip("/"), timeout)
    if isinstance(cache, dict) and cache_key in cache:
        return _coerce_optional_mapping(cache[cache_key])
    http = http_session or requests.Session()
    response = http.get(f"{api_base.rstrip('/')}/status", timeout=timeout)
    payload = response.json()
    collection_stage = payload.get("collection_stage") if isinstance(payload, dict) else None
    snapshot = _coerce_optional_mapping(collection_stage)
    if isinstance(cache, dict):
        cache[cache_key] = dict(snapshot)
    return snapshot

def _load_hybrid_collection_stage_summary(
    api_base: str,
    summary_key: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    snapshot = load_hybrid_collection_status_snapshot(
        api_base,
        http_session=http_session,
        timeout=timeout,
    )
    return _coerce_optional_mapping(snapshot.get(summary_key))

def load_hybrid_collection_operator_status_bundle(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, dict[str, Any]]:
    def _safe_load(loader: Callable[..., dict[str, Any]]) -> dict[str, Any]:
        try:
            return _coerce_optional_mapping(
                loader(
                api_base,
                http_session=http_session,
                timeout=timeout,
                )
            )
        except requests.exceptions.RequestException:
            return {}

    with hybrid_collection_status_snapshot_scope():
        return {
            "guidance": _safe_load(load_hybrid_collection_strategy_guidance),
            "recovery_policy": _safe_load(load_hybrid_collection_recovery_policy),
            "lifecycle_summary": _safe_load(load_hybrid_collection_lifecycle_state_summary),
            "intervention_summary": _safe_load(load_hybrid_collection_operator_intervention_policy_summary),
            "intervention_stability_summary": _safe_load(load_hybrid_collection_operator_intervention_stability_summary),
            "final_guidance_summary": _safe_load(load_hybrid_collection_operator_final_guidance_summary),
            "digest_summary": _safe_load(load_hybrid_collection_operator_digest_summary),
            "digest_stability_summary": _safe_load(load_hybrid_collection_operator_digest_stability_summary),
            "escalation_event_trend_summary": _safe_load(load_hybrid_collection_operator_escalation_event_trend_summary),
            "escalation_event_stability_summary": _safe_load(load_hybrid_collection_operator_escalation_event_stability_summary),
        }

def load_hybrid_collection_strategy_guidance(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_strategy_guidance",
        http_session=http_session,
        timeout=timeout,
    )

def load_hybrid_collection_recovery_policy(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_recovery_policy",
        http_session=http_session,
        timeout=timeout,
    )

def load_hybrid_collection_lifecycle_state_summary(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_lifecycle_state_summary",
        http_session=http_session,
        timeout=timeout,
    )

def load_hybrid_collection_operator_intervention_policy_summary(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_operator_intervention_policy_summary",
        http_session=http_session,
        timeout=timeout,
    )

def load_hybrid_collection_operator_intervention_stability_summary(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_operator_intervention_stability_summary",
        http_session=http_session,
        timeout=timeout,
    )

def load_hybrid_collection_operator_final_guidance_summary(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_operator_final_guidance_summary",
        http_session=http_session,
        timeout=timeout,
    )

def load_hybrid_collection_operator_digest_summary(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_operator_digest_summary",
        http_session=http_session,
        timeout=timeout,
    )

def load_hybrid_collection_operator_digest_stability_summary(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_operator_digest_stability_summary",
        http_session=http_session,
        timeout=timeout,
    )

def load_hybrid_collection_operator_escalation_event_trend_summary(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_operator_escalation_event_trend_summary",
        http_session=http_session,
        timeout=timeout,
    )

def load_hybrid_collection_operator_escalation_event_stability_summary(
    api_base: str,
    *,
    http_session: requests.Session | Any | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    return _load_hybrid_collection_stage_summary(
        api_base,
        "hybrid_collection_operator_escalation_event_stability_summary",
        http_session=http_session,
        timeout=timeout,
    )

_DEFAULT_RUN_LOOP_STATUS_LOADERS = {
    "load_guidance_fn": load_hybrid_collection_strategy_guidance,
    "load_recovery_policy_fn": load_hybrid_collection_recovery_policy,
    "load_lifecycle_summary_fn": load_hybrid_collection_lifecycle_state_summary,
    "load_intervention_summary_fn": load_hybrid_collection_operator_intervention_policy_summary,
    "load_stability_summary_fn": load_hybrid_collection_operator_intervention_stability_summary,
    "load_final_guidance_summary_fn": load_hybrid_collection_operator_final_guidance_summary,
    "load_digest_summary_fn": load_hybrid_collection_operator_digest_summary,
    "load_digest_stability_summary_fn": load_hybrid_collection_operator_digest_stability_summary,
    "load_escalation_event_trend_summary_fn": load_hybrid_collection_operator_escalation_event_trend_summary,
    "load_escalation_event_stability_summary_fn": load_hybrid_collection_operator_escalation_event_stability_summary,
}

__all__ = ('build_next_task_request_url', 'claim_next_seed_task', 'hybrid_collection_status_snapshot_scope', 'load_hybrid_collection_status_snapshot', '_load_hybrid_collection_stage_summary', 'load_hybrid_collection_operator_status_bundle', 'load_hybrid_collection_strategy_guidance', 'load_hybrid_collection_recovery_policy', 'load_hybrid_collection_lifecycle_state_summary', 'load_hybrid_collection_operator_intervention_policy_summary', 'load_hybrid_collection_operator_intervention_stability_summary', 'load_hybrid_collection_operator_final_guidance_summary', 'load_hybrid_collection_operator_digest_summary', 'load_hybrid_collection_operator_digest_stability_summary', 'load_hybrid_collection_operator_escalation_event_trend_summary', 'load_hybrid_collection_operator_escalation_event_stability_summary', '_DEFAULT_RUN_LOOP_STATUS_LOADERS')
