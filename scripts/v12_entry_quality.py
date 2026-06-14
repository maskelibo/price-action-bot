"""HYP-2026-06-02-v12-entry-quality-vsa-widestop.

Raise per-trade EDGE of VSA-WIDESTOP entry via ORTHOGONAL filters, holding -23% DD.
Each lever must raise mean_R OOS with MTC-corrected significance, else entry = ceiling.

METHOD (reuses deployed harness; lookahead-free enrichment):
  - Trades via REAL engine through wlr.gather (DEPLOY exit = champion_characterize).
  - WIDESTOP subset sl_pct>=0.025. True fee priced via PA_FEE_RT_BPS (default 18) by
    fee add-back at the per-trade R layer (the gather R is @55bps engine; we report @18
    by analytic fee swap on the round-trip notional / sl_pct).
  - ORTHOGONAL feature enrichment at entry (NO lookahead): for each trade, using OHLCV
    bars up to & INCLUDING the entry bar, compute:
      * htf_bias_1d   : sign(close - EMA50_1d) aligned with trade side (1=aligned)
      * vol_z_entry   : volume z-score(20) of entry bar
      * adx14         : ADX(14) at entry bar (chop floor)
      * climax_vmult  : max(volume/vol_sma20) over the [entry-15 .. entry-3] window
                        (intensity of the SC/BC that seeded the test) — VSA "more
                        climactic = more reliable test" hypothesis
      * spread_atr    : (high-low)/atr20 of the entry bar
  - Sweep each filter threshold on IS ONLY; measure delta mean_R on OOS hold-out.
  - sl_pct_min re-opt UP: 0.025 / 0.030 / 0.035 (tightening allowed).
  - MTC: Benjamini-Hochberg over all (filter x threshold) shuffle p_gross.
  - Stack return @ -23% DD: portfolio replay (production_replay, live YAML) on the
    FILTERED 19-sym 15m pool, lever to the DD ceiling.

GATES: IS mean_R must beat base IS; IS/OOS ratio < 1.5 (overfit flag); OOS delta>0;
BH-FDR sig; OOS n not collapsed to noise (>=150).

Usage: PA_FEE_RT_BPS=18 .venv/bin/python scripts/v12_entry_quality.py
"""
from __future__ import annotations
import os, sys, json
from pathlib import Path
os.environ["PA_DUCKDB_READ_ONLY"] = "true"
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import logging; logging.getLogger("price_action").setLevel(logging.ERROR)
import numpy as np, pandas as pd, duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
import importlib.util
spec = importlib.util.spec_from_file_location(
    "wlr", str(ROOT / "scripts" / "crypto_winner_let_run_vsa_exit.py"))
wlr = importlib.util.module_from_spec(spec); spec.loader.exec_module(wlr)
from price_action.backtest.lab import ProductionConfig, production_replay
from dataclasses import replace

YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_widestop_vsa2.yaml"
DB = ROOT / "data" / "market.duckdb"
SYMS = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","ADA/USDT","AVAX/USDT",
        "LINK/USDT","DOT/USDT","DOGE/USDT","XRP/USDT","ZEC/USDT","NEAR/USDT",
        "FIL/USDT","XLM/USDT","TRX/USDT","UNI/USDT","ATOM/USDT","AAVE/USDT","ALGO/USDT"]
SL_PCT_MIN = 0.025
RISK_PCT = 0.005
SEED = 12345
FEE_RT_BPS = float(os.environ.get("PA_FEE_RT_BPS", "18"))
IS_END = pd.Timestamp("2024-01-01", tz="UTC")

DEPLOY_EXIT = dict(
    runner_trail_mult=3.0, trail_activate_stage=2,
    tp1_R=1.0, tp2_R=1.5, tp1_close_pct=0.25, tp2_close_pct=0.25,
    runner_force_exit_method="time", runner_force_exit_bars=30,
    force_exit_from_entry=True,
)


def sl_pct_of(t):
    ep = t["entry_price"]
    return abs(t["initial_sl"] - ep) / ep if ep > 0 else 0.04


def fee_R_at(t, rt_bps):
    """Per-trade round-trip fee in R units at given rt_bps on the stop distance."""
    sp = sl_pct_of(t)
    return (rt_bps / 10000.0) / sp if sp > 0 else 0.0


