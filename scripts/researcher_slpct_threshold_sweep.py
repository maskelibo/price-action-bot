"""Researcher — sl_pct_min threshold sweep, 15m + 5m, honest-cost + shuffle.

HYPOTHESIS (pre-reg): The deployed WIDESTOP thresholds (15m=0.025, 5m=0.030)
are fee-erosion controls. NULL H0: lowering the threshold preserves honest
monthly-mean ROI (fee erosion does NOT eat the recovered edge). If H0 holds,
lower thresholds dominate (more trades, same/better honest ROI). If H0 is
falsified, honest monthly-mean drops as threshold lowers despite more trades.

Methodology = lab_15m_widestop_dd_optimization.py BİREBİR (honest +55bps taker
baseline, close-reblend, pyramid OFF, continuous-curve DD via production_replay).
5m uses the same R-based honest replay; 5m has many more bars/yr -> fee erosion
in R-space is harsher (extra_R = bps/(sl_pct*10000) per leg).

Causal note: sl_pct = |entry - initial_sl|/entry, known at ENTRY from ATR.
No df.shift(-1), no future bar. Filter is a pure pre-filter on entry attribute.

Reproduce: .venv/bin/python scripts/researcher_slpct_threshold_sweep.py
"""
from __future__ import annotations
import hashlib
import io
import os
import pickle
import random
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

# Honest-cost params (lab_honest_cost_rebaseline.py birebir)
SLIP_PYR = 0.06
PYR_TRIG = (1.0, 1.5)
PYR_SIZE = (0.50, 0.30)
TP1_R, TP2_R = 1.0, 1.5
POOL_CLOSE = (0.30, 0.30, 0.40)
LIVE_CLOSE = (0.25, 0.25, 0.50)

TRAIN_END = datetime(2024, 11, 1, tzinfo=timezone.utc)


def to_utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def sl_pct_of(t):
    ep = t["entry_price"]
    return abs(t["initial_sl"] - ep) / ep if ep > 0 else 0.04


def reblend_close_pct(t, nc):
    R, pk = t["R"], t["peak_R"]
    c1o, c2o, cro = POOL_CLOSE
    c1n, c2n, crn = nc
    if pk < TP1_R:
        return R
    if pk < TP2_R:
        return c1n * TP1_R + (1.0 - c1n) * ((R - c1o * TP1_R) / (1.0 - c1o))
    R_run = (R - c1o * TP1_R - c2o * TP2_R) / cro
    if R_run > pk:
        return R
    return c1n * TP1_R + c2n * TP2_R + crn * R_run


def build_pool(pool, extra_bps):
    out = []
    for t in pool:
        t2 = dict(t)
        pk = t["peak_R"]
        sl_pct = sl_pct_of(t)
        R = reblend_close_pct(t, LIVE_CLOSE)
        extra_R = (extra_bps / (sl_pct * 10000.0)) if sl_pct > 0 else 0.0
        radj = R
        for trig, sz in zip(PYR_TRIG, PYR_SIZE):
            if pk >= trig:
                radj += sz * max(0.0, R - trig) - SLIP_PYR * sz
                radj -= extra_R * sz
        radj -= extra_R
        t2["R"] = radj
        out.append(t2)
    return out


def continuous_metrics(trades, cfg):
    if len(trades) < 30:
        return None
    r = production_replay(trades, cfg)
    if r is None:
        return None
    return {"n": r.trades, "ret": r.total_return * 100, "dd": r.max_drawdown * 100,
            "wr": r.win_rate * 100, "sumR": r.sum_r}


