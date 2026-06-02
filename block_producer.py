"""TCP block producer that turns LOG messages into replicated blocks."""

from __future__ import annotations

import json
import socket
from typing import Any

from blockchain import create_block, get_latest_hash
from config import (
    BLOCK_PRODUCER_HOST,
    BLOCK_PRODUCER_PORT,
    SECRET_TOKEN,
    SOCKET_BACKLOG,
    SOCKET_TIMEOUT_SECONDS,
    VALIDATOR_IDS,
    VALIDATORS,
)
from crypto_utils import verify_plain_token


producer_chain: list[dict[str, Any]] = []


def receive_json(connection: socket.socket) -> dict[str, Any]:
    """Read one newline-delimited JSON message from a TCP connection."""
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
    """Send one newline-delimited JSON message."""
    encoded = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
    connection.sendall(encoded)


def create_block_from_log(log_message: dict[str, Any]) -> dict[str, Any]:
    """Create and remember the next block from a valid LOG message."""
    log_data = {
        "node_id": log_message["node_id"],
        "message": log_message["message"],
    }
    block = create_block(
        index=len(producer_chain),
        log_data=log_data,
        previous_hash=get_latest_hash(producer_chain),
    )
    producer_chain.append(block)
    return block


def send_block_to_validator(validator_id: str, block: dict[str, Any]) -> bool:
    """Send a block to one validator without affecting other validators."""
    validator = VALIDATORS[validator_id]
    outbound_message = {
        "type": "BLOCK",
        "block": block,
        "token": SECRET_TOKEN,
    }

    try:
        with socket.create_connection(
            (validator["host"], validator["port"]),
            timeout=SOCKET_TIMEOUT_SECONDS,
        ) as client_socket:
            send_json(client_socket, outbound_message)
            response = receive_json(client_socket)
    except OSError as exc:
        print(
            f"[Producer] Failed to send Block #{block['index']} "
            f"to Validator {validator_id}: {exc}"
        )
        return False

    if response.get("status") == "OK":
        print(f"[Producer] Sent Block #{block['index']} to Validator {validator_id}")
        return True

    reason = response.get("reason", "validator rejected block")
    print(
        f"[Producer] Failed to send Block #{block['index']} "
        f"to Validator {validator_id}: {reason}"
    )
    return False


def broadcast_block(block: dict[str, Any]) -> None:
    """Broadcast a block to validators A, B, and C."""
    for validator_id in VALIDATOR_IDS:
        send_block_to_validator(validator_id, block)


def handle_log_connection(
    connection: socket.socket,
    address: tuple[str, int],
) -> None:
    """Handle one LOG message from a log node."""
    try:
        message = receive_json(connection)

        if not verify_plain_token(message.get("token", "")):
            print(f"[Producer] Invalid token from {address[0]}:{address[1]}")
            send_json(connection, {"status": "ERROR", "reason": "invalid token"})
            return

        if message.get("type") != "LOG":
            send_json(connection, {"status": "ERROR", "reason": "invalid LOG type"})
            return

        if not message.get("node_id") or not message.get("message"):
            send_json(connection, {"status": "ERROR", "reason": "missing log fields"})
            return

        print(f"[Producer] Received log from {message['node_id']}")
        block = create_block_from_log(message)
        print(f"[Producer] Created Block #{block['index']}")
        broadcast_block(block)

        send_json(
            connection,
            {
                "status": "OK",
                "block_index": block["index"],
                "current_hash": block["current_hash"],
            },
        )
    except Exception as exc:
        print(f"[Producer] Error while handling {address[0]}:{address[1]}: {exc}")
        try:
            send_json(connection, {"status": "ERROR", "reason": str(exc)})
        except OSError:
            pass


def run_block_producer() -> None:
    """Run the block producer TCP server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((BLOCK_PRODUCER_HOST, BLOCK_PRODUCER_PORT))
        server_socket.listen(SOCKET_BACKLOG)
        print(f"[Producer] Listening on {BLOCK_PRODUCER_HOST}:{BLOCK_PRODUCER_PORT}")

        while True:
            connection, address = server_socket.accept()
            with connection:
                handle_log_connection(connection, address)


if __name__ == "__main__":
    run_block_producer()
