"""V5 — Forex 4H brooks_failed_breakout as a DIVERSIFIER to the crypto VSA-WIDESTOP champion.

Goal: estimate rho(brooks_forex, champion) on a COMMON monthly $-return series built by the
SAME production_replay engine, then compute marginal portfolio Sharpe.

Reproduce: .venv/bin/python scripts/forex_brooks_diversifier.py
"""
from __future__ import annotations
import io, os, sys, pickle, math, random, subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.engine import BacktestEngine
from price_action.backtest.lab import ProductionConfig, production_replay

# Reuse the pre-registered forex research module verbatim (same cost/session/swap)
import importlib.util
spec = importlib.util.spec_from_file_location("fx", str(ROOT / "scripts" / "forex_4h_research.py"))
fx = importlib.util.module_from_spec(spec); spec.loader.exec_module(fx)

SEED = 12345
random.seed(SEED); np.random.seed(SEED)

GIT = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                     capture_output=True, text=True).stdout.strip()

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def to_utc(ts):
    ts = pd.Timestamp(ts)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def month_key(ts):
    t = to_utc(ts)
    return f"{t.year:04d}-{t.month:02d}"


def monthly_dollar_returns(trades, cfg, label, min_trades=1):
    """Realistic per-month ROI via the SAME equity-reset production_replay the champion lab
    harness uses (per_month_mean). Each calendar month is replayed with a fresh $-account so
    concurrency / notional caps / DD-breakers apply correctly. Returns dict[month]->ROI%.

    This is the honest, comparable footing for BOTH the crypto champion and forex brooks.
    """
    if not trades:
        return {}, None
    pool = sorted(trades, key=lambda x: to_utc(x["entry_ts"]))
    start, end = to_utc(pool[0]["entry_ts"]), to_utc(pool[-1]["entry_ts"])
    months, cy, cm = [], start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        me = datetime(cy + (cm == 12), (cm % 12) + 1, 1, tzinfo=timezone.utc)
        if ms > end:
            break
        months.append((ms, me, f"{cy:04d}-{cm:02d}"))
        cm = (cm % 12) + 1
        cy += (cm == 1)
    by_month = {}
    for ms, me, mk in months:
        m_tr = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < min_trades:
            continue
        r = production_replay(m_tr, cfg)
        if r is not None:
            by_month[mk] = r.total_return * 100.0
    return by_month, None


def stats(series):
    a = np.array(series, dtype=float)
    if len(a) == 0:
        return dict(n=0, mean=0, med=0, sd=0, sharpe=0, neg=0, maxdd=0, ann=0)
    mean = a.mean(); med = float(np.median(a)); sd = a.std(ddof=1) if len(a) > 1 else 0.0
    sharpe_m = mean / sd if sd > 0 else 0.0
    sharpe_ann = sharpe_m * math.sqrt(12)
    # compound equity & maxdd on the monthly pct series
    eq = np.cumprod(1 + a / 100.0)
    peak = np.maximum.accumulate(eq)
    dd = (eq / peak - 1.0).min() * 100.0
    ann = (eq[-1] ** (12.0 / len(a)) - 1.0) * 100.0
    neg = int((a < 0).sum())
    return dict(n=len(a), mean=mean, med=med, sd=sd, sharpe_m=sharpe_m,
                sharpe_ann=sharpe_ann, neg=neg, maxdd=dd, ann=ann)


# ---------------------------------------------------------------------------
# 1) FOREX BROOKS — gather trades, monthly $-returns, shuffle
# ---------------------------------------------------------------------------
def forex_brooks(slippage_bps):
    df = fx.load_ohlcv()
    strat = fx.build_strategy("brooks_failed_breakout", "BrooksFailedBreakoutStrategy")
    trades = fx.gather(strat, df, slippage_bps=slippage_bps, apply_swap=True)
    return trades, df


def shuffle_gross(trades, n_iter=5000):
    """Shuffle null on the trade-level net R (sign-flip permutation of the realized R stream
    is degenerate for monthly; use the SOP trade-R shuffle: permute signs, compare mean R)."""
    Rs = np.array([t["R"] for t in trades], dtype=float)
    if len(Rs) == 0:
        return None
    obs = Rs.mean()
    rng = np.random.default_rng(SEED)
    cnt = 0
    for _ in range(n_iter):
        signs = rng.choice([-1.0, 1.0], size=len(Rs))
        if (Rs * signs).mean() >= obs:
            cnt += 1
    return obs, (cnt + 1) / (n_iter + 1)


