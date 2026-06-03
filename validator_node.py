"""TCP validator node that stores accepted blocks in a local chain file."""

from __future__ import annotations

import argparse
import json
import socket
from typing import Any

from blockchain import (
    append_block_idempotent,
    append_blocks_idempotent,
    get_blocks_after_index,
    get_latest_index,
    load_chain,
    save_chain,
    verify_chain_detailed,
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
    """Verify an incoming block against the local chain, then append it."""
    chain_file = VALIDATOR_CHAIN_FILES[validator_id]
    chain = load_chain(chain_file)

    accepted, results = append_blocks_idempotent(chain, [block])
    action, reason = results[-1]
    if accepted:
        if action == "appended":
            save_chain(chain_file, chain)
        return True, reason
    return False, reason


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
    chain_is_valid, _chain_errors = verify_chain_detailed(chain)
    if not chain_is_valid:
        print(
            f"{prefix} Refusing sync request from Validator {requester_id}: "
            "local chain is invalid"
        )
        send_json(
            connection,
            {
                "type": "SYNC_RESPONSE",
                "from_validator": validator_id,
                "error": "LOCAL_CHAIN_INVALID",
                "blocks": [],
                "token": SECRET_TOKEN,
            },
        )
        return

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


def validate_sync_response(
    validator_id: str,
    peer_id: str,
    response: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Validate a SYNC_RESPONSE envelope and return its block list."""
    prefix = f"[Validator {validator_id}]"

    if not verify_plain_token(response.get("token", "")):
        print(f"{prefix} Invalid sync token from Validator {peer_id}")
        return None

    if response.get("type") != "SYNC_RESPONSE":
        print(f"{prefix} Invalid sync response from Validator {peer_id}")
        return None

    if response.get("error") == "LOCAL_CHAIN_INVALID":
        print(
            f"{prefix} Peer {peer_id} reported LOCAL_CHAIN_INVALID. "
            "Ignoring peer for sync."
        )
        return None

    blocks = response.get("blocks")
    if not isinstance(blocks, list):
        print(f"{prefix} Invalid block list from Validator {peer_id}")
        return None

    print(f"{prefix} Peer {peer_id} responded with {len(blocks)} missing blocks")
    return blocks


def collect_sync_responses(
    validator_id: str,
    latest_index: int,
) -> dict[str, list[dict[str, Any]]]:
    """Request missing blocks from all available peer validators."""
    peer_blocks: dict[str, list[dict[str, Any]]] = {}

    for peer_id in VALIDATOR_IDS:
        if peer_id == validator_id:
            continue

        response = request_sync_response(validator_id, peer_id, latest_index)
        if response is None:
            continue

        blocks = validate_sync_response(validator_id, peer_id, response)
        if blocks is None:
            continue

        peer_blocks[peer_id] = blocks

    return peer_blocks


def select_consistent_blocks(
    validator_id: str,
    peer_blocks: dict[str, list[dict[str, Any]]],
) -> list[dict[str, Any]] | None:
    """Compare peer block hashes and return a safe ordered block list."""
    prefix = f"[Validator {validator_id}]"
    peer_count = len(peer_blocks)
    if peer_count == 0:
        return None

    if peer_count == 1:
        print(
            f"{prefix} Warning: only one sync peer responded. "
            "Proceeding after local verification."
        )
        blocks = next(iter(peer_blocks.values()))
        return sorted(
            blocks,
            key=lambda block: block.get("index", -1)
            if isinstance(block, dict)
            else -1,
        )

    blocks_by_index: dict[int, dict[str, list[str]]] = {}
    chosen_blocks: dict[int, dict[str, Any]] = {}

    for peer_id, blocks in peer_blocks.items():
        for block in blocks:
            if not isinstance(block, dict):
                print(f"{prefix} Invalid block object from Validator {peer_id}")
                print(f"{prefix} Sync aborted due to invalid peer response")
                return None

            block_index = block.get("index")
            block_hash = block.get("current_hash")
            if not isinstance(block_index, int) or not isinstance(block_hash, str):
                print(f"{prefix} Invalid block metadata from Validator {peer_id}")
                print(f"{prefix} Sync aborted due to invalid peer response")
                return None

            blocks_by_index.setdefault(block_index, {}).setdefault(
                block_hash, []
            ).append(peer_id)
            chosen_blocks.setdefault(block_index, block)

    for block_index in sorted(blocks_by_index):
        hashes = blocks_by_index[block_index]
        if len(hashes) > 1:
            print(f"{prefix} Conflict detected at Block #{block_index}")
            for block_hash, peer_ids in hashes.items():
                for peer_id in peer_ids:
                    print(f"{prefix} Peer {peer_id} hash: {block_hash}")
            print(f"{prefix} Sync aborted due to conflicting peer responses")
            return None

        peer_ids = next(iter(hashes.values()))
        if len(peer_ids) < 2:
            print(
                f"{prefix} Insufficient quorum at Block #{block_index}: "
                f"only Validator {peer_ids[0]} returned this block"
            )
            print(f"{prefix} Sync aborted due to insufficient peer agreement")
            return None

    return [chosen_blocks[index] for index in sorted(chosen_blocks)]


def append_synced_blocks(
    validator_id: str,
    blocks: list[dict[str, Any]],
) -> bool:
    """Apply consistent sync blocks with local idempotent verification."""
    chain_file = VALIDATOR_CHAIN_FILES[validator_id]
    working_chain = list(load_chain(chain_file))
    prefix = f"[Validator {validator_id}]"
    actions: list[tuple[str, str, int | str]] = []

    for block in blocks:
        block_index = block.get("index") if isinstance(block, dict) else "?"
        accepted, action, message = append_block_idempotent(working_chain, block)
        actions.append((action, message, block_index))
        if not accepted:
            print(f"{prefix} {message}")
            print(f"{prefix} Sync aborted during local verification")
            return False

    save_chain(chain_file, working_chain)
    for action, message, block_index in actions:
        if action == "appended":
            print(f"{prefix} Synced Block #{block_index}")
        elif action == "skipped":
            print(f"{prefix} {message}")

    return True


def sync_from_peers(validator_id: str) -> None:
    """Synchronize this validator using available peer agreement."""
    chain = load_chain(VALIDATOR_CHAIN_FILES[validator_id])
    latest_index = get_latest_index(chain)
    prefix = f"[Validator {validator_id}]"
    print(f"{prefix} Current latest block: #{latest_index}")

    peer_blocks = collect_sync_responses(validator_id, latest_index)
    if not peer_blocks:
        print(f"{prefix} No sync peer available, continuing as server")
        return

    blocks = select_consistent_blocks(validator_id, peer_blocks)
    if blocks is None:
        return

    print(f"{prefix} Received {len(blocks)} consistent missing blocks")
    if append_synced_blocks(validator_id, blocks):
        print(f"{prefix} Sync completed")


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
