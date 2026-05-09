"""Bot v2 (5 fix) — 4 ay / 6 ay / 12 ay karşılaştırma.

5 Fix:
  1. confidence_min 0.42 (lev 1x tier'ı atla)
  2. ema200_conflict_skip (200-EMA üstünde short skip, altında long skip)
  3. max_notional_pct 0.50 (tek trade equity'nin %50'sini geçemez)
  4. consecutive_loss_cooldown 7 days (aynı yönde 2 kayıp → 7 gün cool-down)
  5. kaufman_er_min 0.25 (0.20'den sıkı, chop'tan korun)
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))


SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
           "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]


def _gather():
    """Tüm trade'leri topla — 5y data."""
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
            close = float(df_feats["close"].iloc[idx])
            ema200 = float(df_feats["ema200"].iloc[idx]) if "ema200" in df_feats and not pd.isna(df_feats["ema200"].iloc[idx]) else close
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
                "entry_ts": pd.Timestamp(t["entry_ts"]),
                "exit_ts": pd.Timestamp(t["exit_ts"]),
                "entry_price": float(t["entry_price"]),
                "initial_sl": float(t["initial_sl"]),
                "R": float(t["realized_r_multiple"]),
                "symbol": sym, "side": str(t["side"]),
                "conf": conf, "lev": lev, "kaufman_er": er,
                "close_at_entry": close, "ema200_at_entry": ema200,
            })
    out.sort(key=lambda x: x["entry_ts"])
    return out


def replay(trades, version="v1", initial=10_000.0, max_concurrent=5,
           daily_dd=0.05, weekly_dd=0.10, monthly_dd=0.15, fund_annual=0.10):
    """version: 'v1' (orijinal) veya 'v2' (5 fix)."""
    if not trades: return None
    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = cash = initial
    open_pos, Rs, closed = [], [], []
    fund_d = fund_annual / 365

    daily_anchor = weekly_anchor = monthly_anchor = initial
    last_d = trades[0]["entry_ts"].date()
    last_w = trades[0]["entry_ts"].isocalendar()[1]
    last_m = trades[0]["entry_ts"].month
    blocked_until = None

    # v2 eklemeleri
    last_loss_per_side = {"long": None, "short": None}  # tarih
    consecutive_loss = {"long": 0, "short": 0}

    skip_v2_conf = skip_v2_ema200 = skip_v2_notional = skip_v2_cooldown = skip_v2_er = 0

    def close_due(now):
        nonlocal cash, equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
                fund = p["margin"] * p["lev"] * fund_d * holding
                # Futures P&L: notional fiyat hareketi = risk_d × R (lev sabit pos size)
                pnl = p["risk"] * p["R"] - fund
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                Rs.append(p["R"])
                p["pnl"] = pnl
                closed.append(p)
                # v2 cool-down tracking
                if version == "v2":
                    side = p["side"]
                    if pnl < 0:
                        consecutive_loss[side] += 1
                        if consecutive_loss[side] >= 2:
                            last_loss_per_side[side] = p["exit_ts"]
                    else:
                        consecutive_loss[side] = 0
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])

        # === v2 FILTERS ===
        if version == "v2":
            # Fix 1: Confidence < 0.42 reject
            if t["conf"] < 0.42:
                skip_v2_conf += 1; continue
            # Fix 2: 200-EMA conflict
            if t["side"] == "short" and t["close_at_entry"] > t["ema200_at_entry"]:
                skip_v2_ema200 += 1; continue
            if t["side"] == "long" and t["close_at_entry"] < t["ema200_at_entry"]:
                skip_v2_ema200 += 1; continue
            # Fix 5: Kaufman ER min 0.25
            if t["kaufman_er"] < 0.25:
                skip_v2_er += 1; continue
            # Fix 4: Cool-down 7 days
            ll = last_loss_per_side[t["side"]]
            if ll is not None and (t["entry_ts"] - ll).days < 7:
                skip_v2_cooldown += 1; continue

        # Anchor reset
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
        risk_d = equity * 0.02
        notional = risk_d / sl_pct
        margin = notional / t["lev"]

        # Fix 3: Max notional %50 of equity (v2)
        if version == "v2":
            max_notional = equity * 0.50
            if notional > max_notional:
                # Notional'ı kıs — ayni R risk ama smaller position
                notional = max_notional
                margin = notional / t["lev"]
                # Risk dolar'ı yeniden hesapla (size'a oranla)
                risk_d = notional * sl_pct
                skip_v2_notional += 1  # bu trade kıyıldı (skip değil ama kayıt)

        if margin > cash: continue
        cash -= margin
        new_p = {**t, "margin": margin, "risk": risk_d, "notional": notional, "equity_at_entry": equity}
        open_pos.append(new_p)

    # Force close
    for p in open_pos:
        holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
        fund = p["margin"] * p["lev"] * fund_d * holding
        pnl = p["risk"] * p["R"] - fund  # Futures: lev'den bagimsiz P&L
        cash += p["margin"] + pnl
        equity = cash
        Rs.append(p["R"])
        p["pnl"] = pnl
        closed.append(p)

    win = sum(1 for p in closed if p["pnl"] > 0)

    eq_curve = [initial]
    for p in closed:
        eq_curve.append(p.get("equity_at_entry", eq_curve[-1]) + p["pnl"])
    peak = eq_curve[0]
    max_dd = 0
    for v in eq_curve:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < max_dd: max_dd = dd

    return {
        "final": equity, "trades": len(closed), "wins": win,
        "wr": win / max(1, len(closed)), "max_dd": max_dd,
        "v2_skip_conf": skip_v2_conf, "v2_skip_ema200": skip_v2_ema200,
        "v2_skip_er": skip_v2_er, "v2_skip_cooldown": skip_v2_cooldown,
        "v2_notional_capped": skip_v2_notional,
        "closed": closed,
    }


