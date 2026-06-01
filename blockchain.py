"""JSON-backed blockchain utilities for validator nodes."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import GENESIS_PREVIOUS_HASH, ensure_data_dir
from crypto_utils import calculate_block_hash


REQUIRED_BLOCK_FIELDS = {
    "index",
    "timestamp",
    "log_data",
    "previous_hash",
    "current_hash",
}


def create_block(index: int, log_data: Any, previous_hash: str) -> dict[str, Any]:
    """Create a block containing log data and a SHA-256 chain hash."""
    timestamp = datetime.now(timezone.utc).isoformat()
    current_hash = calculate_block_hash(
        index=index,
        timestamp=timestamp,
        log_data=log_data,
        previous_hash=previous_hash,
    )
    return {
        "index": index,
        "timestamp": timestamp,
        "log_data": log_data,
        "previous_hash": previous_hash,
        "current_hash": current_hash,
    }


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


def verify_chain(chain: list[dict[str, Any]]) -> tuple[bool, list[str]]:
    """Verify block hashes, links, indexes, and tampering evidence."""
    errors: list[str] = []

    for position, block in enumerate(chain):
        if not isinstance(block, dict):
            errors.append(f"Block at position {position} is not an object.")
            continue

        missing_fields = REQUIRED_BLOCK_FIELDS.difference(block)
        if missing_fields:
            field_list = ", ".join(sorted(missing_fields))
            errors.append(
                f"Block at position {position} is missing: {field_list}."
            )
            continue

        expected_index = position
        if block["index"] != expected_index:
            errors.append(
                f"Block at position {position} has index {block['index']}; "
                f"expected {expected_index}."
            )

        expected_previous_hash = (
            GENESIS_PREVIOUS_HASH
            if position == 0
            else chain[position - 1].get("current_hash")
        )
        if block["previous_hash"] != expected_previous_hash:
            errors.append(
                f"Block {block['index']} has previous_hash "
                f"{block['previous_hash']}; expected {expected_previous_hash}."
            )

        recalculated_hash = calculate_block_hash(
            index=block["index"],
            timestamp=block["timestamp"],
            log_data=block["log_data"],
            previous_hash=block["previous_hash"],
        )
        if block["current_hash"] != recalculated_hash:
            errors.append(
                f"Block {block['index']} current_hash does not match the "
                "recalculated hash. The block data may have been tampered with."
            )

    return len(errors) == 0, errors


def verify_chain_file(chain_file: str | Path) -> tuple[bool, list[str]]:
    """Load and verify a validator chain file."""
    return verify_chain(load_chain(chain_file))
