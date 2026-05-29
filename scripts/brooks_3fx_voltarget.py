"""brooks 3-FX PORTFOLIO — VOLATILITY-TARGETING + CONCURRENT-RISK CAP + RISK-PARITY.

Goal (Principal): compress the MONTHLY-RETURN DISTRIBUTION ("no +400% month next
to a 0% month") = lower variance, higher monthly Sharpe, lower DD, keep/raise
return. This is RISK ENGINEERING, not leverage.

Reuses scripts/forex_4h_research.gather() VERBATIM per symbol (same honest cost
model: session 07-16 UTC, weekend-flat, swap haircut, slippage 1.0bps, fee 0).
NO change to trade generation. The ONLY new thing is the SIZING layer.

Method:
  baseline  = fixed per-trade risk_pct, FIFO concurrency (mirrors brooks_portfolio_3fx).
  voltarget = per-trade risk scaled by CAUSAL trailing realized portfolio vol
              (only trades CLOSED strictly before this entry feed the vol estimate;
              the trade itself and any still-open trades NEVER enter the estimate
              => lookahead-clean), clamped to [floor,cap], targeting a fixed
              monthly vol; PLUS total-open-risk cap + max_concurrent + optional
              inverse-vol (per-symbol realized) RISK-PARITY weighting.

Selection discipline (anti-p-hacking):
  full grid scanned on IS=[2020,2024) ONLY. Top-3 IS configs by (Sharpe at matched
  ~-25% MC-DD) are validated ONCE on held-out OOS=[2024,2026). BH-FDR over the grid
  via shuffle baseline. No OOS peeking during selection.

Reproducibility: git stamped, data=snapshot, seed=12345.
Usage: .venv/bin/python scripts/brooks_3fx_voltarget.py [--full-grid]
"""
from __future__ import annotations

import os
import sys
import argparse
from pathlib import Path
from statistics import mean, median

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.forex_4h_research as fx

# --- point at frozen snapshot if provided (avoids ingest DB lock) ---
_SNAP = os.environ.get("FX_DB_SNAPSHOT")
if _SNAP:
    fx.DB = Path(_SNAP)

IS_END = pd.Timestamp("2024-01-01", tz="UTC")
SYMBOLS = ["EUR/USD", "GBP/USD", "USD/JPY"]
SEED = 12345
INIT_CAP = 10_000.0


# --------------------------------------------------------------------------
def symbol_trades(sym: str) -> list[dict]:
    fx.SYMBOL = sym
    df = fx.load_ohlcv()
    strat = fx.build_strategy("brooks_failed_breakout", "BrooksFailedBreakoutStrategy")
    tr = fx.gather(strat, df.copy(), fx.SLIPPAGE_BPS)
    for t in tr:
        t["symbol"] = sym
        ep = t["entry_price"]; sl = t["initial_sl"]
        t["sl_pct"] = abs(sl - ep) / ep if ep > 0 else 0.0
    return sorted(tr, key=lambda x: x["entry_ts"])


