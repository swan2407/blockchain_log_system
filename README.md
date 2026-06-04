# Distributed Log Integrity Verification and Failure Recovery System

## Project Overview

A log system that stores all records in one location is vulnerable to several
failure modes:

- an attacker or operator may modify or delete historical logs;
- a storage failure may make logs unavailable;
- a failed node may miss records produced while it is offline;
- independent replicas may diverge without a clear verification mechanism.

This project explores these problems in a small distributed environment. Log
messages are converted into SHA-256 hash-chained blocks and replicated to three
independent validators: Validator A, Validator B, and Validator C. Each
validator stores its own chain file and can verify the complete history,
identify tampering, compare replicated state, and recover committed blocks
missed during downtime.

Reliability is improved through validator recovery sync, invalid peer
exclusion, quorum-aware recovery, atomic JSON file replacement, idempotent
storage, and a simplified 2-of-3 quorum commit protocol.

## Project Scope and Character

This project is a prototype implementation project. It does not directly
modify or improve a specific commercial logging product, and it does not
propose a new distributed consensus algorithm.

> This project is a prototype that applies distributed systems concepts such
> as hash chaining, validator replication, failure recovery, invalid peer
> exclusion, and simplified quorum commit to verify log integrity and recovery
> behavior.

The project should be understood as an engineering study of distributed log
reliability:

- It is **not a full blockchain** and does not include mining, cryptocurrency,
  or decentralized governance.
- It is **not a full Raft or PBFT implementation**.
- It is **not a new consensus algorithm**.
- Its 2-of-3 protocol is a simplified commit mechanism for controlled
  experiments, not a production-grade consensus protocol.

## Architecture

```text
log_node.py
    |
    | TCP / JSON LOG
    v
block_producer.py
    |
    | PROPOSE_BLOCK
    v
validator_node.py A / B / C
    |
    | ACK / NACK
    v
block_producer.py
    |
    | COMMIT_BLOCK if 2-of-3 quorum is reached
    v
validator_node.py A / B / C
    |
    v
data/validator_A_chain.json
data/validator_B_chain.json
data/validator_C_chain.json
    |
    v
check_validators.py
```

Each validator runs as an independent TCP server and maintains an independent
chain file. On startup, a validator can request missing committed blocks from
its peers before serving new requests.

### Default Ports

| Component | Address |
|---|---|
| Block producer | `127.0.0.1:9000` |
| Validator A | `127.0.0.1:9101` |
| Validator B | `127.0.0.1:9102` |
| Validator C | `127.0.0.1:9103` |

## File Structure

| Path | Responsibility |
|---|---|
| `config.py` | Defines ports, validator addresses, chain paths, shared secret, timeouts, and shared constants. |
| `crypto_utils.py` | Provides SHA-256 block hashing and HMAC-SHA256 message authentication helpers. |
| `network_utils.py` | Sends and receives length-prefixed JSON messages over TCP. |
| `blockchain.py` | Creates and verifies blocks, validates commit proofs, loads and atomically saves chains, and performs idempotent appends. |
| `log_node.py` | Generates equipment-style log messages and sends `LOG` requests to the producer. |
| `block_producer.py` | Creates candidate blocks, collects validator ACKs, and broadcasts committed blocks after quorum. |
| `validator_node.py` | Runs Validator A, B, or C; verifies proposals, stores committed blocks, and performs recovery sync. |
| `check_validators.py` | Verifies each chain and commit proof, then compares validator block counts and latest hashes. |
| `tamper.py` | Intentionally modifies or deletes stored blocks for integrity experiments. |
| `reset_data.py` | Resets all validator chain files for repeatable experiments. |
| `run_experiment.py` | Placeholder for future experiment automation. |
| `data/` | Stores the independent JSON chain files for Validators A, B, and C. |
| `c_client/` | Reserved for a planned C-based external log sender. |

## Length-prefixed TCP Protocol

