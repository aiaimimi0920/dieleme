from __future__ import annotations

from .repository_context import *  # noqa: F401,F403


class RepositorySeedItemsMixin:
    def upsert_seed_items(
        self,
        *,
        job_key: str,
        progress_key: str,
        sort_key: str,
        sort_name: str | None,
        st_param: str,
        page: int,
        source_page_url: str,
        items: Sequence[Dict[str, Any]],
        source_final_url: str | None = None,
    ) -> Dict[str, int]:
        if not self.enabled:
            return {"seen": 0, "new_items": 0, "existing_items": 0, "new_occurrences": 0}
        self.initialize()
        now = _utc_now()
        seen = 0
        new_items = 0
        existing_items = 0
        new_occurrences = 0
        with self.session_factory.begin() as session:
            dialect_name = session.get_bind().dialect.name
            for rank, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    continue
                item_id = _normalized_seed_text(item.get("id") or item.get("item_id") or item.get("source_item_id"))
                if not item_id:
                    continue
                seen += 1
                url = self._seed_item_url(item_id, item.get("url") or item.get("source_url") or item.get("itemUrl"))
                title = _normalized_seed_text(item.get("title") or item.get("source_title"))
                seed_item = session.get(FapaiSeedItem, item_id)
                if seed_item is None:
                    insert_values = {
                        "item_id": item_id,
                        "source_item_id": item_id,
                        "source_url": url,
                        "title": title,
                        "first_seen_job_key": job_key,
                        "first_seen_sort_key": sort_key,
                        "first_seen_at": now,
                        "last_seen_at": now,
                        "source_payload": dict(item),
                        "status": "pending_detail",
                        "detail_attempt_count": 0,
                    }
                    if dialect_name == "postgresql":
                        insert_stmt = postgresql_insert(FapaiSeedItem).values(**insert_values)
                        insert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=[FapaiSeedItem.item_id])
                    elif dialect_name == "sqlite":
                        insert_stmt = sqlite_insert(FapaiSeedItem).values(**insert_values)
                        insert_stmt = insert_stmt.on_conflict_do_nothing(index_elements=[FapaiSeedItem.item_id])
                    else:
                        insert_stmt = None
                    if insert_stmt is not None:
                        result = session.execute(insert_stmt)
                        if int(result.rowcount or 0) > 0:
                            new_items += 1
                        else:
                            existing_items += 1
                    else:
                        try:
                            session.add(
                                FapaiSeedItem(
                                    item_id=item_id,
                                    source_item_id=item_id,
                                    source_url=url,
                                    title=title,
                                    first_seen_job_key=job_key,
                                    first_seen_sort_key=sort_key,
                                    first_seen_at=now,
                                    last_seen_at=now,
                                    source_payload=dict(item),
                                    status="pending_detail",
                                    detail_attempt_count=0,
                                )
                            )
                            session.flush()
                            new_items += 1
                        except IntegrityError:
                            session.rollback()
                            existing_items += 1
                    seed_item = session.get(FapaiSeedItem, item_id)
                    if seed_item is None:
                        continue
                else:
                    existing_items += 1
                if not seed_item.source_url and url:
                    seed_item.source_url = url
                if not seed_item.title and title:
                    seed_item.title = title
                seed_item.last_seen_at = now
                seed_item.source_payload = dict(item)
                if seed_item.status in (None, "", "blocked"):
                    seed_item.status = "pending_detail"
                session.add(seed_item)

                occurrence_key = self._occurrence_key(
                    item_id=item_id,
                    job_key=job_key,
                    sort_key=sort_key,
                    page=int(page or 1),
                    rank=rank,
                )
                occurrence_values = {
                    "occurrence_key": occurrence_key,
                    "item_id": item_id,
                    "job_key": job_key,
                    "progress_key": progress_key,
                    "sort_key": sort_key,
                    "sort_name": sort_name,
                    "st_param": st_param,
                    "page": int(page or 1),
                    "rank": rank,
                    "source_page_url": source_page_url,
                    "source_final_url": source_final_url,
                    "raw_item": dict(item),
                    "seen_at": now,
                }
                if dialect_name == "postgresql":
                    occurrence_stmt = postgresql_insert(FapaiSeedOccurrence).values(**occurrence_values)
                    occurrence_stmt = occurrence_stmt.on_conflict_do_nothing(
                        index_elements=[FapaiSeedOccurrence.occurrence_key]
                    )
                    occurrence_result = session.execute(occurrence_stmt)
                    if int(occurrence_result.rowcount or 0) > 0:
                        new_occurrences += 1
                elif dialect_name == "sqlite":
                    occurrence_stmt = sqlite_insert(FapaiSeedOccurrence).values(**occurrence_values)
                    occurrence_stmt = occurrence_stmt.on_conflict_do_nothing(
                        index_elements=[FapaiSeedOccurrence.occurrence_key]
                    )
                    occurrence_result = session.execute(occurrence_stmt)
                    if int(occurrence_result.rowcount or 0) > 0:
                        new_occurrences += 1
                else:
                    occurrence = session.scalars(
                        select(FapaiSeedOccurrence).where(FapaiSeedOccurrence.occurrence_key == occurrence_key)
                    ).first()
                    if occurrence is None:
                        occurrence = FapaiSeedOccurrence(**occurrence_values)
                        session.add(occurrence)
                        new_occurrences += 1
        return {
            "seen": seen,
            "new_items": new_items,
            "existing_items": existing_items,
            "new_occurrences": new_occurrences,
        }
