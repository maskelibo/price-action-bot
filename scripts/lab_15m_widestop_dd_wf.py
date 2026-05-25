"""Lab — 15m wide-stop DD-opt adaylarinda walk-forward OOS + shuffle dogrulama.

DD-opt sweep (lab_15m_widestop_dd_opt.py) lider adaylari uretti. Bu script
o adaylarda WF OOS (2y train / 90d OOS / 30d step) + shuffle null kosturur —
DD-throttle/risk tuning sonrasi edge hala OOS'ta robust mu?

Reproduce: python scripts/lab_15m_widestop_dd_wf.py
"""
from __future__ import annotations
import io, os, pickle, sys, random
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

POOL = ROOT / "data" / "sec53_15m_pool_v11.pkl"
YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"
SLIP_PYR = 0.06
PYR_TRIG = (1.0, 1.5)
PYR_SIZE = (0.50, 0.30)
TP1_R, TP2_R = 1.0, 1.5
POOL_CLOSE = (0.30, 0.30, 0.40)
LIVE_CLOSE = (0.25, 0.25, 0.50)


def to_utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def sl_pct_of(t):
    ep = t["entry_price"]
    return abs(t["initial_sl"] - ep) / ep if ep > 0 else 0.04


def reblend_close_pct(t, new_close):
    R, pk = t["R"], t["peak_R"]
    c1o, c2o, cro = POOL_CLOSE
    c1n, c2n, crn = new_close
    if pk < TP1_R:
        return R
    if pk < TP2_R:
        R_rest = (R - c1o * TP1_R) / (1.0 - c1o)
        return c1n * TP1_R + (1.0 - c1n) * R_rest
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


def per_month_mean(pool, cfg):
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
    if not rets:
        return None
    return sum(rets) / len(rets)


def walk_forward(pool, cfg, train_days=730, oos_days=90, step_days=30):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
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
    return {
        "windows": len(anns), "neg": sum(1 for a in anns if a < 0),
        "mean_dd": sum(dds) / len(dds), "min": min(anns),
        "median": sorted(anns)[len(anns) // 2],
    }


def shuffle_p(pool, cfg, n_iter=150, seed=42):
    real = per_month_mean(pool, cfg)
    if real is None:
        return None
    rng = random.Random(seed)
    Rs = [t["R"] for t in pool]
    null = []
    for _ in range(n_iter):
        sh = Rs[:]
        rng.shuffle(sh)
        shuffled = [dict(t, R=r) for t, r in zip(pool, sh)]
        m = per_month_mean(shuffled, cfg)
        if m is not None:
            null.append(m)
    if not null:
        return None
    p = sum(1 for m in null if m >= real) / len(null)
    return {"real": real, "null_mean": sum(null) / len(null), "p": p}


def main():
    print("[load] " + POOL.name, flush=True)
    with POOL.open("rb") as f:
        pool = pickle.load(f)
    base = ProductionConfig.from_yaml(str(YAML))
    pools = {55: build_pool(pool, 55.0), 15: build_pool(pool, 15.0)}

    # Lider adaylar (DD-opt sweep'ten DD<=-25% survivor'lar)
    cands = [
        ("KONSERVATIF +55bps taker", 55, 0.025, 0.005,
         dict(daily_dd=0.02, weekly_dd=0.05)),
        ("ORTA +55bps taker", 55, 0.025, 0.005,
         dict(daily_dd=0.04, weekly_dd=0.08)),
        ("IYIMSER +15bps post-only", 15, 0.025, 0.008,
         dict(daily_dd=0.03, weekly_dd=0.06)),
        ("IYIMSER-dusuk-risk +15bps", 15, 0.025, 0.005,
         dict(daily_dd=0.04, weekly_dd=0.08)),
    ]
    print("=" * 118, flush=True)
    print("WALK-FORWARD OOS + SHUFFLE — DD-opt lider adaylar (2y train / 90d OOS / 30d step)", flush=True)
    print("=" * 118, flush=True)
    for label, bps, thr, risk, dd in cands:
        sub = [t for t in pools[bps] if sl_pct_of(t) >= thr]
        cfg = base.with_overrides(
            pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=(),
            fee_bps_per_trade=0.0, risk_pct=risk, **dd,
        )
        print("\n>>> %s  (sl>=%.3f risk%.2f%% n=%d)" % (label, thr, risk * 100, len(sub)), flush=True)
        wf = walk_forward(sub, cfg)
        if wf:
            negpct = wf["neg"] / wf["windows"] * 100
            verdict = "PASS" if negpct <= 33 else "FAIL"
            print("    WF OOS: %d pencere | neg %d (%.0f%%) | medyan-ann %+.0f%% | "
                  "min %+.0f%% | mean_dd %+.1f%%  -> %s" % (
                      wf["windows"], wf["neg"], negpct, wf["median"],
                      wf["min"], wf["mean_dd"], verdict), flush=True)
        sh = shuffle_p(sub, cfg, n_iter=120)
        if sh:
            verdict = "PASS" if sh["p"] < 0.05 else "FAIL"
            print("    SHUFFLE: real aylik-mean %+.2f%% | null %+.2f%% | p=%.4f  -> %s" % (
                sh["real"], sh["null_mean"], sh["p"], verdict), flush=True)
    print("\n[done]", flush=True)


if __name__ == "__main__":
    main()
