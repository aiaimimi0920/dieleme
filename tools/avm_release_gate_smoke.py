"""Implementation slice exposed through the original tool facade."""

from __future__ import annotations

from tools.avm_release_gate_context import *


def _request_json(url: str, method: str = "GET", payload: dict[str, Any] | None = None) -> tuple[int, dict[str, Any], float]:
    started = time.perf_counter()
    if method == "POST":
        req = urllib.request.Request(
            url,
            data=json.dumps(payload or {}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
    else:
        req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req) as resp:
        body = json.loads(resp.read().decode("utf-8"))
        elapsed_ms = (time.perf_counter() - started) * 1000
        return resp.status, body, elapsed_ms


def run_api_smoke(data_root: Path, thresholds: GateThresholds, sample_size: int) -> dict[str, Any]:
    if sample_size <= 0:
        return {"request_count": 0, "error_count": 0, "error_rate": 0.0, "p95_ms": 0.0, "p99_ms": 0.0, "pass": True, "skipped": True}

    samples = _find_sample_records(data_root, limit=max(sample_size, 2))
    if not samples:
        return {"pass": False, "reason": "no_samples"}

    smoke_temp = tempfile.TemporaryDirectory()
    smoke_data_root = Path(smoke_temp.name) / "datas"
    smoke_data_root.mkdir(parents=True, exist_ok=True)
    (smoke_data_root / "smoke_samples.json").write_text(
        json.dumps(samples, ensure_ascii=False),
        encoding="utf-8",
    )

    original_service = server_module.AVM_SERVICE
    original_start = server_module.AVM_SERVICE_START_TIME
    server_module.AVM_SERVICE = AVMService(data_dir=str(smoke_data_root))
    server_module.AVM_SERVICE_START_TIME = time.time()

    httpd = server_module.ReusableTCPServer(("127.0.0.1", 0), server_module.DataHandler)
    port = httpd.server_address[1]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    latencies: List[float] = []
    errors = 0
    try:
        for row in samples[:sample_size]:
            item_id = str(row.get("id") or row.get("item_id") or "")
            if not item_id:
                continue
            try:
                _, _, elapsed = _request_json(
                    f"http://127.0.0.1:{port}/api/avm/predict?id={urllib.parse.quote(item_id)}"
                )
                latencies.append(elapsed)
            except Exception:
                errors += 1

        try:
            subject = {
                "city": samples[0].get("城市"),
                "district": samples[0].get("区"),
                "community_name": samples[0].get("所属小区"),
                "area_sqm": 100,
                "housing_type": "住宅",
            }
            _, _, elapsed = _request_json(
                f"http://127.0.0.1:{port}/api/avm/evaluate",
                method="POST",
                payload={"request_id": "gate-smoke", "subject": subject, "auction": {"starting_price": 1000000}},
            )
            latencies.append(elapsed)
        except Exception:
            errors += 1
    finally:
        httpd.shutdown()
        httpd.server_close()
        server_module.AVM_SERVICE = original_service
        server_module.AVM_SERVICE_START_TIME = original_start
        smoke_temp.cleanup()

    if not latencies:
        return {"pass": False, "reason": "no_successful_requests"}

    arr = np.array(latencies, dtype=float)
    error_rate = errors / max(len(latencies) + errors, 1)
    p95 = float(np.quantile(arr, 0.95))
    p99 = float(np.quantile(arr, 0.99))
    return {
        "request_count": len(latencies) + errors,
        "error_count": errors,
        "error_rate": round(error_rate, 6),
        "p95_ms": round(p95, 2),
        "p99_ms": round(p99, 2),
        "pass": (
            error_rate <= thresholds.max_smoke_error_rate
            and p95 <= thresholds.max_smoke_p95_ms
            and p99 <= thresholds.max_smoke_p99_ms
        ),
    }


__all__ = (
    "_request_json",
    "run_api_smoke",
)