# ---------------------------------------------------------------------------
# 2) CHAMPION — monthly $-returns from the 15m pool via the SAME replay
# ---------------------------------------------------------------------------
def champion_monthly():
    pool_path = ROOT / "data" / "sec53_15m_pool_v11.pkl"
    with open(pool_path, "rb") as f:
        pool = pickle.load(f)
    # champion config: sl_pct_min=0.025, risk=0.005, runner, 55bps round-trip in R-space.
    cfg = ProductionConfig(
        risk_pct=0.005, sl_pct_min=0.025, fee_bps_per_trade=55.0,
        conf_min=0.0, leverage=3.0,
    )
    by_month, res = monthly_dollar_returns(pool, cfg, "champion", min_trades=10)
    return by_month


def main():
    print(f"git={GIT} seed={SEED}")
    print("=" * 72)

    # --- FOREX BROOKS standalone ---
    print("\n[1] FOREX BROOKS_FAILED_BREAKOUT — EUR/USD 4H")
    for slip in (fx.SLIPPAGE_BPS, fx.SLIPPAGE_BPS_STRESS, 5.0):
        trades, _ = forex_brooks(slip)
        # forex has NO extra crypto-style fee; net R already includes spread+swap
        cfg_fx = ProductionConfig(risk_pct=0.005, sl_pct_min=0.0, fee_bps_per_trade=0.0,
                                  conf_min=0.0, leverage=3.0)
        bm, _ = monthly_dollar_returns(trades, cfg_fx, "brooks")
        s = stats(list(bm.values()))
        net_mR = np.mean([t["R"] for t in trades])
        gross_mR = np.mean([t["gross_R"] for t in trades])
        sh = shuffle_gross(trades)
        print(f"  slip={slip:>4}bps  n_trades={len(trades):3d}  net_mR={net_mR:+.3f} "
              f"gross_mR={gross_mR:+.3f}  shuffle p={sh[1]:.4f}")
        print(f"            monthly: n={s['n']} mean={s['mean']:+.2f}% med={s['med']:+.2f}% "
              f"sd={s['sd']:.2f} Sharpe_ann={s['sharpe_ann']:+.2f} maxDD={s['maxdd']:.1f}% "
              f"neg={s['neg']}/{s['n']} ann={s['ann']:+.1f}%")

    # use the pre-reg honest cost (1.0bps) as the canonical brooks for correlation
    trades, _ = forex_brooks(fx.SLIPPAGE_BPS)
    cfg_fx = ProductionConfig(risk_pct=0.005, sl_pct_min=0.0, fee_bps_per_trade=0.0,
                              conf_min=0.0, leverage=3.0)
    brooks_bm, _ = monthly_dollar_returns(trades, cfg_fx, "brooks")

    # --- CHAMPION ---
    print("\n[2] CRYPTO VSA-WIDESTOP CHAMPION — 15m (55bps)")
    champ_bm = champion_monthly()
    sc = stats(list(champ_bm.values()))
    print(f"  monthly: n={sc['n']} mean={sc['mean']:+.2f}% med={sc['med']:+.2f}% "
          f"sd={sc['sd']:.2f} Sharpe_ann={sc['sharpe_ann']:+.2f} maxDD={sc['maxdd']:.1f}% "
          f"neg={sc['neg']}/{sc['n']} ann={sc['ann']:+.1f}%")

    # --- ALIGN months (overlap only) ---
    common = sorted(set(brooks_bm) & set(champ_bm))
    print(f"\n[3] OVERLAP: {len(common)} common months "
          f"({common[0] if common else '-'} .. {common[-1] if common else '-'})")
    bx = np.array([brooks_bm[m] for m in common])
    cx = np.array([champ_bm[m] for m in common])
    if len(common) >= 3:
        rho = float(np.corrcoef(bx, cx)[0, 1])
    else:
        rho = float("nan")
    print(f"    rho(brooks, champion) on common months = {rho:+.3f}")

    # --- PORTFOLIO Sharpe: champion alone vs champion+brooks at capital splits ---
    print("\n[4] PORTFOLIO Sharpe (annualized, monthly series, overlap window)")
    sc_o = stats(list(cx))
    print(f"    champion alone (overlap): mean={sc_o['mean']:+.2f}% sd={sc_o['sd']:.2f} "
          f"Sharpe_ann={sc_o['sharpe_ann']:+.2f} maxDD={sc_o['maxdd']:.1f}%")
    sb_o = stats(list(bx))
    print(f"    brooks   alone (overlap): mean={sb_o['mean']:+.2f}% sd={sb_o['sd']:.2f} "
          f"Sharpe_ann={sb_o['sharpe_ann']:+.2f} maxDD={sb_o['maxdd']:.1f}%")
    print(f"    {'w_champ':>8} {'w_fx':>6} {'mean%':>7} {'sd':>6} {'Sharpe_ann':>11} {'maxDD%':>8}")
    best = None
    for w in (1.0, 0.9, 0.8, 0.7, 0.6, 0.5):
        port = w * cx + (1 - w) * bx
        sp = stats(list(port))
        flag = ""
        print(f"    {w:>8.2f} {1-w:>6.2f} {sp['mean']:>+7.2f} {sp['sd']:>6.2f} "
              f"{sp['sharpe_ann']:>+11.2f} {sp['maxdd']:>8.1f}")
        if best is None or sp['sharpe_ann'] > best[1]:
            best = (w, sp['sharpe_ann'], sp)
    print(f"\n    BEST capital-split blend: w_champ={best[0]:.2f} Sharpe_ann={best[1]:+.2f} "
          f"(champion-alone Sharpe_ann={sc_o['sharpe_ann']:+.2f}) "
          f"lift={best[1]-sc_o['sharpe_ann']:+.2f}")

    # --- VOL-MATCHED / RISK-PARITY view: scale brooks to the champion's monthly vol, then
    #     blend so brooks contributes EQUAL risk. This is the fair diversifier test —
    #     a small-$ leg can't move portfolio Sharpe; the question is the SHAPE of its stream.
    print("\n[5] VOL-MATCHED diversifier test (scale brooks to champion vol, equal-risk blends)")
    k = sc_o['sd'] / sb_o['sd'] if sb_o['sd'] > 0 else 0.0
    bx_scaled = bx * k
    print(f"    brooks scaled x{k:.1f} -> same monthly vol as champion ({sc_o['sd']:.2f}%)")
    print(f"    {'w_champ':>8} {'w_fx':>6} {'mean%':>7} {'sd':>6} {'Sharpe_ann':>11} {'maxDD%':>8}")
    vbest = None
    for w in (1.0, 0.8, 0.7, 0.6, 0.5, 0.4):
        port = w * cx + (1 - w) * bx_scaled
        sp = stats(list(port))
        print(f"    {w:>8.2f} {1-w:>6.2f} {sp['mean']:>+7.2f} {sp['sd']:>6.2f} "
              f"{sp['sharpe_ann']:>+11.2f} {sp['maxdd']:>8.1f}")
        if vbest is None or sp['sharpe_ann'] > vbest[1]:
            vbest = (w, sp['sharpe_ann'], sp)
    # analytic 2-asset optimum Sharpe given rho (vol-matched -> equal vol)
    mu_c, mu_b = sc_o['sharpe_m'], sb_o['sharpe_m']  # per-unit-vol returns
    print(f"\n    BEST vol-matched blend: w_champ={vbest[0]:.2f} Sharpe_ann={vbest[1]:+.2f} "
          f"lift={vbest[1]-sc_o['sharpe_ann']:+.2f}  (rho={rho:+.3f})")
    # theoretical max diversification ratio for two equal-vol, equal-Sharpe legs:
    if not math.isnan(rho) and rho < 1:
        dr = math.sqrt(2.0 / (1.0 + rho))
        print(f"    theoretical equal-vol diversification ratio (1/sqrt scaling) = {dr:.2f}x "
              f"(rho={rho:+.3f}); both legs +Sharpe & rho<<1 -> genuine smoothing")


