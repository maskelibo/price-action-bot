"""ROI reconciliation: ~13%/mo champion claim -> honest +7.58%/mo.

Reproduces the ORIGINAL +12.67%/+13.46% claim from the SAME pool + harness it
came from (data/sec53_15m_pool_v11.pkl + lab.py production_replay R-pool path),
then toggles each assumption one at a time to attribute the gap in pp/month.

Engine-side honest baseline (+7.58%) is read from /tmp/champ_55bps.json
(produced by scripts/_champ_55bps_exit_compare.py, real BacktestEngine, 19 syms).

Reproduce: .venv/bin/python scripts/_roi_reconcile_13_to_7.py
DOES NOT touch market.duckdb, live, or any config.
"""
from __future__ import annotations
import io, json, os, pickle, sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from price_action.backtest.lab import ProductionConfig, production_replay

POOL = ROOT / "data" / "sec53_15m_pool_v11.pkl"
YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"

# ---- original optimizer constants (verbatim from lab_15m_widestop_dd_opt.py) ----
SLIP_PYR = 0.06
PYR_TRIG = (1.0, 1.5)
PYR_SIZE = (0.50, 0.30)
TP1_R, TP2_R = 1.0, 1.5
POOL_CLOSE = (0.30, 0.30, 0.40)
LIVE_CLOSE = (0.25, 0.25, 0.50)


def utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def sl_pct_of(t):
    ep = t["entry_price"]
    return abs(t["initial_sl"] - ep) / ep if ep > 0 else 0.04


def reblend_close_pct(t, new_close):
    R = t["R"]; pk = t["peak_R"]
    c1o, c2o, cro = POOL_CLOSE; c1n, c2n, crn = new_close
    if pk < TP1_R:
        return R
    if pk < TP2_R:
        R_rest = (R - c1o * TP1_R) / (1.0 - c1o)
        return c1n * TP1_R + (1.0 - c1n) * R_rest
    R_run = (R - c1o * TP1_R - c2o * TP2_R) / cro
    if R_run > pk:
        return R
    return c1n * TP1_R + c2n * TP2_R + crn * R_run


def build_pool(pool, extra_bps, reblend, pyramid):
    """Verbatim original build_pool, but pyramid toggle exposed."""
    out = []
    for t in pool:
        t2 = dict(t); pk = t["peak_R"]; sl_pct = sl_pct_of(t)
        R = reblend_close_pct(t, LIVE_CLOSE) if reblend else t["R"]
        extra_R = (extra_bps / (sl_pct * 10000.0)) if sl_pct > 0 else 0.0
        radj = R
        if pyramid:
            for trig, sz in zip(PYR_TRIG, PYR_SIZE):
                if pk >= trig:
                    radj += sz * max(0.0, R - trig) - SLIP_PYR * sz
                    radj -= extra_R * sz
        radj -= extra_R
        t2["R"] = radj
        out.append(t2)
    return out


