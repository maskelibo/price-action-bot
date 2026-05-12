"""Brooks Failed Breakout / Trap — Backtest Runner.

Synthetic OHLCV (seed=42, BTC-like) ile strateji testi.
Gerçek veri bağlantısı gerektirmez.

Run:
    cd "C:\\Users\\koray\\projeler\\Price Action"
    python -m pytest scripts/backtest_brooks_failed_breakout.py -v   # smoke check
    python scripts/backtest_brooks_failed_breakout.py                 # full backtest

Çıktı: reports/research/backtest_brooks_failed_breakout_<ts>.md
"""
from __future__ import annotations

import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# 1. Sentetik OHLCV (500 bar, BTC benzeri, çoklu rejim)
# ---------------------------------------------------------------------------

def _generate_ohlcv(n: int = 500, seed: int = 42) -> pd.DataFrame:
    """Çoklu rejim (uptrend, range, downtrend, recovery) ile sentetik OHLCV.

    Gömülü trap senaryoları:
      - Uptrend → range geçişinde bull trap (yukarı kırılım başarısız)
      - Range → downtrend geçişinde bear trap (aşağı kırılım başarısız)
      - Downtrend sonunda bear trap reversal (long setup)
    """
    rng = np.random.default_rng(seed)
    base_ts = datetime(2023, 1, 1, tzinfo=timezone.utc)
    timestamps = [base_ts + timedelta(days=i) for i in range(n)]

    # Rejimler
    # 0-124:   uptrend (+0.35%/bar)
    # 125-249: range (0% drift, sıkışma)
    # 250-374: downtrend (-0.25%/bar)
    # 375-499: recovery (+0.20%/bar)
    price = np.empty(n)
    price[0] = 45_000.0

    for i in range(1, n):
        if i < 125:
            drift = 0.0035
        elif i < 250:
            drift = 0.0
        elif i < 375:
            drift = -0.0025
        else:
            drift = 0.002

        ret = drift + rng.normal(0, 0.016)
        price[i] = max(price[i - 1] * (1 + ret), 1_000.0)

    close = price.copy()
    open_ = np.empty(n)
    open_[0] = close[0] * (1 + rng.normal(0, 0.003))
    for i in range(1, n):
        open_[i] = close[i - 1] * (1 + rng.normal(0, 0.0015))

    wick_factor = np.abs(rng.normal(0, 0.006, n))
    high = np.maximum(open_, close) * (1 + wick_factor)
    low = np.minimum(open_, close) * (1 - wick_factor)
    volume = rng.uniform(500_000, 5_000_000, n)

    # --- Bull trap senaryoları (range üstüne çıkış, geri dönüş) ---
    # Bar 240-244: range high kırılımı → başarısız → short setup
    # Önce range high oluştur (bar 220-239'da range)
    range_high = close[239]  # bar 239'daki değer
    for idx in [240, 241]:
        # BO bar: close > range_high
        open_[idx] = range_high * 0.998
        close[idx] = range_high * 1.012  # close beyond
        high[idx] = close[idx] * 1.004
        low[idx] = open_[idx] * 0.994
    # Failure bars: close < range_high
    for idx in [242, 243]:
        open_[idx] = close[idx - 1] * 0.999
        close[idx] = range_high * 0.991  # close below level
        high[idx] = close[idx - 1] * 1.003
        low[idx] = close[idx] * 0.993

    # --- Bear trap senaryoları (downtrend low kırılımı, geri dönüş) ---
    # Bar 370-374: downtrend low kırılımı → başarısız → long setup
    range_low = close[369]
    for idx in [370, 371]:
        open_[idx] = range_low * 1.002
        close[idx] = range_low * 0.987  # close below
        low[idx] = close[idx] * 0.996
        high[idx] = open_[idx] * 1.004
    # Failure: close > range_low
    for idx in [372, 373]:
        open_[idx] = close[idx - 1] * 1.001
        close[idx] = range_low * 1.010  # close above level
        high[idx] = close[idx] * 1.004
        low[idx] = open_[idx] * 0.994

    # Clamp
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
# 2. Strateji + Backtest pipeline
# ---------------------------------------------------------------------------

