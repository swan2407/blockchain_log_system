"""TCP validator node that stores accepted blocks in a local chain file."""

from __future__ import annotations

import argparse
import json
import socket
from typing import Any

from blockchain import load_chain, save_chain, verify_block
from config import (
    SOCKET_BACKLOG,
    VALIDATOR_CHAIN_FILES,
    VALIDATOR_IDS,
    VALIDATORS,
    ensure_data_dir,
)
from crypto_utils import verify_plain_token


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
    """Send one newline-delimited JSON response."""
    encoded = json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"
    connection.sendall(encoded)


def append_valid_block(
    validator_id: str,
    block: dict[str, Any],
) -> tuple[bool, str]:
    """Verify an incoming block against the local tip, then append it."""
    chain_file = VALIDATOR_CHAIN_FILES[validator_id]
    chain = load_chain(chain_file)
    previous_block = chain[-1] if chain else None

    is_valid, errors = verify_block(block, previous_block)
    if not is_valid:
        return False, "; ".join(errors)

    chain.append(block)
    save_chain(chain_file, chain)
    return True, "accepted and saved"


def handle_connection(
    validator_id: str,
    connection: socket.socket,
    address: tuple[str, int],
) -> None:
    """Handle one BLOCK message from the block producer."""
    prefix = f"[Validator {validator_id}]"
    try:
        message = receive_json(connection)

        if not verify_plain_token(message.get("token", "")):
            print(f"{prefix} Invalid token from {address[0]}:{address[1]}")
            send_json(connection, {"status": "ERROR", "reason": "invalid token"})
            return

        if message.get("type") != "BLOCK" or not isinstance(
            message.get("block"), dict
        ):
            print(f"{prefix} Invalid message rejected")
            send_json(connection, {"status": "ERROR", "reason": "invalid BLOCK"})
            return

        block = message["block"]
        block_index = block.get("index", "?")
        print(f"{prefix} Received Block #{block_index}")

        accepted, reason = append_valid_block(validator_id, block)
        if accepted:
            print(f"{prefix} Block #{block_index} accepted and saved")
            send_json(connection, {"status": "OK", "reason": reason})
        else:
            print(f"{prefix} Invalid block rejected: {reason}")
            send_json(connection, {"status": "ERROR", "reason": reason})
    except Exception as exc:
        print(f"{prefix} Error while handling {address[0]}:{address[1]}: {exc}")
        try:
            send_json(connection, {"status": "ERROR", "reason": str(exc)})
        except OSError:
            pass


def run_validator(validator_id: str) -> None:
    """Run a validator TCP server for validator A, B, or C."""
    ensure_data_dir()
    chain_file = VALIDATOR_CHAIN_FILES[validator_id]
    if not chain_file.exists():
        save_chain(chain_file, [])

    host = VALIDATORS[validator_id]["host"]
    port = VALIDATORS[validator_id]["port"]
    prefix = f"[Validator {validator_id}]"

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_socket.bind((host, port))
        server_socket.listen(SOCKET_BACKLOG)
        print(f"{prefix} Listening on {host}:{port}")
        print(f"{prefix} Chain file: {chain_file}")

        while True:
            connection, address = server_socket.accept()
            with connection:
                handle_connection(validator_id, connection, address)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a validator node.")
    parser.add_argument("validator_id", choices=VALIDATOR_IDS)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_validator(args.validator_id)
