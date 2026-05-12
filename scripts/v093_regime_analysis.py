"""v0.9.3 — REGIME ANALYSIS: best vs worst 3y rolling pencere karsilastirma.

Amac: 13 pencere icinde 'en kotu' (2022-05 -> 2025-05, yillik +%14.5) ile
'en iyi' (2022-07 -> 2025-07, yillik +%48.4) pencerelerinin makro rejim
imzasi nedir? Hangi degisken filter olarak kullanilabilir?

Cikti:
  - Trade dagilimi (long/short, sembol, strateji, ay)
  - DD ay yigilim (worst pencere)
  - BTC OHLCV rejim metrikleri: ATR%, EMA-trend, hacim, 90d max-DD
  - Best vs worst FARK tablosu
"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

os.environ["PA_LOG_QUIET"] = "1"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

from scripts.v09_optimize_top10 import _gather, TOP_10
from scripts.v091_fix_test import replay_fixed
from scripts.run_real_backtest import _load_symbol_ohlcv

# Pencere tanimlari (PRODUCTION_BENCHMARK.md'den)
WORST_START = pd.Timestamp("2022-05-10", tz="UTC")
WORST_END = pd.Timestamp("2025-05-10", tz="UTC")
BEST_START = pd.Timestamp("2022-07-09", tz="UTC")
BEST_END = pd.Timestamp("2025-07-09", tz="UTC")

SEP = "=" * 100
SUB = "-" * 100


def collect_signals():
    print("Sinyal toplaniyor (10 strateji x 11 sembol, 5y data)...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])
    print(f"Toplam sinyal: {len(all_trades)}")
    return all_trades


def simulate_window(all_trades, start, end, label):
    """v0.9.2 production replay'i (cap 0.30, conf 0.20)."""
    window = [t for t in all_trades if start <= t["entry_ts"] < end]
    r = replay_fixed(
        window,
        risk_pct=0.030, conf_min=0.20,
        consecutive_loss_n=3, consecutive_loss_pause=5,
        max_notional_ratio=0.30,
    )
    return window, r


def per_month_dd_decompose(trades, start, end):
    """Aylik realised P&L yigilimi (replay R*risk yerine R toplami)."""
    out = defaultdict(lambda: {"n": 0, "wins": 0, "losses": 0, "r_sum": 0.0})
    for t in trades:
        ym = f"{t['exit_ts'].year}-{t['exit_ts'].month:02d}"
        out[ym]["n"] += 1
        out[ym]["r_sum"] += t["R"]
        if t["R"] > 0:
            out[ym]["wins"] += 1
        else:
            out[ym]["losses"] += 1
    return dict(sorted(out.items()))


def per_strategy(trades):
    out = defaultdict(lambda: {"n": 0, "wins": 0, "r_sum": 0.0, "longs": 0, "shorts": 0})
    for t in trades:
        s = out[t["strategy"]]
        s["n"] += 1
        s["r_sum"] += t["R"]
        if t["R"] > 0:
            s["wins"] += 1
        if t["side"] == "long":
            s["longs"] += 1
        else:
            s["shorts"] += 1
    return out


def per_symbol(trades):
    out = defaultdict(lambda: {"n": 0, "wins": 0, "r_sum": 0.0, "longs": 0, "shorts": 0})
    for t in trades:
        s = out[t["symbol"]]
        s["n"] += 1
        s["r_sum"] += t["R"]
        if t["R"] > 0:
            s["wins"] += 1
        if t["side"] == "long":
            s["longs"] += 1
        else:
            s["shorts"] += 1
    return out


def big_runners(trades, k=10):
    rs = sorted(trades, key=lambda t: -t["R"])
    return rs[:k]


def big_losers(trades, k=10):
    rs = sorted(trades, key=lambda t: t["R"])
    return rs[:k]