def run_backtest() -> dict:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.brooks_failed_breakout import (
        BrooksFailedBreakoutStrategy,
        _default_manifest,
    )

    print("[1/5] Generating synthetic OHLCV (n=500, seed=42)...")
    df = _generate_ohlcv(n=500, seed=42)
    print(f"      Bars: {len(df)}, range: {df['ts'].iloc[0].date()} -> {df['ts'].iloc[-1].date()}")
    print(f"      Price range: {df['close'].min():.0f} - {df['close'].max():.0f} USDT")

    print("\n[2/5] Building strategy + features...")
    manifest = _default_manifest()
    strategy = BrooksFailedBreakoutStrategy(manifest)
    df_feat = strategy.prepare_features(df)
    new_cols = [c for c in df_feat.columns if c not in df.columns]
    print(f"      Features added: {new_cols}")

    # Sinyal ön özeti
    bull_bo_n = int(df_feat["bull_bo_bar"].sum())
    bear_bo_n = int(df_feat["bear_bo_bar"].sum())
    bull_trap_n = int(df_feat["bull_trap_short"].sum())
    bear_trap_n = int(df_feat["bear_trap_long"].sum())
    print(f"      Bull BO bars: {bull_bo_n}, Bear BO bars: {bear_bo_n}")
    print(f"      Bull traps (short setups): {bull_trap_n}")
    print(f"      Bear traps (long setups): {bear_trap_n}")

    print("\n[3/5] Generating signals...")
    signals = strategy.generate_signals(df_feat)
    long_sigs = [s for s in signals if s.direction == "long"]
    short_sigs = [s for s in signals if s.direction == "short"]
    print(f"      Signals generated: {len(signals)}")
    print(f"      Long (bear_trap): {len(long_sigs)}, Short (bull_trap): {len(short_sigs)}")

    print("\n[4/5] Running backtest engine...")
    start_dt = df["ts"].iloc[0].to_pydatetime()
    end_dt = df["ts"].iloc[-1].to_pydatetime()

    def ohlcv_provider(symbol: str, tf: str, start, end):
        return df_feat.copy()

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
        "df_feat": df_feat,
        "signals": signals,
        "result": result,
    }


# ---------------------------------------------------------------------------
# 3. Summary print
# ---------------------------------------------------------------------------

def print_summary(data: dict) -> None:
    result = data["result"]
    signals = data["signals"]
    kpis = result.kpis

    print("\n" + "=" * 65)
    print("BROOKS FAILED BREAKOUT / TRAP — BACKTEST RESULTS")
    print("=" * 65)
    print(f"Strategy:        {result.strategy_name}")
    print(f"Data:            Synthetic BTC/USDT, 500 daily bars")
    print(f"Signals:         {len(signals)}")
    print(f"Trades:          {result.n_trades}")

    win_rate = kpis.get("win_rate", 0.0)
    profit_factor = kpis.get("profit_factor", 0.0)
    expectancy = kpis.get("expectancy", 0.0)
    sharpe = kpis.get("sharpe", 0.0)
    sortino = kpis.get("sortino", 0.0)
    max_dd = kpis.get("max_drawdown", 0.0)
    cagr = kpis.get("cagr", 0.0)
    calmar = kpis.get("calmar", 0.0)
    dsr = kpis.get("deflated_sharpe", 0.0)

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
        print(f"  Min R:    {r_mults.min():.2f}")
        print(f"  Max R:    {r_mults.max():.2f}")
        print(f"  Mean R:   {r_mults.mean():.2f}")
        print(f"  Median R: {r_mults.median():.2f}")

        avg_win = kpis.get("avg_win", 0.0)
        avg_loss = kpis.get("avg_loss", 0.0)
        print(f"\n--- Per-Trade ---")
        print(f"  Avg Win:  {avg_win:+.2f} USDT")
        print(f"  Avg Loss: {avg_loss:+.2f} USDT")

        # Yıllık breakdown
        trades_df2 = trades_df.copy()
        trades_df2["year"] = pd.to_datetime(trades_df2["exit_ts"]).dt.year
        print(f"\n--- Yearly Breakdown ---")
        for yr, grp in trades_df2.groupby("year"):
            pnl = grp["realized_pnl_usdt"].sum()
            wr = (grp["realized_pnl_usdt"] > 0).mean() * 100
            print(f"  {yr}: n={len(grp):3d}, PnL=USD {pnl:+8.2f}, WR={wr:.0f}%")

        # Pattern breakdown
        if "pattern_id" in trades_df.columns:
            print(f"\n--- Pattern Breakdown ---")
            for pat, grp in trades_df.groupby("pattern_id"):
                wr_p = (grp["realized_pnl_usdt"] > 0).mean() * 100
                pnl_p = grp["realized_pnl_usdt"].sum()
                print(f"  {pat:<25} n={len(grp):3d}  WR={wr_p:.0f}%  PnL=USD {pnl_p:+.2f}")

        # Equity
        eq = result.equity_curve
        initial = eq.iloc[0]
        final = eq.iloc[-1]
        print(f"\n--- Equity ---")
        print(f"  Start: {initial:,.2f} USDT")
        print(f"  End:   {final:,.2f} USDT")
        print(f"  Net:   {final - initial:+,.2f} USDT ({(final/initial - 1):.2%})")
    else:
        print("\n  [No trades executed]")

    # Verdict
    print(f"\n--- VERDICT ---")
    if result.n_trades == 0:
        verdict = "INCONCLUSIVE — 0 trades (warmup/data issue)"
    elif win_rate >= 0.60 and profit_factor >= 1.5 and max_dd <= 0.20:
        verdict = "STRONG EDGE — Brooks iddiasıyla uyumlu (%65-75 WR, PF>1.5)"
    elif win_rate >= 0.50 and profit_factor >= 1.2:
        verdict = "MARGINAL EDGE — canlı test önerilir (daha uzun geriye dönük veri ile)"
    elif profit_factor < 1.0:
        verdict = "NO EDGE — negatif beklenti (parametre revizyonu gerekli)"
    else:
        verdict = f"NEEDS REVIEW — WR={win_rate:.0%}, PF={profit_factor:.2f}, DD={max_dd:.1%}"

    print(f"  {verdict}")
    print("=" * 65)


