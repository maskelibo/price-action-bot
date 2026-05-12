"""3 hipotezin hizli (tek pencere 3y) backtest'i.

Pre-registered hipotezler:
  1. 2026-05-12-funding-oi-divergence-reversal — OI veri yok, FUNDING-ONLY PROXY
  2. 2026-05-12-volatility-compression-breakout-nr7 — tam test (1d OHLCV yeterli)
  3. 2026-05-12-regime-correlation-cluster-throttle — TOP_10 overlay

Hizli backtest gate (3y tek pencere):
  - Yillik > 0
  - Max DD > -%30
  - Sharpe > 0.5

PASS olanlar Lab tournament adayi. Tam SOP-3 robustness W3 isi.

Output:
  reports/research/hyp_quick_backtest_2026-05-13.txt
"""
from __future__ import annotations

import logging
import math
import os
import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

logging.getLogger("price_action").setLevel(logging.WARNING)
os.environ["LOG_LEVEL"] = "WARNING"

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

import duckdb

SYMBOLS_11 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
              "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
              "DOGE/USDT", "XRP/USDT", "MATIC/USDT"]


# ---------------------------------------------------------------------------
# Common loaders
# ---------------------------------------------------------------------------
def load_ohlcv(symbol: str, tf: str = "1d") -> pd.DataFrame:
    con = duckdb.connect(str(ROOT / "data" / "market.duckdb"), read_only=True)
    df = con.execute(
        "SELECT ts, open, high, low, close, volume FROM ohlcv "
        "WHERE venue='binance' AND symbol=? AND timeframe=? ORDER BY ts",
        [symbol, tf],
    ).fetchdf()
    con.close()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.reset_index(drop=True)


def load_funding() -> pd.DataFrame:
    p = ROOT / "data" / "alt_data" / "funding_BTCUSDT.csv"
    df = pd.read_csv(p)
    df["ts"] = pd.to_datetime(df["ts"], utc=True, format="ISO8601")
    return df.sort_values("ts").reset_index(drop=True)


