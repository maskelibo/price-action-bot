"""Researcher — 15m honest-cost edge hunt.

GOREV (P0): 15m'de durust-maliyet altinda aylik >=%10 ROI uretebilecek strateji
VAR MI, yoksa 15m yapisal tavani nedir?

Pre-registered hipotezler:
  HYP-2026-05-21-15m-wide-stop-honest-edge
  HYP-2026-05-21-15m-vsa-conviction-lowfreq
  HYP-2026-05-21-15m-postonly-maker-cost-floor

Pool: data/sec53_15m_pool_v11.pkl — engine R'si 5bps slippage gomulu.
Maliyet senaryolari (round-trip ek):
  +55bps = taker MARKET (fee 15 + slippage delta 40)
  +30bps = mixed
  +15bps = post-only maker (fee 5 + slippage 10)
  +8bps  = idealized referans (memory etiketleri)
extra_cost_R = extra_bps / (sl_pct * 10000)  per trade

market.duckdb DOKUNULMADI — pool pkl R-bazli honest replay (Lab metodolojisi).
lab.py + production YAML + canli daemon DOKUNULMADI.
Reproduce: python scripts/researcher_15m_honest_edge_hunt.py
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
    """30/30/40 -> new_close. Lab rebaseline methodology (engine.py 606-624)."""
    R = t["R"]
    pk = t["peak_R"]
    c1o, c2o, cro = POOL_CLOSE
    c1n, c2n, crn = new_close
    if pk < TP1_R:
        return R
    if pk < TP2_R:
        R_rest = (R - c1o * TP1_R) / (1.0 - c1o)
        return c1n * TP1_R + (1.0 - c1n) * R_rest
    R_run = (R - c1o * TP1_R - c2o * TP2_R) / cro
    if R_run > pk:
        return R  # underdetermined MFE — leave at pool R
    return c1n * TP1_R + c2n * TP2_R + crn * R_run


def build_pool(pool, extra_bps, reblend=True):
    """Apply honest cost (extra_bps round-trip) + close_pct reblend + pyramid IDEAL."""
    out = []
    for t in pool:
        t2 = dict(t)
        pk = t["peak_R"]
        sl_pct = sl_pct_of(t)
        R = reblend_close_pct(t, LIVE_CLOSE) if reblend else t["R"]
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
    annual = (comp ** (12.0 / n) - 1) * 100 if n > 0 else 0
    srt = sorted(rets, reverse=True)
    comp_top5 = 1.0
    for x in srt[5:]:
        comp_top5 *= (1 + x / 100)
    annual_top5 = (comp_top5 ** (12.0 / max(len(srt) - 5, 1)) - 1) * 100
    worst_dd = min(dds) if dds else 0
    return {
        "n": n, "mean": mu, "median": sorted(rets)[n // 2], "annual": annual,
        "annual_ex_top5": annual_top5,
        "cv": std / abs(mu) * 100 if mu else 1e9,
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
    return {
        "windows": len(anns), "mean_annual": ma, "mean_dd": md,
        "r_adj": ma / abs(md) if md else 0,
        "neg": sum(1 for a in anns if a < 0), "min": min(anns), "max": max(anns),
    }


def shuffle_baseline(pool, cfg, n_iter=200, seed=42):
    """Null: shuffle R across trades (break time-edge link). Real monthly mean
    must beat shuffle distribution at p<0.05."""
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
    return {
        "real_mean": real_mean, "null_mean": sum(null_means) / len(null_means),
        "null_p95": nm[int(0.95 * len(nm))], "p_value": p, "n_iter": len(null_means),
    }


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
            devs.append((s, r["mean"], dev))
    return {"base_mean": base_mean, "per_sym": devs,
            "max_abs_dev": max(abs(d[2]) for d in devs) if devs else 0}


def fmt_pm(label, r):
    if r is None:
        print("  %-34s (no data)" % label, flush=True)
        return
    print("  %-34s annual %+9.1f%%  mean %+7.2f%%  med %+6.2f%%  "
          "neg %2d/%d  maxL %+7.2f%%  exTop5 %+9.1f%%  r-adj %6.2f  CV %4.0f%%" % (
              label, r["annual"], r["mean"], r["median"], r["neg"], r["n"],
              r["max_loss"], r["annual_ex_top5"], r["r_adj"], r["cv"]), flush=True)


def main():
    print("[load] " + POOL.name, flush=True)
    with POOL.open("rb") as f:
        pool = pickle.load(f)
    print("  pool: %d trade  %s -> %s\n" % (
        len(pool), pool[0]["entry_ts"], pool[-1]["entry_ts"]), flush=True)

    base = ProductionConfig.from_yaml(str(YAML))
    cfg = base.with_overrides(
        pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=(),
        fee_bps_per_trade=0.0,
    )

    def slf(t, thr):
        return sl_pct_of(t) >= thr

    # ============ SECTION A: cost scenario x sl_pct sweep (full + filtered) ============
    print("=" * 130, flush=True)
    print("SECTION A — COST SCENARIO x sl_pct FILTER SWEEP (engine replay, per-month, 61 ay)", flush=True)
    print("=" * 130, flush=True)
    cost_scenarios = [("+8bps idealized", 8.0), ("+15bps post-only", 15.0),
                      ("+30bps mixed", 30.0), ("+55bps taker", 55.0)]
    sl_thresholds = [0.0, 0.012, 0.015, 0.018, 0.020, 0.025]
    sweep_results = {}
    for cs_label, bps in cost_scenarios:
        print("\n--- COST: %s ---" % cs_label, flush=True)
        built = build_pool(pool, bps)
        for thr in sl_thresholds:
            sub = [t for t in built if sl_pct_of(t) >= thr]
            sumR = sum(t["R"] for t in sub)
            r = per_month(sub, cfg)
            sweep_results[(bps, thr)] = (r, sumR, len(sub))
            tag = "sl>=%.3f" % thr if thr > 0 else "FULL pool"
            if r is None:
                print("  %-12s n=%6d  sumR=%+8.0f  (no months)" % (tag, len(sub), sumR), flush=True)
            else:
                print("  %-12s n=%6d  sumR=%+8.0f | annual %+9.1f%%  mean %+7.2f%%  "
                      "med %+6.2f%%  neg %2d/%d  exTop5 %+8.1f%%  r-adj %6.2f" % (
                          tag, len(sub), sumR, r["annual"], r["mean"], r["median"],
                          r["neg"], r["n"], r["annual_ex_top5"], r["r_adj"]), flush=True)

    # ============ SECTION B: strategy subset x sl_pct (vsa hypothesis) ============
    print("\n" + "=" * 130, flush=True)
    print("SECTION B — STRATEGY SUBSET x sl_pct (HYP vsa-conviction-lowfreq), honest +55bps", flush=True)
    print("=" * 130, flush=True)
    built55 = build_pool(pool, 55.0)
    subsets = {
        "vsa-only": lambda t: t["strategy"] == "vsa_climax_test",
        "vsa+brooks": lambda t: t["strategy"] in ("vsa_climax_test", "brooks_failed_breakout"),
        "all-strat": lambda t: True,
    }
    for sname, sfilt in subsets.items():
        for thr in [0.0, 0.012, 0.015, 0.018]:
            sub = [t for t in built55 if sfilt(t) and sl_pct_of(t) >= thr]
            sumR = sum(t["R"] for t in sub)
            r = per_month(sub, cfg)
            fmt_pm("%s sl>=%.3f (n=%d sumR%+.0f)" % (sname, thr, len(sub), sumR), r)

    # ============ SECTION C: post-only + wide-stop combo (best-case) ============
    print("\n" + "=" * 130, flush=True)
    print("SECTION C — POST-ONLY (+15bps) x WIDE-STOP COMBO + risk sweep (HYP postonly-maker)", flush=True)
    print("=" * 130, flush=True)
    built15 = build_pool(pool, 15.0)
    for thr in [0.0, 0.012, 0.018, 0.025]:
        for rpct in [0.02, 0.03]:
            cfg_r = cfg.with_overrides(risk_pct=rpct)
            sub = [t for t in built15 if sl_pct_of(t) >= thr]
            sumR = sum(t["R"] for t in sub)
            r = per_month(sub, cfg_r)
            fmt_pm("+15bps sl>=%.3f risk%.0f%% (n=%d sumR%+.0f)" % (
                thr, rpct * 100, len(sub), sumR), r)

    # ============ SECTION D: ROBUSTNESS on top candidates ============
    print("\n" + "=" * 130, flush=True)
    print("SECTION D — ROBUSTNESS SUITE on lead candidates", flush=True)
    print("=" * 130, flush=True)
    # candidates: (label, built_pool, sl_thr, cfg)
    candidates = [
        ("C1: +55bps sl>=0.018", build_pool(pool, 55.0), 0.018, cfg),
        ("C2: +55bps sl>=0.025", build_pool(pool, 55.0), 0.025, cfg),
        ("C3: +15bps sl>=0.018", build_pool(pool, 15.0), 0.018, cfg),
        ("C4: +15bps FULL", build_pool(pool, 15.0), 0.0, cfg),
        ("C5: +55bps vsa+sl>=0.015", build_pool(pool, 55.0), 0.015,
         cfg),  # vsa filter applied below
    ]
    for label, built, thr, cfg_c in candidates:
        if "vsa" in label:
            sub = [t for t in built if t["strategy"] == "vsa_climax_test" and sl_pct_of(t) >= thr]
        else:
            sub = [t for t in built if sl_pct_of(t) >= thr]
        print("\n>>> %s  (n=%d)" % (label, len(sub)), flush=True)
        pm = per_month(sub, cfg_c)
        fmt_pm("per-month", pm)
        wf = walk_forward(sub, cfg_c)
        if wf:
            print("  %-34s mean_ann %+9.1f%%  mean_dd %+7.1f%%  r-adj %6.2f  "
                  "neg %2d/%d  min %+9.1f%%" % (
                      "walk-forward OOS", wf["mean_annual"], wf["mean_dd"],
                      wf["r_adj"], wf["neg"], wf["windows"], wf["min"]), flush=True)
        sh = shuffle_baseline(sub, cfg_c, n_iter=150)
        if sh:
            verdict = "PASS (real>null)" if sh["p_value"] < 0.05 else "FAIL"
            print("  %-34s real_mean %+7.2f%%  null_mean %+7.2f%%  null_p95 %+7.2f%%  "
                  "p=%.4f  %s" % ("shuffle baseline", sh["real_mean"], sh["null_mean"],
                                  sh["null_p95"], sh["p_value"], verdict), flush=True)
        so = symbol_out_cv(sub, cfg_c)
        if so:
            print("  %-34s base_mean %+7.2f%%  max_abs_dev %.1f%%" % (
                "symbol-out CV", so["base_mean"], so["max_abs_dev"]), flush=True)
            for s, m, d in so["per_sym"]:
                print("        drop %-10s mean %+7.2f%%  dev %+7.1f%%" % (s, m, d), flush=True)

    print("\n[done]", flush=True)


if __name__ == "__main__":
    main()