# ---------------------------------------------------------------------------
# 4. Report
# ---------------------------------------------------------------------------

def save_report(data: dict, path: Path) -> None:
    result = data["result"]
    signals = data["signals"]
    kpis = result.kpis
    trades_df = result.trades

    win_rate = kpis.get("win_rate", 0.0)
    profit_factor = kpis.get("profit_factor", 0.0)
    max_dd = kpis.get("max_drawdown", 0.0)
    cagr = kpis.get("cagr", 0.0)

    lines = [
        "# Brooks Failed Breakout / Trap — Backtest Report",
        "",
        f"**Strategy:** `{result.strategy_name}`  ",
        f"**Generated:** {datetime.now(timezone.utc).isoformat()}  ",
        f"**Data:** Synthetic BTC/USDT, 500 daily bars (seed=42)  ",
        f"**Period:** {result.start.date()} → {result.end.date()}  ",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Signals | {len(signals)} |",
        f"| Trades | {result.n_trades} |",
        f"| Win Rate | {win_rate:.1%} |",
        f"| Profit Factor | {profit_factor:.3f} |",
        f"| Expectancy | {kpis.get('expectancy', 0):+.2f} USDT/trade |",
        f"| Sharpe | {kpis.get('sharpe', 0):.3f} |",
        f"| Sortino | {kpis.get('sortino', 0):.3f} |",
        f"| Deflated Sharpe | {kpis.get('deflated_sharpe', 0):.3f} |",
        f"| Max Drawdown | {max_dd:.2%} |",
        f"| Calmar | {kpis.get('calmar', 0):.3f} |",
        f"| CAGR | {cagr:.2%} |",
        "",
    ]

    if not trades_df.empty:
        r_mults = trades_df["realized_r_multiple"]
        lines += [
            "## R-Multiple Distribution",
            "",
            "| Stat | Value |",
            "|------|-------|",
            f"| Min R | {r_mults.min():.2f} |",
            f"| Max R | {r_mults.max():.2f} |",
            f"| Mean R | {r_mults.mean():.2f} |",
            f"| Median R | {r_mults.median():.2f} |",
            "",
            "## Trades (all)",
            "",
            "| # | Entry ts | Side | Pattern | Entry | Exit | PnL (USDT) | R |",
            "|---|----------|------|---------|-------|------|------------|---|",
        ]
        for i, row in enumerate(trades_df.to_dict("records"), 1):
            lines.append(
                f"| {i} | {row.get('entry_ts', '')} | {row.get('side', '')} | "
                f"{row.get('pattern_id', '')} | {row.get('entry_price', 0):.0f} | "
                f"{row.get('exit_price', 0):.0f} | {row.get('realized_pnl_usdt', 0):+.2f} | "
                f"{row.get('realized_r_multiple', 0):.2f} |"
            )
        lines.append("")

    # Verdict
    if result.n_trades == 0:
        verdict = "INCONCLUSIVE — 0 trades"
    elif win_rate >= 0.60 and profit_factor >= 1.5 and max_dd <= 0.20:
        verdict = "STRONG EDGE"
    elif win_rate >= 0.50 and profit_factor >= 1.2:
        verdict = "MARGINAL EDGE"
    else:
        verdict = "NEEDS REVIEW / NO EDGE"

    lines += [
        "## Verdict",
        "",
        f"**{verdict}**",
        "",
        "Brooks iddiası: ~%65-75 win rate, 2-3:1 R:R, EV ~+0.8-1.5R",
        "",
    ]

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[5/5] Report saved: {path}")


# ---------------------------------------------------------------------------
# 5. Main
# ---------------------------------------------------------------------------

def main() -> int:
    print("=" * 65)
    print("BROOKS FAILED BREAKOUT / TRAP — BACKTEST")
    print("=" * 65)

    try:
        data = run_backtest()
    except Exception as exc:
        print(f"\n[FATAL] {exc}", file=sys.stderr)
        traceback.print_exc()
        return 1

    print_summary(data)

    ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_path = (
        Path(__file__).parent.parent / "reports" / "research"
        / f"backtest_brooks_failed_breakout_{ts_str}.md"
    )
    try:
        save_report(data, report_path)
    except Exception as exc:
        print(f"\n[WARN] Report save failed: {exc}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
