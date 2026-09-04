"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.seed_collector_context import *


def main(argv: Sequence[str] | None = None) -> int:
    config, loop = config_from_env_and_args(argv)
    repository = create_repository_from_env()
    if not repository.enabled:
        raise RuntimeError("FAPAI_DB_URL must be set for seed-collector mode")
    from tools import browserless_seed_probe

    if loop:
        summary = run_seed_collector_loop(
            config,
            repository=repository,
            browserless_seed_probe=browserless_seed_probe,
            runtime_context_factory=lambda: _build_runtime_context(config),
        )
    else:
        http_session = _build_runtime_context(config)
        summary = run_seed_collector_once(
            config,
            repository=repository,
            http_session=http_session,
            browserless_seed_probe=browserless_seed_probe,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


__all__ = (
    'main',
)
