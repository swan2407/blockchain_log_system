"""JSON-backed blockchain utilities for validator nodes."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, TypedDict

from config import GENESIS_PREVIOUS_HASH, ensure_data_dir
from crypto_utils import calculate_hash


REQUIRED_BLOCK_FIELDS = {
    "index",
    "timestamp",
    "log_data",
    "previous_hash",
    "current_hash",
}


class ChainLoadError(ValueError):
    """Raised when an existing validator chain file cannot be loaded safely."""


class AppendResult(TypedDict):
    """Structured result from an idempotent append attempt."""

    success: bool
    action: str
    reason: str


def append_result(success: bool, action: str, reason: str) -> AppendResult:
    """Build a consistent idempotent append result."""
    return {"success": success, "action": action, "reason": reason}


def calculate_block_hash(block: dict[str, Any]) -> str:
    """Calculate a block hash without including current_hash."""
    hash_payload = {
        "index": block["index"],
        "timestamp": block["timestamp"],
        "log_data": block["log_data"],
        "previous_hash": block["previous_hash"],
    }
    return calculate_hash(hash_payload)


def create_block(index: int, log_data: Any, previous_hash: str) -> dict[str, Any]:
    """Create a block containing log data and a SHA-256 chain hash."""
    block = {
        "index": index,
        "timestamp": time.time(),
        "log_data": log_data,
        "previous_hash": previous_hash,
    }
    block["current_hash"] = calculate_block_hash(block)
    return block


def add_commit_proof(
    block: dict[str, Any],
    acks: list[dict[str, Any]],
    quorum_size: int = 2,
) -> dict[str, Any]:
    """Attach normalized validator acknowledgements to a committed block."""
    block["commit_proof"] = {
        "quorum": quorum_size,
        "acks": [
            {
                "validator_id": ack.get("validator_id"),
                "block_index": ack.get("block_index"),
                "block_hash": ack.get("block_hash"),
            }
            for ack in acks
        ],
    }
    return block


def validate_commit_proof(
    block: dict[str, Any],
    quorum_size: int = 2,
) -> tuple[bool, list[str]]:
    """Verify that a block contains a valid unique-validator quorum proof."""
    errors: list[str] = []
    proof = block.get("commit_proof") if isinstance(block, dict) else None
    if not isinstance(proof, dict):
        return False, ["commit_proof is missing or invalid"]

    proof_quorum = proof.get("quorum")
    if not isinstance(proof_quorum, int) or proof_quorum < quorum_size:
        errors.append(f"commit_proof.quorum must be at least {quorum_size}")

    acks = proof.get("acks")
    if not isinstance(acks, list):
        return False, errors + ["commit_proof.acks must be a list"]
    if len(acks) < quorum_size:
        errors.append(f"commit_proof must contain at least {quorum_size} ACKs")
    if isinstance(proof_quorum, int) and len(acks) < proof_quorum:
        errors.append("commit_proof contains fewer ACKs than its declared quorum")

    validator_ids: set[str] = set()
    for position, ack in enumerate(acks):
        if not isinstance(ack, dict):
            errors.append(f"commit_proof ACK at position {position} is invalid")
            continue

        validator_id = ack.get("validator_id")
        if not isinstance(validator_id, str) or not validator_id:
            errors.append(f"commit_proof ACK at position {position} has invalid validator_id")
        elif validator_id in validator_ids:
            errors.append(f"commit_proof contains duplicate validator_id {validator_id}")
        else:
            validator_ids.add(validator_id)

        if ack.get("block_index") != block.get("index"):
            errors.append(
                f"commit_proof ACK from {validator_id or '?'} has block_index mismatch"
            )
        if ack.get("block_hash") != block.get("current_hash"):
            errors.append(
                f"commit_proof ACK from {validator_id or '?'} has block_hash mismatch"
            )

    return len(errors) == 0, errors


def has_valid_commit_proof(block: dict[str, Any], quorum_size: int = 2) -> bool:
    """Return whether a block has a valid quorum commit proof."""
    is_valid, _errors = validate_commit_proof(block, quorum_size)
    return is_valid


def load_chain(chain_file: str | Path) -> list[dict[str, Any]]:
    """Load a chain, treating missing and empty files as empty chains."""
    ensure_data_dir()
    path = Path(chain_file)

    if not path.exists():
        return []

    try:
        with path.open("r", encoding="utf-8") as file:
            contents = file.read()
        if not contents.strip():
            return []
        chain = json.loads(contents)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        message = f"Unable to load chain file {path}: {exc}"
        print(f"[Storage] Warning: {message}")
        raise ChainLoadError(message) from exc

    if not isinstance(chain, list):
        message = f"Invalid chain file format in {path}: expected a JSON list"
        print(f"[Storage] Warning: {message}")
        raise ChainLoadError(message)

    return chain


def save_chain(chain_file: str | Path, chain: list[dict[str, Any]]) -> None:
    """Atomically persist a validator chain as readable JSON."""
    ensure_data_dir()
    path = Path(chain_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = Path(f"{path}.tmp")

    try:
        with tmp_path.open("w", encoding="utf-8") as file:
            json.dump(chain, file, indent=2, ensure_ascii=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def append_block(chain_file: str | Path, log_data: Any) -> dict[str, Any]:
    """Append a new log block to a validator chain file and return it."""
    chain = load_chain(chain_file)
    previous_hash = (
        chain[-1]["current_hash"] if chain else GENESIS_PREVIOUS_HASH
    )
    block = create_block(
        index=len(chain),
        log_data=log_data,
        previous_hash=previous_hash,
    )
    chain.append(block)
    save_chain(chain_file, chain)
    return block


def get_latest_hash(chain: list[dict[str, Any]]) -> str:
    """Return the current hash at the chain tip, or the genesis hash."""
    return chain[-1]["current_hash"] if chain else GENESIS_PREVIOUS_HASH


def get_latest_index(chain: list[dict[str, Any]]) -> int:
    """Return the latest block index, or -1 for an empty chain."""
    return chain[-1]["index"] if chain else -1


def get_blocks_after_index(
    chain: list[dict[str, Any]],
    latest_index: int,
) -> list[dict[str, Any]]:
    """Return blocks whose index is greater than latest_index."""
    return [
        block
        for block in chain
        if isinstance(block, dict)
        and isinstance(block.get("index"), int)
        and block["index"] > latest_index
    ]


def find_block_by_index(
    chain: list[dict[str, Any]],
    index: int,
) -> dict[str, Any] | None:
    """Return the block with the requested index, if present."""
    for block in chain:
        if isinstance(block, dict) and block.get("index") == index:
            return block
    return None


def validate_next_block(
    chain: list[dict[str, Any]],
    block: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Verify that block is the next valid block for chain."""
    previous_block = chain[-1] if chain else None
    return verify_block(block, previous_block)


