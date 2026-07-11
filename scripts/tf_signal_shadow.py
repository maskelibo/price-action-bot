#!/usr/bin/env python3
"""Run authorized local TF signal shadows (no exchange/order capability)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from price_action.lab.tf_signal_shadow import run_default_scan, run_shadow_config  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    args = parser.parse_args()
    if args.config:
        path = args.config if args.config.is_absolute() else ROOT / args.config
        report = run_shadow_config(path, repo_root=ROOT)
    else:
        report = run_default_scan(repo_root=ROOT)
    print(json.dumps(report, indent=2, sort_keys=True))
    if args.config:
        return 1 if report["counts"]["errors"] else 0
    return (
        1
        if any(str(row.get("status", "")).startswith("REJECTED") for row in report["results"])
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
