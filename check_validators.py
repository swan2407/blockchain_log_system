"""Verify validator chains and compare their latest replicated state."""

from __future__ import annotations

from typing import Any

from blockchain import (
    get_latest_hash,
    get_latest_index,
    load_chain,
    verify_chain_detailed,
)
from config import VALIDATOR_CHAIN_FILES, VALIDATOR_IDS, ensure_data_dir


def print_validator_status(
    validator_id: str,
    chain: list[dict[str, Any]],
    is_valid: bool,
    errors: list[dict[str, Any]],
) -> None:
    """Print chain validity and latest state for one validator."""
    print(f"Validator {validator_id}:")
    print(f"  Chain valid: {is_valid}")
    print(f"  Block count: {len(chain)}")
    print(f"  Latest index: {get_latest_index(chain)}")
    print(f"  Latest hash: {get_latest_hash(chain)}")
    for error in errors:
        block_index = error["block_index"]
        index_text = (
            "unknown block index"
            if block_index is None
            else f"block index {block_index}"
        )
        print(
            f"  Error: Validator {validator_id}, {index_text}, "
            f"position {error['position']}: {error['reason']}. "
            f"{error['message']}"
        )


def explain_difference(
    block_counts: dict[str, int],
    latest_hashes: dict[str, str],
    validities: dict[str, bool],
) -> None:
    """Explain which validators differ from the replicated state."""
    reference_id = VALIDATOR_IDS[0]
    reference_count = block_counts[reference_id]
    reference_hash = latest_hashes[reference_id]

    for validator_id in VALIDATOR_IDS:
        if not validities[validator_id]:
            print(f"- Validator {validator_id} has an invalid chain.")
        if block_counts[validator_id] != reference_count:
            print(
                f"- Validator {validator_id} block count differs: "
                f"{block_counts[validator_id]} != {reference_count}"
            )
        if latest_hashes[validator_id] != reference_hash:
            print(
                f"- Validator {validator_id} latest hash differs: "
                f"{latest_hashes[validator_id]} != {reference_hash}"
            )


def check_validators() -> bool:
    """Verify all validator files and report synchronization status."""
    ensure_data_dir()

    chains: dict[str, list[dict[str, Any]]] = {}
    validities: dict[str, bool] = {}
    block_counts: dict[str, int] = {}
    latest_hashes: dict[str, str] = {}

    print("Validator chain status:")
    for validator_id in VALIDATOR_IDS:
        chain = load_chain(VALIDATOR_CHAIN_FILES[validator_id])
        is_valid, errors = verify_chain_detailed(chain)

        chains[validator_id] = chain
        validities[validator_id] = is_valid
        block_counts[validator_id] = len(chain)
        latest_hashes[validator_id] = get_latest_hash(chain)

        print_validator_status(validator_id, chain, is_valid, errors)

    all_valid = all(validities.values())
    same_block_count = len(set(block_counts.values())) == 1
    same_latest_hash = len(set(latest_hashes.values())) == 1
    synchronized = all_valid and same_block_count and same_latest_hash

    print()
    if synchronized:
        print("Result: All validators are synchronized.")
    else:
        print("Result: Validators are not synchronized.")
        explain_difference(block_counts, latest_hashes, validities)

    return synchronized


if __name__ == "__main__":
    raise SystemExit(0 if check_validators() else 1)