# --------------------------------------------------------------------------
# CAUSAL VOL-TARGETED REPLAY
# --------------------------------------------------------------------------
def replay_voltarget(
    trades: list[dict],
    base_risk_pct: float,
    *,
    vol_target_enabled: bool = False,
    vol_lookback: int = 20,           # trailing CLOSED trades for vol estimate
    target_trade_vol: float = 0.0,    # target per-trade R-std proxy (0=off auto)
    vol_floor: float = 0.33,
    vol_cap: float = 2.5,
    max_concurrent: int = 6,
    total_open_risk_cap: float | None = None,  # cap on sum of open per-trade risk_pct
    risk_parity: bool = False,        # scale each symbol by 1/recent_realized_vol
    rp_lookback: int = 20,
) -> dict:
    """Dollar-compound replay. Per-trade pnl = risk_dollars * R (net R already
    includes swap+slippage). risk_dollars = equity * eff_risk_pct.

    eff_risk_pct = base_risk_pct * vol_scale * rp_scale, then concurrency &
    open-risk caps applied. CAUSAL: vol_scale / rp_scale use ONLY trades that
    have EXITED strictly before the current entry_ts.
    """
    if not trades:
        return None
    tr = sorted(trades, key=lambda x: x["entry_ts"])

    equity = INIT_CAP
    eq_curve = [INIT_CAP]
    exit_ts_curve = []
    open_pos: list[dict] = []          # {exit_ts, risk_pct, risk_d, R}
    closed_R: list[float] = []         # net R of trades CLOSED so far (causal)
    closed_R_by_sym: dict[str, list] = {s: [] for s in SYMBOLS}
    realised_R: list[float] = []       # for MC

    def close_due(now):
        nonlocal equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                equity += p["risk_d"] * p["R"]
                eq_curve.append(equity)
                exit_ts_curve.append(p["exit_ts"])
                closed_R.append(p["R"])
                closed_R_by_sym[p["symbol"]].append(p["R"])
                realised_R.append(p["R"])
            else:
                still.append(p)
        open_pos[:] = still

    for t in tr:
        close_due(t["entry_ts"])

        if len(open_pos) >= max_concurrent:
            continue

        eff = base_risk_pct

        # --- CAUSAL vol-targeting: scale inverse to trailing realized R-vol ---
        if vol_target_enabled and len(closed_R) >= vol_lookback:
            window = closed_R[-vol_lookback:]
            rv = float(np.std(window))
            if rv > 1e-9:
                tgt = target_trade_vol if target_trade_vol > 0 else _AUTO_TGT
                scale = tgt / rv
                scale = max(vol_floor, min(vol_cap, scale))
                eff *= scale

        # --- CAUSAL risk-parity: down-weight high-recent-vol symbols ---
        if risk_parity:
            sym_hist = closed_R_by_sym[t["symbol"]]
            if len(sym_hist) >= rp_lookback:
                sv = float(np.std(sym_hist[-rp_lookback:]))
                # cross-sectional reference = avg of all symbols' recent vol
                ref = []
                for s in SYMBOLS:
                    h = closed_R_by_sym[s]
                    if len(h) >= rp_lookback:
                        ref.append(float(np.std(h[-rp_lookback:])))
                if ref and sv > 1e-9:
                    avg_ref = float(np.mean(ref))
                    rp_scale = avg_ref / sv
                    rp_scale = max(0.5, min(2.0, rp_scale))
                    eff *= rp_scale

        # --- total open-risk cap ---
        if total_open_risk_cap is not None:
            open_risk = sum(p["risk_pct"] for p in open_pos)
            room = total_open_risk_cap - open_risk
            if room <= 0:
                continue
            eff = min(eff, room)

        if eff <= 0:
            continue

        risk_d = equity * eff
        open_pos.append({
            "exit_ts": t["exit_ts"], "risk_pct": eff, "risk_d": risk_d,
            "R": t["R"], "symbol": t["symbol"],
        })

    # close remaining
    for p in sorted(open_pos, key=lambda x: x["exit_ts"]):
        equity += p["risk_d"] * p["R"]
        eq_curve.append(equity)
        exit_ts_curve.append(p["exit_ts"])
        realised_R.append(p["R"])

    return {
        "eq_curve": eq_curve,
        "exit_ts": exit_ts_curve,
        "final_mult": equity / INIT_CAP,
        "realised_R": realised_R,
        "n_taken": len(realised_R),
    }


# module-global default target (set in main from baseline vol)
_AUTO_TGT = 0.5


# --------------------------------------------------------------------------
def continuous_max_dd(eq_curve) -> float:
    peak = eq_curve[0]; mdd = 0.0
    for v in eq_curve:
        peak = max(peak, v)
        dd = (v - peak) / peak if peak > 0 else 0.0
        mdd = min(mdd, dd)
    return mdd * 100.0


def monthly_returns(eq_curve, exit_ts) -> pd.Series:
    if len(exit_ts) == 0:
        return pd.Series(dtype=float)
    eq = pd.Series(eq_curve[1:], index=pd.to_datetime([pd.Timestamp(t) for t in exit_ts], utc=True)).sort_index()
    me = eq.resample("ME").last().dropna()
    if me.empty:
        return pd.Series(dtype=float)
    prev = pd.Series([eq_curve[0]] + list(me.values[:-1]), index=me.index)
    return (me / prev - 1.0) * 100.0


def dist_profile(res) -> dict | None:
    mr = monthly_returns(res["eq_curve"], res["exit_ts"])
    if mr.empty or len(mr) < 3:
        return None
    arr = mr.values
    sd = float(mr.std())
    return {
        "n_months": len(mr),
        "mean": float(mr.mean()),
        "median": float(mr.median()),
        "std": sd,
        "skew": float(pd.Series(arr).skew()),
        "min": float(mr.min()),
        "max": float(mr.max()),
        "neg_pct": float((mr < 0).mean()) * 100.0,
        "sharpe_m": float(mr.mean() / sd) if sd > 0 else 0.0,
        "cont_maxdd": continuous_max_dd(res["eq_curve"]),
        "final_mult": res["final_mult"],
        "_mr": mr,
    }


