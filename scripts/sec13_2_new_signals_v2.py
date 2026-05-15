"""Sec13.2 — Yeni signal source survey v2.

Aday stratejiler:
  1) naked_poc_mr           (1d, mevcut zaten implementli, Sec4 POZITIF)
  2) engulfing_continuation_4h (4h cache, sec11e variant)
  3) volume_expansion       (1d, YENI implement — 60-bar median * 1.5)

Karsilastirma:
  CHAMPION:    TOP_11 (TOP_10 + fvg_fill_reversal) — v1.3 prod
  CHALLENGERS: TOP_11 + her bir yeni signal (3'lu test) ve TOP_15 (4'lu kombine)

Risk config: configs/risk_balanced.yaml (v1.3, monthly_dd=0.06+halt=21, tp2_R=1.5).
Ek deney: max_concurrent=8 (default) ve max_concurrent=12 (slot freedom).

Edge gates:
  Standalone: mR > +0.10, n > 50, WR > 35%
  Ensemble  : Yillik delta > +2pp vs CHAMPION, DD tolerans +5pp, 0/13 negatif, r-adj >= 1.5
"""
from __future__ import annotations

import os
import pickle
import sys
from pathlib import Path
from statistics import mean, median

os.environ.setdefault("PA_LOG_QUIET", "1")

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from price_action.backtest.lab import (
    ProductionConfig, production_replay, _lazy_build_funding_filters,
)
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.v09_optimize_top10 import _gather, TOP_10
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip
from scripts.sec13_2_gather_helpers import gather_4h, summary

REPORT_OUT = ROOT / "reports" / "lab" / "sec13_2_new_signals_v2.md"
CACHE_PATH = ROOT / "reports" / "lab" / "sec13_2_new_trades.pkl"


def _try_load_cache() -> dict | None:
    if CACHE_PATH.exists():
        try:
            with open(CACHE_PATH, "rb") as f:
                d = pickle.load(f)
            print(f"[cache] loaded {len(d)} strats from {CACHE_PATH}")
            return d
        except Exception:
            return None
    return None


