"""TCP block producer that turns LOG messages into replicated blocks."""

from __future__ import annotations

import socket
from typing import Any

from blockchain import add_commit_proof, create_block, get_latest_hash
from config import (
    BLOCK_PRODUCER_HOST,
    BLOCK_PRODUCER_PORT,
    SOCKET_BACKLOG,
    SOCKET_TIMEOUT_SECONDS,
    VALIDATOR_IDS,
    VALIDATORS,
)
from crypto_utils import attach_signature, verify_message_signature
from network_utils import recv_json, send_json


producer_chain: list[dict[str, Any]] = []
PRODUCER_ID = "PRODUCER"


def send_producer_message(
    connection: socket.socket,
    message: dict[str, Any],
) -> None:
    """Sign and send one producer message."""
    send_json(connection, attach_signature(message, PRODUCER_ID))


def verify_validator_response(
    response: dict[str, Any],
    validator_id: str,
) -> tuple[bool, str]:
    """Verify a response came from the expected validator."""
    is_valid, reason = verify_message_signature(response)
    if not is_valid:
        return False, reason
    if response.get("sender_id") != f"VALIDATOR_{validator_id}":
        return False, "unexpected sender_id"
    return True, "ok"


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
    outbound_message = attach_signature(
        {"type": "PROPOSE_BLOCK", "block": block},
        PRODUCER_ID,
    )

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

    signature_is_valid, signature_reason = verify_validator_response(
        response,
        validator_id,
    )
    if not signature_is_valid:
        print(
            f"[Producer] Rejected response from Validator {validator_id}: "
            f"{signature_reason}"
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
    message = attach_signature({"type": "COMMIT_BLOCK", "block": block}, PRODUCER_ID)
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

    signature_is_valid, signature_reason = verify_validator_response(
        response,
        validator_id,
    )
    if not signature_is_valid:
        print(
            f"[Producer] Rejected response from Validator {validator_id}: "
            f"{signature_reason}"
        )
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

        is_valid, reason = verify_message_signature(message)
        if not is_valid:
            print(f"[Producer] Rejected message: {reason}")
            send_producer_message(connection, {"status": "ERROR", "reason": reason})
            return

        if message.get("type") != "LOG":
            send_producer_message(
                connection,
                {"status": "ERROR", "reason": "invalid LOG type"},
            )
            return

        if not message.get("node_id") or not message.get("message"):
            send_producer_message(
                connection,
                {"status": "ERROR", "reason": "missing log fields"},
            )
            return

        if message.get("sender_id") != message["node_id"]:
            print("[Producer] Rejected message: sender_id does not match node_id")
            send_producer_message(
                connection,
                {"status": "ERROR", "reason": "sender_id does not match node_id"},
            )
            return

        print(f"[Producer] Received log from {message['node_id']}")
        block = create_block_from_log(message)
        print(f"[Producer] Created Block #{block['index']}")
        if not commit_candidate(block):
            send_producer_message(
                connection,
                {
                    "status": "ERROR",
                    "reason": "quorum not reached; commit aborted",
                    "block_index": block["index"],
                },
            )
            return

        send_producer_message(
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
            send_producer_message(connection, {"status": "ERROR", "reason": str(exc)})
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
