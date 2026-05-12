"""v0.9.5 — Per-strategy / per-symbol / per-cell ABLATION matrisi.

GOREV:
  1. Her stratejiyi tek tek drop -> baseline'a kiyasla katkisi olcer
  2. Her sembolu tek tek drop -> baseline'a kiyasla katkisi olcer
  3. 10x11 strategy x symbol matrisi: her hucrenin sum_R toplami
  4. Confidence bucket analizi (0.20-0.30, 0.30-0.40, ...)
  5. Combo testler: en kotu 3 hucreyi drop + conf esigi yukselt
  6. Bootstrap CI (variance kontrol)

KOSULLAR:
  - canonical production_replay (lab.py) tek source of truth
  - 3y rolling 13 pencere (her senaryo)
  - quiet logging
"""
from __future__ import annotations

import os

os.environ["PA_LOG_QUIET"] = "1"

import random
import sys
import time
from collections import defaultdict
from pathlib import Path
from statistics import mean, median, stdev

import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))

from price_action.backtest.lab import ProductionConfig, production_replay
from scripts.v09_optimize_top10 import _gather, TOP_10, SYMBOLS_11

STRATEGY_NAMES = [m for m, _ in TOP_10]
RANDOM_SEED = 42


# =========================================================================
# Rolling helper
# =========================================================================


def build_rolling_windows(all_trades: list[dict]) -> list[tuple]:
    full_start = all_trades[0]["entry_ts"]
    full_end = all_trades[-1]["exit_ts"]
    out = []
    cur = full_start
    while cur + pd.Timedelta(days=3 * 365) <= full_end:
        out.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)
    return out


def run_rolling(all_trades, windows, cfg) -> dict:
    anns, dds, finals, ns = [], [], [], []
    for ws, we in windows:
        wt = [t for t in all_trades if ws <= t["entry_ts"] < we]
        if len(wt) < 10:
            continue
        r = production_replay(wt, cfg)
        if r is None:
            continue
        years = (we - ws).total_seconds() / (365.25 * 86400)
        anns.append(r.annualized(years) * 100)
        dds.append(r.max_drawdown * 100)
        finals.append(r.final_equity)
        ns.append(r.trades)
    if not anns:
        return {"n_windows": 0}
    return {
        "n_windows": len(anns),
        "mean_ann": mean(anns),
        "median_ann": median(anns),
        "min_ann": min(anns),
        "max_ann": max(anns),
        "std_ann": stdev(anns) if len(anns) > 1 else 0,
        "mean_dd": mean(dds),
        "min_dd": min(dds),
        "mean_final": mean(finals),
        "mean_n": mean(ns),
    }


# =========================================================================
# Main analysis
# =========================================================================