def append_block_idempotent(
    chain: list[dict[str, Any]],
    block: dict[str, Any],
) -> AppendResult:
    """Append a block unless it is already present with the same hash."""
    if not isinstance(block, dict):
        return append_result(False, "invalid", "Received block is not an object.")

    block_index = block.get("index")
    received_hash = block.get("current_hash")
    if not isinstance(block_index, int):
        return append_result(
            False, "invalid", "Received block index is missing or invalid."
        )

    existing_block = find_block_by_index(chain, block_index)
    if existing_block is not None:
        existing_hash = existing_block.get("current_hash")
        if existing_hash == received_hash:
            return append_result(
                True,
                "skipped",
                f"Block #{block_index} already exists with same hash. Skipping.",
            )
        return append_result(
            False,
            "conflict",
            (
                f"Local conflict at Block #{block_index}: existing hash differs "
                "from received hash."
            ),
        )

    expected_index = get_latest_index(chain) + 1
    if block_index > expected_index:
        return append_result(
            False,
            "gap",
            f"Gap detected: received Block #{block_index} but expected #{expected_index}.",
        )
    if block_index < expected_index:
        return append_result(
            False,
            "conflict",
            (
                f"Local conflict at Block #{block_index}: no matching local block "
                "exists for an old index."
            ),
        )

    is_valid, errors = validate_next_block(chain, block)
    if not is_valid:
        return append_result(False, "invalid", "; ".join(errors))

    chain.append(block)
    return append_result(True, "appended", f"Block #{block_index} appended.")


