"""3 'akıllı kayıp koruma' tekniği — DD düşürme kaybetmeden.

Test edilen:
1. BASELINE — mevcut sistem (R%1)
2. VOL-HEDEFLİ — günlük volatiliteye göre pozisyon boyutu
3. EQUITY STOP-OUT — %20 kayıpta tüm ay durur
4. PARTIAL CLOSE — 1R'da yarı kapat, kalanı trail
5. HEPSİ KOMBİ — üçü birden
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


def _gather():
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
            atr_pct = float(df_feats["atr_pct"].iloc[idx]) if "atr_pct" in df_feats else 0
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
            })
    out.sort(key=lambda x: x["entry_ts"])
    return out


def replay(trades, risk_pct=0.01, max_concurrent=5,
           use_vol_target=False, vol_target_atr=0.04,
           use_equity_stopout=False, stopout_pct=0.20,
           use_partial_close=False,
           daily_dd=0.05, weekly_dd=0.10, monthly_dd=0.15,
           fund_annual=0.10):
    """3 akıllı kayıp koruma tekniği konfigüre edilebilir replay."""
    if not trades:
        return None
    trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = 10_000.0
    cash = 10_000.0
    peak_equity = 10_000.0
    open_pos = []
    eq_curve = [10_000.0]
    fund_d = fund_annual / 365

    daily_anchor = weekly_anchor = monthly_anchor = 10_000.0
    last_d = trades[0]["entry_ts"].date()
    last_w = trades[0]["entry_ts"].isocalendar()[1]
    last_m = trades[0]["entry_ts"].month
    blocked_until = None
    month_stopped_out = None  # (year, month) — bu ay halt

    def close_due(now):
        nonlocal cash, equity, peak_equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
                f = p["margin"] * p["lev"] * fund_d * holding
                # Partial close at 1R: yarı kapat, kalan TP veya SL'de
                if p.get("partial_used"):
                    # Kalan yarı: orijinal R'ın 0.5 katı pnl
                    pnl = p["risk"] * 0.5 * p["R"] * p["lev"] - f * 0.5
                else:
                    pnl = p["risk"] * p["R"] - f
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                if equity > peak_equity:
                    peak_equity = equity
                eq_curve.append(equity)
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])

        # Equity stop-out (technique 2)
        if use_equity_stopout:
            cur_dd = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
            cur_month = (t["entry_ts"].year, t["entry_ts"].month)
            if month_stopped_out and month_stopped_out[0] == cur_month:
                continue  # bu ay halt
            if cur_dd >= stopout_pct:
                month_stopped_out = (cur_month, "halted")
                continue
            # Reset stop-out at new month
            if month_stopped_out and month_stopped_out[0] != cur_month:
                month_stopped_out = None  # yeni ay, tekrar başla
                # Peak equity'yi de aktüalize et
                peak_equity = equity

        # Vol-target sizing (technique 1)
        effective_risk = risk_pct
        if use_vol_target:
            # ATR'i hedefe oranla — ATR > target ise size azalt
            if t["atr_pct"] > 0:
                vol_factor = min(1.0, vol_target_atr / t["atr_pct"])
                effective_risk = risk_pct * vol_factor

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
        risk_d = equity * effective_risk
        notional = risk_d / sl_pct
        margin = notional / t["lev"]
        if margin > cash: continue
        cash -= margin

        # Partial close at 1R simülasyonu
        partial_used = False
        if use_partial_close and t["R"] >= 1.0:
            # Eğer trade 1R'a ulaştıysa yarı kapat
            # %50'sini 1R'da kapat (sabit kar)
            partial_pnl = risk_d * 1.0 * 0.5 * t["lev"]  # yarı pozisyon * 1R
            cash += partial_pnl
            equity = cash + sum(q["margin"] for q in open_pos) + margin
            partial_used = True
            # Kalan yarı orjinal R ile ilerler

        open_pos.append({
            "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
            "margin": margin, "risk": risk_d, "R": t["R"], "lev": t["lev"],
            "partial_used": partial_used,
        })

    for p in open_pos:
        holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
        f = p["margin"] * p["lev"] * fund_d * holding
        if p.get("partial_used"):
            pnl = p["risk"] * 0.5 * p["R"] * p["lev"] - f * 0.5
        else:
            pnl = p["risk"] * p["R"] - f
        cash += p["margin"] + pnl
        equity = cash
        eq_curve.append(equity)

    peak = eq_curve[0]
    max_dd = 0
    for v in eq_curve:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < max_dd: max_dd = dd
    return {"final": equity, "max_dd": max_dd}


def yearly(trades, **kwargs):
    start = trades[0]["entry_ts"]
    rets, dds = [], []
    for yr in range(3):
        ws = start + timedelta(days=365 * yr)
        we = start + timedelta(days=365 * (yr + 1))
        wt = [t for t in trades if ws <= t["entry_ts"] < we]
        r = replay(wt, **kwargs)
        if r is None: continue
        rets.append(r["final"] / 10_000 - 1)
        dds.append(r["max_dd"])
    eq = 10_000.0
    for ret in rets: eq *= (1 + ret)
    annual = ((eq / 10_000) ** (1 / len(rets)) - 1) * 100 if rets else 0
    sigma = (sum((x - sum(rets)/len(rets))**2 for x in rets) / len(rets)) ** 0.5 * 100 if rets else 0
    return {"annual": annual, "compound": eq, "sigma": sigma, "worst_dd": min(dds) * 100, "yearly": rets, "ydds": dds}


def main():
    print("=== AKILLI KAYIP KORUMA TEKNİKLERİ ===\n")
    print("Trade'leri topluyor...")
    trades = _gather()
    print(f"Toplam {len(trades)} trade\n")

    if not trades:
        return

    configs = [
        ("0. BASELINE (R%1, mevcut sistem)", {}),
        ("1. VOL-HEDEFLİ (sakin günde büyük, riskli günde küçük)", {"use_vol_target": True, "vol_target_atr": 0.04}),
        ("2. EQUITY STOP-OUT (%20 kayıpta tüm ay halt)", {"use_equity_stopout": True, "stopout_pct": 0.20}),
        ("3. PARTIAL CLOSE (1R'da yarı kapat)", {"use_partial_close": True}),
        ("4. KOMBI (1+2+3)", {"use_vol_target": True, "use_equity_stopout": True, "use_partial_close": True}),
        ("5. KOMBI sıkı (1+2+3 + stopout %15)", {"use_vol_target": True, "use_equity_stopout": True, "stopout_pct": 0.15, "use_partial_close": True}),
        ("6. KOMBI çok sıkı (1+2+3 + stopout %10)", {"use_vol_target": True, "use_equity_stopout": True, "stopout_pct": 0.10, "use_partial_close": True}),
    ]

    print(f"{'Konfig':<58} {'Yıl1':>7} {'Yıl2':>7} {'Yıl3':>7} {'σ':>6} {'Yıllık':>8} {'maxDD':>7} {'200→1y':>9}")
    print("-" * 120)

    for label, kwargs in configs:
        r = yearly(trades, **kwargs)
        if r["annual"] == 0 and not r["yearly"]: continue
        cells = " ".join(f"{rr*100:>+6.1f}%" for rr in r["yearly"])
        eq_200_1y = 200 * (1 + r["yearly"][0]) if r["yearly"] else 200
        print(f"{label:<58} {cells} {r['sigma']:>5.1f}% {r['annual']:>+7.1f}% {r['worst_dd']:>+5.1f}%   ${eq_200_1y:>5.0f}")

    print()
    print("=" * 120)
    print("Açıklama:")
    print("  'Yıl1/2/3' — her yıl ayrı $10K başlatıldığında o yılın getirisi")
    print("  'σ' — yıllar arası tutarlılık (düşük = daha öngörülebilir)")
    print("  'Yıllık' — 3y compound ortalama")
    print("  'maxDD' — gördüğümüz en kötü an (paranın yüzde kaçı eridi)")
    print("  '200→1y' — $200 ile 1 yıl sonra Yıl1 senaryosunda cebinde")


if __name__ == "__main__":
    main()
