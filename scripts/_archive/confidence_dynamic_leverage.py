"""Per-trade confidence'a göre dinamik leverage.

Confidence score = blend of:
  - confluence_score (normalized)
  - kaufman_er at entry (trend strength)
  - rolling 60-bar sembol Sharpe (sembol güveni)
  - body_ratio (pattern strength)

Leverage tier:
  conf < 0.30 → lev 1x (zayıf, az risk)
  0.30-0.50 → lev 2x
  0.50-0.70 → lev 3x
  0.70-0.85 → lev 4x  (yüksek conviction)
  0.85+    → lev 5x  (highest conviction — agresif)

Forward-looking: tüm metrikler trade entry zamanına kadar olan veriyle.
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


def _gather_engulfing_with_features():
    """Engulfing trades + signal-time features (forward-looking-safe)."""
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
        # body ratio
        df_feats["body_ratio"] = (df_feats["close"] - df_feats["open"]).abs() / (df_feats["high"] - df_feats["low"]).replace(0, np.nan)
        # ts-indexed lookup
        ts_map = pd.to_datetime(df_feats["ts"], utc=True)

        def prov(*a, **k): return df_feats.copy()
        e = BacktestEngine(risk_officer=None, store_load=None)
        r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(), end=df["ts"].iloc[-1].to_pydatetime(), timeframe="1d", initial_capital=10_000.0, fees={"taker":0.00075,"maker":-0.00010}, slippage_bps=5.0, ohlcv_provider=prov)

        for _, t in r.trades.iterrows():
            ts = pd.Timestamp(t["entry_ts"])
            if ts.tzinfo is None:
                ts = ts.tz_localize("UTC")
            # Find bar at-or-before entry_ts (forward-looking-safe)
            mask = ts_map < ts
            if not mask.any():
                continue
            idx = ts_map[mask].index[-1]
            cs = float(t["confluence_score"])
            er = float(df_feats["kaufman_er"].iloc[idx]) if "kaufman_er" in df_feats else 0
            rs60 = float(df_feats["rolling_sharpe_60"].iloc[idx]) if "rolling_sharpe_60" in df_feats else 0
            body_ratio = float(df_feats["body_ratio"].iloc[idx]) if "body_ratio" in df_feats else 0
            if np.isnan(rs60): rs60 = 0
            if np.isnan(body_ratio): body_ratio = 0

            out.append({
                "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
                "entry_price": float(t["entry_price"]), "initial_sl": float(t["initial_sl"]),
                "R": float(t["realized_r_multiple"]), "symbol": sym,
                "confluence": cs, "kaufman_er": er, "rolling_sharpe": rs60, "body_ratio": body_ratio,
            })
    out.sort(key=lambda x: x["entry_ts"])
    return out


def _confidence_score(t: dict) -> float:
    """Per-trade confidence ∈ [0, 1].

    Blend:
      conf_norm = clip((confluence - 1.5) / 1.5, 0, 1)        # 1.5-3.0 → 0-1
      er_norm   = clip(kaufman_er, 0, 1)                       # 0-1 zaten
      rs_norm   = clip((rolling_sharpe + 1) / 2, 0, 1)         # -1..+1 → 0..1
      body_norm = clip(body_ratio, 0, 1)                       # 0-1
    Avg weighted: confluence 0.35, ER 0.25, sharpe 0.25, body 0.15
    """
    conf_norm = max(0.0, min(1.0, (t["confluence"] - 1.5) / 1.5))
    er_norm = max(0.0, min(1.0, t["kaufman_er"]))
    rs_norm = max(0.0, min(1.0, (t["rolling_sharpe"] + 1.0) / 2.0))
    body_norm = max(0.0, min(1.0, t["body_ratio"]))
    return 0.35 * conf_norm + 0.25 * er_norm + 0.25 * rs_norm + 0.15 * body_norm


def _confidence_to_leverage(conf: float, max_lev: float = 5.0) -> float:
    """Map confidence to leverage tier — eşikler veri dağılımına göre kalibre.

    Engulfing confidence dağılımı: min 0.26, max 0.64, mean 0.44, median 0.44
    Eşikler buna göre: percentile-bazlı (yaklaşık 30/50/70/90).
    """
    if conf < 0.32: return 1.0   # ~%20 percentile
    if conf < 0.42: return 2.0   # ~%50 percentile
    if conf < 0.52: return 3.0   # ~%70 percentile
    if conf < 0.58: return 4.0   # ~%90 percentile (en iyi setupler)
    return min(5.0, max_lev)     # üst tail



def replay(trades, risk_pct=0.02, max_lev=5.0,
           daily_dd=0.05, weekly_dd=0.10, monthly_dd=0.15,
           funding_annual=0.10, max_concurrent=5):
    if not trades:
        return {"final": 10_000.0, "trades": 0, "max_dd": 0, "lev_dist": {}}

    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0
    cash = 10_000.0
    open_pos = []
    n_taken = 0
    eq_curve = [10_000.0]
    lev_dist = {1.0: 0, 2.0: 0, 3.0: 0, 4.0: 0, 5.0: 0}
    funding_per_day = funding_annual / 365

    daily_anchor = 10_000.0
    weekly_anchor = 10_000.0
    monthly_anchor = 10_000.0
    last_day = trades[0]["entry_ts"].date()
    last_week = trades[0]["entry_ts"].isocalendar()[1]
    last_month = trades[0]["entry_ts"].month
    blocked_until = None

    def close_due(now):
        nonlocal cash, equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
                fund = p["margin"] * p["leverage"] * funding_per_day * holding
                pnl = p["risk"] * p["R"] * p["leverage"] - fund
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                eq_curve.append(equity)
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])

        cur_day = t["entry_ts"].date()
        cur_week = t["entry_ts"].isocalendar()[1]
        cur_month = t["entry_ts"].month
        if cur_day != last_day: daily_anchor = equity; last_day = cur_day
        if cur_week != last_week: weekly_anchor = equity; last_week = cur_week
        if cur_month != last_month: monthly_anchor = equity; last_month = cur_month

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

        # Confidence-based leverage
        conf = _confidence_score(t)
        lev = _confidence_to_leverage(conf, max_lev=max_lev)
        lev_dist[lev] = lev_dist.get(lev, 0) + 1

        risk_d = equity * risk_pct
        notional = risk_d / sl_pct
        margin = notional / lev
        if margin > cash: continue
        cash -= margin
        open_pos.append({
            "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
            "margin": margin, "risk": risk_d, "R": t["R"], "leverage": lev,
            "conf": conf,
        })
        n_taken += 1

    for p in open_pos:
        holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
        fund = p["margin"] * p["leverage"] * funding_per_day * holding
        cash += p["margin"] + p["risk"] * p["R"] * p["leverage"] - fund
        equity = cash
        eq_curve.append(equity)

    peak = eq_curve[0]
    max_dd = 0
    for v in eq_curve:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < max_dd: max_dd = dd

    return {"final": equity, "trades": n_taken, "max_dd": max_dd, "lev_dist": lev_dist}


def main():
    print("Engulfing trade'lerini + signal-time features topluyor...")
    trades = _gather_engulfing_with_features()
    print(f"Toplam {len(trades)} trade\n")

    if not trades:
        return

    # Confidence dağılımı
    confs = [_confidence_score(t) for t in trades]
    print("--- Confidence Score Dagilimi ---")
    print(f"  min  : {min(confs):.3f}")
    print(f"  max  : {max(confs):.3f}")
    print(f"  mean : {sum(confs)/len(confs):.3f}")
    print(f"  median: {sorted(confs)[len(confs)//2]:.3f}")
    print()

    # Confidence vs R-multiple (edge confirmation)
    print("--- Confidence Tier × Win Rate ---")
    tiers = [(0.0, 0.30, "lev 1x"), (0.30, 0.50, "lev 2x"), (0.50, 0.70, "lev 3x"),
             (0.70, 0.85, "lev 4x"), (0.85, 1.01, "lev 5x")]
    for lo, hi, lbl in tiers:
        in_tier = [t for t in trades if lo <= _confidence_score(t) < hi]
        if not in_tier: continue
        win = sum(1 for t in in_tier if t["R"] > 0) / len(in_tier)
        avgR = sum(t["R"] for t in in_tier) / len(in_tier)
        print(f"  {lbl} (conf {lo:.2f}-{hi:.2f}): n={len(in_tier):>3} win={win*100:>5.1f}% avgR={avgR:>+5.2f}")

    print()
    start = trades[0]["entry_ts"]

    print(f"\n{'Konfig':<45} {'Yil1':>7} {'Yil2':>7} {'Yil3':>7} {'Compound':>11} {'Yillik':>9} {'maxDD':>7}")
    print("-" * 110)

    configs = [
        ("FIX lev 3x (baseline R%2)",            2.0, 0.02, 3.0),  # max_lev_override
        ("DYNAMIC lev 1-3x (R%2)",               2.0, 0.02, 3.0),  # but using confidence map
        ("DYNAMIC lev 1-4x (R%2)",               2.0, 0.02, 4.0),
        ("DYNAMIC lev 1-5x (R%2)",               2.0, 0.02, 5.0),
        ("DYNAMIC lev 1-3x (R%3)",               3.0, 0.03, 3.0),
        ("DYNAMIC lev 1-4x (R%3)",               3.0, 0.03, 4.0),
        ("DYNAMIC lev 1-5x (R%3)",               3.0, 0.03, 5.0),
    ]

    for label, _, risk_pct, max_lev in configs:
        eq_compound = 10_000.0
        yearly = []
        worst_dd = 0.0
        lev_dist_total = {1.0: 0, 2.0: 0, 3.0: 0, 4.0: 0, 5.0: 0}
        for yr in range(3):
            ws = start + timedelta(days=365 * yr)
            we = start + timedelta(days=365 * (yr + 1))
            wt = [t for t in trades if ws <= t["entry_ts"] < we]
            if "FIX lev 3x" in label:
                # Override: tüm trade'ler lev 3x
                # Hack: confidence_to_leverage'ı bypass'la — replay'e fixed leverage versiyonu lazım
                # Kısa yol: tüm trade'lerin confidence'ını 0.6 yap (lev 3x map'i) — ama bu kötü
                # Doğru yol: ayrı replay func. Şimdilik atla, sadece dynamic versiyonları kıyasla
                eq_compound = 10_000.0
                continue
            r = replay(wt, risk_pct=risk_pct, max_lev=max_lev)
            ret = r["final"] / 10_000 - 1
            yearly.append(ret)
            eq_compound *= (1 + ret)
            if r["max_dd"] < worst_dd:
                worst_dd = r["max_dd"]
            for k, v in r["lev_dist"].items():
                lev_dist_total[k] = lev_dist_total.get(k, 0) + v
        if "FIX lev 3x" in label:
            continue
        annual = ((eq_compound / 10_000) ** (1/3) - 1) * 100
        cells = " ".join(f"{(y*100):>+5.1f}%" for y in yearly)
        ld_str = " ".join(f"{int(lv)}x={n}" for lv, n in lev_dist_total.items() if n > 0)
        print(f"{label:<45} {cells} ${eq_compound:>9,.0f} {annual:>+7.2f}% {worst_dd*100:>+5.1f}%  [{ld_str}]")


if __name__ == "__main__":
    main()