def btc_regime_metrics(start, end, tf="1d"):
    """BTC OHLCV uzerinde pencere icin rejim ozeti."""
    df = _load_symbol_ohlcv("BTC/USDT", tf=tf)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df[(df["ts"] >= start) & (df["ts"] < end)].sort_values("ts").reset_index(drop=True)
    if df.empty:
        return None
    df["ret"] = df["close"].pct_change()
    # ATR (Wilder, 14 gun)
    h_l = df["high"] - df["low"]
    h_c = (df["high"] - df["close"].shift()).abs()
    l_c = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([h_l, h_c, l_c], axis=1).max(axis=1)
    df["atr14"] = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df["atr_pct"] = df["atr14"] / df["close"] * 100
    # EMA200 trend filter
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["above_ema200"] = (df["close"] > df["ema200"]).astype(int)
    df["above_ema50"] = (df["close"] > df["ema50"]).astype(int)
    df["ema50_slope"] = df["ema50"].pct_change(20) * 100  # 20d EMA slope
    # 90d max-DD (BTC kendi DD'si)
    rolling_max = df["close"].rolling(90, min_periods=1).max()
    df["dd_90d"] = (df["close"] / rolling_max - 1) * 100
    # Volatility regime: 30d std
    df["vol_30d"] = df["ret"].rolling(30).std() * np.sqrt(365) * 100  # annualized %
    # Hacim z-score (30d)
    df["vol_z30"] = (df["volume"] - df["volume"].rolling(30).mean()) / df["volume"].rolling(30).std()
    # Net return
    net = (df["close"].iloc[-1] / df["close"].iloc[0] - 1) * 100

    return {
        "n_days": len(df),
        "start_price": float(df["close"].iloc[0]),
        "end_price": float(df["close"].iloc[-1]),
        "net_return_pct": float(net),
        "atr_pct_mean": float(df["atr_pct"].mean()),
        "atr_pct_median": float(df["atr_pct"].median()),
        "atr_pct_p90": float(df["atr_pct"].quantile(0.9)),
        "above_ema200_pct": float(df["above_ema200"].mean() * 100),
        "above_ema50_pct": float(df["above_ema50"].mean() * 100),
        "ema50_slope_mean": float(df["ema50_slope"].mean()),
        "min_dd_90d_pct": float(df["dd_90d"].min()),
        "median_dd_90d_pct": float(df["dd_90d"].median()),
        "vol_30d_mean_ann": float(df["vol_30d"].mean()),
        "vol_30d_max_ann": float(df["vol_30d"].max()),
        "vol_z30_mean": float(df["vol_z30"].dropna().mean()),
        "vol_z30_max": float(df["vol_z30"].dropna().max()),
    }


def regime_classify(df):
    """Her gun icin rejim sinif: bull / bear / range."""
    bull = ((df["close"] > df["ema200"]) & (df["ema50_slope"] > 0)).sum()
    bear = ((df["close"] < df["ema200"]) & (df["ema50_slope"] < 0)).sum()
    n = len(df.dropna(subset=["ema50_slope"]))
    range_ = n - bull - bear
    return {
        "bull_days_pct": float(bull / n * 100) if n else 0,
        "bear_days_pct": float(bear / n * 100) if n else 0,
        "range_days_pct": float(range_ / n * 100) if n else 0,
    }


def btc_regime_full(start, end):
    df = _load_symbol_ohlcv("BTC/USDT", tf="1d")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df[(df["ts"] >= start) & (df["ts"] < end)].sort_values("ts").reset_index(drop=True)
    df["ret"] = df["close"].pct_change()
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    df["ema50_slope"] = df["ema50"].pct_change(20)
    cls = regime_classify(df)
    return cls


def per_month_btc(start, end):
    """Aylik BTC return + ATR%."""
    df = _load_symbol_ohlcv("BTC/USDT", tf="1d")
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df[(df["ts"] >= start) & (df["ts"] < end)].sort_values("ts").reset_index(drop=True)
    df["month"] = df["ts"].dt.strftime("%Y-%m")
    grp = df.groupby("month").agg(open=("open", "first"), close=("close", "last"))
    grp["ret_pct"] = (grp["close"] / grp["open"] - 1) * 100
    return grp


