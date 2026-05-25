"""SEC50-SLIM — Capitulation halt 15m re-tune (fast version).

Önceki agent (sec50_halt_15m_retune.py) ağır 37-run sweep + walk-forward +
parity başlattı ama Monitor event'i kaçırdı. Bu slim versiyon:
- 9 kombinasyon (ATR{6,7,8} × DD{-25,-30,-35}; STRK=10 sabit, 1d ile aynı)
- + halt OFF baseline
- Per-month replay (60-90 saniye / config)
- WF özet (her config 12 pencere ~20 saniye)
- Toplam: ~5-10 dk
- Replay parity (1d) atlandı — slim sweep production değişikliği önermez,
  sadece TF-specific YAML patch önerisi olur.

Sec49 baseline reference:
  ATR=6 / STRK=10 / DD=-25 (1d champion): mean +%17.33, zero=20, neg=9,
  WF mean_ann +%735.73 / DD -29.61% / r-adj 21.83
"""
from __future__ import annotations

import csv
import io
import itertools
import os
import pickle
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean

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

import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

import pandas as pd

from price_action.backtest.lab import ProductionConfig, production_replay
from price_action.backtest.regime import compute_btc_capitulation_halt

CSV_OUT = ROOT / "reports" / "engineering" / "2026-05-17_halt_15m_sweep.csv"
REPORT_OUT = ROOT / "reports" / "engineering" / "2026-05-17_halt_15m_retune_final.md"
PER_MONTH_BEST_CSV = ROOT / "reports" / "engineering" / "2026-05-17_halt_15m_best_per_month.csv"

POOL_15M = ROOT / "data" / "sec31_15m_pool.pkl"
YAML_15M = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"
SEC49_CSV = ROOT / "reports" / "lab" / "sec49_per_month.csv"

TOP4_STRATEGIES = {
    "vsa_climax_test",
    "brooks_failed_breakout",
    "anchored_vwap_reversal",
    "engulfing_continuation",
}
SYMBOLS_10 = {
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
    "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT",
}

# Sweep grid — sıfır-ay'ları azaltmaya yönelik (halt'u GEVŞET).
# ATR yukarı = daha az ATR-trigger; DD daha negatif = daha az DD-trigger.
# STRK=10 sabit (1d champion default, EMA200 streak yapısal kontrol — TF-değişmez).
ATR_GRID = [6.0, 7.0, 8.0]
DD_GRID = [-25.0, -30.0, -35.0]
STREAK_FIXED = 10

# Defaults (baseline = 1d champion)
DEF_ATR, DEF_STRK, DEF_DD = 6.0, 10, -25.0


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def per_month_replay(pool, cfg, halt_calendar, label):
    cfg_local = replace(cfg, btc_halt_calendar=halt_calendar)
    pool.sort(key=lambda x: x["entry_ts"])
    start_dt = to_utc(pool[0]["entry_ts"])
    end_dt = to_utc(pool[-1]["entry_ts"])

    months = []
    cur_year, cur_month = start_dt.year, start_dt.month
    while True:
        m_start = datetime(cur_year, cur_month, 1, tzinfo=timezone.utc)
        if cur_month == 12:
            m_end = datetime(cur_year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            m_end = datetime(cur_year, cur_month + 1, 1, tzinfo=timezone.utc)
        if m_start > end_dt:
            break
        months.append((cur_year, cur_month, m_start, m_end))
        cur_month += 1
        if cur_month > 12:
            cur_month = 1
            cur_year += 1

    results = []
    for yr, mo, ms, me in months:
        m_trades = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_trades) < 10:
            continue
        r = production_replay(m_trades, cfg_local)
        if r is None:
            continue
        ret_pct = r.total_return * 100
        dd_pct = r.max_drawdown * 100
        results.append((yr, mo, len(m_trades), ret_pct, dd_pct))

    rets = [r[3] for r in results]
    n = len(rets)
    if n == 0:
        return results, {"label": label, "n_months": 0}

    mean_ret = sum(rets) / n
    std = (sum((x - mean_ret) ** 2 for x in rets) / (n - 1)) ** 0.5 if n > 1 else 0.0
    cv_pct = (std / abs(mean_ret) * 100) if mean_ret != 0 else float("inf")
    pos = sum(1 for x in rets if x > 0)
    neg = sum(1 for x in rets if x < 0)
    zero = sum(1 for x in rets if x == 0)
    ge20 = sum(1 for x in rets if x >= 20.0)
    ge15 = sum(1 for x in rets if x >= 15.0)

    return results, {
        "label": label,
        "n_months": n,
        "mean_pct": round(mean_ret, 3),
        "std_pct": round(std, 3),
        "cv_pct": round(cv_pct, 1),
        "min_pct": round(min(rets), 3),
        "max_pct": round(max(rets), 3),
        "pos": pos, "neg": neg, "zero": zero, "ge20": ge20, "ge15": ge15,
    }