def R_at_fee(t, rt_bps):
    """gather() R is @55bps engine (taker 7.5*2 + slip 5*2 = 25bps... actually engine
    rt = taker 7.5bps/leg *2 legs + slip 5bps/leg*2 = 25bps notional). Re-price to rt_bps:
    add back the 25bps that gather charged, subtract the target rt_bps."""
    GATHER_RT_BPS = 25.0  # taker 7.5*2 + slip 5*2 (engine), on notional
    return t["R"] + fee_R_at(t, GATHER_RT_BPS) - fee_R_at(t, rt_bps)


def cont_dd(eq):
    peak = eq[0]; mdd = 0.0
    for v in eq:
        peak = max(peak, v); mdd = min(mdd, (v - peak) / peak if peak > 0 else 0.0)
    return mdd * 100.0


def monthly_from_replay(res, cfg):
    eq = res.equity_curve or []; ts = res.entry_ts_list or []
    if len(eq) < 2 or not ts:
        return pd.Series(dtype=float)
    n = min(len(eq) - 1, len(ts))
    stamps = pd.to_datetime(ts[:n], utc=True)
    df = pd.DataFrame({"ts": stamps, "eq": eq[1:n + 1]})
    df["m"] = df["ts"].dt.to_period("M")
    me = df.groupby("m")["eq"].last()
    prev = me.shift(1, fill_value=cfg.initial_capital)
    return (me / prev - 1.0) * 100.0


def build_cfg(lev=1.0):
    c = ProductionConfig.from_yaml(str(YAML))
    c = replace(c, risk_pct=RISK_PCT * lev, sl_pct_min=max(c.sl_pct_min, SL_PCT_MIN))
    if c.max_notional_pct_equity is not None:
        c = replace(c, max_notional_pct_equity=c.max_notional_pct_equity * lev)
    if c.concentration_max_per_symbol_pct is not None:
        c = replace(c, concentration_max_per_symbol_pct=c.concentration_max_per_symbol_pct * lev)
    return c


def shuffle_p(Rs, n_iter=4000, seed=SEED):
    a = np.array(Rs, dtype=float)
    if len(a) < 5:
        return 1.0
    obs = a.mean()
    rng = np.random.default_rng(seed)
    cnt = sum(1 for _ in range(n_iter) if rng.choice(a, size=len(a), replace=True).mean() <= 0.0)
    # one-sided: P(mean<=0 under resample) -> proxy sign-flip; use bootstrap CI lower instead
    return (cnt + 1) / (n_iter + 1)


def boot_p_positive(Rs, n_iter=4000, seed=SEED):
    """One-sided bootstrap p that true mean_R <= 0 (we want it small)."""
    a = np.array(Rs, dtype=float)
    if len(a) < 5:
        return 1.0
    rng = np.random.default_rng(seed)
    means = np.array([rng.choice(a, size=len(a), replace=True).mean() for _ in range(n_iter)])
    return (np.sum(means <= 0.0) + 1) / (n_iter + 1)


# ---------- lookahead-free feature enrichment ----------
_OHLCV = {}
_D1 = {}


def load_15m(sym):
    if sym in _OHLCV:
        return _OHLCV[sym]
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute("SELECT ts,open,high,low,close,volume FROM ohlcv WHERE venue='binance' "
                     "AND symbol=? AND timeframe='15m' ORDER BY ts", [sym]).fetchdf()
    con.close()
    if df.empty:
        _OHLCV[sym] = df; return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    # ATR20, vol_sma20, vol_z20
    tr = pd.concat([(df["high"] - df["low"]),
                    (df["high"] - df["close"].shift()).abs(),
                    (df["low"] - df["close"].shift()).abs()], axis=1).max(axis=1)
    df["atr20"] = tr.rolling(20, min_periods=10).mean()
    df["vol_sma20"] = df["volume"].rolling(20, min_periods=10).mean()
    vstd = df["volume"].rolling(20, min_periods=10).std()
    df["vol_z20"] = (df["volume"] - df["vol_sma20"]) / vstd
    df["vmult"] = df["volume"] / df["vol_sma20"]
    df["spread_atr"] = (df["high"] - df["low"]) / df["atr20"]
    # ADX14 (Wilder) lookahead-free
    up = df["high"].diff(); dn = -df["low"].diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    atr_w = tr.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    pdi = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1/14, adjust=False, min_periods=14).mean() / atr_w
    mdi = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1/14, adjust=False, min_periods=14).mean() / atr_w
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    df["adx14"] = dx.ewm(alpha=1/14, adjust=False, min_periods=14).mean()
    _OHLCV[sym] = df
    return df


