"""CROSS-ASSET v2 — HONEST sizing. Monthly returns built additively (fixed-notional,
risk_pct of INITIAL capital) to avoid the 10^28 fractional-compounding fantasy that the
huge crypto monthly sumR produces. Risk-parity sizes each sleeve so monthly STD matches.

All honesty rules from v1 retained (widestop, 55bps taker, block-bootstrap, winner-stripped,
crisis-month convergence). Adds: per-sleeve risk_pct chosen so each sleeve targets the SAME
monthly STD (true risk parity), then combined; reports FX-only vs CROSS on identical window.
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from cross_asset_portfolio import (load_fx, fx_net_usd_cap, load_crypto, CRISIS)

SEED = 12345


def monthly_sumR(df):
    s = df.set_index("entry_ts")["R"].sort_index()
    return s.resample("ME").sum()


def realized_dd_from_monthly(m_pct):
    eq = (1 + m_pct / 100.0).cumprod()
    eq = np.concatenate([[1.0], eq.values])
    pk = np.maximum.accumulate(eq)
    return float(((eq - pk) / pk).min() * 100)


def block_bootstrap_monthly(m_pct, block=6, n=4000, seed=SEED):
    rng = np.random.default_rng(seed)
    a = m_pct.values / 100.0
    nn = len(a); nb = int(np.ceil(nn / block))
    dds, finals = [], []
    for _ in range(n):
        st = rng.integers(0, max(1, nn - block + 1), size=nb)
        path = np.concatenate([a[s:s + block] for s in st])[:nn]
        eq = np.concatenate([[1.0], np.cumprod(1 + path)])
        pk = np.maximum.accumulate(eq)
        dds.append(((eq - pk) / pk).min())
        finals.append(eq[-1])
    dds = np.array(dds) * 100
    return float(np.percentile(dds, 5)), float(np.percentile(dds, 50))


def stats(name, m, show=True):
    k = max(1, int(np.ceil(len(m) * 0.05)))
    ws = m.sort_values()[:-k]
    bb_p05, bb_med = block_bootstrap_monthly(m)
    d = {
        "name": name, "med": m.median(), "ws_med": ws.median(), "mean": m.mean(),
        "std": m.std(), "neg": (m < 0).mean() * 100, "real_dd": realized_dd_from_monthly(m),
        "bb_p05": bb_p05, "sharpe": m.mean() / m.std() if m.std() > 0 else 0,
        "best": m.max(), "worst": m.min(), "_m": m,
    }
    if show:
        print(f"  {name:<30} med={d['med']:+6.2f}% wsMed={d['ws_med']:+6.2f}% mean={d['mean']:+6.2f}% "
              f"STD={d['std']:5.2f}% neg={d['neg']:4.0f}% realDD={d['real_dd']:+6.1f}% "
              f"bbP05DD={d['bb_p05']:+6.1f}% Shrp={d['sharpe']:+5.2f} [worst {d['worst']:+.1f}% best {d['best']:+.1f}%]")
    return d


def main():
    TARGET_STD = 12.0   # target monthly STD per sleeve for risk parity (% per month)
    print("=" * 108)
    print("CROSS-ASSET v2 — HONEST fixed-notional sizing, RISK-PARITY to equal monthly STD")
    print(f"   target per-sleeve monthly STD = {TARGET_STD}%  | crypto: widestop>=2.5%, 55bps RT taker")
    print("=" * 108)

    # FX sleeve, fixed-notional. eff_r solved to hit TARGET_STD.
    fx = fx_net_usd_cap(load_fx(), cap=3, gross=6)
    fx_sumR = monthly_sumR(fx)
    # monthly% = r * sumR ; std = r * std(sumR) => r = TARGET/std(sumR)
    r_fx = (TARGET_STD / 100.0) / fx_sumR.std()
    fx_m = fx_sumR * r_fx * 100
    print(f"\nFX brooks netUSD<=3: n_tr={len(fx)}  solved eff_r={r_fx*100:.3f}% (to hit {TARGET_STD}% STD)")

    cands = {
        "vsa_climax (live)": "vsa_climax_test",
        "anchored_vwap": "anchored_vwap_reversal",
        "brooks_fb crypto": "brooks_failed_breakout",
    }
    crypto_m = {}
    crypto_r = {}
    for label, strat in cands.items():
        cdf = load_crypto(strat, 55.0)
        csum = monthly_sumR(cdf)
        r_c = (TARGET_STD / 100.0) / csum.std()
        crypto_m[label] = csum * r_c * 100
        crypto_r[label] = r_c

    print("\n(a) STANDALONE SLEEVES (each risk-sized to ~%.0f%% monthly STD):" % TARGET_STD)
    fx_d = stats("FX brooks", fx_m)
    cds = {}
    for label in cands:
        cds[label] = stats(f"{label} (r={crypto_r[label]*100:.3f}%)", crypto_m[label])

    # ---- correlations on common window ----
    print("\n(b) FX vs CRYPTO monthly-R CORRELATION + crisis behavior (common window):")
    common_results = {}
    for label, cd in cds.items():
        idx = fx_d["_m"].index.intersection(cd["_m"].index)
        a = fx_d["_m"].reindex(idx); b = cd["_m"].reindex(idx)
        rho = float(np.corrcoef(a.values, b.values)[0, 1])
        common_results[label] = (a, b)
        cc = 0; cn_tot = 0
        crisis_str = []
        for cn, cm in CRISIS.items():
            ts = pd.Timestamp(cm + "-01", tz="UTC") + pd.offsets.MonthEnd(0)
            if ts in idx:
                cn_tot += 1
                fv, cv = float(a.loc[ts]), float(b.loc[ts])
                both = fv < 0 and cv < 0
                cc += both
                crisis_str.append(f"{cm}:FX{fv:+.0f}/CR{cv:+.0f}{'!BOTH-DN' if both else ''}")
        print(f"  FX vs {label:<24} rho={rho:+.3f} (n={len(idx)})  both-down {cc}/{cn_tot} crisis")
        print(f"       {' | '.join(crisis_str)}")

    # ---- cross-asset portfolio: 50/50 risk parity (both sized to TARGET_STD already) ----
    print("\n(c) CROSS-ASSET PORTFOLIO (50/50 of two equal-STD sleeves = risk parity):")
    ports = {}
    for label, (a, b) in common_results.items():
        port = 0.5 * a + 0.5 * b
        ports[label] = port
        stats(f"FX + {label}", port)

    # ---- (d) head-to-head identical window, FX-only vs each cross blend ----
    print("\n(d) HEAD-TO-HEAD  FX-ONLY vs CROSS-ASSET (identical window per blend):")
    for label, port in ports.items():
        a, _ = common_results[label]
        fxo = stats(f"  FX-ONLY ({label} window)", a, show=False)
        cr = stats(f"  CROSS FX+{label}", port, show=False)
        dstd = (cr["std"] - fxo["std"]) / fxo["std"] * 100
        print(f"\n  vs {label}  (window n={len(a)}):")
        print(f"     FX-ONLY : med={fxo['med']:+.2f}% STD={fxo['std']:.2f}% Sharpe={fxo['sharpe']:+.2f} "
              f"realDD={fxo['real_dd']:+.1f}% neg={fxo['neg']:.0f}% worst={fxo['worst']:+.1f}%")
        print(f"     CROSS   : med={cr['med']:+.2f}% STD={cr['std']:.2f}% Sharpe={cr['sharpe']:+.2f} "
              f"realDD={cr['real_dd']:+.1f}% neg={cr['neg']:.0f}% worst={cr['worst']:+.1f}%")
        print(f"     -> STD {dstd:+.1f}% | Sharpe {cr['sharpe']-fxo['sharpe']:+.2f} | "
              f"med {cr['med']-fxo['med']:+.2f}pp | DD {cr['real_dd']-fxo['real_dd']:+.1f}pp | "
              f"worst-month {cr['worst']-fxo['worst']:+.1f}pp")

    print("\nDONE.")


if __name__ == "__main__":
    main()
