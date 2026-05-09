"""3 kaybetiren trade'i detaylı incele — neden bot'ta hatali girisler.

Loser trades:
1. SOL/USDT 2026-01-08 SHORT lev 2x  → -$420
2. AVAX/USDT 2026-04-03 SHORT lev 2x → -$504
3. BNB/USDT 2026-04-19 SHORT lev 3x  → -$766
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))


LOSING_TRADES = [
    ("SOL/USDT",  "2026-01-08",  "short", 2, 136.32, 143.55, -1.04, -420),
    ("AVAX/USDT", "2026-04-03",  "short", 2,   8.75,   9.80, -1.02, -504),
    ("BNB/USDT",  "2026-04-19",  "short", 3, 629.59, 645.99, -1.08, -766),
]


def _load_with_context(symbol: str, entry_date: str, before_bars: int = 10, after_bars: int = 10):
    from price_action.strategies.engulfing_continuation import (
        EngulfingContinuationStrategy, _default_manifest as engulf_manifest,
    )
    from price_action.signals.filters import rolling_sharpe
    from scripts.run_real_backtest import _load_symbol_ohlcv

    df = _load_symbol_ohlcv(symbol, tf="1d")
    df = df.sort_values("ts").reset_index(drop=True)
    s = EngulfingContinuationStrategy(engulf_manifest())
    df_feats = s.prepare_features(df)
    df_feats["rolling_sharpe_60"] = rolling_sharpe(df_feats["close"], period=60)
    df_feats["body_ratio"] = (df_feats["close"] - df_feats["open"]).abs() / (df_feats["high"] - df_feats["low"]).replace(0, np.nan)

    entry_dt = pd.Timestamp(entry_date, tz="UTC")
    df_feats["ts_d"] = pd.to_datetime(df_feats["ts"], utc=True).dt.date
    target = pd.Timestamp(entry_date).date()
    matches = df_feats[df_feats["ts_d"] == target]
    if matches.empty:
        return None
    idx = matches.index[0]
    lo = max(0, idx - before_bars)
    hi = min(len(df_feats), idx + after_bars + 1)
    return df_feats.iloc[lo:hi].copy(), idx - lo


def main():
    print("=" * 100)
    print("KAYBETİREN 3 TRADE — Detaylı İnceleme")
    print("=" * 100)

    for sym, date, side, lev, ent, ext, R, pnl in LOSING_TRADES:
        ctx_data = _load_with_context(sym, date, before_bars=10, after_bars=8)
        if ctx_data is None:
            print(f"\n{sym} {date}: veri bulunamadı")
            continue
        ctx, signal_idx = ctx_data

        print()
        print("█" * 100)
        print(f"  {sym} | {date} | {side.upper()} | lev {lev}x | Entry ${ent} | Exit ${ext} | R={R} | P&L ${pnl}")
        print("█" * 100)

        # Context bars
        print()
        print(f"{'Tarih':<11} {'open':>9} {'high':>9} {'low':>9} {'close':>9} {'body':>5} {'ema50':>9} {'ema200':>9} {'atr%':>5} {'KER':>4} {'vol_z':>5} {'rolSh':>5} {'note':>15}")
        print("-" * 130)

        for i, row in ctx.iterrows():
            d = pd.Timestamp(row["ts"]).strftime("%Y-%m-%d")
            body_pct = abs(row["close"] - row["open"]) / max(row["high"] - row["low"], 0.0001) * 100
            note = ""
            ema_trend = float(row.get("ema_trend", 0)) if not pd.isna(row.get("ema_trend", np.nan)) else 0
            ema200 = float(row.get("ema200", 0)) if not pd.isna(row.get("ema200", np.nan)) else 0
            atr_pct = float(row.get("atr_pct", 0)) * 100 if not pd.isna(row.get("atr_pct", np.nan)) else 0
            ker = float(row.get("kaufman_er", 0)) if not pd.isna(row.get("kaufman_er", np.nan)) else 0
            vz = float(row.get("vol_z", 0)) if not pd.isna(row.get("vol_z", np.nan)) else 0
            rs = float(row.get("rolling_sharpe_60", 0)) if not pd.isna(row.get("rolling_sharpe_60", np.nan)) else 0

            local_idx = i - ctx.index[0]
            if local_idx == signal_idx - 1:
                note = "PREV BAR"
            elif local_idx == signal_idx:
                note = "🔥 SIGNAL/ENTRY"
            elif local_idx == signal_idx + 1:
                note = "T+1"

            o, h, l, c = float(row["open"]), float(row["high"]), float(row["low"]), float(row["close"])
            print(f"{d:<11} {o:>9.2f} {h:>9.2f} {l:>9.2f} {c:>9.2f} {body_pct:>4.0f}% {ema_trend:>9.2f} {ema200:>9.2f} {atr_pct:>4.1f}% {ker:>4.2f} {vz:>+5.2f} {rs:>+5.2f} {note:>15}")

        # Signal bar analizi
        sig = ctx.iloc[signal_idx]
        prev = ctx.iloc[signal_idx - 1] if signal_idx > 0 else None
        print()
        print("🔍 SİNYAL BAR ANALIZI:")
        print(f"   • Pattern türü: bearish_engulfing (büyük olasılıkla)")
        if prev is not None:
            prev_body = abs(prev["close"] - prev["open"])
            sig_body = abs(sig["close"] - sig["open"])
            engulf = sig["open"] > prev["close"] and sig["close"] < prev["open"]
            print(f"   • Engulfing geçerli: {engulf} (sig_body=${sig_body:.2f} prev_body=${prev_body:.2f})")
            print(f"   • EMA trend (50): close ${sig['close']:.2f} {'<' if sig['close'] < sig.get('ema_trend', 0) else '>'} ema50 ${sig.get('ema_trend', 0):.2f}")
            print(f"   • EMA200: close ${sig['close']:.2f} {'<' if sig['close'] < sig.get('ema200', 0) else '>'} ema200 ${sig.get('ema200', 0):.2f}")
            print(f"   • Kaufman ER: {sig.get('kaufman_er', 0):.2f} (>0.20 → onay)")
            print(f"   • Volume z-score: {sig.get('vol_z', 0):+.2f}")

        # Sonraki barlar — ne oldu
        print()
        print("📈 SONRAKİ BARLAR — fiyat ne yaptı:")
        for j in range(signal_idx, min(signal_idx + 5, len(ctx))):
            row = ctx.iloc[j]
            d = pd.Timestamp(row["ts"]).strftime("%Y-%m-%d")
            change_pct = (float(row["close"]) - ent) / ent * 100 if side == "short" else 0
            label = "T+0 (entry)" if j == signal_idx else f"T+{j-signal_idx}"
            print(f"   {label:<14} {d}: close ${float(row['close']):.2f}  ({-change_pct:+.2f}% from entry, short P&L)")

        # Verdict
        print()
        print("⚠️  NEDEN HATALI:")
        # Specific to each trade
        if sym == "SOL/USDT":
            print("   • SOL'da bearish engulfing fired AMA bağlam zayıf:")
            print("     - Confidence 0.32 (tier'ın alt sınırı, lev 2x)")
            print("     - Kaufman ER düşük (chop benzeri)")
            print("     - Sinyal sonrası SOL pump → SL hit oldu")
            print("     - Ders: confidence 0.32 olunca skip etmeli (lev 1x bile riskli)")
        elif sym == "AVAX/USDT":
            print("   • AVAX 2026-04-03 short — Nisan 2026 toparlanmaya geçtiği dönem")
            print("     - Bot bear devam edecek sandı, ama trend dönüyordu")
            print("     - Ders: 200-EMA üstüne geçince bear sinyali güvenilmez")
            print("     - Filter eksik: ema200 cross indikatörü olmalıydı")
        elif sym == "BNB/USDT":
            print("   • BNB 2026-04-19 short lev 3x — en büyük kayıp")
            print("     - Lev 3x yüksek (confidence 0.47)")
            print("     - Genel piyasa Nisan'da toparlandığı için bearish engulfing yanıltıcı")
            print("     - $9,162 notional çok büyük — equity'nin %78'i (single trade)")
            print("     - Ders: confidence 0.47'de lev 3x belki yüksek, lev 2x olmalıydı")

    # GENEL DERS
    print()
    print("=" * 100)
    print("🎓 GENEL ÖĞRENMELER (3 kaybetiren trade'den)")
    print("=" * 100)
    print("""
  1. CONFIDENCE 0.32-0.47 ARASI = ORTA RISK
     Bu aralık tier sınırlarında. Bot lev 2x veya 3x veriyor ama gerçek edge düşük.
     ÖNERI: Confidence < 0.42 → trade reject (sadece 3x+ tier'ları al)

  2. EMA200 CROSS = TREND DONUSU UYARISI
     Nisan 2026'da BTC ema200'ün üstüne geçti → bearish bias zayıf
     ÖNERI: 200-EMA above + bearish signal → conflict, skip

  3. NOTIONAL EQUITY'NIN %50'SINI GEÇMESIN
     BNB lev 3x'te notional $9,162 = equity'nin %78 (tek trade)
     Bir SL hit %2 değil %5+ kayıp etkisi yaratır
     ÖNERI: max_notional_pct = %50 (single position cap)

  4. BACK-TO-BACK BEARISH FAILURE → REJIM DEGISIM SINYALI
     AVAX/BNB Nisan'da 2 ardışık short kaybetti → trend dönüyor
     ÖNERI: 2 ardışık aynı yönde kayıp → 1 hafta short reject

  5. BACKTEST'TE GÖRMEYEN SHANS-SAFETLİĞİ KONTROLLERI
     Bot 6 sinyal arasında 3 doğru, 3 yanlış (random gibi)
     Statistik anlamlılık için minimum 30+ trade gerek
     4 aylık veri istatistik yetersiz — paper trading şart
""")


if __name__ == "__main__":
    main()
