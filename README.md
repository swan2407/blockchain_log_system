# Distributed Log Integrity Verification and Failure Recovery Prototype

## Project Overview

This project is a distributed log integrity verification and failure recovery
prototype. It models reliability problems that can occur in manufacturing,
equipment, and field-node logging systems:

- historical logs may be modified or deleted;
- logs may be missing from one replica;
- validator nodes may fail and later restart;
- recovery may accidentally trust an unsafe peer;
- TCP may split or merge application messages;
- a plain shared token does not protect message-body integrity;
- sustained log processing may expose replica synchronization limits.

Equipment-style log messages are sent to a block producer, converted into
SHA-256 hash-chained blocks, and committed to three independently stored
validator chains after a simplified 2-of-3 quorum decision. Validators verify
block history, reject unsafe data, and can recover missing committed blocks
from peers during startup.

This project is not a new blockchain or a full consensus algorithm. It is a
prototype that applies hash chaining, validator replication, recovery sync,
and simplified quorum commit to study reliability issues in distributed
logging systems. It is not intended for production deployment.

## Project Character

This is an implementation-based experimental prototype and engineering study.
It models realistic distributed log reliability problems and implements
mechanisms to observe and handle them.

- It is not a new algorithm proposal.
- It is not a direct improvement of a specific commercial logging system.
- It is not a complete blockchain.
- It is not a full Raft, PBFT, or other production consensus implementation.
- It includes executable components and repeatable experiments rather than
  formal mathematical proofs.

The code is intended to make failure behavior inspectable. Stored JSON files,
console output, tamper tools, chain checks, and CSV experiment results are used
to show both successful behavior and unresolved limitations.

## Architecture

```text
log_node.py / c_client/log_sender.c
        |
        | length-prefixed TCP + HMAC-signed JSON LOG
        v
block_producer.py
        |
        | PROPOSE_BLOCK
        v
validator_node.py A / B / C
        |
        | ACK with ACCEPT / REJECT status
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
check_validators.py / run_experiment.py
```

The producer creates candidate blocks and coordinates the simplified quorum
commit. Each validator runs as an independent TCP server and owns a separate
chain file. Validators do not store a block during proposal handling; they
store it only after receiving a valid `COMMIT_BLOCK` with a valid
`commit_proof`.

On startup, a validator requests committed blocks after its local latest index.
It validates peer responses, compares responses when multiple peers are
available, and verifies every recovered block before appending it.

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
| `config.py` | Defines addresses, ports, chain paths, timeouts, shared secret, and common constants. |
| `crypto_utils.py` | Implements canonical JSON, SHA-256 hashing, HMAC-SHA256 signing, and signature verification. |
| `network_utils.py` | Implements length-prefixed JSON transmission with `send_json()`, `recv_json()`, and `recv_exact()`. |
| `blockchain.py` | Creates blocks, verifies chains and commit proofs, loads and atomically saves chains, and performs idempotent appends. |
| `log_node.py` | Sends signed Python-generated `LOG` messages to the producer. |
| `block_producer.py` | Creates candidate blocks, collects validator ACKs, attaches commit proofs, and sends committed blocks. |
| `validator_node.py` | Runs Validator A, B, or C; handles proposals, commits, and startup recovery sync. |
| `check_validators.py` | Verifies each full chain and commit proof, then compares replicated state. |
| `tamper.py` | Intentionally modifies or deletes validator data for integrity experiments. |
| `reset_data.py` | Resets validator chain files. |
| `run_experiment.py` | Runs quantitative normal, HMAC, tamper, recovery, and C-client checks and appends CSV results. |
| `test_crypto_utils.py` | Tests HMAC signing, verification, tamper rejection, and timestamp checks. |
| `test_network_utils.py` | Tests length-prefixed TCP message handling. |
| `c_client/log_sender.c` | OpenSSL-based external C log sender using the same wire protocol and HMAC rules. |
| `c_client/README.md` | Documents C client dependencies, build commands, options, and limitations. |
| `data/` | Stores independent Validator A, B, and C JSON chain files. |
| `experiments/` | Stores experiment documentation and generated CSV result files. |