def per_month(pool, cfg, min_trades=10):
    pool = sorted(pool, key=lambda x: utc(x["entry_ts"]))
    if not pool:
        return None
    start, end = utc(pool[0]["entry_ts"]), utc(pool[-1]["entry_ts"])
    months = []; cy, cm = start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        me = datetime(cy + (cm == 12), (cm % 12) + 1, 1, tzinfo=timezone.utc)
        if ms > end:
            break
        months.append((ms, me)); cm = (cm % 12) + 1
        if cm == 1:
            cy += 1
    rets = []
    for ms, me in months:
        m_tr = [t for t in pool if ms <= utc(t["entry_ts"]) < me]
        if len(m_tr) < min_trades:
            continue
        r = production_replay(m_tr, cfg)
        if r is None:
            continue
        rets.append(r.total_return * 100)
    n = len(rets)
    if n == 0:
        return None
    mu = sum(rets) / n
    srt = sorted(rets)
    return {
        "n": n, "mean": mu, "median": srt[n // 2],
        "pos": sum(1 for x in rets if x > 0), "neg": sum(1 for x in rets if x < 0),
        "max_loss": min(rets), "best": max(rets),
        "pos_pct": 100.0 * sum(1 for x in rets if x > 0) / n,
    }


def run(label, pool_raw, base, extra_bps, reblend, pyramid, thr, risk,
        dd, min_trades, syms=None):
    sub = pool_raw
    if syms is not None:
        sub = [t for t in sub if t.get("symbol") in syms]
    bp = build_pool(sub, extra_bps, reblend=reblend, pyramid=pyramid)
    bp = [t for t in bp if sl_pct_of(t) >= thr]
    cfg = base.with_overrides(
        pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=(),
        fee_bps_per_trade=0.0, risk_pct=risk, **dd,
    )
    pm = per_month(bp, cfg, min_trades=min_trades)
    n_trades = len(bp)
    print(f"  {label:<54} mean {pm['mean']:+6.2f}%  med {pm['median']:+6.2f}%  "
          f"pos {pm['pos_pct']:4.0f}%  neg {pm['neg']:2d}/{pm['n']:2d}  "
          f"maxL {pm['max_loss']:+6.2f}%  n_tr {n_trades}", flush=True)
    return {"label": label, **pm, "n_trades": n_trades}


def main():
    print("[load]", POOL.name, flush=True)
    pool = pickle.load(open(POOL, "rb"))
    print(f"  raw pool: {len(pool)} trades, 10 syms, 2021-05..2026-05\n", flush=True)
    base = ProductionConfig.from_yaml(str(YAML))

    dd_base = dict(daily_dd=0.04, weekly_dd=0.08)
    results = {}

    print("=" * 110)
    print("WATERFALL — toggling ONE assumption per step (old pool, old harness)")
    print("=" * 110)

    # STEP 0: REPRODUCE the +12.67% claim exactly (pyramid ON, reblend, 55bps,
    #         sl>=0.025, risk 0.5%, dd-base, min10 trades/month, 10 syms)
    results["S0_claim_pyrON_55_reblend"] = run(
        "S0 ORIG CLAIM: pyr-ON reblend 55bps sl0.025 r0.5% min10",
        pool, base, 55.0, reblend=True, pyramid=True, thr=0.025,
        risk=0.005, dd=dd_base, min_trades=10)

    # STEP 1: remove pyramid amplification (the inflation the resume flagged)
    results["S1_pyrOFF"] = run(
        "S1 -pyramid amplification (pyr-OFF, else identical)",
        pool, base, 55.0, reblend=True, pyramid=False, thr=0.025,
        risk=0.005, dd=dd_base, min_trades=10)

    # STEP 2: remove the min-10-trades/month survivorship filter on the sample
    results["S2_allmonths"] = run(
        "S2 -min10 month filter (count ALL months, incl thin)",
        pool, base, 55.0, reblend=True, pyramid=False, thr=0.025,
        risk=0.005, dd=dd_base, min_trades=1)

    # The remaining gap (10-sym synthetic R-pool -> 19-sym real engine) is read
    # from the engine dump; printed in the report. Also compute pyr-ON variant
    # WITHOUT reblend to locate the +13.46% lineage.

    # +13.46% lineage check: vsa2 amplify used the SAME math; the 13.46 was a
    # walk-down of +17.56 (pyr-ON, 0-neg-month seal). Reproduce the 17.56-style
    # pyr-ON number WITHOUT the min-trade filter relaxation but with the
    # original LIVE_CLOSE reblend to show how "0 neg months" arises.
    print("\n--- lineage probes (not waterfall steps) ---")
    results["P_pyrON_min10_strict"] = run(
        "P pyr-ON 55bps min10 (the +12-13 claim family)",
        pool, base, 55.0, reblend=True, pyramid=True, thr=0.025,
        risk=0.005, dd=dd_base, min_trades=10)
    # 0bps to show fee component on THIS pool
    results["P_pyrON_0bps"] = run(
        "P pyr-ON 0bps min10 (fee add-back on old pool)",
        pool, base, 0.0, reblend=True, pyramid=True, thr=0.025,
        risk=0.005, dd=dd_base, min_trades=10)
    results["P_pyrOFF_0bps"] = run(
        "P pyr-OFF 0bps min10",
        pool, base, 0.0, reblend=True, pyramid=False, thr=0.025,
        risk=0.005, dd=dd_base, min_trades=10)

    # engine honest baseline (read)
    champ = json.load(open("/tmp/champ_55bps.json"))
    b55 = champ["BASELINE@55bps"]; b0 = champ["BASELINE@0bps"]
    print("\n--- engine honest baseline (read from /tmp/champ_55bps.json) ---")
    print(f"  BASELINE@55bps 19-sym real engine: mean {b55['mean_mo']:+.2f}%  "
          f"med {b55['med_mo']:+.2f}%  pos {b55['pos_mo']:.0f}%  "
          f"neg {b55['neg_mo']}/{b55['n_mo']}  DD {b55['maxdd']:.1f}%  "
          f"Sharpe {b55['sharpe_ann']:.2f}  top5R {b55['R_top5_share']:.1f}%")
    print(f"  BASELINE@0bps : mean {b0['mean_mo']:+.2f}%  med {b0['med_mo']:+.2f}%")

    out = {"steps": results,
           "engine_baseline_55": b55, "engine_baseline_0": b0}
    json.dump(out, open("/tmp/roi_reconcile.json", "w"), indent=2, default=str)
    print("\n[done] -> /tmp/roi_reconcile.json")


if __name__ == "__main__":
    main()
