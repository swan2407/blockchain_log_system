"""Cryptographic helpers for block hashing and message authentication."""

import hashlib
import hmac
import json
import time
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


def canonical_message(message: dict[str, Any]) -> str:
    """Return deterministic JSON for a message without its signature."""
    unsigned_message = {
        key: value for key, value in message.items() if key != "signature"
    }
    return json.dumps(unsigned_message, sort_keys=True, separators=(",", ":"))


def sign_message(message: dict[str, Any], secret: str = SECRET_TOKEN) -> str:
    """Return an HMAC-SHA256 signature for a message."""
    return hmac.new(
        secret.encode("utf-8"),
        canonical_message(message).encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def attach_signature(
    message: dict[str, Any],
    sender_id: str,
    secret: str = SECRET_TOKEN,
) -> dict[str, Any]:
    """Return a signed copy of a network message."""
    signed_message = dict(message)
    signed_message["sender_id"] = sender_id
    signed_message.setdefault("timestamp", time.time())
    signed_message["signature"] = sign_message(signed_message, secret)
    return signed_message


def verify_message_signature(
    message: dict[str, Any],
    secret: str = SECRET_TOKEN,
    max_age_seconds: int = 300,
) -> tuple[bool, str]:
    """Verify a message HMAC and reject stale timestamps."""
    if not isinstance(message, dict):
        return False, "message must be an object"

    signature = message.get("signature")
    if not isinstance(signature, str) or not signature:
        return False, "missing signature"

    timestamp = message.get("timestamp")
    if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)):
        return False, "missing or invalid timestamp"

    if time.time() - timestamp > max_age_seconds:
        return False, "message timestamp is too old"

    try:
        expected_signature = sign_message(message, secret)
    except (TypeError, ValueError):
        return False, "message is not valid JSON"

    if not hmac.compare_digest(signature, expected_signature):
        return False, "invalid signature"

    return True, "ok"


def create_token_signature(message: Any) -> str:
    """Create a simple token-based signature for a message."""
    return calculate_hash({"message": message, "token": SECRET_TOKEN})


def verify_token(message: Any, token: str) -> bool:
    """Verify a token signature for a message."""
    return token == create_token_signature(message)


def verify_plain_token(token: str) -> bool:
    """Verify the shared plain-text token used by the current socket protocol."""
    return token == SECRET_TOKEN