def main() -> None:
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out_lines: list[str] = []

    def w(line: str = "") -> None:
        print(line)
        out_lines.append(line)

    w("# Sec13.2 — Yeni Signal Source Survey v2 (2026-05-13)")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w("")
    w("**Hedef:** TOP_11 (v1.3 prod, +%60.16/-%33.38/r-adj 1.802) ustune uncorrelated edge ekle.")
    w("**Adaylar:** naked_poc_mr (1d) + engulfing_continuation_4h (4h cache) + volume_expansion (1d, YENI).")
    w("")

    # 1) Yeni strateji trade gather (cache var, kullan)
    cached = _try_load_cache()
    new_trades_by_strat = cached or {}

    if "naked_poc_mr" not in new_trades_by_strat:
        print("\n[gather] naked_poc_mr (1d)...")
        new_trades_by_strat["naked_poc_mr"] = _gather(
            "naked_poc_mr", "NakedPOCMeanReversionStrategy"
        )
    if "volume_expansion" not in new_trades_by_strat:
        print("\n[gather] volume_expansion (1d, YENI)...")
        new_trades_by_strat["volume_expansion"] = _gather(
            "volume_expansion", "VolumeExpansionStrategy"
        )
    if "engulfing_continuation_4h" not in new_trades_by_strat:
        print("\n[gather] engulfing_continuation_4h (4h cache)...")
        new_trades_by_strat["engulfing_continuation_4h"] = gather_4h(
            "engulfing_continuation_4h", "EngulfingContinuation4HStrategy"
        )

    # Cache yaz
    with open(CACHE_PATH, "wb") as f:
        pickle.dump(new_trades_by_strat, f)
    print(f"[cache] saved -> {CACHE_PATH}")

    # FVG cache (sec11e'den)
    pkl_old = ROOT / "reports" / "lab" / "sec11e_new_trades.pkl"
    fvg = []
    if pkl_old.exists():
        with open(pkl_old, "rb") as f:
            d = pickle.load(f)
        fvg = d.get("fvg_fill_reversal", [])
    print(f"[cache] FVG trades from sec11e: {len(fvg)}")

    npoc = new_trades_by_strat["naked_poc_mr"]
    em4h = new_trades_by_strat["engulfing_continuation_4h"]
    volx = new_trades_by_strat["volume_expansion"]

    # ========== 2) STANDALONE EDGE TABLE ==========
    w("## Standalone Edge (5y, 11 sym, no risk overlay)")
    w("")
    w("Edge gate: mR > +0.10, n > 50, WR > 35%")
    w("")
    w("| Strategy | n | mR | sumR | WR | long/short | Edge |")
    w("|---|---:|---:|---:|---:|---:|---|")
    for nm, ts in [
        ("naked_poc_mr", npoc),
        ("engulfing_continuation_4h", em4h),
        ("volume_expansion", volx),
    ]:
        s = summary(ts, nm)
        passes = s["mR"] > 0.10 and s["n"] > 50 and s["WR"] > 0.35
        verdict = "PASS" if passes else "FAIL"
        w(f"| {nm} | {s['n']} | {s['mR']:+.3f} | {s['sumR']:+.1f} | {s['WR']*100:.1f}% | "
          f"{s['n_long']}/{s['n_short']} | **{verdict}** |")
    w("")

    # ========== 3) TOP_10 + FVG (TOP_11) trade pool yarat ==========
    print("\n[gather] TOP_10 trades...")
    top10_trades = []
    for m, c in TOP_10:
        ts = _gather(m, c)
        top10_trades.extend(ts)
    top11_trades = sorted(top10_trades + fvg, key=lambda x: x["entry_ts"])
    print(f"TOP_11 trade pool: {len(top11_trades)}")

    # CHALLENGERS — pozitif olanlari TOP_11'e ekle
    challengers = [
        ("CHAMPION (TOP_11)", top11_trades),
        ("TOP_11 + naked_poc_mr",        sorted(top11_trades + npoc, key=lambda x: x["entry_ts"])),
        ("TOP_11 + engulfing_4h",        sorted(top11_trades + em4h, key=lambda x: x["entry_ts"])),
        ("TOP_11 + volume_expansion",    sorted(top11_trades + volx, key=lambda x: x["entry_ts"])),
        ("TOP_11 + npoc + volx",         sorted(top11_trades + npoc + volx, key=lambda x: x["entry_ts"])),
        ("TOP_15 (TOP_11 + 3 yeni)",     sorted(top11_trades + npoc + em4h + volx, key=lambda x: x["entry_ts"])),
    ]

    # ========== 4) Filter calendars (v1.3 prod ile parite) ==========
    print("\n[filters] BTC halt + funding + F&G short-skip...")
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": True,
        "funding_aggregation_mode": "00:00_only",
    })
    fng_short_20 = build_fng_short_skip(20)
    fund_short_dict = dict(fund_short or {})
    fng_short_dict = dict(fng_short_20)
    combined_short_skip = {**fund_short_dict, **fng_short_dict}

    # ========== 5) Walk-forward windows ==========
    base_trades = challengers[-1][1]  # TOP_15 — en genis pool
    start = base_trades[0]["entry_ts"]
    end = base_trades[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)
    print(f"\nWalk-forward pencere: {len(windows)} (3y rolling, 60g step)")

    base_bal = ProductionConfig.from_yaml("configs/risk_balanced.yaml")
    # NOT: from_yaml zaten F&G short-skip + halt + risk %4 yukluyor.
    # Override yapmiyoruz (v1.3 prod parite). Yalnizca max_concurrent degistiriyoruz.

    def run_scenario(trades, max_conc):
        cfg = base_bal.with_overrides(max_concurrent=max_conc)
        anns, dds, n_trades = [], [], []
        for ws, we in windows:
            ww_trades = [t for t in trades if ws <= t["entry_ts"] < we]
            r = production_replay(ww_trades, cfg)
            if r is None:
                continue
            anns.append(r.annualized(3.0) * 100)
            dds.append(r.max_drawdown * 100)
            n_trades.append(int(r.trades) if r.trades else 0)
        if not anns:
            return None
        return {
            "ann": mean(anns), "med": median(anns),
            "min": min(anns), "max": max(anns),
            "dd": mean(dds), "neg": sum(1 for a in anns if a < 0),
            "trades": mean(n_trades) if n_trades else 0,
            "anns": anns, "dds": dds,
        }

    # Ek deney: concentration ve cooldown'i gevsetince yeni signal'ler eklenebilir mi?
    # max_conc 8/12 default; 16 = full slot freedom + concentration_off variant
    for max_conc in [8, 12, 16]:
        w(f"## Walk-Forward (3y rolling, {len(windows)} pencere) — max_concurrent={max_conc}")
        w("")
        w(f"| Senaryo | Yillik | Median | Min | Max | DD | r-adj | Negatif | Avg Trades |")
        w(f"|---|---:|---:|---:|---:|---:|---:|---:|---:|")

        rated = []
        print(f"\n=== max_concurrent={max_conc} ===")
        for name, trades in challengers:
            res = run_scenario(trades, max_conc)
            if res is None:
                continue
            r_adj = res["ann"] / abs(res["dd"]) if res["dd"] != 0 else 0
            rated.append((name, res, r_adj))
            print(f"  {name:<35}  {res['ann']:>+6.1f}%  med {res['med']:>+5.1f}%  "
                  f"min {res['min']:>+5.1f}%  max {res['max']:>+5.1f}%  DD {res['dd']:>+5.1f}%  "
                  f"r-adj {r_adj:.3f}  neg {res['neg']}  n {res['trades']:.0f}")
            w(f"| {name} | {res['ann']:+.1f}% | {res['med']:+.1f}% | "
              f"{res['min']:+.1f}% | {res['max']:+.1f}% | {res['dd']:+.1f}% | "
              f"{r_adj:.3f} | {res['neg']} | {res['trades']:.0f} |")
        w("")

        # Karar tablosu
        if rated:
            champ = rated[0]
            w(f"### Karar (max_concurrent={max_conc}) — vs CHAMPION ({champ[1]['ann']:+.1f}%/-{abs(champ[1]['dd']):.1f}%/r-adj {champ[2]:.3f})")
            w("")
            for nm, res, ra in rated[1:]:
                d_ann = res["ann"] - champ[1]["ann"]
                d_dd = res["dd"] - champ[1]["dd"]
                d_ra = ra - champ[2]
                # Statistical gates (yillik delta>+2pp, DD tolerans +5pp, neg=0, r-adj>=1.5)
                gates = {
                    "ann_delta": d_ann > 2.0,
                    "dd_tolerance": d_dd > -5.0,
                    "neg_zero": res["neg"] == 0,
                    "r_adj_15": ra >= 1.5,
                }
                pass_count = sum(gates.values())
                if pass_count == 4 and d_ann > 0:
                    verdict = "TOURNAMENT WINNER"
                elif d_ra > 0 and d_ann > 0:
                    verdict = "MARGINAL POSITIVE"
                elif d_ann > 0 and d_dd > -3.0:
                    verdict = "RETURN UP, RISK FLAT"
                else:
                    verdict = "REJECT"
                gate_str = " ".join(["+" if v else "-" for v in gates.values()])
                w(f"- **{nm}**: dYillik {d_ann:+.1f}pp, dDD {d_dd:+.1f}pp, dR-adj {d_ra:+.3f} | gates [{gate_str}] -> **{verdict}**")
            w("")

    # ========== 6) Reproducibility ==========
    w("## Reproducibility")
    w("")
    w(f"- TOP_10 trades: {len(top10_trades)}")
    w(f"- FVG (sec11e cache): {len(fvg)}")
    w(f"- TOP_11 pool: {len(top11_trades)}")
    w(f"- naked_poc_mr: {len(npoc)}")
    w(f"- engulfing_continuation_4h: {len(em4h)} (data/mtf_4h_cache.pkl)")
    w(f"- volume_expansion: {len(volx)} (YENI strateji)")
    w(f"- Drop pairs (v0.9.7): {len(DROP_PAIRS)}")
    w(f"- Funding short-skip: {len(fund_short or {})}")
    w(f"- F&G short-skip (<=20): {len(fng_short_20)}")
    w(f"- Walk-forward pencere: {len(windows)} (3y rolling, 60g step)")
    w(f"- Risk config: configs/risk_balanced.yaml (v1.3 prod)")
    w(f"- monthly_dd={base_bal.monthly_dd}, halt_days={base_bal.monthly_halt_days}")

    REPORT_OUT.write_text("\n".join(out_lines), encoding="utf-8")
    print(f"\nReport written -> {REPORT_OUT}")


if __name__ == "__main__":
    main()
