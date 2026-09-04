"""Implementation slice extracted from the compatibility facade."""

from __future__ import annotations

from tools.seed_collector_context import *


def _default_seed_job(config: SeedCollectorConfig) -> SeedScanJobSpec:
    return SeedScanJobSpec(
        job_key=config.job_key,
        province=config.province,
        city=config.city,
        district=config.district,
        location_code=config.location_code,
        category=config.category,
        sort_specs=config.sort_specs,
        max_page=config.max_page,
        source_url_template=config.source_url_template,
    )


def _seed_jobs(config: SeedCollectorConfig) -> tuple[SeedScanJobSpec, ...]:
    return config.seed_jobs or (_default_seed_job(config),)


def _ensure_seed_scan_jobs(config: SeedCollectorConfig, repository: PropertyRepository) -> list[dict[str, Any]]:
    ensured: list[dict[str, Any]] = []
    for job in _seed_jobs(config):
        policy_kwargs = {"policy": config.seed_scan_policy} if config.seed_scan_policy else {}
        ensured.append(
            repository.ensure_seed_scan_job(
                job.as_job_dict(),
                sort_specs=[spec.as_dict() for spec in job.sort_specs],
                max_page=job.max_page,
                **policy_kwargs,
            )
        )
    return ensured


def _should_archive_stale_seed_jobs(config: SeedCollectorConfig) -> bool:
    if not config.seed_jobs:
        return False
    job_keys = {job.job_key for job in config.seed_jobs if _clean_text(job.job_key)}
    if len(job_keys) != len(config.seed_jobs):
        return False
    return True


def _archive_stale_seed_jobs(config: SeedCollectorConfig, repository: PropertyRepository) -> dict[str, int]:
    active_job_keys = [job.job_key for job in _seed_jobs(config)]
    policy_kwargs = {"policy": config.seed_scan_policy} if config.seed_scan_policy else {}
    return repository.archive_seed_scan_jobs_except(active_job_keys, **policy_kwargs)


def _has_seed_scan_work(repository: PropertyRepository) -> tuple[bool, dict[str, int]]:
    counts = repository.seed_queue_counts()
    pending = int(counts.get("seed_scan_progress_pending", 0) or 0)
    in_progress = int(counts.get("seed_scan_progress_in_progress", 0) or 0)
    return pending + in_progress > 0, counts


def _seed_scan_queue_progress_total(counts: dict[str, int]) -> int:
    return sum(
        _summary_int(counts.get(key))
        for key in (
            "seed_scan_progress_pending",
            "seed_scan_progress_in_progress",
            "seed_scan_progress_exhausted",
            "seed_scan_progress_blocked",
        )
    )


def _should_ensure_seed_jobs(config: SeedCollectorConfig, counts: dict[str, int]) -> bool:
    if _seed_scan_queue_progress_total(counts) <= 0:
        return True
    return config.worker_id in {"seed-1", "seed-test"}


__all__ = (
    '_default_seed_job',
    '_seed_jobs',
    '_ensure_seed_scan_jobs',
    '_should_archive_stale_seed_jobs',
    '_archive_stale_seed_jobs',
    '_has_seed_scan_work',
    '_seed_scan_queue_progress_total',
    '_should_ensure_seed_jobs',
)