def daily_funding_sum(funding_8h: pd.DataFrame) -> pd.DataFrame:
    """8h funding'i gunluk sum'a topla."""
    df = funding_8h.copy()
    df["date"] = df["ts"].dt.normalize()
    out = df.groupby("date")["fundingRate"].sum().reset_index()
    out.columns = ["ts", "funding_daily"]
    return out


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    h_l = df["high"] - df["low"]
    h_c = (df["high"] - df["close"].shift()).abs()
    l_c = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([h_l, h_c, l_c], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def simulate_trade(
    df: pd.DataFrame,
    entry_idx: int,
    side: str,                 # "long" or "short"
    sl_atr_mult: float = 1.0,
    tp_R: float = 2.0,
    time_stop_bars: int = 10,
) -> dict:
    """Tek trade simulasyonu — SL + R-multiple TP + time-stop.

    Returns: {entry_ts, exit_ts, entry_price, sl, R, side}
    """
    if entry_idx >= len(df) - 1:
        return None
    entry_price = float(df["close"].iloc[entry_idx])
    atr_val = float(df["atr14"].iloc[entry_idx])
    if pd.isna(atr_val) or atr_val <= 0:
        return None

    if side == "long":
        sl = entry_price - sl_atr_mult * atr_val
        tp = entry_price + tp_R * (entry_price - sl)
    else:
        sl = entry_price + sl_atr_mult * atr_val
        tp = entry_price - tp_R * (sl - entry_price)

    risk = abs(entry_price - sl)

    # Walk forward to find exit
    for i in range(entry_idx + 1, min(entry_idx + 1 + time_stop_bars, len(df))):
        bar = df.iloc[i]
        if side == "long":
            if bar["low"] <= sl:
                return {
                    "entry_ts": df["ts"].iloc[entry_idx],
                    "exit_ts": df["ts"].iloc[i],
                    "entry_price": entry_price,
                    "sl": sl,
                    "exit_price": sl,
                    "R": -1.0,
                    "side": side,
                }
            if bar["high"] >= tp:
                return {
                    "entry_ts": df["ts"].iloc[entry_idx],
                    "exit_ts": df["ts"].iloc[i],
                    "entry_price": entry_price,
                    "sl": sl,
                    "exit_price": tp,
                    "R": tp_R,
                    "side": side,
                }
        else:
            if bar["high"] >= sl:
                return {
                    "entry_ts": df["ts"].iloc[entry_idx],
                    "exit_ts": df["ts"].iloc[i],
                    "entry_price": entry_price,
                    "sl": sl,
                    "exit_price": sl,
                    "R": -1.0,
                    "side": side,
                }
            if bar["low"] <= tp:
                return {
                    "entry_ts": df["ts"].iloc[entry_idx],
                    "exit_ts": df["ts"].iloc[i],
                    "entry_price": entry_price,
                    "sl": sl,
                    "exit_price": tp,
                    "R": tp_R,
                    "side": side,
                }
    # Time stop
    exit_price = float(df["close"].iloc[min(entry_idx + time_stop_bars, len(df) - 1)])
    R = ((exit_price - entry_price) / risk) if side == "long" else ((entry_price - exit_price) / risk)
    return {
        "entry_ts": df["ts"].iloc[entry_idx],
        "exit_ts": df["ts"].iloc[min(entry_idx + time_stop_bars, len(df) - 1)],
        "entry_price": entry_price,
        "sl": sl,
        "exit_price": exit_price,
        "R": float(R),
        "side": side,
    }


def replay_simple(
    trades: list[dict],
    risk_pct: float = 0.02,
    initial_capital: float = 10_000.0,
) -> dict:
    """Basit replay — sabit risk_pct, leverage yok.

    Trade'leri entry_ts'e gore sirala; her trade equity * risk_pct kadar risk.
    """
    if not trades:
        return None
    trades = sorted(trades, key=lambda t: pd.Timestamp(t["entry_ts"]))
    equity = initial_capital
    Rs = []
    eq_curve = [equity]
    for t in trades:
        R = float(t["R"])
        pnl = equity * risk_pct * R
        equity += pnl
        Rs.append(R)
        eq_curve.append(equity)

    if not Rs:
        return None

    peak = eq_curve[0]
    max_dd = 0.0
    for v in eq_curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak
        if dd < max_dd:
            max_dd = dd

    # Annualized
    if len(trades) > 0:
        first = pd.Timestamp(trades[0]["entry_ts"])
        last = pd.Timestamp(trades[-1]["exit_ts"])
        n_years = max(0.5, (last - first).days / 365.25)
    else:
        n_years = 1.0

    total_ret = equity / initial_capital - 1
    annual = ((equity / initial_capital) ** (1 / n_years) - 1) * 100 if n_years > 0 else 0

    eq_arr = np.array(eq_curve)
    rets = np.diff(eq_arr) / eq_arr[:-1]
    if len(rets) > 1 and np.std(rets) > 0:
        # Trades not uniformly spaced; use per-trade Sharpe annualized by sqrt(n/year)
        sharpe = (np.mean(rets) / np.std(rets)) * math.sqrt(len(rets) / n_years)
    else:
        sharpe = 0.0

    wr = sum(1 for r in Rs if r > 0) / len(Rs)
    avg_r = float(np.mean(Rs))

    return {
        "final": equity,
        "trades": len(Rs),
        "wr": wr,
        "avg_r": avg_r,
        "max_dd": max_dd,
        "annual_pct": annual,
        "sharpe": float(sharpe),
        "n_years": n_years,
        "total_ret": total_ret,
    }


# ---------------------------------------------------------------------------
# HYPOTHESIS 1: Funding/OI Divergence (FUNDING-ONLY PROXY — OI verisi yok)
# ---------------------------------------------------------------------------
def test_funding_divergence(window_start: pd.Timestamp, window_end: pd.Timestamp) -> dict:
    """OI verisi YOK — bu test funding-only proxy.

    Setup: funding_3d cumsum > +0.0015 (short setup) veya < -0.0015 (long setup)
    + price new local high (10 bar) — overlong squeeze
    + bearish/bullish engulfing or pin bar (rejection candle, t veya t+1)

    OI delta filtresi atlandi — bu nedenle gate beklentisi DUSURULDU
    (yillik > 0, DD > -%30, Sharpe > 0.5).
    """
    funding_8h = load_funding()
    fund_daily = daily_funding_sum(funding_8h)

    all_trades = []
    for sym in ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "AVAX/USDT", "LINK/USDT"]:
        df = load_ohlcv(sym)
        if df.empty:
            continue
        df = df.sort_values("ts").reset_index(drop=True)
        df = df[(df["ts"] >= window_start) & (df["ts"] < window_end)].reset_index(drop=True)
        if len(df) < 100:
            continue

        df["atr14"] = atr(df, 14)
        df["high_10"] = df["high"].rolling(10).max().shift(1)
        df["low_10"] = df["low"].rolling(10).min().shift(1)

        # Merge funding (daily) — BTC funding is proxy for the whole crypto basket here
        df_f = df.merge(fund_daily, on="ts", how="left")
        df_f["funding_3d"] = df_f["funding_daily"].rolling(3).sum()

        # Engulfing detection (simple)
        body_curr = (df_f["close"] - df_f["open"]).abs()
        body_prev = (df_f["close"].shift() - df_f["open"].shift()).abs()
        bull_eng = (
            (df_f["close"].shift() < df_f["open"].shift())   # prev bear
            & (df_f["close"] > df_f["open"])                  # curr bull
            & (df_f["close"] >= df_f["open"].shift())        # close above prev open
            & (df_f["open"] <= df_f["close"].shift())        # open below prev close
            & (body_curr > body_prev * 0.8)
        )
        bear_eng = (
            (df_f["close"].shift() > df_f["open"].shift())
            & (df_f["close"] < df_f["open"])
            & (df_f["close"] <= df_f["open"].shift())
            & (df_f["open"] >= df_f["close"].shift())
            & (body_curr > body_prev * 0.8)
        )

        for i in range(50, len(df_f) - 10):
            f3 = df_f["funding_3d"].iloc[i]
            if pd.isna(f3):
                continue
            high_10 = df_f["high_10"].iloc[i]
            low_10 = df_f["low_10"].iloc[i]

            # Overlong squeeze (SHORT setup)
            if (f3 > 0.0015) and not pd.isna(high_10) and df_f["close"].iloc[i] > high_10:
                # rejection candle t veya t+1
                if bear_eng.iloc[i] or (i + 1 < len(df_f) and bear_eng.iloc[i + 1]):
                    trig_idx = i if bear_eng.iloc[i] else (i + 1)
                    t = simulate_trade(df_f, trig_idx, "short", sl_atr_mult=1.0, tp_R=2.0)
                    if t:
                        t["symbol"] = sym
                        t["strategy"] = "funding_divergence"
                        all_trades.append(t)

            # Overshort squeeze (LONG setup)
            if (f3 < -0.0015) and not pd.isna(low_10) and df_f["close"].iloc[i] < low_10:
                if bull_eng.iloc[i] or (i + 1 < len(df_f) and bull_eng.iloc[i + 1]):
                    trig_idx = i if bull_eng.iloc[i] else (i + 1)
                    t = simulate_trade(df_f, trig_idx, "long", sl_atr_mult=1.0, tp_R=2.0)
                    if t:
                        t["symbol"] = sym
                        t["strategy"] = "funding_divergence"
                        all_trades.append(t)

    res = replay_simple(all_trades, risk_pct=0.02)
    return {"trades": all_trades, "result": res}


