#!/usr/bin/env python3
"""Consume authorized TF evidence into signal-only shadow specifications.

This command never starts a process and never contacts an exchange.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from price_action.lab.tf_shadow_promotion import scan_evidence_directory  # noqa: E402


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fail-closed independent-OOS → signal-only shadow spec consumer"
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=ROOT / "reports" / "tf_robustness",
    )
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument(
        "--audit-output",
        type=Path,
        default=ROOT / "reports" / "tf_shadow_pipeline" / "latest.json",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = scan_evidence_directory(
        evidence_dir=args.evidence_dir,
        repo_root=args.repo_root,
        audit_output=args.audit_output,
    )
    print(json.dumps(report["counts"], sort_keys=True))
    return 1 if report["counts"]["conflicts"] or report["counts"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