def monthly_on_curve(trades, cfg):
    trades = sorted(trades, key=lambda x: to_utc(x["entry_ts"]))
    if not trades:
        return None
    start, end = to_utc(trades[0]["entry_ts"]), to_utc(trades[-1]["entry_ts"])
    months, cy, cm = [], start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        me = datetime(cy + (cm == 12), (cm % 12) + 1, 1, tzinfo=timezone.utc)
        if ms > end:
            break
        months.append((ms, me))
        cm = (cm % 12) + 1
        cy += (cm == 1)
    rets, equity = [], cfg.initial_capital
    for ms, me in months:
        m_tr = [t for t in trades if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 10:
            continue
        r = production_replay(m_tr, cfg.with_overrides(initial_capital=equity))
        if r is None:
            continue
        rets.append(r.total_return * 100)
        equity = r.final_equity if r.final_equity > 0 else 1.0
    n = len(rets)
    if n == 0:
        return None
    mu = sum(rets) / n
    srt = sorted(rets)
    median = srt[n // 2] if n % 2 else (srt[n // 2 - 1] + srt[n // 2]) / 2
    return {"n": n, "mean": mu, "median": median,
            "neg": sum(1 for x in rets if x < 0), "rets": rets}


def per_month_mean_fast(pool, cfg):
    """For shuffle: just monthly-mean scalar (independent $10k per month)."""
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    if not pool:
        return None
    start, end = to_utc(pool[0]["entry_ts"]), to_utc(pool[-1]["entry_ts"])
    months, cy, cm = [], start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        me = datetime(cy + (cm == 12), (cm % 12) + 1, 1, tzinfo=timezone.utc)
        if ms > end:
            break
        months.append((ms, me))
        cm = (cm % 12) + 1
        cy += (cm == 1)
    rets = []
    for ms, me in months:
        m_tr = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 10:
            continue
        r = production_replay(m_tr, cfg)
        if r is not None:
            rets.append(r.total_return * 100)
    return sum(rets) / len(rets) if rets else None


def shuffle_p(pool, cfg, n_iter=120, seed=42):
    real = per_month_mean_fast(pool, cfg)
    if real is None:
        return None
    rng = random.Random(seed)
    Rs = [t["R"] for t in pool]
    null = []
    for _ in range(n_iter):
        sh = Rs[:]
        rng.shuffle(sh)
        m = per_month_mean_fast([dict(t, R=r) for t, r in zip(pool, sh)], cfg)
        if m is not None:
            null.append(m)
    if not null:
        return None
    p = sum(1 for m in null if m >= real) / len(null)
    return {"real": real, "null_mean": sum(null) / len(null), "p": p}


def walk_forward(pool, cfg, train_days=730, oos_days=90, step_days=30):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    if not pool:
        return None
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["exit_ts"])
    anns, dds, cur = [], [], start
    while cur + timedelta(days=train_days + oos_days) <= end:
        os_s = cur + timedelta(days=train_days)
        os_e = os_s + timedelta(days=oos_days)
        oos_tr = [t for t in pool if os_s <= to_utc(t["entry_ts"]) < os_e]
        if len(oos_tr) >= 10:
            r = production_replay(oos_tr, cfg)
            if r is not None:
                anns.append(r.annualized(oos_days / 365.0) * 100)
                dds.append(r.max_drawdown * 100)
        cur += timedelta(days=step_days)
    if not anns:
        return None
    return {"windows": len(anns), "neg": sum(1 for a in anns if a < 0),
            "mean_dd": sum(dds) / len(dds), "median": sorted(anns)[len(anns) // 2],
            "min": min(anns)}


_LOG = None


def log(msg=""):
    print(msg, flush=True)
    if _LOG is not None:
        _LOG.write(msg + "\n")
        _LOG.flush()


def sweep(label, pool_path, yaml_path, sl_grid, risk_pct, dd_kwargs, extra_bps=55.0,
          n_shuffle=80):
    log("=" * 110)
    log("SWEEP: %s   (honest +%dbps taker, pyramid OFF)" % (label, int(extra_bps)))
    log("=" * 110)
    with open(pool_path, "rb") as f:
        pool_raw = pickle.load(f)
    h = hashlib.sha256()
    with open(pool_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    log("[load] %s  sha256=%s  n=%d  range %s -> %s" % (
        Path(pool_path).name, h.hexdigest()[:16], len(pool_raw),
        pool_raw[0]["entry_ts"], pool_raw[-1]["entry_ts"]))

    base = ProductionConfig.from_yaml(str(yaml_path))
    cfg = base.with_overrides(
        pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=(),
        fee_bps_per_trade=0.0, risk_pct=risk_pct, sl_pct_min=0.0, **dd_kwargs)

    pool55 = build_pool(pool_raw, extra_bps)
    log("")
    log("  %-8s %8s %12s %9s %9s %10s %8s" % (
        "sl_min", "n_trade", "mon_mean%", "MaxDD%", "neg_ay%", "shuffle_p", "verdict"))
    rows = []
    for thr in sl_grid:
        sub = [t for t in pool55 if sl_pct_of(t) >= thr]
        cm = continuous_metrics(sub, cfg)
        mo = monthly_on_curve(sub, cfg)
        n = len(sub)
        if cm is None or mo is None:
            log("  %.3f    %8d   (insufficient data)" % (thr, n))
            continue
        sh = shuffle_p(sub, cfg, n_iter=n_shuffle)
        negpct = mo["neg"] / mo["n"] * 100
        p = sh["p"] if sh else float("nan")
        ok_roi = mo["mean"] > 0
        ok_dd = cm["dd"] >= -25.0
        ok_p = (sh is not None and sh["p"] < 0.05)
        verdict = "PASS" if (ok_roi and ok_dd and ok_p) else (
            "soft" if (ok_roi and ok_p) else "FAIL")
        log("  %.3f    %8d   %+10.2f   %+8.1f   %7.1f   %9.4f   %s" % (
            thr, n, mo["mean"], cm["dd"], negpct, p, verdict))
        rows.append((thr, n, mo["mean"], cm["dd"], negpct, p, verdict, mo["rets"]))

    log("")
    log("  --- WALK-FORWARD OOS (2y train / 90d OOS / 30d step) ---")
    for thr in sl_grid:
        sub = [t for t in pool55 if sl_pct_of(t) >= thr]
        wf = walk_forward(sub, cfg)
        if wf:
            negp = wf["neg"] / wf["windows"] * 100
            v = "PASS" if negp <= 33 else "FAIL"
            log("  sl>=%.3f  WF %d win | neg %d (%.0f%%) | med-ann %+.0f%% | "
                "min %+.0f%% | mean_dd %+.1f%%  -> %s" % (
                    thr, wf["windows"], wf["neg"], negp, wf["median"],
                    wf["min"], wf["mean_dd"], v))
    return rows


def main():
    global _LOG
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    _LOG = open(ROOT / "scripts" / ("_slpct_sweep_%s.log" % which), "w")
    log("")
    log("#" * 110)
    log("# RESEARCHER — sl_pct_min THRESHOLD SWEEP (%s)" % which)
    log("# H0: lowering threshold preserves honest monthly-mean (fee erosion harmless)")
    log("#" * 110)
    log("")

    if which in ("all", "15m"):
        sweep("15m", ROOT / "data" / "sec53_15m_pool_v11.pkl",
              ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml",
              sl_grid=[0.015, 0.018, 0.020, 0.022, 0.025, 0.030],
              risk_pct=0.005, dd_kwargs=dict(daily_dd=0.02, weekly_dd=0.05),
              extra_bps=55.0)

    if which in ("all", "5m"):
        sweep("5m", ROOT / "data" / "sec53_5m_pool_v11_vm20.pkl",
              ROOT / "configs" / "risk_phoenix_scalp_5m_p1c.yaml",
              sl_grid=[0.020, 0.025, 0.030, 0.035],
              risk_pct=0.005, dd_kwargs=dict(daily_dd=0.03, weekly_dd=0.06),
              extra_bps=55.0)

    log("")
    log("=" * 110)
    log("MULTIPLE-TESTING: 15m 6 thr + 5m 4 thr = 10 tests. Bonferroni alpha=0.05/10=0.005")
    log("  -> shuffle p must be < 0.005 to claim edge after Bonferroni.")
    log("=" * 110)
    log("[done]")
    _LOG.close()


if __name__ == "__main__":
    main()