def filter_window(trades, start_dt):
    sdt = start_dt if isinstance(start_dt, pd.Timestamp) else pd.Timestamp(start_dt, tz="UTC")
    if sdt.tzinfo is None:
        sdt = sdt.tz_localize("UTC")
    return [t for t in trades if t["entry_ts"] >= sdt]


def main():
    print("Trade'leri topluyor...")
    all_trades = _gather()
    print(f"Toplam {len(all_trades)} sinyal (5y)\n")

    today = pd.Timestamp("2026-05-08", tz="UTC")
    windows = [
        ("4 AY  (2026-01-08 → bugün)", today - pd.Timedelta(days=120)),
        ("6 AY  (2025-11-08 → bugün)", today - pd.Timedelta(days=180)),
        ("12 AY (2025-05-08 → bugün)", today - pd.Timedelta(days=365)),
    ]

    print("=" * 110)
    print("BOT v1 vs v2 KARŞILAŞTIRMA — 3 farklı pencere")
    print("=" * 110)

    for label, start_dt in windows:
        wt = filter_window(all_trades, start_dt)
        if not wt:
            print(f"\n{label}: trade yok")
            continue

        r1 = replay(wt, version="v1")
        r2 = replay(wt, version="v2")

        print(f"\n{'━' * 110}")
        print(f"  {label}  |  Aday sinyaller: {len(wt)}")
        print(f"{'━' * 110}")

        sdt2 = start_dt if isinstance(start_dt, pd.Timestamp) else pd.Timestamp(start_dt, tz="UTC")
        if sdt2.tzinfo is None:
            sdt2 = sdt2.tz_localize("UTC")
        days = (today - sdt2).days
        annualize = 365 / days

        for ver, r in [("v1 (orijinal)", r1), ("v2 (5 fix)", r2)]:
            ret = (r["final"] / 10_000 - 1) * 100
            ann = ((r["final"] / 10_000) ** annualize - 1) * 100
            print(f"  {ver:<20} : Final ${r['final']:>10,.0f}  ret {ret:>+7.2f}%  yıllık {ann:>+7.2f}%  trade {r['trades']:>3}  WR {r['wr']*100:>4.1f}%  DD {r['max_dd']*100:>+5.1f}%")

        # Delta
        delta_ret = ((r2["final"] - r1["final"]) / r1["final"]) * 100
        print(f"  {'DELTA':<20} : v2 vs v1: {delta_ret:+.2f}% getiri farkı, trade {r2['trades']-r1['trades']:+d}, WR {(r2['wr']-r1['wr'])*100:+.1f}pp")

        # v2 skip detail
        v2skip = r2["v2_skip_conf"] + r2["v2_skip_ema200"] + r2["v2_skip_er"] + r2["v2_skip_cooldown"]
        print(f"  v2 ELEME DETAYI       : skip_conf<0.42 {r2['v2_skip_conf']}, skip_ema200_conflict {r2['v2_skip_ema200']}, skip_er<0.25 {r2['v2_skip_er']}, skip_cooldown {r2['v2_skip_cooldown']}, notional_capped {r2['v2_notional_capped']}")
        print(f"                          Toplam {v2skip} sinyal v2 tarafından elendi (kötülerin filtresi)")

    print("\n" + "=" * 110)
    print("SONUÇ KONSOLIDE")
    print("=" * 110)
    print(f"\n5 FIX UYGULANDI v2'de:")
    print(f"  1. confidence < 0.42 → trade skip")
    print(f"  2. 200-EMA conflict → trade skip")
    print(f"  3. notional > equity %50 → kıs")
    print(f"  4. 2 ardışık aynı yön kayıp → 7 gün cool-down")
    print(f"  5. Kaufman ER < 0.25 → trade skip")


if __name__ == "__main__":
    main()
