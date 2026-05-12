"""OB Mitigation Strict Strategy — Backtest Runner.

Fetches BTC/USDT 1D from Binance (2022-01-01 to today), runs
OBMitigationStrictStrategy, and compares KPIs with SMCOrderBlockStrategy
(previous SMC attempt).

Run:
    cd "C:\\Users\\koray\\projeler\\Price Action"
    PYTHONPATH=src python scripts/backtest_ob_mitigation_strict.py
"""
from __future__ import annotations

import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

warnings.filterwarnings("ignore")

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 1. Data fetch
# ---------------------------------------------------------------------------

def fetch_btc_1d(start_dt: datetime, end_dt: datetime) -> pd.DataFrame:
    """Fetch BTC/USDT daily OHLCV from Binance via ccxt."""
    try:
        import ccxt
    except ImportError:
        print("[ERROR] ccxt not installed. pip install ccxt")
        sys.exit(1)

    ex = ccxt.binance({"options": {"defaultType": "spot"}, "enableRateLimit": True})
    since_ms = int(start_dt.timestamp() * 1000)
    end_ms = int(end_dt.timestamp() * 1000)

    print(f"  Fetching BTC/USDT 1d from {start_dt.date()} to {end_dt.date()} ...")
    rows = []
    since = since_ms
    while True:
        chunk = ex.fetch_ohlcv("BTC/USDT", "1d", since=since, limit=1000)
        if not chunk:
            break
        rows.extend(chunk)
        last_ts = chunk[-1][0]
        if last_ts >= end_ms or len(chunk) < 1000:
            break
        since = last_ts + 86_400_000
        time.sleep(0.1)

    df = pd.DataFrame(rows, columns=["ts_ms", "open", "high", "low", "close", "volume"])
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
    df = df[df["ts"] <= pd.Timestamp(end_dt)]
    df["venue"] = "binance"
    df["symbol"] = "BTC/USDT"
    df["timeframe"] = "1d"
    df = df[["ts", "open", "high", "low", "close", "volume", "venue", "symbol", "timeframe"]]
    df = df.sort_values("ts").reset_index(drop=True)
    print(f"  Fetched {len(df)} bars  ({df['ts'].iloc[0].date()} to {df['ts'].iloc[-1].date()})")
    return df


# ---------------------------------------------------------------------------
# 2. Run one strategy
# ---------------------------------------------------------------------------

def run_strategy(strategy, df: pd.DataFrame, start_dt: datetime, end_dt: datetime) -> dict:
    from price_action.backtest.engine import BacktestEngine

    def ohlcv_provider(symbol, tf, start, end):
        return df.copy()

    engine = BacktestEngine()
    result = engine.run(
        strategy,
        ["BTC/USDT"],
        start=start_dt,
        end=end_dt,
        timeframe="1d",
        initial_capital=10_000.0,
        fees={"taker": 0.00075, "maker": -0.00010},
        slippage_bps=5.0,
        ohlcv_provider=ohlcv_provider,
    )
    return result


# ---------------------------------------------------------------------------
# 3. Print & compare
# ---------------------------------------------------------------------------