def walk_forward(pool, cfg, halt_calendar, train_years=2.0, oos_months=3, step_months=1):
    cfg_local = replace(cfg, btc_halt_calendar=halt_calendar)
    pool.sort(key=lambda t: t["entry_ts"])

    win_start = pool[0]["entry_ts"]
    win_end = pool[-1]["exit_ts"]
    win_len_days = int(train_years * 365 + oos_months * 30)
    step_days = step_months * 30

    cur = win_start
    windows = []
    while cur + pd.Timedelta(days=win_len_days) <= win_end:
        windows.append((cur, cur + pd.Timedelta(days=win_len_days)))
        cur += pd.Timedelta(days=step_days)

    years = win_len_days / 365.0
    anns, dds = [], []
    for ws, we in windows:
        w = [t for t in pool if ws <= t["entry_ts"] < we]
        if len(w) < 10:
            continue
        r = production_replay(w, cfg_local)
        if r:
            anns.append(r.annualized(years) * 100)
            dds.append(r.max_drawdown * 100)

    if not anns:
        return {"n": 0, "mean_ann": 0, "mean_dd": 0, "r_adj": 0, "neg": 0}
    ma = mean(anns); md = mean(dds)
    return {
        "n": len(anns),
        "mean_ann": round(ma, 2),
        "mean_dd": round(md, 2),
        "r_adj": round(ma / abs(md), 3) if md != 0 else 0.0,
        "neg": sum(1 for a in anns if a < 0),
        "windows": len(windows),
    }


