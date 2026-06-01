"""Cryptographic helper functions for block hashing."""

import hashlib
import json
from typing import Any

from config import SECRET_TOKEN


def _canonical_json(data: Any) -> bytes:
    """Return a deterministic byte representation for JSON-compatible data."""
    return json.dumps(
        data,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def calculate_hash(data: Any) -> str:
    """Calculate a SHA-256 hash for JSON-compatible data."""
    return hashlib.sha256(_canonical_json(data)).hexdigest()


def create_token_signature(message: Any) -> str:
    """Create a simple token-based signature for a message."""
    return calculate_hash({"message": message, "token": SECRET_TOKEN})


def verify_token(message: Any, token: str) -> bool:
    """Verify a token signature for a message."""
    return token == create_token_signature(message)


def verify_plain_token(token: str) -> bool:
    """Verify the shared plain-text token used by the current socket protocol."""
    return token == SECRET_TOKEN
