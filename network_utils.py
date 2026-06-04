"""Length-prefixed JSON messaging helpers for TCP sockets."""

from __future__ import annotations

import json
import socket
import struct
from typing import Any


MAX_MESSAGE_SIZE = 10 * 1024 * 1024
LENGTH_HEADER_SIZE = 4


def recv_exact(sock: socket.socket, num_bytes: int) -> bytes:
    """Receive exactly num_bytes or raise if the connection closes early."""
    if num_bytes < 0:
        raise ValueError("num_bytes must not be negative")

    chunks: list[bytes] = []
    bytes_received = 0
    while bytes_received < num_bytes:
        chunk = sock.recv(num_bytes - bytes_received)
        if not chunk:
            raise ConnectionError(
                f"connection closed after {bytes_received} of {num_bytes} bytes"
            )
        chunks.append(chunk)
        bytes_received += len(chunk)
    return b"".join(chunks)


def send_json(sock: socket.socket, message: dict[str, Any]) -> None:
    """Send one JSON object with a 4-byte big-endian length prefix."""
    payload = json.dumps(message, separators=(",", ":")).encode("utf-8")
    if len(payload) > MAX_MESSAGE_SIZE:
        raise ValueError(
            f"message length {len(payload)} exceeds maximum {MAX_MESSAGE_SIZE}"
        )
    header = struct.pack("!I", len(payload))
    sock.sendall(header + payload)


def recv_json(sock: socket.socket) -> dict[str, Any]:
    """Receive and decode one length-prefixed JSON object."""
    header = recv_exact(sock, LENGTH_HEADER_SIZE)
    message_length = struct.unpack("!I", header)[0]
    if message_length > MAX_MESSAGE_SIZE:
        raise ValueError(
            f"invalid message length {message_length}; "
            f"maximum is {MAX_MESSAGE_SIZE}"
        )

    payload = recv_exact(sock, message_length)
    message = json.loads(payload.decode("utf-8"))
    if not isinstance(message, dict):
        raise ValueError("JSON message must be an object")
    return message
