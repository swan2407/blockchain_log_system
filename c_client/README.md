# C-based External Log Sender

`log_sender.c` is a lightweight field-side equipment simulator. It sends
authenticated `LOG` messages to the Python block producer, demonstrating that
the distributed log protocol works across different runtime environments.

The client:

- connects to the producer over TCP;
- sends `[4-byte big-endian length][UTF-8 JSON payload]`;
- signs canonical JSON with HMAC-SHA256 using OpenSSL;
- reads and prints the producer's length-prefixed response;
- supports repeated logs and configurable intervals.

The default shared secret is `my_secret_token`, matching `SECRET_TOKEN` in
`config.py`. If that configuration changes, pass the same value with
`--secret`. Node IDs and messages are currently restricted to ASCII so the
client exactly matches Python's `json.dumps(..., ensure_ascii=True)`
canonicalization without embedding a full Unicode JSON implementation.

## Build

OpenSSL development headers and libraries are required.

Linux or macOS:

```bash
cd c_client
gcc log_sender.c -o log_sender -lssl -lcrypto
```

Windows with MSYS2/MinGW:

```bash
cd c_client
gcc log_sender.c -o log_sender.exe -lssl -lcrypto -lws2_32
```

For MSYS2, install the MinGW GCC and OpenSSL packages for the same selected
toolchain before compiling.

## Run

From the project root, reset data and start each service in a separate
terminal:

```bash
python reset_data.py
python validator_node.py A
python validator_node.py B
python validator_node.py C
python block_producer.py
```

Then run the compiled client:

```bash
./c_client/log_sender --count 3 --interval 0.5
```

On Windows:

```powershell
.\c_client\log_sender.exe --count 3 --interval 0.5
```

Available options:

```text
--host 127.0.0.1
--port 9000
--node-id C-EQUIPMENT-01
--message "STATUS=NORMAL ACTION=C_CLIENT_HEARTBEAT"
--count 3
--interval 0.5
--secret my_secret_token
```

Finally, verify the replicated chains:

```bash
python check_validators.py
```

Expected result: the producer receives logs from `C-EQUIPMENT-01`, commits
blocks after validator quorum, and the checker reports all validators
synchronized.

## HMAC Compatibility

Before signing, the C client builds the same sorted, compact JSON that
`crypto_utils.canonical_message()` produces, excluding `signature`:

```json
{"message":"STATUS=NORMAL ACTION=C_CLIENT_HEARTBEAT","node_id":"C-EQUIPMENT-01","sender_id":"C-EQUIPMENT-01","timestamp":1710000000,"type":"LOG"}
```

It computes a lowercase hexadecimal HMAC-SHA256 over those UTF-8 bytes. The
timestamp is a current Unix timestamp encoded as an integer JSON number, which
Python accepts and canonicalizes identically.
