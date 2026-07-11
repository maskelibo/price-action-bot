#!/usr/bin/env python3
"""Print the read-only E13 exit-policy evidence gate as one strict JSON value."""

from __future__ import annotations

import os

# This command is a machine-readable probe.  Suppress package import-time sinks
# before importing ``price_action.execution`` so disk warnings cannot corrupt
# stdout and the probe itself cannot append to the process-wide app log.
os.environ["PA_LOG_QUIET"] = "1"
os.environ["PA_DISABLE_FILE_LOG"] = "1"

import argparse
import json
from pathlib import Path

from price_action.execution.exit_evidence import (
    E13_DEFAULT_CONFIG_PATH,
    e13_exit_evidence,
)

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only E13 ATR-exit evidence gate")
    parser.add_argument(
        "--journal",
        type=Path,
        default=ROOT / "data" / "futures_journal_v15p2.duckdb",
    )
    parser.add_argument("--config", type=Path, default=E13_DEFAULT_CONFIG_PATH)
    args = parser.parse_args()

    payload = e13_exit_evidence(args.journal, config_path=args.config)
    print(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
