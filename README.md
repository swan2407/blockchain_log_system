# Distributed Log Integrity Verification and Failure Recovery System

This project implements a Python TCP socket based distributed log integrity
verification system. Log messages are converted into SHA-256 hash-chained
blocks, replicated to independent validator nodes, and checked for tampering or
state divergence.

This is not a full blockchain with mining, consensus, or cryptocurrency
behavior. It is a SHA-256 hash-chain based distributed log integrity
verification system.

## Architecture Summary

- `log_node.py` sends JSON `LOG` messages to the block producer.
- `block_producer.py` receives logs, creates hash-chained blocks, and sends each
  block to validators A, B, and C.
- `validator_node.py` runs as an independent TCP server for each validator.
- `check_validators.py` verifies validator chain integrity and compares their
  latest replicated state.
- `reset_data.py` resets validator chain files.
- `tamper.py` intentionally modifies one validator chain file for tamper
  detection experiments.
- `run_experiment.py` is a placeholder for later experiment automation.
- `c_client/` is reserved for a future C-based external log sender.

Validator storage files:

- `data/validator_A_chain.json`
- `data/validator_B_chain.json`
- `data/validator_C_chain.json`

## Why Python Is Used

Python is used to quickly build and verify the distributed system behavior:

- TCP server and client control flow;
- SHA-256 block creation and verification;
- validator replication;
- integrity checking and tamper detection;
- later failure recovery and synchronization;
- experiment automation and result collection.

## Why C Will Be Added Later

C will be added as a lightweight field-side log generation node. This language
separation is intentional: it shows that the system is based on a TCP/JSON
protocol and can interoperate across runtime environments, not just
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

`current_hash` is never included when calculating or verifying a block hash.

## Communication Flow

Reset validator data first:

```bash
python reset_data.py
```

Terminal 1:

```bash
python validator_node.py A
```

Terminal 2:

```bash
python validator_node.py B
```

Terminal 3:

```bash
python validator_node.py C
```

Terminal 4:

```bash
python block_producer.py
```

Terminal 5:

```bash
python log_node.py NODE-01 --count 5 --interval 0.5
```

Then verify:

```bash
python check_validators.py
```

Expected result:

- validator A, B, and C should all have valid chains;
- their block counts should match;
- their latest hashes should match;
- `check_validators.py` should print:

```text
Result: All validators are synchronized.
```

## Tamper Detection Experiment

After generating and verifying a normal replicated chain, intentionally tamper
with one validator file:

```bash
python tamper.py B 3 log
```

Then verify again:

```bash
python check_validators.py
```

Expected result:

- validator B should report an invalid chain or a different replicated state;
- the detailed error should identify validator B and the affected block index
  when available;
- `check_validators.py` should print:

```text
Result: Validators are not synchronized.
```

Supported tamper commands:

```bash
python tamper.py B 3 log
python tamper.py B 3 previous_hash
python tamper.py B 3 current_hash
python tamper.py B 3 delete
```

Tamper modes:

- `log` changes the selected block's `log_data.message` field, or replaces
  `log_data` when it is not an object.
- `previous_hash` replaces the selected block's `previous_hash` with an invalid
  value.
- `current_hash` replaces the selected block's `current_hash` with an invalid
  value.
- `delete` removes the selected block from the chain.

`tamper.py` does not recalculate hashes. It simulates an attacker modifying
stored data without repairing the complete hash chain.

## Current Ports

The current default ports are defined in `config.py`:

- block producer: `127.0.0.1:9000`
- validator A: `127.0.0.1:9101`
- validator B: `127.0.0.1:9102`
- validator C: `127.0.0.1:9103`

## Compile Checks

Compile the communication scripts:

```bash
python -m py_compile validator_node.py block_producer.py log_node.py check_validators.py tamper.py
```

Compile the core modules:

```bash
python -m py_compile config.py crypto_utils.py blockchain.py reset_data.py
```

## Current Project Structure

```text
blockchain_log_system/
|-- config.py
|-- crypto_utils.py
|-- blockchain.py
|-- log_node.py
|-- block_producer.py
|-- validator_node.py
|-- check_validators.py
|-- tamper.py
|-- run_experiment.py
|-- reset_data.py
|-- README.md
|-- data/
`-- c_client/
    `-- README.md
```
