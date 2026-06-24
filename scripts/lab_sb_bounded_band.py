"""Lab Scientist — Scenario B bounded-band: lower/mid/upper estimates.

373,675 trade pool. Decomposition exactness:
  - stage0 (51.7%): B-R == baseline R, EXACT.
  - stage1/2 determinate (peak_R > final_R, MFE drove peak): EXACT.
  - stage1/2 indeterminate (peak_R == final_R, ~17.4%): UNDERDETERMINED
    (true MFE unknown, pool stores peak_R = max(MFE, final_R) = final_R).

Determinate stage-2 runner-capture ratio (measured): B_R/peak_R mean +0.766.

Band:
  LOWER : indeterminate B-R = baseline blended R (cap-at-peak floor, B>=base).
  MID   : indeterminate B-R = baseline R / 0.766 * 0.766 ... actually
          indeterminate true MFE estimate = final_R * 1.15 (modest MFE>final);
          B-R = MFE_est * 0.766 capture. Defensible mid.
  UPPER : indeterminate true MFE = final_R * 1.35; B-R = MFE_est * 0.766.
"""
from __future__ import annotations

import io
import os
import pickle
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")
import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay

YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"
POOL = ROOT / "data" / "sec53_15m_pool_v11.pkl"
TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}
SLIP = 5.0 / 10_000.0
TAKER = 0.00075
CAPTURE = 0.766  # measured determinate stage-2 runner-capture ratio


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def derive_B(t, indet_mode):
    """indet_mode: 'lower' | 'mid' | 'upper' — indeterminate trade B-R policy."""
    R = float(t["R"])
    pk = float(t["peak_R"])
    entry = float(t["entry_price"])
    sl = float(t["initial_sl"])
    slp = abs(entry - sl) / entry if entry > 0 else 0.04
    if slp <= 0:
        return R
    tp1g = 1.0 - SLIP * (1.0 / slp + 1.0)
    tp2g = 1.5 - SLIP * (1.0 / slp + 1.5)
    f1 = TAKER * (2.0 + 1.0 * slp) / slp
    f2 = TAKER * (2.0 + 1.5 * slp) / slp
    R1 = tp1g - f1
    R2 = tp2g - f2
    if pk < 1.0 - 1e-9:
        return R  # stage0 exact
    if pk < 1.5 - 1e-9:
        R_B = (R - 0.30 * R1) / 0.70
    else:
        R_B = (R - 0.30 * R1 - 0.30 * R2) / 0.40
    if R_B <= pk:
        return R_B  # determinate-exact (decomposition within MFE ceiling)
    # indeterminate: peak_R = final_R drove it, true MFE unknown >= pk
    if indet_mode == "lower":
        return pk          # B-R floored at baseline blended R (= peak_R here)
    elif indet_mode == "mid":
        mfe_est = pk * 1.15
        return max(pk, mfe_est * CAPTURE)
    else:  # upper
        mfe_est = pk * 1.35
        return max(pk, mfe_est * CAPTURE)


def per_month(pool, cfg):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    start, end = to_utc(pool[0]["entry_ts"]), to_utc(pool[-1]["entry_ts"])
    months = []
    cy, cm = start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        me = datetime(cy + (cm == 12), (cm % 12) + 1, 1, tzinfo=timezone.utc)
        if ms > end:
            break
        months.append((ms, me))
        cm = (cm % 12) + 1
        if cm == 1:
            cy += 1
    rets, dds = [], []
    for ms, me in months:
        m_tr = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 10:
            continue
        r = production_replay(m_tr, cfg)
        if r is None:
            continue
        rets.append(r.total_return * 100)
        dds.append(r.max_drawdown * 100)
    n = len(rets)
    mu = sum(rets) / n
    std = (sum((x - mu) ** 2 for x in rets) / (n - 1)) ** 0.5 if n > 1 else 0
    comp = 1.0
    for x in rets:
        comp *= (1 + x / 100)
    annual = (comp ** (12.0 / n) - 1) * 100 if n > 0 else 0
    worst_dd = min(dds) if dds else 0
    return {"n": n, "mean": mu, "annual": annual,
            "cv": std / abs(mu) * 100 if mu else 1e9,
            "pos": sum(1 for x in rets if x > 0), "neg": sum(1 for x in rets if x < 0),
            "ge20": sum(1 for x in rets if x >= 20),
            "max_loss": min(rets), "worst_month_dd": worst_dd,
            "r_adj": annual / abs(worst_dd) if worst_dd else 0}


def walk_forward(pool, cfg):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["exit_ts"])
    anns, dds = [], []
    cur = start
    while cur + timedelta(days=820) <= end:
        os_s = cur + timedelta(days=730)
        os_e = os_s + timedelta(days=90)
        oos = [t for t in pool if os_s <= to_utc(t["entry_ts"]) < os_e]
        if len(oos) >= 10:
            r = production_replay(oos, cfg)
            if r is not None:
                anns.append(r.annualized(90 / 365.0) * 100)
                dds.append(r.max_drawdown * 100)
        cur += timedelta(days=30)
    ma = sum(anns) / len(anns)
    md = sum(dds) / len(dds)
    return {"windows": len(anns), "mean_annual": ma, "mean_dd": md,
            "r_adj": ma / abs(md) if md else 0, "neg": sum(1 for a in anns if a < 0)}


