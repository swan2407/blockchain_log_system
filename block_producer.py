"""TCP block producer that receives logs and broadcasts blocks to validators."""

from __future__ import annotations

import json
import socket
from typing import Any

from blockchain import create_block
from config import (
    AUTH_TOKEN,
    BLOCK_PRODUCER_HOST,
    BLOCK_PRODUCER_PORT,
    GENESIS_PREVIOUS_HASH,
    SOCKET_BACKLOG,
    SOCKET_TIMEOUT_SECONDS,
    VALIDATOR_HOST,
    VALIDATOR_IDS,
    VALIDATOR_PORTS,
)


producer_chain: list[dict[str, Any]] = []


def receive_json(connection: socket.socket) -> dict[str, Any]:
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
    data = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
    connection.sendall(data)


def build_block(log_message: dict[str, Any]) -> dict[str, Any]:
    """Convert a LOG message into the next hash-chained block."""
    previous_hash = (
        producer_chain[-1]["current_hash"]
        if producer_chain
        else GENESIS_PREVIOUS_HASH
    )
    log_data = {
        "node_id": log_message["node_id"],
        "message": log_message["message"],
    }
    block = create_block(
        index=len(producer_chain),
        log_data=log_data,
        previous_hash=previous_hash,
    )
    producer_chain.append(block)
    return block


def send_block_to_validator(
    validator_id: str,
    block: dict[str, Any],
) -> tuple[bool, str]:
    """Send a block to one validator and return whether it was accepted."""
    port = VALIDATOR_PORTS[validator_id]
    outbound_message = {
        "type": "BLOCK",
        "block": block,
        "token": AUTH_TOKEN,
    }

    try:
        with socket.create_connection(
            (VALIDATOR_HOST, port),
            timeout=SOCKET_TIMEOUT_SECONDS,
        ) as client_socket:
            send_json(client_socket, outbound_message)
            response = receive_json(client_socket)
    except OSError as exc:
        return False, f"connection failed: {exc}"

    if response.get("status") == "OK":
        return True, response.get("reason", "accepted")
    return False, response.get("reason", "rejected")


def broadcast_block(block: dict[str, Any]) -> None:
    """Send a block to every validator, continuing if one is unavailable."""
    for validator_id in VALIDATOR_IDS:
        accepted, reason = send_block_to_validator(validator_id, block)
        status = "sent" if accepted else "failed"
        print(f"Validator {validator_id}: {status} ({reason})")


def handle_log_connection(
    connection: socket.socket,
    address: tuple[str, int],
) -> None:
    """Receive one LOG message, create one block, and broadcast it."""
    try:
        message = receive_json(connection)
        if message.get("token") != AUTH_TOKEN:
            send_json(connection, {"status": "ERROR", "reason": "invalid token"})
            return

        if message.get("type") != "LOG":
            send_json(connection, {"status": "ERROR", "reason": "invalid LOG type"})
            return

        if not message.get("node_id") or not message.get("message"):
            send_json(connection, {"status": "ERROR", "reason": "missing log fields"})
            return

        block = build_block(message)
        print(
            f"LOG from {address[0]}:{address[1]} -> block {block['index']} "
            f"{block['current_hash']}"
        )
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
        send_json(connection, {"status": "ERROR", "reason": str(exc)})
        print(f"{address[0]}:{address[1]} -> ERROR: {exc}")


def run_block_producer() -> None:
    """Run the block producer TCP server."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((BLOCK_PRODUCER_HOST, BLOCK_PRODUCER_PORT))
        server_socket.listen(SOCKET_BACKLOG)
        print(
            "Block producer listening on "
            f"{BLOCK_PRODUCER_HOST}:{BLOCK_PRODUCER_PORT}"
        )

        while True:
            connection, address = server_socket.accept()
            with connection:
                handle_log_connection(connection, address)


if __name__ == "__main__":
    run_block_producer()
