from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src import llm_helper
from src.avm.collection_template import sync_collection_record
from src.avm.normalize import parse_area_sqm, parse_money_to_yuan
from src.detail_artifacts import extract_detail_artifacts


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/148.0.0.0 Safari/537.36 Edg/148.0.0.0"
)


def load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def decode_response_text(response: Any) -> str:
    content = bytes(getattr(response, "content", b"") or b"")
    content_type = str(getattr(response, "headers", {}).get("Content-Type", ""))
    declared = None
    match = re.search(r"charset=([A-Za-z0-9_\-]+)", content_type, re.I)
    if match:
        declared = match.group(1)
    encodings = [declared, getattr(response, "encoding", None), "utf-8", "gb18030", "gbk"]
    best_text = ""
    best_replacements = None
    for encoding in [enc for enc in encodings if enc]:
        try:
            text = content.decode(str(encoding), errors="replace")
        except LookupError:
            continue
        replacements = text.count("\ufffd")
        if best_replacements is None or replacements < best_replacements:
            best_text = text
            best_replacements = replacements
            if replacements == 0:
                break
    if best_text:
        return best_text
    return str(getattr(response, "text", "") or "")


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def has_positive_area(value: Any) -> bool:
    parsed = parse_area_sqm(value)
    return parsed is not None and parsed > 0


def _evidence_window(text: str, area: float) -> str:
    markers = ("房屋建筑面积", "不动产建筑面积", "产权建筑面积", "证载建筑面积", "建筑面积")
    best_index = -1
    for marker in markers:
        index = text.find(marker)
        if index >= 0:
            best_index = index
            break
    if best_index < 0:
        best_index = text.find(str(area))
    if best_index < 0:
        best_index = 0
    start = max(best_index - 40, 0)
    end = min(best_index + 140, len(text))
    return " ".join(text[start:end].split())


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


def _artifact_root_for_job(job: dict[str, Any], artifact_root: str | Path | None) -> Path | None:
    if artifact_root is not None:
        return Path(artifact_root)
    for key in ("detail_html_path", "final_json_path", "selected_json_path"):
        value = job.get(key)
        if value:
            path = Path(value)
            if path.parent.name == str(job.get("item_id")):
                return path.parent.parent
            return path.parent
    return None


def _job_item_dir(job: dict[str, Any], artifact_root: str | Path | None) -> Path:
    item_id = str(job.get("item_id") or "")
    root = _artifact_root_for_job(job, artifact_root)
    if root is not None and item_id:
        return root / item_id
    for key in ("detail_html_path", "final_json_path", "selected_json_path"):
        value = job.get(key)
        if value:
            return Path(value).parent
    return Path(".") / item_id


def _first_existing_path(*values: Any) -> Path | None:
    for value in values:
        if not value:
            continue
        path = Path(str(value))
        if path.exists():
            return path
    return None


def _relative_artifact_path(path: str | Path | None, root: Path) -> str:
    if not path:
        return ""
    candidate = Path(path)
    try:
        return os.path.relpath(candidate, root).replace("\\", "/")
    except ValueError:
        return str(candidate)


def _load_final_payload(job: dict[str, Any], item_dir: Path) -> dict[str, Any]:
    path = _first_existing_path(job.get("final_json_path"), item_dir / "final.json")
    if path is None:
        return {}
    payload = load_json(path)
    return payload if isinstance(payload, dict) else {}


def _transaction_price(job: dict[str, Any], final_payload: dict[str, Any]) -> float | None:
    auction = as_dict(final_payload.get("auction"))
    for value in (
        job.get("transaction_price"),
        final_payload.get("成交价格"),
        final_payload.get("transaction_price"),
        auction.get("transaction_price"),
    ):
        amount = parse_money_to_yuan(value)
        if amount is not None:
            return amount
    return None


