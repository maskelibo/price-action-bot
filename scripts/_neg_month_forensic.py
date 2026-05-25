"""Negative-month forensic — PHOENIX-SCALP 15m R4 (halt OFF + pyramid ON).

7 negatif ay için trade-level pattern hunting:
  - Sembol konsantrasyonu
  - Strateji konsantrasyonu
  - Side asymmetry (long/short)
  - BTC daily rejim (bull/bear/range)
  - Günlük dağılım (tek-gün crash vs. süreğen erozyon)
  - Vol filter sinyali (vol_z ortalaması)

Sonra kontrolüm:
  - Tüm 61 ay için aynı metrikleri çıkar (baseline dağılım)
  - 7 neg ay outlier mı, yoksa baseline dağılımın bir kuyruğu mu?

Hipotez testleri (Fisher exact / Welch t):
  (a) neg-month side ratio = baseline'dan farklı mı?
  (b) neg-month strategy ratio = baseline'dan farklı mı?
  (c) neg-month sym konsantrasyonu = baseline > mu?
  (d) neg-month BTC ret = bear-konsantre mi?
"""
from __future__ import annotations

import io
import os
import pickle
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, stdev

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import duckdb

POOL_15M = ROOT / "data" / "sec31_15m_pool.pkl"

TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}

NEG_MONTHS = [
    ("2025-07", -7.293, 17),
    ("2026-02", -6.909, 16),
    ("2024-02", -3.085, 14),
    ("2025-01", -1.378, 35),
    ("2023-05", -1.243, 2),   # too few trades
    ("2026-03", -1.121, 9),
    ("2024-10", -0.176, 17),
]


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def month_bounds(yyyy_mm):
    y, m = map(int, yyyy_mm.split("-"))
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    if m == 12:
        end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(y, m + 1, 1, tzinfo=timezone.utc)
    return start, end


def fetch_btc_daily(yyyy_mm):
    """Get BTC 1d returns for given month."""
    start, end = month_bounds(yyyy_mm)
    # extend by 30 days for regime classification (EMA200 needs history)
    pre = datetime(start.year - (1 if start.month <= 8 else 0),
                   start.month + 4 if start.month <= 8 else start.month - 8, 1, tzinfo=timezone.utc)
    con = duckdb.connect(str(ROOT / "data" / "market.duckdb"), read_only=True)
    df = con.execute(
        "SELECT ts, close FROM ohlcv WHERE symbol='BTC/USDT' AND timeframe='1d' "
        "AND ts >= ? AND ts < ? ORDER BY ts",
        [pre, end]
    ).fetchall()
    con.close()
    if not df:
        return None
    closes = [(r[0], r[1]) for r in df]
    month_closes = []
    for ts, cl in closes:
        ts2 = ts if ts.tzinfo is not None else ts.replace(tzinfo=timezone.utc)
        if start <= ts2 < end:
            month_closes.append((ts2, cl))
    if len(month_closes) < 2:
        return None
    first = month_closes[0][1]
    last = month_closes[-1][1]
    pct_change = (last / first - 1) * 100
    # daily returns
    rets = []
    for i in range(1, len(month_closes)):
        rets.append((month_closes[i][1] / month_closes[i-1][1] - 1) * 100)
    return {
        "month_pct": pct_change,
        "daily_rets": rets,
        "n_days": len(month_closes),
        "mean_daily": mean(rets) if rets else 0.0,
        "vol_daily": stdev(rets) if len(rets) > 1 else 0.0,
    }


