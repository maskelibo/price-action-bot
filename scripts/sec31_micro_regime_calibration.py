"""SEC31: Micro-Regime Signature Calibration — 15m / 5m / 1m capitulation halt.

CONTEXT
-------
v1 regime filter (capitulation halt) 1d için kalibre:
  ATR%(14) >= 6.0 + below_EMA200_streak >= 10 + 90d_DD <= -25  (any 2 of 3 → halt)
  Resume: ATR%<=4 AND BTC>EMA50 for 5 consec days.
Kaynak: src/price_action/backtest/regime.py + memory/analyst/learning_20260512_regime_signature.md

PROBLEM
-------
1d eşikler intraday TF'de neyi karşılar?
  - 1d ATR%(14) = 14 günlük volatilite proxy'si (~280 saat real-time)
  - 15m ATR%(14) sadece 3.5 saatlik pencere → mikrostrüktür gürültüsü dominant
  - Naive scale (14 → 14×96=1344 bar) işe yarayabilir AMA ATR% absolute eşik
    (6.0%) TF-bağımsız DEĞİL (intraday ATR% genelde 0.1-0.5% range).

YAKLAŞIM (calibration framework — 3 ADIM)
------------------------------------------
1. **Pencere scale**: ATR period = 14 (TF-agnostic), AMA reference window TF-ölçekli:
   - 1d:  14 bar (=14 gün)
   - 15m: 56 bar (=14 saat, intraday "1 sessions") VEYA 96×14=1344 bar (=14 gün)
   - 5m:  168 bar (=14 saat) VEYA 288×14=4032 bar (=14 gün)
   - 1m:  840 bar (=14 saat) VEYA 1440×14=20160 bar (=14 gün)
   → Iki sürüm: "intraday-native" (14 saat) ve "scaled-equivalent" (14 gün).

2. **ATR% eşik percentile**: Absolute eşik yerine ROLLING PERCENTILE.
   1d eşik 6.0% pratikte 5y BTC distribution'unda p~90-92. Aynı percentile'ı
   her TF'de yeniden hesapla:
     - threshold_TF = percentile_92(ATR%(14)_TF_5y_BTC)
   Bu TF-agnostic ve symbol-agnostic; piyasa kendi gürültü tabanına göre kalibre.

3. **Drawdown pencereleri TF-scaled**:
   - 1d:  90d DD = 90 bar
   - 15m: 90 gün × 96 = 8640 bar VEYA "intraday session" 3 gün × 96 = 288 bar
   - 5m:  90 gün × 288 = 25920 bar VEYA 3 gün × 288 = 864 bar
   - 1m:  90 gün × 1440 = 129600 bar VEYA 3 gün × 1440 = 4320 bar
   → "session-native" (3 gün) intraday rejimi yakalar (Phoenix 1d'deki 90g
     yapısal bear DD'sinin intraday karşılığı).

OUTPUT TABLE
------------
TF × {atr_pct_p92, dd_session_pct, ema_streak_session} threshold önerileri.

KISITLAR
--------
- Bu sprint kalibrasyon **framework** üretir; gerçek empirik tarama scalper backtest
  pool'u gelince çalıştırılacak. Şu an BTC 1d datası üstünde demo + intraday için
  formül + script harness var.
- 1m BTC 5y datası ~2.6M bar — DuckDB load + rolling percentile single thread 30-60s
  beklenir, multi-symbol için multiprocessing fanout SEC32 sprint'i.
- ATR% percentile distribution-dependent: 2022 LUNA / 2024 ETH ETF gibi
  rejim shift'ler eşiği etkiler — rolling 1y percentile vs cumulative 5y percentile
  ablation gerekli (bu script CUMULATIVE 5y default, parametrize edildi).

USAGE
-----
    python scripts/sec31_micro_regime_calibration.py            # 1d demo (mevcut)
    python scripts/sec31_micro_regime_calibration.py --tf 15m   # ingest sonrası
    python scripts/sec31_micro_regime_calibration.py --tf 5m    # SEC29.5m sonra
    python scripts/sec31_micro_regime_calibration.py --all      # tüm TF (data hazırsa)
"""
from __future__ import annotations

