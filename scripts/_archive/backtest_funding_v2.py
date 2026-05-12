"""Backtest sweep: funding_mean_reversion v1.0.0 (baseline) vs v2.0.0 (revised).

Also runs engulfing_continuation for correlation analysis.
Synthetic 3-year data (2023-05-10 to 2026-05-08), 4 symbols (BTC, ETH, SOL, XRP).
Capital: $10,000 shared.
"""
from __future__ import annotations

import sys
sys.path.insert(0, "src")

import numpy as np
import pandas as pd
from datetime import datetime, timedelta, timezone

from price_action.strategies.base import StrategyManifest
from price_action.strategies.funding_mean_reversion import (
    FundingMeanReversionStrategy,
    _atr,
    _swing_high_low,
    _funding_z_score,
    _reversal_bar_bearish,
    _reversal_bar_bullish,
    _kaufman_er,
    _adaptive_funding_bands,
    merge_funding_to_ohlcv,
    BNB_EXCLUDED_SYMBOLS,
    REGIME_ER_MAX,
)
from price_action.backtest.engine import BacktestEngine
from price_action.backtest.metrics import compute_kpis


# =========================================================================
# Synthetic data
# =========================================================================

def make_3year_data(symbol: str, seed: int, base_price: float = 50_000.0, n_bars: int = 3 * 365 * 3):
    """3 years of 8h OHLCV + realistic funding rates with regime switching."""
    rng = np.random.default_rng(seed)
    start = datetime(2023, 5, 10, tzinfo=timezone.utc)
    n = n_bars

    close = np.empty(n)
    close[0] = base_price

    regime = 0
    regime_bars_left = 80
    for i in range(1, n):
        if regime_bars_left <= 0:
            regime = int(rng.integers(0, 3))
            regime_bars_left = int(rng.uniform(60, 250))
        regime_bars_left -= 1
        if regime == 0:
            ret = rng.normal(0, 0.008)
        elif regime == 1:
            ret = rng.normal(0.003, 0.010)
        else:
            ret = rng.normal(-0.003, 0.010)
        close[i] = max(close[i - 1] * float(np.exp(ret)), 1.0)

    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1.0 + np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * (1.0 - np.abs(rng.normal(0, 0.003, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(5e8, 5e9, n)
    ts = [start + timedelta(hours=8 * i) for i in range(n)]

    ohlcv = pd.DataFrame({
        "ts": ts, "open": open_, "high": high, "low": low,
        "close": close, "volume": volume,
        "venue": "binance", "symbol": symbol, "timeframe": "4h",
    })

    price_chg = np.concatenate([[0.0], np.diff(close) / np.where(close[:-1] > 0, close[:-1], 1.0)])
    funding_base = pd.Series(price_chg).rolling(12, min_periods=1).mean().values * 15.0
    funding_noise = rng.normal(0, 0.00005, n)
    funding_rate = funding_base + funding_noise + 0.0001
    funding_rate = np.clip(funding_rate, -0.003, 0.003)

    funding_df = pd.DataFrame({
        "venue": "binance", "symbol": symbol,
        "ts": ts,
        "funding_rate": funding_rate,
        "mark_price": close,
    })
    return ohlcv, funding_df


SYMBOLS = {
    "BTC/USDT:USDT": (42, 65_000.0),
    "ETH/USDT:USDT": (123, 3_500.0),
    "SOL/USDT:USDT": (456, 180.0),
    "XRP/USDT:USDT": (789, 0.60),
}

start_dt = datetime(2023, 5, 10, tzinfo=timezone.utc)
end_dt = datetime(2026, 5, 8, tzinfo=timezone.utc)

print("Building synthetic 3-year dataset...")
merged_data: dict[str, pd.DataFrame] = {}
for sym, (seed, base_price) in SYMBOLS.items():
    ohlcv, funding = make_3year_data(sym, seed, base_price)
    merged = merge_funding_to_ohlcv(ohlcv, funding, symbol=sym)
    merged["symbol"] = sym
    merged["timeframe"] = "4h"
    merged_data[sym] = merged

print(f"  {len(merged_data)} symbols x {len(merged_data['BTC/USDT:USDT'])} bars = "
      f"{len(merged_data) * len(merged_data['BTC/USDT:USDT'])} total bars\n")


# =========================================================================
# v1.0.0 Baseline — manual re-implementation (fixed threshold + z-score)
# =========================================================================

def simulate_v1(merged_data: dict[str, pd.DataFrame], initial_capital: float = 10_000.0):
    """v1.0.0: fixed +-0.0005 threshold + z-score >= 1.5, no regime filter, BNB included.

    Bar-by-bar simulation matching BacktestEngine logic:
    - One position at a time per symbol (in_position flag with proper exit tracking)
    - Entry at next bar open, exit on first SL/TP hit or EOD
    """
    threshold = 0.0005
    z_min = 1.5
    primary_r = 1.5
    atr_min_pct = 0.002
    risk_per_trade = 0.01

    all_trades = []
    equity = initial_capital

    for sym, df_raw in merged_data.items():
        df = df_raw.copy()
        df = df.sort_values("ts").reset_index(drop=True)
        df["atr14"] = _atr(df, 14)
        df["atr_pct"] = df["atr14"] / df["close"].replace(0, np.nan)
        sh, slv = _swing_high_low(df, 8)
        df["swing_high_8"] = sh
        df["swing_low_8"] = slv
        df["funding_rate_lag1"] = df["funding_rate"].shift(1)
        df["funding_z"] = _funding_z_score(df["funding_rate"], 90)
        df["funding_z_lag1"] = df["funding_z"].shift(1)
        df["reversal_bear"] = _reversal_bar_bearish(df, 0.35)
        df["reversal_bull"] = _reversal_bar_bullish(df, 0.35)

        n = len(df)
        i = 0
        while i < n - 1:
            row = df.iloc[i]
            atr_pct = float(row.get("atr_pct") or 0)
            atr = float(row.get("atr14") or 0)
            if np.isnan(atr) or atr <= 0 or atr_pct < atr_min_pct:
                i += 1
                continue
            fr = row.get("funding_rate_lag1")
            fz = row.get("funding_z_lag1")
            if fr is None or (isinstance(fr, float) and np.isnan(float(fr))):
                i += 1
                continue
            fr = float(fr)
            fz_val = float(fz) if (fz is not None and not (isinstance(fz, float) and np.isnan(float(fz)))) else 0.0

            close = float(row["close"])
            direction = None
            sl_price = 0.0

            if fr > threshold and fz_val > z_min and bool(row.get("reversal_bear", False)):
                direction = "short"
                sl_raw = float(row.get("swing_high_8") or (close + 2.0 * atr))
                sl_price = max(sl_raw, close + 0.3 * atr)
            elif fr < -threshold and fz_val < -z_min and bool(row.get("reversal_bull", False)):
                direction = "long"
                sl_raw = float(row.get("swing_low_8") or (close - 2.0 * atr))
                sl_price = min(sl_raw, close - 0.3 * atr)

            if direction is None:
                i += 1
                continue

            # Entry next bar open
            entry_bar = df.iloc[i + 1]
            slip = 0.0005
            entry_price = float(entry_bar["open"]) * (1 + slip if direction == "long" else 1 - slip)
            if direction == "long":
                risk = entry_price - sl_price
            else:
                risk = sl_price - entry_price
            if risk <= 0:
                i += 1
                continue

            risk_dollar = equity * risk_per_trade
            qty = risk_dollar / risk
            tp_price = (
                (entry_price + primary_r * risk) if direction == "long"
                else (entry_price - primary_r * risk)
            )

            # Forward simulation: find exit
            exit_price = entry_price
            exit_i = n - 1
            for j in range(i + 1, n):
                bar = df.iloc[j]
                hi, lo = float(bar["high"]), float(bar["low"])
                if direction == "long":
                    if lo <= sl_price:
                        exit_price = sl_price * (1 - slip)
                        exit_i = j
                        break
                    if hi >= tp_price:
                        exit_price = tp_price * (1 - slip)
                        exit_i = j
                        break
                else:
                    if hi >= sl_price:
                        exit_price = sl_price * (1 + slip)
                        exit_i = j
                        break
                    if lo <= tp_price:
                        exit_price = tp_price * (1 - slip)
                        exit_i = j
                        break
            else:
                exit_price = float(df.iloc[-1]["close"])

            if direction == "long":
                gross = (exit_price - entry_price) * qty
            else:
                gross = (entry_price - exit_price) * qty
            fee = (entry_price + exit_price) * qty * 0.00075
            net = gross - fee
            equity += net
            all_trades.append({
                "sym": sym, "direction": direction, "net_pnl": net,
                "entry": entry_price, "exit": exit_price,
                "ts_entry": pd.Timestamp(entry_bar["ts"]),
                "fr_at_signal": fr, "fz_at_signal": fz_val,
            })
            # Advance past the exit bar
            i = exit_i + 1

    return all_trades, equity


# =========================================================================
# v2.0.0 Revised — using the new strategy
# =========================================================================

def make_v2_manifest():
    raw = {
        "name": "funding_mean_reversion",
        "version": "2.0.0",
        "trend_filter": {"type": "none", "period": 0, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "funding_fade_short", "enabled": True, "weight": 1.0,
                    "params": {
                        "adaptive_window": 60,
                        "extreme_pctile_high": 95.0,
                        "reversal_body_ratio_min": 0.35,
                        "swing_lookback": 8,
                        "kaufman_er_max": 0.30,
                        "kaufman_er_period": 14,
                    },
                },
                {
                    "id": "funding_fade_long", "enabled": True, "weight": 1.0,
                    "params": {
                        "adaptive_window": 60,
                        "extreme_pctile_low": 5.0,
                        "reversal_body_ratio_min": 0.35,
                        "swing_lookback": 8,
                        "kaufman_er_max": 0.30,
                        "kaufman_er_period": 14,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 60, "cluster_atr_multiplier": 0.5,
                    "min_touches": 2, "max_age_bars": 60,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {"atr_min_pct": 0.002},
            "confluence": {"method": "weighted_sum", "min_score": 1.0},
        },
        "risk": {
            "take_profit": {"method": "r_multiple", "primary_R": 1.5},
        },
    }
    return StrategyManifest.model_validate(raw)


def simulate_v2(merged_data: dict[str, pd.DataFrame], initial_capital: float = 10_000.0):
    """v2.0.0: adaptive threshold + regime filter + BNB excluded."""
    strat = FundingMeanReversionStrategy(make_v2_manifest())
    engine = BacktestEngine()

    def provider(sym, tf, start, end):
        df = merged_data.get(sym)
        if df is None:
            return pd.DataFrame()
        s = pd.Timestamp(start)
        e = pd.Timestamp(end)
        if s.tzinfo is None:
            s = s.tz_localize("UTC")
        if e.tzinfo is None:
            e = e.tz_localize("UTC")
        mask = (df["ts"] >= s) & (df["ts"] <= e)
        return df[mask].copy()

    result = engine.run(
        strat,
        universe=list(merged_data.keys()),
        start=start_dt,
        end=end_dt,
        initial_capital=initial_capital,
        timeframe="4h",
        ohlcv_provider=provider,
    )
    return result


# =========================================================================
# Run both versions
# =========================================================================
INITIAL_CAPITAL = 10_000.0

print("=" * 60)
print("v1.0.0 BASELINE (fixed threshold +-0.0005 + z-score, BNB included)")
print("=" * 60)
v1_trades, v1_final_equity = simulate_v1(merged_data, INITIAL_CAPITAL)
v1_pnl = pd.Series([t["net_pnl"] for t in v1_trades])
v1_total_return = (v1_final_equity / INITIAL_CAPITAL - 1.0) * 100
v1_wr = float((v1_pnl > 0).mean()) * 100 if not v1_pnl.empty else 0.0
v1_pf = float(v1_pnl[v1_pnl > 0].sum() / (-v1_pnl[v1_pnl < 0].sum())) if (v1_pnl < 0).any() else float("inf")

print(f"  N trades:       {len(v1_trades)}")
print(f"  Total return:   {v1_total_return:+.1f}%")
print(f"  Win rate:       {v1_wr:.1f}%")
print(f"  Profit factor:  {v1_pf:.2f}")
print(f"  Avg win:        ${v1_pnl[v1_pnl > 0].mean():.1f}" if (v1_pnl > 0).any() else "  Avg win:        n/a")
print(f"  Avg loss:       ${v1_pnl[v1_pnl < 0].mean():.1f}" if (v1_pnl < 0).any() else "  Avg loss:        n/a")
yearly_v1 = v1_total_return / 3.0
print(f"  Yearly (approx): {yearly_v1:+.1f}%")

# Per-symbol breakdown v1
sym_counts_v1 = {}
for t in v1_trades:
    sym_counts_v1[t["sym"]] = sym_counts_v1.get(t["sym"], 0) + 1
print("\n  Per-symbol trade counts:")
for sym, cnt in sorted(sym_counts_v1.items()):
    sym_pnls = [t["net_pnl"] for t in v1_trades if t["sym"] == sym]
    print(f"    {sym}: {cnt} trades, PnL=${sum(sym_pnls):+.1f}")

print()
print("=" * 60)
print("v2.0.0 REVISED (adaptive 95th/5th pctile + ER<0.30 + BNB excluded)")
print("=" * 60)
v2_result = simulate_v2(merged_data, INITIAL_CAPITAL)
v2_kpis = v2_result.kpis
v2_total_return = (v2_result.equity_curve.iloc[-1] / INITIAL_CAPITAL - 1.0) * 100
v2_wr = v2_kpis.get("win_rate", 0) * 100
v2_pf = v2_kpis.get("profit_factor", 0)
v2_n = v2_result.n_trades
yearly_v2 = v2_total_return / 3.0

print(f"  N trades:       {v2_n}")
print(f"  Total return:   {v2_total_return:+.1f}%")
print(f"  Yearly (approx): {yearly_v2:+.1f}%")
print(f"  Sharpe:         {v2_kpis.get('sharpe', 0):.2f}")
print(f"  Win rate:       {v2_wr:.1f}%")
print(f"  Profit factor:  {v2_pf:.2f}")
print(f"  Max drawdown:   {v2_kpis.get('max_drawdown', 0)*100:.1f}%")
print(f"  Avg win:        ${v2_kpis.get('avg_win', 0):.1f}")
print(f"  Avg loss:       ${v2_kpis.get('avg_loss', 0):.1f}")

# Per-symbol trade counts v2
if not v2_result.trades.empty:
    print("\n  Per-symbol trade counts:")
    for sym in merged_data.keys():
        sym_trades = v2_result.trades[v2_result.trades["symbol"] == sym] if "symbol" in v2_result.trades.columns else pd.DataFrame()
        if not sym_trades.empty:
            pnl_sum = sym_trades["realized_pnl_usdt"].sum()
            print(f"    {sym}: {len(sym_trades)} trades, PnL=${pnl_sum:+.1f}")
        else:
            print(f"    {sym}: 0 trades")

# =========================================================================
# Improvement summary
# =========================================================================
print()
print("=" * 60)
print("IMPROVEMENT SUMMARY")
print("=" * 60)
improvement = v2_total_return - v1_total_return
improvement_yearly = yearly_v2 - yearly_v1
print(f"  Baseline total return:  {v1_total_return:+.1f}% ({yearly_v1:+.1f}%/year)")
print(f"  Revised  total return:  {v2_total_return:+.1f}% ({yearly_v2:+.1f}%/year)")
print(f"  Delta:                  {improvement:+.1f}% total ({improvement_yearly:+.1f}%/year)")
print(f"  Trade count: v1={len(v1_trades)} -> v2={v2_n} ({v2_n - len(v1_trades):+d})")

# =========================================================================
# Engulfing strategy — for decorrelation analysis
# =========================================================================
print()
print("=" * 60)
print("ENGULFING CONTINUATION — decorrelation check")
print("=" * 60)
from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy

def make_engulfing_strategy():
    raw = {
        "name": "engulfing_continuation",
        "version": "1.0.0",
        "trend_filter": {"type": "ema", "period": 50, "required": True},
        "signals": {
            "patterns": [
                {"id": "bullish_engulfing_cont", "enabled": True, "weight": 1.5,
                 "params": {"body_ratio_min": 0.6, "pullback_window": 10, "pullback_touch_atr": 0.5}},
                {"id": "bearish_engulfing_cont", "enabled": True, "weight": 1.5,
                 "params": {"body_ratio_min": 0.6, "pullback_window": 10, "pullback_touch_atr": 0.5}},
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {"lookback_bars": 120, "cluster_atr_multiplier": 0.5, "min_touches": 2, "max_age_bars": 120},
                "require_proximity_to_sr_atr": 0.5,
            },
            "filters": {"atr_min_pct": 0.005, "kaufman_er_period": 14, "kaufman_er_min": 0.20},
            "confluence": {"method": "weighted_sum", "min_score": 1.5, "bonus_if_at_sr": 0.5},
        },
        "risk": {
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
        },
    }
    return EngulfingContinuationStrategy(StrategyManifest.model_validate(raw))

engulf_strat = make_engulfing_strategy()
engine2 = BacktestEngine()

# Use only OHLCV columns (no funding) for engulfing
ohlcv_only = {
    sym: df[["ts", "open", "high", "low", "close", "volume", "venue", "symbol", "timeframe"]].copy()
    for sym, df in merged_data.items()
}

def engulf_provider(sym, tf, start, end):
    df = ohlcv_only.get(sym)
    if df is None:
        return pd.DataFrame()
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    if s.tzinfo is None:
        s = s.tz_localize("UTC")
    if e.tzinfo is None:
        e = e.tz_localize("UTC")
    mask = (df["ts"] >= s) & (df["ts"] <= e)
    return df[mask].copy()

eng_result = engine2.run(
    engulf_strat,
    universe=list(merged_data.keys()),
    start=start_dt,
    end=end_dt,
    initial_capital=INITIAL_CAPITAL,
    timeframe="4h",
    ohlcv_provider=engulf_provider,
)

eng_total_return = (eng_result.equity_curve.iloc[-1] / INITIAL_CAPITAL - 1.0) * 100
eng_yearly = eng_total_return / 3.0
print(f"  Engulfing N trades:     {eng_result.n_trades}")
print(f"  Engulfing total return: {eng_total_return:+.1f}% ({eng_yearly:+.1f}%/year)")
print(f"  Engulfing Sharpe:       {eng_result.kpis.get('sharpe', 0):.2f}")
print(f"  Engulfing win rate:     {eng_result.kpis.get('win_rate', 0)*100:.1f}%")

# R-multiple correlation between engulfing and funding MR
if not v2_result.trades.empty and not eng_result.trades.empty:
    v2_rmults = v2_result.trades["realized_r_multiple"].values
    eng_rmults = eng_result.trades["realized_r_multiple"].values
    # Align by length for correlation (both time-sorted, different sizes)
    # Use rolling monthly binning instead
    def monthly_pnl(trades_df, start):
        if trades_df.empty:
            return pd.Series(dtype=float)
        trades_df = trades_df.copy()
        trades_df["exit_ts"] = pd.to_datetime(trades_df["exit_ts"], utc=True, errors="coerce")
        trades_df["month"] = trades_df["exit_ts"].dt.to_period("M")
        return trades_df.groupby("month")["realized_pnl_usdt"].sum()

    v2_monthly = monthly_pnl(v2_result.trades, start_dt)
    eng_monthly = monthly_pnl(eng_result.trades, start_dt)
    common_months = v2_monthly.index.intersection(eng_monthly.index)
    if len(common_months) >= 3:
        corr = float(np.corrcoef(
            v2_monthly.loc[common_months].values,
            eng_monthly.loc[common_months].values
        )[0, 1])
        print(f"\n  Monthly PnL correlation (Funding MR vs Engulfing): r={corr:.3f}")
        print(f"  (|r| < 0.3 = decorrelated, |r| < 0.1 = near-orthogonal)")
        if abs(corr) < 0.15:
            print("  -> NEAR-ORTHOGONAL: excellent diversification")
        elif abs(corr) < 0.30:
            print("  -> DECORRELATED: good diversification")
        else:
            print("  -> CORRELATED: check regime overlap")
    else:
        print(f"\n  Not enough common months ({len(common_months)}) for correlation.")

# =========================================================================
# Combined portfolio simulation
# =========================================================================
print()
print("=" * 60)
print("COMBINED PORTFOLIO (Funding MR v2 + Engulfing)")
print("=" * 60)

# Merge equity curves
v2_daily = v2_result.equity_curve.resample("D").last().ffill()
eng_daily = eng_result.equity_curve.resample("D").last().ffill()
common_idx = v2_daily.index.intersection(eng_daily.index)
if len(common_idx) > 2:
    # Equal-weight combined (each starts at $10k, combined = $20k notional)
    combined = v2_daily.loc[common_idx] + eng_daily.loc[common_idx]
    combined_return = (combined.iloc[-1] / combined.iloc[0] - 1.0) * 100
    combined_yearly = combined_return / 3.0

    combined_rets = combined.pct_change().dropna()
    combined_sharpe = float(
        np.sqrt(365) * combined_rets.mean() / combined_rets.std(ddof=0)
    ) if combined_rets.std(ddof=0) > 0 else 0.0

    print(f"  Combined total return:  {combined_return:+.1f}% ({combined_yearly:+.1f}%/year)")
    print(f"  Combined Sharpe:        {combined_sharpe:.2f}")
    print(f"  vs Engulfing alone:     {eng_total_return:+.1f}% / Sharpe {eng_result.kpis.get('sharpe', 0):.2f}")
    print(f"  vs Funding MR v2 alone: {v2_total_return:+.1f}% / Sharpe {v2_kpis.get('sharpe', 0):.2f}")

# =========================================================================
# VERDICT
# =========================================================================
print()
print("=" * 60)
print("VERDICT")
print("=" * 60)
if yearly_v2 > 3.0 and v2_kpis.get("sharpe", 0) > 0.5 and v2_kpis.get("profit_factor", 0) > 1.1:
    verdict = "PROMOTE"
elif yearly_v2 > 0.0 or (v2_total_return > v1_total_return + 3.0):
    verdict = "DEFER (re-run with live data)"
else:
    verdict = "REJECT"

print(f"  Baseline v1.0.0: {yearly_v1:+.1f}%/year")
print(f"  Revised  v2.0.0: {yearly_v2:+.1f}%/year")
print(f"  Improvement:     {improvement_yearly:+.1f}%/year")
print(f"  Sharpe v2:       {v2_kpis.get('sharpe', 0):.2f}")
print(f"  Profit factor:   {v2_pf:.2f}")
print(f"")
print(f"  VERDICT: {verdict}")
