"""TCP block producer that turns LOG messages into replicated blocks."""

from __future__ import annotations

import socket
from typing import Any

from blockchain import add_commit_proof, create_block, get_latest_hash
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
from network_utils import recv_json, send_json


producer_chain: list[dict[str, Any]] = []


def create_block_from_log(log_message: dict[str, Any]) -> dict[str, Any]:
    """Create a candidate block from a valid LOG message."""
    log_data = {
        "node_id": log_message["node_id"],
        "message": log_message["message"],
    }
    block = create_block(
        index=len(producer_chain),
        log_data=log_data,
        previous_hash=get_latest_hash(producer_chain),
    )
    return block


def propose_block_to_validator(
    validator_id: str,
    block: dict[str, Any],
) -> dict[str, Any] | None:
    """Propose a candidate block and return a validated ACCEPT ACK."""
    validator = VALIDATORS[validator_id]
    outbound_message = {
        "type": "PROPOSE_BLOCK",
        "block": block,
        "token": SECRET_TOKEN,
    }

    try:
        with socket.create_connection(
            (validator["host"], validator["port"]),
            timeout=SOCKET_TIMEOUT_SECONDS,
        ) as client_socket:
            send_json(client_socket, outbound_message)
            response = recv_json(client_socket)
    except (OSError, ValueError, ConnectionError) as exc:
        print(
            f"[Producer] Failed to propose Block #{block['index']} "
            f"to Validator {validator_id}: {exc}"
        )
        return None

    if not isinstance(response, dict):
        print(
            f"[Producer] Validator {validator_id} returned an invalid proposal response"
        )
        return None

    valid_ack = (
        response.get("type") == "ACK"
        and response.get("validator_id") == validator_id
        and response.get("block_index") == block["index"]
        and response.get("block_hash") == block["current_hash"]
        and response.get("status") == "ACCEPT"
    )
    if valid_ack:
        print(f"[Producer] Validator {validator_id} ACKed Block #{block['index']}")
        return response

    reason = response.get("reason", "invalid or rejected ACK")
    print(
        f"[Producer] Validator {validator_id} rejected Block #{block['index']}: "
        f"{reason}"
    )
    return None


def send_commit_to_validator(validator_id: str, block: dict[str, Any]) -> bool:
    """Send a quorum-committed block to one validator."""
    validator = VALIDATORS[validator_id]
    message = {"type": "COMMIT_BLOCK", "block": block, "token": SECRET_TOKEN}
    try:
        with socket.create_connection(
            (validator["host"], validator["port"]),
            timeout=SOCKET_TIMEOUT_SECONDS,
        ) as client_socket:
            send_json(client_socket, message)
            response = recv_json(client_socket)
    except (OSError, ValueError, ConnectionError) as exc:
        print(
            f"[Producer] Failed to commit Block #{block['index']} "
            f"to Validator {validator_id}: {exc}"
        )
        return False

    if not isinstance(response, dict):
        print(f"[Producer] Validator {validator_id} returned an invalid commit response")
        return False

    if response.get("status") == "OK":
        return True
    print(
        f"[Producer] Validator {validator_id} failed to save Block #{block['index']}: "
        f"{response.get('reason', 'unknown error')}"
    )
    return False


def commit_candidate(block: dict[str, Any]) -> bool:
    """Commit a candidate after collecting a 2-of-3 validator quorum."""
    acks = []
    for validator_id in VALIDATOR_IDS:
        ack = propose_block_to_validator(validator_id, block)
        if ack is not None:
            acks.append(ack)

    if len(acks) < 2:
        print(
            f"[Producer] Block #{block['index']} failed to reach quorum. "
            "Commit aborted."
        )
        return False

    print(f"[Producer] Block #{block['index']} reached quorum with {len(acks)} ACKs")
    add_commit_proof(block, acks, quorum_size=2)
    producer_chain.append(block)
    for validator_id in VALIDATOR_IDS:
        send_commit_to_validator(validator_id, block)
    print(f"[Producer] Committed Block #{block['index']}")
    return True


def handle_log_connection(
    connection: socket.socket,
    address: tuple[str, int],
) -> None:
    """Handle one LOG message from a log node."""
    try:
        message = recv_json(connection)

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
        if not commit_candidate(block):
            send_json(
                connection,
                {
                    "status": "ERROR",
                    "reason": "quorum not reached; commit aborted",
                    "block_index": block["index"],
                },
            )
            return

        send_json(
            connection,
            {
                "status": "OK",
                "block_index": block["index"],
                "current_hash": block["current_hash"],
            },
        )
    except (ConnectionError, UnicodeError, ValueError) as exc:
        print(f"[Network] Failed to receive JSON message: {exc}")
        print("[Producer] Invalid message from client. Closing connection.")
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
