"""CROSS-ASSET portfolio: FX brooks (right-skew momentum) + HONEST crypto edge.

Honesty rules (adversary lessons):
  - iid Monte Carlo BANNED. Only realized-path contMaxDD + block-bootstrap (20-trade blocks).
  - Report raw median AND winner-stripped (top-5% months removed) median.
  - Crypto fee model HONEST: trades use widestop (sl_pct>=2.5%) filter and an
    explicit round-trip taker fee converted to R via fee_R = fee_pct / sl_pct.
  - Common-mode awareness: crisis-month correlation check between FX and crypto.

Equity model = COMPOUNDED, fixed-notional per leg (sequential, risk_pct of running equity).
Monthly returns from the compounded equity curve. Risk-parity = scale each sleeve's
risk_pct so that each contributes equal realized monthly STD over the common window.
"""
from __future__ import annotations
import pickle
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SEED = 12345

# crisis months (UTC month-ends) from brief
CRISIS = {
    "2021-05 China ban": "2021-05",
    "2022-05 LUNA": "2022-05",
    "2022-06 3AC/Celsius": "2022-06",
    "2022-11 FTX": "2022-11",
    "2024-03 BTC ATH": "2024-03",
    "2024-08 Yen carry": "2024-08",
}


def fee_R(sl_pct: np.ndarray, fee_bps: float) -> np.ndarray:
    return (fee_bps / 10000.0) / np.clip(sl_pct, 1e-4, None)


def load_fx():
    d = pickle.load(open("/tmp/rt_trades.pkl", "rb"))
    tr = d["trades"]
    rows = []
    # risk-parity inside FX: halve AUD/NZD (per honest_cap)
    block = {"AUD/USD", "NZD/USD"}
    for s, lst in tr.items():
        sc = 0.5 if s in block else 1.0
        for t in lst:
            rows.append({"entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
                         "R": t["R"] * sc, "symbol": s, "side": t["side"]})
    df = pd.DataFrame(rows)
    df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True)
    df["exit_ts"] = pd.to_datetime(df["exit_ts"], utc=True)
    return df.sort_values("entry_ts").reset_index(drop=True)


def usd_dir(sym, side):
    is_long = side == "long"
    if sym.endswith("/USD"):
        return -1 if is_long else +1
    if sym.startswith("USD/"):
        return +1 if is_long else -1
    return 0


def fx_net_usd_cap(df, cap=3, gross=6):
    """CAUSAL net-USD exposure cap (reproduce honest_cap netUSD<=3)."""
    open_pos = []
    keep = []
    for _, t in df.iterrows():
        now = t["entry_ts"]
        open_pos = [p for p in open_pos if p["exit_ts"] > now]
        if len(open_pos) >= gross:
            continue
        u = usd_dir(t["symbol"], t["side"])
        cur = sum(p["usd"] for p in open_pos)
        if abs(cur + u) > cap:
            continue
        open_pos.append({"exit_ts": t["exit_ts"], "usd": u})
        keep.append(t)
    return pd.DataFrame(keep).reset_index(drop=True)


def load_crypto(strategy, fee_bps, widestop=0.025, max_concurrent=8):
    d = pickle.load(open("data/sec53_15m_pool_v11.pkl", "rb"))
    df = pd.DataFrame([t for t in d if t["strategy"] == strategy])
    df["entry_ts"] = pd.to_datetime(df["entry_ts"], utc=True)
    df["exit_ts"] = pd.to_datetime(df["exit_ts"], utc=True)
    df["sl_pct"] = (df["entry_price"] - df["initial_sl"]).abs() / df["entry_price"]
    if widestop:
        df = df[df["sl_pct"] >= widestop].copy()
    df = df.sort_values("entry_ts").reset_index(drop=True)
    # honest net R after fee
    df["R"] = df["R"] - fee_R(df["sl_pct"].values, fee_bps)
    # causal concurrency cap (symbol-blind, like prod replay)
    open_exit = []
    keep_idx = []
    for i, t in enumerate(df.itertuples()):
        now = t.entry_ts
        open_exit = [e for e in open_exit if e > now]
        if len(open_exit) >= max_concurrent:
            continue
        open_exit.append(t.exit_ts)
        keep_idx.append(i)
    df = df.iloc[keep_idx].reset_index(drop=True)
    return df[["entry_ts", "exit_ts", "R", "symbol", "side", "sl_pct"]]