def analyse_month(yyyy_mm, trades, btc_info=None):
    """Compute per-month forensic metrics from raw trades."""
    if not trades:
        return None
    n = len(trades)
    # symbol concentration
    sym_R = defaultdict(list)
    strat_R = defaultdict(list)
    side_R = defaultdict(list)
    daily_R = defaultdict(list)
    for t in trades:
        sym_R[t["symbol"]].append(t["R"])
        strat_R[t["strategy"]].append(t["R"])
        side_R[t["side"]].append(t["R"])
        d = to_utc(t["entry_ts"]).date()
        daily_R[d].append(t["R"])

    def agg(d):
        return {k: {"n": len(v), "sum_R": round(sum(v), 2), "mean_R": round(sum(v)/len(v), 3)}
                for k, v in d.items()}

    return {
        "yyyy_mm": yyyy_mm,
        "n": n,
        "sum_R": round(sum(t["R"] for t in trades), 2),
        "mean_R": round(sum(t["R"] for t in trades) / n, 3),
        "wr": round(sum(1 for t in trades if t["R"] > 0) / n * 100, 1),
        "by_symbol": agg(sym_R),
        "by_strategy": agg(strat_R),
        "by_side": agg(side_R),
        "n_days_with_trades": len(daily_R),
        "worst_day": (lambda dr: max(dr.items(), key=lambda x: -sum(x[1])) if dr else None)(daily_R),
        "best_day":  (lambda dr: max(dr.items(), key=lambda x: sum(x[1])) if dr else None)(daily_R),
        "btc": btc_info,
    }


def fmt_subdict(d):
    items = sorted(d.items(), key=lambda x: x[1]["sum_R"])
    return " | ".join([f"{k}: n={v['n']} sum_R={v['sum_R']:+.2f}" for k, v in items])


