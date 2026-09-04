from __future__ import annotations

from .repository_context import *  # noqa: F401,F403


class RepositoryReadinessMixin:
    @staticmethod
    def _done_like_statuses() -> tuple[str, ...]:
        return ("done", "成交", "failure", "failed_timeout")

    @staticmethod
    def _pending_detail_statuses() -> tuple[str, ...]:
        return ("pending", "failed", "replay_requested", "archived")

    @staticmethod
    def _analysis_status_ready_values() -> tuple[str, ...]:
        return ("done", "成交")

    def _detail_pending_filter(self):
        return and_(
            PropertyListing.is_deleted.is_(False),
            PropertyListing.source_url.is_not(None),
            PropertyListing.source_url != "",
            PropertyListing.status.in_(self._done_like_statuses()),
            or_(PropertyAudit.is_processed.is_(False), PropertyAudit.is_processed.is_(None)),
            or_(
                PropertyAudit.detail_status.in_(self._pending_detail_statuses()),
                PropertyAudit.detail_status.is_(None),
            ),
        )

    def _analysis_contract_has_price_anchor(self):
        return or_(
            PropertyListing.transaction_price.is_not(None),
            PropertyListing.starting_price.is_not(None),
            PropertyListing.actual_paid_price.is_not(None),
            PropertyListing.evaluation_price.is_not(None),
        )

    def _analysis_contract_has_location_precision(self):
        return or_(
            and_(PropertyListing.latitude.is_not(None), PropertyListing.longitude.is_not(None)),
            PropertyListing.community_name.is_not(None),
            PropertyListing.business_area.is_not(None),
        )

    def _analysis_contract_fallback_ready(self):
        return and_(
            PropertyListing.is_deleted.is_(False),
            PropertyListing.status.in_(self._done_like_statuses()),
            PropertyAudit.detail_captured.is_(True),
            PropertyListing.area_sqm.is_not(None),
            PropertyListing.city.is_not(None),
            PropertyListing.district.is_not(None),
            self._analysis_contract_has_price_anchor(),
            self._analysis_contract_has_location_precision(),
        )

    def _analysis_ready_filter(self):
        return or_(
            PropertyAudit.analysis_ready.is_(True),
            and_(PropertyAudit.analysis_status == "ready", PropertyAudit.analysis_ready.is_not(False)),
            and_(PropertyAudit.analysis_ready.is_(None), self._analysis_contract_fallback_ready()),
        )

    def _analysis_not_ready_filter(self):
        return and_(
            PropertyListing.is_deleted.is_(False),
            or_(
                PropertyAudit.analysis_ready.is_(False),
                PropertyAudit.analysis_status == "not_ready",
                and_(
                    PropertyAudit.analysis_ready.is_(None),
                    PropertyAudit.analysis_status.is_(None),
                    not_(self._analysis_contract_fallback_ready()),
                ),
            ),
        )

    def count_listings(self) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        with self.session_factory() as session:
            return session.scalar(select(func.count()).select_from(PropertyListing)) or 0

    def count_processed_listings(self) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        with self.session_factory() as session:
            stmt = (
                select(func.count())
                .select_from(PropertyListing)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(
                    PropertyListing.is_deleted.is_(False),
                    PropertyAudit.is_processed.is_(True),
                )
            )
            return session.scalar(stmt) or 0

    def counts_snapshot(self) -> Dict[str, int]:
        if not self.enabled:
            return {
                "db_total_ids": 0,
                "db_processed_ids": 0,
                "db_pending_ids": 0,
                "db_detail_captured_ids": 0,
            }
        self.initialize()
        with self.session_factory() as session:
            stmt = (
                select(
                    func.count(PropertyListing.item_id),
                    func.sum(case((PropertyAudit.is_processed.is_(True), 1), else_=0)),
                    func.sum(case((PropertyAudit.detail_captured.is_(True), 1), else_=0)),
                    func.sum(
                        case(
                            (
                                self._detail_pending_filter(),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                )
                .select_from(PropertyListing)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(PropertyListing.is_deleted.is_(False))
            )
            total_ids, processed_ids, detail_captured_ids, pending_ids = session.execute(stmt).one()
            return {
                "db_total_ids": int(total_ids or 0),
                "db_processed_ids": int(processed_ids or 0),
                "db_pending_ids": int(pending_ids or 0),
                "db_detail_captured_ids": int(detail_captured_ids or 0),
            }

    def count_detail_captured_items(self) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        with self.session_factory() as session:
            stmt = (
                select(func.count())
                .select_from(PropertyListing)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(
                    PropertyListing.is_deleted.is_(False),
                    PropertyAudit.detail_captured.is_(True),
                )
            )
            return session.scalar(stmt) or 0

    def count_analysis_ready_items(self) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        with self.session_factory() as session:
            stmt = (
                select(func.count())
                .select_from(PropertyListing)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(self._analysis_ready_filter())
            )
            return session.scalar(stmt) or 0

    def analysis_readiness_snapshot(self) -> Dict[str, Any]:
        if not self.enabled:
            return {
                "ready": 0,
                "not_ready": 0,
                "invalid": 0,
                "blockers": {},
            }
        self.initialize()
        detail_stage_ready = or_(
            PropertyAudit.detail_status.in_(("archived", "enriched")),
            and_(PropertyAudit.detail_status.is_(None), PropertyAudit.detail_captured.is_(True)),
        )
        strict_status_ready = PropertyListing.status.in_(self._analysis_status_ready_values())
        strict_location_precision = or_(
            PropertyListing.latitude.is_not(None),
            and_(PropertyListing.community_name.is_not(None), PropertyListing.community_name != ""),
        )
        with self.session_factory() as session:
            stage_counts = self.stage_status_counts()
            blocker_stmt = (
                select(
                    func.sum(case((PropertyListing.auction_date.is_(None), 1), else_=0)),
                    func.sum(case((PropertyListing.area_sqm.is_(None), 1), else_=0)),
                    func.sum(case((or_(PropertyListing.city.is_(None), PropertyListing.city == ""), 1), else_=0)),
                    func.sum(case((or_(PropertyListing.district.is_(None), PropertyListing.district == ""), 1), else_=0)),
                    func.sum(case((or_(PropertyListing.business_area.is_(None), PropertyListing.business_area == ""), 1), else_=0)),
                    func.sum(case((not_(self._analysis_contract_has_price_anchor()), 1), else_=0)),
                    func.sum(case((not_(detail_stage_ready), 1), else_=0)),
                    func.sum(case((not_(strict_status_ready), 1), else_=0)),
                    func.sum(case((not_(strict_location_precision), 1), else_=0)),
                )
                .select_from(PropertyListing)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(self._analysis_not_ready_filter())
            )
            row = session.execute(blocker_stmt).one()
        blocker_keys = (
            "auction_date",
            "area_sqm",
            "city",
            "district",
            "business_area",
            "price_anchor",
            "detail_stage",
            "status",
            "location_precision",
        )
        blockers = {
            key: int(value or 0)
            for key, value in zip(blocker_keys, row)
            if int(value or 0) > 0
        }
        return {
            "ready": int(stage_counts.get("analysis_ready", 0) or 0),
            "not_ready": int(stage_counts.get("analysis_not_ready", 0) or 0),
            "invalid": int(stage_counts.get("analysis_invalid", 0) or 0),
            "blockers": blockers,
        }

    def dataset_signature(self) -> tuple[int, str | None]:
        if not self.enabled:
            return (0, None)
        self.initialize()
        with self.session_factory() as session:
            row = session.execute(
                select(
                    func.count(PropertyListing.item_id),
                    func.max(PropertyListing.last_synced_at),
                ).where(PropertyListing.is_deleted.is_(False))
            ).one()
            count_value, max_synced = row
            max_synced_text = None
            if max_synced is not None:
                max_synced_text = max_synced.isoformat(sep=" ", timespec="seconds")
            return int(count_value or 0), max_synced_text

    def yield_analysis_ready_rows(self, limit: int | None = None, chunk_size: int = 1000) -> Iterator[Dict[str, Any]]:
        if not self.enabled:
            return
        self.initialize()
        yielded = 0
        with self.session_factory() as session:
            stmt = (
                select(PropertyListing, PropertyRiskFlags, PropertyAudit)
                .outerjoin(PropertyRiskFlags, PropertyRiskFlags.item_id == PropertyListing.item_id)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(self._analysis_ready_filter())
                .order_by(PropertyListing.created_at.asc(), PropertyListing.item_id.asc())
                .execution_options(yield_per=max(1, chunk_size))
            )
            stream = session.execute(stmt)
            for listing, risk, audit in stream:
                yield self._feature_source_payload_from_rows(listing, risk, audit)
                yielded += 1
                if limit and yielded >= limit:
                    break

    def yield_analysis_ready_flat_items(self, limit: int | None = None, chunk_size: int = 1000) -> Iterator[Dict[str, Any]]:
        if not self.enabled:
            return
        self.initialize()
        yielded = 0
        with self.session_factory() as session:
            stmt = (
                select(PropertyListing, PropertyRiskFlags, PropertyLegalContext, PropertyAudit)
                .outerjoin(PropertyRiskFlags, PropertyRiskFlags.item_id == PropertyListing.item_id)
                .outerjoin(PropertyLegalContext, PropertyLegalContext.item_id == PropertyListing.item_id)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(self._analysis_ready_filter())
                .order_by(PropertyListing.created_at.asc(), PropertyListing.item_id.asc())
                .execution_options(yield_per=max(1, chunk_size))
            )
            stream = session.execute(stmt)
            for listing, risk, legal, audit in stream:
                yield self._listing_payload_from_rows(listing, risk, legal, audit)
                yielded += 1
                if limit and yielded >= limit:
                    break

    def iter_analysis_candidate_rows(
        self,
        subject: Dict[str, Any],
        *,
        per_bucket_limit: int = 1500,
        global_limit: int = 2000,
        total_limit: int = 5000,
    ) -> list[Dict[str, Any]]:
        if not self.enabled:
            return []
        self.initialize()

        def _norm(value: Any) -> str:
            text_value = str(value or "").strip()
            if not text_value or text_value == "UNK":
                return ""
            return text_value

        community = _norm(subject.get("community_name"))
        business_area = _norm(subject.get("business_area"))
        district = _norm(subject.get("district"))
        city = _norm(subject.get("city"))

        def _query(session: Session, *conditions, limit: int) -> list[Dict[str, Any]]:
            rows = (
                session.execute(
                    select(PropertyListing, PropertyRiskFlags, PropertyAudit)
                    .outerjoin(PropertyRiskFlags, PropertyRiskFlags.item_id == PropertyListing.item_id)
                    .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                    .where(
                        self._analysis_ready_filter(),
                        *conditions,
                    )
                    .order_by(PropertyListing.auction_date.desc().nulls_last(), PropertyListing.item_id.asc())
                    .limit(limit)
                )
                .all()
            )
            return [self._feature_source_payload_from_rows(listing, risk, audit) for listing, risk, audit in rows]

        ordered_candidates: list[Dict[str, Any]] = []
        seen_ids: set[str] = set()

        def _extend(rows: list[Dict[str, Any]]) -> None:
            for row in rows:
                item_id = str(row.get("item_id") or "")
                if not item_id or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                ordered_candidates.append(row)
                if len(ordered_candidates) >= total_limit:
                    return

        with self.session_factory() as session:
            if community:
                _extend(_query(session, PropertyListing.community_name == community, limit=per_bucket_limit))
            if len(ordered_candidates) < total_limit and city and district and business_area:
                _extend(
                    _query(
                        session,
                        PropertyListing.city == city,
                        PropertyListing.district == district,
                        PropertyListing.business_area == business_area,
                        limit=per_bucket_limit,
                    )
                )
            if len(ordered_candidates) < total_limit and city and district:
                _extend(
                    _query(
                        session,
                        PropertyListing.city == city,
                        PropertyListing.district == district,
                        limit=per_bucket_limit,
                    )
                )
            if len(ordered_candidates) < total_limit and city:
                _extend(_query(session, PropertyListing.city == city, limit=per_bucket_limit))
            if len(ordered_candidates) < total_limit:
                _extend(_query(session, limit=global_limit))

        return ordered_candidates[:total_limit]
