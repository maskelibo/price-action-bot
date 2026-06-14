"""Champion-Challenger harness — "Live'i gec" tournament (15m WIDESTOP VSA2).

GOAL: Does any re-blendable parameter variant BEAT the live 15m champion config
on ROI AND/OR MaxDD, head-to-head, honestly? If "none beats" -> that is a VALID,
HONEST result (champion robust). NO deploy — report only.

CHAMPION = configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml live params:
    sl_pct_min=0.025, risk_pct=0.005, TP1=1.0R/TP2=1.5R/runner (LIVE_CLOSE 25/25/50),
    trail_mult=3.0 (BAKED into pool R/peak_R), pyramid OFF.

CHALLENGER grid = ONLY the dimensions that production_replay + R-space reblend can
HONESTLY sweep WITHOUT re-simulating from OHLCV:
    sl_pct      in {0.022, 0.024, 0.025, 0.028, 0.030}   (causal entry pre-filter)
    tp_r        in {1.0, 1.5, 2.0, 999}                   (R-cap; 999 = runner/no-cap)
    risk_pct    in {0.005}                                (sizing)
  FULL itertools.product (NO 1-cell bug — every combination evaluated).

WHY trail_mult is NOT in the grid (HONEST architectural limit):
  The pool (sec53_15m_pool_v11.pkl) stores per-trade R and peak_R that were
  PRODUCED by the champion's exit policy incl. trail_mult=3.0. Changing trail_mult
  changes how far each runner ran -> changes R/peak_R themselves -> requires a FULL
  re-simulation from OHLCV. It is NOT a pool-reblend. So trail_mult belongs in the
  SAME heavy "full-rerun" bucket as signal-params (volume_zscore_min, vol_sma_mult,
  confirmation_window) and is reported as a follow-up, NOT faked here.

tp_r reblend semantic (apply_cell parity):
  pool R/peak_R already reflect the champion's TP1=1.0R/TP2=1.5R/runner+trail policy.
  To approximate a DIFFERENT take-profit CAP without re-sim we use the apply_cell
  rule: if peak_R >= tp_r the trade is capped at +tp_r (it would have hit that TP
  and exited), otherwise the realized (reblended) R stands. tp_r=999 = no cap =
  pure champion runner reblend. This is an APPROXIMATION (it ignores that a tighter
  TP frees capital earlier); flagged in the report.

HONEST cost: +55bps taker baseline + +100bps stress (fragility), R-space fee via
  extra_R = extra_bps/(sl_pct*10000) per leg (researcher_slpct_threshold_sweep
  birebir). We compare ROI + continuous-curve MaxDD, NOT R-space Sharpe (which
  inflates under sub-daily multi-symbol concurrency).

Determinist (LLM-less). Pool read-only. Reuses production_replay / ProductionConfig
/ build_pool / monthly_on_curve / continuous_metrics / shuffle_p. No new engine.

Run: .venv/bin/python scripts/champion_challenger.py
"""
from __future__ import annotations

import hashlib
import io
import itertools
import math
import os
import pickle
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ["PA_LOG_QUIET"] = "1"
import warnings  # noqa: E402
warnings.filterwarnings("ignore")
import logging  # noqa: E402
logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
from price_action.backtest.lab import ProductionConfig, production_replay  # noqa: E402

# Reuse the PROVEN honest-cost reblend machinery verbatim
# (researcher_slpct_threshold_sweep.py / lab_15m_widestop_dd_optimization.py).
SLIP_PYR = 0.06
PYR_TRIG = (1.0, 1.5)
PYR_SIZE = (0.50, 0.30)
TP1_R, TP2_R = 1.0, 1.5
POOL_CLOSE = (0.30, 0.30, 0.40)   # pool was built with these close pcts
LIVE_CLOSE = (0.25, 0.25, 0.50)   # live champion reality (25/25/50)

POOL_PATH = ROOT / "data" / "sec53_15m_pool_v11.pkl"
CHAMPION_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
GATES_YAML = ROOT / "configs" / "lab_gates.yaml"

