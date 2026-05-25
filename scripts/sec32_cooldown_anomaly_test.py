"""SEC32 Analyst — Cooldown Baseline Anomaly Forensic

Step 1: Replay parity — Baseline A (TOP-4 trend-cont) iki defa:
  Run 1: cooldown=15dk (YAML default 0.010 day)
  Run 2: cooldown=0  (script override, RESUME etiket scenariosu)
Karşılaştır: annual mean, mean monthly, zero ay, neg ay, CV, ge20 ay.

Step 2: Cooldown sweep — 0.0, 0.003 (~4.3dk), 0.010 (15dk),
        0.020 (~29dk), 0.040 (~58dk), 0.063 (~90dk), 0.125 (3h),
        0.25 (6h), 1.0 (1g), 3.0 (3g)
        Her senaryo 34-pencere WF + 61 ay per-month.

Output: print + reports/analyst/2026-05-17_sec32_cooldown_baseline_anomaly.md
"""
from __future__ import annotations
import io, os, pickle, sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean as stat_mean, stdev

if __name__ == "__main__":
    try: sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception: pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import pandas as pd
from price_action.backtest.lab import ProductionConfig, production_replay

POOL_R4 = ROOT / "data" / "sec31_15m_pool.pkl"
YAML_R3 = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"
REPORT_OUT = ROOT / "reports" / "analyst" / "2026-05-17_sec32_cooldown_baseline_anomaly.md"

TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}

TRAIN_DAYS = 2 * 365
OOS_DAYS = 90
STEP_DAYS = 30


def to_utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def build_windows(trades):
    trades.sort(key=lambda x: x["entry_ts"])
    start = trades[0]["entry_ts"]
    end = trades[-1]["exit_ts"]
    out = []
    cur = start
    while cur + pd.Timedelta(days=TRAIN_DAYS + OOS_DAYS) <= end:
        out.append((cur, cur + pd.Timedelta(days=TRAIN_DAYS)))
        cur += pd.Timedelta(days=STEP_DAYS)
    return out


def walk_forward(pool, cfg, years=TRAIN_DAYS/365.0):
    pool = sorted(pool, key=lambda x: x["entry_ts"])
    windows = build_windows(pool)
    anns, dds, neg, ntot = [], [], 0, 0
    for ws, we in windows:
        w = [t for t in pool if ws <= t["entry_ts"] < we]
        if not w:
            continue
        r = production_replay(w, cfg)
        if r is None:
            continue
        ann = r.annualized(years) * 100
        dd = r.max_drawdown * 100
        anns.append(ann); dds.append(dd); ntot += r.trades
        if ann < 0: neg += 1
    if not anns:
        return None
    ma = stat_mean(anns); md = stat_mean(dds)
    return {
        "n_win": len(anns),
        "neg": neg,
        "ann_mean": ma,
        "ann_min": min(anns),
        "ann_max": max(anns),
        "dd_mean": md,
        "r_adj": ma / abs(md) if md != 0 else 0,
        "n_trades_total": ntot,
    }


def per_month(pool, cfg):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["entry_ts"])

    months = []
    cy, cm = start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        if cm == 12:
            me = datetime(cy + 1, 1, 1, tzinfo=timezone.utc)
        else:
            me = datetime(cy, cm + 1, 1, tzinfo=timezone.utc)
        if ms > end:
            break
        months.append((cy, cm, ms, me))
        cm += 1
        if cm > 12:
            cm = 1; cy += 1

    rets, zero, neg = [], 0, 0
    ge20 = 0
    for yr, mo, ms, me in months:
        m_tr = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 1:
            zero += 1
            rets.append(0.0); continue
        if len(m_tr) < 10:
            rets.append(0.0); continue
        r = production_replay(m_tr, cfg)
        if r is None:
            rets.append(0.0); continue
        ret = r.total_return * 100
        rets.append(ret)
        if ret < 0: neg += 1
        if ret >= 20.0: ge20 += 1
    if not rets:
        return None
    mu = stat_mean(rets)
    sd = stdev(rets) if len(rets) > 1 else 0.0
    return {
        "n_months": len(months),
        "mean_pct": mu,
        "stdev_pct": sd,
        "cv_pct": (sd / abs(mu) * 100) if mu != 0 else 1e9,
        "zero_months": zero,
        "neg_months": neg,
        "ge20_months": ge20,
        "min_pct": min(rets),
        "max_pct": max(rets),
    }


