"""Run repeatable distributed log experiments and append quantitative CSV results."""

from __future__ import annotations

import argparse
import csv
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from blockchain import (
    ChainLoadError,
    get_latest_hash,
    load_chain,
    save_chain,
    validate_commit_proof,
    verify_chain_detailed,
)
from config import (
    BLOCK_PRODUCER_HOST,
    BLOCK_PRODUCER_PORT,
    PROJECT_ROOT,
    SOCKET_TIMEOUT_SECONDS,
    VALIDATOR_CHAIN_FILES,
    VALIDATOR_IDS,
)
from crypto_utils import attach_signature, verify_message_signature
from network_utils import recv_json, send_json
from tamper import TAMPER_TYPES, apply_tamper


DEFAULT_OUTPUT = PROJECT_ROOT / "experiments" / "experiment_results.csv"
RESULT_FIELDS = [
    "timestamp",
    "experiment_type",
    "count",
    "total_time_sec",
    "avg_time_ms",
    "sign_time_sec",
    "verify_time_sec",
    "avg_sign_ms",
    "avg_verify_ms",
    "success",
    "synchronized",
    "validator",
    "block_index",
    "tamper_type",
    "detected",
    "chain_valid",
    "before_synchronized",
    "after_synchronized",
    "missing_blocks",
    "recovery_success",
    "node_id",
    "found_log_count",
    "notes",
]


