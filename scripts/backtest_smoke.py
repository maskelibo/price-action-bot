"""Backtest pipeline smoke test — synthetic OHLCV data only.

Tests: signals -> strategy -> backtest engine -> markdown report
Uses deterministic numpy seed=42. No real data, no exchange, no chromadb.

Run:
    PYTHONPATH=src python scripts/backtest_smoke.py
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 1. Synthetic OHLCV with embedded patterns
# ---------------------------------------------------------------------------

def _generate_synthetic_ohlcv(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Generate ~200 daily bars of BTC-like prices with embedded patterns.

    Embedded patterns (deterministic):
      - 3 bullish pin bars near support
      - 1 bearish pin bar near resistance
      - 2 bullish engulfing bars
      - 1 bearish engulfing bar
      - 2 inside bars
      - Mix of trending and ranging regimes
    """
    rng = np.random.default_rng(seed)
    base_ts = datetime(2025, 1, 1, tzinfo=timezone.utc)
    timestamps = [base_ts + timedelta(days=i) for i in range(n)]

    # Base price: BTC-like, starts ~45000, has trend + range regimes
    # Regime 1 (bars 0-59): uptrend
    # Regime 2 (bars 60-119): range
    # Regime 3 (bars 120-179): downtrend
    # Regime 4 (bars 180-199): recovery uptrend
    price = np.empty(n)
    price[0] = 45_000.0

    for i in range(1, n):
        if i < 60:      # uptrend: +0.3% drift
            drift = 0.003
        elif i < 120:   # range: 0% drift
            drift = 0.0
        elif i < 180:   # downtrend: -0.2% drift
            drift = -0.002
        else:           # recovery: +0.15% drift
            drift = 0.0015

        ret = drift + rng.normal(0, 0.018)
        price[i] = price[i - 1] * (1 + ret)

    # Build OHLCV from close prices
    close = price.copy()
    open_ = np.empty(n)
    open_[0] = close[0] * (1 + rng.normal(0, 0.003))
    for i in range(1, n):
        open_[i] = close[i - 1] * (1 + rng.normal(0, 0.002))

    # Normal wicks
    wick_factor = np.abs(rng.normal(0, 0.006, n))
    high = np.maximum(open_, close) * (1 + wick_factor)
    low = np.minimum(open_, close) * (1 - wick_factor)
    volume = rng.uniform(800_000, 4_000_000, n)

    # ---- Embed bullish pin bars at bars 45, 90, 150 (near support zones) ----
    for idx in [45, 90, 150]:
        # Pin bar: small body, large lower wick, tiny upper wick
        body_center = close[idx]
        body_size = body_center * 0.008       # 0.8% body
        lower_wick_size = body_center * 0.035  # 3.5% lower wick
        upper_wick_size = body_center * 0.003  # 0.3% upper wick
        # Bearish body pin (close slightly below open, hammer shape)
        open_[idx] = body_center + body_size * 0.5
        close[idx] = body_center - body_size * 0.5
        low[idx] = body_center - body_size * 0.5 - lower_wick_size
        high[idx] = body_center + body_size * 0.5 + upper_wick_size

    # ---- Embed bearish pin bar at bar 30 (near resistance) ----
    for idx in [30]:
        # Shooting star: small body, large upper wick, tiny lower wick
        body_center = close[idx]
        body_size = body_center * 0.008
        upper_wick_size = body_center * 0.035
        lower_wick_size = body_center * 0.003
        open_[idx] = body_center - body_size * 0.5
        close[idx] = body_center + body_size * 0.5
        high[idx] = body_center + body_size * 0.5 + upper_wick_size
        low[idx] = body_center - body_size * 0.5 - lower_wick_size

    # ---- Embed bullish engulfing bars at bars 70, 130 ----
    for idx in [70, 130]:
        if idx > 0:
            # Previous bar: bearish with decent body
            prev_mid = close[idx - 1]
            prev_body = prev_mid * 0.02
            open_[idx - 1] = prev_mid + prev_body * 0.5
            close[idx - 1] = prev_mid - prev_body * 0.5
            high[idx - 1] = open_[idx - 1] + prev_mid * 0.005
            low[idx - 1] = close[idx - 1] - prev_mid * 0.005
            # Current bar: bullish engulfing (open <= prev close, close >= prev open)
            open_[idx] = close[idx - 1] - prev_mid * 0.001  # open below prev close
            close[idx] = open_[idx - 1] + prev_mid * 0.001  # close above prev open
            high[idx] = close[idx] + prev_mid * 0.005
            low[idx] = open_[idx] - prev_mid * 0.003

    # ---- Embed bearish engulfing bar at bar 55 ----
    for idx in [55]:
        if idx > 0:
            prev_mid = close[idx - 1]
            prev_body = prev_mid * 0.015
            # Previous bar: bullish
            open_[idx - 1] = prev_mid - prev_body * 0.5
            close[idx - 1] = prev_mid + prev_body * 0.5
            high[idx - 1] = close[idx - 1] + prev_mid * 0.005
            low[idx - 1] = open_[idx - 1] - prev_mid * 0.005
            # Current bar: bearish engulfing
            open_[idx] = close[idx - 1] + prev_mid * 0.001
            close[idx] = open_[idx - 1] - prev_mid * 0.001
            high[idx] = open_[idx] + prev_mid * 0.005
            low[idx] = close[idx] - prev_mid * 0.003

    # ---- Embed inside bars at bars 80, 160 ----
    for idx in [80, 160]:
        if idx > 0:
            # Inside bar: high < prev high, low > prev low
            prev_hi = high[idx - 1]
            prev_lo = low[idx - 1]
            mid = (prev_hi + prev_lo) / 2
            range_ = prev_hi - prev_lo
            # Inside bar uses 40% of previous range
            high[idx] = mid + range_ * 0.20
            low[idx] = mid - range_ * 0.20
            open_[idx] = mid + range_ * 0.05
            close[idx] = mid - range_ * 0.05

    # Clamp: ensure high >= max(open, close) and low <= min(open, close)
    high = np.maximum(high, np.maximum(open_, close))
    low = np.minimum(low, np.minimum(open_, close))

    df = pd.DataFrame({
        "venue": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1d",
        "ts": timestamps,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })
    return df


