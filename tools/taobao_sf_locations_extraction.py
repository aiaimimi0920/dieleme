"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.taobao_sf_locations_context import *


def is_challenge_html(html: str, final_url: str = "") -> bool:
    parsed_url = urlparse(final_url or "")
    if parsed_url.hostname in {"login.taobao.com", "login.tmall.com"}:
        return True
    text = f"{final_url}\n{html or ''}"
    return any(marker in text for marker in CHALLENGE_MARKERS)


def absolute_href(href: str, page_url: str = "https://sf.taobao.com/") -> str:
    clean_href = clean_text(href)
    if clean_href.startswith("//"):
        return f"https:{clean_href}"
    return urljoin(page_url or "https://sf.taobao.com/", clean_href)


def extract_location_code(href: str) -> str | None:
    parsed = urlparse(href)
    values = parse_qs(parsed.query).get("location_code") or []
    if not values:
        return None
    code = clean_text(values[0])
    return code if code else None


def _is_taobao_sf_list_href(href: str) -> bool:
    return "sf.taobao.com/list/" in href or href.startswith("//sf.taobao.com/list/")


def _is_city_location_href(href: str) -> bool:
    path = urlparse(href).path
    return "___" in path


def _is_province_location_href(href: str) -> bool:
    path = urlparse(href).path
    return "__" in path and "___" not in path


def _tag_text(tag: Any) -> str:
    return clean_text(tag.get_text(" ", strip=True) if tag is not None else "")


def _find_location_filter_scope(soup: BeautifulSoup) -> Any | None:
    key_nodes = soup.find_all(string=lambda value: clean_text(value) == "所在地")
    for key_node in key_nodes:
        key_tag = getattr(key_node, "parent", None)
        current = key_tag
        for _ in range(5):
            if current is None:
                break
            current = current.parent
            if current is None or getattr(current, "name", None) in {"body", "html", "[document]"}:
                break
            anchors = current.find_all("a", href=True)
            if not anchors:
                continue
            location_like_count = sum(1 for anchor in anchors if _is_taobao_sf_list_href(absolute_href(anchor.get("href", ""))))
            if location_like_count and len(anchors) <= 260:
                return current
    return None


def _collect_location_anchors_from_document_order(soup: BeautifulSoup, page_url: str) -> list[Any]:
    key = soup.find(string=lambda value: clean_text(value) == "所在地")
    if key is None:
        return []
    key_tag = getattr(key, "parent", None)
    anchors: list[Any] = []
    started = False
    for tag in soup.find_all(True):
        if tag is key_tag:
            started = True
            continue
        if not started:
            continue
        if "sf-filter-key" in (tag.get("class") or []) and clean_text(tag.get_text(strip=True)) != "所在地":
            break
        if tag.name == "a" and tag.get("href"):
            href = absolute_href(str(tag.get("href")), page_url)
            if _is_taobao_sf_list_href(href):
                anchors.append(tag)
    return anchors


def extract_location_filter_options(html: str, *, page_url: str = "https://sf.taobao.com/") -> LocationFilterOptions:
    soup = BeautifulSoup(html or "", "html.parser")
    scope = _find_location_filter_scope(soup)
    anchors = scope.find_all("a", href=True) if scope is not None else _collect_location_anchors_from_document_order(soup, page_url)
    provinces: list[LocationOption] = []
    cities: list[LocationOption] = []
    districts: list[LocationOption] = []
    seen: set[tuple[str, str, str | None, str]] = set()
    for anchor in anchors:
        label = _tag_text(anchor)
        if label in LOCATION_OPTION_IGNORE_LABELS or (label in CATEGORY_LABELS and label not in {"其他", "其它"}):
            continue
        href = absolute_href(str(anchor.get("href") or ""), page_url)
        if not _is_taobao_sf_list_href(href):
            continue
        location_code = extract_location_code(href)
        if location_code:
            level = "district"
        elif _is_city_location_href(href):
            level = "city"
        elif _is_province_location_href(href):
            level = "province"
        else:
            continue
        key = (level, label, location_code, href)
        if key in seen:
            continue
        seen.add(key)
        option = LocationOption(label=label, href=href, level=level, location_code=location_code)
        if level == "district":
            districts.append(option)
        elif level == "city":
            cities.append(option)
        else:
            provinces.append(option)
    return LocationFilterOptions(provinces=provinces, cities=cities, districts=districts, source_url=page_url)


__all__ = (
    'is_challenge_html',
    'absolute_href',
    'extract_location_code',
    '_is_taobao_sf_list_href',
    '_is_city_location_href',
    '_is_province_location_href',
    '_tag_text',
    '_find_location_filter_scope',
    '_collect_location_anchors_from_document_order',
    'extract_location_filter_options',
)