## Message and Block Format

### TCP Framing

TCP is a byte stream. A single `recv()` call does not guarantee one complete
JSON message, so all network components use explicit framing:

```text
[4-byte big-endian unsigned payload length][UTF-8 JSON payload]
```

`network_utils.recv_exact()` reads the required number of bytes before JSON
decoding. Messages larger than 10 MiB are rejected.

### HMAC Authentication

Authenticated network messages include:

```json
{
  "sender_id": "NODE-01",
  "timestamp": 1710000000.123,
  "signature": "hex-encoded-hmac-sha256"
}
```

The signature is calculated over canonical JSON containing the complete
message except `signature`. Canonical JSON uses sorted keys and compact
separators. Receivers verify the signature, reject timestamps older than the
configured acceptance window, and check the expected sender identity.

### Protocol Messages

| Message | Direction | Purpose |
|---|---|---|
| `LOG` | Log node or C client to producer | Submits an equipment log entry. |
| `PROPOSE_BLOCK` | Producer to validators | Requests validation of a candidate block without storing it. |
| `ACK` with `status=ACCEPT` | Validator to producer | Confirms the candidate index and hash are acceptable. |
| `ACK` with `status=REJECT` | Validator to producer | Rejects the candidate and includes a reason. This is the protocol's NACK behavior. |
| `COMMIT_BLOCK` | Producer to validators | Sends a quorum-approved block with `commit_proof` for storage. |
| `SYNC_REQUEST` | Recovering validator to peer | Requests committed blocks after a local index. |
| `SYNC_RESPONSE` | Peer validator to recovering validator | Returns missing blocks or `LOCAL_CHAIN_INVALID`. |

Example signed `LOG` message:

```json
{
  "type": "LOG",
  "node_id": "NODE-01",
  "message": "STATUS=NORMAL ACTION=HEARTBEAT",
  "sender_id": "NODE-01",
  "timestamp": 1710000000.123,
  "signature": "..."
}
```

### Block Structure

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

`current_hash` is calculated from `index`, `timestamp`, `log_data`, and
`previous_hash`. It excludes `current_hash` and `commit_proof`. The proof is
attached only after the producer receives at least two valid ACCEPT ACKs.

A valid `commit_proof` requires a quorum of at least two unique validator IDs,
with every ACK referring to the committed block's index and hash.

## Development Process and Engineering Decisions

This section records the main implementation stages, problems discovered
during development, and the resulting design decisions.

### Initial Distributed Log Replication

The initial flow was:

```text
log_node -> block_producer -> Validator A / B / C
```

Each validator stored a separate JSON chain file. `check_validators.py` was
used to compare block counts and latest hashes.

This established basic replication, but replication alone only proves that
data was copied. It did not adequately explain middle-block tampering,
recovery safety, or whether a stored block had been accepted by a majority.

### Latest Hash Comparison Was Not Enough

**Problem:** Comparing only latest hashes and block counts cannot locate or
clearly explain corruption inside a chain. Different failure patterns can
produce the same high-level mismatch.

**Decision:** Full chain verification was added. For every block, the verifier:

- checks required fields and sequential index order;
- recalculates `current_hash`;
- checks the `previous_hash` link;
- reports the block position, index, mismatch type, and explanation.

Replica comparison remains useful, but it is performed after each chain is
individually verified.

### Tamper Detection Experiments

**Problem:** Integrity checking needed to be tested against actual manipulated
stored data rather than only valid chains.

**Decision:** `tamper.py` was implemented with four mutation types:

- `log`: modifies `log_data`;
- `previous_hash`: modifies a block's previous link;
- `current_hash`: modifies the stored current hash;
- `delete`: removes a block.

Observed detection behavior:

| Tamper operation | Observed result |
|---|---|
| Log data modification | Recalculated hash mismatch. |
| `previous_hash` modification | Previous-hash mismatch and hash mismatch. |
| `current_hash` modification | Hash mismatch and next-block previous-hash mismatch. |
| Block deletion | Index mismatch and replica block-count mismatch. |

### Validator Failure Recovery

