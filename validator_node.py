"""TCP validator node that stores accepted blocks in a local chain file."""

from __future__ import annotations

import argparse
import socket
from typing import Any

from blockchain import (
    ChainLoadError,
    append_block_idempotent,
    get_blocks_after_index,
    get_latest_index,
    has_valid_commit_proof,
    load_chain,
    save_chain,
    validate_commit_proof,
    validate_next_block,
    verify_chain_detailed,
)
from config import (
    SOCKET_BACKLOG,
    SOCKET_TIMEOUT_SECONDS,
    VALIDATOR_CHAIN_FILES,
    VALIDATOR_IDS,
    VALIDATORS,
    ensure_data_dir,
)
from crypto_utils import attach_signature, verify_message_signature
from network_utils import recv_json, send_json


def validator_sender_id(validator_id: str) -> str:
    """Return the network sender ID for a validator."""
    return f"VALIDATOR_{validator_id}"


def send_validator_message(
    validator_id: str,
    connection: socket.socket,
    message: dict[str, Any],
) -> None:
    """Sign and send one validator message."""
    send_json(connection, attach_signature(message, validator_sender_id(validator_id)))


def ack_message(
    validator_id: str,
    block: dict[str, Any],
    status: str,
    reason: str | None = None,
) -> dict[str, Any]:
    """Build an ACK/NACK response for one proposed block."""
    response = {
        "type": "ACK",
        "validator_id": validator_id,
        "block_index": block.get("index"),
        "block_hash": block.get("current_hash"),
        "status": status,
    }
    if reason:
        response["reason"] = reason
    return response


def handle_propose_block(
    validator_id: str,
    connection: socket.socket,
    message: dict[str, Any],
) -> None:
    """Verify a proposed block without storing it."""
    prefix = f"[Validator {validator_id}]"
    if not isinstance(message.get("block"), dict):
        send_validator_message(
            validator_id,
            connection,
            ack_message(validator_id, {}, "REJECT", "invalid proposed block"),
        )
        return

    block = message["block"]
    block_index = block.get("index", "?")
    chain = load_chain(VALIDATOR_CHAIN_FILES[validator_id])
    is_valid, errors = validate_next_block(chain, block)
    if is_valid:
        print(f"{prefix} ACK Block #{block_index}")
        send_validator_message(
            validator_id,
            connection,
            ack_message(validator_id, block, "ACCEPT"),
        )
        return

    reason = "; ".join(errors)
    print(f"{prefix} NACK Block #{block_index}: {reason}")
    send_validator_message(
        validator_id,
        connection,
        ack_message(validator_id, block, "REJECT", reason),
    )


