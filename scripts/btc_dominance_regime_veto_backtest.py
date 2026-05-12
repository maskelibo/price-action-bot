"""BTC Dominance regime veto overlay backtest — Researcher Sprint 2026-05-14.

Pre-registered: memory/researcher/hypotheses/2026-05-12-regime-btc-dominance-trend-veto.md

Problem: CoinGecko free tier sadece son 90 gun BTC.D verir. 5y backtest
icin **sentetik BTC.D** turetiyoruz: 11 sembol pool'undan BTC mcap orani
proxy (BTC close x dolasimda ~19.4M arz / sum_11_sym(close x supply)).

Causal: her bar i icin son 30 bar slope hesaplanir, t-1 cutoff. Trade i
icin t-1 close'tan onceki 30 bar slope kullanilir.

Overlay:
  - BTC_DOMINANT (slope > +0.03%/day): alt-long SKIP, alt-short PASS
  - ALT_ROTATION (slope < -0.03%/day): alt-long PASS, alt-short half-risk
  - NEUTRAL: default

Output:
  - Baseline BALANCED (mevcut yillik): Top 10 + 11 sym trade pool, flat 3% risk
  - With overlay: ayni pool + BTC.D veto
  - Gate: yillik > +5pp VEYA DD > +3pp improvement
"""
from __future__ import annotations

import sys
import time
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

import logging
logging.getLogger("price_action").setLevel(logging.WARNING)
import os
os.environ["LOG_LEVEL"] = "WARNING"

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

import duckdb


SYMBOLS_11 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
              "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
              "DOGE/USDT", "XRP/USDT", "MATIC/USDT"]

# Approx max supply for proxy mcap calculation (NOT precise; for ratio only)
APPROX_SUPPLY = {
    "BTC/USDT": 19_700_000,
    "ETH/USDT": 120_000_000,
    "SOL/USDT": 470_000_000,
    "BNB/USDT": 145_000_000,
    "ADA/USDT": 36_000_000_000,
    "AVAX/USDT": 420_000_000,
    "LINK/USDT": 640_000_000,
    "DOT/USDT": 1_500_000_000,
    "DOGE/USDT": 145_000_000_000,
    "XRP/USDT": 56_000_000_000,
    "MATIC/USDT": 9_700_000_000,
}


def _load_ohlcv_duckdb(symbol: str, tf: str = "1d") -> pd.DataFrame:
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
    return df


def build_synthetic_btcd() -> pd.DataFrame:
    """11 sembol pool'undan sentetik BTC.D — BTC mcap / sum mcap, daily."""
    closes = {}
    for sym in SYMBOLS_11:
        df = _load_ohlcv_duckdb(sym)
        if df.empty:
            continue
        df = df[["ts", "close"]].copy()
        df["mcap"] = df["close"] * APPROX_SUPPLY[sym]
        closes[sym] = df.set_index("ts")["mcap"]

    if "BTC/USDT" not in closes:
        raise RuntimeError("BTC/USDT data yok — sentetik BTC.D mumkun degil")

    # All series, outer-merge on ts
    df_mcap = pd.concat(closes, axis=1).sort_index()
    df_mcap = df_mcap.ffill()
    df_mcap["sum_total"] = df_mcap.sum(axis=1)
    df_mcap["btc_dom"] = df_mcap["BTC/USDT"] / df_mcap["sum_total"] * 100  # %
    return df_mcap[["btc_dom"]].reset_index()


def btcd_regime_lookup(btcd_df: pd.DataFrame, target_ts: pd.Timestamp, lookback: int = 30) -> tuple[str, float]:
    """Causal lookup: son `lookback` bar t-1'e kadar slope."""
    yesterday = target_ts.normalize() - pd.Timedelta(days=1)
    mask = btcd_df["ts"] <= yesterday
    if not mask.any():
        return ("UNKNOWN", 0.0)
    sub = btcd_df.loc[mask].tail(lookback)
    if len(sub) < int(lookback * 0.8):
        return ("UNKNOWN", 0.0)
    x = np.arange(len(sub))
    y = sub["btc_dom"].values
    slope = np.polyfit(x, y, 1)[0]
    slope_pct = slope / np.mean(y) * 100  # % per day
    if slope_pct > 0.03:
        return ("BTC_DOMINANT", slope_pct)
    if slope_pct < -0.03:
        return ("ALT_ROTATION", slope_pct)
    return ("NEUTRAL", slope_pct)