**Problem:** If Validator B stops while A and C continue receiving committed
blocks, B falls behind.

**Decision:** Startup recovery sync was added. A restarting validator:

1. loads and checks its local latest index;
2. sends `SYNC_REQUEST` messages to peers;
3. receives missing committed blocks in `SYNC_RESPONSE`;
4. verifies each block and its commit proof locally;
5. appends verified blocks idempotently.

This handles a validator that restarts after missing committed blocks.

### Unsafe Peer Problem During Recovery

**Problem:** Recovering from one peer without checking that peer can copy
corrupted history.

**Decision:** Recovery became peer-aware and quorum-aware:

- a peer verifies its own chain before serving recovery data;
- an invalid peer returns `LOCAL_CHAIN_INVALID`;
- the recovering validator ignores invalid peers;
- responses from multiple peers are compared by block index and hash;
- conflicting responses abort synchronization;
- recovered blocks are still verified locally before storage.

When only one valid peer responds, the prototype can proceed after local block
and commit-proof verification, but it logs that reduced assurance.

### Direct Replication Was Not Enough

**Problem:** Directly sending a block to validators for immediate storage does
not show that a majority accepted the same candidate.

**Decision:** A simplified 2-of-3 quorum commit protocol replaced direct
storage:

```text
Producer  -> PROPOSE_BLOCK -> Validators verify without saving
Validator -> ACK ACCEPT or ACK REJECT -> Producer
Producer receives at least two matching ACCEPT ACKs
Producer  -> COMMIT_BLOCK with commit_proof -> Validators save
```

Validators do not save during proposal handling. The producer commits only
after at least two validators accept the same block index and hash. Committed
blocks include a normalized `commit_proof`.

This is a simplified quorum-based commit protocol, not full Raft or PBFT. It
does not provide leader election, terms, complete partition handling, or full
replicated state-machine guarantees.

### File Write Reliability Problem

**Problem:** Directly overwriting a JSON chain file can leave partial or
corrupt data if a process stops during the write.

**Decision:** Chain storage uses atomic replacement:

1. write the complete chain to a `.tmp` file;
2. flush the Python file buffer;
3. call `fsync()`;
4. replace the destination with `os.replace()`.

Idempotent append rules were also added:

- same index and same hash: skip as already stored;
- same index and different hash: reject as conflict;
- future index with a gap: reject;
- next valid index and hash link: append.

### TCP Message Framing Problem

**Problem:** TCP does not preserve application-message boundaries.
`recv(4096)` may return a partial JSON document or multiple documents.

**Decision:** `network_utils.py` introduced:

- `send_json()`;
- `recv_json()`;
- `recv_exact()`;
- a 4-byte big-endian payload-length prefix.

`test_network_utils.py` verifies framing behavior.

### Token Authentication Was Too Weak

**Problem:** A plain token only shows that a sender knows the token. It does
not protect the message body from modification.

**Decision:** Network messages now use HMAC-SHA256 authentication. Messages
include `sender_id`, `timestamp`, and `signature`. The signature covers
canonical JSON excluding `signature`. Receivers verify the HMAC, timestamp,
and expected sender.

`test_crypto_utils.py` passed for the implemented signing and verification
behavior.

### Python-Only System Limitation

**Problem:** Field equipment and embedded nodes may use C or C++ rather than
Python.

**Decision:** `c_client/log_sender.c` was added. It uses OpenSSL for
HMAC-SHA256, supports Winsock2 and POSIX sockets, and sends the same framed,
signed `LOG` message accepted from Python clients.

Observed C-client integration result:

- the C client sent 3 logs;
- Validators A, B, and C each stored 3 committed blocks;
- commit proofs were valid for all stored blocks;
- `check_validators.py` reported synchronized validators.

### High-Volume Experiment Revealed Synchronization Limits

**Problem:** Small and medium normal experiments completed successfully, but a
1000-log run exposed synchronization failure.

Recorded normal experiment results:

| Count | Success | Synchronized | Committed |
|---:|---|---|---:|
| 10 | `True` | `True` | 10/10 |
| 100 | `True` | `True` | 100/100 |
| 1000 | `False` | `False` | 631/1000 |

