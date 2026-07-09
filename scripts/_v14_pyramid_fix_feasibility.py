"""v14 pyramid FIX fizibilitesi — capture-rate: MFE-touch (backtest) vs 15m-close
(canlı şimdi) vs 5m-close (ince-tick fix proxy).

Soru: peak_R>=1.2 (MFE leg-1'e değen) trade'lerin hold penceresinde kaçında bir
15m bar-CLOSE trigger'ı geçti (canlı yakalayabileceği), kaçında 5m bar-CLOSE
(60s-tick fix'in yaklaşık kurtaracağı)? Boşluk = fix'in kurtarma potansiyeli.

Yorum:
  - 15m-close capture YÜKSEK ama canlı 0/47 → LIVE BUG (daemon yakalamalıydı).
  - 15m düşük, 5m çok daha yüksek → granülarite öldürüyor, tick-fix işe yarar.
  - ikisi de düşük → spike'lar gerçekten intra-bar geçici, fix az kurtarır, manşet MFE-touch fantezisi.

Read-only. OHLCV: data/market.duckdb (15m + 5m).
"""
from __future__ import annotations
import os, pickle, sys
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
import duckdb
import pandas as pd

POOL = ROOT / "data" / "pool_19sym_20260610.pkl"
DB = ROOT / "data" / "market.duckdb"
TRIG = 1.2                 # leg-1 trigger (R)
SAMPLE = 4000             # peak_R>=TRIG trade örneklemi
SEED_STEP = 80            # deterministik örnekleme adımı (Math.random yok)


def main():
    with POOL.open("rb") as f:
        pool = pickle.load(f)
    cand = [t for t in pool if t.get("peak_R", t["R"]) >= TRIG]
    print(f"[pool] {len(pool)} trade | peak_R>=%.1f: {len(cand)}" % TRIG, flush=True)
    # deterministik örnek: her SEED_STEP'te bir al, SAMPLE'a kadar
    samp = cand[::max(1, len(cand) // SAMPLE)][:SAMPLE]
    print(f"[sample] {len(samp)} trade (deterministik stride)", flush=True)

    con = duckdb.connect(str(DB), read_only=True)
    # venue tespit: en çok satırı olan venue
    venue = con.execute(
        "SELECT venue FROM ohlcv WHERE timeframe='15m' GROUP BY venue ORDER BY count(*) DESC LIMIT 1"
    ).fetchone()[0]
    print(f"[venue] {venue}", flush=True)

    # sembol bazında grupla
    from collections import defaultdict
    by_sym = defaultdict(list)
    for t in samp:
        by_sym[t["symbol"]].append(t)

    def load_tf(sym, tf):
        df = con.execute(
            "SELECT ts, open, high, low, close FROM ohlcv "
            "WHERE venue=? AND symbol=? AND timeframe=? ORDER BY ts",
            [venue, sym, tf],
        ).df()
        if df.empty:
            return df
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        return df.set_index("ts")

    stats = {"n": 0, "mfe_touch": 0, "c15": 0, "c5": 0, "no_data": 0,
             "c15_and_not_exit": 0}
    per_strat = defaultdict(lambda: {"n": 0, "c15": 0, "c5": 0})

    for sym, trades in by_sym.items():
        d15 = load_tf(sym, "15m")
        d5 = load_tf(sym, "5m")
        if d15.empty:
            stats["no_data"] += len(trades)
            continue
        for t in trades:
            ep = t["entry_price"]; sl = t["initial_sl"]; side = t["side"]
            iR = abs(ep - sl)
            if iR <= 0:
                continue
            trig_px = ep + TRIG * iR if side == "long" else ep - TRIG * iR
            ets = pd.Timestamp(t["entry_ts"]); xts = pd.Timestamp(t["exit_ts"])
            if ets.tzinfo is None: ets = ets.tz_localize("UTC")
            if xts.tzinfo is None: xts = xts.tz_localize("UTC")
            # hold penceresi bar'ları (pozisyon açıkken oluşan close'lar)
            w15 = d15[(d15.index >= ets) & (d15.index < xts)]
            if w15.empty:
                stats["no_data"] += 1
                continue
            stats["n"] += 1
            st = per_strat[t["strategy"]]; st["n"] += 1
            # MFE-touch (backtest): bar high/low trig'i geçti mi
            if side == "long":
                touch = (w15["high"] >= trig_px).any()
                c15 = (w15["close"] >= trig_px).any()
            else:
                touch = (w15["low"] <= trig_px).any()
                c15 = (w15["close"] <= trig_px).any()
            if touch: stats["mfe_touch"] += 1
            if c15:
                stats["c15"] += 1; st["c15"] += 1
            # 5m-close
            c5 = False
            if not d5.empty:
                w5 = d5[(d5.index >= ets) & (d5.index < xts)]
                if not w5.empty:
                    c5 = ((w5["close"] >= trig_px).any() if side == "long"
                          else (w5["close"] <= trig_px).any())
            if c5:
                stats["c5"] += 1; st["c5"] += 1

    con.close()
    n = stats["n"] or 1
    print("\n" + "=" * 70)
    print(f"CAPTURE-RATE  (peak_R>=1.2 örneklemi, n={stats['n']} geçerli, "
          f"{stats['no_data']} veri-yok)")
    print("=" * 70)
    print(f"  MFE-touch  (backtest varsayımı, bar high/low) : {100*stats['mfe_touch']/n:5.1f}%  "
          f"(~%100 beklenir, sanity)")
    print(f"  15m-close  (CANLI ŞİMDİ yakalayabileceği)     : {100*stats['c15']/n:5.1f}%")
    print(f"  5m-close   (ince-tick fix proxy)              : {100*stats['c5']/n:5.1f}%")
    print("-" * 70)
    print(f"  FIX KAZANIMI 15m→5m: +{100*(stats['c5']-stats['c15'])/n:.1f}pp")
    print(f"  ULAŞILAMAZ ARTIK (5m-close bile kaçırır): {100*(stats['mfe_touch']-stats['c5'])/n:.1f}pp")
    print("\n  Strateji bazında 15m-close / 5m-close capture (n>=50):")
    for s, d in sorted(per_strat.items(), key=lambda x: -x[1]["n"]):
        if d["n"] >= 50:
            print(f"    {s:28s} n={d['n']:4d}  15m={100*d['c15']/d['n']:4.0f}%  5m={100*d['c5']/d['n']:4.0f}%")


if __name__ == "__main__":
    main()
