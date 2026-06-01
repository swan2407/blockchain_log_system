"""Reset local validator blockchain data for repeatable experiments."""

from config import VALIDATOR_CHAIN_FILES, ensure_data_dir
from blockchain import save_chain


def reset_data() -> None:
    """Create the data directory and reset every validator chain to empty."""
    ensure_data_dir()
    for chain_file in VALIDATOR_CHAIN_FILES.values():
        save_chain(chain_file, [])


if __name__ == "__main__":
    reset_data()
    print("Data directory reset.")
