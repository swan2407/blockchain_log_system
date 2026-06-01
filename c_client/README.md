# C Log Sender Placeholder

This directory is reserved for a future C-based log sender.

The C client will act as a lightweight external node that sends JSON log
messages to the Python block producer over TCP. Its purpose is to demonstrate
that the system is protocol-based and language-independent, rather than only a
Python-to-Python demonstration.

Planned behavior:

- connect to `BLOCK_PRODUCER_HOST:BLOCK_PRODUCER_PORT`;
- send a JSON `LOG` message using the shared protocol;
- include the shared token for the current simple authentication step;
- close the TCP connection after receiving a response.