def timestamp_now() -> str:
    """Return a stable UTC timestamp for a result row."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def format_seconds(value: float) -> str:
    return f"{value:.6f}"


def format_milliseconds(value: float) -> str:
    return f"{value:.3f}"


def append_result(output: Path, result: dict[str, Any]) -> None:
    """Append one normalized result row to the shared CSV file."""
    output.parent.mkdir(parents=True, exist_ok=True)
    needs_header = not output.exists() or output.stat().st_size == 0
    row = {field: result.get(field, "") for field in RESULT_FIELDS}
    row["timestamp"] = result.get("timestamp", timestamp_now())

    with output.open("a", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=RESULT_FIELDS)
        if needs_header:
            writer.writeheader()
        writer.writerow(row)
    print(f"CSV result appended: {output}")


def load_validator_state() -> dict[str, Any]:
    """Load chains and calculate chain, proof, and synchronization status."""
    chains: dict[str, list[dict[str, Any]]] = {}
    chain_validities: dict[str, bool] = {}
    proof_validities: dict[str, bool] = {}
    errors: list[str] = []

    for validator_id in VALIDATOR_IDS:
        try:
            chain = load_chain(VALIDATOR_CHAIN_FILES[validator_id])
            chain_valid, chain_errors = verify_chain_detailed(chain)
        except ChainLoadError as exc:
            chain = []
            chain_valid = False
            chain_errors = [{"message": str(exc)}]

        proof_valid = all(validate_commit_proof(block)[0] for block in chain)
        chains[validator_id] = chain
        chain_validities[validator_id] = chain_valid
        proof_validities[validator_id] = proof_valid
        errors.extend(
            f"Validator {validator_id}: {error['message']}"
            for error in chain_errors
        )
        if not proof_valid:
            errors.append(f"Validator {validator_id}: invalid commit proof")

    counts = {validator_id: len(chain) for validator_id, chain in chains.items()}
    latest_hashes = {
        validator_id: get_latest_hash(chain)
        for validator_id, chain in chains.items()
    }
    synchronized = (
        all(chain_validities.values())
        and all(proof_validities.values())
        and len(set(counts.values())) == 1
        and len(set(latest_hashes.values())) == 1
    )
    return {
        "chains": chains,
        "counts": counts,
        "chain_validities": chain_validities,
        "proof_validities": proof_validities,
        "latest_hashes": latest_hashes,
        "synchronized": synchronized,
        "errors": errors,
    }


def send_experiment_log(node_id: str, sequence: int) -> dict[str, Any]:
    """Send one signed experiment LOG request and validate the producer response."""
    message = attach_signature(
        {
            "type": "LOG",
            "node_id": node_id,
            "message": f"STATUS=NORMAL ACTION=EXPERIMENT SEQUENCE={sequence}",
        },
        sender_id=node_id,
    )
    with socket.create_connection(
        (BLOCK_PRODUCER_HOST, BLOCK_PRODUCER_PORT),
        timeout=SOCKET_TIMEOUT_SECONDS,
    ) as client_socket:
        send_json(client_socket, message)
        response = recv_json(client_socket)

    valid, reason = verify_message_signature(response)
    if not valid:
        raise ValueError(f"invalid producer response: {reason}")
    if response.get("sender_id") != "PRODUCER":
        raise ValueError("invalid producer response: unexpected sender_id")
    return response


def run_normal(args: argparse.Namespace) -> int:
    """Measure end-to-end LOG commit request latency."""
    successful_logs = 0
    failures: list[str] = []
    start = time.perf_counter()
    for sequence in range(1, args.count + 1):
        try:
            response = send_experiment_log(args.node_id, sequence)
            if response.get("status") == "OK":
                successful_logs += 1
            else:
                failures.append(
                    f"log {sequence}: {response.get('reason', 'producer rejected log')}"
                )
        except (OSError, ConnectionError, ValueError) as exc:
            failures.append(f"log {sequence}: {exc}")
    total_time = time.perf_counter() - start
    avg_time_ms = total_time * 1000.0 / args.count
    state = load_validator_state()
    success = successful_logs == args.count and state["synchronized"]
    notes = (
        f"committed={successful_logs}/{args.count}"
        + (f"; {'; '.join(failures[:5])}" if failures else "")
    )

    print(f"Normal experiment count={args.count}")
    print(f"Total time: {total_time:.6f} sec")
    print(f"Avg time per log: {avg_time_ms:.3f} ms")
    print(f"Synchronized: {state['synchronized']}")
    append_result(
        args.output,
        {
            "experiment_type": "normal",
            "count": args.count,
            "total_time_sec": format_seconds(total_time),
            "avg_time_ms": format_milliseconds(avg_time_ms),
            "success": success,
            "synchronized": state["synchronized"],
            "notes": notes,
        },
    )
    return 0 if success else 1


def run_hmac(args: argparse.Namespace) -> int:
    """Measure HMAC signing and verification throughput."""
    unsigned_messages = [
        {
            "type": "LOG",
            "node_id": args.node_id,
            "message": f"STATUS=NORMAL ACTION=HMAC_EXPERIMENT SEQUENCE={sequence}",
        }
        for sequence in range(args.count)
    ]

    sign_start = time.perf_counter()
    signed_messages = [
        attach_signature(message, sender_id=args.node_id)
        for message in unsigned_messages
    ]
    sign_time = time.perf_counter() - sign_start

    verify_start = time.perf_counter()
    verification_results = [
        verify_message_signature(message)[0] for message in signed_messages
    ]
    verify_time = time.perf_counter() - verify_start

    verified_count = sum(verification_results)
    avg_sign_ms = sign_time * 1000.0 / args.count
    avg_verify_ms = verify_time * 1000.0 / args.count
    success = verified_count == args.count

    print(f"Signed messages: {len(signed_messages)}")
    print(f"Verified messages: {verified_count}")
    print(f"Signing time: {sign_time:.6f} sec")
    print(f"Verification time: {verify_time:.6f} sec")
    print(f"Avg signing time: {avg_sign_ms:.3f} ms")
    print(f"Avg verification time: {avg_verify_ms:.3f} ms")
    append_result(
        args.output,
        {
            "experiment_type": "hmac",
            "count": args.count,
            "sign_time_sec": format_seconds(sign_time),
            "verify_time_sec": format_seconds(verify_time),
            "avg_sign_ms": format_milliseconds(avg_sign_ms),
            "avg_verify_ms": format_milliseconds(avg_verify_ms),
            "success": success,
            "notes": f"verified={verified_count}/{args.count}",
        },
    )
    return 0 if success else 1


def run_tamper(args: argparse.Namespace) -> int:
    """Apply an explicit tamper operation and measure whether it is detected."""
    chain_file = VALIDATOR_CHAIN_FILES[args.validator]
    notes: list[str] = []
    try:
        chain = load_chain(chain_file)
        notes.append(apply_tamper(chain, args.block_index, args.tamper_type))
        save_chain(chain_file, chain)
        chain_valid, chain_errors = verify_chain_detailed(chain)
        proofs_valid = all(validate_commit_proof(block)[0] for block in chain)
        state = load_validator_state()
        detected = not chain_valid or not proofs_valid or not state["synchronized"]
        notes.extend(error["message"] for error in chain_errors[:3])
    except (ChainLoadError, OSError, ValueError) as exc:
        chain_valid = False
        detected = False
        state = {"synchronized": False}
        notes.append(f"tamper failed: {exc}")

    print(f"Tamper type: {args.tamper_type}")
    print(f"Validator: {args.validator}, block index: {args.block_index}")
    print(f"Detected: {detected}")
    print(f"Selected chain valid: {chain_valid}")
    append_result(
        args.output,
        {
            "experiment_type": "tamper",
            "validator": args.validator,
            "block_index": args.block_index,
            "tamper_type": args.tamper_type,
            "detected": detected,
            "chain_valid": chain_valid,
            "synchronized": state["synchronized"],
            "success": detected,
            "notes": "; ".join(notes),
        },
    )
    return 0 if detected else 1


def run_recovery_check(args: argparse.Namespace) -> int:
    """Record validator state before and after a manual recovery observation window."""
    before = load_validator_state()
    before_counts = before["counts"]
    highest_count = max(before_counts.values())
    missing_blocks = sum(highest_count - count for count in before_counts.values())

    print(f"Before synchronized: {before['synchronized']}")
    print(f"Before block counts: {before_counts}")
    print(f"Missing blocks: {missing_blocks}")
    if args.wait > 0:
        print(
            f"Waiting {args.wait:.1f} sec for externally managed validator recovery..."
        )
        time.sleep(args.wait)

    after = load_validator_state()
    recovery_success = after["synchronized"]
    notes = f"before_counts={before_counts}; after_counts={after['counts']}"
    print(f"After synchronized: {after['synchronized']}")
    print(f"After block counts: {after['counts']}")
    print(f"Recovery success: {recovery_success}")
    append_result(
        args.output,
        {
            "experiment_type": "recovery-check",
            "before_synchronized": before["synchronized"],
            "after_synchronized": after["synchronized"],
            "missing_blocks": missing_blocks,
            "recovery_success": recovery_success,
            "success": recovery_success,
            "notes": notes,
        },
    )
    return 0 if recovery_success else 1


def run_c_client_check(args: argparse.Namespace) -> int:
    """Count committed logs for one external C client node ID."""
    state = load_validator_state()
    found_counts = {
        validator_id: sum(
            1
            for block in chain
            if isinstance(block, dict)
            and isinstance(block.get("log_data"), dict)
            and block["log_data"].get("node_id") == args.node_id
        )
        for validator_id, chain in state["chains"].items()
    }
    same_count = len(set(found_counts.values())) == 1
    found_log_count = min(found_counts.values())
    success = found_log_count > 0 and same_count and state["synchronized"]

    print(f"C client node ID: {args.node_id}")
    print(f"Found log counts: {found_counts}")
    print(f"Synchronized: {state['synchronized']}")
    print(f"Success: {success}")
    append_result(
        args.output,
        {
            "experiment_type": "c-client-check",
            "node_id": args.node_id,
            "found_log_count": found_log_count,
            "synchronized": state["synchronized"],
            "success": success,
            "notes": f"per_validator_counts={found_counts}",
        },
    )
    return 0 if success else 1


def positive_count(value: str) -> int:
    count = int(value)
    if count < 1:
        raise argparse.ArgumentTypeError("count must be at least 1")
    return count


def nonnegative_float(value: str) -> float:
    number = float(value)
    if number < 0:
        raise argparse.ArgumentTypeError("value must not be negative")
    return number


def add_output_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Append CSV results to this file (default: {DEFAULT_OUTPUT}).",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run quantitative distributed log experiments."
    )
    subparsers = parser.add_subparsers(dest="experiment", required=True)

    normal = subparsers.add_parser(
        "normal", help="Measure end-to-end LOG commit latency."
    )
    normal.add_argument("--count", type=positive_count, default=10)
    normal.add_argument("--node-id", default="EXPERIMENT-NODE-01")
    add_output_argument(normal)
    normal.set_defaults(handler=run_normal)

    hmac = subparsers.add_parser(
        "hmac", help="Measure HMAC signing and verification performance."
    )
    hmac.add_argument("--count", type=positive_count, default=1000)
    hmac.add_argument("--node-id", default="HMAC-EXPERIMENT-01")
    add_output_argument(hmac)
    hmac.set_defaults(handler=run_hmac)

    tamper = subparsers.add_parser(
        "tamper", help="Tamper with one stored chain and check detection."
    )
    tamper.add_argument("--validator", choices=VALIDATOR_IDS, required=True)
    tamper.add_argument("--block-index", type=int, required=True)
    tamper.add_argument("--tamper-type", choices=TAMPER_TYPES, required=True)
    add_output_argument(tamper)
    tamper.set_defaults(handler=run_tamper)

    recovery = subparsers.add_parser(
        "recovery-check",
        help="Record chain state before and after a manual recovery window.",
    )
    recovery.add_argument(
        "--wait",
        type=nonnegative_float,
        default=0.0,
        help="Seconds to wait before recording the after state.",
    )
    add_output_argument(recovery)
    recovery.set_defaults(handler=run_recovery_check)

    c_client = subparsers.add_parser(
        "c-client-check", help="Check committed blocks generated by the C client."
    )
    c_client.add_argument("--node-id", default="C-EQUIPMENT-01")
    add_output_argument(c_client)
    c_client.set_defaults(handler=run_c_client_check)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