def _extract_candidates_from_detail_html(job: dict[str, Any], item_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    path = _first_existing_path(job.get("detail_html_path"), item_dir / "detail.html")
    if path is None:
        return [], {}
    html = path.read_text(encoding="utf-8", errors="replace")
    source_url = job.get("source_url") or job.get("detail_final_url")
    artifacts = extract_detail_artifacts(item_dir, html, job.get("item_id"), job.get("auction_date"), source_url=str(source_url or ""))
    candidates = extract_area_candidates_from_text(html, source_type="detail_html", source_path=str(path))
    for rel_key in ("notice_text_path", "desc_text_path", "detail_text_path"):
        rel_path = artifacts.get(rel_key)
        if rel_path:
            candidate_path = item_dir / str(rel_path)
            if candidate_path.exists():
                source_type = rel_key.replace("_path", "")
                text = candidate_path.read_text(encoding="utf-8", errors="replace")
                candidates.extend(extract_area_candidates_from_text(text, source_type=source_type, source_path=str(candidate_path)))
    return candidates, artifacts


def _extract_candidates_from_job_paths(job: dict[str, Any]) -> list[dict[str, Any]]:
    paths = [
        job.get("description_data_path"),
        job.get("selected_json_path"),
    ]
    return extract_area_candidates_from_paths(path for path in paths if path)


def select_best_candidate(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    valid = [candidate for candidate in candidates if has_positive_area(candidate.get("area_sqm"))]
    if not valid:
        return None
    return sorted(
        valid,
        key=lambda item: (
            float(item.get("confidence") or 0),
            1 if item.get("source_type") in {"notice_text", "detail_html", "local_text"} else 0,
        ),
        reverse=True,
    )[0]


def build_area_patch(
    *,
    area_sqm: float,
    transaction_price: float | None,
    selected_candidate: dict[str, Any],
    final_payload: dict[str, Any],
    artifacts: dict[str, Any],
    item_dir: Path,
) -> dict[str, Any]:
    unit_price = round(transaction_price / area_sqm, 2) if transaction_price and area_sqm > 0 else 0
    property_section = dict(as_dict(final_payload.get("property")))
    property_section.update(
        {
            "area_sqm": area_sqm,
            "gross_area_sqm": area_sqm,
            "unit_price": unit_price,
            "area_followup_source": selected_candidate.get("source_type"),
            "area_followup_evidence": selected_candidate.get("evidence"),
        }
    )
    archive_section = dict(as_dict(final_payload.get("archive")))
    legal_section = dict(as_dict(final_payload.get("legal_context")))
    if artifacts:
        archive_section.update(
            {
                "detail_text_path": artifacts.get("detail_text_path", archive_section.get("detail_text_path", "")),
                "notice_text_path": artifacts.get("notice_text_path", archive_section.get("notice_text_path", "")),
                "desc_text_path": artifacts.get("desc_text_path", archive_section.get("desc_text_path", "")),
                "attachment_manifest_path": artifacts.get("attachment_manifest_path", archive_section.get("attachment_manifest_path", "")),
                "image_manifest_path": artifacts.get("image_manifest_path", archive_section.get("image_manifest_path", "")),
            }
        )
        if artifacts.get("announcement_attachment_urls"):
            legal_section["announcement_attachment_urls"] = artifacts.get("announcement_attachment_urls")
        if artifacts.get("appraisal_report_urls"):
            legal_section["appraisal_report_urls"] = artifacts.get("appraisal_report_urls")
    return {
        "建筑面积": area_sqm,
        "产权建筑面积": area_sqm,
        "单价": unit_price,
        "area_sqm": area_sqm,
        "gross_area_sqm": area_sqm,
        "unit_price": unit_price,
        "area_followup_source": selected_candidate.get("source_type"),
        "area_followup_evidence": selected_candidate.get("evidence"),
        "property": property_section,
        "archive": archive_section,
        "legal_context": legal_section,
        "attachment_manifest_path": _relative_artifact_path(item_dir / str(artifacts.get("attachment_manifest_path")), item_dir)
        if artifacts.get("attachment_manifest_path")
        else archive_section.get("attachment_manifest_path", ""),
    }


def infer_final_path_from_patch_path(patch_path: Path) -> Path:
    return patch_path.parent / "final.json"


def apply_patch_payload(final_payload: dict[str, Any], patch_result: dict[str, Any]) -> dict[str, Any]:
    patch = as_dict(patch_result.get("patch"))
    selected = as_dict(patch_result.get("selected_candidate"))
    merged = deep_merge(final_payload, patch)
    if selected.get("source_type"):
        merged["area_followup_source"] = selected.get("source_type")
    if selected.get("evidence"):
        merged["area_followup_evidence"] = selected.get("evidence")
    merged["area_followup_applied"] = True
    merged["area_followup_item_id"] = patch_result.get("item_id")
    sync_collection_record(merged)
    area = patch.get("建筑面积") or patch.get("area_sqm")
    gross_area = patch.get("产权建筑面积") or patch.get("gross_area_sqm") or area
    unit_price = patch.get("单价") or patch.get("unit_price")
    if area not in (None, ""):
        merged["建筑面积"] = area
        merged["area_sqm"] = area
        merged.setdefault("property", {})["area_sqm"] = area
    if gross_area not in (None, ""):
        merged["产权建筑面积"] = gross_area
        merged["gross_area_sqm"] = gross_area
        merged.setdefault("property", {})["gross_area_sqm"] = gross_area
    if unit_price not in (None, ""):
        merged["单价"] = unit_price
        merged["unit_price"] = unit_price
        merged.setdefault("property", {})["unit_price"] = unit_price
    return merged


def build_area_result_payload(patch_result: dict[str, Any]) -> dict[str, Any]:
    patch = as_dict(patch_result.get("patch"))
    selected = as_dict(patch_result.get("selected_candidate"))
    payload = {
        "id": str(patch_result.get("item_id") or ""),
        "建筑面积": patch.get("建筑面积") or patch.get("area_sqm"),
        "产权建筑面积": patch.get("产权建筑面积") or patch.get("gross_area_sqm") or patch.get("area_sqm"),
        "单价": patch.get("单价") or patch.get("unit_price"),
        "area_sqm": patch.get("area_sqm") or patch.get("建筑面积"),
        "gross_area_sqm": patch.get("gross_area_sqm") or patch.get("产权建筑面积") or patch.get("area_sqm"),
        "unit_price": patch.get("unit_price") or patch.get("单价"),
        "property": dict(as_dict(patch.get("property"))),
        "archive": dict(as_dict(patch.get("archive"))),
        "legal_context": dict(as_dict(patch.get("legal_context"))),
        "source_type": selected.get("source_type") or patch.get("area_followup_source") or "area_followup",
        "evidence_source": selected.get("evidence") or patch.get("area_followup_evidence") or "",
        "source": "area_followup_runner",
        "area_followup_patch_path": patch_result.get("patch_path") or "",
        "area_followup_source": selected.get("source_type") or patch.get("area_followup_source") or "",
        "area_followup_evidence": selected.get("evidence") or patch.get("area_followup_evidence") or "",
    }
    payload["property"].update(
        {
            "area_sqm": payload["建筑面积"],
            "gross_area_sqm": payload["产权建筑面积"],
            "unit_price": payload["单价"],
            "area_followup_source": payload["area_followup_source"],
            "area_followup_evidence": payload["area_followup_evidence"],
        }
    )
    return payload


def push_area_result(
    patch_result: dict[str, Any],
    *,
    api_url: str,
    session: Any | None = None,
    timeout: float = 30,
) -> dict[str, Any]:
    http = session or requests.Session()
    payload = build_area_result_payload(patch_result)
    response = http.post(api_url, json=payload, timeout=timeout)
    if hasattr(response, "raise_for_status"):
        response.raise_for_status()
    body: Any
    if hasattr(response, "json"):
        try:
            body = response.json()
        except Exception:
            body = None
    else:
        body = None
    return {"status": "ok", "response": body}


def apply_patch_file(patch_path: str | Path, *, final_path: str | Path | None = None) -> dict[str, Any]:
    patch_path = Path(patch_path)
    patch_result = load_json(patch_path)
    if not isinstance(patch_result, dict):
        raise RuntimeError(f"patch must be a JSON object: {patch_path}")
    if patch_result.get("status") != "resolved":
        return {"status": "skipped", "reason": "patch_not_resolved", "patch_path": str(patch_path)}
    final_path = Path(final_path) if final_path is not None else infer_final_path_from_patch_path(patch_path)
    final_payload = load_json(final_path)
    if not isinstance(final_payload, dict):
        raise RuntimeError(f"final must be a JSON object: {final_path}")
    backup_path = final_path.with_suffix(final_path.suffix + ".area-followup.bak")
    backup_path.write_text(json.dumps(final_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    updated = apply_patch_payload(final_payload, patch_result)
    write_json(final_path, updated)
    return {
        "status": "applied",
        "patch_path": str(patch_path),
        "final_path": str(final_path),
        "backup_path": str(backup_path),
        "item_id": patch_result.get("item_id"),
        "area_sqm": updated.get("建筑面积"),
        "unit_price": updated.get("单价"),
    }


def resolve_job(
    job: dict[str, Any],
    *,
    artifact_root: str | Path | None = None,
    write_patch: bool = True,
    http_session: Any | None = None,
) -> dict[str, Any]:
    item_dir = _job_item_dir(job, artifact_root)
    final_payload = _load_final_payload(job, item_dir)
    candidates: list[dict[str, Any]] = []
    html_candidates, artifacts = _extract_candidates_from_detail_html(job, item_dir)
    candidates.extend(html_candidates)
    candidates.extend(_extract_candidates_from_job_paths(job))
    fetched_notices: list[dict[str, Any]] = []
    if http_session is not None:
        notice_job = dict(job)
        if artifacts:
            notice_job["artifacts"] = artifacts
        notice_candidates, fetched_notices = fetch_notice_detail_candidates(notice_job, item_dir=item_dir, http_session=http_session)
        candidates.extend(notice_candidates)
    selected = select_best_candidate(candidates)
    result: dict[str, Any] = {
        "item_id": str(job.get("item_id") or ""),
        "status": "unresolved",
        "candidate_count": len(candidates),
        "selected_candidate": selected,
        "candidates": candidates,
        "artifacts": artifacts,
        "fetched_notice_count": len(fetched_notices),
        "fetched_notices": fetched_notices,
        "patch": {},
        "patch_path": None,
    }
    if selected is None:
        result["reason"] = "no_area_candidate_found"
        if write_patch:
            write_json(item_dir / "area_followup_unresolved.json", result)
        return result

    area = round(float(selected["area_sqm"]), 2)
    transaction_price = _transaction_price(job, final_payload)
    patch = build_area_patch(
        area_sqm=area,
        transaction_price=transaction_price,
        selected_candidate=selected,
        final_payload=final_payload,
        artifacts=artifacts,
        item_dir=item_dir,
    )
    result["status"] = "resolved"
    result["patch"] = patch
    if write_patch:
        patch_path = item_dir / "area_followup_patch.json"
        write_json(patch_path, result)
        result["patch_path"] = str(patch_path)
    return result


def build_http_session_from_cdp(cdp_endpoint: str) -> requests.Session:
    from tools import browserless_seed_probe

    cookies = browserless_seed_probe.export_cdp_cookies(cdp_endpoint)
    session = browserless_seed_probe.build_session_from_playwright_cookies(cookies)
    session.trust_env = False
    session.proxies = {"http": None, "https": None}
    return session


def run_queue(
    queue_path: str | Path,
    *,
    output_dir: str | Path | None = None,
    limit: int | None = None,
    http_session: Any | None = None,
) -> dict[str, Any]:
    queue_path = Path(queue_path)
    queue = load_json(queue_path)
    if not isinstance(queue, dict):
        raise RuntimeError(f"queue must be a JSON object: {queue_path}")
    jobs = [job for job in queue.get("jobs", []) if isinstance(job, dict)]
    if limit is not None:
        jobs = jobs[:limit]
    artifact_root = Path(output_dir) if output_dir is not None else queue_path.parent
    results = [resolve_job(job, artifact_root=artifact_root, write_patch=True, http_session=http_session) for job in jobs]
    summary = {
        "queue_path": str(queue_path),
        "processed_jobs": len(results),
        "resolved_jobs": sum(1 for result in results if result.get("status") == "resolved"),
        "unresolved_jobs": sum(1 for result in results if result.get("status") != "resolved"),
        "results": results,
    }
    write_json(artifact_root / "area_followup_result.json", summary)
    return summary


def apply_resolved_patches(output_dir: str | Path, *, limit: int | None = None) -> dict[str, Any]:
    root = Path(output_dir)
    patch_paths = sorted(root.glob("*/area_followup_patch.json"))
    if limit is not None:
        patch_paths = patch_paths[:limit]
    results = [apply_patch_file(path) for path in patch_paths]
    summary = {
        "output_dir": str(root),
        "patch_count": len(patch_paths),
        "applied_count": sum(1 for result in results if result.get("status") == "applied"),
        "skipped_count": sum(1 for result in results if result.get("status") == "skipped"),
        "results": results,
    }
    write_json(root / "area_followup_apply_result.json", summary)
    return summary


def push_resolved_patches(
    output_dir: str | Path,
    *,
    api_url: str,
    limit: int | None = None,
    session: Any | None = None,
) -> dict[str, Any]:
    root = Path(output_dir)
    patch_paths = sorted(root.glob("*/area_followup_patch.json"))
    if limit is not None:
        patch_paths = patch_paths[:limit]
    results = []
    http = session or requests.Session()
    for path in patch_paths:
        patch_result = load_json(path)
        if not isinstance(patch_result, dict) or patch_result.get("status") != "resolved":
            results.append({"status": "skipped", "reason": "patch_not_resolved", "patch_path": str(path)})
            continue
        patch_result.setdefault("patch_path", str(path))
        try:
            pushed = push_area_result(patch_result, api_url=api_url, session=http)
            results.append({"status": "pushed", "patch_path": str(path), "item_id": patch_result.get("item_id"), "response": pushed.get("response")})
        except Exception as exc:
            results.append({"status": "failed", "patch_path": str(path), "item_id": patch_result.get("item_id"), "error": repr(exc)})
    summary = {
        "output_dir": str(root),
        "api_url": api_url,
        "patch_count": len(patch_paths),
        "pushed_count": sum(1 for result in results if result.get("status") == "pushed"),
        "failed_count": sum(1 for result in results if result.get("status") == "failed"),
        "skipped_count": sum(1 for result in results if result.get("status") == "skipped"),
        "results": results,
    }
    write_json(root / "area_followup_push_result.json", summary)
    return summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve area-missing jobs produced by live_batch_smoke.py.")
    parser.add_argument("--queue", type=Path, default=Path("output/live_batch_smoke/area_followup_queue.json"))
    parser.add_argument("--output-dir", type=Path, default=None, help="Artifact root. Defaults to queue parent.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--cdp-endpoint", default=None, help="Optional Chrome CDP endpoint. When set, fetch notice_detail pages with logged-in cookies.")
    parser.add_argument("--apply-patches", action="store_true", help="Apply resolved area_followup_patch.json files into each item final.json.")
    parser.add_argument("--push-area-result", default=None, help="POST resolved patches to this area_result API URL.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.apply_patches:
        root = args.output_dir or args.queue.parent
        summary = apply_resolved_patches(root, limit=args.limit)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0
    if args.push_area_result:
        root = args.output_dir or args.queue.parent
        summary = push_resolved_patches(root, api_url=args.push_area_result, limit=args.limit)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if summary["failed_count"] == 0 else 2
    http_session = build_http_session_from_cdp(args.cdp_endpoint) if args.cdp_endpoint else None
    summary = run_queue(args.queue, output_dir=args.output_dir, limit=args.limit, http_session=http_session)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["unresolved_jobs"] == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
