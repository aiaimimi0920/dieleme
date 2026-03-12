import argparse
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional

import requests


DEFAULT_MAX_BATCH_SIZE = 100
DEFAULT_REQUEST_TIMEOUT = 10


@dataclass
class AVMResult:
    item_id: str
    margin_of_safety: Optional[float]
    payload: Dict[str, Any]


class AVMService:
    """Simple AVM service client for one-by-one item evaluation."""

    def __init__(self, base_url: str, timeout: int = DEFAULT_REQUEST_TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def evaluate(self, item_id: str) -> Dict[str, Any]:
        resp = requests.post(
            f"{self.base_url}/api/avm/evaluate",
            json={"item_id": item_id},
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()


def _parse_margin_of_safety(result: Dict[str, Any]) -> Optional[float]:
    value = result.get("margin_of_safety")
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def batch_evaluate_item_ids(
    item_ids: Iterable[str],
    avm_service: AVMService,
    max_batch_size: int = DEFAULT_MAX_BATCH_SIZE,
    logger: Optional[logging.Logger] = None,
) -> List[AVMResult]:
    logger = logger or logging.getLogger(__name__)
    normalized_ids = [str(item_id).strip() for item_id in item_ids if str(item_id).strip()]

    if len(normalized_ids) > max_batch_size:
        raise ValueError(
            f"Batch size exceeded: got {len(normalized_ids)}, max allowed is {max_batch_size}."
        )

    total_start = time.perf_counter()
    logger.info("[AVM] Batch start | size=%d", len(normalized_ids))

    results: List[AVMResult] = []
    for idx, item_id in enumerate(normalized_ids, start=1):
        item_start = time.perf_counter()
        payload = avm_service.evaluate(item_id)
        cost_ms = (time.perf_counter() - item_start) * 1000

        margin = _parse_margin_of_safety(payload)
        logger.info(
            "[AVM] item_id=%s done (%d/%d) | margin_of_safety=%s | cost=%.2fms",
            item_id,
            idx,
            len(normalized_ids),
            margin,
            cost_ms,
        )

        results.append(AVMResult(item_id=item_id, margin_of_safety=margin, payload=payload))

    results.sort(
        key=lambda x: x.margin_of_safety if x.margin_of_safety is not None else float("-inf"),
        reverse=True,
    )

    total_cost_ms = (time.perf_counter() - total_start) * 1000
    logger.info("[AVM] Batch finished | size=%d | cost=%.2fms", len(normalized_ids), total_cost_ms)
    return results


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="输入 item_id 列表，批量调用 AVMService，并按 margin_of_safety 降序输出。"
    )
    parser.add_argument(
        "--item-ids",
        required=True,
        help="item_id 列表，逗号分隔，例如: 1001,1002,1003",
    )
    parser.add_argument(
        "--max-batch-size",
        type=int,
        default=DEFAULT_MAX_BATCH_SIZE,
        help=f"限制批量大小，默认 {DEFAULT_MAX_BATCH_SIZE}",
    )
    parser.add_argument(
        "--avm-service-url",
        default=os.getenv("AVM_SERVICE_URL", "http://127.0.0.1:8001"),
        help="AVMService 地址（默认读取 AVM_SERVICE_URL 或 http://127.0.0.1:8001）",
    )
    return parser.parse_args()


def main() -> None:
    _setup_logging()
    args = _parse_args()

    item_ids = [x.strip() for x in args.item_ids.split(",") if x.strip()]
    service = AVMService(base_url=args.avm_service_url)

    results = batch_evaluate_item_ids(
        item_ids=item_ids,
        avm_service=service,
        max_batch_size=args.max_batch_size,
    )

    print("\n=== Sorted by margin_of_safety (DESC) ===")
    for idx, r in enumerate(results, start=1):
        print(f"{idx}. item_id={r.item_id}, margin_of_safety={r.margin_of_safety}, payload={r.payload}")


if __name__ == "__main__":
    main()
