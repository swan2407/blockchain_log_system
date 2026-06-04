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
- `block_producer.py` receives logs, proposes hash-chained blocks, and commits
  them after a 2-of-3 validator quorum.
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
  "current_hash": "...",
  "commit_proof": {
    "quorum": 2,
    "acks": [
      {"validator_id": "A", "block_index": 0, "block_hash": "..."},
      {"validator_id": "C", "block_index": 0, "block_hash": "..."}
    ]
  }
}
```

The block hash is calculated only from:

- `index`
- `timestamp`
- `log_data`
- `previous_hash`

`current_hash` is never included when calculating or verifying a block hash.
`commit_proof` is also excluded from the block hash because it is added only
after validators acknowledge the candidate block.

## 2-of-3 Quorum Commit Protocol

This is not a full Raft or PBFT consensus algorithm. It is a simplified quorum
commit protocol for this prototype.

1. The producer creates a candidate block but does not add it to its chain.
2. The producer sends `PROPOSE_BLOCK` to validators A, B, and C.
3. Each validator verifies the index, previous hash, and recalculated block
   hash, then returns an ACCEPT ACK or REJECT ACK. Proposals are not stored.
4. The producer commits only after at least two validators ACK the same block
   index and hash.
5. The producer adds `commit_proof` containing the quorum ACK metadata and
   sends `COMMIT_BLOCK` to all validators.
6. Validators revalidate the block and commit proof before idempotently saving
   the block.

A valid `commit_proof` has a declared quorum of at least two, at least two ACKs,
unique validator IDs, and ACK block indexes and hashes matching the committed
block. Recovery sync accepts only blocks with valid commit proof metadata, so a
validator recovers committed blocks rather than arbitrary peer data.

### Experiment 1: Normal quorum commit

1. Reset data with `python reset_data.py`.
2. Start Validator A, B, and C in separate terminals.
3. Start `python block_producer.py`.
4. Run `python log_node.py NODE-01 --count 5 --interval 0.5`.
5. Run `python check_validators.py`.

Expected: the producer prints that quorum was reached and each block was
committed, validators save committed blocks, and the checker reports all
validators synchronized with valid commit proofs.

### Experiment 2: One validator down but quorum still succeeds

1. Reset data with `python reset_data.py`.
2. Start only Validator A and Validator C.
3. Start the producer and generate logs.
4. Run the checker, then start Validator B to recover the committed blocks.

Expected: the producer cannot contact B, A and C ACK, the 2-of-3 quorum commits,
and B later syncs blocks carrying valid commit proofs.

### Experiment 3: Quorum failure

1. Reset data with `python reset_data.py`.
2. Start only Validator A.
3. Start the producer and generate logs.
4. Run `python check_validators.py`.

Expected: only one ACK is received, quorum is not reached, the producer aborts
the commit, and no validator stores the candidate block.

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

## Failure Recovery Experiment

This experiment verifies that a validator can recover blocks it missed while it
was offline.

1. Reset data:

```bash
python reset_data.py
```

2. Start Validator A, B, and C in separate terminals:

```bash
python validator_node.py A
python validator_node.py B
python validator_node.py C
```

3. Start the producer in another terminal:

```bash
python block_producer.py
```

4. Generate initial logs:

```bash
python log_node.py NODE-01 --count 3 --interval 0.5
```

5. Stop Validator B manually.

6. Generate more logs while B is down:

```bash
python log_node.py NODE-01 --count 3 --interval 0.5
```

7. Check validators:

```bash
python check_validators.py
```

Expected: Validator B should have fewer blocks and validators should not be
synchronized.

8. Restart Validator B:

```bash
python validator_node.py B
```

Expected: Validator B should automatically request missing blocks from another
validator and sync.

9. Check validators again:

```bash
python check_validators.py
```

Expected:

```text
Result: All validators are synchronized.
```

## Quorum-based Recovery Sync and Conflict Detection

Validator startup recovery now requests missing blocks from every available peer
validator. When more than one safe peer responds, the recovering validator
compares returned blocks by index and `current_hash` before appending anything.
Every accepted block is still verified locally against the recovering
validator's current chain tip.

If a validator's own local chain is invalid, it refuses to serve sync blocks and
returns `LOCAL_CHAIN_INVALID`. The recovering validator ignores that peer as an
unsafe sync source.

### Experiment 1: Normal quorum recovery

1. Reset data:

```bash
python reset_data.py
```

2. Start Validator A, B, and C in separate terminals:

```bash
python validator_node.py A
python validator_node.py B
python validator_node.py C
```

3. Start the producer:

```bash
python block_producer.py
```

4. Generate 3 logs:

```bash
python log_node.py NODE-01 --count 3 --interval 0.5
```

5. Stop Validator B manually.

6. Generate 3 more logs while B is down:

```bash
python log_node.py NODE-01 --count 3 --interval 0.5
```

7. Check validators:

```bash
python check_validators.py
```

Expected: Validator B should have fewer blocks and validators should not be
synchronized.

8. Restart Validator B:

```bash
python validator_node.py B
```

Expected: Validator B requests missing blocks from Validator A and Validator C.
A and C should respond with matching block hashes, and B should sync the missing
blocks.

9. Check validators again:

```bash
python check_validators.py
```

Expected:

```text
Result: All validators are synchronized.
```

### Experiment 2: Conflict detection during recovery

1. Reset data:

```bash
python reset_data.py
```

2. Start Validator A, B, and C in separate terminals:

```bash
python validator_node.py A
python validator_node.py B
python validator_node.py C
```

3. Start the producer:

```bash
python block_producer.py
```

4. Generate 3 logs:

```bash
python log_node.py NODE-01 --count 3 --interval 0.5
```

5. Stop Validator B manually.

6. Generate 3 more logs while B is down:

```bash
python log_node.py NODE-01 --count 3 --interval 0.5
```

7. Tamper Validator C block 4:

```bash
python tamper.py C 4 log
```

8. Restart Validator B:

```bash
python validator_node.py B
```

Expected: Validator B requests missing blocks from A and C. Validator C should
refuse to serve sync blocks because its local chain is invalid, and B should
ignore C as an unsafe sync source. If multiple valid peers return different
`current_hash` values for the same block index, B reports the conflicting peer
hashes and aborts sync without appending the conflicting blocks.

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
