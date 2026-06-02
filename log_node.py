"""Log generation node that sends JSON LOG messages to the block producer."""

from __future__ import annotations

import argparse
import json
import socket
import time
from typing import Any

from config import (
    BLOCK_PRODUCER_HOST,
    BLOCK_PRODUCER_PORT,
    SECRET_TOKEN,
    SOCKET_TIMEOUT_SECONDS,
)


LOG_MESSAGES = [
    "STATUS=NORMAL ACTION=BOOT",
    "STATUS=NORMAL ACTION=HEARTBEAT",
    "STATUS=WARNING ACTION=HIGH_CPU",
    "STATUS=NORMAL ACTION=CHECK",
]


def receive_json(connection: socket.socket) -> dict[str, Any]:
    """Read one newline-delimited JSON response."""
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
    """Send one newline-delimited JSON message."""
    encoded = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
    connection.sendall(encoded)


def send_log(node_id: str, log_message: str) -> dict[str, Any]:
    """Send one LOG message to the block producer."""
    message = {
        "type": "LOG",
        "node_id": node_id,
        "message": log_message,
        "token": SECRET_TOKEN,
    }

    with socket.create_connection(
        (BLOCK_PRODUCER_HOST, BLOCK_PRODUCER_PORT),
        timeout=SOCKET_TIMEOUT_SECONDS,
    ) as client_socket:
        send_json(client_socket, message)
        return receive_json(client_socket)


def run_log_node(node_id: str, count: int, interval: float) -> None:
    """Send a sequence of log messages to the block producer."""
    for sequence in range(1, count + 1):
        log_message = LOG_MESSAGES[(sequence - 1) % len(LOG_MESSAGES)]
        try:
            response = send_log(node_id, log_message)
            if response.get("status") == "OK":
                print(f"[LogNode {node_id}] Sent log {sequence}/{count}")
            else:
                print(
                    f"[LogNode {node_id}] Log {sequence}/{count} rejected: "
                    f"{response.get('reason')}"
                )
        except OSError as exc:
            print(f"[LogNode {node_id}] Failed to send log {sequence}/{count}: {exc}")

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
