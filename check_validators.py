"""Verify validator chains and report whether validators are synchronized."""

from __future__ import annotations

from typing import Any

from blockchain import load_chain, verify_chain
from config import VALIDATOR_CHAIN_FILES, VALIDATOR_IDS, ensure_data_dir


def latest_hash(chain: list[dict[str, Any]]) -> str | None:
    return chain[-1]["current_hash"] if chain else None


def check_validators() -> bool:
    """Verify all validator files and compare their chain tips."""
    ensure_data_dir()
    chains: dict[str, list[dict[str, Any]]] = {}
    all_valid = True

    print("Validator chain status:")
    for validator_id in VALIDATOR_IDS:
        chain_file = VALIDATOR_CHAIN_FILES[validator_id]
        chain = load_chain(chain_file)
        chains[validator_id] = chain
        is_valid, errors = verify_chain(chain)
        all_valid = all_valid and is_valid

        print(
            f"- Validator {validator_id}: "
            f"blocks={len(chain)}, latest_hash={latest_hash(chain)}"
        )
        if is_valid:
            print("  chain_valid=True")
        else:
            print("  chain_valid=False")
            for error in errors:
                print(f"  error: {error}")

    block_counts = {validator_id: len(chain) for validator_id, chain in chains.items()}
    latest_hashes = {
        validator_id: latest_hash(chain) for validator_id, chain in chains.items()
    }

    counts_match = len(set(block_counts.values())) == 1
    hashes_match = len(set(latest_hashes.values())) == 1

    print()
    print(f"Block counts match: {counts_match}")
    print(f"Latest hashes match: {hashes_match}")

    synchronized = all_valid and counts_match and hashes_match
    if synchronized:
        print("All validators are synchronized.")
    else:
        print("Validators are NOT synchronized.")

    return synchronized


if __name__ == "__main__":
    raise SystemExit(0 if check_validators() else 1)