def main():
    t0 = time.time()
    lines: list[str] = []

    def log(msg=""):
        print(msg)
        lines.append(msg)

    log("=" * 100)
    log("v0.9.5 STRATEJI x SEMBOL ABLATION MATRISI")
    log("=" * 100)
    log("")
    log("KAYNAK: canonical production_replay (lab.py)")
    log("PENCERE: 3y rolling 13 pencere (60-gun adim)")
    log("BASE CONFIG: risk.yaml v0.9.2 production (r%3, cap0.30, conf>=0.20, cd3/5d)")
    log("")

    log("Trade'leri topluyor (10 strateji x 11 sembol, 5y data)...")
    all_trades = []
    for m, c in TOP_10:
        trs = _gather(m, c)
        all_trades.extend(trs)
        log(f"  {m:<32} n={len(trs)}")
    all_trades.sort(key=lambda x: x["entry_ts"])
    log(f"  TOPLAM SINYAL: {len(all_trades)}")
    log(f"  (gather: {time.time() - t0:.1f}s)")
    log("")

    windows = build_rolling_windows(all_trades)
    log(f"3y rolling pencere sayisi: {len(windows)}")
    log(f"  Ilk pencere : {windows[0][0].date()} -> {windows[0][1].date()}")
    log(f"  Son pencere : {windows[-1][0].date()} -> {windows[-1][1].date()}")
    log("")

    base_cfg = ProductionConfig.from_yaml()
    log(f"BASE CONFIG label: {base_cfg.label()}")
    log("")

    # =====================================================================
    # PART 0 — BASELINE
    # =====================================================================
    log("=" * 100)
    log("PART 0 — BASELINE (drop yok)")
    log("=" * 100)
    base = run_rolling(all_trades, windows, base_cfg)
    log(
        f"  ort. yIllIk: {base['mean_ann']:+.2f}%   median: {base['median_ann']:+.2f}%"
        f"   min: {base['min_ann']:+.1f}%   max: {base['max_ann']:+.1f}%"
    )
    log(
        f"  ort. DD    : {base['mean_dd']:+.1f}%   min DD: {base['min_dd']:+.1f}%"
        f"   ort. n: {base['mean_n']:.0f}"
    )
    log("")

    # =====================================================================
    # PART 1 — PER-STRATEGY ABLATION
    # =====================================================================
    log("=" * 100)
    log("PART 1 — PER-STRATEGY ABLATION (her stratejiyi tek tek drop)")
    log("=" * 100)
    log("Yorum: 'delta_ann' baseline'a gore yillik degisim.")
    log("       delta < 0  => strateji KAZANDIRIYOR (cikinca dustu)")
    log("       delta > 0  => strateji KAYIPLI    (cikinca yukseldi) -> DROP onerilir")
    log("")
    log(f"{'Strateji':<32} {'ort. yIllIk':>13} {'delta_ann':>11} {'ort. DD':>9} {'delta_DD':>10} {'ort. n':>8}")
    log("-" * 100)

    per_strat_rows = []
    for strat in STRATEGY_NAMES:
        cfg = base_cfg.with_overrides(drop_strategies=frozenset({strat}))
        r = run_rolling(all_trades, windows, cfg)
        if r["n_windows"] == 0:
            log(f"  {strat:<32} (sonuc yok)")
            continue
        d_ann = r["mean_ann"] - base["mean_ann"]
        d_dd = r["mean_dd"] - base["mean_dd"]
        verdict = "DROP" if d_ann > 1.5 else ("KEEP-VAL" if d_ann < -2 else "neutral")
        per_strat_rows.append((strat, r["mean_ann"], d_ann, r["mean_dd"], d_dd, r["mean_n"], verdict))
        log(
            f"  {strat:<32} {r['mean_ann']:>+11.2f}% {d_ann:>+9.2f}pp"
            f" {r['mean_dd']:>+7.1f}% {d_dd:>+8.1f}pp {r['mean_n']:>6.0f}  [{verdict}]"
        )
    log("")

    # =====================================================================
    # PART 2 — PER-SYMBOL ABLATION
    # =====================================================================
    log("=" * 100)
    log("PART 2 — PER-SYMBOL ABLATION (her sembolu tek tek drop)")
    log("=" * 100)
    log("")
    log(f"{'Sembol':<14} {'ort. yIllIk':>13} {'delta_ann':>11} {'ort. DD':>9} {'delta_DD':>10} {'ort. n':>8}")
    log("-" * 80)

    per_sym_rows = []
    for sym in SYMBOLS_11:
        cfg = base_cfg.with_overrides(drop_symbols=frozenset({sym}))
        r = run_rolling(all_trades, windows, cfg)
        if r["n_windows"] == 0:
            log(f"  {sym:<14} (sonuc yok)")
            continue
        d_ann = r["mean_ann"] - base["mean_ann"]
        d_dd = r["mean_dd"] - base["mean_dd"]
        verdict = "DROP" if d_ann > 1.5 else ("KEEP-VAL" if d_ann < -2 else "neutral")
        per_sym_rows.append((sym, r["mean_ann"], d_ann, r["mean_dd"], d_dd, r["mean_n"], verdict))
        log(
            f"  {sym:<14} {r['mean_ann']:>+11.2f}% {d_ann:>+9.2f}pp"
            f" {r['mean_dd']:>+7.1f}% {d_dd:>+8.1f}pp {r['mean_n']:>6.0f}  [{verdict}]"
        )
    log("")

    # =====================================================================
    # PART 3 — STRATEGY x SYMBOL MATRIS (raw sum_R + trade count)
    # =====================================================================
    log("=" * 100)
    log("PART 3 — STRATEGY x SYMBOL MATRIS")
    log("=" * 100)
    log("Her hucre: 5y'lik (strategy, symbol) icin: sum_R / n_trade / avg_R / wr")
    log("Ham veri (replay icine girmeden) — sinyal seti bazli.")
    log("")

    # Buckets: (strategy, symbol) -> list[R]
    cell_R = defaultdict(list)
    cell_conf = defaultdict(list)
    for t in all_trades:
        cell_R[(t["strategy"], t["symbol"])].append(t["R"])
        cell_conf[(t["strategy"], t["symbol"])].append(t["conf"])

    # Matris (sum_R)
    log("SUM_R MATRIS (5y boyunca toplam R, dropsuz):")
    log("  Negatif = strateji-sembol kombosu kayipta")
    log("  Yuksek pozitif = en buyuk kazandiranlar")
    log("")
    # Header
    sym_short = [s.replace("/USDT", "") for s in SYMBOLS_11]
    log(f"  {'strategy':<28}" + "".join(f" {s:>7}" for s in sym_short))
    log("  " + "-" * (28 + 8 * 11))
    cell_rows = []
    for strat in STRATEGY_NAMES:
        cells_line = f"  {strat:<28}"
        for sym in SYMBOLS_11:
            rs = cell_R.get((strat, sym), [])
            if rs:
                sumR = sum(rs)
                cells_line += f" {sumR:>+7.1f}"
                cell_rows.append((strat, sym, sumR, len(rs), sumR / len(rs)))
            else:
                cells_line += f" {'.':>7}"
        log(cells_line)
    log("")

    # n_trade matris
    log("N_TRADE MATRIS (5y boyunca trade sayisi):")
    log("")
    log(f"  {'strategy':<28}" + "".join(f" {s:>7}" for s in sym_short))
    log("  " + "-" * (28 + 8 * 11))
    for strat in STRATEGY_NAMES:
        ln = f"  {strat:<28}"
        for sym in SYMBOLS_11:
            rs = cell_R.get((strat, sym), [])
            ln += f" {len(rs):>7d}" if rs else f" {'.':>7}"
        log(ln)
    log("")

    # AVG_R matris
    log("AVG_R MATRIS (trade basina ortalama R):")
    log("")
    log(f"  {'strategy':<28}" + "".join(f" {s:>7}" for s in sym_short))
    log("  " + "-" * (28 + 8 * 11))
    for strat in STRATEGY_NAMES:
        ln = f"  {strat:<28}"
        for sym in SYMBOLS_11:
            rs = cell_R.get((strat, sym), [])
            if rs:
                avgR = sum(rs) / len(rs)
                ln += f" {avgR:>+7.2f}"
            else:
                ln += f" {'.':>7}"
        log(ln)
    log("")

    # =====================================================================
    # PART 4 — EN KOTU 10 HUCRE (worst sum_R, sample size >= 10)
    # =====================================================================
    log("=" * 100)
    log("PART 4 — EN KOTU / EN IYI HUCRELER (min 10 trade)")
    log("=" * 100)
    log("")
    sized = [(s, y, sr, n, av) for s, y, sr, n, av in cell_rows if n >= 10]
    sized_by_sumr = sorted(sized, key=lambda x: x[2])
    log("EN KOTU 15 (sum_R en negatif):")
    log(f"  {'strategy':<28} {'symbol':<12} {'sum_R':>8} {'n':>5} {'avg_R':>8}")
    log("  " + "-" * 65)
    for s, y, sr, n, av in sized_by_sumr[:15]:
        log(f"  {s:<28} {y:<12} {sr:>+8.1f} {n:>5d} {av:>+8.3f}")
    log("")
    log("EN IYI 10 (sum_R en pozitif):")
    log(f"  {'strategy':<28} {'symbol':<12} {'sum_R':>8} {'n':>5} {'avg_R':>8}")
    log("  " + "-" * 65)
    for s, y, sr, n, av in sized_by_sumr[-10:][::-1]:
        log(f"  {s:<28} {y:<12} {sr:>+8.1f} {n:>5d} {av:>+8.3f}")
    log("")

    # =====================================================================
    # PART 5 — CONFIDENCE BUCKET ANALIZI
    # =====================================================================
    log("=" * 100)
    log("PART 5 — CONFIDENCE BUCKET ANALIZI")
    log("=" * 100)
    log("Her bucket'ta: trade sayisi, ortalama R, win rate, sum_R")
    log("")
    buckets = [
        (0.20, 0.30),
        (0.30, 0.40),
        (0.40, 0.50),
        (0.50, 0.60),
        (0.60, 1.01),
    ]
    log(f"  {'bucket':<14} {'n':>6} {'avg_R':>8} {'WR%':>6} {'sum_R':>8} {'pct_total':>10}")
    log("  " + "-" * 55)
    total = len(all_trades)
    for lo, hi in buckets:
        Rs = [t["R"] for t in all_trades if lo <= t["conf"] < hi]
        n = len(Rs)
        if n == 0:
            log(f"  [{lo:.2f},{hi:.2f})    (yok)")
            continue
        sumR = sum(Rs)
        wr = sum(1 for r in Rs if r > 0) / n * 100
        avgR = sumR / n
        log(
            f"  [{lo:.2f},{hi:.2f}) {n:>6d} {avgR:>+8.3f} {wr:>5.1f}% "
            f"{sumR:>+8.1f} {n / total * 100:>8.1f}%"
        )
    log("")

    # Confidence MIN replay sweep (production_replay icinde test edilir)
    log("CONF_MIN SWEEP (rolling 3y, replay icinde):")
    log(f"  {'conf_min':<10} {'ort. yIllIk':>13} {'delta':>9} {'ort. DD':>9} {'ort. n':>8}")
    log("  " + "-" * 60)
    conf_results: dict[float, dict] = {}
    for cm in [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55]:
        cfg = base_cfg.with_overrides(conf_min=cm)
        r = run_rolling(all_trades, windows, cfg)
        if r["n_windows"] == 0:
            log(f"  {cm:<10.2f} (yok)")
            continue
        d_ann = r["mean_ann"] - base["mean_ann"]
        conf_results[cm] = r
        log(
            f"  {cm:<10.2f} {r['mean_ann']:>+11.2f}% {d_ann:>+7.2f}pp"
            f" {r['mean_dd']:>+7.1f}% {r['mean_n']:>6.0f}"
        )
    log("")

    # =====================================================================
    # PART 6 — COMBO TESTLERI
    # =====================================================================
    log("=" * 100)
    log("PART 6 — COMBO TESTLERI (en kotu hucreleri drop + conf sweep)")
    log("=" * 100)
    log("")

    # En kotu N (samp>=10) hucreyi pair olarak drop et
    log("TEST 1 — En kotu 3 hucreyi (strategy, symbol) drop_pairs ile cikar:")
    worst3 = sized_by_sumr[:3]
    pairs3 = frozenset((s, y) for s, y, _, _, _ in worst3)
    for s, y, sr, n, av in worst3:
        log(f"  DROP: {s} x {y} (sum_R={sr:+.1f}, n={n}, avg={av:+.3f})")
    cfg = base_cfg.with_overrides(drop_pairs=pairs3)
    r = run_rolling(all_trades, windows, cfg)
    d_ann_test1 = r["mean_ann"] - base["mean_ann"]
    log(
        f"  Sonuc: ort. yIllIk {r['mean_ann']:+.2f}% (delta {d_ann_test1:+.2f}pp),"
        f" DD {r['mean_dd']:+.1f}% (delta {r['mean_dd'] - base['mean_dd']:+.1f}pp), n={r['mean_n']:.0f}"
    )
    log("")

    log("TEST 2 — En kotu 5 hucreyi drop:")
    worst5 = sized_by_sumr[:5]
    pairs5 = frozenset((s, y) for s, y, _, _, _ in worst5)
    for s, y, sr, n, av in worst5:
        log(f"  DROP: {s} x {y} (sum_R={sr:+.1f}, n={n}, avg={av:+.3f})")
    cfg = base_cfg.with_overrides(drop_pairs=pairs5)
    r = run_rolling(all_trades, windows, cfg)
    d_ann_test2 = r["mean_ann"] - base["mean_ann"]
    log(
        f"  Sonuc: ort. yIllIk {r['mean_ann']:+.2f}% (delta {d_ann_test2:+.2f}pp),"
        f" DD {r['mean_dd']:+.1f}% (delta {r['mean_dd'] - base['mean_dd']:+.1f}pp), n={r['mean_n']:.0f}"
    )
    log("")

    log("TEST 3 — En kotu 10 hucreyi drop:")
    worst10 = sized_by_sumr[:10]
    pairs10 = frozenset((s, y) for s, y, _, _, _ in worst10)
    cfg = base_cfg.with_overrides(drop_pairs=pairs10)
    r = run_rolling(all_trades, windows, cfg)
    d_ann_test3 = r["mean_ann"] - base["mean_ann"]
    log(
        f"  Sonuc: ort. yIllIk {r['mean_ann']:+.2f}% (delta {d_ann_test3:+.2f}pp),"
        f" DD {r['mean_dd']:+.1f}% (delta {r['mean_dd'] - base['mean_dd']:+.1f}pp), n={r['mean_n']:.0f}"
    )
    log("")

    log("TEST 4 — En kotu 5 hucre + conf_min 0.30:")
    cfg = base_cfg.with_overrides(drop_pairs=pairs5, conf_min=0.30)
    r = run_rolling(all_trades, windows, cfg)
    log(
        f"  Sonuc: ort. yIllIk {r['mean_ann']:+.2f}% (delta {r['mean_ann'] - base['mean_ann']:+.2f}pp),"
        f" DD {r['mean_dd']:+.1f}%, n={r['mean_n']:.0f}"
    )
    log("")

    log("TEST 5 — En kotu 10 hucre + conf_min 0.30:")
    cfg = base_cfg.with_overrides(drop_pairs=pairs10, conf_min=0.30)
    r = run_rolling(all_trades, windows, cfg)
    log(
        f"  Sonuc: ort. yIllIk {r['mean_ann']:+.2f}% (delta {r['mean_ann'] - base['mean_ann']:+.2f}pp),"
        f" DD {r['mean_dd']:+.1f}%, n={r['mean_n']:.0f}"
    )
    log("")

    log("TEST 6 — drop_strategy (en zayif strateji per_strat'tan) + en kotu 5 cell:")
    if per_strat_rows:
        worst_strat = max(per_strat_rows, key=lambda x: x[2])  # en yuksek delta_ann (en kayipli)
        sname = worst_strat[0]
        log(f"  Worst-strategy aday: {sname} (delta_ann={worst_strat[2]:+.2f}pp)")
        cfg = base_cfg.with_overrides(
            drop_strategies=frozenset({sname}),
            drop_pairs=pairs5,
        )
        r = run_rolling(all_trades, windows, cfg)
        log(
            f"  Sonuc: ort. yIllIk {r['mean_ann']:+.2f}% (delta {r['mean_ann'] - base['mean_ann']:+.2f}pp),"
            f" DD {r['mean_dd']:+.1f}%, n={r['mean_n']:.0f}"
        )
    log("")

    # =====================================================================
    # PART 7 — BOOTSTRAP CI (variance check)
    # =====================================================================
    log("=" * 100)
    log("PART 7 — BOOTSTRAP CI (variance kontrol)")
    log("=" * 100)
    log("Bootstrap: trade listesinden resample (n=N, replacement) -> 3y rolling tekrar.")
    log("10 resample, baseline icin ann mean dagilim.")
    log("")
    random.seed(RANDOM_SEED)
    boot_anns = []
    for i in range(10):
        sample = random.choices(all_trades, k=len(all_trades))
        sample.sort(key=lambda x: x["entry_ts"])
        w2 = build_rolling_windows(sample)
        r = run_rolling(sample, w2, base_cfg)
        if r["n_windows"] > 0:
            boot_anns.append(r["mean_ann"])
            log(f"  Bootstrap {i + 1:>2}: ort. yIllIk {r['mean_ann']:+.2f}% (n_win={r['n_windows']})")
    if boot_anns:
        log("")
        log(
            f"  BOOTSTRAP OZET: median {median(boot_anns):+.2f}%   "
            f"std {stdev(boot_anns) if len(boot_anns) > 1 else 0:.2f}pp   "
            f"range [{min(boot_anns):+.2f}, {max(boot_anns):+.2f}]"
        )
        # 90% CI estimate (quick: min-max range usually conservative; use percentile)
        sorted_b = sorted(boot_anns)
        log(
            f"  Baseline gercek {base['mean_ann']:+.2f}% — bootstrap range icinde mi? "
            f"({'EVET' if sorted_b[0] <= base['mean_ann'] <= sorted_b[-1] else 'HAYIR (sample bagimli)'})"
        )
    log("")

    # =====================================================================
    # PART 8 — KARARLAR
    # =====================================================================
    log("=" * 100)
    log("PART 8 — KARAR ONERILERI (sayilarla)")
    log("=" * 100)
    log("")

    # Strategy drop adaylari
    log("STRATEGY ablation kararlari (delta_ann > +1.5pp olanlari at):")
    drops_strat = [r for r in per_strat_rows if r[2] > 1.5]
    if drops_strat:
        for s, m_ann, d_ann, m_dd, d_dd, m_n, v in drops_strat:
            log(f"  DROP_STRATEGY: {s}  (delta_ann={d_ann:+.2f}pp, delta_DD={d_dd:+.1f}pp)")
    else:
        log("  (hicbiri esiklik degil — tum stratejiler net pozitif katki)")
    log("")

    log("SYMBOL ablation kararlari (delta_ann > +1.5pp olanlari at):")
    drops_sym = [r for r in per_sym_rows if r[2] > 1.5]
    if drops_sym:
        for s, m_ann, d_ann, m_dd, d_dd, m_n, v in drops_sym:
            log(f"  DROP_SYMBOL: {s}  (delta_ann={d_ann:+.2f}pp, delta_DD={d_dd:+.1f}pp)")
    else:
        log("  (hicbir sembol kayipta degil)")
    log("")

    log("EN KOTU 5 (strategy, symbol) HUCRE — drop kararlari (sample >= 10, sum_R cok negatif):")
    for s, y, sr, n, av in sized_by_sumr[:5]:
        log(f"  DROP_PAIR: ({s}, {y})  sum_R={sr:+.1f}, n={n}, avg_R={av:+.3f}")
    log("")

    log("CONF_MIN onerisi:")
    # En yuksek mean_ann conf
    if conf_results:
        best_cm = max(conf_results.items(), key=lambda kv: kv[1]["mean_ann"])
        log(
            f"  En iyi conf_min: {best_cm[0]:.2f} (ort. yIllIk {best_cm[1]['mean_ann']:+.2f}%,"
            f" delta vs 0.20 = {best_cm[1]['mean_ann'] - base['mean_ann']:+.2f}pp)"
        )
    log("")

    log("=" * 100)
    log(f"BITIS — toplam sure: {time.time() - t0:.1f}s")
    log("=" * 100)

    # =====================================================================
    # Output
    # =====================================================================
    out_path = ROOT / "reports" / "v095_ablation_matrix.txt"
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n[OK] Yazildi: {out_path}")

    # Memory note icin yapi dondur
    return {
        "baseline": base,
        "per_strat": per_strat_rows,
        "per_sym": per_sym_rows,
        "worst_cells": sized_by_sumr[:10],
        "best_cells": sized_by_sumr[-10:][::-1],
        "conf_buckets": conf_results,
        "combo_test1_pairs3_delta": d_ann_test1,
        "combo_test2_pairs5_delta": d_ann_test2,
        "combo_test3_pairs10_delta": d_ann_test3,
        "bootstrap": boot_anns if boot_anns else [],
    }


if __name__ == "__main__":
    main()
