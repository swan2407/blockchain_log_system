"""Cryptographic helper functions for block hashing."""

import hashlib
import json
from typing import Any


def _canonical_block_payload(
    index: int,
    timestamp: str,
    log_data: Any,
    previous_hash: str,
) -> bytes:
    """Return a deterministic byte representation of hash-relevant fields."""
    payload = {
        "index": index,
        "timestamp": timestamp,
        "log_data": log_data,
        "previous_hash": previous_hash,
    }
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def calculate_block_hash(
    index: int,
    timestamp: str,
    log_data: Any,
    previous_hash: str,
) -> str:
    """Calculate a SHA-256 block hash without including current_hash."""
    block_bytes = _canonical_block_payload(
        index=index,
        timestamp=timestamp,
        log_data=log_data,
        previous_hash=previous_hash,
    )
    return hashlib.sha256(block_bytes).hexdigest()
