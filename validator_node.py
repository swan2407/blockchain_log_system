"""TCP validator node that stores accepted blocks in a local chain file."""

from __future__ import annotations

import argparse
import json
import socket
from typing import Any

from blockchain import (
    get_blocks_after_index,
    get_latest_index,
    load_chain,
    save_chain,
    verify_block,
)
from config import (
    SECRET_TOKEN,
    SOCKET_BACKLOG,
    SOCKET_TIMEOUT_SECONDS,
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


def handle_block_message(
    validator_id: str,
    connection: socket.socket,
    message: dict[str, Any],
) -> None:
    """Verify and append one BLOCK message from the block producer."""
    prefix = f"[Validator {validator_id}]"

    if not isinstance(message.get("block"), dict):
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


def handle_sync_request(
    validator_id: str,
    connection: socket.socket,
    message: dict[str, Any],
) -> None:
    """Return blocks after the requester's latest block index."""
    prefix = f"[Validator {validator_id}]"
    latest_index = message.get("latest_index")
    requester_id = message.get("from_validator", "?")

    if not isinstance(latest_index, int):
        send_json(connection, {"status": "ERROR", "reason": "invalid latest_index"})
        return

    chain = load_chain(VALIDATOR_CHAIN_FILES[validator_id])
    missing_blocks = get_blocks_after_index(chain, latest_index)
    print(
        f"{prefix} Sync request from Validator {requester_id} "
        f"starting after #{latest_index}: {len(missing_blocks)} block(s)"
    )
    send_json(
        connection,
        {
            "type": "SYNC_RESPONSE",
            "from_validator": validator_id,
            "blocks": missing_blocks,
            "token": SECRET_TOKEN,
        },
    )


def handle_connection(
    validator_id: str,
    connection: socket.socket,
    address: tuple[str, int],
) -> None:
    """Handle one validator TCP message."""
    prefix = f"[Validator {validator_id}]"
    try:
        message = receive_json(connection)

        if not verify_plain_token(message.get("token", "")):
            print(f"{prefix} Invalid token from {address[0]}:{address[1]}")
            send_json(connection, {"status": "ERROR", "reason": "invalid token"})
            return

        message_type = message.get("type")
        if message_type == "BLOCK":
            handle_block_message(validator_id, connection, message)
        elif message_type == "SYNC_REQUEST":
            handle_sync_request(validator_id, connection, message)
        else:
            print(f"{prefix} Invalid message rejected")
            send_json(connection, {"status": "ERROR", "reason": "invalid message"})
    except Exception as exc:
        print(f"{prefix} Error while handling {address[0]}:{address[1]}: {exc}")
        try:
            send_json(connection, {"status": "ERROR", "reason": str(exc)})
        except OSError:
            pass


def request_sync_response(
    validator_id: str,
    peer_id: str,
    latest_index: int,
) -> dict[str, Any] | None:
    """Request missing blocks from one peer validator."""
    peer = VALIDATORS[peer_id]
    prefix = f"[Validator {validator_id}]"
    print(
        f"{prefix} Requesting sync from Validator {peer_id} "
        f"starting after #{latest_index}"
    )

    request = {
        "type": "SYNC_REQUEST",
        "from_validator": validator_id,
        "latest_index": latest_index,
        "token": SECRET_TOKEN,
    }

    try:
        with socket.create_connection(
            (peer["host"], peer["port"]),
            timeout=SOCKET_TIMEOUT_SECONDS,
        ) as client_socket:
            send_json(client_socket, request)
            return receive_json(client_socket)
    except OSError as exc:
        print(f"{prefix} Validator {peer_id} unavailable for sync: {exc}")
        return None


def append_synced_blocks(
    validator_id: str,
    peer_id: str,
    blocks: list[dict[str, Any]],
) -> bool:
    """Verify missing blocks from a peer and append them to the local chain."""
    chain_file = VALIDATOR_CHAIN_FILES[validator_id]
    chain = load_chain(chain_file)
    existing_indexes = {
        block.get("index") for block in chain if isinstance(block.get("index"), int)
    }
    prefix = f"[Validator {validator_id}]"

    for block in blocks:
        block_index = block.get("index") if isinstance(block, dict) else "?"
        if isinstance(block_index, int) and block_index in existing_indexes:
            print(f"{prefix} Skipping duplicate Block #{block_index}")
            continue

        previous_block = chain[-1] if chain else None
        is_valid, errors = verify_block(block, previous_block)
        if not is_valid:
            print(
                f"{prefix} Rejected sync from Validator {peer_id} at "
                f"Block #{block_index}: {'; '.join(errors)}"
            )
            return False

        chain.append(block)
        existing_indexes.add(block_index)
        save_chain(chain_file, chain)
        print(f"{prefix} Synced Block #{block_index}")

    return True


def sync_from_peers(validator_id: str) -> None:
    """Synchronize this validator from the first available valid peer."""
    chain = load_chain(VALIDATOR_CHAIN_FILES[validator_id])
    latest_index = get_latest_index(chain)
    prefix = f"[Validator {validator_id}]"
    print(f"{prefix} Current latest block: #{latest_index}")

    for peer_id in VALIDATOR_IDS:
        if peer_id == validator_id:
            continue

        response = request_sync_response(validator_id, peer_id, latest_index)
        if response is None:
            continue

        if not verify_plain_token(response.get("token", "")):
            print(f"{prefix} Invalid sync token from Validator {peer_id}")
            continue

        if response.get("type") != "SYNC_RESPONSE":
            print(f"{prefix} Invalid sync response from Validator {peer_id}")
            continue

        blocks = response.get("blocks")
        if not isinstance(blocks, list):
            print(f"{prefix} Invalid block list from Validator {peer_id}")
            continue

        print(
            f"{prefix} Received {len(blocks)} missing blocks "
            f"from Validator {peer_id}"
        )
        if append_synced_blocks(validator_id, peer_id, blocks):
            print(f"{prefix} Sync completed")
            return

    print(f"{prefix} No sync peer available, continuing as server")


def run_validator(validator_id: str) -> None:
    """Run a validator TCP server for validator A, B, or C."""
    ensure_data_dir()
    chain_file = VALIDATOR_CHAIN_FILES[validator_id]
    if not chain_file.exists():
        save_chain(chain_file, [])

    sync_from_peers(validator_id)

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