def append_blocks_idempotent(
    chain: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
) -> tuple[bool, list[AppendResult]]:
    """Append blocks idempotently and stop at the first unsafe block."""
    results: list[AppendResult] = []
    for block in blocks:
        result = append_block_idempotent(chain, block)
        results.append(result)
        if not result["success"]:
            return False, results
    return True, results


def verify_block_detailed(
    block: dict[str, Any],
    previous_block: dict[str, Any] | None,
) -> tuple[bool, list[dict[str, Any]]]:
    """Verify one block against its previous block."""
    errors: list[dict[str, Any]] = []

    if not isinstance(block, dict):
        return False, [
            {
                "block_index": None,
                "reason": "block format error",
                "message": "Block is not an object.",
            }
        ]

    missing_fields = REQUIRED_BLOCK_FIELDS.difference(block)
    if missing_fields:
        field_list = ", ".join(sorted(missing_fields))
        return False, [
            {
                "block_index": block.get("index"),
                "reason": "block format error",
                "message": f"Block is missing: {field_list}.",
            }
        ]

    expected_index = 0 if previous_block is None else previous_block["index"] + 1
    if block["index"] != expected_index:
        errors.append(
            {
                "block_index": block["index"],
                "reason": "index mismatch",
                "message": (
                    f"Block has index {block['index']}; "
                    f"expected {expected_index}."
                ),
            }
        )

    expected_previous_hash = (
        GENESIS_PREVIOUS_HASH
        if previous_block is None
        else previous_block["current_hash"]
    )
    if block["previous_hash"] != expected_previous_hash:
        errors.append(
            {
                "block_index": block["index"],
                "reason": "previous_hash mismatch",
                "message": (
                    f"Block previous_hash is {block['previous_hash']}; "
                    f"expected {expected_previous_hash}."
                ),
            }
        )

    recalculated_hash = calculate_block_hash(block)
    if block["current_hash"] != recalculated_hash:
        errors.append(
            {
                "block_index": block["index"],
                "reason": "hash mismatch",
                "message": (
                    "Block current_hash does not match the recalculated hash. "
                    "The block data may have been tampered with."
                ),
            }
        )

    return len(errors) == 0, errors


def verify_block(
    block: dict[str, Any],
    previous_block: dict[str, Any] | None,
) -> tuple[bool, list[str]]:
    """Verify one block and return human-readable error messages."""
    is_valid, details = verify_block_detailed(block, previous_block)
    return is_valid, [detail["message"] for detail in details]


def verify_chain_detailed(
    chain: list[dict[str, Any]],
) -> tuple[bool, list[dict[str, Any]]]:
    """Verify block hashes, links, indexes, and tampering evidence."""
    errors: list[dict[str, Any]] = []

    for position, block in enumerate(chain):
        previous_block = None if position == 0 else chain[position - 1]
        is_valid, block_errors = verify_block_detailed(block, previous_block)
        if not is_valid:
            for error in block_errors:
                errors.append({"position": position, **error})

    return len(errors) == 0, errors


def verify_chain(chain: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Verify a chain and return human-readable error messages."""
    is_valid, details = verify_chain_detailed(chain)
    errors = []
    for detail in details:
        block_index = detail["block_index"]
        index_text = (
            "unknown index" if block_index is None else f"index {block_index}"
        )
        errors.append(
            f"Block at position {detail['position']} ({index_text}): "
            f"{detail['reason']}: {detail['message']}"
        )
    return is_valid, errors


def verify_chain_file(chain_file: str | Path) -> tuple[bool, list[str]]:
    """Load and verify a validator chain file."""
    return verify_chain(load_chain(chain_file))