def print_result(name: str, result) -> None:
    kpis = result.kpis
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")
    print(f"  Trades:          {result.n_trades}")
    print(f"  Win Rate:        {kpis.get('win_rate', 0):.1%}")
    print(f"  Profit Factor:   {kpis.get('profit_factor', 0):.3f}")
    print(f"  Expectancy:      {kpis.get('expectancy', 0):+.2f} USDT/trade")
    print(f"  Sharpe:          {kpis.get('sharpe', 0):.3f}")
    print(f"  Sortino:         {kpis.get('sortino', 0):.3f}")
    print(f"  Max Drawdown:    {kpis.get('max_drawdown', 0):.2%}")
    print(f"  Calmar:          {kpis.get('calmar', 0):.3f}")
    print(f"  CAGR:            {kpis.get('cagr', 0):.2%}")
    print(f"  Deflated Sharpe: {kpis.get('deflated_sharpe', 0):.3f}")

    trades = result.trades
    if not trades.empty and "realized_r_multiple" in trades.columns:
        r = trades["realized_r_multiple"]
        print(f"\n  R-Multiple: min={r.min():.2f}  mean={r.mean():.2f}  max={r.max():.2f}")
        # Annual breakdown
        if "entry_ts" in trades.columns:
            trades_cp = trades.copy()
            trades_cp["year"] = pd.to_datetime(trades_cp["entry_ts"]).dt.year
            print(f"\n  Annual breakdown:")
            for yr, grp in trades_cp.groupby("year"):
                wr = (grp.get("realized_pnl_usdt", pd.Series([0])) > 0).mean()
                n = len(grp)
                pnl = grp.get("realized_pnl_usdt", pd.Series([0])).sum()
                print(f"    {yr}: {n:3d} trades  WR={wr:.0%}  PnL={pnl:+,.0f} USDT")

    eq = result.equity_curve
    if len(eq) > 0:
        start_eq = eq.iloc[0]
        end_eq = eq.iloc[-1]
        print(f"\n  Equity: {start_eq:,.0f} to {end_eq:,.0f} USDT ({(end_eq/start_eq-1):.1%})")


def compare(r_new, r_old) -> None:
    kn = r_new.kpis
    ko = r_old.kpis

    def diff(key):
        n = kn.get(key, 0)
        o = ko.get(key, 0)
        delta = n - o
        sign = "+" if delta >= 0 else ""
        return f"{n:.3f}  (vs {o:.3f}, {sign}{delta:.3f})"

    print(f"\n{'='*60}")
    print("  COMPARISON: ob_mitigation_strict vs smc_orderblock")
    print(f"{'='*60}")
    print(f"  Win Rate:        {diff('win_rate')}")
    print(f"  Profit Factor:   {diff('profit_factor')}")
    print(f"  Sharpe:          {diff('sharpe')}")
    print(f"  Max DD:          {diff('max_drawdown')}")
    print(f"  CAGR:            {diff('cagr')}")
    print(f"  Trades:          {r_new.n_trades}  (vs {r_old.n_trades})")


