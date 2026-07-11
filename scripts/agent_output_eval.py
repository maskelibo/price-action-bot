#!/usr/bin/env python3
"""Evaluate stored agent artifacts with the offline quality contract."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ["PA_LOG_QUIET"] = "1"
os.environ["PA_DISABLE_FILE_LOG"] = "1"

from price_action.lab.agent_output_eval import (  # noqa: E402
    AgentOutputEvalError,
    evaluate_agent_outputs,
    load_eval_config,
    write_report,
)


def _timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise AgentOutputEvalError("--as-of must include a timezone")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "agent_output_eval.yaml",
    )
    parser.add_argument(
        "--input",
        action="append",
        help="Repository-relative artifact path; repeated values override config inputs.",
    )
    parser.add_argument(
        "--no-inputs",
        action="store_true",
        help="Evaluate the explicit no-input fail-closed path.",
    )
    parser.add_argument("--as-of", help="Timezone-aware deterministic evaluation timestamp.")
    parser.add_argument("--report", help="Repository-relative report path override.")
    parser.add_argument("--no-report", action="store_true", help="Do not write the JSON report.")
    args = parser.parse_args(argv)
    if args.no_inputs and args.input:
        parser.error("--no-inputs cannot be combined with --input")

    try:
        config = load_eval_config(args.config, repo_root=ROOT)
        inputs = [] if args.no_inputs else args.input
        report = evaluate_agent_outputs(
            config,
            input_paths=inputs,
            evaluated_at=_timestamp(args.as_of),
        )
        if not args.no_report:
            output = write_report(report, config, path=args.report)
            report["report_path"] = str(output.relative_to(ROOT))
    except (AgentOutputEvalError, OSError, UnicodeError) as exc:
        print(
            json.dumps(
                {
                    "schema_version": "agent-output-eval-error-v1",
                    "status": "FAIL",
                    "error": f"{type(exc).__name__}:{exc}",
                    "promotion_authorized": False,
                    "live_authorized": False,
                    "order_authorized": False,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 2

    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    if report["status"] == "PASS":
        return 0
    return 3 if report["status"] == "HOLD" else 4


if __name__ == "__main__":
    raise SystemExit(main())
