#!/usr/bin/env python3
"""Read-only validate or explicitly apply the controlled E13 hash migration.

Without ``--apply`` no writer lease or runtime artifact is created/modified;
successful static validation returns ``HOLD_REQUIRES_APPLY_LOCK`` because only
the locked apply path can make a concurrency-safe migration decision.
"""

from __future__ import annotations

import os

os.environ["PA_LOG_QUIET"] = "1"
os.environ["PA_DISABLE_FILE_LOG"] = "1"

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from price_action.execution.e13_policy_migration import (  # noqa: E402
    migrate_e13_policy_provenance,
)
from price_action.execution.exit_evidence import (  # noqa: E402
    E13_DEFAULT_CONFIG_PATH,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=E13_DEFAULT_CONFIG_PATH)
    parser.add_argument("--expected-old-hash", required=True)
    parser.add_argument("--expected-new-hash", required=True)
    parser.add_argument("--operator-reason", required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "acquire the global lease and migrate; omission performs mutation-free "
            "static validation and returns HOLD_REQUIRES_APPLY_LOCK"
        ),
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        payload = migrate_e13_policy_provenance(
            config_path=args.config,
            expected_old_hash=args.expected_old_hash,
            expected_new_hash=args.expected_new_hash,
            operator_reason=args.operator_reason,
            apply=args.apply,
        )
    except Exception as exc:
        mutation_marker = getattr(exc, "mutated_real_artifacts", None)
        mutation_paths = getattr(exc, "mutation_paths", None)
        payload = {
            "status": "FAIL_CLOSED",
            "fail_closed": True,
            "apply_requested": bool(args.apply),
            "dry_run": not args.apply,
            "mutated_real_artifacts": True if mutation_marker is True else None,
            "mutation_outcome": "mutated" if mutation_marker is True else "unknown",
            "mutated_artifact_paths": (
                list(mutation_paths) if mutation_paths is not None else None
            ),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "network_calls": 0,
            "exchange_calls": 0,
        }
        print(json.dumps(payload, sort_keys=True, allow_nan=False))
        return 2

    if args.as_json:
        print(json.dumps(payload, sort_keys=True, allow_nan=False))
    else:
        print(
            f"{payload['status']} dry_run={payload['dry_run']} "
            f"old={payload['computed_legacy_hash']} new={payload['computed_new_hash']}"
        )
    if payload["status"] == "HOLD_WRITER_BUSY":
        return 3
    if payload["status"].startswith("HOLD_"):
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