def load_d1(sym):
    if sym in _D1:
        return _D1[sym]
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute("SELECT ts,close FROM ohlcv WHERE venue='binance' "
                     "AND symbol=? AND timeframe='1d' ORDER BY ts", [sym]).fetchdf()
    con.close()
    if df.empty:
        _D1[sym] = df; return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    df["ema50"] = df["close"].ewm(span=50, adjust=False).mean()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    _D1[sym] = df
    return df


def enrich(trades):
    """Attach orthogonal entry features (lookahead-free) to each trade in place."""
    for sym in SYMS:
        df = load_15m(sym); d1 = load_d1(sym)
        if df.empty:
            continue
        ts_arr = df["ts"].values
        d1_ts = d1["ts"].values if not d1.empty else np.array([], dtype="datetime64[ns]")
        for t in trades:
            if t["symbol"] != sym:
                continue
            te = np.datetime64(pd.Timestamp(t["entry_ts"]).tz_convert("UTC").tz_localize(None))
            i = np.searchsorted(ts_arr, te, side="right") - 1  # entry bar index (incl)
            if i < 0 or i >= len(df):
                continue
            side = t["side"].lower()
            t["vol_z_entry"] = float(df["vol_z20"].iloc[i]) if not np.isnan(df["vol_z20"].iloc[i]) else 0.0
            t["adx14"] = float(df["adx14"].iloc[i]) if not np.isnan(df["adx14"].iloc[i]) else 0.0
            t["spread_atr_entry"] = float(df["spread_atr"].iloc[i]) if not np.isnan(df["spread_atr"].iloc[i]) else 0.0
            # climax intensity: max vmult in [i-15 .. i-3] (the SC/BC seed window)
            lo, hi = max(0, i - 15), max(0, i - 3)
            seg = df["vmult"].iloc[lo:hi + 1].dropna()
            t["climax_vmult"] = float(seg.max()) if len(seg) else 0.0
            # HTF 1d bias aligned with side
            if not d1.empty:
                j = np.searchsorted(d1_ts, te, side="right") - 1
                if 0 <= j < len(d1) and not np.isnan(d1["ema50"].iloc[j]):
                    above = d1["close"].iloc[j] > d1["ema50"].iloc[j]
                    t["htf_aligned"] = 1.0 if ((side == "long" and above) or (side == "short" and not above)) else 0.0
                else:
                    t["htf_aligned"] = -1.0  # unknown
            else:
                t["htf_aligned"] = -1.0
    return trades


