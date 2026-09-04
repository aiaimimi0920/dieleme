from __future__ import annotations

from .repository_context import *  # noqa: F401,F403


class RepositorySearchMixin:
    @staticmethod
    def _search_task_key(location_code: str, category: str, sort_param: str) -> str:
        return f"{location_code}:{category}:{sort_param}"

    @staticmethod
    def _build_search_task_url(location_code: str, category: str, sort_param: str, page: int) -> str:
        return (
            f"https://sf.taobao.com/list/{category}__2.htm"
            f"?location_code={location_code}&st_param={sort_param}&auction_start_seg=-1&page={page}"
        )

    def bootstrap_search_task(self, task: Dict[str, Any], leased_by: str | None = None, lease_seconds: int = 90) -> None:
        if not self.enabled:
            return
        self.initialize()
        location_code = str(task.get("location_code") or "").strip()
        category = str(task.get("category") or "").strip()
        sort_param = str(task.get("st_param") or "").strip()
        page = int(task.get("page") or 1)
        if not location_code or not category or not sort_param:
            return
        task_key = self._search_task_key(location_code, category, sort_param)
        now = _utc_now()
        with self.session_factory.begin() as session:
            row = session.get(PropertySearchTask, task_key) or PropertySearchTask(task_key=task_key)
            row.location_code = location_code
            row.category = category
            row.sort_param = sort_param
            row.next_page = page
            row.source_url = task.get("url") or self._build_search_task_url(location_code, category, sort_param, page)
            row.last_seen_at = now
            if leased_by:
                row.leased_by = leased_by
                row.lease_until = now + timedelta(seconds=max(lease_seconds, 1))
                row.status = "in_progress"
            else:
                row.status = row.status or "pending"
            session.add(row)

    def claim_search_task(
        self,
        session_id: str,
        lease_seconds: int = 90,
        *,
        priority_codes: Sequence[str] | None = None,
        sort_order: Sequence[str] | None = None,
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        self.initialize()
        now = _utc_now()
        priority_index = {code: idx for idx, code in enumerate(priority_codes or [])}
        sort_index = {code: idx for idx, code in enumerate(sort_order or ("2", "1", "0", "3", "4", "5"))}
        with self.session_factory.begin() as session:
            rows = session.execute(
                select(PropertySearchTask).where(PropertySearchTask.status.in_(("pending", "in_progress")))
            ).scalars().all()
            ordered_rows = sorted(
                rows,
                key=lambda row: (
                    0 if row.status == "pending" else 1,
                    priority_index.get(str(row.location_code), 10**9),
                    sort_index.get(str(row.sort_param), 10**9),
                    row.updated_at or datetime.min,
                    row.task_key,
                ),
            )
            for row in ordered_rows:
                if row.status == "in_progress" and row.leased_by != session_id:
                    if not _lease_reclaimable(row.lease_until, row.updated_at, now=now, lease_seconds=lease_seconds):
                        continue
                row.status = "in_progress"
                row.leased_by = session_id
                row.lease_until = now + timedelta(seconds=max(lease_seconds, 1))
                row.last_seen_at = now
                session.add(row)
                page = int(row.next_page or 1)
                return {
                    "location_code": row.location_code,
                    "category": row.category,
                    "st_param": row.sort_param,
                    "page": page,
                    "url": self._build_search_task_url(row.location_code, row.category or "", row.sort_param or "", page),
                    "desc": f"Sniff-{row.location_code}-S{row.sort_param}-P{page}",
                    "is_resume": page > 1,
                }
        return None

    def report_search_task_progress(
        self,
        *,
        url: str,
        page_num: int,
        has_next: bool = True,
        max_page: int | None = None,
        zero_bid_detected: bool = False,
    ) -> None:
        if not self.enabled:
            return
        self.initialize()
        from urllib.parse import parse_qs, urlparse
        import re

        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        location_code = params.get("location_code", [""])[0]
        sort_param = params.get("st_param", ["2"])[0]
        match = re.search(r"/list/(\d+)", parsed.path)
        category = match.group(1) if match else "50025969"
        if not location_code:
            return

        task_key = self._search_task_key(location_code, category, sort_param)
        now = _utc_now()
        with self.session_factory.begin() as session:
            row = session.get(PropertySearchTask, task_key) or PropertySearchTask(task_key=task_key)
            row.location_code = location_code
            row.category = category
            row.sort_param = sort_param
            row.source_url = url
            row.last_seen_at = now
            if max_page and (row.max_page is None or max_page > row.max_page):
                row.max_page = max_page

            if zero_bid_detected or (sort_param == "2" and not has_next and int(page_num or 1) < 83):
                row.status = "done"
                row.zero_bid_terminated = True
                row.next_page = max(int(page_num or 1), 1)
                row.leased_by = None
                row.lease_until = None
                sibling_status = "pruned"
            elif has_next:
                row.status = "pending"
                row.next_page = max(int(page_num or 1) + 1, row.next_page or 1)
                row.leased_by = None
                row.lease_until = None
                sibling_status = None
            else:
                row.status = "done"
                row.next_page = max(int(page_num or 1), row.next_page or 1)
                row.leased_by = None
                row.lease_until = None
                sibling_status = "pending" if sort_param == "2" and int(page_num or 1) >= 83 else None

            session.add(row)
            if sort_param == "2" and sibling_status in {"pending", "pruned"}:
                for sibling_sort in ("1", "0", "3", "4", "5"):
                    sibling_key = self._search_task_key(location_code, category, sibling_sort)
                    sibling = session.get(PropertySearchTask, sibling_key) or PropertySearchTask(task_key=sibling_key)
                    sibling.location_code = location_code
                    sibling.category = category
                    sibling.sort_param = sibling_sort
                    sibling.next_page = max(int(sibling.next_page or 1), 1)
                    sibling.source_url = self._build_search_task_url(location_code, category, sibling_sort, sibling.next_page)
                    sibling.status = sibling_status
                    sibling.zero_bid_terminated = sibling_status == "pruned"
                    sibling.leased_by = None
                    sibling.lease_until = None
                    sibling.last_seen_at = now
                    session.add(sibling)

    def search_task_counts(self) -> Dict[str, int]:
        counts = {
            "search_pending": 0,
            "search_in_progress": 0,
            "search_done": 0,
            "search_pruned": 0,
        }
        if not self.enabled:
            return counts
        self.initialize()
        with self.session_factory() as session:
            stmt = select(PropertySearchTask.status, func.count(PropertySearchTask.task_key)).group_by(PropertySearchTask.status)
            for status, count_value in session.execute(stmt):
                key = f"search_{status}"
                if key in counts:
                    counts[key] = int(count_value or 0)
        return counts

    def count_search_tasks(self) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        with self.session_factory() as session:
            return int(session.scalar(select(func.count()).select_from(PropertySearchTask)) or 0)

    def ensure_seed_search_tasks(self, location_codes: Sequence[str], categories: Sequence[str], sort_param: str = "2") -> int:
        if not self.enabled:
            return 0
        self.initialize()
        inserted = 0
        with self.session_factory.begin() as session:
            for location_code in location_codes:
                if not location_code:
                    continue
                for category in categories:
                    task_key = self._search_task_key(str(location_code), str(category), str(sort_param))
                    row = session.get(PropertySearchTask, task_key)
                    if row is not None:
                        continue
                    row = PropertySearchTask(
                        task_key=task_key,
                        location_code=str(location_code),
                        category=str(category),
                        sort_param=str(sort_param),
                        next_page=1,
                        status="pending",
                        zero_bid_terminated=False,
                        retry_count=0,
                        source_url=self._build_search_task_url(str(location_code), str(category), str(sort_param), 1),
                    )
                    session.add(row)
                    inserted += 1
        return inserted

    def import_search_task_snapshots(self, snapshots: Sequence[Dict[str, Any]]) -> int:
        if not self.enabled:
            return 0
        self.initialize()
        imported = 0
        with self.session_factory.begin() as session:
            for snapshot in snapshots:
                location_code = str(snapshot.get("location_code") or "").strip()
                category = str(snapshot.get("category") or "").strip()
                sort_param = str(snapshot.get("sort_param") or "").strip()
                if not location_code or not category or not sort_param:
                    continue
                task_key = self._search_task_key(location_code, category, sort_param)
                row = session.get(PropertySearchTask, task_key) or PropertySearchTask(task_key=task_key)
                pages = snapshot.get("pages") or []
                page_floor = max([int(p) for p in pages if isinstance(p, int) or str(p).isdigit()] or [0])
                dispatched_page = int(snapshot.get("dispatched_page") or 0)
                next_page = max(page_floor, dispatched_page, 0) + 1 if not snapshot.get("is_done") else max(page_floor, dispatched_page, 1)
                last_update = _parse_dt(snapshot.get("last_update_time"))
                need_try = bool(snapshot.get("need_try", True))
                is_done = bool(snapshot.get("is_done", False))
                max_page = snapshot.get("max_page")
                max_page_int = int(max_page) if max_page not in (None, "") and str(max_page).lstrip("-").isdigit() else None

                status = "pending"
                zero_bid_terminated = False
                if is_done and not need_try and sort_param != "2":
                    status = "pruned"
                elif is_done:
                    status = "done"
                    if sort_param == "2" and max_page_int is not None and 0 < max_page_int < 83:
                        zero_bid_terminated = True
                elif snapshot.get("now_session_id"):
                    status = "in_progress"

                row.location_code = location_code
                row.category = category
                row.sort_param = sort_param
                row.next_page = max(next_page, 1)
                row.max_page = max_page_int
                row.status = status
                row.leased_by = str(snapshot.get("now_session_id") or "").strip() or None
                row.lease_until = last_update + timedelta(seconds=90) if row.leased_by and last_update else None
                row.zero_bid_terminated = zero_bid_terminated
                row.source_url = self._build_search_task_url(location_code, category, sort_param, row.next_page)
                row.last_seen_at = last_update
                row.retry_count = int(row.retry_count or 0)
                session.add(row)
                imported += 1
        return imported
