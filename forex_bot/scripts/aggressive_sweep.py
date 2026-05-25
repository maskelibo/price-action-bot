"""Aggressive optimization sweep targeting monthly %20.

Tests high-frequency / high-leverage / high-risk configs to find the ROI ceiling.
USDJPY-only (best edge pair from prior sweep).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ..backtest.costs import CostModel
from ..backtest.engine import BacktestEngine, EngineConfig
from ..backtest.monte_carlo import monte_carlo_shuffle
from ..data.store import OHLCVStore
from ..news.guard import NewsGuard
from ..risk.officer import RiskConfig, RiskOfficer
from ..settings import DUCKDB_PATH, PARQUET_DIR, REPORTS_DIR
from ..signals.generator import GeneratorConfig, SignalGenerator
from ..strategies import (
    AsiaRangeFadeStrategy, EngulfingSessionStrategy, FVGFillStrategy,
    LondonBreakoutStrategy, NyOpenReversalStrategy, OBRetestContinuationStrategy,
    PinBarSessionStrategy, SMCLiquiditySweepStrategy,
)

STRATS = (
    LondonBreakoutStrategy, NyOpenReversalStrategy, AsiaRangeFadeStrategy,
    SMCLiquiditySweepStrategy, OBRetestContinuationStrategy,
    FVGFillStrategy, PinBarSessionStrategy, EngulfingSessionStrategy,
)


def main():
    store = OHLCVStore(DUCKDB_PATH, PARQUET_DIR)
    df = store.read_ohlcv("USDJPY", "15m")
    print(f"USDJPY bars: {len(df)}")
    news = NewsGuard()

    # cache signals per confluence
    sig_cache = {}
    for conf in [0.40, 0.45, 0.50, 0.55]:
        strategies = [cls() for cls in STRATS]
        gen = SignalGenerator(pair="USDJPY", strategies=strategies,
                              config=GeneratorConfig(confluence_threshold=conf), news_guard=news)
        sig_cache[conf] = gen.generate(df)
        print(f"  conf={conf}: {len(sig_cache[conf])} signals")

    results = []
    grid = []
    for conf in [0.40, 0.45, 0.50, 0.55]:
        for risk in [0.02, 0.03, 0.05, 0.08]:
            for lev in [100.0, 200.0, 500.0]:
                for min_rr in [1.2, 1.5]:
                    grid.append((conf, risk, lev, min_rr))

    print(f"\n=== {len(grid)} aggressive configs ===\n")
    for i, (conf, risk, lev, min_rr) in enumerate(grid):
        rcfg = RiskConfig(
            risk_per_trade_pct=risk, max_risk_per_trade_pct=risk * 1.5,
            leverage_max=lev, max_open_positions=4, max_per_pair_pct=0.50,
            min_rr=min_rr,
        )
        engine = BacktestEngine(RiskOfficer(rcfg, news_guard=news), CostModel(),
                                EngineConfig(), news_guard=news)
        r = engine.run(df, sig_cache[conf], pair="USDJPY")
        k = r.kpis
        cagr = k.get("cagr_pct", 0)
        monthly = ((1 + cagr / 100) ** (1 / 12) - 1) * 100 if cagr > -100 else -100
        results.append({
            "confluence": conf, "risk_pct": risk, "leverage": lev, "min_rr": min_rr,
            "n_trades": r.n_trades, "roi_4y": k.get("return_total_pct", 0),
            "cagr": cagr, "monthly_pct": monthly, "max_dd": k.get("max_dd_pct", 0),
            "wr": k.get("win_rate", 0), "pf": k.get("profit_factor", 0),
            "sharpe": k.get("sharpe", 0), "final": r.final_balance,
        })
        print(f"[{i+1:3d}/{len(grid)}] conf={conf} risk={risk*100:.0f}% lev={lev:.0f} rr={min_rr} "
              f"N={r.n_trades:4d} ROI4y={k.get('return_total_pct',0):8.1f}% "
              f"monthly={monthly:6.2f}% DD={k.get('max_dd_pct',0):7.1f}% "
              f"WR={k.get('win_rate',0):.2f} PF={k.get('profit_factor',0):.2f}", flush=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPORTS_DIR / f"forex_aggressive_{ts}.json"
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    print("\n=== Top 10 by monthly % (DD < 60%) ===")
    valid = [r for r in results if r["max_dd"] > -60 and r["n_trades"] > 20]
    ranked = sorted(valid, key=lambda r: r["monthly_pct"], reverse=True)
    for r in ranked[:10]:
        print(f"  monthly={r['monthly_pct']:6.2f}% ROI4y={r['roi_4y']:9.1f}% DD={r['max_dd']:7.1f}% "
              f"WR={r['wr']:.2f} PF={r['pf']:.2f} N={r['n_trades']} | "
              f"conf={r['confluence']} risk={r['risk_pct']*100:.0f}% lev={r['leverage']:.0f} rr={r['min_rr']}")

    print("\n=== Top 5 by monthly % (any DD) ===")
    ranked_all = sorted([r for r in results if r["n_trades"] > 20], key=lambda r: r["monthly_pct"], reverse=True)
    for r in ranked_all[:5]:
        print(f"  monthly={r['monthly_pct']:6.2f}% ROI4y={r['roi_4y']:9.1f}% DD={r['max_dd']:7.1f}% "
              f"N={r['n_trades']} | conf={r['confluence']} risk={r['risk_pct']*100:.0f}% lev={r['leverage']:.0f}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
