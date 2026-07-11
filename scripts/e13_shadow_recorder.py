#!/usr/bin/env python3
"""Operate the local-only E13 ATR shadow state; never touches an exchange."""

from __future__ import annotations

import os

os.environ["PA_LOG_QUIET"] = "1"
os.environ["PA_DISABLE_FILE_LOG"] = "1"

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

from price_action.execution.e13_shadow import (
    AtrChandelierShadowRecorder,
    E13ShadowBusyError,
    E13ShadowLease,
)
from price_action.execution.e13_storage import (
    e13_policy_migration_transaction_path,
    validate_e13_artifact_path,
)
from price_action.execution.exit_evidence import (
    E13_DEFAULT_CONFIG_PATH,
    load_e13_policy,
)


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("timestamp must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Local causal ATR-chandelier shadow recorder (zero exchange I/O)"
    )
    parser.add_argument("--config", type=Path, default=E13_DEFAULT_CONFIG_PATH)
    commands = parser.add_subparsers(dest="command", required=True)

    start = commands.add_parser("start")
    start.add_argument("--trade-id", required=True)
    start.add_argument("--side", choices=["long", "short"], required=True)
    start.add_argument("--ts-open", type=_aware_datetime, required=True)
    start.add_argument("--entry-price", type=float, required=True)
    start.add_argument("--initial-sl-price", type=float, required=True)

    bar = commands.add_parser("bar")
    bar.add_argument("--trade-id", required=True)
    bar.add_argument("--ts", type=_aware_datetime, required=True)
    bar.add_argument("--open", dest="open_price", type=float, required=True)
    bar.add_argument("--high", type=float, required=True)
    bar.add_argument("--low", type=float, required=True)
    bar.add_argument("--close", type=float, required=True)
    bar.add_argument("--atr", type=float, required=True)

    baseline = commands.add_parser("baseline-close")
    baseline.add_argument("--trade-id", required=True)
    baseline.add_argument("--ts-close", type=_aware_datetime, required=True)
    baseline.add_argument("--exit-price", type=float, required=True)
    baseline.add_argument("--close-reason", required=True)

    commands.add_parser("status")
    return parser


def main() -> int:
    args = _parser().parse_args()
    policy = load_e13_policy(args.config)
    try:
        with E13ShadowLease(policy.shadow_state_path) as lease:
            migration_transaction = validate_e13_artifact_path(
                e13_policy_migration_transaction_path(),
                field="E13 policy migration transaction",
            )
            if migration_transaction.exists():
                result = {
                    "status": "HOLD_POLICY_MIGRATION_PENDING",
                    "fail_closed": True,
                    "retryable": False,
                    "migration_transaction_path": str(migration_transaction),
                    "mutated_state_or_evidence": False,
                    "exchange_calls": 0,
                }
                print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
                return 4
            recorder = AtrChandelierShadowRecorder(policy, lease=lease)
            if args.command == "start":
                result = recorder.start_trade(
                    trade_id=args.trade_id,
                    side=args.side,
                    ts_open=args.ts_open,
                    entry_price=args.entry_price,
                    initial_sl_price=args.initial_sl_price,
                )
            elif args.command == "bar":
                result = recorder.observe_closed_bar(
                    trade_id=args.trade_id,
                    ts=args.ts,
                    open_price=args.open_price,
                    high=args.high,
                    low=args.low,
                    close=args.close,
                    atr=args.atr,
                )
            elif args.command == "baseline-close":
                result = recorder.record_baseline_close(
                    trade_id=args.trade_id,
                    ts_close=args.ts_close,
                    exit_price=args.exit_price,
                    close_reason=args.close_reason,
                )
            else:
                result = recorder.status()
    except E13ShadowBusyError as exc:
        result = {
            "status": "HOLD_WRITER_BUSY",
            "fail_closed": True,
            "retryable": True,
            "lease_busy": True,
            "writer_lock_path": str(exc.lock_path),
            "mutated_state_or_evidence": False,
            "exchange_calls": 0,
        }
        print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
        return 3
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