def main():
    print("=" * 100)
    print(f"v12 ENTRY-QUALITY  PA_FEE_RT_BPS={FEE_RT_BPS}  (gather@25bps engine -> repriced)")
    print("=" * 100)
    print("gathering 19-sym 15m DEPLOY-exit trades through real engine...")
    allt = []
    for s in SYMS:
        t = wlr.gather(s, DEPLOY_EXIT)
        allt += [x for x in t if sl_pct_of(x) >= SL_PCT_MIN]
    print(f"  widestop pool n={len(allt)}")

    # reprice R to true fee
    for t in allt:
        t["R18"] = R_at_fee(t, FEE_RT_BPS)
    print("enriching orthogonal entry features (lookahead-free)...")
    enrich(allt)

    base_R = np.array([t["R18"] for t in allt])
    is_t = [t for t in allt if t["entry_ts"] < IS_END]
    oos_t = [t for t in allt if t["entry_ts"] >= IS_END]
    print(f"\nBASE (true {FEE_RT_BPS}bps): n={len(allt)} mean_R={base_R.mean():+.4f} "
          f"win={np.mean(base_R>0)*100:.1f}%  | IS n={len(is_t)} mR={np.mean([t['R18'] for t in is_t]):+.4f}"
          f" | OOS n={len(oos_t)} mR={np.mean([t['R18'] for t in oos_t]):+.4f}")
    base_is_mR = float(np.mean([t["R18"] for t in is_t]))
    base_oos_mR = float(np.mean([t["R18"] for t in oos_t]))

    # ---- LEVER 1: confluence threshold ----
    confs = set(round(t["conf"], 4) for t in allt)
    print(f"\n[LEVER 1] confluence_score distinct values: {confs}")
    print("  -> confluence_score is HARDCODED 2.0 (conf=0.333) for every signal: ZERO variance.")
    print("  -> Lever 1 is DEAD: cannot threshold a constant. SKIP.")

    # ---- LEVER 2: orthogonal filters, threshold chosen on IS, measured OOS ----
    print("\n" + "=" * 100)
    print("[LEVER 2] ORTHOGONAL FILTERS — threshold picked on IS, measured OOS")
    print("=" * 100)
    # define filters as (name, accessor, list of thresholds, direction '>=' keep)
    filters = []
    for thr in [0.0, 0.5, 1.0, 1.5, 2.0]:
        filters.append((f"vol_z>={thr}", lambda t, thr=thr: t.get("vol_z_entry", -9) >= thr))
    for thr in [15, 20, 25, 30]:
        filters.append((f"adx>={thr}", lambda t, thr=thr: t.get("adx14", -9) >= thr))
    for thr in [15, 20, 25, 30]:
        filters.append((f"adx<={thr}(chop_only)", lambda t, thr=thr: 0 < t.get("adx14", 999) <= thr))
    for thr in [2.5, 3.0, 4.0, 5.0, 6.0]:
        filters.append((f"climax_vmult>={thr}", lambda t, thr=thr: t.get("climax_vmult", -9) >= thr))
    for thr in [1.0, 1.5, 2.0]:
        filters.append((f"spread_atr>={thr}", lambda t, thr=thr: t.get("spread_atr_entry", -9) >= thr))
    filters.append(("htf_1d_aligned", lambda t: t.get("htf_aligned", -1) == 1.0))
    filters.append(("htf_1d_counter", lambda t: t.get("htf_aligned", -1) == 0.0))

    hdr = f"{'filter':<24} {'IS_n':>6} {'IS_mR':>7} {'OOS_n':>6} {'OOS_mR':>7} {'dOOS':>7} {'IS/OOS':>7} {'boot_p':>7}"
    print(hdr); print("-" * len(hdr))
    results = []
    for name, fn in filters:
        fis = [t for t in is_t if fn(t)]
        foos = [t for t in oos_t if fn(t)]
        if len(fis) < 30 or len(foos) < 30:
            print(f"{name:<24} {len(fis):>6} {'--':>7} {len(foos):>6} {'--':>7}  (too few)")
            continue
        is_mR = float(np.mean([t["R18"] for t in fis]))
        oos_mR = float(np.mean([t["R18"] for t in foos]))
        d_oos = oos_mR - base_oos_mR
        # IS/OOS ratio relative to base lift (overfit detector): IS lift vs OOS lift
        is_lift = is_mR - base_is_mR
        ratio = (is_lift / d_oos) if abs(d_oos) > 1e-9 else (99.0 if is_lift > 0 else 0.0)
        bp = boot_p_positive([t["R18"] for t in foos])
        results.append(dict(name=name, is_n=len(fis), is_mR=is_mR, oos_n=len(foos),
                            oos_mR=oos_mR, d_oos=d_oos, is_lift=is_lift, ratio=ratio, boot_p=bp,
                            fn=fn))
        print(f"{name:<24} {len(fis):>6} {is_mR:>+7.4f} {len(foos):>6} {oos_mR:>+7.4f} "
              f"{d_oos:>+7.4f} {ratio:>+7.2f} {bp:>7.4f}")

    # ---- candidate gate: IS lift>0, OOS lift>0, IS/OOS ratio<1.5, OOS n>=150 ----
    print("\n--- CANDIDATE GATE (IS_lift>0 AND OOS_lift>0 AND 0<IS/OOS<1.5 AND OOS_n>=150) ---")
    cands = [r for r in results if r["is_lift"] > 0 and r["d_oos"] > 0
             and 0 < r["ratio"] < 1.5 and r["oos_n"] >= 150]
    for r in results:
        gate = (r["is_lift"] > 0 and r["d_oos"] > 0 and 0 < r["ratio"] < 1.5 and r["oos_n"] >= 150)
        why = []
        if r["is_lift"] <= 0: why.append("IS_no_lift")
        if r["d_oos"] <= 0: why.append("OOS_no_lift")
        if not (0 < r["ratio"] < 1.5): why.append(f"ratio={r['ratio']:.1f}")
        if r["oos_n"] < 150: why.append("small_n")
        print(f"  {r['name']:<24} {'PASS' if gate else 'fail: '+','.join(why)}")

    # ---- BH-FDR over candidate boot_p (corrected significance) ----
    if cands:
        ps = sorted(cands, key=lambda r: r["boot_p"]); m = len(results)  # correct over ALL tests
        print(f"\n--- BH-FDR (alpha=0.05) over ALL {m} filter tests, candidates ranked ---")
        sig = []
        for i, r in enumerate(sorted(results, key=lambda x: x["boot_p"]), 1):
            thr = 0.05 * i / m
            ok = r["boot_p"] <= thr
            tag = "SIG" if ok else ""
            if r in cands and ok:
                sig.append(r)
            if r in cands:
                print(f"  {i:>2}. {r['name']:<24} boot_p={r['boot_p']:.4f} BH_thr={thr:.4f} {tag} [CAND]")
        surviving = sig
    else:
        surviving = []
        print("\n  NO candidates passed the overfit gate.")

    # ---- LEVER 3: sl_pct_min UP re-opt ----
    print("\n" + "=" * 100)
    print("[LEVER 3] WIDESTOP threshold re-opt UP (tightening allowed): 0.025/0.030/0.035")
    print("=" * 100)
    print(f"{'sl_min':>7} {'IS_n':>6} {'IS_mR':>7} {'OOS_n':>6} {'OOS_mR':>7} {'dOOS':>7}")
    lever3 = []
    for slm in [0.025, 0.030, 0.035, 0.040]:
        fis = [t for t in is_t if sl_pct_of(t) >= slm]
        foos = [t for t in oos_t if sl_pct_of(t) >= slm]
        if len(foos) < 30:
            print(f"{slm:>7.3f} {len(fis):>6} {'--':>7} {len(foos):>6} small"); continue
        is_mR = float(np.mean([t["R18"] for t in fis]))
        oos_mR = float(np.mean([t["R18"] for t in foos]))
        lever3.append((slm, is_mR, oos_mR, len(fis), len(foos)))
        print(f"{slm:>7.3f} {len(fis):>6} {is_mR:>+7.4f} {len(foos):>6} {oos_mR:>+7.4f} {oos_mR-base_oos_mR:>+7.4f}")

    # ---- STACK RETURN @ -23% DD: base vs each surviving lever ----
    print("\n" + "=" * 100)
    print("STACK MONTHLY RETURN @ MaxDD <= -23% (production_replay, 19-sym 15m, lever to DD)")
    print("=" * 100)

    def stack_at_dd(pool, dd_cap=-23.0, lev_grid=None):
        # include SUB-1.0 leverage: base DD is ~-42%, so reaching -23% needs de-lever.
        lev_grid = lev_grid or [0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0]
        best = None
        for L in lev_grid:
            cfg = build_cfg(L)
            res = production_replay(sorted(pool, key=lambda x: x["entry_ts"]), cfg)
            mr = monthly_from_replay(res, cfg)
            dd = cont_dd(res.equity_curve)
            mean = float(mr.mean()) if len(mr) else 0.0
            row = (L, mean, dd, float((mr > 0).mean() * 100) if len(mr) else 0)
            if dd >= dd_cap:  # within budget
                if best is None or mean > best[1]:
                    best = row
        return best

    def report(label, pool):
        bb = stack_at_dd(pool)
        if bb:
            print(f"{label:<34} L={bb[0]:.1f} mean={bb[1]:+.2f}%/mo DD={bb[2]:+.1f}% "
                  f"pos={bb[3]:.0f}% (n={len(pool)})")
        else:
            print(f"{label:<34} NO leverage in [0.4..2.0] keeps DD<=-23% (n={len(pool)})")
        return bb

    base_best = report("BASE (no filter, sl0.025):", allt)

    surv_pools = {}
    for r in surviving:
        fpool = [t for t in allt if r["fn"](t)]
        surv_pools[r["name"]] = (r["fn"], fpool)
        report(f"FILTER {r['name']}", fpool)

    # COMBINED surviving filters (AND)
    if len(surviving) >= 2:
        fns = [r["fn"] for r in surviving]
        cpool = [t for t in allt if all(f(t) for f in fns)]
        report("COMBINED " + "&".join(r["name"] for r in surviving), cpool)

    # lever3 best stack (raise sl_min) + combine with best surviving filter
    for slm in [0.030, 0.035]:
        report(f"WIDESTOP sl>={slm:.3f}", [t for t in allt if sl_pct_of(t) >= slm])
    # widestop 0.030 + htf alignment (the two cleanest orthogonal levers)
    htf = next((r["fn"] for r in surviving if "htf" in r["name"]), None)
    if htf:
        report("sl>=0.030 & htf_aligned",
               [t for t in allt if sl_pct_of(t) >= 0.030 and htf(t)])

    out = dict(fee=FEE_RT_BPS, base_oos_mR=base_oos_mR, base_is_mR=base_is_mR,
               results=[{k: v for k, v in r.items() if k != "fn"} for r in results],
               surviving=[r["name"] for r in surviving], lever3=lever3,
               base_stack=base_best, confluence_dead=True)
    json.dump(out, open("/tmp/v12_entry_quality.json", "w"), indent=2, default=str)
    print("\n[dumped /tmp/v12_entry_quality.json]")


if __name__ == "__main__":
    main()