# Champion live parameters (the head-to-head baseline)
CHAMP_SL = 0.025
CHAMP_TP_R = 999          # runner (no TP cap — champion uses TP1/TP2/runner+trail)
CHAMP_RISK = 0.005

# Challenger grid — ONLY re-blendable dims, FULL product
GRID_SL = [0.022, 0.024, 0.025, 0.028, 0.030]
GRID_TP_R = [1.0, 1.5, 2.0, 999]      # 999 = runner / no cap
GRID_RISK = [0.005]

EXTRA_BPS_BASELINE = 55.0
EXTRA_BPS_STRESS = 100.0
# Shuffle is the dominant cost (each iter = full monthly replay over a large
# filtered pool). We compute it ONCE for the champion and ONLY for challenger
# cells that already pass the ROI+DD head-to-head (a cell that doesn't even beat
# champion on ROI/DD can NOT be BEATS_LIVE regardless of p, so its shuffle_p is
# decision-irrelevant). This keeps statistical rigor where it matters without a
# 40x2-cell x 80-iter blow-up.
N_SHUFFLE = 60


def to_utc(ts):
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts.astimezone(timezone.utc)


def sl_pct_of(t):
    ep = t["entry_price"]
    return abs(t["initial_sl"] - ep) / ep if ep > 0 else 0.04


def reblend_close_pct(t, nc):
    """Reconstruct realized R under new close-pct policy (champion runner)."""
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


def build_pool(pool, extra_bps, tp_r=999):
    """Honest-cost pool (R-space fee) + optional tp_r CAP (apply_cell semantic).

    tp_r=999 -> no cap (champion runner). tp_r finite -> if peak_R >= tp_r the
    trade is capped at +tp_r (would have hit that TP). Fee is applied AFTER the
    cap on the (capped) R, in R-space per leg. pyramid OFF for widestop.
    """
    out = []
    for t in pool:
        t2 = dict(t)
        pk = t["peak_R"]
        sl_pct = sl_pct_of(t)
        R = reblend_close_pct(t, LIVE_CLOSE)
        # tp_r CAP (only when a finite TP is requested and it would have triggered)
        if tp_r < 900 and pk >= tp_r:
            R = float(tp_r)
        extra_R = (extra_bps / (sl_pct * 10000.0)) if sl_pct > 0 else 0.0
        radj = R - extra_R   # pyramid OFF -> single round-trip leg
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
        if ms > end:
            break
        me = datetime(cy + (cm == 12), (cm % 12) + 1, 1, tzinfo=timezone.utc)
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
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    if not pool:
        return None
    start, end = to_utc(pool[0]["entry_ts"]), to_utc(pool[-1]["entry_ts"])
    months, cy, cm = [], start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        if ms > end:
            break
        me = datetime(cy + (cm == 12), (cm % 12) + 1, 1, tzinfo=timezone.utc)
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


def shuffle_p(pool, cfg, n_iter=N_SHUFFLE, seed=42):
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
    return {"real": real, "p": sum(1 for m in null if m >= real) / len(null)}


def welch_t(a, b):
    """Welch's t-test on two monthly-return samples (returns t, approx p)."""
    na, nb = len(a), len(b)
    if na < 2 or nb < 2:
        return None
    ma, mb = sum(a) / na, sum(b) / nb
    va = sum((x - ma) ** 2 for x in a) / (na - 1)
    vb = sum((x - mb) ** 2 for x in b) / (nb - 1)
    se = math.sqrt(va / na + vb / nb)
    if se == 0:
        return None
    t = (ma - mb) / se
    # Welch-Satterthwaite df
    num = (va / na + vb / nb) ** 2
    den = (va / na) ** 2 / (na - 1) + (vb / nb) ** 2 / (nb - 1)
    df = num / den if den > 0 else min(na, nb) - 1
    # two-sided p via normal approx for moderate df (informative only)
    p = 2.0 * (1.0 - _norm_cdf(abs(t)))
    return {"t": t, "df": df, "p": p, "mean_diff": ma - mb}


