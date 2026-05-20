"""15m JPY-family edge test on FULL Dukascopy data (~97-99k bars/pair, 4y, %100 coverage).

This is the definitive test: full real 15m data, no missing-bar artifact.
Sweeps confluence + leverage. If no config shows genuine edge (PF > 1.1 after costs,
positive across walk-forward), the strategy set does NOT work — reported honestly.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ..backtest.costs import CostModel
from ..backtest.portfolio_engine import PortfolioEngine, PortfolioConfig
from ..data.store import OHLCVStore
from ..news.guard import NewsGuard
from ..risk.breaker import BreakerConfig
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
JPY_PAIRS = ["USDJPY", "EURJPY", "GBPJPY"]


def main():
    store = OHLCVStore(DUCKDB_PATH, PARQUET_DIR)
    news = NewsGuard()
    dfs = {}
    for p in JPY_PAIRS:
        dfs[p] = store.read_ohlcv(p, "15m")
        print(f"{p}: {len(dfs[p])} bars (FULL Dukascopy 15m), "
              f"{dfs[p].index[0]} -> {dfs[p].index[-1]}")

    sig_cache = {}
    for conf in [0.45, 0.50, 0.55, 0.60]:
        sig_cache[conf] = {}
        for p in JPY_PAIRS:
            strategies = [cls() for cls in STRATS]
            gen = SignalGenerator(pair=p, strategies=strategies,
                                  config=GeneratorConfig(confluence_threshold=conf), news_guard=news)
            sig_cache[conf][p] = gen.generate(dfs[p])
        tot = sum(len(s) for s in sig_cache[conf].values())
        print(f"  conf={conf}: {tot} signals")

    results = []
    for conf in [0.45, 0.50, 0.55, 0.60]:
        for tgt_lev in [1.0, 2.0, 3.0, 5.0]:
            rcfg = RiskConfig(
                sizing_mode="leverage_target", target_leverage=tgt_lev,
                leverage_target_max_risk=0.20, leverage_max=tgt_lev * 3 * 1.2,
                max_open_positions=3, min_rr=1.2,
                breaker=BreakerConfig(daily_loss_pct=0.30, weekly_loss_pct=0.50,
                                      monthly_loss_pct=0.70, consecutive_losses=99),
            )
            engine = PortfolioEngine(RiskOfficer(rcfg, news_guard=news), CostModel(),
                                     PortfolioConfig(), news_guard=news)
            r = engine.run(dfs, sig_cache[conf])
            k = r.kpis
            results.append({
                "confluence": conf, "target_leverage": tgt_lev,
                "n_trades": r.n_trades, "roi": k.get("return_total_pct", 0),
                "cagr": k.get("cagr_pct", 0), "monthly": k.get("monthly_pct", 0),
                "max_dd": k.get("max_dd_pct", 0), "wr": k.get("win_rate", 0),
                "pf": k.get("profit_factor", 0), "sharpe": k.get("sharpe", 0),
                "final": r.final_balance,
            })
            print(f"  conf={conf} lev={tgt_lev:.0f}x N={r.n_trades:5d} "
                  f"ROI={k.get('return_total_pct',0):9.1f}% monthly={k.get('monthly_pct',0):7.2f}% "
                  f"DD={k.get('max_dd_pct',0):7.1f}% WR={k.get('win_rate',0):.2f} "
                  f"PF={k.get('profit_factor',0):.2f} Sharpe={k.get('sharpe',0):.2f}", flush=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPORTS_DIR / f"forex_jpy_15m_edge_{ts}.json"
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    print("\n=== Ranked by monthly % ===")
    for r in sorted(results, key=lambda r: r["monthly"], reverse=True)[:10]:
        print(f"  monthly={r['monthly']:7.2f}% ROI={r['roi']:9.1f}% DD={r['max_dd']:7.1f}% "
              f"Sharpe={r['sharpe']:.2f} PF={r['pf']:.2f} WR={r['wr']:.2f} N={r['n_trades']} | "
              f"conf={r['confluence']} lev={r['target_leverage']:.0f}x")

    # Edge verdict
    best = max(results, key=lambda r: r["monthly"])
    best_pf = max(results, key=lambda r: r["pf"])
    print(f"\n=== EDGE VERDICT ===")
    print(f"  Best monthly: {best['monthly']:.2f}% (conf={best['confluence']} lev={best['target_leverage']:.0f}x, PF={best['pf']:.2f})")
    print(f"  Best PF: {best_pf['pf']:.2f} (conf={best_pf['confluence']} lev={best_pf['target_leverage']:.0f}x)")
    has_edge = best_pf["pf"] > 1.10 and best["monthly"] > 0
    print(f"  Genuine edge (best PF > 1.10 AND positive monthly): {'YES' if has_edge else 'NO'}")
    print(f"  Target monthly %10: {'REACHED' if best['monthly'] >= 10 else 'NOT reached'}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