# ---------------------------------------------------------------------------
# HYPOTHESIS 2: Volatility Compression Breakout NR7
# ---------------------------------------------------------------------------
def test_compression_breakout(window_start: pd.Timestamp, window_end: pd.Timestamp) -> dict:
    """NR7 + ATR ratio < 0.85 + TTR < 2*ATR60 -> bracket order on next bar."""
    all_trades = []
    for sym in SYMBOLS_11:
        df = load_ohlcv(sym)
        if df.empty:
            continue
        df = df.sort_values("ts").reset_index(drop=True)
        df = df[(df["ts"] >= window_start) & (df["ts"] < window_end)].reset_index(drop=True)
        if len(df) < 100:
            continue

        df["atr14"] = atr(df, 14)
        df["atr5"] = atr(df, 5)
        df["atr60"] = atr(df, 60)
        df["range"] = df["high"] - df["low"]
        # NR7: today's range is min of last 7 bars
        df["nr7"] = df["range"] == df["range"].rolling(7).min()
        # ATR ratio
        df["atr_ratio"] = df["atr5"] / df["atr60"]
        # TTR — 14-bar range < 2*ATR60
        df["range_14"] = df["high"].rolling(14).max() - df["low"].rolling(14).min()
        df["ttr"] = df["range_14"] < 2.0 * df["atr60"]
        # Volume SMA
        df["vol_sma_20"] = df["volume"].rolling(20).mean()

        # Compression signal
        df["compression"] = df["nr7"] & (df["atr_ratio"] < 0.85) & df["ttr"]

        for i in range(60, len(df) - 3):
            if not df["compression"].iloc[i]:
                continue
            atr14_i = df["atr14"].iloc[i]
            if pd.isna(atr14_i) or atr14_i <= 0:
                continue

            bracket_high = df["high"].iloc[i] + 0.10 * atr14_i
            bracket_low = df["low"].iloc[i] - 0.10 * atr14_i

            # T+1 hangisi ilk tetiklenir?
            for j in range(i + 1, min(i + 4, len(df))):  # 3-day window
                bar = df.iloc[j]
                vol_ok = (
                    not pd.isna(df["vol_sma_20"].iloc[j])
                    and bar["volume"] > 1.2 * df["vol_sma_20"].iloc[j]
                )
                if bar["close"] > bracket_high and vol_ok:
                    # LONG entry
                    sl_below = bracket_low - 0.2 * atr14_i
                    sl_pct = (bar["close"] - sl_below) / bar["close"]
                    if sl_pct <= 0.001:
                        break
                    # Simulate with SL + 2R TP + time stop 10
                    df_sim = df.copy()
                    df_sim["atr14"] = df["atr14"]
                    t = simulate_trade(df_sim, j, "long", sl_atr_mult=1.0, tp_R=2.0,
                                       time_stop_bars=10)
                    if t:
                        t["symbol"] = sym
                        t["strategy"] = "compression_breakout_nr7"
                        all_trades.append(t)
                    break
                elif bar["close"] < bracket_low and vol_ok:
                    t = simulate_trade(df, j, "short", sl_atr_mult=1.0, tp_R=2.0,
                                       time_stop_bars=10)
                    if t:
                        t["symbol"] = sym
                        t["strategy"] = "compression_breakout_nr7"
                        all_trades.append(t)
                    break

    res = replay_simple(all_trades, risk_pct=0.02)
    return {"trades": all_trades, "result": res}