import argparse
import io
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"

# Windows console UTF-8 fix
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# TF-bar mapping (1d baseline)
BARS_PER_DAY: dict[str, int] = {
    "1d": 1,
    "4h": 6,
    "1h": 24,
    "15m": 96,
    "5m": 288,
    "1m": 1440,
}

# Calibration profile — 1d baseline'a denk olacak şekilde TF-scaled pencereler
@dataclass(frozen=True)
class TFProfile:
    tf: str
    atr_period: int          # ATR period (TF-agnostic 14)
    dd_session_bars: int     # session-native DD penceresi (intraday 3 gün varsayılan)
    ema_long_bars: int       # 1d EMA200 equivalent (intraday'de TF-scaled OR fixed)
    ema_short_bars: int      # 1d EMA50 equivalent (resume kontrolü)
    streak_session_bars: int # streak eşiği (intraday'de saat cinsinden değil bar)
    target_atr_p: float      # ATR% percentile (capitulation eşiği)
    target_atr_p_resume: float  # resume için ATR% percentile alt
    streak_session_min: int  # min consec bar threshold
    resume_streak_min: int   # resume için consec bar


# Default TF profilleri (theoretical önerii)
# 1d: mevcut Phoenix v1 ayarları (referans)
# 15m: session = 3 gün × 96 = 288 bar, EMA "200" = ~2 gün × 96 = 192 → 200 yakın
# 5m:  session = 3 gün × 288 = 864 bar, EMA "200" = ~17 saat × 12 = 200 (12 bar/saat)
# 1m:  session = 3 gün × 1440 = 4320 bar, EMA "200" = ~3.3 saat × 60 = 200
TF_PROFILES: dict[str, TFProfile] = {
    "1d": TFProfile(
        tf="1d", atr_period=14,
        dd_session_bars=90,             # 90 gün
        ema_long_bars=200, ema_short_bars=50,
        streak_session_bars=10,
        target_atr_p=92.0, target_atr_p_resume=70.0,
        streak_session_min=10, resume_streak_min=5,
    ),
    "15m": TFProfile(
        tf="15m", atr_period=14,
        dd_session_bars=288,            # 3 gün × 96
        ema_long_bars=200, ema_short_bars=50,    # ~50 saat, ~12.5 saat
        streak_session_bars=96,                  # 24 saat consec below-EMA
        target_atr_p=92.0, target_atr_p_resume=70.0,
        streak_session_min=96, resume_streak_min=24,    # 24-bar = 6 saat resume
    ),
    "5m": TFProfile(
        tf="5m", atr_period=14,
        dd_session_bars=864,            # 3 gün × 288
        ema_long_bars=200, ema_short_bars=50,    # ~17 saat, ~4 saat
        streak_session_bars=288,                 # 24 saat consec
        target_atr_p=92.0, target_atr_p_resume=70.0,
        streak_session_min=288, resume_streak_min=72,   # 72-bar = 6 saat resume
    ),
    "1m": TFProfile(
        tf="1m", atr_period=14,
        dd_session_bars=4320,           # 3 gün × 1440
        ema_long_bars=200, ema_short_bars=50,    # ~3.3 saat, ~50 dk
        streak_session_bars=1440,                # 24 saat consec
        target_atr_p=92.0, target_atr_p_resume=70.0,
        streak_session_min=1440, resume_streak_min=360,  # 360-bar = 6 saat resume
    ),
}


def wilder_atr(df: pd.DataFrame, period: int) -> pd.Series:
    """Wilder ATR (EMA alpha = 1/period). regime.py ile parite."""
    h_l = df["high"] - df["low"]
    h_c = (df["high"] - df["close"].shift()).abs()
    l_c = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([h_l, h_c, l_c], axis=1).max(axis=1)
    return tr.ewm(alpha=1.0 / period, adjust=False).mean()


