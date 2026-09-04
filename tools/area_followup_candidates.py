"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.area_followup_context import *


def extract_area_candidates_from_text(text: str, *, source_type: str, source_path: str | None = None) -> list[dict[str, Any]]:
    area = llm_helper.extract_area_from_text(text)
    if area is None:
        return []
    return [
        {
            "area_sqm": round(float(area), 2),
            "source_type": source_type,
            "source_path": source_path,
            "evidence": _evidence_window(text, float(area)),
            "confidence": 0.82 if source_type in {"notice_text", "detail_html", "local_text"} else 0.72,
        }
    ]


def extract_area_candidates_from_paths(paths: Iterable[str | Path]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for raw_path in paths:
        path = Path(raw_path)
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        candidates.extend(extract_area_candidates_from_text(text, source_type="local_text", source_path=str(path)))
    return candidates


def _notice_urls_from_job(job: dict[str, Any]) -> list[str]:
    raw_urls: list[Any] = []
    raw_urls.extend(job.get("announcement_attachment_urls") or [])
    raw_urls.extend(job.get("appraisal_report_urls") or [])
    artifacts = as_dict(job.get("artifacts"))
    raw_urls.extend(artifacts.get("announcement_attachment_urls") or [])
    urls: list[str] = []
    for raw in raw_urls:
        url = str(raw or "").strip()
        if not url or url in urls:
            continue
        host = urlparse(url).netloc
        path = urlparse(url).path
        if "notice_detail" in path or "notice_detail" in url:
            urls.append(url)
    return urls


def _notice_content_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one(".notice-content") or soup.find(id="J_NoticeDetail") or soup.body
    if node is None:
        return " ".join(soup.stripped_strings)
    return " ".join(node.stripped_strings)


def fetch_notice_detail_candidates(
    job: dict[str, Any],
    *,
    item_dir: Path,
    http_session: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates: list[dict[str, Any]] = []
    fetched: list[dict[str, Any]] = []
    for index, url in enumerate(_notice_urls_from_job(job), start=1):
        response = http_session.get(
            url,
            headers={
                "User-Agent": DEFAULT_USER_AGENT,
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Referer": str(job.get("source_url") or ""),
            },
            timeout=30,
            allow_redirects=True,
        )
        response.raise_for_status()
        text = decode_response_text(response)
        archive_path = item_dir / f"notice_detail_{index}.html"
        archive_path.write_text(text, encoding="utf-8")
        content_text = _notice_content_text(text)
        text_path = item_dir / f"notice_detail_{index}.txt"
        text_path.write_text(content_text, encoding="utf-8")
        fetched.append(
            {
                "url": url,
                "final_url": getattr(response, "url", url),
                "status_code": getattr(response, "status_code", None),
                "html_path": str(archive_path),
                "text_path": str(text_path),
                "text_len": len(content_text),
            }
        )
        candidates.extend(
            extract_area_candidates_from_text(content_text, source_type="notice_detail", source_path=str(text_path))
        )
    return candidates, fetched


__all__ = (
    "extract_area_candidates_from_text",
    "extract_area_candidates_from_paths",
    "_notice_urls_from_job",
    "_notice_content_text",
    "fetch_notice_detail_candidates",
)
