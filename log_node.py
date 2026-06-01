"""Log generation node that sends LOG messages to the block producer."""

from __future__ import annotations

import argparse
import json
import socket
import time
from typing import Any

from config import (
    AUTH_TOKEN,
    BLOCK_PRODUCER_HOST,
    BLOCK_PRODUCER_PORT,
    SOCKET_TIMEOUT_SECONDS,
)


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
        raise ValueError("empty response")
    return json.loads(raw_message.decode("utf-8"))


def send_json(connection: socket.socket, message: dict[str, Any]) -> None:
    data = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
    connection.sendall(data)


def send_log(node_id: str, message: str) -> dict[str, Any]:
    """Send one LOG message to the block producer."""
    log_message = {
        "type": "LOG",
        "node_id": node_id,
        "message": message,
        "token": AUTH_TOKEN,
    }
    with socket.create_connection(
        (BLOCK_PRODUCER_HOST, BLOCK_PRODUCER_PORT),
        timeout=SOCKET_TIMEOUT_SECONDS,
    ) as client_socket:
        send_json(client_socket, log_message)
        return receive_json(client_socket)


def run_log_node(node_id: str, count: int, interval: float) -> None:
    for sequence in range(1, count + 1):
        message = f"STATUS=NORMAL ACTION=BOOT SEQ={sequence}"
        try:
            response = send_log(node_id, message)
            print(f"Sent log {sequence}/{count}: {response}")
        except OSError as exc:
            print(f"Failed to send log {sequence}/{count}: {exc}")

        if sequence < count:
            time.sleep(interval)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send LOG messages.")
    parser.add_argument("node_id", help="Log node ID, for example NODE-01.")
    parser.add_argument("--count", type=int, default=1, help="Number of logs to send.")
    parser.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="Seconds to wait between log messages.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_log_node(args.node_id, args.count, args.interval)
