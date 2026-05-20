"""Leverage-target aggressive sweep — test full-leverage sizing for high ROI.

sizing_mode='leverage_target': position notional = equity * target_leverage.
Compounding: equity grows → position grows. This is the AGGRESSIVE mode.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone

from ..backtest.costs import CostModel
from ..backtest.engine import BacktestEngine, EngineConfig
from ..backtest.monte_carlo import monte_carlo_shuffle
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


def main():
    store = OHLCVStore(DUCKDB_PATH, PARQUET_DIR)
    df = store.read_ohlcv("USDJPY", "15m")
    print(f"USDJPY bars: {len(df)}")
    news = NewsGuard()

    sig_cache = {}
    for conf in [0.50, 0.55]:
        strategies = [cls() for cls in STRATS]
        gen = SignalGenerator(pair="USDJPY", strategies=strategies,
                              config=GeneratorConfig(confluence_threshold=conf), news_guard=news)
        sig_cache[conf] = gen.generate(df)
        print(f"  conf={conf}: {len(sig_cache[conf])} signals")

    results = []
    # leverage_target sweep — wide breaker so it doesn't kill the aggressive run prematurely
    for conf in [0.50, 0.55]:
        for tgt_lev in [2.0, 3.0, 5.0, 10.0, 20.0, 30.0, 50.0]:
            for max_risk in [0.20, 0.35, 0.50]:
                rcfg = RiskConfig(
                    sizing_mode="leverage_target",
                    target_leverage=tgt_lev,
                    leverage_target_max_risk=max_risk,
                    leverage_max=tgt_lev * 4,  # allow the position
                    max_open_positions=2,
                    min_rr=1.2,
                    breaker=BreakerConfig(daily_loss_pct=0.50, weekly_loss_pct=0.70,
                                          monthly_loss_pct=0.90, consecutive_losses=99),
                )
                engine = BacktestEngine(RiskOfficer(rcfg, news_guard=news), CostModel(),
                                        EngineConfig(), news_guard=news)
                r = engine.run(df, sig_cache[conf], pair="USDJPY")
                k = r.kpis
                cagr = k.get("cagr_pct", 0)
                monthly = ((1 + cagr / 100) ** (1 / 12) - 1) * 100 if cagr > -100 else -100
                results.append({
                    "confluence": conf, "target_leverage": tgt_lev, "max_risk": max_risk,
                    "n_trades": r.n_trades, "roi_4y": k.get("return_total_pct", 0),
                    "cagr": cagr, "monthly_pct": monthly, "max_dd": k.get("max_dd_pct", 0),
                    "wr": k.get("win_rate", 0), "pf": k.get("profit_factor", 0),
                    "final": r.final_balance, "wiped": r.final_balance < 100,
                })
                print(f"  conf={conf} tgt_lev={tgt_lev:4.0f}x max_risk={max_risk*100:.0f}% "
                      f"N={r.n_trades:4d} ROI4y={k.get('return_total_pct',0):11.1f}% "
                      f"monthly={monthly:7.2f}% DD={k.get('max_dd_pct',0):8.1f}% "
                      f"final=${r.final_balance:13,.0f} {'[WIPED]' if r.final_balance<100 else ''}",
                      flush=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPORTS_DIR / f"forex_leverage_target_{ts}.json"
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    print("\n=== Configs reaching monthly >= %6.8 (yıllık %120) — sorted by DD ===")
    hit = [r for r in results if r["monthly_pct"] >= 6.8 and not r["wiped"]]
    if hit:
        for r in sorted(hit, key=lambda r: r["max_dd"], reverse=True)[:10]:
            print(f"  monthly={r['monthly_pct']:7.2f}% DD={r['max_dd']:8.1f}% WR={r['wr']:.2f} "
                  f"PF={r['pf']:.2f} N={r['n_trades']} | conf={r['confluence']} "
                  f"tgt_lev={r['target_leverage']:.0f}x max_risk={r['max_risk']*100:.0f}%")
    else:
        print("  NONE — no config reaches monthly %6.8 without wiping the account")

    print("\n=== Best monthly % overall (non-wiped) ===")
    nonwiped = [r for r in results if not r["wiped"] and r["n_trades"] > 10]
    for r in sorted(nonwiped, key=lambda r: r["monthly_pct"], reverse=True)[:8]:
        print(f"  monthly={r['monthly_pct']:7.2f}% DD={r['max_dd']:8.1f}% N={r['n_trades']} "
              f"final=${r['final']:,.0f} | tgt_lev={r['target_leverage']:.0f}x max_risk={r['max_risk']*100:.0f}%")

    n_wiped = sum(1 for r in results if r["wiped"])
    print(f"\n{n_wiped}/{len(results)} configs WIPED THE ACCOUNT (final < $100)")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
