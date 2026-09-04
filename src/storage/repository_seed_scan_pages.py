from __future__ import annotations

from .repository_context import *  # noqa: F401,F403


class RepositorySeedScanPagesMixin:
    def claim_seed_scan_page(
        self,
        worker_id: str,
        lease_seconds: int = 90,
        *,
        parallel_sorts: bool = False,
        failure_cooldown_threshold: int | None = None,
        failure_cooldown_seconds: int | None = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        self.initialize()
        now = _utc_now()
        lease_until = now + timedelta(seconds=max(lease_seconds, 1))
        cooldown_threshold = max(int(failure_cooldown_threshold or 0), 0)
        cooldown_seconds = max(int(failure_cooldown_seconds or 0), 0)
        failure_cooldown_cutoff = now - timedelta(seconds=cooldown_seconds) if cooldown_seconds > 0 else None

        def failure_in_cooldown(row: FapaiSeedScanProgress) -> bool:
            if cooldown_threshold <= 0 or failure_cooldown_cutoff is None:
                return False
            if not str(row.last_error or "").strip():
                return False
            if int(row.retry_count or 0) < cooldown_threshold:
                return False
            return _cooldown_active(row.updated_at, now=now, cutoff=failure_cooldown_cutoff)

        with self.session_factory.begin() as session:
            if parallel_sorts:
                category_rank_expr = case(
                    (FapaiSeedScanJob.category == "50025969", 0),
                    (FapaiSeedScanJob.category == "200782003", 1),
                    else_=10_000,
                )
                ordered = session.scalars(
                    select(FapaiSeedScanProgress)
                    .join(FapaiSeedScanJob, FapaiSeedScanProgress.job_key == FapaiSeedScanJob.job_key)
                    .where(FapaiSeedScanProgress.status.in_(("pending", "in_progress")))
                    .order_by(
                        FapaiSeedScanJob.province,
                        FapaiSeedScanJob.city,
                        FapaiSeedScanJob.district,
                        FapaiSeedScanJob.location_code,
                        category_rank_expr,
                        FapaiSeedScanJob.category,
                        FapaiSeedScanProgress.retry_count,
                        FapaiSeedScanProgress.next_page,
                        FapaiSeedScanProgress.job_key,
                        FapaiSeedScanProgress.sort_order,
                        FapaiSeedScanProgress.progress_key,
                    )
                    .limit(512)
                ).all()
                progress_by_job: Dict[str, list[FapaiSeedScanProgress]] = {}
            else:
                rows = session.scalars(select(FapaiSeedScanProgress)).all()
                jobs_by_key = {
                    job.job_key: job
                    for job in session.scalars(select(FapaiSeedScanJob)).all()
                }
                progress_by_job = {}
                for row in rows:
                    progress_by_job.setdefault(row.job_key, []).append(row)

                ordered = sorted(
                    rows,
                    key=lambda row: (
                        self._seed_scan_scope_order_key(jobs_by_key.get(row.job_key)),
                        int(row.sort_order or 0),
                        int(row.next_page or 1),
                        row.progress_key,
                    ),
                )
            blocked_job_keys: set[str] = set()
            for row in ordered:
                if not parallel_sorts and row.job_key in blocked_job_keys:
                    continue
                if row.status not in {"pending", "in_progress"}:
                    continue
                if row.status == "in_progress" and row.leased_by != worker_id:
                    if not _lease_reclaimable(row.lease_until, row.updated_at, now=now, lease_seconds=lease_seconds):
                        if parallel_sorts:
                            continue
                        blocked_job_keys.add(row.job_key)
                        continue
                if failure_in_cooldown(row):
                    if parallel_sorts:
                        continue
                    blocked_job_keys.add(row.job_key)
                    continue
                if row.max_page is not None and int(row.next_page or 1) > int(row.max_page):
                    row.status = "exhausted"
                    row.leased_by = None
                    row.lease_until = None
                    row.completed_at = row.completed_at or now
                    session.add(row)
                    self._refresh_seed_scan_job_status(session, row.job_key, now)
                    continue

                if not parallel_sorts:
                    siblings = sorted(progress_by_job.get(row.job_key, []), key=lambda sibling: (int(sibling.sort_order or 0), sibling.progress_key))
                    if any(
                        int(sibling.sort_order or 0) < int(row.sort_order or 0)
                        and sibling.status in {"pending", "in_progress"}
                        and not failure_in_cooldown(sibling)
                        and not (
                            sibling.status == "in_progress"
                            and sibling.leased_by != worker_id
                            and _lease_reclaimable(
                                sibling.lease_until,
                                sibling.updated_at,
                                now=now,
                                lease_seconds=lease_seconds,
                            )
                        )
                        for sibling in siblings
                    ):
                        blocked_job_keys.add(row.job_key)
                        continue

                job = session.get(FapaiSeedScanJob, row.job_key)
                if job is None:
                    continue
                row.status = "in_progress"
                row.leased_by = worker_id
                row.lease_until = lease_until
                session.add(row)
                self._refresh_seed_scan_job_status(session, row.job_key, now)
                return self._seed_scan_progress_payload(row, job)
        return None

    def complete_seed_scan_page(
        self,
        *,
        progress_key: str,
        page: int,
        item_count: int,
        has_next: bool,
        source_url: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        now = _utc_now()
        with self.session_factory.begin() as session:
            row = session.get(FapaiSeedScanProgress, progress_key)
            if row is None:
                return
            row.last_success_page = max(int(page or 1), int(row.last_success_page or 0))
            row.last_item_count = int(item_count or 0)
            row.last_fetch_url = source_url
            row.last_error = None
            row.retry_count = 0
            row.leased_by = None
            row.lease_until = None
            max_page = int(row.max_page) if row.max_page else None
            next_page = int(page or 1) + 1
            if bool(has_next) and (max_page is None or next_page <= max_page):
                row.status = "pending"
                row.next_page = max(int(row.next_page or 1), next_page)
                row.completed_at = None
            else:
                row.status = "exhausted"
                row.next_page = max(int(row.next_page or 1), int(page or 1))
                row.completed_at = now
            session.add(row)
            self._refresh_seed_scan_job_status(session, row.job_key, now)

    def fail_seed_scan_page(self, progress_key: str, error: str, *, retryable: bool = True) -> None:
        if not self.enabled:
            return
        self.initialize()
        now = _utc_now()
        with self.session_factory.begin() as session:
            row = session.get(FapaiSeedScanProgress, progress_key)
            if row is None:
                return
            previous_error = str(row.last_error or "").strip()
            row.last_error = str(error)
            if previous_error:
                row.retry_count = int(row.retry_count or 0) + 1
            else:
                row.retry_count = 1
            row.leased_by = None
            row.lease_until = None
            row.status = "pending" if retryable else "blocked"
            row.updated_at = now
            session.add(row)
            self._refresh_seed_scan_job_status(session, row.job_key, now)
