"""Compare forex backtest with crypto bot champion.

Usage:
    python -m forex_bot.scripts.compare_with_crypto \\
        --forex-kpis reports/forex/forex_all_kpis_*.json \\
        --crypto-kpis reports/champion_kpis.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..reporting.compare_crypto import write_comparison_report
from ..settings import REPORTS_DIR


DEFAULT_RATIONALE = """\
Forex spot pairs annualize at ~5-12% realized vol vs crypto ~60-80%. With the same
strategy edge and similar trade frequency, forex ROI scales ~5-15× lower than crypto.
Spread+commission+swap drag is also higher relative to typical move size (5-15 pips
typical range vs 50-200 bps in crypto). Achieving %1800/yr on forex requires:
  - ≥1:200 leverage (pro / offshore only), OR
  - ≥3% risk-per-trade with higher signal rate, OR
  - Compounding aggressively from sub-optimal early DDs.
With retail-tier 1:30 and 1.5% risk/trade, realistic target band is %30-150/year with %15-25 DD.
"""


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--forex-kpis", required=True)
    p.add_argument("--crypto-kpis", required=True)
    p.add_argument("--out", default=None)
    args = p.parse_args(argv)
    forex = json.loads(Path(args.forex_kpis).read_text(encoding="utf-8"))
    crypto = json.loads(Path(args.crypto_kpis).read_text(encoding="utf-8"))
    # average across pairs if forex is per-pair list
    if isinstance(forex, list):
        agg = {}
        keys = ["return_total_pct", "cagr_pct", "max_dd_pct", "sharpe", "sortino", "calmar",
                "win_rate", "profit_factor", "expectancy_r", "n_trades"]
        for k in keys:
            vals = [r["kpis"].get(k, 0) for r in forex if r.get("kpis")]
            if vals:
                agg[k] = sum(vals) / len(vals) if k != "n_trades" else sum(vals)
        forex = agg
    out = Path(args.out) if args.out else REPORTS_DIR / "forex_vs_crypto.html"
    write_comparison_report(out, crypto, forex, rationale=DEFAULT_RATIONALE)
    print(f"wrote {out}")


if __name__ == "__main__":
    raise SystemExit(main())
