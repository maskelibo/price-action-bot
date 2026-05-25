"""JPY-family portfolio backtest on real yfinance data (1h x 2y, 100% coverage).

Tests USDJPY + EURJPY + GBPJPY as a portfolio with shared equity, 5x leverage cap.
Sweeps confluence + target_leverage to find best monthly return.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ..backtest.costs import CostModel
from ..backtest.portfolio_engine import PortfolioEngine, PortfolioConfig
from ..data.yfinance_ingest import fetch_yf
from ..news.guard import NewsGuard
from ..risk.breaker import BreakerConfig
from ..risk.officer import RiskConfig, RiskOfficer
from ..settings import REPORTS_DIR
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
    news = NewsGuard()
    dfs = {}
    for p in JPY_PAIRS:
        dfs[p] = fetch_yf(p, "2024-06-01", "2026-05-01", interval="1h")
        print(f"{p}: {len(dfs[p])} bars (real yfinance 1h)")

    # cache signals per confluence
    sig_cache = {}
    for conf in [0.45, 0.50, 0.55]:
        sig_cache[conf] = {}
        for p in JPY_PAIRS:
            strategies = [cls() for cls in STRATS]
            gen = SignalGenerator(pair=p, strategies=strategies,
                                  config=GeneratorConfig(confluence_threshold=conf), news_guard=news)
            sig_cache[conf][p] = gen.generate(dfs[p])
        tot = sum(len(s) for s in sig_cache[conf].values())
        print(f"  conf={conf}: {tot} total signals")

    results = []
    for conf in [0.45, 0.50, 0.55]:
        for tgt_lev in [2.0, 3.0, 5.0]:
            for max_risk in [0.15, 0.25]:
                rcfg = RiskConfig(
                    sizing_mode="leverage_target",
                    target_leverage=tgt_lev,
                    leverage_target_max_risk=max_risk,
                    leverage_max=tgt_lev * 3 * 1.2,  # 3 pairs * lev + buffer
                    max_open_positions=3,
                    min_rr=1.2,
                    breaker=BreakerConfig(daily_loss_pct=0.30, weekly_loss_pct=0.50,
                                          monthly_loss_pct=0.70, consecutive_losses=99),
                )
                engine = PortfolioEngine(RiskOfficer(rcfg, news_guard=news), CostModel(),
                                         PortfolioConfig(), news_guard=news)
                r = engine.run(dfs, sig_cache[conf])
                k = r.kpis
                results.append({
                    "confluence": conf, "target_leverage": tgt_lev, "max_risk": max_risk,
                    "n_trades": r.n_trades, "roi": k.get("return_total_pct", 0),
                    "cagr": k.get("cagr_pct", 0), "monthly": k.get("monthly_pct", 0),
                    "max_dd": k.get("max_dd_pct", 0), "wr": k.get("win_rate", 0),
                    "pf": k.get("profit_factor", 0), "sharpe": k.get("sharpe", 0),
                    "final": r.final_balance,
                })
                print(f"  conf={conf} lev={tgt_lev:.0f}x maxR={max_risk*100:.0f}% "
                      f"N={r.n_trades:4d} ROI={k.get('return_total_pct',0):8.1f}% "
                      f"monthly={k.get('monthly_pct',0):6.2f}% DD={k.get('max_dd_pct',0):7.1f}% "
                      f"WR={k.get('win_rate',0):.2f} PF={k.get('profit_factor',0):.2f} "
                      f"Sharpe={k.get('sharpe',0):.2f}", flush=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPORTS_DIR / f"forex_jpy_portfolio_{ts}.json"
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")

    print("\n=== Ranked by monthly % ===")
    for r in sorted(results, key=lambda r: r["monthly"], reverse=True)[:8]:
        print(f"  monthly={r['monthly']:6.2f}% ROI={r['roi']:8.1f}% DD={r['max_dd']:7.1f}% "
              f"Sharpe={r['sharpe']:.2f} PF={r['pf']:.2f} N={r['n_trades']} | "
              f"conf={r['confluence']} lev={r['target_leverage']:.0f}x maxR={r['max_risk']*100:.0f}%")
    print(f"\nTarget: monthly %10. Best achieved: {max(r['monthly'] for r in results):.2f}%")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
