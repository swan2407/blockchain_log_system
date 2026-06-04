"""Focused tests for HMAC-SHA256 message authentication."""

from __future__ import annotations

import time

from crypto_utils import (
    attach_signature,
    canonical_message,
    sign_message,
    verify_message_signature,
)


def test_sign_and_verify() -> None:
    message = attach_signature({"type": "LOG", "message": "ok"}, "NODE-01")
    assert verify_message_signature(message) == (True, "ok")


def test_modified_message_fails() -> None:
    message = attach_signature({"type": "LOG", "message": "original"}, "NODE-01")
    message["message"] = "modified"
    assert verify_message_signature(message) == (False, "invalid signature")


def test_missing_signature_fails() -> None:
    message = {"type": "LOG", "timestamp": time.time(), "sender_id": "NODE-01"}
    assert verify_message_signature(message) == (False, "missing signature")


def test_old_timestamp_fails() -> None:
    message = attach_signature(
        {"type": "LOG", "timestamp": time.time() - 301},
        "NODE-01",
    )
    assert verify_message_signature(message) == (
        False,
        "message timestamp is too old",
    )


def test_canonical_order_is_stable() -> None:
    first = {"type": "LOG", "message": "ok", "timestamp": 1, "sender_id": "NODE-01"}
    second = {"sender_id": "NODE-01", "timestamp": 1, "message": "ok", "type": "LOG"}
    assert canonical_message(first) == canonical_message(second)
    assert sign_message(first) == sign_message(second)


if __name__ == "__main__":
    test_sign_and_verify()
    test_modified_message_fails()
    test_missing_signature_fails()
    test_old_timestamp_fails()
    test_canonical_order_is_stable()
    print("crypto_utils tests passed")
