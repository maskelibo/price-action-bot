#!/usr/bin/env python3
"""Advance E13 from local journal + completed 15m bars (zero network/exchange I/O)."""

from __future__ import annotations

import os

# Keep --json machine-readable even when disk-health logging would normally emit
# to stdout, and prevent this short probe from opening the shared app log.
os.environ["PA_LOG_QUIET"] = "1"
os.environ["PA_DISABLE_FILE_LOG"] = "1"

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from price_action.execution.e13_shadow_sync import sync_e13_shadow  # noqa: E402


def _aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("--through must be ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise argparse.ArgumentTypeError("--through must include a timezone")
    return parsed.astimezone(UTC)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--market", type=Path, required=True)
    parser.add_argument("--through", type=_aware_datetime)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        payload = sync_e13_shadow(
            args.journal,
            args.market,
            config_path=args.config,
            through=args.through,
            dry_run=args.dry_run,
        )
    except Exception as exc:  # fail-closed CLI boundary; no artifact fabrication
        mutation_marker = getattr(exc, "mutated_real_artifacts", None)
        mutated = True if mutation_marker is True else None
        mutation_paths = getattr(exc, "mutation_paths", None)
        payload = {
            "status": "FAIL_CLOSED",
            "fail_closed": True,
            "dry_run": bool(args.dry_run),
            "mutated_real_artifacts": mutated,
            "mutation_outcome": "mutated" if mutated is True else "unknown",
            "mutated_artifact_paths": (
                list(mutation_paths) if mutation_paths is not None else None
            ),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "network_calls": 0,
            "exchange_calls": 0,
        }
        if args.as_json:
            print(json.dumps(payload, sort_keys=True, allow_nan=False))
        else:
            print(f"FAIL_CLOSED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(payload, sort_keys=True, allow_nan=False))
    else:
        print(
            f"{payload['status']} started={payload['trades_started']} "
            f"bars={payload['bars_applied']} evidence={payload['evidence_emitted']} "
            f"open={payload['open_shadow_trades']} issues={len(payload['issues'])} "
            f"dry_run={payload['dry_run']}"
        )
    # StartInterval launchd jobs naturally retry on the next tick. A concurrent
    # writer is expected contention, but must be visible and non-successful.
    if payload.get("lease_busy"):
        return 3
    if payload.get("status") == "HOLD_POLICY_MIGRATION_PENDING":
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
