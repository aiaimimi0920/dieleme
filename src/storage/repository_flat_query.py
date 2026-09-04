from __future__ import annotations

from .repository_context import *  # noqa: F401,F403


class RepositoryFlatQueryMixin:
    def get_flat_item(self, item_id: str) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        self.initialize()
        with self.session_factory() as session:
            listing = session.get(PropertyListing, item_id)
            if listing is None or listing.is_deleted:
                return None
            risk = session.get(PropertyRiskFlags, item_id)
            legal = session.get(PropertyLegalContext, item_id)
            audit = session.get(PropertyAudit, item_id)
            return self._listing_payload_from_rows(listing, risk, legal, audit)

    def _select_flat_item_rows(self, session: Session, where_clause=None, limit: int | None = None):
        stmt = (
            select(PropertyListing, PropertyRiskFlags, PropertyLegalContext, PropertyAudit)
            .outerjoin(PropertyRiskFlags, PropertyRiskFlags.item_id == PropertyListing.item_id)
            .outerjoin(PropertyLegalContext, PropertyLegalContext.item_id == PropertyListing.item_id)
            .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
            .where(PropertyListing.is_deleted.is_(False))
            .order_by(PropertyListing.created_at.asc(), PropertyListing.item_id.asc())
        )
        if where_clause is not None:
            stmt = stmt.where(where_clause)
        if limit and limit > 0:
            stmt = stmt.limit(limit)
        return session.execute(stmt).all()

    def iter_flat_items(self, limit: int | None = None) -> list[Dict[str, Any]]:
        if not self.enabled:
            return []
        self.initialize()
        with self.session_factory() as session:
            rows = self._select_flat_item_rows(session, limit=limit)
            result = []
            for listing, risk, legal, audit in rows:
                result.append(
                    self._listing_payload_from_rows(
                        listing,
                        risk,
                        legal,
                        audit,
                    )
                )
            return result

    def yield_feature_source_rows(self, limit: int | None = None, chunk_size: int = 1000) -> Iterator[Dict[str, Any]]:
        if not self.enabled:
            return
        self.initialize()
        yielded = 0
        with self.session_factory() as session:
            stmt = (
                select(PropertyListing, PropertyRiskFlags, PropertyAudit)
                .outerjoin(PropertyRiskFlags, PropertyRiskFlags.item_id == PropertyListing.item_id)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(PropertyListing.is_deleted.is_(False))
                .order_by(PropertyListing.created_at.asc(), PropertyListing.item_id.asc())
                .execution_options(yield_per=max(1, chunk_size))
            )
            stream = session.execute(stmt)
            for listing, risk, audit in stream:
                yield self._feature_source_payload_from_rows(listing, risk, audit)
                yielded += 1
                if limit and yielded >= limit:
                    break

    def iter_feature_candidate_rows(
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
                    .where(PropertyListing.is_deleted.is_(False), *conditions)
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

    def yield_flat_items(self, limit: int | None = None, chunk_size: int = 1000) -> Iterator[Dict[str, Any]]:
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
                .where(PropertyListing.is_deleted.is_(False))
                .order_by(PropertyListing.created_at.asc(), PropertyListing.item_id.asc())
                .execution_options(yield_per=max(1, chunk_size))
            )
            stream = session.execute(stmt)
            for listing, risk, legal, audit in stream:
                yield self._listing_payload_from_rows(listing, risk, legal, audit)
                yielded += 1
                if limit and yielded >= limit:
                    break

    def iter_recent_flat_items(self, window_days: int, limit: int | None = None) -> list[Dict[str, Any]]:
        if not self.enabled:
            return []
        self.initialize()
        with self.session_factory() as session:
            max_dt = session.scalar(
                select(func.max(PropertyListing.auction_date)).where(
                    PropertyListing.is_deleted.is_(False),
                    PropertyListing.auction_date.is_not(None),
                )
            )
            if max_dt is None:
                return []
            recent_start = max_dt - timedelta(days=max(window_days - 1, 0))
            rows = self._select_flat_item_rows(
                session,
                where_clause=PropertyListing.auction_date >= recent_start,
                limit=limit,
            )
            result = []
            for listing, risk, legal, audit in rows:
                result.append(self._listing_payload_from_rows(listing, risk, legal, audit))
            return result

    def yield_recent_flat_items(
        self,
        window_days: int,
        limit: int | None = None,
        chunk_size: int = 1000,
    ) -> Iterator[Dict[str, Any]]:
        if not self.enabled:
            return
        self.initialize()
        yielded = 0
        with self.session_factory() as session:
            max_dt = session.scalar(
                select(func.max(PropertyListing.auction_date)).where(
                    PropertyListing.is_deleted.is_(False),
                    PropertyListing.auction_date.is_not(None),
                )
            )
            if max_dt is None:
                return
            recent_start = max_dt - timedelta(days=max(window_days - 1, 0))
            stmt = (
                select(PropertyListing, PropertyRiskFlags, PropertyLegalContext, PropertyAudit)
                .outerjoin(PropertyRiskFlags, PropertyRiskFlags.item_id == PropertyListing.item_id)
                .outerjoin(PropertyLegalContext, PropertyLegalContext.item_id == PropertyListing.item_id)
                .outerjoin(PropertyAudit, PropertyAudit.item_id == PropertyListing.item_id)
                .where(
                    PropertyListing.is_deleted.is_(False),
                    PropertyListing.auction_date >= recent_start,
                )
                .order_by(PropertyListing.created_at.asc(), PropertyListing.item_id.asc())
                .execution_options(yield_per=max(1, chunk_size))
            )
            stream = session.execute(stmt)
            for listing, risk, legal, audit in stream:
                yield self._listing_payload_from_rows(listing, risk, legal, audit)
                yielded += 1
                if limit and yielded >= limit:
                    break
