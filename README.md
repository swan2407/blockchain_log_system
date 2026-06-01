# Distributed Log Integrity Verification and Failure Recovery System

This project is a Python TCP socket based distributed systems project for
verifying log integrity with SHA-256 hash-chained blocks.

The system will use these components:

- `log_node.py`: generates log messages and sends them to the block producer.
- `block_producer.py`: receives logs and creates hash-chained blocks.
- `validator_node.py`: runs validator nodes A, B, and C.
- `check_validators.py`: verifies each validator chain and compares latest
  hashes.
- `tamper.py`: simulates tampering experiments.

Current implementation status:

- `config.py` defines shared paths, validator IDs, and socket ports.
- `crypto_utils.py` calculates deterministic SHA-256 block hashes.
- `blockchain.py` creates, stores, loads, appends, and verifies JSON blockchains.
- `reset_data.py` recreates empty validator chain files under `data/`.

Each validator stores an independent blockchain file:

- `data/validator_A_chain.json`
- `data/validator_B_chain.json`
- `data/validator_C_chain.json`

## Block Format

Each block is stored as JSON with these fields:

- `index`
- `timestamp`
- `log_data`
- `previous_hash`
- `current_hash`

The block hash is calculated only from `index`, `timestamp`, `log_data`, and
`previous_hash`. The `current_hash` field is never included when calculating or
verifying a block hash.

## Basic Commands

Reset validator data:

```bash
python reset_data.py
```

Check that the current Python files compile:

```bash
python -m py_compile config.py crypto_utils.py blockchain.py reset_data.py
```

## Verification Rules

`verify_chain()` checks:

- each block's `current_hash` against a recalculated SHA-256 hash;
- each block's `previous_hash` against the previous block's `current_hash`;
- each block index against its expected position in the chain;
- tampering in middle blocks through hash mismatch and broken chain links.

## Next Implementation Steps

The next project files should be:

- `log_node.py`
- `block_producer.py`
- `validator_node.py`
- `check_validators.py`
- `tamper.py`