def apply_overlay(trade: dict, state: str) -> tuple[str, float]:
    """Returns (action, risk_multiplier)."""
    is_btc = trade["symbol"] == "BTC/USDT"
    if is_btc:
        return ("PASS", 1.0)
    if state == "BTC_DOMINANT":
        if trade["side"] == "long":
            return ("SKIP", 0.0)
        else:
            return ("PASS", 1.0)
    if state == "ALT_ROTATION":
        if trade["side"] == "long":
            return ("PASS", 1.0)
        else:
            return ("PASS", 0.5)  # half-risk short
    return ("PASS", 1.0)


def replay(trades: list[dict], risk_pct: float = 0.03, leverage: float = 3.0, max_concurrent: int = 8, cooldown_days: int = 3) -> dict:
    """Basit replay — BALANCED preset emulation."""
    if not trades:
        return None
    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0
    cash = 10_000.0
    open_pos = []
    eq_curve = [10_000.0]
    Rs = []
    last_entry = {}

    for t in trades:
        # close due
        still = []
        for p in open_pos:
            if p["exit_ts"] <= t["entry_ts"]:
                pnl = p["risk"] * p["R"]
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                Rs.append(p["R"])
                eq_curve.append(equity)
            else:
                still.append(p)
        open_pos = still

        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).days < cooldown_days:
            continue
        if len(open_pos) >= max_concurrent:
            continue

        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0:
            continue

        risk_d = equity * risk_pct * t.get("risk_mult", 1.0)
        if risk_d <= 0:
            continue
        notional = risk_d / sl_pct
        max_notional = equity * 0.30
        if notional > max_notional:
            notional = max_notional
            risk_d = notional * sl_pct
        margin = notional / leverage
        if margin > cash:
            continue
        cash -= margin
        last_entry[key] = t["entry_ts"]
        open_pos.append({"exit_ts": t["exit_ts"], "margin": margin, "risk": risk_d, "R": t["R"]})

    for p in open_pos:
        cash += p["margin"] + p["risk"] * p["R"]
        equity = cash
        Rs.append(p["R"])
        eq_curve.append(equity)

    if not Rs:
        return None
    final_eq = equity
    peak = eq_curve[0]
    max_dd = 0.0
    for v in eq_curve:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < max_dd: max_dd = dd
    wr = sum(1 for x in Rs if x > 0) / len(Rs)
    return {
        "final": final_eq,
        "trades": len(Rs),
        "wr": wr,
        "avg_r": float(np.mean(Rs)),
        "max_dd": max_dd,
    }