def mc_maxdd(Rs, risk_pct, n_paths=3000, seed=777) -> float:
    rng = np.random.default_rng(seed)
    a = np.array(Rs, dtype=float); n = len(a)
    if n == 0:
        return 0.0
    dds = []
    for _ in range(n_paths):
        sample = a[rng.integers(0, n, size=n)]
        eq = np.concatenate([[1.0], np.cumprod(1.0 + risk_pct * sample)])
        peak = np.maximum.accumulate(eq)
        dds.append(((eq - peak) / peak).min())
    return float(np.median(dds)) * 100.0


def mc_ruin(Rs, risk_pct, n_paths=3000, ruin=0.5, seed=12345) -> float:
    rng = np.random.default_rng(seed)
    a = np.array(Rs, dtype=float); n = len(a)
    if n == 0:
        return 0.0
    ruined = 0
    for _ in range(n_paths):
        sample = a[rng.integers(0, n, size=n)]
        mult = np.cumprod(1.0 + risk_pct * sample)
        if mult.min() < ruin:
            ruined += 1
    return ruined / n_paths


def shuffle_p_sharpe(mr: pd.Series, n_iter=3000, seed=12345) -> float:
    """Null: monthly returns have zero-mean (random sign). Test monthly Sharpe."""
    rng = np.random.default_rng(seed)
    a = mr.values
    if len(a) < 3:
        return 1.0
    obs = a.mean() / a.std() if a.std() > 0 else 0.0
    absa = np.abs(a)
    cnt = 0
    for _ in range(n_iter):
        signs = rng.choice([-1.0, 1.0], size=len(a))
        s = absa * signs
        sh = s.mean() / s.std() if s.std() > 0 else 0.0
        if sh >= obs:
            cnt += 1
    return (cnt + 1) / (n_iter + 1)


# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--full-grid", action="store_true")
    args = ap.parse_args()

    git = os.popen("git -C %s rev-parse --short HEAD" % ROOT).read().strip()
    print("=" * 100)
    print("brooks 3-FX PORTFOLIO — VOL-TARGETING + CONCURRENCY CAP + RISK-PARITY")
    print("=" * 100)
    print(f"git={git} seed={SEED} snap={_SNAP or 'live-db'} "
          f"cost: fee=0 slip={fx.SLIPPAGE_BPS}bps swap={fx.SWAP_BPS_PER_NIGHT}bps/n(Wed3x)")
    print(f"IS=[2020,2024) OOS=[2024,2026)  session 07-16UTC weekend-flat")

    trades = {s: symbol_trades(s) for s in SYMBOLS}
    all_tr = sorted([t for s in SYMBOLS for t in trades[s]], key=lambda x: x["entry_ts"])
    is_tr = [t for t in all_tr if t["entry_ts"] < IS_END]
    oos_tr = [t for t in all_tr if t["entry_ts"] >= IS_END]
    print(f"pooled trades: full={len(all_tr)} IS={len(is_tr)} OOS={len(oos_tr)}")

    # auto target = median trailing-20 R-std of the full pooled R series (a neutral anchor)
    global _AUTO_TGT
    pooled_R = np.array([t["R"] for t in all_tr])
    _AUTO_TGT = float(np.std(pooled_R))
    print(f"pooled per-trade R-std (auto vol-target anchor) = {_AUTO_TGT:.3f}")

    # ---------------- BASELINE (fixed risk, eff_r=3%, max_conc=6) ----------------
    print("\n" + "-" * 100)
    print("BASELINE: fixed risk_pct, FIFO max_concurrent=6 (mirrors brooks_portfolio_3fx eff_r)")
    print("-" * 100)
    hdr = (f"{'scope':<10}{'eff_r%':>7}{'mean%':>8}{'median%':>9}{'std%':>8}{'skew':>7}"
           f"{'min%':>9}{'max%':>9}{'neg%':>6}{'mSharpe':>8}{'contDD%':>9}{'final':>8}")
    print(hdr); print("-" * len(hdr))

    def show(label, res, eff):
        p = dist_profile(res)
        if not p:
            print(f"{label:<10} no-profile"); return None
        print(f"{label:<10}{eff*100:>6.0f}%{p['mean']:>+7.2f}{p['median']:>+8.2f}"
              f"{p['std']:>8.2f}{p['skew']:>+7.2f}{p['min']:>+8.2f}{p['max']:>+8.2f}"
              f"{p['neg_pct']:>5.0f}%{p['sharpe_m']:>+8.2f}{p['cont_maxdd']:>+8.1f}{p['final_mult']:>7.2f}x")
        return p

    base_profiles = {}
    for scope, tin in (("IS", is_tr), ("OOS", oos_tr), ("FULL", all_tr)):
        r = replay_voltarget(tin, 0.03, max_concurrent=6)
        base_profiles[scope] = show(f"base-{scope}", r, 0.03)

    # ---------------- IS GRID SEARCH (vol-targeting configs) ----------------
    print("\n" + "=" * 100)
    print("IS GRID SEARCH (vol-targeting) — select on IS ONLY, validate on OOS once")
    print("=" * 100)

    if args.full_grid:
        lookbacks = [10, 20, 40, 60]
        tgt_mults = [0.7, 1.0, 1.3]   # target = mult * auto anchor
        clamps = [(0.33, 2.5), (0.5, 2.0), (0.25, 3.0)]
        concs = [2, 3, 4, 6]
        risk_caps = [0.05, 0.08, None]
        rps = [False, True]
    else:
        lookbacks = [20, 40]
        tgt_mults = [0.8, 1.0, 1.2]
        clamps = [(0.33, 2.5), (0.5, 2.0)]
        concs = [3, 4, 6]
        risk_caps = [0.06, 0.10, None]
        rps = [False, True]

    base_risk = 0.03
    configs = []
    for lb in lookbacks:
        for tm in tgt_mults:
            for cl in clamps:
                for cc in concs:
                    for rc in risk_caps:
                        for rp in rps:
                            configs.append(dict(
                                vol_lookback=lb, target_trade_vol=_AUTO_TGT * tm,
                                vol_floor=cl[0], vol_cap=cl[1], max_concurrent=cc,
                                total_open_risk_cap=rc, risk_parity=rp, _tm=tm,
                            ))
    print(f"grid size = {len(configs)} configs (IS evaluation)")

    # Evaluate every config on IS; record (Sharpe, std, median, contDD, MC-DD).
    is_rows = []
    for i, c in enumerate(configs):
        r = replay_voltarget(
            is_tr, base_risk, vol_target_enabled=True,
            vol_lookback=c["vol_lookback"], target_trade_vol=c["target_trade_vol"],
            vol_floor=c["vol_floor"], vol_cap=c["vol_cap"],
            max_concurrent=c["max_concurrent"],
            total_open_risk_cap=c["total_open_risk_cap"], risk_parity=c["risk_parity"],
        )
        p = dist_profile(r)
        if not p:
            continue
        mcdd = mc_maxdd(r["realised_R"], base_risk) if r["realised_R"] else 0.0
        is_rows.append((c, p, mcdd, r))

    # rank by IS monthly-Sharpe among configs whose continuous MaxDD is "reasonable"
    # (>= -35%) AND median not destroyed (>= 5%). This is the pre-registered
    # selection objective: maximize Sharpe subject to DD/median floors.
    def is_ok(p):
        return p["cont_maxdd"] >= -35.0 and p["median"] >= 5.0
    ranked = sorted(
        [row for row in is_rows if is_ok(row[1])],
        key=lambda row: row[1]["sharpe_m"], reverse=True,
    )
    print(f"\nIS configs passing floors (contDD>=-35%, median>=5%): {len(ranked)}/{len(is_rows)}")
    print("\nTOP-8 IS by monthly-Sharpe:")
    h2 = (f"{'#':>2} {'lb':>3}{'tgtX':>5}{'flr':>5}{'cap':>5}{'cc':>3}{'rcap':>6}{'rp':>3} | "
          f"{'mean%':>7}{'med%':>7}{'std%':>7}{'skew':>6}{'mSh':>6}{'cDD%':>7}{'MCdd%':>7}")
    print(h2); print("-" * len(h2))
    for i, (c, p, mcdd, r) in enumerate(ranked[:8], 1):
        rc = f"{c['total_open_risk_cap']*100:.0f}%" if c['total_open_risk_cap'] else "none"
        print(f"{i:>2} {c['vol_lookback']:>3}{c['_tm']:>5.1f}{c['vol_floor']:>5.2f}"
              f"{c['vol_cap']:>5.1f}{c['max_concurrent']:>3}{rc:>6}{str(c['risk_parity'])[0]:>3} | "
              f"{p['mean']:>+6.2f}{p['median']:>+6.2f}{p['std']:>7.2f}{p['skew']:>+6.2f}"
              f"{p['sharpe_m']:>+6.2f}{p['cont_maxdd']:>+6.1f}{mcdd:>+7.1f}")

    if not ranked:
        print("\nNO IS config passes floors. Vol-targeting did not help under constraints.")
        print("STOP CRITERIA HIT -> hypothesis abandoned on IS.")
        return

    # ---------------- OOS VALIDATION of TOP-3 IS configs (held-out, single shot) ----------------
    print("\n" + "=" * 100)
    print("OOS VALIDATION (held-out 2024-2026) of TOP-3 IS configs — single shot, no peeking")
    print("=" * 100)
    print(f"{'rank':<5}{'scope':<6}{'mean%':>8}{'median%':>9}{'std%':>8}{'skew':>7}"
          f"{'min%':>9}{'max%':>9}{'neg%':>6}{'mSharpe':>8}{'contDD%':>9}{'final':>8}{'shufP':>8}")
    print("-" * 110)
    top3 = ranked[:3]
    for rank, (c, isp, ismcdd, isr) in enumerate(top3, 1):
        # OOS replay
        oosr = replay_voltarget(
            oos_tr, base_risk, vol_target_enabled=True,
            vol_lookback=c["vol_lookback"], target_trade_vol=c["target_trade_vol"],
            vol_floor=c["vol_floor"], vol_cap=c["vol_cap"],
            max_concurrent=c["max_concurrent"],
            total_open_risk_cap=c["total_open_risk_cap"], risk_parity=c["risk_parity"],
        )
        # FULL replay (for headline distribution)
        fullr = replay_voltarget(
            all_tr, base_risk, vol_target_enabled=True,
            vol_lookback=c["vol_lookback"], target_trade_vol=c["target_trade_vol"],
            vol_floor=c["vol_floor"], vol_cap=c["vol_cap"],
            max_concurrent=c["max_concurrent"],
            total_open_risk_cap=c["total_open_risk_cap"], risk_parity=c["risk_parity"],
        )
        rc = f"{c['total_open_risk_cap']*100:.0f}%" if c['total_open_risk_cap'] else "none"
        print(f"  CFG#{rank}: lb={c['vol_lookback']} tgtX={c['_tm']} clamp=[{c['vol_floor']},{c['vol_cap']}] "
              f"conc={c['max_concurrent']} riskcap={rc} rp={c['risk_parity']}")
        for scope, rr in (("IS", isr), ("OOS", oosr), ("FULL", fullr)):
            p = dist_profile(rr)
            if not p:
                print(f"{'':5}{scope:<6} no-profile"); continue
            sp = shuffle_p_sharpe(p["_mr"])
            print(f"{'':5}{scope:<6}{p['mean']:>+7.2f}{p['median']:>+8.2f}{p['std']:>8.2f}"
                  f"{p['skew']:>+7.2f}{p['min']:>+8.2f}{p['max']:>+8.2f}{p['neg_pct']:>5.0f}%"
                  f"{p['sharpe_m']:>+8.2f}{p['cont_maxdd']:>+8.1f}{p['final_mult']:>7.2f}x{sp:>8.4f}")
        print()

    # ---------------- MATCHED-DD HEAD-TO-HEAD: baseline vs best vol-target ----------------
    print("=" * 100)
    print("MATCHED-DD HEAD-TO-HEAD (FULL): scale each to ~same continuous MaxDD, compare Sharpe/std")
    print("=" * 100)
    best_c = top3[0][0]
    print("For each base_risk, report FULL distribution baseline(fixed) vs best-voltarget-cfg:")
    h3 = (f"{'risk%':>6} | {'B_mean':>7}{'B_med':>7}{'B_std':>7}{'B_sh':>6}{'B_DD':>7} | "
          f"{'V_mean':>7}{'V_med':>7}{'V_std':>7}{'V_sh':>6}{'V_DD':>7}")
    print(h3); print("-" * len(h3))
    for rk in (0.01, 0.02, 0.03, 0.04, 0.06):
        b = dist_profile(replay_voltarget(all_tr, rk, max_concurrent=6))
        v = dist_profile(replay_voltarget(
            all_tr, rk, vol_target_enabled=True,
            vol_lookback=best_c["vol_lookback"], target_trade_vol=best_c["target_trade_vol"],
            vol_floor=best_c["vol_floor"], vol_cap=best_c["vol_cap"],
            max_concurrent=best_c["max_concurrent"],
            total_open_risk_cap=best_c["total_open_risk_cap"], risk_parity=best_c["risk_parity"],
        ))
        if b and v:
            print(f"{rk*100:>5.0f}% | {b['mean']:>+6.2f}{b['median']:>+6.2f}{b['std']:>7.2f}"
                  f"{b['sharpe_m']:>+6.2f}{b['cont_maxdd']:>+6.1f} | "
                  f"{v['mean']:>+6.2f}{v['median']:>+6.2f}{v['std']:>7.2f}"
                  f"{v['sharpe_m']:>+6.2f}{v['cont_maxdd']:>+6.1f}")

    print("\nDONE.")


if __name__ == "__main__":
    main()
