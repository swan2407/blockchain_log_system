"""Shared configuration for the log integrity verification project."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"

HOST = "127.0.0.1"

# These ports are reserved for the socket-based components that will be added
# in the next phase of the project.
BLOCK_PRODUCER_HOST = HOST
BLOCK_PRODUCER_PORT = 5000

VALIDATOR_HOST = HOST
VALIDATOR_PORTS = {
    "A": 6001,
    "B": 6002,
    "C": 6003,
}

VALIDATOR_IDS = tuple(VALIDATOR_PORTS.keys())
VALIDATOR_CHAIN_FILES = {
    validator_id: DATA_DIR / f"validator_{validator_id}_chain.json"
    for validator_id in VALIDATOR_IDS
}

GENESIS_PREVIOUS_HASH = "0" * 64


def ensure_data_dir() -> Path:
    """Create the data directory if needed and return its path."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