A later validator-state observation showed:

| Validator | Block count | Individual chain valid | Stored commit proofs valid |
|---|---:|---|---|
| A | 740 | Yes | Yes |
| B | 741 | Yes | Yes |
| C | 197 | Yes | Yes |

The issue was not hash-chain corruption. Each stored chain was individually
valid, and stored commit proofs were valid, but the replicas were not
synchronized. The result indicates replica lag or commit-delivery
inconsistency during sustained processing.

Current recovery runs only when a validator starts. It does not continuously
catch up a validator that remains running but misses `COMMIT_BLOCK` delivery.
Background catch-up synchronization and commit-delivery retry are required
before high-volume processing can be considered reliable.

## How to Run

### Requirements

- Python 3.10 or later
- Python standard library only for Python components
- OpenSSL development headers and libraries for the C client
- Commands run from the project root

### Reset Data

Stop validators and the producer before resetting:

```bash
python reset_data.py
```

### Start Validators and Producer

Start each process in a separate terminal:

```bash
python validator_node.py A
python validator_node.py B
python validator_node.py C
python block_producer.py
```

### Send Logs with Python

```bash
python log_node.py NODE-01 --count 5 --interval 0.5
```

### Send Logs with C

Build on Linux or macOS:

```bash
gcc c_client/log_sender.c -o c_client/log_sender -lssl -lcrypto
./c_client/log_sender --count 3 --interval 0.5
```

Build on Windows with MSYS2/MinGW:

```bash
gcc c_client/log_sender.c -o c_client/log_sender.exe -lssl -lcrypto -lws2_32
./c_client/log_sender.exe --count 3 --interval 0.5
```

See `c_client/README.md` for platform details and C-client options.

### Verify Validators

```bash
python check_validators.py
```

For a synchronized valid state:

```text
Result: All validators are synchronized.
```

### Run Focused Tests

```bash
python test_crypto_utils.py
python test_network_utils.py
```

### Run Experiment Automation

`run_experiment.py` appends timestamped results to
`experiments/experiment_results.csv` by default.

```bash
python run_experiment.py normal --count 10
python run_experiment.py normal --count 100
python run_experiment.py hmac --count 1000
python run_experiment.py recovery-check --wait 10
python run_experiment.py c-client-check --node-id C-EQUIPMENT-01
```

The `normal` mode requires validators and the producer to be running.
`recovery-check` records state before and after a wait period but does not
start or restart processes.

The experiment tamper mode intentionally modifies stored data:

```bash
python run_experiment.py tamper --validator B --block-index 3 --tamper-type log
```

Stop the selected validator before tampering, and reset or recover its data
after the experiment.

## Experiments

Use `python reset_data.py` before each independent experiment unless the
procedure explicitly requires existing data.

### Normal Quorum Commit

1. Start all validators and the producer.
2. Send logs with `log_node.py` or `run_experiment.py normal`.
3. Run `python check_validators.py`.

Expected result for low-volume runs: each block reaches quorum, all validators
store the committed block, and replicas are synchronized.

### Tamper Detection

Create several blocks, stop the selected validator, then run one mutation:

```bash
python tamper.py B 3 log
python tamper.py B 3 previous_hash
python tamper.py B 3 current_hash
python tamper.py B 3 delete
python check_validators.py
```

Run one tamper type per reset to keep results interpretable.

### Validator Failure and Recovery

1. Start all validators and the producer.
2. Send initial logs.
3. Stop Validator B.
4. Send additional logs while A and C form quorum.
5. Restart Validator B.
6. Run `python check_validators.py`.

Validator B should request and verify missing committed blocks during startup.

### Invalid Peer Exclusion

1. Make Validator B fall behind.
2. Stop and tamper with Validator C.
3. Restart C, then restart B.

C should report `LOCAL_CHAIN_INVALID` when asked for recovery data. B should
ignore C and use valid peer data subject to local verification.

### Quorum Failure

1. Reset data.
2. Start only Validator A and the producer.
3. Send logs.