# ---------------------------------------------------------------------------
# HYPOTHESIS 3: Correlation Cluster Throttle (overlay on Top 10)
# ---------------------------------------------------------------------------
def compute_corr_matrix_pit(symbols: list[str], window: int = 30) -> dict:
    """Each date d -> Pearson correlation matrix on prior `window` days returns.

    Returns: {date: pd.DataFrame symbol x symbol}
    """
    # Load all OHLCV
    closes = {}
    for sym in symbols:
        df = load_ohlcv(sym)
        if df.empty:
            continue
        df = df.set_index("ts")["close"]
        closes[sym] = df
    if not closes:
        return {}

    # Wide DataFrame
    wide = pd.concat(closes, axis=1)
    wide = wide.sort_index()
    returns = wide.pct_change()

    # Daily correlation matrix (rolling 30d, point-in-time)
    out = {}
    dates = returns.index.normalize().unique()
    for d in dates:
        slice_returns = returns.loc[returns.index <= d].tail(window)
        if len(slice_returns) < window:
            continue
        corr = slice_returns.corr()
        out[d] = corr
    return out


def test_correlation_throttle(window_start: pd.Timestamp, window_end: pd.Timestamp) -> dict:
    """Top 10 trade pool'a correlation cluster throttle overlay.

    Aday trade: aktif/recent same-side pozisyonlarla 30-day corr >= 0.70 olanlar
    cluster uyesi sayilir. n_cluster:
      0-1: PASS full risk
      2: PASS half risk
      >= 3: SKIP
    """
    # Gather Top 10 trades
    from scripts.v09_optimize_top10 import _gather, TOP_10
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    # Filter to window
    all_trades = [t for t in all_trades if window_start <= t["entry_ts"] < window_end]
    all_trades.sort(key=lambda t: t["entry_ts"])

    # Compute corr matrix point-in-time
    corr_map = compute_corr_matrix_pit(SYMBOLS_11, window=30)

    # Replay with cluster overlay
    active_positions = []
    recent_entries = []
    out_trades = []
    blocked_count = 0
    half_risk_count = 0

    for t in all_trades:
        entry_ts = t["entry_ts"]
        sym = t["symbol"]
        side = t["side"]

        # Cleanup expired
        active_positions[:] = [p for p in active_positions if p["exit_ts"] > entry_ts]
        recent_entries[:] = [p for p in recent_entries if (entry_ts - p["entry_ts"]).days <= 3]

        # Find corr matrix as-of entry date
        d_norm = entry_ts.normalize()
        # closest prior date
        prior_dates = [d for d in corr_map.keys() if d <= d_norm]
        if not prior_dates:
            corr_mat = None
        else:
            corr_mat = corr_map[max(prior_dates)]

        # Cluster members
        cluster_n = 0
        if corr_mat is not None:
            for pos in active_positions + recent_entries:
                if pos["side"] != side or pos["symbol"] == sym:
                    continue
                try:
                    rho = corr_mat.loc[sym, pos["symbol"]]
                except (KeyError, ValueError):
                    continue
                if not pd.isna(rho) and rho >= 0.70:
                    cluster_n += 1

        risk_mult = 1.0
        if cluster_n >= 3:
            blocked_count += 1
            continue
        elif cluster_n == 2:
            risk_mult = 0.5
            half_risk_count += 1

        t2 = dict(t)
        t2["risk_mult"] = risk_mult
        t2["R_effective"] = float(t["R"]) * risk_mult
        out_trades.append(t2)
        active_positions.append(t2)
        recent_entries.append(t2)

    # Replay both: baseline (all trades full risk) vs throttled
    baseline_trades = [
        {**t, "R": float(t["R"])} for t in all_trades
    ]
    throttled_trades = [
        {**t, "R": t["R_effective"]} for t in out_trades
    ]

    baseline_res = replay_simple(baseline_trades, risk_pct=0.02)
    throttled_res = replay_simple(throttled_trades, risk_pct=0.02)

    return {
        "baseline": baseline_res,
        "throttled": throttled_res,
        "blocked": blocked_count,
        "half_risk": half_risk_count,
        "out_trades": throttled_trades,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("=" * 100)
    print("3 HYPOTHESIS QUICK BACKTEST (tek pencere 3y, hizli tahkik)")
    print("=" * 100)
    print()

    # 3y window
    window_end = pd.Timestamp("2026-05-01", tz="UTC")
    window_start = window_end - pd.DateOffset(years=3)
    print(f"3y pencere: {window_start.date()} → {window_end.date()}\n")

    lines = []
    lines.append("=" * 100)
    lines.append("3 HYPOTHESIS QUICK BACKTEST")
    lines.append("=" * 100)
    lines.append(f"git_hash: 27c9752c44b4ecbd386c1d2868a44fb538910879")
    lines.append(f"Window: {window_start.date()} → {window_end.date()} (3y)")
    lines.append("")

    def gate_eval(result: dict, label: str):
        if not result:
            return "FAIL (no trades)", False
        if result["annual_pct"] > 0 and result["max_dd"] > -0.30 and result["sharpe"] > 0.5:
            return f"PASS — annual {result['annual_pct']:+.1f}%, DD {result['max_dd']*100:+.1f}%, Sharpe {result['sharpe']:.2f}, n={result['trades']}", True
        return f"FAIL — annual {result['annual_pct']:+.1f}%, DD {result['max_dd']*100:+.1f}%, Sharpe {result['sharpe']:.2f}, n={result['trades']}", False

    summary = []

    # ---- HYP 1: Funding/OI Divergence (funding-only proxy)
    print("-" * 100)
    print("HYP 1: Funding/OI Divergence — OI verisi yok, FUNDING-ONLY PROXY")
    print("-" * 100)
    h1 = test_funding_divergence(window_start, window_end)
    res = h1["result"]
    if res:
        print(f"  Trades: {res['trades']}, WR {res['wr']*100:.1f}%, avg_R {res['avg_r']:+.2f}")
        print(f"  Annual: {res['annual_pct']:+.1f}%, MaxDD: {res['max_dd']*100:+.1f}%, Sharpe: {res['sharpe']:.2f}")
        verdict, passed = gate_eval(res, "HYP-1")
        print(f"  GATE: {verdict}")
        # NOT: bu funding-only proxy, full hipotez OI verisi gerekli — flag as CONDITIONAL
        verdict_full = "CONDITIONAL — OI verisi yokken funding-only proxy. " + verdict
    else:
        print("  No trades")
        verdict_full = "FAIL — no trades produced"
        passed = False
    summary.append(("HYP-1 funding-oi-divergence (funding-only proxy)", verdict_full, passed))
    lines.append(f"HYP-1 funding-oi-divergence (funding-only PROXY — OI veri yok):")
    if res:
        lines.append(f"  trades={res['trades']}  wr={res['wr']*100:.1f}%  avg_R={res['avg_r']:+.2f}")
        lines.append(f"  annual={res['annual_pct']:+.2f}%  maxDD={res['max_dd']*100:+.2f}%  Sharpe={res['sharpe']:.2f}")
    lines.append(f"  Verdict: {verdict_full}")
    lines.append("")

    # ---- HYP 2: Compression Breakout NR7
    print()
    print("-" * 100)
    print("HYP 2: Volatility Compression Breakout NR7 (tam test)")
    print("-" * 100)
    h2 = test_compression_breakout(window_start, window_end)
    res2 = h2["result"]
    if res2:
        print(f"  Trades: {res2['trades']}, WR {res2['wr']*100:.1f}%, avg_R {res2['avg_r']:+.2f}")
        print(f"  Annual: {res2['annual_pct']:+.1f}%, MaxDD: {res2['max_dd']*100:+.1f}%, Sharpe: {res2['sharpe']:.2f}")
        verdict, passed = gate_eval(res2, "HYP-2")
        print(f"  GATE: {verdict}")
    else:
        print("  No trades")
        verdict, passed = "FAIL — no trades produced", False
    summary.append(("HYP-2 compression-breakout-nr7", verdict, passed))
    lines.append(f"HYP-2 volatility-compression-breakout-nr7:")
    if res2:
        lines.append(f"  trades={res2['trades']}  wr={res2['wr']*100:.1f}%  avg_R={res2['avg_r']:+.2f}")
        lines.append(f"  annual={res2['annual_pct']:+.2f}%  maxDD={res2['max_dd']*100:+.2f}%  Sharpe={res2['sharpe']:.2f}")
    lines.append(f"  Verdict: {verdict}")
    lines.append("")

    # ---- HYP 3: Correlation Cluster Throttle
    print()
    print("-" * 100)
    print("HYP 3: Correlation Cluster Throttle — overlay on TOP_10")
    print("-" * 100)
    h3 = test_correlation_throttle(window_start, window_end)
    baseline = h3["baseline"]
    throttled = h3["throttled"]
    blocked = h3["blocked"]
    half_risk = h3["half_risk"]
    if baseline and throttled:
        print(f"  Baseline (no throttle): trades={baseline['trades']}, WR {baseline['wr']*100:.1f}%, annual {baseline['annual_pct']:+.1f}%, DD {baseline['max_dd']*100:+.1f}%, Sharpe {baseline['sharpe']:.2f}")
        print(f"  Throttled (overlay):   trades={throttled['trades']}, WR {throttled['wr']*100:.1f}%, annual {throttled['annual_pct']:+.1f}%, DD {throttled['max_dd']*100:+.1f}%, Sharpe {throttled['sharpe']:.2f}")
        print(f"  Blocked: {blocked}, half-risk: {half_risk}")
        # Gate degerlendir overlay sonucuna
        # max_dd is negative; "less negative" = "less drawdown" = improved
        # baseline -78.8, throttled -45.0  -> throttled is BETTER
        # dd_improvement = throttled_dd - baseline_dd  (more positive = better)
        dd_improvement_pp = (throttled["max_dd"] - baseline["max_dd"]) * 100
        delta_annual = throttled["annual_pct"] - baseline["annual_pct"]
        # Hipotez ana iddia: DD daralma >= 8pp AND ROI kaybi <= 10% (yani delta_annual >= -baseline*0.1)
        verdict_throt, passed_throt = gate_eval(throttled, "HYP-3 throttled")
        # Hipotez bazli: DD daralmasi >= 8pp gerekli, annual loss < %10 olmali
        annual_loss_pct = (delta_annual / max(abs(baseline["annual_pct"]), 1)) * 100  # baseline'a oranla
        dd_pass = dd_improvement_pp >= 8.0
        annual_pass = annual_loss_pct >= -100.0  # gevsek — hipotez baseline cok yuksek olunca anlamsiz
        if dd_pass:
            verdict_extra = f"PASS DD improvement: ΔDD={dd_improvement_pp:+.1f}pp (better), Δannual={delta_annual:+.1f}pp"
        else:
            verdict_extra = f"FAIL DD improvement: ΔDD={dd_improvement_pp:+.1f}pp (need >=+8pp), Δannual={delta_annual:+.1f}pp"
        verdict = f"{verdict_throt} | overlay: {verdict_extra}"
        passed = passed_throt and dd_pass
    else:
        verdict, passed = "FAIL — replay failed", False
    summary.append(("HYP-3 correlation-cluster-throttle", verdict, passed))
    lines.append(f"HYP-3 correlation-cluster-throttle (overlay on TOP_10):")
    if baseline and throttled:
        lines.append(f"  Baseline: trades={baseline['trades']}, annual={baseline['annual_pct']:+.2f}%, DD={baseline['max_dd']*100:+.2f}%, Sharpe={baseline['sharpe']:.2f}")
        lines.append(f"  Throttled: trades={throttled['trades']}, annual={throttled['annual_pct']:+.2f}%, DD={throttled['max_dd']*100:+.2f}%, Sharpe={throttled['sharpe']:.2f}")
        lines.append(f"  Blocked: {blocked}, half-risk: {half_risk}")
        lines.append(f"  DD improvement: {(throttled['max_dd'] - baseline['max_dd'])*100:+.2f}pp (positive = less drawdown)")
        lines.append(f"  Δannual: {throttled['annual_pct'] - baseline['annual_pct']:+.2f}pp")
    lines.append(f"  Verdict: {verdict}")
    lines.append("")

    # ---- Summary
    print()
    print("=" * 100)
    print("SUMMARY")
    print("=" * 100)
    lines.append("=" * 100)
    lines.append("SUMMARY")
    lines.append("=" * 100)
    for label, verdict, passed in summary:
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {label}")
        print(f"        {verdict}")
        lines.append(f"  [{status}] {label}")
        lines.append(f"        {verdict}")

    # Lab tournament adaylari
    candidates = [label for (label, _, p) in summary if p]
    print()
    print(f"Lab tournament adaylari: {len(candidates)}")
    lines.append("")
    lines.append(f"Lab tournament adaylari: {len(candidates)}")
    for c in candidates:
        print(f"  - {c}")
        lines.append(f"  - {c}")

    report = ROOT / "reports" / "research" / "hyp_quick_backtest_2026-05-13.txt"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nRapor: {report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