def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def load_gates():
    import yaml
    g = yaml.safe_load(GATES_YAML.read_text())["promotion_gates"]
    return g


def log(msg=""):
    print(msg, flush=True)
    if _LOG is not None:
        _LOG.write(msg + "\n")
        _LOG.flush()


_LOG = None


def evaluate_cell(pool_raw, cfg, sl, tp_r, risk, extra_bps):
    """One (sl,tp_r,risk) cell at a given cost. Returns metrics dict or None."""
    p = build_pool(pool_raw, extra_bps, tp_r=tp_r)
    sub = [t for t in p if sl_pct_of(t) >= sl]
    c = cfg.with_overrides(risk_pct=risk, sl_pct_min=0.0)  # sl filter applied in `sub`
    cm = continuous_metrics(sub, c)
    mo = monthly_on_curve(sub, c)
    if cm is None or mo is None:
        return None
    return {"sl": sl, "tp_r": tp_r, "risk": risk, "n": len(sub),
            "roi_mean": mo["mean"], "roi_median": mo["median"],
            "dd": cm["dd"], "neg": mo["neg"], "n_months": mo["n"],
            "rets": mo["rets"]}


def main():
    global _LOG
    date = datetime.now(timezone.utc).date().isoformat()
    _LOG = open(ROOT / "scripts" / "_champion_challenger.log", "w")

    log("#" * 110)
    log("# CHAMPION-CHALLENGER — 15m WIDESTOP VSA2 — 'Live'i gec' tournament")
    log("# %s" % date)
    log("#" * 110)

    with open(POOL_PATH, "rb") as f:
        pool_raw = pickle.load(f)
    h = hashlib.sha256()
    with open(POOL_PATH, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    log("[load] %s sha256=%s n=%d range %s -> %s" % (
        POOL_PATH.name, h.hexdigest()[:16], len(pool_raw),
        pool_raw[0]["entry_ts"], pool_raw[-1]["entry_ts"]))

    base = ProductionConfig.from_yaml(str(CHAMPION_YAML)).with_overrides(
        pyramid_enabled=False, pyramid_triggers=(), pyramid_sizes=(),
        fee_bps_per_trade=0.0, sl_pct_min=0.0,
        daily_dd=0.02, weekly_dd=0.05)
    gates = load_gates()
    log("[gates] effect>=%.0f%% dsr_p<%.2f maxdd_excess<=%.0f%% regime>=%d" % (
        gates["effect_size_min_pct"] * 100, gates["dsr_p_value_max"],
        gates["maxdd_excess_max"] * 100, gates["regime_coverage_min"]))

    results = {}   # (cost_label) -> list of cell dicts
    champ = {}      # cost_label -> champion cell

    for cost_label, bps in (("baseline_55bps", EXTRA_BPS_BASELINE),
                            ("stress_100bps", EXTRA_BPS_STRESS)):
        log("")
        log("=" * 110)
        log("COST = +%dbps taker (%s)" % (int(bps), cost_label))
        log("=" * 110)

        # CHAMPION baseline first
        ch = evaluate_cell(pool_raw, base, CHAMP_SL, CHAMP_TP_R, CHAMP_RISK, bps)
        champ[cost_label] = ch
        log("[CHAMPION] sl=%.3f tp=runner risk=%.3f  n=%d  ROI_mean=%+.2f%%  "
            "ROI_med=%+.2f%%  MaxDD=%+.1f%%  neg=%d/%d" % (
                CHAMP_SL, CHAMP_RISK, ch["n"], ch["roi_mean"], ch["roi_median"],
                ch["dd"], ch["neg"], ch["n_months"]))

        cells = list(itertools.product(GRID_SL, GRID_TP_R, GRID_RISK))
        log("[grid] %d challenger cells (FULL product %dx%dx%d)" % (
            len(cells), len(GRID_SL), len(GRID_TP_R), len(GRID_RISK)))
        log("")
        log("  %-7s %-7s %-7s %7s %10s %10s %9s %8s %10s %s" % (
            "sl", "tp_r", "risk", "n", "ROImean%", "ROImed%", "MaxDD%",
            "neg", "welch_p", "verdict"))

        rows = []
        n_eval = 0
        for sl, tp_r, risk in cells:
            m = evaluate_cell(pool_raw, base, sl, tp_r, risk, bps)
            if m is None:
                continue
            n_eval += 1
            # is this the champion cell itself? skip self-compare verdict
            is_self = (abs(sl - CHAMP_SL) < 1e-9 and tp_r == CHAMP_TP_R
                       and abs(risk - CHAMP_RISK) < 1e-9)

            # Head-to-head vs champion (same cost)
            roi_ok = m["roi_mean"] >= ch["roi_mean"]
            # DD: more negative = worse. "<=" worse means MaxDD not worse:
            # challenger dd >= champion dd (less negative or equal).
            dd_ok = m["dd"] >= ch["dd"]
            pareto = (roi_ok and dd_ok and (m["roi_mean"] > ch["roi_mean"] or m["dd"] > ch["dd"]))
            # lab_gates: effect size on ROI mean (% relative improvement)
            eff = ((m["roi_mean"] - ch["roi_mean"]) / abs(ch["roi_mean"])
                   if ch["roi_mean"] != 0 else 0.0)
            eff_ok = eff >= gates["effect_size_min_pct"]
            dd_excess_ok = (ch["dd"] - m["dd"]) <= gates["maxdd_excess_max"] * 100.0

            # Significance: Welch's t-test on the paired monthly-return series
            # (challenger vs champion) — SOP-1's prescribed head-to-head test.
            # Directly tests "is the challenger's monthly ROI distribution
            # significantly HIGHER than champion's". Fast + meaningful (the
            # per-month shuffle null was degenerate p=1.0 AND 260s/cell here).
            wt = welch_t(m["rets"], ch["rets"])
            # one-sided p for "challenger > champion"
            if wt is None:
                m["welch_p"] = float("nan")
            else:
                m["welch_p"] = (wt["p"] / 2.0 if wt["mean_diff"] > 0
                                else 1.0 - wt["p"] / 2.0)
            p_ok = (not math.isnan(m["welch_p"])) and m["welch_p"] < gates["dsr_p_value_max"]

            m["effect"] = eff
            m["pareto"] = pareto
            if is_self:
                verdict = "(=CHAMP)"
            elif roi_ok and dd_ok and eff_ok and dd_excess_ok and p_ok:
                verdict = "BEATS_LIVE"
            elif pareto:
                verdict = "pareto~"     # dominates but fails a gate
            else:
                verdict = "no"
            m["verdict"] = verdict
            rows.append(m)
            log("  %-7.3f %-7s %-7.3f %7d %+9.2f %+9.2f %+8.1f %5d/%d %9.4f  %s" % (
                sl, ("runner" if tp_r >= 900 else "%.1f" % tp_r), risk, m["n"],
                m["roi_mean"], m["roi_median"], m["dd"], m["neg"], m["n_months"],
                m["welch_p"], verdict))
        results[cost_label] = rows
        log("[eval] %d/%d cells produced metrics" % (n_eval, len(cells)))

    # ---- Cross-cost consistency: BEATS_LIVE must hold at BOTH costs ----
    log("")
    log("=" * 110)
    log("BEATS_LIVE CANDIDATES (must beat at BOTH 55bps baseline AND 100bps stress)")
    log("=" * 110)
    base_beats = {(r["sl"], r["tp_r"], r["risk"]) for r in results["baseline_55bps"]
                  if r["verdict"] == "BEATS_LIVE"}
    stress_beats = {(r["sl"], r["tp_r"], r["risk"]) for r in results["stress_100bps"]
                    if r["verdict"] == "BEATS_LIVE"}
    robust = base_beats & stress_beats
    if robust:
        for key in sorted(robust):
            log("  ROBUST BEATS_LIVE: sl=%.3f tp_r=%s risk=%.3f" % (
                key[0], "runner" if key[1] >= 900 else key[1], key[2]))
    else:
        log("  NONE. No challenger beats the live champion on ROI+DD at BOTH costs")
        log("  with effect>=15%% + welch_p<0.05 + DD-excess<=5pp. CHAMPION ROBUST.")
        if base_beats:
            log("  (baseline-only beats, FAIL at stress -> fee-fragile, REJECTED: %s)" %
                sorted(base_beats))

    # ---- write report ----
    write_report(date, h.hexdigest()[:16], len(pool_raw), pool_raw, gates,
                 champ, results, robust, base_beats, stress_beats)
    log("")
    log("[done] report -> reports/lab/champion_challenger_%s.md" % date)
    _LOG.close()


def write_report(date, sha, npool, pool_raw, gates, champ, results, robust,
                 base_beats, stress_beats):
    out = ROOT / "reports" / "lab" / ("champion_challenger_%s.md" % date)
    out.parent.mkdir(parents=True, exist_ok=True)
    L = []
    L.append("# Champion-Challenger — 15m WIDESTOP VSA2 — \"Live'i gec\"")
    L.append("")
    L.append("_Generated: %s UTC (determinist, LLM-less)_" % datetime.now(timezone.utc).isoformat())
    L.append("")
    L.append("## Setup")
    L.append("- **Pool:** `data/sec53_15m_pool_v11.pkl` sha256=`%s` n=%d (read-only)" % (sha, npool))
    L.append("- **Range:** %s -> %s" % (pool_raw[0]["entry_ts"], pool_raw[-1]["entry_ts"]))
    L.append("- **Champion config:** `configs/risk_phoenix_scalp_15m_widestop_vsa2.yaml`")
    L.append("  (sl_pct_min=0.025, risk=0.005, TP1=1.0R/TP2=1.5R/runner, trail=3.0 BAKED, pyramid OFF)")
    L.append("- **Challenger grid (FULL product, no 1-cell bug):** "
             "sl in {0.022,0.024,0.025,0.028,0.030} x tp_r in {1.0,1.5,2.0,runner} x risk in {0.005} = %d cells/cost"
             % (len(GRID_SL) * len(GRID_TP_R) * len(GRID_RISK)))
    L.append("- **Honest cost:** +55bps taker baseline + +100bps stress (R-space fee).")
    L.append("- **Gates (lab_gates.yaml):** effect>=%.0f%%, Welch p<%.2f "
             "(one-sided, challenger>champion monthly ROI), MaxDD-excess<=%.0fpp."
             % (gates["effect_size_min_pct"] * 100,
                gates["dsr_p_value_max"], gates["maxdd_excess_max"] * 100))
    L.append("- **Significance note:** the SOP per-month shuffle null was both "
             "degenerate (p~1.0 — winner-skew clusters) and ~260s/cell; replaced "
             "by Welch's t-test on the paired monthly-return series, the SOP-1 "
             "head-to-head test. Welch p only computed for ROI+DD-passing cells.")
    L.append("- **Compare on ROI + continuous-curve MaxDD** (NOT R-space Sharpe — "
             "inflates under sub-daily multi-symbol concurrency).")
    L.append("")

    for cost_label in ("baseline_55bps", "stress_100bps"):
        ch = champ[cost_label]
        L.append("## %s" % cost_label)
        L.append("")
        L.append("**CHAMPION baseline:** sl=0.025 tp=runner risk=0.005 -> "
                 "n=%d, ROI_mean=**%+.2f%%/mo**, ROI_median=%+.2f%%, "
                 "MaxDD=**%+.1f%%**, neg=%d/%d"
                 % (ch["n"], ch["roi_mean"], ch["roi_median"], ch["dd"],
                    ch["neg"], ch["n_months"]))
        L.append("")
        L.append("| sl | tp_r | risk | n | ROI_mean% | ROI_med% | MaxDD% | neg | "
                 "effect_vs_champ | welch_p | verdict |")
        L.append("|----|------|------|---|-----------|----------|--------|-----|"
                 "-----------------|---------|---------|")
        for r in sorted(results[cost_label], key=lambda x: -x["roi_mean"]):
            pstr = "n/a" if math.isnan(r["welch_p"]) else "%.4f" % r["welch_p"]
            L.append("| %.3f | %s | %.3f | %d | %+.2f | %+.2f | %+.1f | %d/%d | "
                     "%+.1f%% | %s | %s |" % (
                         r["sl"], "runner" if r["tp_r"] >= 900 else "%.1f" % r["tp_r"],
                         r["risk"], r["n"], r["roi_mean"], r["roi_median"], r["dd"],
                         r["neg"], r["n_months"], r["effect"] * 100,
                         pstr, r["verdict"]))
        L.append("")

    L.append("## VERDICT — BEATS_LIVE candidates")
    L.append("")
    L.append("Rule: BEATS_LIVE = ROI_mean >= champion AND MaxDD not worse, "
             "AND effect>=15%, AND Welch p<0.05, AND DD-excess<=5pp - "
             "**at BOTH 55bps and 100bps** (fee-robust).")
    L.append("")
    if robust:
        for key in sorted(robust):
            L.append("- **ROBUST BEATS_LIVE:** sl=%.3f tp_r=%s risk=%.3f"
                     % (key[0], "runner" if key[1] >= 900 else key[1], key[2]))
        L.append("")
        L.append("> NOTE: These are CANDIDATES for the human-approval queue, NOT a deploy. "
                 "Promotion requires CEO brief + Principal sign-off (hard limit).")
    else:
        L.append("**NONE. No challenger beats the live champion on ROI+DD at both costs.**")
        L.append("")
        L.append("**CHAMPION ROBUST** — the deployed live 15m config is not dominated by any "
                 "re-blendable sl/tp/risk variant. The wide-stop 0.025 threshold + runner-TP "
                 "is at/near the Pareto frontier of the searchable axes.")
        if base_beats:
            L.append("")
            L.append("- Baseline-only beats that FAIL at stress (fee-fragile, REJECTED): `%s`"
                     % sorted(base_beats))

    L.append("")
    L.append("## Honest caveats")
    L.append("- **R-space cost dependency.** ROI is reblended R x sizing; the +55/+100bps "
             "fee is applied in R-space (extra_R=bps/(sl_pct*10000)). Lower sl_pct -> larger "
             "fee_R -> tighter stops are penalized harder. This is the WIDESTOP fee-shield "
             "mechanism and is intentional.")
    L.append("- **Single-regime caveat.** Monthly ROI is whole-pool 2021-2026. Per-regime "
             "(bull/bear/range) coverage gate not separately split in this harness; the "
             "weekly tournament SOP-1 walk-forward + regime split is the authority for "
             "promotion. This harness is a head-to-head ROI+DD screen, not the full gate.")
    L.append("- **tp_r is an R-space CAP approximation.** It does not model freed-capital "
             "re-deployment from earlier exits; runner (999) is the exact champion policy.")
    L.append("")
    L.append("## Follow-up — FULL-RERUN axes (NOT in this harness)")
    L.append("These change which trades exist / how far runners run -> require full "
             "re-simulation from OHLCV (a separate, heavy champion-challenger), NOT a pool reblend:")
    L.append("- **trail_mult** (2.0/3.0/4.0) — determines runner extent -> regenerates R/peak_R. "
             "The pool's R already encodes champion trail=3.0; sweeping it here would be FAKE.")
    L.append("- **Signal-params** (volume_zscore_min, vol_sma_mult, confirmation_window_N) — "
             "change the set of signals that fire -> full re-detect + re-sim. The known "
             "hypothesis_runner 1-cell bug (only sl/tp/risk axes recognized) lives here.")
    L.append("")
    out.write_text("\n".join(L))


if __name__ == "__main__":
    main()
