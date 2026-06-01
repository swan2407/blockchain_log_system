# Distributed Log Integrity Verification and Failure Recovery System

This project implements a Python TCP socket based distributed log integrity
verification system. Log messages are converted into SHA-256 hash-chained
blocks, replicated to independent validator nodes, and later checked for
tampering or divergence.

This is not intended to be a full blockchain with mining, consensus, or
cryptocurrency behavior. It is a distributed log integrity verification system
that uses a hash chain as the tamper-evident data structure.

## Architecture Summary

Current and planned components:

- `log_node.py`: Python log sender that generates JSON `LOG` messages.
- `block_producer.py`: TCP server that receives logs and creates hash-chained
  blocks.
- `validator_node.py`: TCP server for validator A, B, or C. Each validator
  stores an independent JSON chain file.
- `check_validators.py`: verifies each validator chain, compares block counts,
  and compares latest hashes.
- `tamper.py`: placeholder for tampering experiments.
- `run_experiment.py`: placeholder for automated performance and recovery
  experiments.
- `reset_data.py`: resets local validator chain data.
- `c_client/`: placeholder for a future C-based log sender.

Validator storage files:

- `data/validator_A_chain.json`
- `data/validator_B_chain.json`
- `data/validator_C_chain.json`

## Why Python Is Used

Python is the main implementation language because it lets the project quickly
build and verify distributed system behavior:

- TCP server/client control flow;
- block creation and SHA-256 hash verification;
- validator replication;
- integrity checking and tamper detection;
- later failure recovery and synchronization logic;
- experiment automation and result collection.

The goal is to keep the distributed systems logic readable, testable, and easy
to extend for a university project.

## Why C Will Be Added Later

C will be added later as a lightweight external log sender that simulates a
field-side device or embedded log generation node.

This language separation is intentional. The Python services define and enforce
the protocol, while the future C client will prove that log ingestion is based
on TCP and JSON message interoperability across runtime environments, not only
Python-to-Python communication.

## Block Format

Each block is stored as JSON:

```json
{
  "index": 0,
  "timestamp": 1710000000.123,
  "log_data": {
    "node_id": "NODE-01",
    "message": "STATUS=NORMAL ACTION=BOOT"
  },
  "previous_hash": "0000000000000000000000000000000000000000000000000000000000000000",
  "current_hash": "..."
}
```

The block hash is calculated only from:

- `index`
- `timestamp`
- `log_data`
- `previous_hash`

`current_hash` is never included when calculating or verifying the block hash.

## Current Execution Instructions

Reset validator data:

```bash
python reset_data.py
```

Compile the current core modules:

```bash
python -m py_compile config.py crypto_utils.py blockchain.py reset_data.py
```

Run the current Python TCP flow:

```bash
python validator_node.py A
python validator_node.py B
python validator_node.py C
python block_producer.py
python log_node.py NODE-01 --count 5 --interval 0.5
python check_validators.py
```

Use separate terminals for each long-running validator and for the block
producer.

Expected verification result:

- validator A, B, and C chains are valid;
- block counts match;
- latest hashes match;
- `check_validators.py` reports that all validators are synchronized.

## Current Project Structure

```text
blockchain_log_system/
├── config.py
├── crypto_utils.py
├── blockchain.py
├── log_node.py
├── block_producer.py
├── validator_node.py
├── check_validators.py
├── tamper.py
├── run_experiment.py
├── reset_data.py
├── README.md
├── data/
└── c_client/
    └── README.md
```
