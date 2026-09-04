from __future__ import annotations

from .repository_context import *  # noqa: F401,F403


class RepositoryDetailClaimMixin:
    def claim_seed_detail_item(
        self,
        worker_id: str,
        lease_seconds: int = 300,
        *,
        exclude_item_ids: Iterable[str] | None = None,
        max_item_attempts: int | None = None,
        failure_cooldown_seconds: int | None = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        self.initialize()
        now = _utc_now()
        lease_until = now + timedelta(seconds=max(lease_seconds, 1))
        excluded = {str(item_id) for item_id in (exclude_item_ids or ())}
        attempt_limit = max(int(max_item_attempts), 1) if max_item_attempts is not None else None
        cooldown_seconds = max(int(failure_cooldown_seconds or 0), 0)
        failure_cooldown_cutoff = now - timedelta(seconds=cooldown_seconds) if cooldown_seconds > 0 else None
        claimed_item_id: str | None = None
        claimed_payload: Dict[str, Any] | None = None
        with self.session_factory.begin() as session:
            stale_failed_retry_cutoff = now - timedelta(seconds=SEED_ITEM_STALE_FAILED_PRIORITY_SECONDS)
            stale_retry_timestamp = func.coalesce(FapaiSeedItem.updated_at, FapaiSeedItem.first_seen_at)
            sort_first_seen_at = func.coalesce(FapaiSeedItem.first_seen_at, datetime.min)
            detail_claim_priority = case(
                (
                    and_(
                        FapaiSeedItem.status == "in_progress",
                        or_(
                            FapaiSeedItem.detail_lease_until.is_(None),
                            FapaiSeedItem.detail_lease_until < now,
                        ),
                    ),
                    0,
                ),
                (
                    and_(
                        FapaiSeedItem.status == "detail_failed",
                        stale_retry_timestamp < stale_failed_retry_cutoff,
                    ),
                    1,
                ),
                (FapaiSeedItem.status == "pending_detail", 2),
                (FapaiSeedItem.status == "detail_failed", 3),
                (FapaiSeedItem.status == "in_progress", 4),
                else_=99,
            )

            def _detail_row_priority(row: FapaiSeedItem) -> int:
                if (
                    row.status == "in_progress"
                    and row.detail_leased_by != worker_id
                    and _lease_reclaimable(row.detail_lease_until, row.updated_at, now=now, lease_seconds=lease_seconds)
                ):
                    return 0
                if row.status == "detail_failed" and (
                    (_coerce_naive_utc(row.updated_at) or row.first_seen_at or datetime.min) < stale_failed_retry_cutoff
                ):
                    return 1
                if row.status == "pending_detail":
                    return 2
                if row.status == "detail_failed":
                    return 3
                return 4

            last_cursor: tuple[int, datetime, str] | None = None
            while claimed_payload is None:
                candidate_query = (
                    select(
                        FapaiSeedItem.item_id,
                        detail_claim_priority.label("claim_priority"),
                        sort_first_seen_at.label("sort_first_seen_at"),
                    )
                    .where(FapaiSeedItem.status.in_(("pending_detail", "detail_failed", "in_progress")))
                    .order_by(detail_claim_priority, sort_first_seen_at.asc(), FapaiSeedItem.item_id.asc())
                    .limit(SEED_ITEM_CLAIM_BATCH_LIMIT)
                )
                if excluded:
                    candidate_query = candidate_query.where(not_(FapaiSeedItem.item_id.in_(excluded)))
                cursor_clause = _seed_claim_cursor_clause(detail_claim_priority, sort_first_seen_at, last_cursor)
                if cursor_clause is not None:
                    candidate_query = candidate_query.where(cursor_clause)
                candidates = session.execute(candidate_query).all()
                if not candidates:
                    break
                locked_rows: list[FapaiSeedItem] = []
                for candidate in candidates:
                    candidate_item_id = str(candidate.item_id)
                    row = session.scalars(
                        select(FapaiSeedItem)
                        .where(FapaiSeedItem.item_id == candidate_item_id)
                        .with_for_update(skip_locked=True)
                    ).first()
                    if row is None:
                        continue
                    locked_rows.append(row)
                remaining_rows: list[FapaiSeedItem] = []
                for row in locked_rows:
                    attempt_count = int(row.detail_attempt_count or 0)
                    if attempt_limit is not None and attempt_count >= attempt_limit:
                        row.status = "detail_blocked"
                        row.detail_leased_by = None
                        row.detail_lease_until = None
                        previous_error = (row.detail_last_error or "").strip()
                        limit_error = f"retry limit reached: attempts={attempt_count}, max={attempt_limit}"
                        row.detail_last_error = (
                            f"{limit_error}; previous_error={previous_error}" if previous_error else limit_error
                        )
                        session.add(row)
                        continue
                    remaining_rows.append(row)
                remaining_rows.sort(
                    key=lambda row: (
                        _detail_row_priority(row),
                        row.first_seen_at or datetime.min,
                        row.item_id,
                    )
                )
                for row in remaining_rows:
                    if row.status == "in_progress" and row.detail_leased_by != worker_id:
                        if not _lease_reclaimable(
                            row.detail_lease_until,
                            row.updated_at,
                            now=now,
                            lease_seconds=lease_seconds,
                        ):
                            continue
                    if (
                        failure_cooldown_cutoff is not None
                        and row.status == "detail_failed"
                        and _cooldown_active(row.updated_at, now=now, cutoff=failure_cooldown_cutoff)
                    ):
                        continue
                    attempt_count = int(row.detail_attempt_count or 0)
                    row.status = "in_progress"
                    row.detail_leased_by = worker_id
                    row.detail_lease_until = lease_until
                    row.detail_attempt_count = attempt_count + 1
                    session.add(row)
                    claimed_item_id = row.item_id
                    claimed_payload = dict(row.source_payload or {})
                    source_item_id = str(
                        row.source_item_id
                        or claimed_payload.get("source_item_id")
                        or claimed_payload.get("id")
                        or row.item_id
                    )
                    claimed_payload.setdefault("id", source_item_id)
                    claimed_payload["item_id"] = row.item_id
                    claimed_payload["source_item_id"] = source_item_id
                    if row.source_platform:
                        claimed_payload["source_platform"] = row.source_platform
                    canonical_url = self._seed_item_url(
                        source_item_id,
                        row.source_url or claimed_payload.get("url") or claimed_payload.get("source_url"),
                    )
                    claimed_payload["url"] = canonical_url
                    claimed_payload["source_url"] = canonical_url
                    if row.title:
                        claimed_payload.setdefault("title", row.title)
                        claimed_payload.setdefault("source_title", row.title)
                    break
                if claimed_payload is not None:
                    break
                last_candidate = candidates[-1]
                last_cursor = (
                    int(last_candidate.claim_priority),
                    _coerce_naive_utc(last_candidate.sort_first_seen_at) or datetime.min,
                    str(last_candidate.item_id),
                )
                if len(candidates) < SEED_ITEM_CLAIM_BATCH_LIMIT:
                    break
        if claimed_payload is None or claimed_item_id is None:
            return None
        with self.session_factory() as session:
            occurrence = session.scalars(
                select(FapaiSeedOccurrence)
                .where(FapaiSeedOccurrence.item_id == claimed_item_id)
                .order_by(FapaiSeedOccurrence.seen_at.asc(), FapaiSeedOccurrence.id.asc())
            ).first()
            if occurrence is not None:
                claimed_payload.setdefault("source_page_url", occurrence.source_page_url)
                claimed_payload.setdefault("list_location_code", None)
                claimed_payload.setdefault("list_category", None)
                claimed_payload.setdefault("list_st_param", occurrence.st_param)
                claimed_payload.setdefault("list_page", occurrence.page)
                claimed_payload.setdefault("list_sort_key", occurrence.sort_key)
                claimed_payload.setdefault("list_sort_name", occurrence.sort_name)
        return claimed_payload

    def release_seed_detail_worker_leases(self, worker_id: str) -> Dict[str, int]:
        if not self.enabled:
            return {"released": 0}
        normalized_worker_id = str(worker_id or "").strip()
        if not normalized_worker_id:
            return {"released": 0}
        self.initialize()
        now = _utc_now()
        released = 0
        with self.session_factory.begin() as session:
            rows = session.scalars(
                select(FapaiSeedItem).where(
                    FapaiSeedItem.detail_leased_by == normalized_worker_id,
                    FapaiSeedItem.status.in_(("in_progress", "analysis_in_progress")),
                )
            ).all()
            for row in rows:
                if row.status == "analysis_in_progress":
                    row.status = "raw_detail_captured"
                    payload = dict(row.source_payload or {})
                    payload["_analysis_attempt_count"] = max(int(payload.get("_analysis_attempt_count") or 0) - 1, 0)
                    row.source_payload = payload
                else:
                    row.status = "pending_detail"
                    row.detail_attempt_count = max(int(row.detail_attempt_count or 0) - 1, 0)
                row.detail_leased_by = None
                row.detail_lease_until = None
                row.updated_at = now
                session.add(row)
                released += 1
        return {"released": released}

    def mark_seed_detail_completed(
        self,
        item_id: str,
        *,
        final_json_path: str | None = None,
        selected_json_path: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        now = _utc_now()
        with self.session_factory.begin() as session:
            row = session.get(FapaiSeedItem, str(item_id))
            if row is None:
                return
            row.status = "detail_completed"
            row.detail_completed_at = now
            row.detail_leased_by = None
            row.detail_lease_until = None
            row.detail_last_error = None
            row.final_json_path = final_json_path
            row.selected_json_path = selected_json_path
            session.add(row)

    def mark_seed_raw_detail_captured(
        self,
        item_id: str,
        *,
        detail_html_path: str | None = None,
        description_json_path: str | None = None,
        selected_json_path: str | None = None,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        now = _utc_now()
        with self.session_factory.begin() as session:
            row = session.get(FapaiSeedItem, str(item_id))
            if row is None:
                return
            row.status = "raw_detail_captured"
            row.detail_completed_at = now
            row.detail_leased_by = None
            row.detail_lease_until = None
            row.detail_last_error = None
            row.final_json_path = None
            row.selected_json_path = selected_json_path
            payload = dict(row.source_payload or {})
            payload["_raw_detail_artifacts"] = {
                "detail_html_path": detail_html_path,
                "description_json_path": description_json_path,
                "selected_json_path": selected_json_path,
            }
            row.source_payload = payload
            session.add(row)

    def claim_seed_raw_detail_item(
        self,
        worker_id: str,
        lease_seconds: int = 300,
        *,
        exclude_item_ids: Iterable[str] | None = None,
        max_analysis_attempts: int | None = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        self.initialize()
        now = _utc_now()
        lease_until = now + timedelta(seconds=max(lease_seconds, 1))
        excluded = {str(item_id) for item_id in (exclude_item_ids or ())}
        attempt_limit = max(int(max_analysis_attempts), 1) if max_analysis_attempts is not None else None
        claimed_payload: Dict[str, Any] | None = None
        with self.session_factory.begin() as session:
            stale_failed_retry_cutoff = now - timedelta(seconds=SEED_ITEM_STALE_FAILED_PRIORITY_SECONDS)
            stale_retry_timestamp = func.coalesce(FapaiSeedItem.updated_at, FapaiSeedItem.first_seen_at)
            sort_first_seen_at = func.coalesce(FapaiSeedItem.first_seen_at, datetime.min)
            raw_claim_priority = case(
                (
                    and_(
                        FapaiSeedItem.status == "analysis_failed",
                        stale_retry_timestamp < stale_failed_retry_cutoff,
                    ),
                    0,
                ),
                (FapaiSeedItem.status == "raw_detail_captured", 1),
                (FapaiSeedItem.status == "analysis_failed", 2),
                (FapaiSeedItem.status == "analysis_in_progress", 3),
                else_=99,
            )

            def _analysis_row_priority(row: FapaiSeedItem) -> int:
                if row.status == "analysis_failed" and (
                    (_coerce_naive_utc(row.updated_at) or row.first_seen_at or datetime.min) < stale_failed_retry_cutoff
                ):
                    return 0
                if row.status == "raw_detail_captured":
                    return 1
                if row.status == "analysis_failed":
                    return 2
                if (
                    row.status == "analysis_in_progress"
                    and row.detail_leased_by != worker_id
                    and _lease_reclaimable(row.detail_lease_until, row.updated_at, now=now, lease_seconds=lease_seconds)
                ):
                    return 3
                return 4

            last_cursor: tuple[int, datetime, str] | None = None
            while claimed_payload is None:
                candidate_query = (
                    select(
                        FapaiSeedItem.item_id,
                        raw_claim_priority.label("claim_priority"),
                        sort_first_seen_at.label("sort_first_seen_at"),
                    )
                    .where(FapaiSeedItem.status.in_(("raw_detail_captured", "analysis_failed", "analysis_in_progress")))
                    .order_by(raw_claim_priority, sort_first_seen_at.asc(), FapaiSeedItem.item_id.asc())
                    .limit(SEED_ITEM_CLAIM_BATCH_LIMIT)
                )
                if excluded:
                    candidate_query = candidate_query.where(not_(FapaiSeedItem.item_id.in_(excluded)))
                cursor_clause = _seed_claim_cursor_clause(raw_claim_priority, sort_first_seen_at, last_cursor)
                if cursor_clause is not None:
                    candidate_query = candidate_query.where(cursor_clause)
                candidates = session.execute(candidate_query).all()
                if not candidates:
                    break
                locked_rows: list[FapaiSeedItem] = []
                for candidate in candidates:
                    candidate_item_id = str(candidate.item_id)
                    row = session.scalars(
                        select(FapaiSeedItem)
                        .where(FapaiSeedItem.item_id == candidate_item_id)
                        .with_for_update(skip_locked=True)
                    ).first()
                    if row is None:
                        continue
                    locked_rows.append(row)
                remaining_rows: list[tuple[FapaiSeedItem, Dict[str, Any], Dict[str, Any], str, str, str]] = []
                for row in locked_rows:
                    payload = dict(row.source_payload or {})
                    artifacts = dict(payload.get("_raw_detail_artifacts") or {})
                    detail_html_path = str(
                        _resolve_collection_artifact_path(artifacts.get("detail_html_path")) or ""
                    ).strip()
                    selected_json_path = str(
                        _resolve_collection_artifact_path(artifacts.get("selected_json_path") or row.selected_json_path) or ""
                    ).strip()
                    description_json_path = str(
                        _resolve_collection_artifact_path(artifacts.get("description_json_path")) or ""
                    ).strip()
                    if not detail_html_path or not os.path.isfile(detail_html_path):
                        row.status = "analysis_blocked"
                        row.detail_leased_by = None
                        row.detail_lease_until = None
                        row.detail_last_error = (
                            f"analysis raw detail artifact missing: detail_html_path={detail_html_path or '<missing>'}"
                        )
                        session.add(row)
                        continue
                    attempt_count = int(payload.get("_analysis_attempt_count") or 0)
                    if attempt_limit is not None and attempt_count >= attempt_limit:
                        row.status = "analysis_blocked"
                        row.detail_leased_by = None
                        row.detail_lease_until = None
                        previous_error = (row.detail_last_error or "").strip()
                        limit_error = f"analysis retry limit reached: attempts={attempt_count}, max={attempt_limit}"
                        row.detail_last_error = (
                            f"{limit_error}; previous_error={previous_error}" if previous_error else limit_error
                        )
                        session.add(row)
                        continue
                    remaining_rows.append(
                        (
                            row,
                            payload,
                            artifacts,
                            detail_html_path,
                            selected_json_path,
                            description_json_path,
                        )
                    )
                remaining_rows.sort(
                    key=lambda row: (
                        _analysis_row_priority(row[0]),
                        row[0].first_seen_at or datetime.min,
                        row[0].item_id,
                    )
                )
                for row, payload, artifacts, detail_html_path, selected_json_path, description_json_path in remaining_rows:
                    if row.status == "analysis_in_progress" and row.detail_leased_by != worker_id:
                        if not _lease_reclaimable(
                            row.detail_lease_until,
                            row.updated_at,
                            now=now,
                            lease_seconds=lease_seconds,
                        ):
                            continue
                    attempt_count = int(payload.get("_analysis_attempt_count") or 0)

                    row.status = "analysis_in_progress"
                    row.detail_leased_by = worker_id
                    row.detail_lease_until = lease_until
                    payload["_analysis_attempt_count"] = attempt_count + 1
                    source_item_id = str(
                        row.source_item_id
                        or payload.get("source_item_id")
                        or payload.get("id")
                        or row.item_id
                    )
                    payload.setdefault("id", source_item_id)
                    payload["item_id"] = row.item_id
                    payload["source_item_id"] = source_item_id
                    if row.source_platform:
                        payload["source_platform"] = row.source_platform
                    payload.setdefault("url", self._seed_item_url(source_item_id, row.source_url))
                    payload.setdefault("source_url", payload.get("url"))
                    if row.title:
                        payload.setdefault("title", row.title)
                        payload.setdefault("source_title", row.title)
                    artifacts["detail_html_path"] = detail_html_path
                    if selected_json_path:
                        artifacts["selected_json_path"] = selected_json_path
                    if description_json_path:
                        artifacts["description_json_path"] = description_json_path
                    payload["_raw_detail_artifacts"] = artifacts
                    row.source_payload = payload
                    session.add(row)
                    claimed_payload = dict(payload)
                    break
                if claimed_payload is not None:
                    break
                last_candidate = candidates[-1]
                last_cursor = (
                    int(last_candidate.claim_priority),
                    _coerce_naive_utc(last_candidate.sort_first_seen_at) or datetime.min,
                    str(last_candidate.item_id),
                )
                if len(candidates) < SEED_ITEM_CLAIM_BATCH_LIMIT:
                    break
        return claimed_payload
