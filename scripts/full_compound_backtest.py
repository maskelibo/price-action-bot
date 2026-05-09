"""5 filter birden açık compound backtest — $10K → 3y.

Engulfing + Vol-target + F&G + BTC.D + Stablecoin + MVRV (hepsi açık)
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
           "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]


def _load_fng_synthetic(start, end):
    """Synthetic F&G if API unavailable. Realistic 0-100 range."""
    days = pd.date_range(start, end, freq="D", tz="UTC")
    rng = np.random.default_rng(42)
    base = 50 + 25 * np.sin(np.linspace(0, 6 * np.pi, len(days)))
    noise = rng.normal(0, 8, len(days))
    fng = np.clip(base + noise, 5, 95)
    return pd.DataFrame({"ts": days, "fng": fng})


def _load_btcd_synthetic(start, end):
    """Synthetic BTC.D % range 40-65."""
    days = pd.date_range(start, end, freq="D", tz="UTC")
    rng = np.random.default_rng(7)
    base = 50 + 8 * np.sin(np.linspace(0, 4 * np.pi, len(days)))
    noise = rng.normal(0, 1.5, len(days))
    btcd = np.clip(base + noise, 35, 70)
    return pd.DataFrame({"ts": days, "btcd": btcd})


def _load_stable_synthetic(start, end):
    """Stablecoin total mcap (USDT+USDC) — büyüyor genelde."""
    days = pd.date_range(start, end, freq="D", tz="UTC")
    # Linear growth + noise
    n = len(days)
    base = 80e9 + np.linspace(0, 200e9, n)  # 80B → 280B
    rng = np.random.default_rng(13)
    noise = rng.normal(0, 5e9, n)
    stable = base + noise
    # 30-day pct change
    df = pd.DataFrame({"ts": days, "total": stable})
    df["growth_30d"] = df["total"].pct_change(30)
    return df


def _gather_engulfing():
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import (
        EngulfingContinuationStrategy, _default_manifest as engulf_manifest,
    )
    from price_action.signals.filters import rolling_sharpe
    from scripts.run_real_backtest import _load_symbol_ohlcv

    manifest = engulf_manifest()
    out = []
    for sym in SYMBOLS:
        df = _load_symbol_ohlcv(sym, tf="1d")
        df = df.sort_values("ts").reset_index(drop=True)
        s = EngulfingContinuationStrategy(manifest)
        df_feats = s.prepare_features(df)
        df_feats["rolling_sharpe_60"] = rolling_sharpe(df_feats["close"], period=60)
        df_feats["body_ratio"] = (df_feats["close"] - df_feats["open"]).abs() / (df_feats["high"] - df_feats["low"]).replace(0, np.nan)
        ts_map = pd.to_datetime(df_feats["ts"], utc=True)
        def prov(*a, **k): return df_feats.copy()
        e = BacktestEngine(risk_officer=None, store_load=None)
        r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(), end=df["ts"].iloc[-1].to_pydatetime(), timeframe="1d", initial_capital=10_000.0, fees={"taker":0.00075,"maker":-0.00010}, slippage_bps=5.0, ohlcv_provider=prov)
        for _, t in r.trades.iterrows():
            ts = pd.Timestamp(t["entry_ts"])
            if ts.tzinfo is None: ts = ts.tz_localize("UTC")
            mask = ts_map < ts
            if not mask.any(): continue
            idx = ts_map[mask].index[-1]
            er = float(df_feats["kaufman_er"].iloc[idx]) if "kaufman_er" in df_feats else 0
            atr_pct = float(df_feats["atr_pct"].iloc[idx]) if "atr_pct" in df_feats else 0.05
            rs60 = float(df_feats["rolling_sharpe_60"].iloc[idx])
            body = float(df_feats["body_ratio"].iloc[idx])
            if np.isnan(rs60): rs60 = 0
            if np.isnan(body): body = 0
            if np.isnan(atr_pct): atr_pct = 0.05
            cn = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
            en = max(0.0, min(1.0, er))
            rn = max(0.0, min(1.0, (rs60 + 1.0) / 2.0))
            bn = max(0.0, min(1.0, body))
            conf = 0.35 * cn + 0.25 * en + 0.25 * rn + 0.15 * bn
            if conf < 0.32: lev = 1.0
            elif conf < 0.42: lev = 2.0
            elif conf < 0.52: lev = 3.0
            elif conf < 0.58: lev = 4.0
            else: lev = 5.0
            out.append({
                "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
                "entry_price": float(t["entry_price"]), "initial_sl": float(t["initial_sl"]),
                "R": float(t["realized_r_multiple"]), "symbol": sym,
                "conf": conf, "lev": lev, "atr_pct": atr_pct,
                "side": str(t["side"]),
            })
    out.sort(key=lambda x: x["entry_ts"])
    return out


def apply_fng_filter(trades, fng_df, long_max=60, short_min=40):
    """F&G filter."""
    fng_lookup = {}
    for _, row in fng_df.iterrows():
        d = pd.Timestamp(row["ts"]).tz_convert("UTC").date()
        fng_lookup[d] = row["fng"]
    out = []
    for t in trades:
        # shift(1) — yesterday's F&G
        d = (pd.Timestamp(t["entry_ts"]) - timedelta(days=1)).date()
        fng = fng_lookup.get(d, 50)
        if t["side"] == "long" and fng > long_max:
            continue
        if t["side"] == "short" and fng < short_min:
            continue
        out.append(t)
    return out


def apply_btcd_filter(trades, btcd_df, lookback=30):
    """BTC.D trend filter — alt long sadece BTC.D düşüyorsa."""
    btcd_df = btcd_df.copy()
    btcd_df["ts_d"] = pd.to_datetime(btcd_df["ts"]).dt.tz_convert("UTC").dt.date
    btcd_df["btcd_lag"] = btcd_df["btcd"].shift(1)
    btcd_df["btcd_ma"] = btcd_df["btcd_lag"].rolling(lookback).mean()
    btcd_df["btcd_slope"] = btcd_df["btcd_lag"] - btcd_df["btcd_ma"]
    lookup = dict(zip(btcd_df["ts_d"], btcd_df["btcd_slope"]))
    out = []
    for t in trades:
        if t["symbol"].startswith("BTC"):
            out.append(t)  # BTC bypass filter
            continue
        d = pd.Timestamp(t["entry_ts"]).date()
        slope = lookup.get(d, 0.0)
        if pd.isna(slope): slope = 0.0
        if t["side"] == "long" and slope > 0:
            continue  # BTC.D yükseliyor, alt long suppress
        if t["side"] == "short" and slope < 0:
            continue
        out.append(t)
    return out


def apply_stable_filter(trades, stable_df):
    """Stablecoin growth filter — long sadece growth > 0."""
    stable_df = stable_df.copy()
    stable_df["ts_d"] = pd.to_datetime(stable_df["ts"]).dt.tz_convert("UTC").dt.date
    stable_df["growth_lag"] = stable_df["growth_30d"].shift(1)
    lookup = dict(zip(stable_df["ts_d"], stable_df["growth_lag"]))
    out = []
    for t in trades:
        d = pd.Timestamp(t["entry_ts"]).date()
        g = lookup.get(d, 0.0)
        if pd.isna(g): g = 0.0
        if t["side"] == "long" and g < 0:
            continue
        if t["side"] == "short" and g > 0:
            continue
        out.append(t)
    return out


def apply_vol_target(trades, target_atr=0.04, min_factor=0.20, max_factor=1.50):
    """Vol-target sizing — risk_pct'i atr'a göre ölçeklendir."""
    out = []
    for t in trades:
        cur_atr = t["atr_pct"]
        if cur_atr > 0:
            factor = max(min_factor, min(max_factor, target_atr / cur_atr))
        else:
            factor = 1.0
        new_t = dict(t)
        new_t["risk_factor"] = factor
        out.append(new_t)
    return out


def replay(trades, daily_dd=0.05, weekly_dd=0.10, monthly_dd=0.15,
           fund_annual=0.10, max_concurrent=5, base_risk_pct=0.02):
    if not trades:
        return None
    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0
    cash = 10_000.0
    open_pos = []
    eq_curve = [10_000.0]
    Rs = []
    fund_d = fund_annual / 365

    daily_anchor = weekly_anchor = monthly_anchor = 10_000.0
    last_d = trades[0]["entry_ts"].date()
    last_w = trades[0]["entry_ts"].isocalendar()[1]
    last_m = trades[0]["entry_ts"].month
    blocked_until = None

    def close_due(now):
        nonlocal cash, equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
                f = p["margin"] * p["lev"] * fund_d * holding
                pnl = p["risk"] * p["R"] - f
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                Rs.append(p["R"])
                eq_curve.append(equity)
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])
        cd = t["entry_ts"].date()
        cw = t["entry_ts"].isocalendar()[1]
        cm = t["entry_ts"].month
        if cd != last_d: daily_anchor = equity; last_d = cd
        if cw != last_w: weekly_anchor = equity; last_w = cw
        if cm != last_m: monthly_anchor = equity; last_m = cm
        if blocked_until and t["entry_ts"] < blocked_until: continue
        if (daily_anchor - equity) / max(daily_anchor, 1) >= daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=1); continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=7); continue
        if (monthly_anchor - equity) / max(monthly_anchor, 1) >= monthly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=30); continue
        if len(open_pos) >= max_concurrent: continue

        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0: continue
        risk_factor = t.get("risk_factor", 1.0)
        risk_d = equity * base_risk_pct * risk_factor
        notional = risk_d / sl_pct
        margin = notional / t["lev"]
        if margin > cash: continue
        cash -= margin
        open_pos.append({
            "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
            "margin": margin, "risk": risk_d, "R": t["R"], "lev": t["lev"],
        })

    for p in open_pos:
        holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
        f = p["margin"] * p["lev"] * fund_d * holding
        cash += p["margin"] + p["risk"] * p["R"] - f
        equity = cash
        Rs.append(p["R"])
        eq_curve.append(equity)

    peak = eq_curve[0]
    max_dd = 0
    for v in eq_curve:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < max_dd: max_dd = dd
    win = sum(1 for x in Rs if x > 0) / len(Rs) if Rs else 0
    return {"final": equity, "max_dd": max_dd, "trades": len(Rs), "win": win}


def yearly_compound(trades, **replay_kwargs):
    start = trades[0]["entry_ts"]
    eq = 10_000.0
    yearly = []
    worst_dd = 0.0
    total_trades = 0
    for yr in range(3):
        ws = start + timedelta(days=365 * yr)
        we = start + timedelta(days=365 * (yr + 1))
        wt = [t for t in trades if ws <= t["entry_ts"] < we]
        r = replay(wt, **replay_kwargs)
        if r is None:
            yearly.append(0); continue
        yearly.append(r["final"] / 10_000 - 1)
        eq *= (1 + yearly[-1])
        if r["max_dd"] < worst_dd: worst_dd = r["max_dd"]
        total_trades += r["trades"]
    annual = ((eq / 10_000) ** (1/3) - 1) * 100
    return eq, annual, worst_dd * 100, yearly, total_trades


def main():
    print("=== TÜM FILTRELER AÇIK COMPOUND BACKTEST ===\n")
    print("Trade'leri topluyor...")
    trades = _gather_engulfing()
    print(f"Toplam {len(trades)} engulfing sinyali\n")

    if not trades:
        return

    start = trades[0]["entry_ts"] - timedelta(days=60)
    end = trades[-1]["exit_ts"] + timedelta(days=10)

    fng = _load_fng_synthetic(start, end)
    btcd = _load_btcd_synthetic(start, end)
    stable = _load_stable_synthetic(start, end)

    scenarios = [
        ("0. SOLO Engulfing (baseline)", trades),
        ("1. + Vol-target (sakin/riskli sizing)",
         apply_vol_target(trades)),
        ("2. + F&G filter",
         apply_fng_filter(trades, fng)),
        ("3. + BTC.D filter",
         apply_btcd_filter(apply_fng_filter(trades, fng), btcd)),
        ("4. + Stablecoin filter",
         apply_stable_filter(apply_btcd_filter(apply_fng_filter(trades, fng), btcd), stable)),
        ("5. HEPSİ AÇIK (Vol+F&G+BTC.D+Stable)",
         apply_vol_target(
             apply_stable_filter(
                 apply_btcd_filter(
                     apply_fng_filter(trades, fng),
                     btcd
                 ),
                 stable
             )
         )),
    ]

    print(f"{'Senaryo':<48} {'sinyal':>6} {'final$':>10} {'yıllık':>9} {'maxDD':>7} {'win%':>6}")
    print("-" * 100)

    for label, ts in scenarios:
        if not ts:
            continue
        eq, ann, dd, yr_rets, n_tr = yearly_compound(ts)
        win = "—"
        # Win rate from replay
        cells = " ".join(f"{r*100:>+5.1f}%" for r in yr_rets)
        print(f"{label:<48} {len(ts):>6} {eq:>10,.0f} {ann:>+8.2f}% {dd:>+5.1f}%   ({cells})")

    print()
    print("Açıklama:")
    print("  'sinyal'  — filtreden geçen toplam trade sayısı (3y)")
    print("  'final$'  — $10K compound 3y sonrası")
    print("  'yıllık'  — 3y compound annualized")
    print("  'maxDD'   — yıl-içi en kötü düşüş")
    print("  Sağdaki paranthez: Yıl1 / Yıl2 / Yıl3 getirileri")
    print()
    print("NOT: BTC.D + Stable synthetic data (real CoinGecko Pro/paid gerek)")
    print("     F&G synthetic (real API çalışıyor ama 4y free, 3y altı)")
    print("     Numbers indicative — paper trading'de gerçek verilerle tekrar ölçülecek")


if __name__ == "__main__":
    main()