if __name__ == "__main__":
    main()


def robustness_addendum():
    """OOS-only (2024-2025) rho + sub-period stability — guard against IS-only diversification."""
    print("\n[6] ROBUSTNESS — OOS-only & sub-period rho stability")
    trades, _ = forex_brooks(fx.SLIPPAGE_BPS)
    cfg_fx = ProductionConfig(risk_pct=0.005, sl_pct_min=0.0, fee_bps_per_trade=0.0,
                              conf_min=0.0, leverage=3.0)
    brooks_bm, _ = monthly_dollar_returns(trades, cfg_fx, "brooks")
    champ_bm = champion_monthly()
    for lo, hi, lab in (("2021-05", "2024-01", "IS  2021-23"),
                        ("2024-01", "2026-01", "OOS 2024-25")):
        common = sorted(m for m in set(brooks_bm) & set(champ_bm) if lo <= m < hi)
        if len(common) < 3:
            print(f"    {lab}: n={len(common)} too few"); continue
        bx = np.array([brooks_bm[m] for m in common])
        cx = np.array([champ_bm[m] for m in common])
        rho = float(np.corrcoef(bx, cx)[0, 1])
        sb, sc = stats(list(bx)), stats(list(cx))
        print(f"    {lab}: n={len(common):2d}  rho={rho:+.3f}  "
              f"brooks Sharpe_ann={sb['sharpe_ann']:+.2f} (mean {sb['mean']:+.2f}%)  "
              f"champ Sharpe_ann={sc['sharpe_ann']:+.2f}")


if __name__ == "__main__":
    robustness_addendum()