def handle_commit_block(
    validator_id: str,
    connection: socket.socket,
    message: dict[str, Any],
) -> None:
    """Validate and idempotently store a quorum-committed block."""
    prefix = f"[Validator {validator_id}]"
    block = message.get("block")
    if not isinstance(block, dict):
        send_validator_message(
            validator_id,
            connection,
            {"status": "ERROR", "reason": "invalid committed block"},
        )
        return

    proof_is_valid, proof_errors = validate_commit_proof(block)
    if not proof_is_valid:
        reason = "; ".join(proof_errors)
        print(f"{prefix} Invalid commit proof rejected: {reason}")
        send_validator_message(
            validator_id,
            connection,
            {"status": "ERROR", "reason": reason},
        )
        return

    chain_file = VALIDATOR_CHAIN_FILES[validator_id]
    chain = load_chain(chain_file)
    result = append_block_idempotent(chain, block)
    if result["success"]:
        if result["action"] == "appended":
            save_chain(chain_file, chain)
            print(f"{prefix} Committed Block #{block['index']} saved")
        else:
            print(f"{prefix} {result['reason']}")
        send_validator_message(
            validator_id,
            connection,
            {"status": "OK", "reason": result["reason"]},
        )
    else:
        print(
            f"{prefix} Committed block {result['action']}: {result['reason']}"
        )
        send_validator_message(
            validator_id,
            connection,
            {"status": "ERROR", "reason": result["reason"]},
        )


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
        send_validator_message(
            validator_id,
            connection,
            {"status": "ERROR", "reason": "invalid latest_index"},
        )
        return

    chain = load_chain(VALIDATOR_CHAIN_FILES[validator_id])
    chain_is_valid, _chain_errors = verify_chain_detailed(chain)
    proofs_are_valid = all(has_valid_commit_proof(block) for block in chain)
    if not chain_is_valid or not proofs_are_valid:
        print(
            f"{prefix} Refusing sync request from Validator {requester_id}: "
            "local chain is invalid"
        )
        send_validator_message(
            validator_id,
            connection,
            {
                "type": "SYNC_RESPONSE",
                "from_validator": validator_id,
                "error": "LOCAL_CHAIN_INVALID",
                "blocks": [],
            },
        )
        return

    missing_blocks = get_blocks_after_index(chain, latest_index)
    print(
        f"{prefix} Sync request from Validator {requester_id} "
        f"starting after #{latest_index}: {len(missing_blocks)} block(s)"
    )
    send_validator_message(
        validator_id,
        connection,
        {
            "type": "SYNC_RESPONSE",
            "from_validator": validator_id,
            "blocks": missing_blocks,
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
        message = recv_json(connection)

        is_valid, reason = verify_message_signature(message)
        if not is_valid:
            print(f"{prefix} Rejected request: {reason}")
            send_validator_message(
                validator_id,
                connection,
                {"status": "ERROR", "reason": reason},
            )
            return

        message_type = message.get("type")
        expected_sender = None
        if message_type in {"PROPOSE_BLOCK", "COMMIT_BLOCK", "BLOCK"}:
            expected_sender = "PRODUCER"
        elif message_type == "SYNC_REQUEST":
            from_validator = message.get("from_validator")
            if isinstance(from_validator, str):
                expected_sender = validator_sender_id(from_validator)

        if expected_sender is None or message.get("sender_id") != expected_sender:
            print(f"{prefix} Rejected request: unexpected sender_id")
            send_validator_message(
                validator_id,
                connection,
                {"status": "ERROR", "reason": "unexpected sender_id"},
            )
            return

        if message_type == "PROPOSE_BLOCK":
            handle_propose_block(validator_id, connection, message)
        elif message_type == "COMMIT_BLOCK":
            handle_commit_block(validator_id, connection, message)
        elif message_type == "BLOCK":
            send_validator_message(
                validator_id,
                connection,
                {"status": "ERROR", "reason": "legacy BLOCK rejected; commit proof required"},
            )
        elif message_type == "SYNC_REQUEST":
            handle_sync_request(validator_id, connection, message)
        else:
            print(f"{prefix} Invalid message rejected")
            send_validator_message(
                validator_id,
                connection,
                {"status": "ERROR", "reason": "invalid message"},
            )
    except (ConnectionError, UnicodeError, ValueError) as exc:
        print(f"[Network] Failed to receive JSON message: {exc}")
        print(f"{prefix} Failed to handle request: {exc}")
    except Exception as exc:
        print(f"{prefix} Error while handling {address[0]}:{address[1]}: {exc}")
        try:
            send_validator_message(
                validator_id,
                connection,
                {"status": "ERROR", "reason": str(exc)},
            )
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

    request = attach_signature(
        {
            "type": "SYNC_REQUEST",
            "from_validator": validator_id,
            "latest_index": latest_index,
        },
        validator_sender_id(validator_id),
    )

    try:
        with socket.create_connection(
            (peer["host"], peer["port"]),
            timeout=SOCKET_TIMEOUT_SECONDS,
        ) as client_socket:
            send_json(client_socket, request)
            return recv_json(client_socket)
    except (OSError, ValueError, ConnectionError) as exc:
        print(f"{prefix} Validator {peer_id} unavailable for sync: {exc}")
        return None


def validate_sync_response(
    validator_id: str,
    peer_id: str,
    response: dict[str, Any],
) -> list[dict[str, Any]] | None:
    """Validate a SYNC_RESPONSE envelope and return its block list."""
    prefix = f"[Validator {validator_id}]"

    is_valid, reason = verify_message_signature(response)
    if not is_valid:
        print(f"{prefix} Rejected sync response from Validator {peer_id}: {reason}")
        return None

    if response.get("sender_id") != validator_sender_id(peer_id):
        print(f"{prefix} Invalid sync sender_id from Validator {peer_id}")
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
    actions: list[tuple[dict[str, Any], int | str]] = []

    for block in blocks:
        block_index = block.get("index") if isinstance(block, dict) else "?"
        proof_is_valid, proof_errors = validate_commit_proof(block)
        if not proof_is_valid:
            print(
                f"{prefix} Skipping Block #{block_index}: invalid commit_proof: "
                f"{'; '.join(proof_errors)}"
            )
            print(f"{prefix} Sync aborted during commit proof verification")
            return False
        result = append_block_idempotent(working_chain, block)
        actions.append((result, block_index))
        if not result["success"]:
            print(f"{prefix} {result['action']}: {result['reason']}")
            print(f"{prefix} Sync aborted during local verification")
            return False

    save_chain(chain_file, working_chain)
    for result, block_index in actions:
        if result["action"] == "appended":
            print(f"{prefix} Synced Block #{block_index}")
        elif result["action"] == "skipped":
            print(f"{prefix} {result['reason']}")

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

    try:
        sync_from_peers(validator_id)
    except ChainLoadError as exc:
        print(
            f"[Validator {validator_id}] Refusing to start with unreadable "
            f"local chain: {exc}"
        )
        return

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