# ---------------------------------------------------------------------------
# 4. Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print("OB MITIGATION STRICT — BACKTEST")
    print("=" * 60)

    start_dt = datetime(2022, 1, 1, tzinfo=timezone.utc)
    end_dt = datetime(2026, 5, 1, tzinfo=timezone.utc)

    print("\n[1/5] Fetching BTC/USDT 1D data...")
    df = fetch_btc_1d(start_dt, end_dt)

    print("\n[2/5] Running OBMitigationStrictStrategy...")
    from price_action.strategies.ob_mitigation_strict import (
        OBMitigationStrictStrategy,
        _default_manifest as ob_manifest,
    )
    ob_strat = OBMitigationStrictStrategy(ob_manifest())
    df_feat = ob_strat.prepare_features(df)
    signals_ob = ob_strat.generate_signals(df_feat)
    print(f"  OB signals generated: {len(signals_ob)}")
    if signals_ob:
        long_n = sum(1 for s in signals_ob if s.direction == "long")
        short_n = sum(1 for s in signals_ob if s.direction == "short")
        patterns: dict[str, int] = {}
        for s in signals_ob:
            patterns[s.pattern_id] = patterns.get(s.pattern_id, 0) + 1
        print(f"  Long: {long_n}, Short: {short_n}")
        print(f"  Patterns: {patterns}")
    result_ob = run_strategy(ob_strat, df, start_dt, end_dt)

    print("\n[3/5] Running SMCOrderBlockStrategy (for comparison)...")
    from price_action.strategies.smc_orderblock import SMCOrderBlockStrategy
    from price_action.strategies.base import StrategyManifest

    smc_raw = {
        "name": "smc_orderblock",
        "version": "1.0.0",
        "trend_filter": {"type": "ema", "period": 200, "required": True},
        "signals": {
            "patterns": [],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {"lookback_bars": 50, "cluster_atr_multiplier": 0.5, "min_touches": 2},
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {"atr_min_pct": 0.0, "volume_zscore_min": 0.0, "atr_mult_for_displacement": 1.5},
            "confluence": {"method": "weighted_sum", "min_score": 2.0, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "stop_loss": {"method": "structural", "atr_period": 14, "atr_multiplier": 1.0},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    smc_manifest = StrategyManifest.model_validate(smc_raw)
    smc_strat = SMCOrderBlockStrategy(smc_manifest)
    df_smc = smc_strat.prepare_features(df)
    signals_smc = smc_strat.generate_signals(df_smc)
    print(f"  SMC signals generated: {len(signals_smc)}")
    result_smc = run_strategy(smc_strat, df, start_dt, end_dt)

    print("\n[4/5] Results:")
    print_result("OB MITIGATION STRICT (new)", result_ob)
    print_result("SMC ORDER BLOCK (prior)", result_smc)
    compare(result_ob, result_smc)

    print("\n[5/5] Verdict:")
    kn = result_ob.kpis
    ko = result_smc.kpis

    new_wins = 0
    checks = [
        ("Win Rate", "win_rate", True),
        ("Profit Factor", "profit_factor", True),
        ("Sharpe", "sharpe", True),
        ("Max DD", "max_drawdown", False),  # lower is better
        ("CAGR", "cagr", True),
    ]
    for label, key, higher_is_better in checks:
        nv = kn.get(key, 0)
        ov = ko.get(key, 0)
        if (higher_is_better and nv > ov) or (not higher_is_better and nv < ov):
            new_wins += 1

    if new_wins >= 4:
        verdict = "PROMOTE CANDIDATE: strict OB mitigation outperforms prior SMC on >= 4/5 metrics"
    elif new_wins >= 3:
        verdict = "MARGINAL: outperforms on 3/5 metrics, investigate further"
    else:
        verdict = "REJECT: strict OB mitigation does NOT improve over prior SMC"

    print(f"\n  VERDICT: {verdict}")
    print(f"  (Outperforms on {new_wins}/5 key metrics)")

    # Save report
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_dir = Path(__file__).parent.parent / "reports" / "research"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"backtest_ob_mitigation_strict_{ts_str}.md"

    kn2 = result_ob.kpis
    ko2 = result_smc.kpis
    lines = [
        f"# OB Mitigation Strict — Backtest Report",
        f"",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}  ",
        f"**Period:** {start_dt.date()} → {end_dt.date()}  ",
        f"**Symbol:** BTC/USDT 1D  ",
        f"",
        f"## OB Mitigation Strict",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Trades | {result_ob.n_trades} |",
        f"| Win Rate | {kn2.get('win_rate', 0):.1%} |",
        f"| Profit Factor | {kn2.get('profit_factor', 0):.3f} |",
        f"| Expectancy | {kn2.get('expectancy', 0):+.2f} USDT |",
        f"| Sharpe | {kn2.get('sharpe', 0):.3f} |",
        f"| Max Drawdown | {kn2.get('max_drawdown', 0):.2%} |",
        f"| CAGR | {kn2.get('cagr', 0):.2%} |",
        f"| Calmar | {kn2.get('calmar', 0):.3f} |",
        f"",
        f"## SMC OrderBlock (prior)",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Trades | {result_smc.n_trades} |",
        f"| Win Rate | {ko2.get('win_rate', 0):.1%} |",
        f"| Profit Factor | {ko2.get('profit_factor', 0):.3f} |",
        f"| Expectancy | {ko2.get('expectancy', 0):+.2f} USDT |",
        f"| Sharpe | {ko2.get('sharpe', 0):.3f} |",
        f"| Max Drawdown | {ko2.get('max_drawdown', 0):.2%} |",
        f"| CAGR | {ko2.get('cagr', 0):.2%} |",
        f"| Calmar | {ko2.get('calmar', 0):.3f} |",
        f"",
        f"## Verdict",
        f"",
        f"**{verdict}**",
        f"",
        f"Outperforms on {new_wins}/5 key metrics.",
    ]
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  Report saved: {report_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
