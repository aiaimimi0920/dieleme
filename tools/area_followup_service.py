"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.area_followup_context import *


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


__all__ = (
    "resolve_job",
    "build_http_session_from_cdp",
    "run_queue",
    "apply_resolved_patches",
    "push_resolved_patches",
)
