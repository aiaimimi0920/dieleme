from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import parse_qs, urlparse


@dataclass(frozen=True)
class SearchTaskSeed:
    task_key: str
    location_code: str
    category: str
    sort_param: str
    page: int
    source_url: str


@dataclass(frozen=True)
class SearchProgressDecision:
    status: str
    next_page: int
    source_url: str | None
    zero_bid_terminated: bool | None = None
    sibling_status: str | None = None


class SearchTaskPolicy(Protocol):
    source_platform: str
    sibling_sort_params: tuple[str, ...]
    requires_lease_owner: bool

    def normalize_bootstrap(self, task: Mapping[str, Any]) -> SearchTaskSeed | None: ...

    def owns_task(self, task_key: str) -> bool: ...

    def resolve_progress_task_key(self, *, task_key: str | None, url: str | None) -> str | None: ...

    def claim_payload(
        self,
        *,
        task_key: str,
        location_code: str,
        category: str,
        sort_param: str,
        page: int,
        source_url: str | None,
    ) -> dict[str, Any]: ...

    def progress_decision(
        self,
        *,
        sort_param: str,
        current_next_page: int,
        current_source_url: str | None,
        page_num: int,
        has_next: bool,
        zero_bid_detected: bool,
        url: str | None,
        next_url: str | None,
    ) -> SearchProgressDecision: ...

    def sibling_url(self, *, location_code: str, category: str, sort_param: str, page: int) -> str: ...


@dataclass(frozen=True)
class GenericSearchTaskPolicy:
    """URL-cursor task policy for arbitrary product listing sources."""

    source_platform: str = "generic"
    sibling_sort_params: tuple[str, ...] = ()
    requires_lease_owner: bool = True

    @property
    def task_key_prefix(self) -> str:
        platform = self.source_platform.strip() or "generic"
        slug = re.sub(r"[^a-z0-9]+", "-", platform.lower()).strip("-") or "source"
        namespace = f"{slug[:24]}-{hashlib.sha256(platform.encode('utf-8')).hexdigest()[:8]}"
        return f"source:{namespace}:"

    def normalize_bootstrap(self, task: Mapping[str, Any]) -> SearchTaskSeed | None:
        source_url = str(task.get("source_url") or task.get("url") or "").strip()
        if not source_url:
            return None
        supplied_key = str(task.get("task_key") or "").strip()
        internal_key_pattern = rf"{re.escape(self.task_key_prefix)}[0-9a-f]{{40}}"
        if re.fullmatch(internal_key_pattern, supplied_key):
            task_key = supplied_key
        else:
            identity = supplied_key or source_url
            digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:40]
            task_key = f"{self.task_key_prefix}{digest}"
        page = max(int(task.get("page") or 1), 1)
        return SearchTaskSeed(
            task_key=task_key,
            location_code=str(task.get("location_code") or "source").strip()[:16] or "source",
            category=(self.source_platform.strip() or "generic")[:32],
            sort_param="source",
            page=page,
            source_url=source_url,
        )

    def owns_task(self, task_key: str) -> bool:
        return task_key.startswith(self.task_key_prefix)

    def resolve_progress_task_key(self, *, task_key: str | None, url: str | None) -> str | None:
        del url
        normalized = str(task_key or "").strip()
        return normalized if self.owns_task(normalized) else None

    def claim_payload(
        self,
        *,
        task_key: str,
        location_code: str,
        category: str,
        sort_param: str,
        page: int,
        source_url: str | None,
    ) -> dict[str, Any]:
        del category, sort_param
        payload = {
            "task_key": task_key,
            "source_platform": self.source_platform,
            "page": page,
            "url": source_url,
            "desc": f"Collect-{self.source_platform}-P{page}",
            "is_resume": page > 1,
        }
        if location_code != "source":
            payload["location_code"] = location_code
        return payload

    def progress_decision(
        self,
        *,
        sort_param: str,
        current_next_page: int,
        current_source_url: str | None,
        page_num: int,
        has_next: bool,
        zero_bid_detected: bool,
        url: str | None,
        next_url: str | None,
    ) -> SearchProgressDecision:
        del sort_param, zero_bid_detected
        page = max(int(page_num or 1), 1)
        return SearchProgressDecision(
            status="pending" if has_next else "done",
            next_page=max(page + 1 if has_next else page, current_next_page or 1),
            source_url=next_url or url or current_source_url,
            zero_bid_terminated=False,
        )

    def sibling_url(self, *, location_code: str, category: str, sort_param: str, page: int) -> str:
        del location_code, category, sort_param, page
        raise ValueError("generic search tasks do not create sibling sorts")