With only one ACK available, the producer should abort commits because the
required 2-of-3 quorum is unavailable.

### HMAC Test and Measurement

```bash
python test_crypto_utils.py
python run_experiment.py hmac --count 1000
```

The test checks correctness. The experiment records signing and verification
timings.

### C Client Integration

1. Start all validators and the producer.
2. Send logs with `c_client/log_sender`.
3. Run:

```bash
python check_validators.py
python run_experiment.py c-client-check --node-id C-EQUIPMENT-01
```

### High-Volume Normal Experiment

```bash
python run_experiment.py normal --count 1000
python check_validators.py
```

The recorded 1000-log run did not remain synchronized. Treat this as a
diagnostic experiment for the current implementation, not an expected passing
test.

## Current Results

| Experiment | Result |
|---|---|
| Normal 5 logs | Synchronized. |
| Tamper `log_data` | Hash mismatch detected. |
| Tamper `previous_hash` | Previous-hash mismatch detected. |
| Tamper `current_hash` | Hash mismatch and next previous-hash mismatch detected. |
| Block deletion | Index mismatch and replica count mismatch detected. |
| Validator B failure and restart | Missing committed blocks recovered by startup sync. |
| Invalid peer during recovery | Invalid peer excluded from recovery source selection. |
| Simplified 2-of-3 quorum commit | Candidate committed after at least two valid ACKs. |
| HMAC test | Passed. |
| C client, 3 logs | Validators synchronized with valid commit proofs. |
| 1000-log experiment | Not synchronized; high-volume limitation observed. |

## Limitations

- This is not a complete blockchain.
- This is not full Raft, PBFT, or a production consensus implementation.
- There is no leader election, term management, or automatic producer
  failover.
- The producer is a single leader-like component and a single point of
  failure.
- The 2-of-3 quorum protocol is simplified and does not provide complete
  distributed consensus guarantees.
- A producer can advance its in-memory chain after quorum even if subsequent
  `COMMIT_BLOCK` delivery fails for one or more validators.
- Running validators do not continuously catch up in the background.
- Startup recovery does not repair a lagging validator that stays running.
- `COMMIT_BLOCK` delivery is not retried until confirmed durable at every
  intended replica.
- Persistent connections, batching, flow control, and backpressure are not
  implemented.
- High-volume experiments have demonstrated replica synchronization limits.
- HMAC uses one shared secret rather than per-node production key management.
- `commit_proof` stores validator IDs, indexes, and hashes, not public-key
  digital signatures.
- HMAC does not encrypt traffic and does not prevent replay within the accepted
  timestamp window.
- JSON file storage is suitable for a prototype, not high-throughput or
  production durability requirements.
- Directory synchronization and more complete crash-recovery behavior are not
  implemented.
- Real network partitions, concurrent producers, Byzantine behavior, and
  complex timing failures are not fully simulated.
- Experiment automation does not safely manage the full process lifecycle.

## Future Work

The next engineering priority is to keep running validators synchronized under
sustained load.

- Add periodic or event-driven background catch-up sync.
- Retry `COMMIT_BLOCK` delivery and track per-validator delivery status.
- Add persistent producer-to-validator connections.
- Add batch proposal and commit support.
- Add bounded queues, backpressure, and better failure diagnostics.
- Record per-stage latency and retry metrics during experiments.
- Expand the automated benchmark suite with repeated trials, percentiles, and
  controlled process failure injection.
- Integrate a public manufacturing or equipment log dataset.
- Develop a Raft-inspired design document or simulation for comparison without
  representing the current protocol as Raft.
- Replace the shared HMAC secret with stronger per-node key management or
  digital signatures.
- Evaluate storage mechanisms that provide stronger durability and concurrency
  guarantees than JSON files.

## Development Status

- Core integrity, replication, quorum, recovery, framing, authentication, and
  experiment mechanisms are implemented.
- Basic and medium-scale experiments pass under the tested conditions.
- The high-volume experiment exposes unresolved synchronization and delivery
  limitations.
- The project is suitable as a technical prototype and engineering study, not
  as a production deployment.
