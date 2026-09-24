"""Deliver durable controller receipts without replaying stale commands."""

import json
import logging
import os
from pathlib import Path
from urllib.error import HTTPError
from uuid import uuid4


def deliver_receipt(client, journal: Path) -> None:
    receipt = json.loads(journal.read_text(encoding="utf-8"))
    outcome = "delivered"
    try:
        client.post("result", receipt)
    except HTTPError as error:
        # Only a stale claim is terminal. Authentication and transient failures
        # retain the pending receipt until delivery can be retried safely.
        if error.code != 409:
            raise
        outcome = "stale"
        logging.getLogger(__name__).warning("Controller receipt rejected as stale (HTTP 409)")
    archive = journal.parent / "receipts"
    archive.mkdir(parents=True, exist_ok=True)
    os.replace(journal, archive / f"{journal.stem}-{outcome}-{uuid4().hex}.json")