# ---------------------------------------------------------------------------
# 2. Strategy + Backtest pipeline
# ---------------------------------------------------------------------------

def _make_manifest():
    from price_action.strategies.base import StrategyManifest

    raw = {
        "name": "classic_pa_smoke",
        "version": "0.0.1",
        "trend_filter": {
            "type": "ema",
            "period": 20,        # shorter period for 200-bar synthetic data
            "required": True,
        },
        "signals": {
            "patterns": [
                {"id": "bullish_pin_bar", "enabled": True, "weight": 1.5, "params": {
                    "body_to_range_max": 0.33,
                    "lower_wick_to_range_min": 0.6,
                    "upper_wick_to_range_max": 0.15,
                }},
                {"id": "bearish_pin_bar", "enabled": True, "weight": 1.5, "params": {
                    "body_to_range_max": 0.33,
                    "upper_wick_to_range_min": 0.6,
                    "lower_wick_to_range_max": 0.15,
                }},
                {"id": "bullish_engulfing", "enabled": True, "weight": 1.5, "params": {
                    "prev_body_min_range_pct": 0.15,
                }},
                {"id": "bearish_engulfing", "enabled": True, "weight": 1.5, "params": {
                    "prev_body_min_range_pct": 0.15,
                }},
                {"id": "inside_bar_breakout", "enabled": True, "weight": 0.8, "params": {
                    "confirm_with_close": True,
                }},
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 60,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 60,
                },
                # Relax S/R proximity — 200 bars may not build dense S/R clusters
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.003,   # allow lower volatility bars
                "volume_zscore_min": 0.0,
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 1.0,       # lower threshold for smoke test
                "bonus_if_at_sr": 0.5,
            },
        },
        "risk": {
            "stop_loss": {"atr_multiplier": 2.0},
            "take_profit": {"primary_R": 2.0},
        },
    }
    return StrategyManifest.model_validate(raw)


