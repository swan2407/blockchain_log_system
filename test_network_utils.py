"""Focused tests for the length-prefixed TCP JSON protocol."""

from __future__ import annotations

import json
import socket
import struct

from network_utils import MAX_MESSAGE_SIZE, recv_exact, recv_json, send_json


def test_round_trip() -> None:
    sender, receiver = socket.socketpair()
    try:
        message = {"type": "LOG", "node_id": "NODE-01", "message": "STATUS=NORMAL"}
        send_json(sender, message)
        assert recv_json(receiver) == message
    finally:
        sender.close()
        receiver.close()


def test_multiple_messages() -> None:
    sender, receiver = socket.socketpair()
    try:
        first = {"sequence": 1}
        second = {"sequence": 2}
        send_json(sender, first)
        send_json(sender, second)
        assert recv_json(receiver) == first
        assert recv_json(receiver) == second
    finally:
        sender.close()
        receiver.close()


def test_fragmented_message() -> None:
    sender, receiver = socket.socketpair()
    try:
        message = {"type": "SYNC_REQUEST", "latest_index": 12}
        payload = json.dumps(message).encode("utf-8")
        framed_message = struct.pack("!I", len(payload)) + payload

        for byte in framed_message:
            sender.sendall(bytes([byte]))

        assert recv_json(receiver) == message
    finally:
        sender.close()
        receiver.close()


def test_incomplete_message() -> None:
    sender, receiver = socket.socketpair()
    try:
        sender.sendall(b"ab")
        sender.close()
        try:
            recv_exact(receiver, 4)
        except ConnectionError:
            pass
        else:
            raise AssertionError("incomplete message should raise ConnectionError")
    finally:
        receiver.close()


def test_oversized_message() -> None:
    sender, receiver = socket.socketpair()
    try:
        sender.sendall(struct.pack("!I", MAX_MESSAGE_SIZE + 1))
        try:
            recv_json(receiver)
        except ValueError:
            pass
        else:
            raise AssertionError("oversized message should raise ValueError")
    finally:
        sender.close()
        receiver.close()


if __name__ == "__main__":
    test_round_trip()
    test_multiple_messages()
    test_fragmented_message()
    test_incomplete_message()
    test_oversized_message()
    print("network_utils tests passed")
