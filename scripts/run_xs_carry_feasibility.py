#!/usr/bin/env python3
"""Run the pre-registered XS-carry PRIMARY feasibility experiment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from price_action.backtest.xs_carry import (
    XSCarryConfig,
    load_local_xs_carry_data,
    run_xs_carry_feasibility,
)


def _parser() -> argparse.ArgumentParser:
    repository = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(
        description=(
            "Weekly 7d-score top/bottom-3 spot-hedged XS funding carry. "
            "Output is always FEASIBILITY_NOT_PROMOTION."
        )
    )
    parser.add_argument("--funding-db", type=Path, default=repository / "data" / "funding.duckdb")
    parser.add_argument("--market-db", type=Path, default=repository / "data" / "market.duckdb")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default="2026-06-30")
    parser.add_argument("--oos-start", default="2024-01-01")
    parser.add_argument("--permutations", type=int, default=500)
    parser.add_argument("--random-seed", type=int, default=42)
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional JSON report path. Parent directories are created.",
    )
    parser.add_argument(
        "--weekly-output",
        type=Path,
        help="Optional CSV path for the period-level audit trail.",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    config = XSCarryConfig(
        start=args.start,
        end=args.end,
        oos_start=args.oos_start,
        permutations=args.permutations,
        random_seed=args.random_seed,
    )
    data = load_local_xs_carry_data(args.funding_db, args.market_db, config)
    result = run_xs_carry_feasibility(data, config)
    payload = result.to_dict()

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    if args.weekly_output:
        args.weekly_output.parent.mkdir(parents=True, exist_ok=True)
        weekly = result.weekly_returns.copy()
        for column in ("top_symbols", "bottom_symbols"):
            weekly[column] = weekly[column].map(lambda values: ",".join(values))
        weekly.to_csv(args.weekly_output, index=False)

    concise = {
        "status": payload["status"],
        "promotion_eligible": payload["promotion_eligible"],
        "coverage": payload["coverage"],
        "metrics": payload["metrics"],
        "gates": payload["gates"],
        "reproducibility": payload["reproducibility"],
        "output": str(args.output.resolve()) if args.output else None,
        "weekly_output": str(args.weekly_output.resolve()) if args.weekly_output else None,
    }
    print(json.dumps(concise, indent=2, sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
