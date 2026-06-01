"""Reset local validator blockchain data for repeatable experiments."""

from blockchain import save_chain
from config import DATA_DIR, VALIDATOR_CHAIN_FILES, ensure_data_dir


def reset_data() -> None:
    """Create the data directory and reset every validator chain to empty."""
    ensure_data_dir()
    for chain_file in VALIDATOR_CHAIN_FILES.values():
        save_chain(chain_file, [])

    experiment_result = DATA_DIR / "experiment_result.csv"
    if experiment_result.exists():
        experiment_result.unlink()


if __name__ == "__main__":
    reset_data()
    print("Data directory reset.")
