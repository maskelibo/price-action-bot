"""Optimization sweep on real Dukascopy 4y data — find max ROI / min DD configuration.

Sweep dims:
  - confluence threshold: [0.55, 0.60, 0.65, 0.70]
  - risk_per_trade: [0.010, 0.015, 0.020, 0.025]
  - vol_target enabled: [False, True]
  - per-pair filter: ['all', 'usdjpy_only', 'jpy_pairs']  (latter requires extra data)
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..backtest.costs import CostModel
from ..backtest.engine import BacktestEngine, EngineConfig
from ..data.store import OHLCVStore
from ..news.guard import NewsGuard
from ..risk.officer import RiskConfig, RiskOfficer
from ..risk.vol_target import VolTargetConfig
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


def run_config(pair: str, df: pd.DataFrame, *, confluence: float, risk_pct: float,
               vol_target_on: bool, leverage_max: float) -> dict:
    strategies = [cls() for cls in STRATS]
    news = NewsGuard()
    gen_cfg = GeneratorConfig(confluence_threshold=confluence)
    gen = SignalGenerator(pair=pair, strategies=strategies, config=gen_cfg, news_guard=news)
    signals = gen.generate(df)
    vt = VolTargetConfig(enabled=vol_target_on, target_atr_pct=0.0010, min_factor=0.30, max_factor=2.0)
    rcfg = RiskConfig(
        risk_per_trade_pct=risk_pct,
        max_risk_per_trade_pct=risk_pct * 2,
        leverage_max=leverage_max,
        max_open_positions=6,
        max_per_pair_pct=0.30,
        vol_target=vt,
    )
    engine = BacktestEngine(RiskOfficer(rcfg, news_guard=news), CostModel(), EngineConfig(), news_guard=news)
    result = engine.run(df, signals, pair=pair, timeframe="15m")
    return {"n_signals": len(signals), "n_trades": result.n_trades, **result.kpis,
            "initial": result.initial_balance, "final": result.final_balance}


def main():
    store = OHLCVStore(DUCKDB_PATH, PARQUET_DIR)
    pairs = ["EURUSD", "USDJPY", "GBPUSD"]
    dfs = {p: store.read_ohlcv(p, "15m") for p in pairs}
    print(f"Loaded: " + ", ".join(f"{p}={len(d)} bars" for p, d in dfs.items()))

    grid = []
    for conf in [0.55, 0.60, 0.65]:
        for risk in [0.010, 0.015, 0.020]:
            for vt in [False, True]:
                for lev in [30.0, 100.0, 200.0]:
                    grid.append({"confluence": conf, "risk_pct": risk, "vol_target": vt, "leverage": lev})

    print(f"\n=== sweeping {len(grid)} configurations × {len(pairs)} pairs = {len(grid)*len(pairs)} runs ===\n")
    results = []
    for i, cfg in enumerate(grid):
        per_pair = {}
        for p, df in dfs.items():
            try:
                r = run_config(p, df,
                              confluence=cfg["confluence"], risk_pct=cfg["risk_pct"],
                              vol_target_on=cfg["vol_target"], leverage_max=cfg["leverage"])
            except Exception as e:
                r = {"error": str(e), "return_total_pct": -100, "n_trades": 0}
            per_pair[p] = r
        # aggregate (mean across pairs)
        roi = sum(r.get("return_total_pct", 0) for r in per_pair.values()) / len(pairs)
        dd = sum(r.get("max_dd_pct", 0) for r in per_pair.values()) / len(pairs)
        wr = sum(r.get("win_rate", 0) for r in per_pair.values()) / len(pairs)
        pf = sum(r.get("profit_factor", 0) for r in per_pair.values()) / len(pairs)
        nt = sum(r.get("n_trades", 0) for r in per_pair.values())
        calmar = abs(roi / dd) if dd < 0 else 0
        results.append({
            **cfg, "mean_roi": roi, "mean_dd": dd, "mean_wr": wr, "mean_pf": pf,
            "n_trades": nt, "calmar": calmar, "per_pair": per_pair,
        })
        print(f"[{i+1:3d}/{len(grid)}] conf={cfg['confluence']} risk={cfg['risk_pct']*100:.1f}% "
              f"vt={cfg['vol_target']} lev={cfg['leverage']:.0f}  "
              f"ROI={roi:6.2f}% DD={dd:6.2f}% WR={wr:.2f} PF={pf:.2f} N={nt} calmar={calmar:.2f}", flush=True)

    # rank
    print("\n=== Top 5 by ROI ===")
    ranked = sorted(results, key=lambda r: r["mean_roi"], reverse=True)
    for r in ranked[:5]:
        print(f"  ROI={r['mean_roi']:.2f}% DD={r['mean_dd']:.2f}% WR={r['mean_wr']:.2f} PF={r['mean_pf']:.2f} "
              f"calmar={r['calmar']:.2f} conf={r['confluence']} risk={r['risk_pct']*100:.1f}% vt={r['vol_target']} lev={r['leverage']:.0f}")
    print("\n=== Top 5 by Calmar ===")
    ranked = sorted(results, key=lambda r: r["calmar"], reverse=True)
    for r in ranked[:5]:
        print(f"  Calmar={r['calmar']:.2f} ROI={r['mean_roi']:.2f}% DD={r['mean_dd']:.2f}% WR={r['mean_wr']:.2f} "
              f"PF={r['mean_pf']:.2f} conf={r['confluence']} risk={r['risk_pct']*100:.1f}% vt={r['vol_target']} lev={r['leverage']:.0f}")

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out = REPORTS_DIR / f"forex_sweep_{ts}.json"
    out.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