def compound_equity(df, risk_pct, init=10000.0):
    """Sequential compounded equity; trades applied at exit_ts order? Use entry order
    (causal), book pnl at exit_ts for monthly bucketing."""
    df = df.sort_values("entry_ts")
    eq = init
    rows = []
    for r, xts in zip(df["R"].values, df["exit_ts"].values):
        eq += eq * risk_pct * r
        rows.append((xts, eq))
    s = pd.Series([e for _, e in rows], index=pd.to_datetime([x for x, _ in rows], utc=True)).sort_index()
    return s


def monthly_ret(eq, init=10000.0):
    if eq.empty:
        return pd.Series(dtype=float)
    me = eq.resample("ME").last().dropna()
    prev = pd.Series([init] + list(me.values[:-1]), index=me.index)
    return (me / prev - 1.0) * 100.0


def realized_contmaxdd(eq, init=10000.0):
    arr = np.concatenate([[init], eq.values])
    peak = np.maximum.accumulate(arr)
    return float(((arr - peak) / peak).min() * 100)


def block_bootstrap_dd(Rs, risk_pct, block=20, n_paths=4000, seed=777):
    rng = np.random.default_rng(seed)
    a = np.asarray(Rs, float)
    n = len(a)
    if n < block:
        block = max(1, n)
    nb = int(np.ceil(n / block))
    dds = []
    for _ in range(n_paths):
        st = rng.integers(0, n - block + 1, size=nb)
        path = np.concatenate([a[s:s + block] for s in st])[:n]
        eq = np.cumprod(1.0 + risk_pct * path)
        eq = np.concatenate([[1.0], eq])
        peak = np.maximum.accumulate(eq)
        dds.append(((eq - peak) / peak).min())
    dds = np.array(dds) * 100
    return float(np.median(dds)), float(np.percentile(dds, 5)), float(np.percentile(dds, 95))


def profile_monthly(mr, eq, Rs, risk_pct, init=10000.0):
    if mr.empty:
        return None
    raw_med = float(mr.median())
    k = max(1, int(np.ceil(len(mr) * 0.05)))
    ws = mr.sort_values()[:-k] if k < len(mr) else mr
    bb_med, bb_p05, bb_p95 = block_bootstrap_dd(Rs, risk_pct)
    return {
        "n_mo": len(mr), "mean": float(mr.mean()), "median": raw_med,
        "ws_median": float(ws.median()), "std": float(mr.std()),
        "neg": float((mr < 0).mean()) * 100, "worst": float(mr.min()),
        "best": float(mr.max()),
        "real_dd": realized_contmaxdd(eq, init),
        "bb_p05_dd": bb_p05,
        "sharpe": float(mr.mean() / mr.std()) if mr.std() > 0 else 0.0,
        "final_x": float(eq.iloc[-1] / init),
        "_mr": mr,
    }


def equalize_window(mr_a, mr_b):
    """common month index."""
    idx = mr_a.index.intersection(mr_b.index)
    return mr_a.reindex(idx).fillna(0.0), mr_b.reindex(idx).fillna(0.0)


def main():
    print("=" * 100)
    print("CROSS-ASSET PORTFOLIO — FX brooks (right-skew) + HONEST crypto edge")
    print("=" * 100)

    # ---- FX sleeve: netUSD<=3, eff_r 1.0% ----
    fx = load_fx()
    fx = fx_net_usd_cap(fx, cap=3, gross=6)
    FX_R = 0.010
    fx_eq = compound_equity(fx, FX_R)
    fx_mr = monthly_ret(fx_eq)
    fx_p = profile_monthly(fx_mr, fx_eq, fx["R"].values, FX_R)
    print(f"\n[FX] netUSD<=3 eff_r={FX_R*100:.1f}%  n_tr={len(fx)}  "
          f"skew={((fx['R']-fx['R'].mean())**3).mean()/fx['R'].std()**3:+.2f}")

    # ---- Crypto sleeve candidates (HONEST, widestop, 55bps conservative) ----
    FEE = 55.0
    candidates = {
        "vsa_climax (live, skewHi)": "vsa_climax_test",
        "anchored_vwap (lowSkew)": "anchored_vwap_reversal",
        "brooks_fb (skewHi)": "brooks_failed_breakout",
    }
    crypto_data = {}
    print(f"\nCrypto honest model: widestop sl_pct>=2.5%, fee={FEE}bps RT taker, max_concurrent=8")
    for label, strat in candidates.items():
        cdf = load_crypto(strat, FEE)
        sk = ((cdf['R'] - cdf['R'].mean())**3).mean() / cdf['R'].std()**3
        crypto_data[label] = cdf
        print(f"  {label:28} n_tr={len(cdf):>6} netMeanR={cdf['R'].mean():+.4f} skew={sk:+.2f}")

    # pick crypto sleeve risk so 5y compound is comparable; sweep eff_r later.
    print("\n" + "=" * 100)
    print("(a) STANDALONE SLEEVES — honest monthly distribution (eff_r chosen per sleeve)")
    print("=" * 100)
    hdr = f"{'sleeve':<30}{'eff_r':>6}{'med%':>7}{'wsMed%':>8}{'mean%':>7}{'STD%':>7}{'neg%':>6}{'realDD%':>9}{'bbP05%':>9}{'Shrp':>7}{'final_x':>9}"
    print(hdr); print("-" * len(hdr))
    sleeves = {}
    # FX
    print(f"{'FX brooks netUSD<=3':<30}{FX_R*100:>5.1f}%{fx_p['median']:>+6.2f}%{fx_p['ws_median']:>+7.2f}%"
          f"{fx_p['mean']:>+6.2f}%{fx_p['std']:>6.2f}%{fx_p['neg']:>5.0f}%{fx_p['real_dd']:>+8.1f}%"
          f"{fx_p['bb_p05_dd']:>+8.1f}%{fx_p['sharpe']:>+6.2f}{fx_p['final_x']:>8.1f}x")
    sleeves["FX"] = (fx, FX_R, fx_p)
    # crypto each at eff_r that gives sane sizing — use 0.5% (matches rsi2/vsa risk_per_trade)
    CR = 0.005
    for label, cdf in crypto_data.items():
        ceq = compound_equity(cdf, CR)
        cmr = monthly_ret(ceq)
        cp = profile_monthly(cmr, ceq, cdf["R"].values, CR)
        sleeves[label] = (cdf, CR, cp)
        print(f"{label:<30}{CR*100:>5.1f}%{cp['median']:>+6.2f}%{cp['ws_median']:>+7.2f}%"
              f"{cp['mean']:>+6.2f}%{cp['std']:>6.2f}%{cp['neg']:>5.0f}%{cp['real_dd']:>+8.1f}%"
              f"{cp['bb_p05_dd']:>+8.1f}%{cp['sharpe']:>+6.2f}{cp['final_x']:>8.1f}x")

    # ---- (b) CORRELATIONS FX vs each crypto (monthly R, common window) ----
    print("\n" + "=" * 100)
    print("(b) FX vs CRYPTO MONTHLY-R CORRELATION (common window) + crisis-month behavior")
    print("=" * 100)
    for label, (cdf, cr, cp) in sleeves.items():
        if label == "FX":
            continue
        a, b = equalize_window(fx_p["_mr"], cp["_mr"])
        if len(a) < 6:
            continue
        rho = float(np.corrcoef(a.values, b.values)[0, 1])
        # crisis months
        crisis_pairs = []
        for cname, cm in CRISIS.items():
            ts = pd.Timestamp(cm + "-01", tz="UTC") + pd.offsets.MonthEnd(0)
            if ts in a.index:
                crisis_pairs.append((cname, float(a.loc[ts]), float(b.loc[ts])))
        print(f"\n  FX  vs  {label}:  rho={rho:+.3f}  (n_common_months={len(a)})")
        print(f"    {'crisis month':<24}{'FX%':>9}{'crypto%':>10}{'same-sign?':>12}")
        cc = 0
        for cn, fv, cv in crisis_pairs:
            same = (fv < 0 and cv < 0)
            cc += same
            print(f"    {cn:<24}{fv:>+8.2f}%{cv:>+9.2f}%{('BOTH DOWN' if same else 'diverge'):>12}")
        if crisis_pairs:
            print(f"    -> both-down in {cc}/{len(crisis_pairs)} crisis months "
                  f"(convergence risk {'HIGH' if cc>len(crisis_pairs)/2 else 'moderate/low'})")

    # ---- (c) CROSS-ASSET PORTFOLIO (risk-parity) ----
    print("\n" + "=" * 100)
    print("(c) CROSS-ASSET PORTFOLIO  FX + crypto, RISK-PARITY (equal monthly-STD contribution)")
    print("=" * 100)
    # For each crypto candidate, build a risk-parity blended monthly-R on the common window.
    # Risk-parity weight w_fx, w_cr so that w_fx*std_fx = w_cr*std_cr, w_fx+w_cr=1.
    phdr = (f"{'portfolio (FX + X)':<32}{'med%':>7}{'wsMed%':>8}{'mean%':>7}{'STD%':>7}"
            f"{'neg%':>6}{'realDD%':>9}{'bbP05%':>9}{'Shrp':>7}{'wFX/wCR':>10}")
    print(phdr); print("-" * len(phdr))
    # FX-only baseline on common windows reported per candidate for fair compare
    portfolios = {}
    for label, (cdf, cr, cp) in sleeves.items():
        if label == "FX":
            continue
        a, b = equalize_window(fx_p["_mr"], cp["_mr"])  # monthly % returns
        sa, sb = a.std(), b.std()
        # risk parity weights
        wa = (1 / sa) / ((1 / sa) + (1 / sb))
        wb = 1 - wa
        port = wa * a + wb * b
        # rebuild portfolio equity to get realized DD + block bootstrap of blended monthly
        peq = (1 + port / 100.0).cumprod() * 10000.0
        real_dd = realized_contmaxdd(peq)
        # block-bootstrap on monthly returns (block=6 months ~ regime cluster)
        rng = np.random.default_rng(SEED)
        m = port.values / 100.0
        n = len(m); blk = 6; nb = int(np.ceil(n / blk))
        dds = []
        for _ in range(4000):
            st = rng.integers(0, max(1, n - blk + 1), size=nb)
            path = np.concatenate([m[s:s + blk] for s in st])[:n]
            eq = np.concatenate([[1.0], np.cumprod(1 + path)])
            pk = np.maximum.accumulate(eq)
            dds.append(((eq - pk) / pk).min())
        bb_p05 = float(np.percentile(np.array(dds) * 100, 5))
        k = max(1, int(np.ceil(len(port) * 0.05)))
        ws = port.sort_values()[:-k]
        portfolios[label] = port
        print(f"{'FX + ' + label:<32}{port.median():>+6.2f}%{ws.median():>+7.2f}%"
              f"{port.mean():>+6.2f}%{port.std():>6.2f}%{(port < 0).mean()*100:>5.0f}%"
              f"{real_dd:>+8.1f}%{bb_p05:>+8.1f}%{port.mean()/port.std():>+6.2f}"
              f"{wa:>6.2f}/{wb:.2f}")

    # ---- (d) HEAD-TO-HEAD: FX-only vs best cross-asset, SAME common window ----
    print("\n" + "=" * 100)
    print("(d) FX-ONLY vs CROSS-ASSET  (best blend = lowest-corr crypto), identical window")
    print("=" * 100)
    # choose best blend = the one minimizing portfolio STD with positive mean
    best = None
    for label, port in portfolios.items():
        a, b = equalize_window(fx_p["_mr"], sleeves[label][2]["_mr"])
        fx_only = a  # fx monthly on common window
        score = port.std()
        if best is None or (port.mean() > 0 and score < best[1]):
            best = (label, score, port, fx_only)
    label, _, port, fx_only = best
    def line(name, s):
        k = max(1, int(np.ceil(len(s) * 0.05)))
        ws = s.sort_values()[:-k]
        peq = (1 + s / 100).cumprod() * 10000
        return (f"{name:<26}med={s.median():+6.2f}% wsMed={ws.median():+6.2f}% mean={s.mean():+6.2f}% "
                f"STD={s.std():5.2f}% neg={(s<0).mean()*100:4.0f}% realDD={realized_contmaxdd(peq):+6.1f}% "
                f"Sharpe={s.mean()/s.std():+5.2f} best_mo={s.max():+6.1f}% worst_mo={s.min():+6.1f}%")
    print("  Common window:", fx_only.index.min().date(), "->", fx_only.index.max().date(), f"(n={len(fx_only)} months)")
    print("  " + line("FX-ONLY", fx_only))
    print("  " + line(f"CROSS (FX+{label})", port))
    dstd = (port.std() - fx_only.std()) / fx_only.std() * 100
    dsharpe = port.mean()/port.std() - fx_only.mean()/fx_only.std()
    print(f"\n  --> STD change: {dstd:+.1f}%   Sharpe change: {dsharpe:+.2f}   "
          f"range compression (max-min): FX-only {fx_only.max()-fx_only.min():.1f}pp vs CROSS {port.max()-port.min():.1f}pp")

    print("\nDONE.")


if __name__ == "__main__":
    main()
