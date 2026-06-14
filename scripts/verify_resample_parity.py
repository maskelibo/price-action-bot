"""30m/45m resample parity audit — B1 blocker clearance tool.

Compares live ccxt 5m->30m/45m resample against market.duckdb stored 5m->30m/45m.
Must pass for >= 7 consecutive calendar days before 30m/45m legs are promoted from
staged to active in risk_multitf_stack_paper_l12.yaml.

B1 BLOCKER (configs/risk_multitf_stack_paper_l12.yaml):
    status: OPEN
    Cleared when: max_close_diff_pct < 0.001 (0.1%) across all 10 symbols
                  for >= 7 calendar days of consecutive checks.

Usage:
    .venv/bin/python scripts/verify_resample_parity.py
    .venv/bin/python scripts/verify_resample_parity.py --rule 30min --days 7

Output:
    logs/parity/resample_parity_YYYY-MM-DD.jsonl  (one line per symbol per check)
    Console summary: PASS / FAIL per symbol/rule
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from scripts.futures_trade_30m45m import SYMBOLS_10, verify_resample_parity


def main():
    parser = argparse.ArgumentParser(description="Resample parity audit (B1 blocker)")
    parser.add_argument("--rule", default="both", choices=["30min", "45min", "both"],
                        help="Resample rule to check (default: both)")
    parser.add_argument("--symbols", nargs="+", default=None,
                        help="Symbols to check (default: all 10)")
    args = parser.parse_args()

    rules = ["30min", "45min"] if args.rule == "both" else [args.rule]
    syms = args.symbols or SYMBOLS_10

    log_dir = ROOT / "logs" / "parity"
    log_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now(UTC).strftime("%Y-%m-%d")
    log_path = log_dir / f"resample_parity_{today}.jsonl"

    print(f"{'='*70}")
    print(f"RESAMPLE PARITY AUDIT  {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%SZ')}")
    print(f"Rules: {rules}  Symbols: {len(syms)}")
    print(f"B1 BLOCKER: OPEN — 30m/45m legs staged until parity confirmed >=7d")
    print(f"{'='*70}")

    all_pass = True
    rows = []

    for rule in rules:
        print(f"\n--- Rule: {rule} ---")
        print(f"{'symbol':<12} {'n_live':>8} {'n_db':>8} {'n_common':>10} "
              f"{'max_close_diff':>16} {'max_vol_diff':>14} {'parity':>8}")
        for sym in syms:
            res = verify_resample_parity(sym, rule)
            res["check_ts"] = datetime.now(UTC).isoformat()
            rows.append(res)

            parity_str = "PASS" if res["parity_ok"] else "FAIL"
            err_str = f" ERR={res['error']}" if res["error"] else ""
            print(
                f"{sym:<12} {res['n_live_bars']:>8} {res['n_db_bars']:>8} {res['n_common']:>10} "
                f"{res['max_close_diff_pct']:>14.6f} {res['max_vol_diff_pct']:>13.6f} {parity_str:>8}{err_str}"
            )
            if not res["parity_ok"]:
                all_pass = False

    # Write log
    with open(log_path, "a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")

    print(f"\n{'='*70}")
    if all_pass:
        print(f"OVERALL: PASS — all symbols parity OK for rules {rules}")
        print(f"B1 status: accumulate {len(rows)}-row record; need >=7 calendar days of PASS")
    else:
        print(f"OVERALL: FAIL — parity gap detected (see rows above)")
        print(f"B1 status: OPEN — DO NOT enable 30m/45m legs until all PASS")
    print(f"Log: {log_path}")
    print(f"{'='*70}")

    # Check consecutive days
    _check_consecutive_days(log_dir, rules)

    return 0 if all_pass else 1


def _check_consecutive_days(log_dir: Path, rules: list[str]) -> None:
    """Read all parity logs and count consecutive passing days."""
    import glob
    import re

    pattern = str(log_dir / "resample_parity_*.jsonl")
    files = sorted(glob.glob(pattern))
    if not files:
        return

    day_results: dict[str, bool] = {}
    for fp in files:
        m = re.search(r"resample_parity_(\d{4}-\d{2}-\d{2})\.jsonl", fp)
        if not m:
            continue
        day = m.group(1)
        day_pass = True
        try:
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    row = json.loads(line.strip())
                    if row.get("resample_rule" if "resample_rule" in row else "rule") in rules:
                        if not row.get("parity_ok", False):
                            day_pass = False
        except Exception:
            day_pass = False
        day_results[day] = day_results.get(day, True) and day_pass

    days = sorted(day_results.keys())
    consec = 0
    for d in reversed(days):
        if day_results[d]:
            consec += 1
        else:
            break

    print(f"\nB1 PARITY HISTORY: {consec} consecutive passing day(s) (need 7)")
    if consec >= 7:
        print("B1 BLOCKER: READY TO CLEAR — parity confirmed >=7 days")
        print("  Next step: update deploy_blockers B1 status to CLEARED in")
        print("  configs/risk_multitf_stack_paper_l12.yaml, then enable 30m/45m.")
    else:
        print(f"B1 BLOCKER: OPEN — {7 - consec} more passing day(s) needed")


if __name__ == "__main__":
    sys.exit(main())