def main():
    print("=" * 100)
    print("NEG-MONTH FORENSIC — PHOENIX-SCALP 15m R4 (halt OFF + pyramid ON)")
    print("=" * 100)

    print(f"\n[LOAD] {POOL_15M.name}")
    with POOL_15M.open("rb") as fh:
        pool_raw = pickle.load(fh)
    pool = [t for t in pool_raw
            if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    print(f"  TOP4 × 10sym pool: {len(pool):,} trade")

    # raw pool per-month split (no replay)
    pool.sort(key=lambda x: to_utc(x["entry_ts"]))

    # ---------- 1) NEG MONTH DETAIL ----------
    print("\n" + "=" * 100)
    print("STEP 1: PER-NEG-MONTH FORENSIC")
    print("=" * 100)

    neg_results = []
    for yyyy_mm, ret_pct, replay_trades in NEG_MONTHS:
        start, end = month_bounds(yyyy_mm)
        m_trades = [t for t in pool if start <= to_utc(t["entry_ts"]) < end]
        btc = fetch_btc_daily(yyyy_mm)
        res = analyse_month(yyyy_mm, m_trades, btc_info=btc)
        if res is None:
            continue
        neg_results.append((yyyy_mm, ret_pct, replay_trades, res))

        print(f"\n--- {yyyy_mm} (replay ret={ret_pct:+.2f}%, replay trades={replay_trades}) ---")
        print(f"  RAW POOL: n={res['n']}, sum_R={res['sum_R']:+.2f}, mean_R={res['mean_R']:+.3f}, wr={res['wr']}%")
        if btc:
            print(f"  BTC daily 1d: month={btc['month_pct']:+.2f}%, daily mu={btc['mean_daily']:+.3f}%, vol={btc['vol_daily']:.2f}%")
        else:
            print(f"  BTC daily: N/A")
        print(f"  BY SIDE     : {fmt_subdict(res['by_side'])}")
        print(f"  BY STRAT    : {fmt_subdict(res['by_strategy'])}")
        print(f"  BY SYMBOL   : {fmt_subdict(res['by_symbol'])}")
        if res["worst_day"]:
            wd, wt = res["worst_day"]
            print(f"  WORST DAY   : {wd} sum_R={sum(wt):+.2f} (n={len(wt)})")
        if res["best_day"]:
            bd, bt = res["best_day"]
            print(f"  BEST DAY    : {bd} sum_R={sum(bt):+.2f} (n={len(bt)})")
        print(f"  DAYS w/trade: {res['n_days_with_trades']}")

    # ---------- 2) BASELINE (61-month dist) ----------
    print("\n" + "=" * 100)
    print("STEP 2: BASELINE PATTERN DISTRIBUTION (61 ay raw pool)")
    print("=" * 100)

    # iterate all months and collect per-month rate of long_share, top_sym_share, top_strat_share
    all_months = {}
    for t in pool:
        ts = to_utc(t["entry_ts"])
        ym = f"{ts.year:04d}-{ts.month:02d}"
        all_months.setdefault(ym, []).append(t)

    long_share_dist, top_sym_share_dist, top_strat_share_dist = [], [], []
    long_meanR_dist, short_meanR_dist = [], []
    sym_top1_R_dist, strat_top1_R_dist = [], []
    neg_set = {ym for ym, _, _ in NEG_MONTHS}

    baseline_rows, neg_rows_summary = [], []
    for ym, trades in sorted(all_months.items()):
        if len(trades) < 5:
            continue
        sides = Counter(t["side"] for t in trades)
        long_share = sides.get("long", 0) / len(trades)
        long_share_dist.append(long_share)

        syms = Counter(t["symbol"] for t in trades)
        top_sym, top_sym_n = syms.most_common(1)[0]
        top_sym_share = top_sym_n / len(trades)
        top_sym_share_dist.append(top_sym_share)

        strats = Counter(t["strategy"] for t in trades)
        top_strat, top_strat_n = strats.most_common(1)[0]
        top_strat_share = top_strat_n / len(trades)
        top_strat_share_dist.append(top_strat_share)

        # per-side mean R
        lR = [t["R"] for t in trades if t["side"] == "long"]
        sR = [t["R"] for t in trades if t["side"] == "short"]
        if lR:
            long_meanR_dist.append(sum(lR) / len(lR))
        if sR:
            short_meanR_dist.append(sum(sR) / len(sR))

        # top-symbol R contribution
        sym_topR = sum(t["R"] for t in trades if t["symbol"] == top_sym)
        sym_top1_R_dist.append(sym_topR)
        # top-strat R contribution
        strat_topR = sum(t["R"] for t in trades if t["strategy"] == top_strat)
        strat_top1_R_dist.append(strat_topR)

        row = {
            "ym": ym, "n": len(trades),
            "sum_R": round(sum(t["R"] for t in trades), 2),
            "long_share": round(long_share, 3),
            "top_sym": top_sym, "top_sym_share": round(top_sym_share, 3),
            "top_strat": top_strat, "top_strat_share": round(top_strat_share, 3),
            "long_meanR": round(sum(lR)/len(lR), 3) if lR else None,
            "short_meanR": round(sum(sR)/len(sR), 3) if sR else None,
        }
        if ym in neg_set:
            neg_rows_summary.append(row)
        else:
            baseline_rows.append(row)

    def stats(arr):
        if not arr:
            return None
        return {
            "n": len(arr),
            "mean": round(sum(arr)/len(arr), 3),
            "stdev": round(stdev(arr), 3) if len(arr) > 1 else 0.0,
            "min": round(min(arr), 3),
            "max": round(max(arr), 3),
        }

    print(f"\n--- BASELINE (all 61 months) ---")
    print(f"  long_share        : {stats(long_share_dist)}")
    print(f"  top_sym_share     : {stats(top_sym_share_dist)}")
    print(f"  top_strat_share   : {stats(top_strat_share_dist)}")
    print(f"  long mean_R / mo  : {stats(long_meanR_dist)}")
    print(f"  short mean_R / mo : {stats(short_meanR_dist)}")
    print(f"  top_sym sum_R     : {stats(sym_top1_R_dist)}")
    print(f"  top_strat sum_R   : {stats(strat_top1_R_dist)}")

    print(f"\n--- NEG MONTH side-by-side ---")
    print(f"  {'ym':<10} {'n':>4} {'sum_R':>7} {'long%':>6} {'top_sym':<12} {'top_sym%':>8} {'top_strat':<24} {'top_strat%':>10} {'long_mR':>8} {'short_mR':>9}")
    for r in neg_rows_summary:
        print(f"  {r['ym']:<10} {r['n']:>4} {r['sum_R']:>+7.2f} {r['long_share']*100:>5.0f}% {r['top_sym']:<12} {r['top_sym_share']*100:>7.0f}% {r['top_strat']:<24} {r['top_strat_share']*100:>9.0f}% "
              f"{(r['long_meanR'] if r['long_meanR'] is not None else 0):>+8.3f} {(r['short_meanR'] if r['short_meanR'] is not None else 0):>+9.3f}")

    # ---------- 3) HYPOTHESIS TESTS ----------
    print("\n" + "=" * 100)
    print("STEP 3: HYPOTHESIS PATTERNS")
    print("=" * 100)

    # H1: neg months have MORE long_share?
    neg_long_shares = [r["long_share"] for r in neg_rows_summary]
    pos_long_shares = [r["long_share"] for r in baseline_rows if r["sum_R"] > 0]
    print(f"\nH1 — Side asymmetry (long_share)")
    print(f"  neg-month mean long_share : {mean(neg_long_shares):.3f} (n={len(neg_long_shares)})")
    print(f"  pos-month mean long_share : {mean(pos_long_shares):.3f} (n={len(pos_long_shares)})")
    diff = mean(neg_long_shares) - mean(pos_long_shares)
    print(f"  delta                     : {diff:+.3f}")

    # H2: neg months have MORE top-sym concentration?
    neg_top_sym = [r["top_sym_share"] for r in neg_rows_summary]
    pos_top_sym = [r["top_sym_share"] for r in baseline_rows if r["sum_R"] > 0]
    print(f"\nH2 — Symbol concentration (top_sym_share)")
    print(f"  neg-month mean top_sym%   : {mean(neg_top_sym):.3f}")
    print(f"  pos-month mean top_sym%   : {mean(pos_top_sym):.3f}")
    print(f"  delta                     : {mean(neg_top_sym)-mean(pos_top_sym):+.3f}")

    # H3: neg months top-strategy concentration?
    neg_top_strat = [r["top_strat_share"] for r in neg_rows_summary]
    pos_top_strat = [r["top_strat_share"] for r in baseline_rows if r["sum_R"] > 0]
    print(f"\nH3 — Strategy concentration (top_strat_share)")
    print(f"  neg-month mean top_strat% : {mean(neg_top_strat):.3f}")
    print(f"  pos-month mean top_strat% : {mean(pos_top_strat):.3f}")
    print(f"  delta                     : {mean(neg_top_strat)-mean(pos_top_strat):+.3f}")

    # H4: BTC monthly return on neg months vs pos months
    print(f"\nH4 — BTC regime in neg months")
    neg_btc = []
    for ym, _, _, res in neg_results:
        if res["btc"]:
            neg_btc.append((ym, res["btc"]["month_pct"]))
    for ym, btc in neg_btc:
        print(f"  {ym} BTC 1d ret : {btc:+.2f}%")
    print(f"  neg-month BTC mean ret: {mean([b for _,b in neg_btc]):+.2f}% (n={len(neg_btc)})")

    # H5: top-sym sum_R in neg months — which single symbol drained the month?
    print(f"\nH5 — Top-sym sum_R in neg months (single-symbol drag)")
    for ym, ret_pct, _, res in neg_results:
        sym_sorted = sorted(res["by_symbol"].items(), key=lambda x: x[1]["sum_R"])
        worst_sym, worst_v = sym_sorted[0]
        share_of_loss = worst_v["sum_R"] / res["sum_R"] if res["sum_R"] < 0 else None
        print(f"  {ym} worst-sym: {worst_sym} sum_R={worst_v['sum_R']:+.2f} (n={worst_v['n']}), month sum_R={res['sum_R']:+.2f}, share_of_loss={share_of_loss}")

    # H6: top-strat sum_R in neg months
    print(f"\nH6 — Top-strat sum_R in neg months (single-strategy drag)")
    for ym, ret_pct, _, res in neg_results:
        strat_sorted = sorted(res["by_strategy"].items(), key=lambda x: x[1]["sum_R"])
        worst_strat, worst_v = strat_sorted[0]
        print(f"  {ym} worst-strat: {worst_strat:<24} sum_R={worst_v['sum_R']:+.2f} (n={worst_v['n']})")

    # H7: tek-gün crash vs sürekli erozyon
    print(f"\nH7 — Single-day crash vs erosion")
    for ym, ret_pct, _, res in neg_results:
        if res["worst_day"]:
            wd, wt = res["worst_day"]
            share_str = f"{sum(wt) / res['sum_R']:.2f}x" if res["sum_R"] < 0 else "N/A (raw_pool pozitif)"
            print(f"  {ym} worst_day {wd} sum_R={sum(wt):+.2f} (share_of_loss={share_str}), days_w/trades={res['n_days_with_trades']}")


if __name__ == "__main__":
    main()
