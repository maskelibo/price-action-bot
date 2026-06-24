"""Researcher — 15m honest edge: Section A finish + Section D robustness (lean).

Continuation of researcher_15m_honest_edge_hunt.py — runs the slow parts with
reduced shuffle iterations and focused candidates.
Reproduce: python scripts/researcher_15m_honest_robustness.py
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


def per_month(pool, cfg):
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
    if n == 0:
        return None
    mu = sum(rets) / n
    std = (sum((x - mu) ** 2 for x in rets) / (n - 1)) ** 0.5 if n > 1 else 0
    comp = 1.0
    for x in rets:
        comp *= (1 + x / 100)
    annual = (comp ** (12.0 / n) - 1) * 100
    srt = sorted(rets, reverse=True)
    comp_t5 = 1.0
    for x in srt[5:]:
        comp_t5 *= (1 + x / 100)
    annual_t5 = (comp_t5 ** (12.0 / max(len(srt) - 5, 1)) - 1) * 100
    worst_dd = min(dds) if dds else 0
    return {
        "n": n, "mean": mu, "median": sorted(rets)[n // 2], "annual": annual,
        "annual_ex_top5": annual_t5, "cv": std / abs(mu) * 100 if mu else 1e9,
        "pos": sum(1 for x in rets if x > 0), "neg": sum(1 for x in rets if x < 0),
        "max_loss": min(rets), "worst_month_dd": worst_dd, "rets": rets,
        "r_adj": annual / abs(worst_dd) if worst_dd else 0,
    }


def walk_forward(pool, cfg, train_days=730, oos_days=90, step_days=30):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    if not pool:
        return None
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["exit_ts"])
    anns, dds = [], []
    cur = start
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
    ma = sum(anns) / len(anns)
    md = sum(dds) / len(dds)
    return {"windows": len(anns), "mean_annual": ma, "mean_dd": md,
            "r_adj": ma / abs(md) if md else 0,
            "neg": sum(1 for a in anns if a < 0), "min": min(anns), "max": max(anns)}


def shuffle_baseline(pool, cfg, n_iter=120, seed=42):
    real = per_month(pool, cfg)
    if real is None:
        return None
    real_mean = real["mean"]
    rng = random.Random(seed)
    Rs = [t["R"] for t in pool]
    null_means = []
    for _ in range(n_iter):
        sh = Rs[:]
        rng.shuffle(sh)
        shuffled = [dict(t, R=r) for t, r in zip(pool, sh)]
        rm = per_month(shuffled, cfg)
        if rm is not None:
            null_means.append(rm["mean"])
    if not null_means:
        return None
    p = sum(1 for m in null_means if m >= real_mean) / len(null_means)
    nm = sorted(null_means)
    return {"real_mean": real_mean, "null_mean": sum(null_means) / len(null_means),
            "null_p95": nm[int(0.95 * len(nm))], "p_value": p, "n_iter": len(null_means)}


def symbol_out_cv(pool, cfg):
    syms = sorted(set(t["symbol"] for t in pool))
    base = per_month(pool, cfg)
    if base is None:
        return None
    base_mean = base["mean"]
    devs = []
    for s in syms:
        sub = [t for t in pool if t["symbol"] != s]
        r = per_month(sub, cfg)
        if r is not None:
            dev = (r["mean"] - base_mean) / abs(base_mean) * 100 if base_mean else 0
            devs.append((s, r["mean"], r["neg"], dev))
    return {"base_mean": base_mean, "per_sym": devs,
            "max_abs_dev": max(abs(d[3]) for d in devs) if devs else 0}


STRESS = {
    "2022-05 LUNA": (datetime(2022, 5, 1, tzinfo=timezone.utc), datetime(2022, 6, 1, tzinfo=timezone.utc)),
    "2022-11 FTX": (datetime(2022, 11, 1, tzinfo=timezone.utc), datetime(2022, 12, 1, tzinfo=timezone.utc)),
    "2024-03 ATH": (datetime(2024, 3, 1, tzinfo=timezone.utc), datetime(2024, 4, 1, tzinfo=timezone.utc)),
    "2024-08 Yen": (datetime(2024, 8, 1, tzinfo=timezone.utc), datetime(2024, 9, 1, tzinfo=timezone.utc)),
}


def stress_test(pool, cfg):
    out = []
    for name, (s, e) in STRESS.items():
        sub = [t for t in pool if s <= to_utc(t["entry_ts"]) < e]
        if len(sub) < 10:
            out.append((name, None, len(sub)))
            continue
        r = production_replay(sub, cfg)
        out.append((name, r.total_return * 100 if r else None, len(sub)))
    return out


def fmt_pm(label, r):
    if r is None:
        print("  %-38s (no data)" % label, flush=True)
        return
    print("  %-38s annual %+9.1f%%  mean %+7.2f%%  med %+6.2f%%  neg %2d/%d  "
          "maxL %+7.2f%%  exTop5 %+9.1f%%  r-adj %6.2f  CV %4.0f%%" % (
              label, r["annual"], r["mean"], r["median"], r["neg"], r["n"],
              r["max_loss"], r["annual_ex_top5"], r["r_adj"], r["cv"]), flush=True)


def main():
    print("[load] " + POOL.name, flush=True)
    with POOL.open("rb") as f:
        pool = pickle.load(f)
    print("  pool: %d trade\n" % len(pool), flush=True)
    base = ProductionConfig.from_yaml(str(YAML))
    cfg = base.with_overrides(pyramid_enabled=False, pyramid_triggers=(),
                              pyramid_sizes=(), fee_bps_per_trade=0.0)

    built55 = build_pool(pool, 55.0)
    built15 = build_pool(pool, 15.0)
    built30 = build_pool(pool, 30.0)

    # ---- Section A finish: +55bps wide-stop ----
    print("=" * 120, flush=True)
    print("SECTION A (finish) — +55bps taker, wide-stop sweep", flush=True)
    print("=" * 120, flush=True)
    for thr in [0.018, 0.020, 0.025, 0.030]:
        sub = [t for t in built55 if sl_pct_of(t) >= thr]
        sumR = sum(t["R"] for t in sub)
        r = per_month(sub, cfg)
        fmt_pm("+55bps sl>=%.3f (n=%d sumR%+.0f)" % (thr, len(sub), sumR), r)

    # ---- Section D: robustness on lead candidates ----
    print("\n" + "=" * 120, flush=True)
    print("SECTION D — ROBUSTNESS SUITE", flush=True)
    print("=" * 120, flush=True)
    candidates = [
        ("C1 +55bps sl>=0.018", built55, lambda t: sl_pct_of(t) >= 0.018, cfg),
        ("C2 +55bps sl>=0.025", built55, lambda t: sl_pct_of(t) >= 0.025, cfg),
        ("C3 +30bps sl>=0.018", built30, lambda t: sl_pct_of(t) >= 0.018, cfg),
        ("C4 +15bps sl>=0.018", built15, lambda t: sl_pct_of(t) >= 0.018, cfg),
        ("C5 +55bps vsa sl>=0.015", built55,
         lambda t: t["strategy"] == "vsa_climax_test" and sl_pct_of(t) >= 0.015, cfg),
    ]
    for label, built, filt, cfg_c in candidates:
        sub = [t for t in built if filt(t)]
        print("\n>>> %s  (n=%d)" % (label, len(sub)), flush=True)
        pm = per_month(sub, cfg_c)
        fmt_pm("per-month", pm)
        wf = walk_forward(sub, cfg_c)
        if wf:
            print("  %-38s mean_ann %+9.1f%%  mean_dd %+7.1f%%  r-adj %6.2f  "
                  "neg %2d/%d  min %+9.1f%%" % (
                      "walk-forward OOS", wf["mean_annual"], wf["mean_dd"],
                      wf["r_adj"], wf["neg"], wf["windows"], wf["min"]), flush=True)
        sh = shuffle_baseline(sub, cfg_c, n_iter=100)
        if sh:
            v = "PASS" if sh["p_value"] < 0.05 else "FAIL"
            print("  %-38s real %+7.2f%%  null %+7.2f%%  null_p95 %+7.2f%%  p=%.4f  %s" % (
                "shuffle baseline", sh["real_mean"], sh["null_mean"],
                sh["null_p95"], sh["p_value"], v), flush=True)
        so = symbol_out_cv(sub, cfg_c)
        if so:
            print("  %-38s base %+7.2f%%  max_abs_dev %.1f%%" % (
                "symbol-out CV", so["base_mean"], so["max_abs_dev"]), flush=True)
        st = stress_test(sub, cfg_c)
        sline = "  %-38s " % "stress periods"
        for name, ret, n in st:
            sline += "%s %s(n%d)  " % (name, "%+.1f%%" % ret if ret is not None else "n/a", n)
        print(sline, flush=True)

    print("\n[done]", flush=True)


if __name__ == "__main__":
    main()