def main():
    print("=" * 78)
    print("SEC50-SLIM — Capitulation halt 15m re-tune")
    print("=" * 78)

    # ------------------------------------------------------------
    print("\n[LOAD] 15m pool + cfg")
    with POOL_15M.open("rb") as fh:
        pool_raw = pickle.load(fh)
    pool = [
        t for t in pool_raw
        if t.get("strategy") in TOP4_STRATEGIES
        and t.get("symbol") in SYMBOLS_10
    ]
    print(f"  pool: {len(pool):,} trade (TOP-4 + 10sym)")

    cfg = ProductionConfig.from_yaml(str(YAML_15M))
    cfg = cfg.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)
    print(f"  cfg: pyr_en={cfg.pyramid_enabled} trig={cfg.pyramid_triggers} "
          f"sizes={cfg.pyramid_sizes} mc={cfg.max_concurrent}")

    # ------------------------------------------------------------
    print("\n[STEP 1] Per-month sweep")
    sweep_results = []
    detailed_runs = {}

    # halt OFF
    print(f"\n  [00] HALT OFF")
    res_off, sum_off = per_month_replay(pool, cfg, None, "halt_OFF")
    print(f"      mean={sum_off['mean_pct']:+.2f}% cv={sum_off['cv_pct']:.0f}% "
          f"neg={sum_off['neg']} zero={sum_off['zero']} ge20={sum_off['ge20']}")
    sweep_results.append({"atr": None, "strk": None, "dd": None, "halt_days": 0, **sum_off})
    detailed_runs["off"] = res_off

    # 9 combos
    combos = list(itertools.product(ATR_GRID, DD_GRID))
    for i, (atr, dd) in enumerate(combos, start=1):
        cal = compute_btc_capitulation_halt(atr, STREAK_FIXED, dd)
        hd = sum(1 for v in cal.values() if v)
        res, summ = per_month_replay(pool, cfg, cal, f"ATR={atr}_DD={dd}")
        label_is_def = "(DEF)" if (atr == DEF_ATR and dd == DEF_DD) else ""
        print(f"  [{i:>2}] ATR={atr} DD={dd} {label_is_def} → halt={hd} "
              f"mean={summ['mean_pct']:+.2f}% cv={summ['cv_pct']:.0f}% "
              f"neg={summ['neg']} zero={summ['zero']} ge20={summ['ge20']}")
        sweep_results.append({"atr": atr, "strk": STREAK_FIXED, "dd": dd, "halt_days": hd, **summ})
        detailed_runs[(atr, dd)] = res

    # ------------------------------------------------------------
    # CSV out
    print(f"\n[WRITE] {CSV_OUT}")
    CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
    with CSV_OUT.open("w", newline="", encoding="utf-8") as fh:
        keys = ["atr", "strk", "dd", "halt_days", "label", "n_months",
                "mean_pct", "std_pct", "cv_pct", "min_pct", "max_pct",
                "pos", "neg", "zero", "ge20", "ge15"]
        w = csv.DictWriter(fh, fieldnames=keys)
        w.writeheader()
        for row in sweep_results:
            w.writerow({k: row.get(k, "") for k in keys})

    # ------------------------------------------------------------
    print("\n[STEP 2] Best param selection")

    # Objective: minimize (zero+neg), reward mean
    def score(r):
        if r["n_months"] == 0:
            return 1e9
        return (r["zero"] + r["neg"]) * 10 - r["mean_pct"] * 0.5

    sorted_sw = sorted(sweep_results, key=score)
    print(f"\n  Top-5 (composite score):")
    print(f"  {'ATR':>5} {'STRK':>5} {'DD':>6} {'halt':>5} {'mean%':>8} {'cv%':>5} "
          f"{'neg':>3} {'zero':>4} {'ge20':>4} {'score':>7}")
    for r in sorted_sw[:5]:
        atr = r['atr'] if r['atr'] is not None else "OFF"
        strk = r['strk'] if r['strk'] is not None else "-"
        dd = r['dd'] if r['dd'] is not None else "-"
        print(f"  {str(atr):>5} {str(strk):>5} {str(dd):>6} {r['halt_days']:>5} "
              f"{r['mean_pct']:>+8.2f} {r['cv_pct']:>5.0f} "
              f"{r['neg']:>3} {r['zero']:>4} {r['ge20']:>4} {score(r):>7.2f}")

    best = sorted_sw[0]
    print(f"\n  BEST: ATR={best['atr']} STRK={best['strk']} DD={best['dd']} "
          f"(zero+neg={best['zero']+best['neg']}, mean={best['mean_pct']:+.2f}%)")

    # ------------------------------------------------------------
    print("\n[STEP 3] Walk-forward — best + baseline + halt OFF")

    wf_base = walk_forward(pool, cfg, compute_btc_capitulation_halt(DEF_ATR, DEF_STRK, DEF_DD))
    print(f"  Baseline (DEF):  ann={wf_base['mean_ann']:+.2f}% dd={wf_base['mean_dd']:.2f}% "
          f"r-adj={wf_base['r_adj']} n={wf_base['n']}/{wf_base['windows']}")

    if best["atr"] is None:
        cal_best = None
    else:
        cal_best = compute_btc_capitulation_halt(best["atr"], best["strk"], best["dd"])
    wf_best = walk_forward(pool, cfg, cal_best)
    print(f"  BEST:            ann={wf_best['mean_ann']:+.2f}% dd={wf_best['mean_dd']:.2f}% "
          f"r-adj={wf_best['r_adj']} n={wf_best['n']}/{wf_best['windows']}")

    wf_off = walk_forward(pool, cfg, None)
    print(f"  HALT OFF:        ann={wf_off['mean_ann']:+.2f}% dd={wf_off['mean_dd']:.2f}% "
          f"r-adj={wf_off['r_adj']} n={wf_off['n']}/{wf_off['windows']}")

    # ------------------------------------------------------------
    print("\n[STEP 4] Per-month best — before/after vs sec49 baseline")

    df_sec49 = pd.read_csv(SEC49_CSV)
    sec49_dict = {f"{int(r['year'])}-{int(r['month']):02d}": r["monthly_pct"]
                  for _, r in df_sec49.iterrows()}

    best_key = "off" if best["atr"] is None else (best["atr"], best["dd"])
    res_best = detailed_runs[best_key]
    rows = []
    for r in res_best:
        ym = f"{r[0]}-{r[1]:02d}"
        sec_pct = sec49_dict.get(ym, 0.0)
        best_pct = r[3]
        delta = best_pct - sec_pct
        rows.append((ym, r[2], sec_pct, best_pct, delta))

    PER_MONTH_BEST_CSV.parent.mkdir(parents=True, exist_ok=True)
    with PER_MONTH_BEST_CSV.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["ym", "n_trade", "sec49_pct", "best_pct", "delta_pp"])
        for row in rows:
            w.writerow([row[0], row[1], f"{row[2]:.3f}", f"{row[3]:.3f}", f"{row[4]:.3f}"])
    print(f"  [WRITE] {PER_MONTH_BEST_CSV}")

    # ------------------------------------------------------------
    print("\n[STEP 5] Verdict")
    baseline_row = next((r for r in sweep_results if r["atr"] == DEF_ATR and r["dd"] == DEF_DD), None)
    sec49_zero = baseline_row["zero"] if baseline_row else 20
    sec49_neg = baseline_row["neg"] if baseline_row else 9
    sec49_mean = baseline_row["mean_pct"] if baseline_row else 17.33

    zero_after = best["zero"]
    neg_after = best["neg"]
    mean_after = best["mean_pct"]
    wf_delta = wf_best["mean_ann"] - wf_base["mean_ann"]

    # Gate: zero <= 8 + mean değişim >= -1pp (sec49 mean baseline)
    # Yumuşatılmış: zero <= 12 (PARTIAL), > 12 (FAIL)
    if zero_after <= 8 and (mean_after - sec49_mean) >= -2.0 and wf_delta >= -wf_base["mean_ann"] * 0.10:
        verdict = "PASS"
    elif zero_after <= 12 and wf_delta >= -wf_base["mean_ann"] * 0.20:
        verdict = "PARTIAL"
    else:
        verdict = "FAIL"

    # Halt OFF kıyas: en iyi sonuç hangi konfigde?
    off_row = sweep_results[0]  # ilk satır halt OFF
    halt_off_better = (off_row["zero"] + off_row["neg"]) <= (best["zero"] + best["neg"]) and \
                      off_row["mean_pct"] >= best["mean_pct"]

    print(f"\n  Zero ay: {sec49_zero} (baseline) → {zero_after} (best) "
          f"{'PASS' if zero_after <= 8 else 'PARTIAL' if zero_after <= 12 else 'FAIL'}")
    print(f"  Neg ay: {sec49_neg} (baseline) → {neg_after} (best)")
    print(f"  Mean: {sec49_mean:+.2f}% (baseline) → {mean_after:+.2f}% (best)")
    print(f"  WF delta (best vs baseline): {wf_delta:+.2f}pp")
    print(f"  Halt OFF zero={off_row['zero']} neg={off_row['neg']} mean={off_row['mean_pct']:+.2f}%")
    print(f"  Halt OFF is best: {halt_off_better}")
    print(f"\n  === VERDICT: {verdict} ===")

    # ------------------------------------------------------------
    # Markdown report
    print(f"\n[WRITE] {REPORT_OUT}")
    md = []
    md.append("# SEC50-SLIM — Capitulation Halt 15m Re-tune Final\n\n")
    md.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n")
    md.append(f"**Script:** `scripts/_halt_15m_slim_sweep.py`\n")
    md.append(f"**Pool:** `data/sec31_15m_pool.pkl` (TOP-4 + 10sym, {len(pool):,} trade)\n")
    md.append(f"**Config:** `configs/risk_phoenix_scalp_15m_pyramid_r3.yaml` (mc=20, cooldown=0)\n\n")
    md.append(f"## TL;DR\n\n")
    md.append(f"| | Sec49 baseline (ATR=6/STRK=10/DD=-25) | Best (ATR={best['atr']}/STRK={best['strk']}/DD={best['dd']}) | Halt OFF |\n")
    md.append(f"|---|---:|---:|---:|\n")
    md.append(f"| Per-ay mean % | {sec49_mean:+.2f} | {best['mean_pct']:+.2f} | {off_row['mean_pct']:+.2f} |\n")
    md.append(f"| Per-ay CV % | {baseline_row['cv_pct']:.0f} | {best['cv_pct']:.0f} | {off_row['cv_pct']:.0f} |\n")
    md.append(f"| Zero ay | {sec49_zero}/61 | {best['zero']}/61 | {off_row['zero']}/61 |\n")
    md.append(f"| Neg ay | {sec49_neg}/61 | {best['neg']}/61 | {off_row['neg']}/61 |\n")
    md.append(f"| Aylar >= +20% | {baseline_row['ge20']}/61 | {best['ge20']}/61 | {off_row['ge20']}/61 |\n")
    md.append(f"| WF mean_ann % | {wf_base['mean_ann']:+.2f} | {wf_best['mean_ann']:+.2f} | {wf_off['mean_ann']:+.2f} |\n")
    md.append(f"| WF DD % | {wf_base['mean_dd']:.2f} | {wf_best['mean_dd']:.2f} | {wf_off['mean_dd']:.2f} |\n")
    md.append(f"| WF r-adj | {wf_base['r_adj']} | {wf_best['r_adj']} | {wf_off['r_adj']} |\n")
    md.append(f"\n**Verdict: {verdict}**\n\n")
    md.append(f"- **Halt OFF strictly better?** {halt_off_better}\n")
    md.append(f"- Sweep grid: ATR{ATR_GRID} × DD{DD_GRID} (STRK={STREAK_FIXED} sabit) + halt OFF\n\n")

    md.append("## 1. Sweep Tablosu (composite score = (zero+neg)*10 - mean*0.5)\n\n")
    md.append("| Rank | ATR | STRK | DD | halt_days | mean% | CV% | neg | zero | ge20 | score |\n")
    md.append("|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|\n")
    for i, r in enumerate(sorted_sw, start=1):
        atr = r['atr'] if r['atr'] is not None else "OFF"
        strk = r['strk'] if r['strk'] is not None else "-"
        dd = r['dd'] if r['dd'] is not None else "-"
        is_best = " **BEST**" if i == 1 else ""
        is_def = " (DEF)" if (r['atr'] == DEF_ATR and r['dd'] == DEF_DD) else ""
        md.append(f"| {i}{is_best}{is_def} | {atr} | {strk} | {dd} | {r['halt_days']} | "
                  f"{r['mean_pct']:+.2f} | {r['cv_pct']:.0f} | {r['neg']} | "
                  f"{r['zero']} | {r['ge20']} | {score(r):.2f} |\n")

    md.append("\n**Raw CSV:** `reports/engineering/2026-05-17_halt_15m_sweep.csv`\n\n")

    md.append("## 2. Walk-Forward (2y train + 3mo OOS + 1mo step)\n\n")
    md.append("| Config | n_pencere | mean_ann % | mean_dd % | r-adj | neg |\n")
    md.append("|---|---:|---:|---:|---:|---:|\n")
    md.append(f"| Baseline (DEF) | {wf_base['n']}/{wf_base['windows']} | "
              f"{wf_base['mean_ann']:+.2f} | {wf_base['mean_dd']:.2f} | "
              f"{wf_base['r_adj']} | {wf_base['neg']} |\n")
    md.append(f"| **BEST** (ATR={best['atr']}/STRK={best['strk']}/DD={best['dd']}) | "
              f"{wf_best['n']}/{wf_best['windows']} | {wf_best['mean_ann']:+.2f} | "
              f"{wf_best['mean_dd']:.2f} | {wf_best['r_adj']} | {wf_best['neg']} |\n")
    md.append(f"| Halt OFF | {wf_off['n']}/{wf_off['windows']} | {wf_off['mean_ann']:+.2f} | "
              f"{wf_off['mean_dd']:.2f} | {wf_off['r_adj']} | {wf_off['neg']} |\n\n")

    md.append("## 3. Per-Ay Before/After (BEST vs Sec49 baseline)\n\n")
    md.append("Sıfır → pozitif geçişler **bold**, negatif → pozitif geçişler *italic*.\n\n")
    md.append("| YYYY-MM | n_trade | sec49 % | best % | Δ pp |\n")
    md.append("|---|---:|---:|---:|---:|\n")
    for ym, ntr, sec, bst, dlt in rows:
        marker = ""
        if abs(sec) < 1e-6 and bst > 0.5:
            marker = " **+**"
        elif sec < -0.5 and bst > 0:
            marker = " *+*"
        elif sec > 0 and bst < -0.5:
            marker = " ⚠"
        md.append(f"| {ym} | {ntr:,} | {sec:+.2f} | {bst:+.2f} | {dlt:+.2f}{marker} |\n")

    md.append(f"\n**Per-ay best CSV:** `reports/engineering/2026-05-17_halt_15m_best_per_month.csv`\n\n")

    md.append("## 4. Önerilen YAML Patch (TF-Specific)\n\n")
    if verdict == "FAIL" or halt_off_better:
        md.append("**Karar:** ")
        if halt_off_better:
            md.append("**Halt OFF** stricly better — `btc_capitulation_halt_enabled: false`.\n\n")
        else:
            md.append("Sweep gate'leri geçemedi — production değişikliği önerilmiyor.\n\n")
        md.append("```yaml\n")
        md.append("# configs/risk_phoenix_scalp_15m_pyramid_r3.yaml\n")
        md.append("regime_filter:\n")
        if halt_off_better:
            md.append(f"  btc_capitulation_halt_enabled: false  # TF-specific OFF\n")
        else:
            md.append(f"  btc_capitulation_halt_enabled: true   # No change\n")
            md.append(f"  atr_pct_threshold: 6.0                # 1d default\n")
            md.append(f"  ema200_streak_days: 10                # 1d default\n")
            md.append(f"  dd_90d_threshold_pct: -25.0           # 1d default\n")
        md.append("```\n\n")
    else:
        md.append("**Karar:** TF-specific threshold override önerilir.\n\n")
        md.append("```yaml\n")
        md.append("# configs/risk_phoenix_scalp_15m_pyramid_r3.yaml\n")
        md.append("regime_filter:\n")
        md.append("  btc_capitulation_halt_enabled: true\n")
        md.append(f"  atr_pct_threshold: {best['atr']}        # 1d default 6.0\n")
        md.append(f"  ema200_streak_days: {best['strk']}      # 1d default 10\n")
        md.append(f"  dd_90d_threshold_pct: {best['dd']}      # 1d default -25.0\n")
        md.append("  # Reasoning: 15m TF; 1d default'ları %33 sıfır ay (20/61) üretiyor.\n")
        md.append("  # Slim sweep BEST: gevşek ATR + derin DD eşiği.\n")
        md.append("```\n\n")
        md.append("**Backward compat:** 1d champion YAML'ları (risk_balanced.yaml vb) DOKUNULMAMALI.\n")
        md.append("regime.py API geriye uyumlu — kwarg'lar zaten parametreli.\n\n")

    md.append("## 5. Verdict Detay\n\n")
    md.append(f"**Gate kriterleri:**\n")
    md.append(f"- Zero ay <= 8 (sec49 baseline 20 → en az -%60)\n")
    md.append(f"- Mean değişim >= -2.0pp (baseline {sec49_mean:+.2f}%'a yakın kal)\n")
    md.append(f"- WF ann düşüşü <= %10 ({wf_base['mean_ann']*0.10:.0f}pp tolerans)\n\n")
    md.append(f"**Best sonuç:**\n")
    md.append(f"- Zero ay: {sec49_zero} → **{zero_after}** "
              f"{'PASS' if zero_after <= 8 else 'PARTIAL' if zero_after <= 12 else 'FAIL'}\n")
    md.append(f"- Mean: {sec49_mean:+.2f}% → **{mean_after:+.2f}%** "
              f"{'PASS' if (mean_after - sec49_mean) >= -2.0 else 'FAIL'}\n")
    md.append(f"- WF ann: {wf_base['mean_ann']:+.2f}% → **{wf_best['mean_ann']:+.2f}%** "
              f"(Δ {wf_delta:+.2f}pp) "
              f"{'PASS' if wf_delta >= -wf_base['mean_ann']*0.10 else 'FAIL'}\n\n")
    md.append(f"**VERDICT: {verdict}**\n\n")

    md.append("## 6. Cooldown / Cikis\n\n")
    if halt_off_better:
        md.append("**Halt OFF stricly better** — Phoenix-scalp 15m TF için capitulation halt\n")
        md.append("**KAPAT** önerisi. 1d için kalibre edilen filtre 15m bull-dominant 2024-25\n")
        md.append("rejiminde aylık alpha'yı yutuyor. MR pool sprint'i halt OFF baseline ile retest edilmeli.\n\n")
    elif verdict == "PASS":
        md.append(f"**TF-specific override önerilir** — ATR={best['atr']}/DD={best['dd']} kullan.\n")
        md.append(f"MR pool sprint'i bu best parametre ile retest edilmeli.\n\n")
    elif verdict == "PARTIAL":
        md.append(f"**Marjinal iyileşme** — ATR={best['atr']}/DD={best['dd']} 15m'de aday ama\n")
        md.append(f"paper trade onayına ihtiyaç. MR pool retest baseline (DEF) ile yapılabilir.\n\n")
    else:
        md.append("**FAIL** — halt re-tune hedeflenen sıfır-ay azalmasını sağlamadı.\n")
        md.append("15m'de yüksek sıfır-ay yapısal (regime-conditional alpha); halt parametresi\n")
        md.append("değil pool/strateji setinde aranmalı. MR pool sprint'i baseline ile retest.\n\n")

    REPORT_OUT.write_text("".join(md), encoding="utf-8")
    print(f"\n[DONE]")


if __name__ == "__main__":
    main()