def compute_calibration(df: pd.DataFrame, profile: TFProfile) -> dict[str, float]:
    """ATR% percentile + DD distribution + streak distribution.

    Args:
        df: BTC OHLCV (ts, open, high, low, close, volume) — ts ascending
        profile: TFProfile (mevcut TF için scale)

    Returns: dict — calibration metrikleri (önerilen eşikler dahil).
    """
    if df.empty or len(df) < profile.atr_period * 5:
        return {"error": "insufficient_data", "n_bars": len(df)}

    df = df.copy()
    df["atr"] = wilder_atr(df, profile.atr_period)
    df["atr_pct"] = df["atr"] / df["close"] * 100.0

    # EMA long/short
    df["ema_long"] = df["close"].ewm(span=profile.ema_long_bars, adjust=False).mean()
    df["ema_short"] = df["close"].ewm(span=profile.ema_short_bars, adjust=False).mean()
    df["below_ema_long"] = (df["close"] < df["ema_long"]).astype(int)

    # Streak hesabı (vectorize: cumcount within group)
    g = (df["below_ema_long"] != df["below_ema_long"].shift()).cumsum()
    df["below_streak"] = df.groupby(g).cumcount() + 1
    df.loc[df["below_ema_long"] == 0, "below_streak"] = 0

    # DD session-native (rolling max → DD%)
    rolling_max = df["close"].rolling(profile.dd_session_bars, min_periods=1).max()
    df["dd_session"] = (df["close"] / rolling_max - 1.0) * 100.0

    # Percentile thresholds
    atr_p92 = float(np.nanpercentile(df["atr_pct"].dropna(), profile.target_atr_p))
    atr_p70 = float(np.nanpercentile(df["atr_pct"].dropna(), profile.target_atr_p_resume))
    dd_p8 = float(np.nanpercentile(df["dd_session"].dropna(), 100.0 - profile.target_atr_p))
    # (DD negatif → p8 ≈ en dipteki %8)

    # Streak distribution (sadece nonzero)
    nonzero_streaks = df.loc[df["below_streak"] > 0, "below_streak"]
    streak_p92 = float(np.nanpercentile(nonzero_streaks, profile.target_atr_p)) if not nonzero_streaks.empty else 0.0

    out = {
        "tf": profile.tf,
        "n_bars": int(len(df)),
        "first_ts": str(df["ts"].iloc[0])[:19] if "ts" in df.columns else "",
        "last_ts": str(df["ts"].iloc[-1])[:19] if "ts" in df.columns else "",
        "atr_period": profile.atr_period,
        # Önerilen capitulation thresholds (TF-native)
        "threshold_atr_pct_p92": round(atr_p92, 4),
        "threshold_atr_pct_resume_p70": round(atr_p70, 4),
        "threshold_dd_session_pct": round(dd_p8, 4),
        "threshold_streak_min_bars": int(profile.streak_session_min),
        "threshold_streak_p92": round(streak_p92, 1),
        # Distribution stats
        "atr_pct_median": round(float(df["atr_pct"].median()), 4),
        "atr_pct_p99": round(float(np.nanpercentile(df["atr_pct"].dropna(), 99)), 4),
        "dd_session_median": round(float(df["dd_session"].median()), 4),
        "dd_session_p1": round(float(np.nanpercentile(df["dd_session"].dropna(), 1)), 4),
        # Reference (1d Phoenix eşiği ile karşılaştırma)
        "ref_phoenix_1d_atr_pct": 6.0,
        "ref_phoenix_1d_dd_90d": -25.0,
        "ref_phoenix_1d_streak": 10,
    }
    return out


def _load_btc_parquet(tf: str) -> pd.DataFrame:
    """Parquet fallback (daemon-safe — DuckDB lock'tan kaçar)."""
    parquet_root = ROOT / "data" / "parquet" / "binance" / "BTC_USDT" / tf
    if not parquet_root.exists():
        return pd.DataFrame()
    files = sorted(parquet_root.rglob("*.parquet"))
    if not files:
        return pd.DataFrame()
    dfs = []
    for f in files:
        try:
            dfs.append(pd.read_parquet(f))
        except Exception:
            continue
    if not dfs:
        return pd.DataFrame()
    df = pd.concat(dfs, ignore_index=True)
    return df


