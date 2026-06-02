"""Shared configuration for the log integrity verification project."""

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"

HOST = "127.0.0.1"

BLOCK_PRODUCER_HOST = HOST
BLOCK_PRODUCER_PORT = 9000

VALIDATORS = {
    "A": {"host": HOST, "port": 9101},
    "B": {"host": HOST, "port": 9102},
    "C": {"host": HOST, "port": 9103},
}

SECRET_TOKEN = "my_secret_token"
GENESIS_PREVIOUS_HASH = "0" * 64

VALIDATOR_IDS = tuple(VALIDATORS.keys())
VALIDATOR_CHAIN_FILES = {
    validator_id: DATA_DIR / f"validator_{validator_id}_chain.json"
    for validator_id in VALIDATOR_IDS
}

# Backward-compatible aliases used by the TCP scripts.
AUTH_TOKEN = SECRET_TOKEN
VALIDATOR_HOST = HOST
VALIDATOR_PORTS = {
    validator_id: validator["port"]
    for validator_id, validator in VALIDATORS.items()
}

SOCKET_BACKLOG = 5
SOCKET_TIMEOUT_SECONDS = 5.0


def ensure_data_dir() -> Path:
    """Create the data directory if needed and return its path."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR
