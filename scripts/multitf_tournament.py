"""Lab tournament: CHAMPION (15m single-TF BASELINE) vs CHALLENGER (5m+15m+30m+45m stack).

Both at TRUE fee PA_FEE_RT_BPS=18, BASELINE exit, WIDESTOP sl_pct_min=0.025, risk 0.5%.
Reuses v9_multitf_truefee harness verbatim (real BacktestEngine + production_replay).

Adds the SKEW-AWARE, MULTIPLE-TESTING-CORRECT tournament gates the broken shuffle_p can't give:
  - Welch's t-test on champion vs challenger MONTHLY returns (effect + p)
  - sign-flip / sign-randomization p_gross (zero-centered null) on per-trade R
  - one-sample t on per-trade R
  - DSR (Deflated Sharpe Ratio) with n_trials deflation for the multi-TF search
  - PBO (prob. of backtest overfit) via combinatorially-symmetric cross-validation on monthly blocks
  - regime coverage (BTC realized-vol tertiles), top-5% R-share, median monthly
  - fee-vs-stacking edge decomposition

Usage: PA_FEE_RT_BPS=18 .venv/bin/python scripts/multitf_tournament.py
"""
from __future__ import annotations
import os, sys, json, itertools
from pathlib import Path
os.environ["PA_DUCKDB_READ_ONLY"] = "true"
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)
import numpy as np, pandas as pd
from scipy import stats as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
import importlib.util
spec = importlib.util.spec_from_file_location("v9", str(ROOT / "scripts" / "v9_multitf_truefee.py"))
v9 = importlib.util.module_from_spec(spec); spec.loader.exec_module(v9)

SEED = 12345
FEE = float(os.environ.get("PA_FEE_RT_BPS", "18"))


# ---- correct zero-centered nulls (NOT the broken bootstrap-around-mean shuffle_p) ----
def sign_flip_p(Rs, n_iter=20000, seed=SEED):
    a = np.array(Rs, float)
    if len(a) < 5:
        return 1.0
    obs = a.mean(); n = len(a)
    rng = np.random.default_rng(seed)
    null = (rng.choice([-1.0, 1.0], size=(n_iter, n)) * a).mean(axis=1)
    return (np.sum(null >= obs) + 1) / (n_iter + 1)


def deflated_sharpe(monthly_pct, n_trials, sr_benchmark=0.0):
    """DSR per Bailey & Lopez de Prado. monthly_pct in %; annualize x sqrt(12).
    Deflates the observed Sharpe by the expected max Sharpe of n_trials independent
    bets, accounting for skew/kurtosis of the monthly stream. Returns (SR_ann, DSR_prob)."""
    r = np.array(monthly_pct, float) / 100.0
    n = len(r)
    if n < 8 or r.std() == 0:
        return 0.0, 0.0
    sr_m = r.mean() / r.std()                       # monthly Sharpe
    sr_ann = sr_m * np.sqrt(12)
    g3 = st.skew(r); g4 = st.kurtosis(r, fisher=False)
    # expected max of n_trials std-normals (Bailey-LdP approx)
    emc = 0.5772156649
    e_max = (1 - emc) * st.norm.ppf(1 - 1.0 / n_trials) + emc * st.norm.ppf(1 - 1.0 / (n_trials * np.e))
    sr0_m = (r.std() and (e_max / np.sqrt(n)))      # benchmark monthly SR threshold from selection
    # PSR/DSR statistic: prob observed SR exceeds the selection benchmark
    num = (sr_m - sr0_m) * np.sqrt(n - 1)
    den = np.sqrt(1 - g3 * sr_m + (g4 - 1) / 4.0 * sr_m**2)
    z = num / den if den > 0 else 0.0
    dsr = st.norm.cdf(z)
    return float(sr_ann), float(dsr)


def pbo(monthly_pct_champ, monthly_pct_chall, n_splits=16, seed=SEED):
    """Prob. of backtest overfit: split months into S blocks, for each combinatorial
    train/test partition, pick the in-sample winner, check if it stays >median out-of-sample.
    Returns fraction of partitions where IS-winner under-performs OOS (logit<0 rate)."""
    a = np.array(monthly_pct_champ, float); b = np.array(monthly_pct_chall, float)
    m = min(len(a), len(b))
    a, b = a[:m], b[:m]
    if m < n_splits:
        n_splits = (m // 2) * 2
    if n_splits < 4:
        return float("nan")
    idx = np.array_split(np.arange(m), n_splits)
    blocks = list(range(n_splits))
    half = n_splits // 2
    lam = []
    for tr in itertools.combinations(blocks, half):
        tr = set(tr); te = [x for x in blocks if x not in tr]
        tri = np.concatenate([idx[i] for i in tr]); tei = np.concatenate([idx[i] for i in te])
        # in-sample Sharpe of each strategy
        sa_is, sb_is = a[tri].mean() / (a[tri].std() or 1), b[tri].mean() / (b[tri].std() or 1)
        win_is = "b" if sb_is >= sa_is else "a"          # IS winner
        sa_oos, sb_oos = a[tei].mean() / (a[tei].std() or 1), b[tei].mean() / (b[tei].std() or 1)
        # rank of IS-winner OOS among {a,b}: is it the OOS winner too?
        oos_ranks = {"a": sa_oos, "b": sb_oos}
        rel = oos_ranks[win_is] - np.median(list(oos_ranks.values()))
        lam.append(1.0 if rel < 0 else 0.0)
    return float(np.mean(lam)) if lam else float("nan")


def main():
    print("=" * 96)
    print(f"TOURNAMENT  CHAMPION(15m-19sym) vs CHALLENGER(5m+15m+30m+45m)  @ {FEE}bps  BASELINE exit")
    print("=" * 96)

    # ---------- gather legs (reuse v9) ----------
    print("gathering 5m,15m(10),1h,4h native ...")
    p05 = v9.gather_native(v9.SYMS10, "5m")
    p15_10 = v9.gather_native(v9.SYMS10, "15m")
    print("gathering 15m on full 19-sym (champion + deploy leg) ...")
    p15_19 = v9.gather_native(v9.SYMS19, "15m")
    print("resampling 30m, 45m ...")
    p30 = v9.gather_resampled(v9.SYMS10, "30min", "30m")
    p45 = v9.gather_resampled(v9.SYMS10, "45min", "45m")
    print(f"  n: 5m={len(p05)} 15m10={len(p15_10)} 15m19={len(p15_19)} 30m={len(p30)} 45m={len(p45)}")

    # CHAMPION = 15m single-TF, full 19-sym (the deployable incumbent at true fee, BASELINE)
    champ = sorted(p15_19, key=lambda x: x["entry_ts"])
    # CHALLENGER = pooled 5m+15m(19sym)+30m+45m
    chall = sorted(p05 + p15_19 + p30 + p45, key=lambda x: x["entry_ts"])

    def profile(pool, lev=1.0):
        ms, dd = v9.monthly_series(pool, lev)
        s = v9.stats(ms)
        R = np.array([t["R"] for t in pool], float)
        top5_share = np.sort(R)[int(0.95 * len(R)):].sum() / R.sum() if R.sum() > 0 else float("nan")
        return ms, dd, s, R, top5_share

    cm_ms, cm_dd, cm_s, cm_R, cm_top5 = profile(champ)
    ch_ms, ch_dd, ch_s, ch_R, ch_top5 = profile(chall)

    print("\n--- HEADLINE PROFILES (unlevered, 18bps, BASELINE) ---")
    for nm, s, dd, R, t5, ms in [("CHAMP 15m", cm_s, cm_dd, cm_R, cm_top5, cm_ms),
                                 ("CHALL stack", ch_s, ch_dd, ch_R, ch_top5, ch_ms)]:
        print(f"  {nm:<12} n_tr={len(R):>6} n_mo={s['n']:>3} mean={s['mean']:+.2f}%/mo "
              f"med={s['med']:+.2f}% pos={s['pos']:.0f}% min={s['mn']:+.2f}% "
              f"MaxDD={dd:+.1f}% Sharpe={s['sharpe']:+.2f} top5%Rshare={t5*100:.1f}%")

    # ---------- GATE 1: effect vs champion (Welch on monthly) ----------
    # align on common months for a paired-ish comparison; Welch on the two monthly samples
    eff_pct = (ch_s['mean'] - cm_s['mean']) / abs(cm_s['mean']) * 100
    t_w, p_w = st.ttest_ind(ch_ms.values, cm_ms.values, equal_var=False)
    med_eff = (ch_s['med'] - cm_s['med']) / abs(cm_s['med']) * 100
    print("\n--- GATE 1: effect & Welch (monthly returns) ---")
    print(f"  mean effect = {eff_pct:+.1f}% over champion (need >=+15%)  | median effect = {med_eff:+.1f}%")
    print(f"  Welch t={t_w:+.2f}  p={p_w:.4f}")

    # ---------- GATE 2: gross edge null (sign-flip + t) on challenger R ----------
    sf_ch = sign_flip_p(ch_R); t_ch, pt_ch = st.ttest_1samp(ch_R, 0.0)
    sf_cm = sign_flip_p(cm_R); t_cm, pt_cm = st.ttest_1samp(cm_R, 0.0)
    print("\n--- GATE 2: zero-centered gross-edge null (CORRECT, not shuffle_p) ---")
    print(f"  CHALL: sign-flip p_gross={sf_ch:.5f}  one-sample t p={pt_ch:.2e}  meanR={ch_R.mean():+.4f}")
    print(f"  CHAMP: sign-flip p_gross={sf_cm:.5f}  one-sample t p={pt_cm:.2e}  meanR={cm_R.mean():+.4f}")

    # ---------- GATE 3: DSR deflated for the multi-TF search ----------
    # n_trials = TF legs searched (5m,15m,30m,45m,1h,4h) x exit-variant family already vetted.
    # The multi-TF search examined 6 candidate legs + greedy adds; be conservative: n_trials.
    for n_trials in (6, 20, 50):
        sr_ann, dsr = deflated_sharpe(ch_ms.values, n_trials)
        print(f"  DSR @ n_trials={n_trials:<3}: SR_ann={sr_ann:.2f}  DSR_prob={dsr:.4f}  "
              f"({'PASS p<0.05' if dsr > 0.95 else 'check'})")

    # ---------- GATE 4: PBO ----------
    pbo_v = pbo(cm_ms.values, ch_ms.values)
    print(f"\n--- GATE 4: PBO (prob backtest overfit) = {pbo_v:.3f}  ({'OK <0.5' if pbo_v < 0.5 else 'HIGH'})")

    # ---------- GATE 5: MaxDD constraint ----------
    print(f"\n--- GATE 5: MaxDD  CHALL={ch_dd:+.1f}%  CHAMP={cm_dd:+.1f}%  "
          f"(need CHALL <= CHAMP+5pp = {cm_dd-5:+.1f}%)")

    # ---------- GATE 6: regime coverage (BTC realized-vol tertiles) ----------
    import duckdb
    con = duckdb.connect(str(ROOT / "data" / "market.duckdb"), read_only=True)
    btc = con.execute("SELECT ts,close FROM ohlcv WHERE venue='binance' AND symbol='BTC/USDT' AND timeframe='15m' ORDER BY ts").fetchdf()
    con.close()
    btc["ts"] = pd.to_datetime(btc["ts"], utc=True); btc = btc.sort_values("ts").reset_index(drop=True)
    btc["ret"] = np.log(btc["close"]).diff(); btc["rv"] = btc["ret"].rolling(96).std()
    btc = btc.dropna(subset=["rv"]); q1, q2 = btc["rv"].quantile([1/3, 2/3])

    def regime_of(ts):
        i = btc["ts"].searchsorted(ts) - 1
        if i < 0 or i >= len(btc):
            return "unk"
        rv = btc["rv"].iloc[i]
        return "range" if rv <= q1 else ("trend" if rv >= q2 else "mid")
    print("\n--- GATE 6: regime coverage (challenger per-trade R) ---")
    reg = {"range": [], "mid": [], "trend": []}
    for t in chall:
        k = regime_of(t["entry_ts"])
        if k in reg:
            reg[k].append(t["R"])
    pos_regimes = 0
    for k in ["range", "mid", "trend"]:
        a = np.array(reg[k])
        ok = len(a) and a.mean() > 0
        pos_regimes += int(ok)
        print(f"  {k:<6} n={len(a):>6} meanR={a.mean():+.3f} sumR={a.sum():+.1f}  {'+' if ok else '-'}")
    print(f"  positive in {pos_regimes}/3 regimes (need >=2)")

    # ---------- DECOMP: fee re-pricing vs multi-TF stacking ----------
    print("\n--- EDGE DECOMPOSITION: fee re-pricing vs multi-TF stacking ---")
    # champion at 55bps (over-conservative) vs 18bps (true): the fee delta
    p15_19_55 = v9.gather_native(v9.SYMS19, "15m", fee_override=55.0)
    _, dd55, s55, _, _ = profile(sorted(p15_19_55, key=lambda x: x["entry_ts"]))
    fee_lift = cm_s['mean'] - s55['mean']
    stack_lift = ch_s['mean'] - cm_s['mean']
    print(f"  champ 15m @55bps = {s55['mean']:+.2f}%/mo   @18bps = {cm_s['mean']:+.2f}%/mo   "
          f"FEE re-pricing lift = {fee_lift:+.2f}pp")
    print(f"  champ 15m @18bps = {cm_s['mean']:+.2f}%/mo   stack @18bps = {ch_s['mean']:+.2f}%/mo   "
          f"MULTI-TF stacking lift = {stack_lift:+.2f}pp")

    # ---------- determinism: re-gather 15m, count off-by-one ----------
    p15_19_b = v9.gather_native(v9.SYMS19, "15m")
    print(f"\n--- determinism: 15m re-gather n={len(p15_19)} vs {len(p15_19_b)} "
          f"(delta={len(p15_19_b)-len(p15_19)}; immaterial if |delta|<=2)")

    out = dict(fee=FEE,
               champ=dict(n=len(cm_R), mean=cm_s['mean'], med=cm_s['med'], pos=cm_s['pos'],
                          mn=cm_s['mn'], dd=cm_dd, sharpe=cm_s['sharpe'], top5=cm_top5,
                          sf=sf_cm, tp=float(pt_cm)),
               chall=dict(n=len(ch_R), mean=ch_s['mean'], med=ch_s['med'], pos=ch_s['pos'],
                          mn=ch_s['mn'], dd=ch_dd, sharpe=ch_s['sharpe'], top5=ch_top5,
                          sf=sf_ch, tp=float(pt_ch)),
               effect_mean=eff_pct, effect_med=med_eff, welch_t=float(t_w), welch_p=float(p_w),
               dsr={str(n): deflated_sharpe(ch_ms.values, n) for n in (6, 20, 50)},
               pbo=pbo_v, fee_lift=fee_lift, stack_lift=stack_lift,
               regime={k: (float(np.mean(reg[k])) if reg[k] else None) for k in reg},
               determinism_delta=len(p15_19_b) - len(p15_19))
    json.dump(out, open("/tmp/multitf_tournament.json", "w"), indent=2, default=str)
    print("\n[dumped /tmp/multitf_tournament.json]")


if __name__ == "__main__":
    main()
