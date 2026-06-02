"""Intentionally tamper with one validator chain file for experiments."""

from __future__ import annotations

import argparse
from typing import Any

from blockchain import load_chain, save_chain
from config import VALIDATOR_CHAIN_FILES, VALIDATOR_IDS


TAMPER_TYPES = ("log", "previous_hash", "current_hash", "delete")


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Modify one validator chain file without recalculating hashes."
    )
    parser.add_argument(
        "validator_id",
        choices=VALIDATOR_IDS,
        help="Validator ID to tamper with.",
    )
    parser.add_argument(
        "block_index",
        type=int,
        help="Block index to tamper with.",
    )
    parser.add_argument(
        "tamper_type",
        choices=TAMPER_TYPES,
        help="Tamper operation to apply.",
    )
    return parser.parse_args()


def find_block_position(
    chain: list[dict[str, Any]],
    block_index: int,
) -> int:
    """Return the list position of a block with the requested index."""
    for position, block in enumerate(chain):
        if block.get("index") == block_index:
            return position
    raise ValueError(f"Block index {block_index} was not found in the chain.")


def tamper_log_data(block: dict[str, Any]) -> str:
    """Modify a block's log_data message without updating current_hash."""
    log_data = block.get("log_data")
    if isinstance(log_data, dict):
        old_value = log_data.get("message")
        if old_value is None:
            log_data["message"] = "TAMPERED_LOG_DATA"
        else:
            log_data["message"] = f"{old_value} [TAMPERED]"
        return (
            "log_data.message changed from "
            f"{old_value!r} to {log_data['message']!r}"
        )

    old_value = log_data
    block["log_data"] = "TAMPERED_LOG_DATA"
    return f"log_data changed from {old_value!r} to {block['log_data']!r}"


def apply_tamper(
    chain: list[dict[str, Any]],
    block_index: int,
    tamper_type: str,
) -> str:
    """Apply the requested tamper operation and return a description."""
    position = find_block_position(chain, block_index)
    block = chain[position]

    if tamper_type == "log":
        detail = tamper_log_data(block)
        return f"Modified block {block_index}: {detail}."

    if tamper_type == "previous_hash":
        old_value = block["previous_hash"]
        block["previous_hash"] = "TAMPERED_PREVIOUS_HASH"
        return (
            f"Modified block {block_index}: previous_hash changed from "
            f"{old_value!r} to {block['previous_hash']!r}."
        )

    if tamper_type == "current_hash":
        old_value = block["current_hash"]
        block["current_hash"] = "TAMPERED_CURRENT_HASH"
        return (
            f"Modified block {block_index}: current_hash changed from "
            f"{old_value!r} to {block['current_hash']!r}."
        )

    if tamper_type == "delete":
        chain.pop(position)
        return f"Deleted block {block_index} from chain position {position}."

    raise ValueError(f"Unsupported tamper type: {tamper_type}")


def main() -> int:
    """Run the tamper experiment command."""
    args = parse_args()
    chain_file = VALIDATOR_CHAIN_FILES[args.validator_id]

    try:
        chain = load_chain(chain_file)
        description = apply_tamper(
            chain,
            args.block_index,
            args.tamper_type,
        )
    except ValueError as exc:
        print(f"Tamper failed: {exc}")
        return 1

    save_chain(chain_file, chain)
    print(f"Validator {args.validator_id} chain file: {chain_file}")
    print(description)
    print("Hashes were not recalculated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