def run_smoke_test() -> dict:
    """Run the full pipeline and return results dict."""
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.classic_pa import ClassicPriceActionStrategy

    print("[1/5] Generating synthetic OHLCV data (seed=42)...")
    df = _generate_synthetic_ohlcv(n=200, seed=42)
    print(f"      Bars: {len(df)}, range: {df['ts'].iloc[0].date()} -> {df['ts'].iloc[-1].date()}")
    print(f"      Price range: {df['close'].min():.0f} - {df['close'].max():.0f} USDT")
    print(f"      Embedded: 3 bullish pins, 1 bearish pin, 2 bull engulfing, "
          f"1 bear engulfing, 2 inside bars")

    print("\n[2/5] Building strategy manifest + features...")
    manifest = _make_manifest()
    strategy = ClassicPriceActionStrategy(manifest)
    df_feats = strategy.prepare_features(df)
    print(f"      Features added: {[c for c in df_feats.columns if c not in df.columns]}")

    print("\n[3/5] Generating signals...")
    signals = strategy.generate_signals(df_feats)
    print(f"      Signals generated: {len(signals)}")
    if signals:
        long_sigs = [s for s in signals if s.direction == "long"]
        short_sigs = [s for s in signals if s.direction == "short"]
        patterns = {}
        for s in signals:
            patterns[s.pattern_id] = patterns.get(s.pattern_id, 0) + 1
        print(f"      Long: {len(long_sigs)}, Short: {len(short_sigs)}")
        print(f"      Patterns: {patterns}")
        scores = [s.confluence_score for s in signals]
        print(f"      Confluence scores: min={min(scores):.2f}, max={max(scores):.2f}, "
              f"mean={sum(scores)/len(scores):.2f}")

    print("\n[4/5] Running backtest engine...")
    start_dt = df["ts"].iloc[0].to_pydatetime()
    end_dt = df["ts"].iloc[-1].to_pydatetime()

    def ohlcv_provider(symbol: str, tf: str, start, end):
        return df_feats.copy()

    engine = BacktestEngine(risk_officer=None, store_load=None)
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
    print(f"      Engine elapsed: {result.elapsed_sec:.3f}s")
    print(f"      Trades executed: {result.n_trades}")

    return {
        "df": df,
        "df_feats": df_feats,
        "signals": signals,
        "result": result,
    }


# ---------------------------------------------------------------------------
# 3. Summary stats printing
# ---------------------------------------------------------------------------

