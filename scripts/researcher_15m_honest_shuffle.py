"""Researcher — 15m honest edge: shuffle baseline + symbol-out + stress (lean).
Reproduce: python scripts/researcher_15m_honest_shuffle.py
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


def per_month_mean(pool, cfg):
    """Fast: returns just (mean, neg, n) of monthly returns."""
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    if not pool:
        return None
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
    rets = []
    for ms, me in months:
        m_tr = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 10:
            continue
        r = production_replay(m_tr, cfg)
        if r is None:
            continue
        rets.append(r.total_return * 100)
    if not rets:
        return None
    return {"mean": sum(rets) / len(rets), "neg": sum(1 for x in rets if x < 0),
            "n": len(rets)}


def shuffle_baseline(pool, cfg, n_iter, seed=42):
    real = per_month_mean(pool, cfg)
    if real is None:
        return None
    rng = random.Random(seed)
    Rs = [t["R"] for t in pool]
    null_means = []
    for _ in range(n_iter):
        sh = Rs[:]
        rng.shuffle(sh)
        rm = per_month_mean([dict(t, R=r) for t, r in zip(pool, sh)], cfg)
        if rm is not None:
            null_means.append(rm["mean"])
    if not null_means:
        return None
    p = sum(1 for m in null_means if m >= real["mean"]) / len(null_means)
    nm = sorted(null_means)
    return {"real": real["mean"], "null_mean": sum(null_means) / len(null_means),
            "null_p95": nm[int(0.95 * len(nm))], "p": p, "n_iter": len(null_means)}


def symbol_out(pool, cfg):
    syms = sorted(set(t["symbol"] for t in pool))
    base = per_month_mean(pool, cfg)
    if base is None:
        return None
    devs = []
    for s in syms:
        r = per_month_mean([t for t in pool if t["symbol"] != s], cfg)
        if r is not None:
            dev = (r["mean"] - base["mean"]) / abs(base["mean"]) * 100 if base["mean"] else 0
            devs.append((s, r["mean"], r["neg"], dev))
    return {"base": base["mean"], "devs": devs,
            "max_dev": max(abs(d[3]) for d in devs) if devs else 0}


STRESS = {
    "2022-05_LUNA": (datetime(2022, 5, 1, tzinfo=timezone.utc), datetime(2022, 6, 1, tzinfo=timezone.utc)),
    "2022-11_FTX": (datetime(2022, 11, 1, tzinfo=timezone.utc), datetime(2022, 12, 1, tzinfo=timezone.utc)),
    "2024-03_ATH": (datetime(2024, 3, 1, tzinfo=timezone.utc), datetime(2024, 4, 1, tzinfo=timezone.utc)),
    "2024-08_Yen": (datetime(2024, 8, 1, tzinfo=timezone.utc), datetime(2024, 9, 1, tzinfo=timezone.utc)),
}


def stress(pool, cfg):
    out = []
    for name, (s, e) in STRESS.items():
        sub = [t for t in pool if s <= to_utc(t["entry_ts"]) < e]
        if len(sub) < 10:
            out.append((name, None, len(sub)))
            continue
        r = production_replay(sub, cfg)
        out.append((name, r.total_return * 100 if r else None, len(sub)))
    return out


def main():
    with POOL.open("rb") as f:
        pool = pickle.load(f)
    print("[load] %d trade\n" % len(pool), flush=True)
    base = ProductionConfig.from_yaml(str(YAML))
    cfg = base.with_overrides(pyramid_enabled=False, pyramid_triggers=(),
                              pyramid_sizes=(), fee_bps_per_trade=0.0)
    b55 = build_pool(pool, 55.0)
    b30 = build_pool(pool, 30.0)
    b15 = build_pool(pool, 15.0)
    cands = [
        ("C1 +55bps sl>=0.018", [t for t in b55 if sl_pct_of(t) >= 0.018]),
        ("C2 +55bps sl>=0.025", [t for t in b55 if sl_pct_of(t) >= 0.025]),
        ("C3 +30bps sl>=0.018", [t for t in b30 if sl_pct_of(t) >= 0.018]),
        ("C4 +15bps sl>=0.018", [t for t in b15 if sl_pct_of(t) >= 0.018]),
        ("C5 +55bps vsa sl>=0.015",
         [t for t in b55 if t["strategy"] == "vsa_climax_test" and sl_pct_of(t) >= 0.015]),
        ("C6 +55bps FULL (control)", b55),
    ]
    for label, sub in cands:
        print(">>> %s  (n=%d)" % (label, len(sub)), flush=True)
        sh = shuffle_baseline(sub, cfg, n_iter=60)
        if sh:
            v = "PASS" if sh["p"] < 0.05 else "FAIL"
            print("  shuffle: real %+7.2f%%  null_mean %+7.2f%%  null_p95 %+7.2f%%  "
                  "p=%.4f  %s  (n_iter=%d)" % (
                      sh["real"], sh["null_mean"], sh["null_p95"], sh["p"], v,
                      sh["n_iter"]), flush=True)
        so = symbol_out(sub, cfg)
        if so:
            print("  symbol-out CV: base %+7.2f%%  max_abs_dev %.1f%%" % (
                so["base"], so["max_dev"]), flush=True)
            for s, m, neg, d in so["devs"]:
                print("      drop %-10s mean %+7.2f%%  neg %2d  dev %+7.1f%%" % (
                    s, m, neg, d), flush=True)
        st = stress(sub, cfg)
        sl = "  stress: "
        for name, ret, n in st:
            sl += "%s %s(n%d)  " % (name, "%+.1f%%" % ret if ret is not None else "n/a", n)
        print(sl + "\n", flush=True)
    print("[done]", flush=True)


if __name__ == "__main__":
    main()