def print_window_summary(label, trades, replay_result):
    print(f"\n{SEP}\n{label}\n{SEP}")
    if replay_result:
        ret = (replay_result["final"] / 10000 - 1) * 100
        yrs = 3.0
        ann = ((replay_result["final"] / 10000) ** (1 / yrs) - 1) * 100
        print(f"  Replay: trades={replay_result['trades']:>3d}  final=${replay_result['final']:>10,.0f}  "
              f"3y={ret:+.1f}%  yillik={ann:+.2f}%  DD={replay_result['max_dd']*100:+.1f}%  WR={replay_result['wr']*100:.1f}%")

    longs = sum(1 for t in trades if t["side"] == "long")
    shorts = sum(1 for t in trades if t["side"] == "short")
    wins = sum(1 for t in trades if t["R"] > 0)
    losses = sum(1 for t in trades if t["R"] <= 0)
    print(f"  Sinyal sayisi (replay oncesi filtre): {len(trades)} "
          f"({longs} long, {shorts} short, wins={wins}, losses={losses})")

    # Per-symbol
    syms = per_symbol(trades)
    print(f"\n  Sembol bazinda (signal sayisi):")
    print(f"    {'Sembol':<14} {'n':>4} {'long':>5} {'short':>5} {'W':>4} {'R_sum':>8}")
    for sym, s in sorted(syms.items(), key=lambda x: -x[1]["n"]):
        print(f"    {sym:<14} {s['n']:>4} {s['longs']:>5} {s['shorts']:>5} {s['wins']:>4} {s['r_sum']:>+7.2f}")

    # Per-strategy
    strat = per_strategy(trades)
    print(f"\n  Strateji bazinda:")
    print(f"    {'Strateji':<32} {'n':>4} {'long':>5} {'short':>5} {'W':>4} {'WR':>5} {'R_sum':>8}")
    for s, st in sorted(strat.items(), key=lambda x: x[1]["r_sum"]):
        wr = st["wins"] / st["n"] * 100 if st["n"] else 0
        print(f"    {s:<32} {st['n']:>4} {st['longs']:>5} {st['shorts']:>5} {st['wins']:>4} {wr:>4.0f}% {st['r_sum']:>+7.2f}")


def diff_table(worst_btc, best_btc, worst_reg, best_reg):
    print(f"\n{SEP}\nBTC REJIM IMZASI — BEST vs WORST FARKI\n{SEP}")
    print(f"  {'Metrik':<32} {'WORST 2022-05':>14} {'BEST 2022-07':>14} {'Fark':>10}")
    print("  " + "-" * 76)

    keys_btc = [
        ("net_return_pct", "BTC net return (3y) %"),
        ("atr_pct_mean", "ATR% mean"),
        ("atr_pct_median", "ATR% median"),
        ("atr_pct_p90", "ATR% p90"),
        ("above_ema200_pct", "EMA200 ustu gun %"),
        ("above_ema50_pct", "EMA50 ustu gun %"),
        ("ema50_slope_mean", "EMA50 slope (20d) %"),
        ("min_dd_90d_pct", "BTC 90d max-DD %"),
        ("median_dd_90d_pct", "BTC 90d median-DD %"),
        ("vol_30d_mean_ann", "30d vol (annualized) %"),
        ("vol_30d_max_ann", "30d vol max %"),
        ("vol_z30_mean", "Hacim z-30 mean"),
        ("vol_z30_max", "Hacim z-30 max"),
    ]
    for key, name in keys_btc:
        w = worst_btc[key]; b = best_btc[key]
        d = b - w
        print(f"  {name:<32} {w:>+13.3f}  {b:>+13.3f}  {d:>+9.3f}")

    print("\n  Rejim sinif (gun %)")
    print(f"  {'':<32} {'WORST':>14} {'BEST':>14} {'Fark':>10}")
    for k, n in [("bull_days_pct", "bull (close>EMA200, slope>0)"),
                 ("bear_days_pct", "bear (close<EMA200, slope<0)"),
                 ("range_days_pct", "range (diger)")]:
        w = worst_reg[k]; b = best_reg[k]
        print(f"  {n:<32} {w:>+13.2f}  {b:>+13.2f}  {(b - w):>+9.2f}")


def print_monthly(label, monthly, btc_monthly):
    print(f"\n{SEP}\n{label} — AYLIK YIGILIM (trade R + BTC return)\n{SEP}")
    print(f"  {'Ay':<10} {'n':>3} {'W':>3} {'L':>3} {'R_sum':>7} {'BTC_ret%':>9}")
    print("  " + "-" * 50)
    btc_dict = btc_monthly["ret_pct"].to_dict()
    for ym, s in monthly.items():
        btc_r = btc_dict.get(ym, np.nan)
        print(f"  {ym:<10} {s['n']:>3} {s['wins']:>3} {s['losses']:>3} {s['r_sum']:>+6.2f} {btc_r:>+8.2f}%")


def print_runners(label, runners, kind):
    print(f"\n  {label} — Top 10 {kind}:")
    print(f"    {'Tarih':<11} {'Sembol':<10} {'Yon':<5} {'Strateji':<28} {'R':>6}")
    for t in runners:
        print(f"    {t['entry_ts'].date()} {t['symbol']:<10} {t['side']:<5} {t['strategy']:<28} {t['R']:>+5.2f}")


