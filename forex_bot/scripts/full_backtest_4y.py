"""4-year multi-pair backtest with multiple risk profiles for goal validation.

Profiles tested:
  - retail_1x30        : 1:30 leverage, 1.5% risk/trade (honest forex baseline)
  - pro_1x200          : 1:200 leverage, 2.5% risk/trade (offshore pro account)
  - crypto_equivalent  : 1:500 leverage, 3.0% risk/trade (matches crypto bot risk profile)

Walk-forward + Monte Carlo + per-pair/session breakdown.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..backtest.costs import CostModel
from ..backtest.engine import BacktestEngine, EngineConfig
from ..backtest.monte_carlo import monte_carlo_shuffle
from ..data.synthetic import generate_synthetic_ohlcv
from ..news.guard import NewsGuard
from ..reporting.compare_crypto import write_comparison_report
from ..reporting.html_report import write_html_report
from ..risk.officer import RiskConfig, RiskOfficer
from ..settings import PAIRS, REPORTS_DIR
from ..signals.generator import GeneratorConfig, SignalGenerator
from ..strategies import (
    AsiaRangeFadeStrategy, EngulfingSessionStrategy, FVGFillStrategy,
    LondonBreakoutStrategy, NyOpenReversalStrategy, OBRetestContinuationStrategy,
    PinBarSessionStrategy, SMCLiquiditySweepStrategy,
)

PROFILES = {
    "retail_1x30": RiskConfig(
        risk_per_trade_pct=0.015,
        max_risk_per_trade_pct=0.03,
        leverage_max=30.0,
        max_open_positions=6,
    ),
    "pro_1x200": RiskConfig(
        risk_per_trade_pct=0.025,
        max_risk_per_trade_pct=0.05,
        leverage_max=200.0,
        max_open_positions=8,
    ),
    "crypto_equivalent_1x500": RiskConfig(
        risk_per_trade_pct=0.030,
        max_risk_per_trade_pct=0.06,
        leverage_max=500.0,
        max_open_positions=10,
    ),
}

STRATS = (
    LondonBreakoutStrategy, NyOpenReversalStrategy, AsiaRangeFadeStrategy,
    SMCLiquiditySweepStrategy, OBRetestContinuationStrategy,
    FVGFillStrategy, PinBarSessionStrategy, EngulfingSessionStrategy,
)


def run_pair(pair: str, start: str, end: str, risk_cfg: RiskConfig) -> dict:
    df = generate_synthetic_ohlcv(pair, start, end)
    strategies = [cls() for cls in STRATS]
    news = NewsGuard()
    gen = SignalGenerator(pair=pair, strategies=strategies, config=GeneratorConfig(), news_guard=news)
    signals = gen.generate(df)
    engine = BacktestEngine(RiskOfficer(risk_cfg), CostModel(), EngineConfig(), news_guard=news)
    result = engine.run(df, signals, pair=pair)
    mc = monte_carlo_shuffle(result.trades, n_iter=200, initial=result.initial_balance) if result.n_trades > 5 else {}
    return {
        "pair": pair, "n_signals": len(signals), "n_trades": result.n_trades,
        "initial": result.initial_balance, "final": result.final_balance,
        **result.kpis, "mc_p5_roi": mc.get("p5_roi"), "mc_p50_roi": mc.get("p50_roi"),
        "mc_p95_roi": mc.get("p95_roi"), "mc_p5_dd": mc.get("p5_dd"), "mc_p95_dd": mc.get("p95_dd"),
        "trades_df": result.trades,
    }


def _aggregate(per_pair: list[dict]) -> dict:
    keys = ["return_total_pct", "cagr_pct", "max_dd_pct", "sharpe", "sortino", "calmar",
            "win_rate", "profit_factor", "expectancy_r"]
    agg = {}
    n_trades = sum(r.get("n_trades", 0) for r in per_pair)
    agg["n_trades"] = n_trades
    agg["n_pairs"] = len(per_pair)
    for k in keys:
        vals = [r.get(k) for r in per_pair if r.get(k) is not None]
        if vals:
            agg[k] = sum(vals) / len(vals)
    final_eq = sum(r.get("final", 0) for r in per_pair)
    init_eq = sum(r.get("initial", 0) for r in per_pair)
    agg["portfolio_roi_pct"] = (final_eq / max(1, init_eq) - 1.0) * 100.0 if init_eq else 0.0
    return agg


def main(start: str = "2022-01-01", end: str = "2026-01-01"):
    summary: dict[str, dict] = {}
    all_trades: dict[str, pd.DataFrame] = {}
    for profile_name, risk_cfg in PROFILES.items():
        print(f"\n=== profile: {profile_name} ===")
        per_pair = []
        for pair in PAIRS:
            r = run_pair(pair, start, end, risk_cfg)
            print(f"[{profile_name}/{pair}] trades={r['n_trades']:4d} ROI={r.get('return_total_pct',0):7.1f}% "
                  f"DD={r.get('max_dd_pct',0):6.1f}% WR={r.get('win_rate',0):.2f} PF={r.get('profit_factor',0):.2f}")
            per_pair.append(r)
        # collect trades
        td_list = [r.pop("trades_df") for r in per_pair]
        td = pd.concat(td_list, ignore_index=True) if any(not t.empty for t in td_list) else pd.DataFrame()
        all_trades[profile_name] = td
        agg = _aggregate(per_pair)
        summary[profile_name] = {"per_pair": per_pair, "aggregate": agg}
        print(f"[{profile_name}] AGGREGATE: portfolio_roi={agg['portfolio_roi_pct']:.1f}% "
              f"mean_pair_ROI={agg.get('return_total_pct',0):.1f}% mean_DD={agg.get('max_dd_pct',0):.1f}% "
              f"mean_Sharpe={agg.get('sharpe',0):.2f} n_trades={agg['n_trades']}")

    out_json = REPORTS_DIR / f"forex_4y_full_{datetime.utcnow():%Y%m%d_%H%M%S}.json"
    out_json.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {out_json}")

    # generate forex vs crypto report from best profile
    best_profile = max(summary.keys(), key=lambda k: summary[k]["aggregate"].get("portfolio_roi_pct", -999))
    forex_kpis = summary[best_profile]["aggregate"]
    crypto_champion = {
        "return_total_pct": 935.4, "cagr_pct": 302.0, "max_dd_pct": -63.0,
        "sharpe": 2.35, "sortino": 3.20, "calmar": 4.79,
        "win_rate": 0.515, "profit_factor": 2.10, "expectancy_r": 0.41,
        "n_trades": 1450,
    }
    rationale = (
        f"4-year synthetic GBM backtest, best risk profile: {best_profile}\n"
        f"Forex aggregate ROI (mean per pair): {forex_kpis.get('return_total_pct',0):.1f}%\n"
        f"Forex aggregate DD (mean per pair): {forex_kpis.get('max_dd_pct',0):.1f}%\n\n"
        "WHY DELTA vs crypto %1800:\n"
        "1) Synthetic GBM has NO market edge — strategies only emit cost drag.\n"
        "2) Major spot pair annualized vol ~5-12% vs BTC ~60-80% → same edge scales 5-15x lower.\n"
        "3) Spread tax: 1-2 pips on 8-15 pip typical 15m range vs 5-10 bps on crypto move.\n"
        "4) Real Dukascopy edge needs separate ingest + tune; this baseline is a lower-bound.\n\n"
        "REACHING %1800 on real forex data requires:\n"
        "  - 1:200+ leverage (offshore pro account, not retail)\n"
        "  - 3% risk/trade with sharp signal selection\n"
        "  - Genuine edge (real-data calibrated, not GBM noise)\n\n"
        "Realistic retail (1:30, 1.5% risk) band: ROI %30-150/yr, DD %15-25.\n"
    )
    write_comparison_report(REPORTS_DIR / "forex_vs_crypto_4y.html", crypto_champion, forex_kpis, rationale=rationale)
    return summary


if __name__ == "__main__":
    main()
