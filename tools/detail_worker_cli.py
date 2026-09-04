"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.detail_worker_context import *


def main(argv: Sequence[str] | None = None) -> int:
    config, loop = config_from_env_and_args(argv)
    # Allow running without LLM for raw data collection
    # if not os.environ.get("OPENAI_BASE_URL") or not os.environ.get("OPENAI_API_KEY"):
    #     raise RuntimeError("OPENAI_BASE_URL/OPENAI_API_KEY must be set for detail-worker mode")
    repository = create_repository_from_env()
    if not repository.enabled:
        raise RuntimeError("FAPAI_DB_URL must be set for detail-worker mode")

    if loop:
        summary = run_detail_worker_loop(
            config,
            repository=repository,
            runtime_context_factory=lambda: (None, {}) if config.analysis_only else _build_runtime_context(config),
        )
    else:
        http_session, browser_pages = (None, {}) if config.analysis_only else _build_runtime_context(config)
        summary = run_detail_worker_batch(
            config,
            repository=repository,
            http_session=http_session,
            browser_pages=browser_pages,
        )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


__all__ = (
    'main',
)