@dataclass(frozen=True)
class TaobaoJudicialSearchTaskPolicy:
    """Legacy-compatible task policy for sf.taobao.com listing pages."""

    source_platform: str = "taobao_sf"
    sibling_sort_params: tuple[str, ...] = ("1", "0", "3", "4", "5")
    requires_lease_owner: bool = False

    @staticmethod
    def task_key(location_code: str, category: str, sort_param: str) -> str:
        return f"{location_code}:{category}:{sort_param}"

    @staticmethod
    def build_url(location_code: str, category: str, sort_param: str, page: int) -> str:
        return (
            f"https://sf.taobao.com/list/{category}__2.htm"
            f"?location_code={location_code}&st_param={sort_param}&auction_start_seg=-1&page={page}"
        )

    def normalize_bootstrap(self, task: Mapping[str, Any]) -> SearchTaskSeed | None:
        location_code = str(task.get("location_code") or "").strip()
        category = str(task.get("category") or "").strip()
        sort_param = str(task.get("st_param") or "").strip()
        page = max(int(task.get("page") or 1), 1)
        source_url = str(task.get("url") or "").strip()
        if source_url and (not location_code or not category or not sort_param):
            parsed = urlparse(source_url)
            params = parse_qs(parsed.query)
            location_code = location_code or params.get("location_code", [""])[0]
            sort_param = sort_param or params.get("st_param", ["2"])[0]
            match = re.search(r"/list/(\d+)", parsed.path)
            category = category or (match.group(1) if match else "50025969")
        if not location_code or not category or not sort_param:
            return None
        return SearchTaskSeed(
            task_key=self.task_key(location_code, category, sort_param),
            location_code=location_code,
            category=category,
            sort_param=sort_param,
            page=page,
            source_url=source_url or self.build_url(location_code, category, sort_param, page),
        )

    def owns_task(self, task_key: str) -> bool:
        return re.fullmatch(r"\d+:\d+:[0-5]", task_key) is not None

    def resolve_progress_task_key(self, *, task_key: str | None, url: str | None) -> str | None:
        normalized_key = str(task_key or "").strip()
        if normalized_key and self.owns_task(normalized_key):
            return normalized_key
        parsed = urlparse(str(url or ""))
        params = parse_qs(parsed.query)
        location_code = params.get("location_code", [""])[0]
        if not location_code:
            return None
        sort_param = params.get("st_param", ["2"])[0]
        match = re.search(r"/list/(\d+)", parsed.path)
        category = match.group(1) if match else "50025969"
        return self.task_key(location_code, category, sort_param)

    def claim_payload(
        self,
        *,
        task_key: str,
        location_code: str,
        category: str,
        sort_param: str,
        page: int,
        source_url: str | None,
    ) -> dict[str, Any]:
        del source_url
        return {
            "task_key": task_key,
            "source_platform": self.source_platform,
            "location_code": location_code,
            "category": category,
            "st_param": sort_param,
            "page": page,
            "url": self.build_url(location_code, category, sort_param, page),
            "desc": f"Sniff-{location_code}-S{sort_param}-P{page}",
            "is_resume": page > 1,
        }

    def progress_decision(
        self,
        *,
        sort_param: str,
        current_next_page: int,
        current_source_url: str | None,
        page_num: int,
        has_next: bool,
        zero_bid_detected: bool,
        url: str | None,
        next_url: str | None,
    ) -> SearchProgressDecision:
        del next_url
        page = max(int(page_num or 1), 1)
        if zero_bid_detected or (sort_param == "2" and not has_next and page < 83):
            sibling_status = "pruned" if sort_param == "2" else None
            return SearchProgressDecision("done", page, url or current_source_url, True, sibling_status)
        if has_next:
            return SearchProgressDecision(
                "pending", max(page + 1, current_next_page or 1), url or current_source_url
            )
        sibling_status = "pending" if sort_param == "2" and page >= 83 else None
        return SearchProgressDecision(
            "done", max(page, current_next_page or 1), url or current_source_url, None, sibling_status
        )

    def sibling_url(self, *, location_code: str, category: str, sort_param: str, page: int) -> str:
        return self.build_url(location_code, category, sort_param, page)


DEFAULT_SEARCH_TASK_POLICY = TaobaoJudicialSearchTaskPolicy()