TCP is a byte stream, not a message-based protocol. A single `recv(4096)` call
does not guarantee one complete JSON message: one message may be split across
multiple reads, or multiple messages may arrive in one read.

All Python components therefore use an explicit length-prefixed protocol:

```text
[4-byte length][JSON payload]
```

The first four bytes are an unsigned big-endian integer containing the UTF-8
JSON payload length. `network_utils.py` reads the header and payload exactly,
rejects messages larger than 10 MiB, and returns one decoded JSON object at a
time.

This framing also defines a clear interoperability contract for the future
C-based log sender. A C client must encode the payload as UTF-8 JSON and send
its byte length in network byte order before the payload.

## HMAC-SHA256 Message Authentication

The previous network protocol included a plain shared token. That proved only
that a sender knew the token and did not protect the rest of the message from
modification.

Every network message is now authenticated with HMAC-SHA256 and includes:

- `sender_id`
- `timestamp`
- `signature`

The signature is computed using the shared secret over a canonical JSON
representation of the complete message excluding `signature`. Canonical JSON
uses sorted keys and compact separators so independently serialized messages
produce the same signature.

Receivers verify the HMAC with `hmac.compare_digest()`, reject messages older
than five minutes, and confirm the expected sender identity before processing
the message. This protects LOG, proposal, ACK/NACK, commit, sync, success, and
error envelopes against undetected modification in transit. Validator ACKs are
verified before they count toward quorum.

This remains prototype-level authentication. It does not encrypt traffic,
prevent replay within the accepted timestamp window, provide per-node keys, or
replace TLS and production-grade key management.

## Block Structure

A committed block is stored as JSON:

```json
{
  "index": 3,
  "timestamp": 1710000000.123,
  "log_data": {
    "node_id": "NODE-01",
    "message": "STATUS=NORMAL ACTION=HEARTBEAT"
  },
  "previous_hash": "previous-block-sha256-hash",
  "current_hash": "current-block-sha256-hash",
  "commit_proof": {
    "quorum": 2,
    "acks": [
      {
        "validator_id": "A",
        "block_index": 3,
        "block_hash": "current-block-sha256-hash"
      },
      {
        "validator_id": "C",
        "block_index": 3,
        "block_hash": "current-block-sha256-hash"
      }
    ]
  }
}
```

`current_hash` is calculated from only:

- `index`
- `timestamp`
- `log_data`
- `previous_hash`

`current_hash` itself is not included when recalculating the hash.
`commit_proof` is also excluded because it is attached only after validators
acknowledge the candidate block.

## Core Features

### SHA-256 Hash Chain

Every block contains the previous block's hash. Modifying a historical block
changes its recalculated hash and breaks the connection to later blocks.

### Full Chain Verification

The verifier checks every block in order:

- required block fields;
- sequential block index;
- connection to the previous block hash;
- recalculated SHA-256 hash;
- commit proof status when validator state is checked.

### Validator Replication

Validators A, B, and C store independent chain files. This allows the project
to compare replicas, detect divergence, and recover a validator that missed
committed blocks.

### Tamper Detection

`tamper.py` intentionally changes stored data without repairing the full chain.
The checker can detect modified log data, invalid hashes, broken links, deleted
blocks, and differences between validator replicas.

### Failure Recovery Sync

When a validator starts, it requests blocks after its local latest index. Each
received block is verified locally before it is appended.

### Quorum-Aware Recovery Sync

When multiple valid peers respond, the recovering validator compares block
indexes and hashes. Conflicting responses cause sync to abort rather than
silently selecting inconsistent data.

### Invalid Peer Exclusion

A validator with an invalid local chain refuses to serve recovery blocks and
returns `LOCAL_CHAIN_INVALID`. A recovering validator ignores that peer and
continues using available valid data subject to local verification.

### 2-of-3 Quorum Commit

The producer commits a candidate only after at least two validators acknowledge
the same block index and hash. A proposal that receives only one ACK is
aborted.

### Commit Proof Validation

Committed and recovered blocks must contain a valid `commit_proof`:

- the declared quorum must be at least two;
- at least two ACK entries must exist;
- validator IDs must be unique;
- each ACK index must match the block index;
- each ACK hash must match the block's `current_hash`.

### Atomic and Idempotent Storage

Validator chains are written to a temporary file, flushed, synchronized with
`fsync()`, and atomically replaced using `os.replace()`. Repeated delivery of
the same committed block is treated as a successful skip, while conflicting,
invalid, or out-of-order blocks are rejected before storage.

## 2-of-3 Quorum Commit Protocol

The earlier direct replication approach allowed a validator to save a block as
soon as it received it:

```text
Producer -> BLOCK -> Validator saves immediately
```

The current flow separates verification from storage:

```text
Producer  -> PROPOSE_BLOCK -> Validator verifies, but does not save
Validator -> ACK / NACK    -> Producer
Producer receives at least 2 matching ACKs
Producer  -> COMMIT_BLOCK  -> Validator verifies commit_proof and saves
```

Protocol behavior:

1. The producer creates a candidate block without advancing its committed
   in-memory chain.
2. The producer sends `PROPOSE_BLOCK` to Validators A, B, and C.
3. Each validator verifies the next index, `previous_hash`, and recalculated
   `current_hash`.
4. Validators return an ACCEPT ACK or a REJECT ACK with a reason.
5. Validators do **not** save blocks during `PROPOSE_BLOCK`.
6. If at least two validators ACK the same candidate, the producer adds
   `commit_proof` and sends `COMMIT_BLOCK`.
7. Validators save only a locally valid block with a valid `commit_proof`.
8. If only one validator ACKs, the producer aborts the commit.
9. If one validator is down, the other two validators can still form quorum.

**This is a simplified quorum-based commit protocol, not a full Raft or PBFT
consensus algorithm.** It does not implement leader election, terms, replicated
state-machine guarantees, Byzantine signatures, or complete network partition
handling.

## How to Run

Requirements:

- Python 3.10 or later
- Python standard library only
- Run commands from the project root

Reset validator data before a repeatable experiment:

```bash
python reset_data.py
```

Start each component in a separate terminal.

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

Verify chain integrity and synchronization:

```bash
python check_validators.py
```

Expected normal result:

```text
Result: All validators are synchronized.
```

Run the focused protocol tests:

```bash
python test_network_utils.py
```

Run the focused HMAC authentication tests:

```bash
python test_crypto_utils.py
```

## Experiments

Use `python reset_data.py` before each experiment unless the procedure says
otherwise.

### Experiment 1: Normal Replication and Quorum Commit

1. Start Validators A, B, and C.
2. Start the producer.
3. Generate logs:

```bash
python log_node.py NODE-01 --count 5 --interval 0.5
```

4. Check validator state:

```bash
python check_validators.py
```

Expected behavior:

- the producer reports that each block reached quorum;
- all validators save committed blocks;
- all chains and commit proofs are valid;
- `check_validators.py` reports synchronized validators.

### Experiment 2: Tamper Detection

First create at least five committed blocks, then stop the affected validator
before editing its file. Run one tamper command per reset:

```bash
python tamper.py B 3 log
python tamper.py B 3 previous_hash
python tamper.py B 3 current_hash
python tamper.py B 3 delete
```

Then run:

```bash
python check_validators.py
```

Expected errors depend on the selected tamper mode:

| Tamper mode | Typical result |
|---|---|
| `log` | Hash mismatch because `log_data` changed. |
| `previous_hash` | Previous-hash mismatch and possibly a hash mismatch. |
| `current_hash` | Hash mismatch and a broken link to the next block. |
| `delete` | Index mismatch, previous-hash mismatch, block-count mismatch, or latest-hash difference. |

### Experiment 3: Validator Failure and Recovery

1. Start Validators A, B, and C and the producer.
2. Generate three logs:

```bash
python log_node.py NODE-01 --count 3 --interval 0.5
```