def print_summary(data: dict) -> None:
    result = data["result"]
    signals = data["signals"]
    kpis = result.kpis

    print("\n" + "=" * 60)
    print("SMOKE TEST SUMMARY")
    print("=" * 60)
    print(f"Strategy:        {result.strategy_name}")
    print(f"Signals:         {len(signals)}")
    print(f"Trades:          {result.n_trades}")

    n_trades = int(kpis.get("n_trades", 0))
    win_rate = kpis.get("win_rate", 0.0)
    sharpe = kpis.get("sharpe", 0.0)
    sortino = kpis.get("sortino", 0.0)
    max_dd = kpis.get("max_drawdown", 0.0)
    profit_factor = kpis.get("profit_factor", 0.0)
    expectancy = kpis.get("expectancy", 0.0)
    cagr = kpis.get("cagr", 0.0)
    dsr = kpis.get("deflated_sharpe", 0.0)
    calmar = kpis.get("calmar", 0.0)

    print(f"\n--- KPIs ---")
    print(f"  Win Rate:        {win_rate:.1%}")
    print(f"  Profit Factor:   {profit_factor:.3f}")
    print(f"  Expectancy:      {expectancy:+.2f} USDT/trade")
    print(f"  Sharpe:          {sharpe:.3f}")
    print(f"  Sortino:         {sortino:.3f}")
    print(f"  Deflated Sharpe: {dsr:.3f}")
    print(f"  Max Drawdown:    {max_dd:.2%}")
    print(f"  Calmar:          {calmar:.3f}")
    print(f"  CAGR (annlzd):   {cagr:.2%}")

    if not result.trades.empty:
        trades_df = result.trades
        r_mults = trades_df["realized_r_multiple"]
        print(f"\n--- R-Multiple Distribution ---")
        print(f"  Min R:      {r_mults.min():.2f}")
        print(f"  Max R:      {r_mults.max():.2f}")
        print(f"  Mean R:     {r_mults.mean():.2f}")
        print(f"  Median R:   {r_mults.median():.2f}")

        # Percentiles
        p25 = r_mults.quantile(0.25)
        p75 = r_mults.quantile(0.75)
        print(f"  P25/P75:    {p25:.2f} / {p75:.2f}")

        avg_win = kpis.get("avg_win", 0.0)
        avg_loss = kpis.get("avg_loss", 0.0)
        print(f"\n--- Per-Trade ---")
        print(f"  Avg Win:    {avg_win:+.2f} USDT")
        print(f"  Avg Loss:   {avg_loss:+.2f} USDT")

        print(f"\n--- Pattern Breakdown ---")
        if "pattern_id" in trades_df.columns:
            pattern_counts = trades_df["pattern_id"].value_counts()
            for pat, cnt in pattern_counts.items():
                pat_trades = trades_df[trades_df["pattern_id"] == pat]
                pat_wr = (pat_trades["realized_pnl_usdt"] > 0).mean()
                print(f"  {pat:<30} n={cnt:2d}  wr={pat_wr:.0%}")

        print(f"\n--- Equity ---")
        eq = result.equity_curve
        initial = eq.iloc[0]
        final = eq.iloc[-1]
        print(f"  Start: {initial:,.2f} USDT")
        print(f"  End:   {final:,.2f} USDT")
        print(f"  Net:   {final - initial:+,.2f} USDT ({(final/initial - 1):.2%})")
    else:
        print("\n  [No trades executed]")

    print(f"\n--- Manifest ---")
    print(f"  Composite hash:  {result.manifest.composite}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# 4. Report generation
# ---------------------------------------------------------------------------

def save_report(data: dict, report_path: Path) -> None:
    """Save a markdown summary report."""
    result = data["result"]
    signals = data["signals"]
    kpis = result.kpis
    trades_df = result.trades

    lines = [
        f"# Backtest Smoke Test Report",
        f"",
        f"**Strategy:** `{result.strategy_name}`  ",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}  ",
        f"**Data:** Synthetic BTC/USDT, 200 daily bars (seed=42)  ",
        f"**Period:** {result.start.date()} → {result.end.date()}  ",
        f"**Manifest:** `{result.manifest.composite}`  ",
        f"**Engine elapsed:** {result.elapsed_sec:.3f}s  ",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Signals generated | {len(signals)} |",
        f"| Trades executed | {result.n_trades} |",
        f"| Win Rate | {kpis.get('win_rate', 0):.1%} |",
        f"| Profit Factor | {kpis.get('profit_factor', 0):.3f} |",
        f"| Expectancy (USDT) | {kpis.get('expectancy', 0):+.2f} |",
        f"| Sharpe | {kpis.get('sharpe', 0):.3f} |",
        f"| Sortino | {kpis.get('sortino', 0):.3f} |",
        f"| Deflated Sharpe | {kpis.get('deflated_sharpe', 0):.3f} |",
        f"| Max Drawdown | {kpis.get('max_drawdown', 0):.2%} |",
        f"| Calmar | {kpis.get('calmar', 0):.3f} |",
        f"| CAGR (annlzd) | {kpis.get('cagr', 0):.2%} |",
        f"",
    ]

    if not trades_df.empty:
        r_mults = trades_df["realized_r_multiple"]
        lines += [
            f"## R-Multiple Distribution",
            f"",
            f"| Stat | Value |",
            f"|------|-------|",
            f"| Min R | {r_mults.min():.2f} |",
            f"| Max R | {r_mults.max():.2f} |",
            f"| Mean R | {r_mults.mean():.2f} |",
            f"| Median R | {r_mults.median():.2f} |",
            f"| P25 | {r_mults.quantile(0.25):.2f} |",
            f"| P75 | {r_mults.quantile(0.75):.2f} |",
            f"",
        ]

        # Equity
        eq = result.equity_curve
        lines += [
            f"## Equity Curve (last 10 points)",
            f"",
            f"| Date | Equity (USDT) |",
            f"|------|--------------|",
        ]
        for ts, val in eq.tail(10).items():
            lines.append(f"| {ts} | {val:,.2f} |")

        lines += [""]

        # Trades table (last 20)
        lines += [
            f"## Trades (last 20 of {result.n_trades})",
            f"",
            f"| # | Entry | Side | Pattern | Entry Price | Exit Price | PnL (USDT) | R |",
            f"|---|-------|------|---------|-------------|------------|------------|---|",
        ]
        display = trades_df.tail(20)
        for i, row in enumerate(display.to_dict("records"), 1):
            lines.append(
                f"| {i} | {row.get('entry_ts', '')} | {row.get('side', '')} | "
                f"{row.get('pattern_id', '')} | {row.get('entry_price', 0):.0f} | "
                f"{row.get('exit_price', 0):.0f} | {row.get('realized_pnl_usdt', 0):+.2f} | "
                f"{row.get('realized_r_multiple', 0):.2f} |"
            )

        lines += [""]

    # Signal details
    if signals:
        lines += [
            f"## Signals Generated ({len(signals)} total)",
            f"",
            f"| ts | Direction | Pattern | Score | SL | TP |",
            f"|----|-----------|---------|-------|----|----|",
        ]
        for sig in signals[:20]:
            lines.append(
                f"| {sig.ts.date()} | {sig.direction} | {sig.pattern_id} | "
                f"{sig.confluence_score:.2f} | {sig.sl_price:.0f} | {sig.tp_price:.0f} |"
            )
        if len(signals) > 20:
            lines.append(f"| ... | *{len(signals) - 20} more* | | | | |")
        lines += [""]

    lines += [
        f"## Pipeline Status",
        f"",
        f"- [x] Synthetic OHLCV generation",
        f"- [x] Feature preparation (EMA, ATR, swings)",
        f"- [x] Signal generation (classic_pa)",
        f"- [x] Backtest engine simulation",
        f"- [x] KPI computation",
        f"- [x] Report generation",
        f"",
        f"**Status: WORKS**",
    ]

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[5/5] Report saved to: {report_path}")


# ---------------------------------------------------------------------------
# 5. Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 60)
    print("BACKTEST PIPELINE SMOKE TEST")
    print("=" * 60)
    print("Mode: SYNTHETIC ONLY — no real data, no exchange, no DB")
    print()

    errors: list[str] = []

    try:
        data = run_smoke_test()
    except Exception as exc:
        print(f"\n[FATAL] Pipeline failed: {exc}", file=sys.stderr)
        traceback.print_exc()
        errors.append(f"Pipeline error: {exc}")
        return 1

    print_summary(data)

    # Save report
    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = (
        Path(__file__).parent.parent / "reports" / "research"
        / f"backtest_smoke_{ts_str}.md"
    )
    try:
        save_report(data, report_path)
    except Exception as exc:
        print(f"\n[WARN] Report save failed: {exc}", file=sys.stderr)
        errors.append(f"Report error: {exc}")

    if errors:
        print(f"\n[DONE] Completed with {len(errors)} warning(s):")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"\n[DONE] Smoke test PASSED. Pipeline is operational.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
