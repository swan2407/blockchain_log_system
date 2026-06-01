"""TCP validator node that stores blocks in its own blockchain file."""

from __future__ import annotations

import argparse
import json
import socket
from typing import Any

from blockchain import calculate_block_hash, load_chain, save_chain, verify_chain
from config import (
    AUTH_TOKEN,
    SOCKET_BACKLOG,
    VALIDATOR_CHAIN_FILES,
    VALIDATOR_HOST,
    VALIDATOR_IDS,
    VALIDATOR_PORTS,
    ensure_data_dir,
)


def receive_json(connection: socket.socket) -> dict[str, Any]:
    """Read one newline-delimited JSON message from a socket."""
    chunks: list[bytes] = []
    while True:
        chunk = connection.recv(4096)
        if not chunk:
            break
        chunks.append(chunk)
        if b"\n" in chunk:
            break

    raw_message = b"".join(chunks).split(b"\n", 1)[0]
    if not raw_message:
        raise ValueError("empty message")
    return json.loads(raw_message.decode("utf-8"))


def send_json(connection: socket.socket, message: dict[str, Any]) -> None:
    """Send one newline-delimited JSON response."""
    data = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
    connection.sendall(data)


def validate_incoming_block(
    validator_id: str,
    block: dict[str, Any],
) -> tuple[bool, str]:
    """Validate an incoming block against this validator's local chain."""
    chain_file = VALIDATOR_CHAIN_FILES[validator_id]
    chain = load_chain(chain_file)
    expected_index = len(chain)
    expected_previous_hash = (
        chain[-1]["current_hash"] if chain else "0" * 64
    )

    if block.get("index") != expected_index:
        return False, f"expected index {expected_index}, got {block.get('index')}"

    if block.get("previous_hash") != expected_previous_hash:
        return False, "previous_hash does not match local chain tip"

    recalculated_hash = calculate_block_hash(block)
    if block.get("current_hash") != recalculated_hash:
        return False, "current_hash does not match block contents"

    test_chain = chain + [block]
    is_valid, errors = verify_chain(test_chain)
    if not is_valid:
        return False, "; ".join(errors)

    save_chain(chain_file, test_chain)
    return True, "block accepted"


def handle_connection(
    validator_id: str,
    connection: socket.socket,
    address: tuple[str, int],
) -> None:
    """Handle one block submission from the block producer."""
    try:
        message = receive_json(connection)
        if message.get("token") != AUTH_TOKEN:
            send_json(connection, {"status": "ERROR", "reason": "invalid token"})
            return

        if message.get("type") != "BLOCK" or not isinstance(
            message.get("block"), dict
        ):
            send_json(connection, {"status": "ERROR", "reason": "invalid BLOCK"})
            return

        accepted, reason = validate_incoming_block(
            validator_id=validator_id,
            block=message["block"],
        )
        status = "OK" if accepted else "ERROR"
        send_json(connection, {"status": status, "validator": validator_id, "reason": reason})
        print(f"{address[0]}:{address[1]} -> {status}: {reason}")
    except Exception as exc:
        send_json(connection, {"status": "ERROR", "reason": str(exc)})
        print(f"{address[0]}:{address[1]} -> ERROR: {exc}")


def run_validator(validator_id: str) -> None:
    """Run one validator TCP server."""
    ensure_data_dir()
    chain_file = VALIDATOR_CHAIN_FILES[validator_id]
    if not chain_file.exists():
        save_chain(chain_file, [])

    port = VALIDATOR_PORTS[validator_id]
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((VALIDATOR_HOST, port))
        server_socket.listen(SOCKET_BACKLOG)
        print(f"Validator {validator_id} listening on {VALIDATOR_HOST}:{port}")
        print(f"Chain file: {chain_file}")

        while True:
            connection, address = server_socket.accept()
            with connection:
                handle_connection(validator_id, connection, address)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a validator node.")
    parser.add_argument(
        "validator_id",
        choices=VALIDATOR_IDS,
        help="Validator ID to run: A, B, or C.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_validator(args.validator_id)