def R_use(t, cfg):
    R = float(t["R"])
    slp = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"] if t["entry_price"] > 0 else 0.04
    if cfg.pyramid_enabled and cfg.pyramid_triggers and cfg.pyramid_sizes:
        pk = float(t.get("peak_R", R))
        bonus = ero = 0.0
        for trig, sz in zip(cfg.pyramid_triggers, cfg.pyramid_sizes):
            if pk >= float(trig):
                bonus += float(sz) * max(0.0, R - float(trig))
                ero += 0.06 * float(sz)
        R = R + bonus - ero
    if cfg.fee_bps_per_trade != 0.0 and slp > 0:
        base = cfg.fee_bps_per_trade / (slp * 10_000.0)
        pyr = 0.0
        if cfg.pyramid_enabled and cfg.pyramid_triggers and cfg.pyramid_sizes:
            pk2 = float(t.get("peak_R", t["R"]))
            for trig, sz in zip(cfg.pyramid_triggers, cfg.pyramid_sizes):
                if pk2 >= float(trig):
                    pyr += cfg.fee_bps_per_trade / (slp * 10_000.0) * float(sz)
        R = R - base - pyr
    return R


def main():
    print("=" * 98, flush=True)
    print("SCENARIO B — BOUNDED BAND (lower / mid / upper)", flush=True)
    print("=" * 98, flush=True)
    with POOL.open("rb") as f:
        raw = pickle.load(f)
    pool = [t for t in raw if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    print(f"pool: {len(pool):,} trade  |  capture-ratio {CAPTURE} (measured determinate s2)", flush=True)

    pools = {
        "B-lower": [dict(t, R=derive_B(t, "lower")) for t in pool],
        "B-mid": [dict(t, R=derive_B(t, "mid")) for t in pool],
        "B-upper": [dict(t, R=derive_B(t, "upper")) for t in pool],
    }
    base = ProductionConfig.from_yaml(str(YAML))

    for fee in (0.0, 8.0):
        print(f"\n{'='*98}\nFEE = {fee:+.0f} bps\n{'='*98}", flush=True)
        cfg = base.with_overrides(fee_bps_per_trade=fee)
        cfg_off = base.with_overrides(fee_bps_per_trade=fee, pyramid_enabled=False,
                                      pyramid_triggers=(), pyramid_sizes=())
        cur_sr = sum(R_use(t, cfg) for t in pool)
        f_sr = sum(R_use(t, cfg_off) for t in pool)
        print(f"\n--- POOL-R uplift vs CURRENT (compound-bagimsiz) ---", flush=True)
        print(f"  F   pyr OFF  useSumR {f_sr:+.0f}", flush=True)
        print(f"  CUR pyr ON   useSumR {cur_sr:+.0f}  (vs F {(cur_sr/f_sr-1)*100:+.1f}%)", flush=True)
        for name, pl in pools.items():
            sr = sum(R_use(t, cfg) for t in pl)
            print(f"  {name:<11} useSumR {sr:+.0f}  vs CUR {(sr/cur_sr-1)*100:+.1f}%  "
                  f"vs F {(sr/f_sr-1)*100:+.1f}%", flush=True)

        print(f"\n--- PER-MONTH + WALK-FORWARD ---", flush=True)
        print(f"{'scen':<12}{'PM_ann':>12}{'PM_mean':>9}{'PM_neg':>8}{'PM_maxL':>10}"
              f"{'PM_radj':>9}{'WF_ann':>11}{'WF_radj':>9}{'WF_neg':>8}", flush=True)
        print("-" * 92, flush=True)
        cur_pm = per_month(pool, cfg)
        cur_wf = walk_forward(pool, cfg)
        print(f"{'CURRENT':<12}{cur_pm['annual']:>+11.1f}%{cur_pm['mean']:>+8.2f}%"
              f"{cur_pm['neg']:>8d}{cur_pm['max_loss']:>+9.2f}%{cur_pm['r_adj']:>9.2f}"
              f"{cur_wf['mean_annual']:>+10.1f}%{cur_wf['r_adj']:>9.2f}{cur_wf['neg']:>8d}", flush=True)
        for name, pl in pools.items():
            pm = per_month(pl, cfg)
            wf = walk_forward(pl, cfg)
            print(f"{name:<12}{pm['annual']:>+11.1f}%{pm['mean']:>+8.2f}%"
                  f"{pm['neg']:>8d}{pm['max_loss']:>+9.2f}%{pm['r_adj']:>9.2f}"
                  f"{wf['mean_annual']:>+10.1f}%{wf['r_adj']:>9.2f}{wf['neg']:>8d}", flush=True)


if __name__ == "__main__":
    main()
