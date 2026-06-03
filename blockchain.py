"""JSON-backed blockchain utilities for validator nodes."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from config import GENESIS_PREVIOUS_HASH, ensure_data_dir
from crypto_utils import calculate_hash


REQUIRED_BLOCK_FIELDS = {
    "index",
    "timestamp",
    "log_data",
    "previous_hash",
    "current_hash",
}


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


def load_chain(chain_file: str | Path) -> list[dict[str, Any]]:
    """Load a validator chain from disk. Missing files are treated as empty."""
    ensure_data_dir()
    path = Path(chain_file)

    if not path.exists():
        return []

    with path.open("r", encoding="utf-8") as file:
        chain = json.load(file)

    if not isinstance(chain, list):
        raise ValueError(f"Invalid chain file format: {path}")

    return chain


def save_chain(chain_file: str | Path, chain: list[dict[str, Any]]) -> None:
    """Persist a validator chain as readable JSON."""
    ensure_data_dir()
    path = Path(chain_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", encoding="utf-8") as file:
        json.dump(chain, file, indent=2, ensure_ascii=True)
        file.write("\n")


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
) -> tuple[bool, str, str]:
    """Append a block unless it is already present with the same hash."""
    if not isinstance(block, dict):
        return False, "rejected", "Received block is not an object."

    block_index = block.get("index")
    received_hash = block.get("current_hash")
    if not isinstance(block_index, int):
        return False, "rejected", "Received block index is missing or invalid."

    existing_block = find_block_by_index(chain, block_index)
    if existing_block is not None:
        existing_hash = existing_block.get("current_hash")
        if existing_hash == received_hash:
            return (
                True,
                "skipped",
                f"Block #{block_index} already exists with same hash. Skipping.",
            )
        return (
            False,
            "conflict",
            (
                f"Local conflict at Block #{block_index}: existing hash differs "
                "from received hash."
            ),
        )

    expected_index = get_latest_index(chain) + 1
    if block_index > expected_index:
        return (
            False,
            "gap",
            f"Gap detected: received Block #{block_index} but expected #{expected_index}.",
        )
    if block_index < expected_index:
        return (
            False,
            "conflict",
            (
                f"Local conflict at Block #{block_index}: no matching local block "
                "exists for an old index."
            ),
        )

    is_valid, errors = validate_next_block(chain, block)
    if not is_valid:
        return False, "rejected", "; ".join(errors)

    chain.append(block)
    return True, "appended", f"Block #{block_index} appended."


def append_blocks_idempotent(
    chain: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
) -> tuple[bool, list[tuple[str, str]]]:
    """Append blocks idempotently and stop at the first unsafe block."""
    results: list[tuple[str, str]] = []
    for block in blocks:
        accepted, action, message = append_block_idempotent(chain, block)
        results.append((action, message))
        if not accepted:
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