def load_btc(tf: str, start_iso: str | None = None) -> pd.DataFrame:
    """BTC/USDT OHLCV loader. DuckDB read-only önce, fail olursa Parquet fallback."""
    df = pd.DataFrame()
    try:
        import duckdb
        db_path = ROOT / "data" / "market.duckdb"
        con = duckdb.connect(str(db_path), read_only=True)
        try:
            df = con.execute(
                "SELECT ts, open, high, low, close, volume FROM ohlcv "
                "WHERE venue=? AND symbol=? AND timeframe=? ORDER BY ts",
                ["binance", "BTC/USDT", tf],
            ).fetchdf()
        finally:
            con.close()
    except Exception as exc:
        print(f"   [WARN] duckdb load failed ({exc.__class__.__name__}); fallback parquet")
        df = _load_btc_parquet(tf)
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    if start_iso:
        start_dt = pd.Timestamp(start_iso, tz="UTC")
        df = df[df["ts"] >= start_dt]
    df = df.sort_values("ts").reset_index(drop=True)
    return df[["ts", "open", "high", "low", "close", "volume"]]


def main() -> None:
    ap = argparse.ArgumentParser(description="Micro-regime signature calibration harness")
    ap.add_argument("--tf", default="1d", choices=list(TF_PROFILES.keys()),
                    help="TF to calibrate (default: 1d demo)")
    ap.add_argument("--all", action="store_true", help="Try all TFs (skips missing data)")
    ap.add_argument("--start", default=None, help="ISO start date (default: full history)")
    args = ap.parse_args()

    tfs = list(TF_PROFILES.keys()) if args.all else [args.tf]

    print("SEC31: Micro-Regime Signature Calibration")
    print("=" * 78)
    print(f"  Reference (Phoenix 1d):  ATR% >= 6.0  |  DD90d <= -25%  |  EMA200 streak >= 10")
    print(f"  Method: percentile-based, TF-native scaling, session-DD (3-day intraday)")
    print()

    results: list[dict] = []
    for tf in tfs:
        profile = TF_PROFILES[tf]
        print(f">> {tf}  (atr={profile.atr_period}, dd_session={profile.dd_session_bars}b, "
              f"ema_long={profile.ema_long_bars}b)")
        df = load_btc(tf, start_iso=args.start)
        if df.empty:
            print(f"   [SKIP] no data for BTC/USDT @ {tf}")
            continue
        res = compute_calibration(df, profile)
        results.append(res)
        print(f"   n={res['n_bars']:>9}  range={res['first_ts']} - {res['last_ts']}")
        print(f"   ATR% p50={res['atr_pct_median']:.3f}  p92={res['threshold_atr_pct_p92']:.3f}  p99={res['atr_pct_p99']:.3f}")
        print(f"   DD(session) p50={res['dd_session_median']:.3f}%  p8(deep)={res['threshold_dd_session_pct']:.3f}%")
        print(f"   Streak p92 (nonzero below-EMA bars)={res['threshold_streak_p92']:.1f}")
        print()

    # Compact summary table
    if results:
        print("=" * 78)
        print("CALIBRATION SUMMARY — önerilen capitulation eşikleri (any-2-of-3 ile birleştir)")
        print("=" * 78)
        header = f"{'TF':<6}{'ATR% thr':>10}{'DD% thr':>12}{'streak thr':>14}{'resume ATR%':>14}"
        print(header)
        print("-" * 78)
        for r in results:
            row = (
                f"{r['tf']:<6}"
                f"{r['threshold_atr_pct_p92']:>10.3f}"
                f"{r['threshold_dd_session_pct']:>12.3f}"
                f"{r['threshold_streak_min_bars']:>14}"
                f"{r['threshold_atr_pct_resume_p70']:>14.3f}"
            )
            print(row)
        print()
        print("NOTE: Bu eşikler EMPİRİK (BTC 5y distribution). Multi-symbol kalibrasyon")
        print("için sym-bazlı percentile (ETH/SOL/alts ayrı) → median ensemble önerilir.")
        print()
        print("DEPLOY: src/price_action/risk/regime_filter.py + scripts/regime_compute_intraday.py")
        print("        wiring scalper backtest pool gelince yapılacak (Phase 5).")


if __name__ == "__main__":
    main()