def fmt_row(label, wf, pm):
    return (f"| {label} | {wf['ann_mean']:+.1f}% | {wf['dd_mean']:+.1f}% | "
            f"{wf['r_adj']:.2f} | {pm['mean_pct']:+.2f}% | {pm['cv_pct']:.0f}% | "
            f"{pm['zero_months']} | {pm['neg_months']} | {pm['ge20_months']} |")


def main():
    REPORT_OUT.parent.mkdir(parents=True, exist_ok=True)
    out: list[str] = []
    def w(s: str = ""):
        print(s); out.append(s)

    w("# SEC32 — Cooldown Baseline Anomaly Forensic")
    w("")
    w(f"**Generated:** {pd.Timestamp.now('UTC').isoformat()}")
    w("**Analyst:** Head of Performance Analytics")
    w("**Pool:** sec31_15m_pool.pkl filtered to TOP-4 trend-cont (sec_s5 baseline A)")
    w("**Config:** risk_phoenix_scalp_15m_pyramid_r3.yaml (mc=20 override)")
    w("**Window:** WF 2y train + 3mo OOS + 1mo step (34 pencere), per-ay 61 ay")
    w("")

    # Load R4 pool
    print(f"[load] {POOL_R4.name}")
    with POOL_R4.open("rb") as f:
        r4_raw = pickle.load(f)
    pool = [t for t in r4_raw if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    print(f"  TOP-4 trades: {len(pool):,}")

    # Base cfg from YAML
    base_cfg = ProductionConfig.from_yaml(str(YAML_R3)).with_overrides(max_concurrent=20)
    print(f"[cfg] {YAML_R3.name} mc=20")
    print(f"  YAML default cooldown: {base_cfg.same_symbol_side_cooldown_days} day "
          f"({base_cfg.same_symbol_side_cooldown_days*86400:.1f}s = "
          f"{base_cfg.same_symbol_side_cooldown_days*1440:.1f} dk)")

    # =========================================================================
    # STEP 1 — Replay parity (15dk vs 0)
    # =========================================================================
    w("## Step 1 — Replay Parity: 15dk vs 0 cooldown")
    w("")
    w("Baseline A (TOP-4 trend-cont, no MR) iki cooldown ile:")
    w("")
    w("| Senaryo | Annual | DD | r-adj | Mean/mo | CV | Zero | Neg | ge20 |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|")

    # Run 1: YAML default (0.010 = 15dk)
    cfg_15dk = base_cfg  # YAML default already 0.010
    print(f"\n[Run 1] cooldown=0.010d (15dk, YAML default)")
    wf1 = walk_forward(pool, cfg_15dk)
    pm1 = per_month(pool, cfg_15dk)
    w(fmt_row("Run 1 — cooldown=0.010d (15dk, YAML)", wf1, pm1))

    # Run 2: override 0
    cfg_0 = base_cfg.with_overrides(same_symbol_side_cooldown_days=0.0)
    print(f"\n[Run 2] cooldown=0.0d (RESUME etiket override)")
    wf2 = walk_forward(pool, cfg_0)
    pm2 = per_month(pool, cfg_0)
    w(fmt_row("Run 2 — cooldown=0.0d  (RESUME override)", wf2, pm2))

    w("")
    w("**Delta (Run1 - Run2):**")
    w(f"- Annual: {wf1['ann_mean']-wf2['ann_mean']:+.1f}pp")
    w(f"- DD: {wf1['dd_mean']-wf2['dd_mean']:+.1f}pp")
    w(f"- Mean monthly: {pm1['mean_pct']-pm2['mean_pct']:+.2f}pp")
    w(f"- CV: {pm1['cv_pct']-pm2['cv_pct']:+.0f}pp")
    w(f"- Zero ay: {pm1['zero_months']-pm2['zero_months']:+d}")
    w(f"- Neg ay: {pm1['neg_months']-pm2['neg_months']:+d}")
    w(f"- ge20 ay: {pm1['ge20_months']-pm2['ge20_months']:+d}")
    w(f"- WF trades: Run1={wf1['n_trades_total']:,}, Run2={wf2['n_trades_total']:,} "
      f"(delta {wf2['n_trades_total']-wf1['n_trades_total']:+,})")
    w("")

    # =========================================================================
    # STEP 2 — Cooldown sweep
    # =========================================================================
    w("## Step 2 — Cooldown Sweep (10 nokta)")
    w("")
    sweep = [
        (0.000, "0 (off)"),
        (0.003, "0.003d (~4.3dk)"),
        (0.010, "0.010d (~15dk) YAML"),
        (0.020, "0.020d (~29dk)"),
        (0.040, "0.040d (~58dk)"),
        (0.063, "0.063d (~90dk)"),
        (0.125, "0.125d (3h)"),
        (0.250, "0.250d (6h)"),
        (1.000, "1.000d (1g)"),
        (3.000, "3.000d (3g) 1d default"),
    ]
    w("| Cooldown | Annual | DD | r-adj | Mean/mo | CV | Zero | Neg | ge20 | WF trades |")
    w("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    sweep_rows = []
    for cd, label in sweep:
        print(f"\n[sweep] cooldown={cd:.3f}d ({label})")
        cfg = base_cfg.with_overrides(same_symbol_side_cooldown_days=cd)
        wf = walk_forward(pool, cfg)
        pm = per_month(pool, cfg)
        row = (f"| {label} | {wf['ann_mean']:+.1f}% | {wf['dd_mean']:+.1f}% | "
               f"{wf['r_adj']:.2f} | {pm['mean_pct']:+.2f}% | {pm['cv_pct']:.0f}% | "
               f"{pm['zero_months']} | {pm['neg_months']} | {pm['ge20_months']} | "
               f"{wf['n_trades_total']:,} |")
        w(row)
        sweep_rows.append({"cd": cd, "label": label, "wf": wf, "pm": pm})
    w("")

    # =========================================================================
    # STEP 3 — Mechanism analysis
    # =========================================================================
    w("## Step 3 — Mekanizma Analizi")
    w("")
    w("**Cooldown cast bug fix (lab.py):**")
    w("")
    w("```python")
    w("# ESKİ (broken):")
    w("same_symbol_side_cooldown_days: int = 3")
    w("# YAML loader: int(0.010) = 0  → cooldown effectively OFF")
    w("# Enforcement: (entry_ts - prev).days < 0 → always False → no-op")
    w("")
    w("# YENİ (fixed):")
    w("same_symbol_side_cooldown_days: float = 3.0")
    w("# YAML loader: float(0.010) = 0.010  → 15dk")
    w("# Enforcement: (entry_ts - prev).total_seconds() < 0.010 * 86400 = 864s")
    w("```")
    w("")
    base_15 = sweep_rows[2]  # 0.010
    base_0  = sweep_rows[0]  # 0
    base_3  = sweep_rows[9]  # 3.0
    trade_reduction = base_15["wf"]["n_trades_total"] / max(base_0["wf"]["n_trades_total"],1)
    w(f"**Trade reduction (cooldown 0 → 15dk):** "
      f"{base_0['wf']['n_trades_total']:,} → {base_15['wf']['n_trades_total']:,} "
      f"({(trade_reduction-1)*100:+.1f}%)")
    w(f"**Mean monthly etkisi (0 → 15dk):** "
      f"{base_0['pm']['mean_pct']:+.2f}% → {base_15['pm']['mean_pct']:+.2f}% "
      f"({base_15['pm']['mean_pct']-base_0['pm']['mean_pct']:+.2f}pp)")
    w(f"**Annual etkisi (0 → 15dk):** "
      f"{base_0['wf']['ann_mean']:+.1f}% → {base_15['wf']['ann_mean']:+.1f}% "
      f"({base_15['wf']['ann_mean']-base_0['wf']['ann_mean']:+.1f}pp)")
    w(f"**Zero ay etkisi (0 → 15dk):** "
      f"{base_0['pm']['zero_months']} → {base_15['pm']['zero_months']} "
      f"({base_15['pm']['zero_months']-base_0['pm']['zero_months']:+d})")
    w("")

    REPORT_OUT.write_text("\n".join(out), encoding="utf-8")
    print(f"\n[report] {REPORT_OUT}")


if __name__ == "__main__":
    main()