def main():
    print(SEP)
    print("v0.9.3 REGIME ANALYSIS — BEST vs WORST 3y rolling pencere")
    print(SEP)
    print(f"  WORST: {WORST_START.date()} -> {WORST_END.date()}  (yillik +%14.5)")
    print(f"  BEST : {BEST_START.date()} -> {BEST_END.date()}  (yillik +%48.4)")

    all_trades = collect_signals()

    worst_trades_raw, worst_r = simulate_window(all_trades, WORST_START, WORST_END, "WORST")
    best_trades_raw, best_r = simulate_window(all_trades, BEST_START, BEST_END, "BEST")
    # conf filter zaten replay icinde; raw=tum sinyaller, R replay sonucu
    # trade dagilim icin conf>=0.2 filtre uygula
    worst_trades = [t for t in worst_trades_raw if t["conf"] >= 0.20]
    best_trades = [t for t in best_trades_raw if t["conf"] >= 0.20]

    print_window_summary("WORST PENCERE 2022-05-10 -> 2025-05-10", worst_trades, worst_r)
    print_window_summary("BEST  PENCERE 2022-07-09 -> 2025-07-09", best_trades, best_r)

    # Aylik yigilim
    worst_monthly = per_month_dd_decompose(worst_trades, WORST_START, WORST_END)
    best_monthly = per_month_dd_decompose(best_trades, BEST_START, BEST_END)
    btc_worst_monthly = per_month_btc(WORST_START, WORST_END)
    btc_best_monthly = per_month_btc(BEST_START, BEST_END)
    print_monthly("WORST", worst_monthly, btc_worst_monthly)
    print_monthly("BEST", best_monthly, btc_best_monthly)

    # Top runners
    print_runners("WORST", big_runners(worst_trades, 10), "winners (R)")
    print_runners("WORST", big_losers(worst_trades, 10), "losers (R)")
    print_runners("BEST", big_runners(best_trades, 10), "winners (R)")
    print_runners("BEST", big_losers(best_trades, 10), "losers (R)")

    # BTC rejim
    worst_btc = btc_regime_metrics(WORST_START, WORST_END)
    best_btc = btc_regime_metrics(BEST_START, BEST_END)
    worst_reg = btc_regime_full(WORST_START, WORST_END)
    best_reg = btc_regime_full(BEST_START, BEST_END)
    diff_table(worst_btc, best_btc, worst_reg, best_reg)

    # Ozet ayrim
    print(f"\n{SEP}\nAYRIM IPUCU\n{SEP}")
    print(f"  WORST pencere BTC net: {worst_btc['net_return_pct']:+.1f}% | EMA200 ustu gun: {worst_btc['above_ema200_pct']:.1f}%")
    print(f"  BEST  pencere BTC net: {best_btc['net_return_pct']:+.1f}%  | EMA200 ustu gun: {best_btc['above_ema200_pct']:.1f}%")
    print(f"  Worst ATR%: {worst_btc['atr_pct_mean']:.2f} vs Best ATR%: {best_btc['atr_pct_mean']:.2f}")
    print(f"  Worst bear gun %: {worst_reg['bear_days_pct']:.1f} vs Best bear gun %: {best_reg['bear_days_pct']:.1f}")
    print(f"  Worst bull gun %: {worst_reg['bull_days_pct']:.1f} vs Best bull gun %: {best_reg['bull_days_pct']:.1f}")

    # Ilk 6 ay (her pencerenin "rejim girisi")
    print(f"\n  Ilk 6 ay rejim girisi (BTC):")
    for label, start, end in [("WORST first-6mo", WORST_START, WORST_START + pd.Timedelta(days=180)),
                              ("BEST  first-6mo", BEST_START, BEST_START + pd.Timedelta(days=180))]:
        m = btc_regime_metrics(start, end)
        r = btc_regime_full(start, end)
        print(f"    {label}: BTC {m['net_return_pct']:+6.1f}%, ATR% {m['atr_pct_mean']:.2f}, "
              f"EMA200>{m['above_ema200_pct']:.0f}%, bear gun {r['bear_days_pct']:.0f}%, "
              f"bull gun {r['bull_days_pct']:.0f}%, 90d_DD {m['min_dd_90d_pct']:+.1f}%")


if __name__ == "__main__":
    main()