def main():
    t0 = time.time()
    print("=" * 80)
    print("BTC Dominance Regime Veto Overlay Backtest")
    print("=" * 80)
    print(f"Pre-registered: memory/researcher/hypotheses/2026-05-12-regime-btc-dominance-trend-veto.md")
    print(f"NOT: CoinGecko 5y veri yok (free tier limit) — SENTETIK BTC.D kullaniliyor")
    print(f"     (BTC mcap proxy / sum 11 sym mcap proxy)\n")

    # ---- 1. Sentetik BTC.D
    print("[1/3] Sentetik BTC.D inseasi...")
    btcd = build_synthetic_btcd()
    print(f"  BTC.D dagilim: min={btcd['btc_dom'].min():.2f}% med={btcd['btc_dom'].median():.2f}% "
          f"max={btcd['btc_dom'].max():.2f}%")
    print(f"  Tarih araligi: {btcd['ts'].min().date()} -> {btcd['ts'].max().date()} ({len(btcd)} gun)")

    # ---- 2. Top 10 trade pool
    print("\n[2/3] Top 10 strateji trade pool...")
    from scripts.v09_optimize_top10 import _gather, TOP_10
    all_trades = []
    for m, c in TOP_10:
        trs = _gather(m, c)
        all_trades.extend(trs)
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"  Toplam: {len(all_trades)} trade")

    # 3y window
    cutoff = pd.Timestamp("2023-01-01", tz="UTC")
    end_cut = pd.Timestamp("2026-05-13", tz="UTC")
    trades_3y = [t for t in all_trades if cutoff <= t["entry_ts"] < end_cut]
    print(f"  3y window: {len(trades_3y)} trade")

    # ---- 3. Overlay
    print("\n[3/3] BTC.D rejim sayilari + overlay uygulamasi...")
    regime_counts = {"BTC_DOMINANT": 0, "ALT_ROTATION": 0, "NEUTRAL": 0, "UNKNOWN": 0}
    action_counts = {"PASS": 0, "SKIP": 0, "HALF": 0}
    overlay_trades = []
    for t in trades_3y:
        state, slope = btcd_regime_lookup(btcd, t["entry_ts"], lookback=30)
        regime_counts[state] += 1
        action, mult = apply_overlay(t, state)
        if action == "SKIP":
            action_counts["SKIP"] += 1
            continue
        if mult < 1.0:
            action_counts["HALF"] += 1
        else:
            action_counts["PASS"] += 1
        t2 = dict(t)
        t2["risk_mult"] = mult
        t2["btcd_state"] = state
        t2["btcd_slope"] = slope
        overlay_trades.append(t2)

    print(f"  Rejim dagilim: {regime_counts}")
    print(f"  Aksiyon dagilim: {action_counts}")

    # Baseline (no overlay)
    baseline = replay(trades_3y, risk_pct=0.03, leverage=3.0)
    # With overlay
    treated = replay(overlay_trades, risk_pct=0.03, leverage=3.0)

    if baseline is None or treated is None:
        print("HATA: replay null")
        return 1

    b_ret = (baseline["final"] / 10000 - 1) * 100
    t_ret = (treated["final"] / 10000 - 1) * 100
    years = (end_cut - cutoff).total_seconds() / (365.25 * 86400)
    b_annual = ((baseline["final"] / 10000) ** (1 / years) - 1) * 100 if baseline["final"] > 0 else -100
    t_annual = ((treated["final"] / 10000) ** (1 / years) - 1) * 100 if treated["final"] > 0 else -100

    print()
    print("=" * 80)
    print("RESULTS (3y window, 2023-01 → 2026-05)")
    print("=" * 80)
    print(f"  {'Metric':<20} {'Baseline':>15} {'Overlay':>15} {'Delta':>15}")
    print(f"  {'-'*65}")
    print(f"  {'Final $':<20} ${baseline['final']:>13.2f}  ${treated['final']:>13.2f}")
    print(f"  {'Total return %':<20} {b_ret:>14.2f}%  {t_ret:>14.2f}%  {t_ret-b_ret:>+14.2f}pp")
    print(f"  {'Annual % (CAGR)':<20} {b_annual:>14.2f}%  {t_annual:>14.2f}%  {t_annual-b_annual:>+14.2f}pp")
    print(f"  {'Max DD %':<20} {baseline['max_dd']*100:>14.2f}%  {treated['max_dd']*100:>14.2f}%  {(treated['max_dd']-baseline['max_dd'])*100:>+14.2f}pp")
    print(f"  {'Trades':<20} {baseline['trades']:>15}  {treated['trades']:>15}  {treated['trades']-baseline['trades']:>+15}")
    print(f"  {'Win rate %':<20} {baseline['wr']*100:>14.1f}%  {treated['wr']*100:>14.1f}%")
    print(f"  {'Avg R':<20} {baseline['avg_r']:>+14.3f}  {treated['avg_r']:>+14.3f}")

    # Gates
    annual_delta = t_annual - b_annual
    dd_delta = (treated["max_dd"] - baseline["max_dd"]) * 100  # positive = improvement (less negative)
    gate_annual = annual_delta >= 5.0
    gate_dd = dd_delta >= 3.0
    overall = gate_annual or gate_dd
    print()
    print("Pre-registered gate'ler:")
    print(f"  [{'PASS' if gate_annual else 'FAIL'}] Annual delta >= +5pp:  actual={annual_delta:+.2f}pp")
    print(f"  [{'PASS' if gate_dd else 'FAIL'}] DD delta >= +3pp:      actual={dd_delta:+.2f}pp")
    print(f"  OVERALL: {'PASS' if overall else 'FAIL'} (en az biri PASS gerek)")

    print(f"\nElapsed: {time.time() - t0:.1f}s")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