3. Stop Validator B.
4. Generate three more logs:

```bash
python log_node.py NODE-01 --count 3 --interval 0.5
```

5. Validators A and C should have six blocks while B still has three.
6. Restart Validator B:

```bash
python validator_node.py B
```

7. Validator B requests missing committed blocks, verifies them, and syncs.
8. Run `python check_validators.py`.

Expected behavior: all three validators become synchronized again.

### Experiment 4: Invalid Peer Exclusion

1. Start all validators and the producer, then generate initial logs.
2. Stop Validator B.
3. Generate additional logs so B falls behind.
4. Stop Validator C and tamper with its chain:

```bash
python tamper.py C 4 log
```

5. Restart Validator C, then restart Validator B.

Expected behavior:

- C detects its invalid local chain and reports `LOCAL_CHAIN_INVALID` when
  asked to serve sync data;
- B ignores C as an unsafe recovery source;
- B can use a valid peer's committed blocks after local block and commit-proof
  verification;
- conflicting or invalid recovery data is not appended.

### Experiment 5: Quorum Failure

1. Reset data.
2. Start only Validator A.
3. Start the producer.
4. Generate logs:

```bash
python log_node.py NODE-01 --count 3 --interval 0.5
```

Expected behavior:

- only one validator ACK is available;
- the producer fails to reach the required 2-of-3 quorum;
- the producer aborts each commit;
- no candidate block is stored as committed.

## Current Development Status

| Feature | Status |
|---|---|
| Length-prefixed Python TCP/JSON communication | Completed |
| HMAC-SHA256 network message authentication | Completed |
| SHA-256 hash-chained blocks | Completed |
| Independent Validator A/B/C storage | Completed |
| Full chain verification | Completed |
| Tamper detection experiments | Completed |
| Validator failure recovery sync | Completed |
| Invalid peer exclusion | Completed |
| Quorum-aware recovery sync | Completed |
| Simplified 2-of-3 quorum commit | Completed |
| Commit proof validation | Completed |
| Atomic file replacement and idempotent append | Completed |
| Automated experiment runner | Planned |
| C-based log sender | Planned |

## Limitations

- This is not a full blockchain.
- This is not a full Raft or PBFT implementation.
- There is no leader election, term management, or automatic producer failover.
- The producer remains a single leader-like component and a potential single
  point of failure.
- Stored `commit_proof` ACK entries do not retain their network HMAC signatures.
- HMAC authentication is intentionally prototype-level and is not suitable for
  production security by itself.
- All nodes currently share one HMAC secret, so cryptographic signatures do not
  prove which specific node created a message if that secret is compromised.
- Timestamp validation rejects old messages but does not prevent replay within
  the five-minute acceptance window.
- TCP messages are limited to 10 MiB, but the protocol does not yet negotiate
  versions or capabilities.
- JSON file storage is suitable for prototype experiments, not high-throughput
  production workloads.
- Recovery behavior is simplified and does not fully model network partitions,
  concurrent leaders, or Byzantine validators.
- A real deployment would require stronger durable storage, authentication,
  authorization, observability, and operational recovery procedures.

## Future Improvements

- Further harden atomic file writes with directory synchronization, backups,
  and tested crash-recovery procedures.
- Add protocol versioning and structured error codes.
- Add per-node keys, nonce-based replay protection, key rotation, and TLS.
- Implement the planned C-based log sender in `c_client/`.
- Automate normal, failure, tamper, recovery, and quorum experiments through
  `run_experiment.py`.
- Add unit and integration tests for protocol messages and crash scenarios.
- Create a Raft-inspired design document or simulation to compare this
  simplified protocol with a complete consensus design without claiming that
  the current implementation is Raft.

## Portfolio Summary

This project demonstrates a distributed log integrity verification prototype
that uses SHA-256 hash chaining, validator replication, tamper detection,
failure recovery, invalid peer exclusion, and simplified 2-of-3 quorum commit
to study reliability issues in distributed logging systems.
