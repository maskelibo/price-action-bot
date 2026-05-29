"""brooks_8fx REGIME FILTER test — disciplined IS-design / OOS-validate.

Pre-reg: memory/researcher/hypotheses/2026-05-29-brooks8fx-regime-filter.md

DISCIPLINE:
  - Regime metrics computed CAUSALLY: only bars strictly BEFORE entry_ts (t-1).
    Entry bar itself NEVER enters the regime calc (no lookahead).
  - Filter thresholds chosen on IS (2020-2023) ONLY. OOS (2024-2025) sees the
    single frozen threshold per filter. No grid on OOS.
  - Engine UNCHANGED: filter just drops trades pre-cap; production_replay byte-identical.
  - Reports filtered vs unfiltered, IS+OOS: robust(ws) median, raw median, STD,
    realized contDD, monthly Sharpe, neg-month count, n_trade, n_cut, cut mean-R,
    and top-5% winner retention (did the filter butcher the big winners?).

Usage: .venv/bin/python scripts/brooks_8fx_regime_filter.py
"""
from __future__ import annotations
import os, sys, pickle
from pathlib import Path
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yaml, duckdb

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from price_action.backtest.lab import production_replay
from scripts.brooks_8fx_honest_cap import (
    risk_parity_trades, apply_net_usd_cap, build_cfg, profile, monthly_returns_from_curve,
    continuous_max_dd, RISK_BLOCK,
)

IS_START = pd.Timestamp("2020-01-01", tz="UTC")
IS_END   = pd.Timestamp("2024-01-01", tz="UTC")   # IS = 2020..2023, OOS = 2024..2025
NET_USD_CAP, GROSS_CAP, EFF_R = 3, 6, 0.01
SYMBOLS = ['EUR/USD','GBP/USD','USD/JPY','AUD/USD','USD/CHF','EUR/GBP','USD/CAD','NZD/USD']


# ----------------------------- regime feature engineering (causal) -----------------------------
def load_bars():
    con = duckdb.connect(str(ROOT / "data" / "forex_market.duckdb"), read_only=True)
    out = {}
    for s in SYMBOLS:
        df = con.execute(
            "SELECT ts, open, high, low, close FROM ohlcv WHERE symbol=? AND timeframe='4h' ORDER BY ts",
            [s]).fetch_df()
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
        df = df.set_index("ts").sort_index()
        out[s] = df
    con.close()
    return out


def wilder_adx(df, n=14):
    h, l, c = df["high"], df["low"], df["close"]
    up = h.diff(); dn = -l.diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([(h - l), (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    pdi = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / atr
    mdi = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / n, adjust=False, min_periods=n).mean() / atr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    adx = dx.ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return adx, atr


def build_features(bars):
    feat = {}
    for s, df in bars.items():
        adx, atr = wilder_adx(df, 14)
        ema50 = df["close"].ewm(span=50, adjust=False).mean()
        ema200 = df["close"].ewm(span=200, adjust=False).mean()
        atr_pct = (atr / df["close"])
        atr_pctile = atr_pct.rolling(250, min_periods=60).apply(
            lambda w: (w[-1] >= w).mean(), raw=True)
        N = 20
        chg = df["close"].diff(N).abs()
        vol = df["close"].diff().abs().rolling(N).sum()
        er = (chg / vol.replace(0, np.nan))
        f = pd.DataFrame({
            "adx": adx, "ema50": ema50, "ema200": ema200,
            "atr_pctile": atr_pctile, "er": er,
        }, index=df.index)
        feat[s] = f
    return feat


def regime_at_entry(feat, sym, entry_ts, col):
    """Causal lookup: value of `col` at the LAST bar STRICTLY BEFORE entry_ts.
    Returns np.nan if unavailable (filter treats nan as fail -> conservative)."""
    f = feat[sym]
    idx = f.index.searchsorted(entry_ts, side="left")  # first bar >= entry
    j = idx - 1  # last bar strictly before entry
    if j < 0:
        return np.nan
    return f[col].iloc[j]


def tag_trades(trades, feat):
    """Attach causal regime metrics to every trade (mutates copies)."""
    tagged = {}
    for s in SYMBOLS:
        lst = []
        for t in trades[s]:
            t2 = dict(t)
            t2["_adx"] = regime_at_entry(feat, s, t["entry_ts"], "adx")
            e50 = regime_at_entry(feat, s, t["entry_ts"], "ema50")
            e200 = regime_at_entry(feat, s, t["entry_ts"], "ema200")
            t2["_ema_aligned"] = (
                (e50 > e200) if t["side"] == "long" else (e50 < e200)
            ) if (pd.notna(e50) and pd.notna(e200)) else False
            t2["_atr_pctile"] = regime_at_entry(feat, s, t["entry_ts"], "atr_pctile")
            t2["_er"] = regime_at_entry(feat, s, t["entry_ts"], "er")
            lst.append(t2)
        tagged[s] = lst
    return tagged


# ----------------------------- filter predicates -----------------------------
def filt_none(t):  return True
def make_adx(thr):
    def f(t): return pd.notna(t["_adx"]) and t["_adx"] >= thr
    return f
def filt_ema(t):   return bool(t["_ema_aligned"])
def make_atr(lo, hi):
    def f(t): return pd.notna(t["_atr_pctile"]) and lo <= t["_atr_pctile"] <= hi
    return f
def make_er(thr):
    def f(t): return pd.notna(t["_er"]) and t["_er"] >= thr
    return f


# ----------------------------- run a filtered config on a date window -----------------------------
def run_window(tagged, predicate, raw, lo_ts, hi_ts, decay_downweight=False):
    """Apply filter -> risk-parity -> net-USD cap -> production_replay, restricted
    to trades with entry in [lo_ts, hi_ts). Returns (profile, n_cut, cut_meanR,
    kept_meanR, pool_meanR, top5_retention)."""
    # filter + window
    filt = {}
    pool_R, cut_R, kept_R = [], [], []
    DECAY = {"USD/CHF", "EUR/GBP"}
    for s in SYMBOLS:
        lst = []
        for t in tagged[s]:
            if not (lo_ts <= t["entry_ts"] < hi_ts):
                continue
            pool_R.append(t["R"])
            if predicate(t):
                t2 = dict(t)
                if decay_downweight and s in DECAY:
                    t2["R"] = t["R"] * 0.5
                    t2["gross_R"] = t.get("gross_R", t["R"]) * 0.5
                lst.append(t2)
                kept_R.append(t["R"])
            else:
                cut_R.append(t["R"])
        filt[s] = lst
    pooled = risk_parity_trades(filt, SYMBOLS)
    admitted = apply_net_usd_cap(pooled, NET_USD_CAP, gross_cap=GROSS_CAP)
    cfg = build_cfg(raw, max_concurrent=GROSS_CAP).with_overrides(risk_pct=EFF_R)
    res = production_replay(admitted, cfg)
    p = profile(res, [t["R"] for t in admitted]) if res else None
    # top-5% winner retention: of the pool's top-5% R trades, how many survived filter?
    pool_arr = np.array(pool_R) if pool_R else np.array([0.0])
    thr95 = np.percentile(pool_arr, 95)
    n_top = int((pool_arr >= thr95).sum())
    kept_arr = np.array(kept_R) if kept_R else np.array([])
    n_top_kept = int((kept_arr >= thr95).sum()) if len(kept_arr) else 0
    retention = (n_top_kept / n_top) if n_top else 1.0
    return {
        "p": p,
        "n_pool": len(pool_R), "n_cut": len(cut_R), "n_kept": len(kept_R),
        "cut_meanR": float(np.mean(cut_R)) if cut_R else float("nan"),
        "kept_meanR": float(np.mean(kept_R)) if kept_R else float("nan"),
        "pool_meanR": float(np.mean(pool_R)) if pool_R else float("nan"),
        "top5_retention": retention,
    }


def row(name, r):
    p = r["p"]
    if p is None:
        return f"{name:<22} {'(no trades / empty)':>40}"
    return (f"{name:<22} {r['n_kept']:>5}/{r['n_pool']:<5} "
            f"ws={p['ws_median']:>+6.2f}% raw={p['median']:>+6.2f}% std={p['std']:>5.2f} "
            f"DD={p['realized_contDD']:>+6.1f}% Shrp={p['mo_sharpe']:>+5.2f} "
            f"neg={p['neg']:>3.0f}% cutR={r['cut_meanR']:>+5.2f} poolR={r['pool_meanR']:>+5.2f} "
            f"top5keep={r['top5_retention']*100:>3.0f}%")


def main():
    d = pickle.load(open("/tmp/rt_trades.pkl", "rb"))
    trades = d["trades"]
    raw = yaml.safe_load((ROOT / "configs" / "risk_forex.yaml").read_text())

    print("Loading bars + building causal regime features ...")
    bars = load_bars()
    feat = build_features(bars)
    tagged = tag_trades(trades, feat)

    # coverage / lookahead sanity
    n_total = sum(len(v) for v in tagged.values())
    n_adx_nan = sum(1 for s in SYMBOLS for t in tagged[s] if pd.isna(t["_adx"]))
    n_er_nan = sum(1 for s in SYMBOLS for t in tagged[s] if pd.isna(t["_er"]))
    print(f"tagged trades={n_total}  adx_nan={n_adx_nan}  er_nan={n_er_nan} "
          f"(nan = early bars, treated as filter-FAIL = conservative)")

    OOS_END = pd.Timestamp("2026-01-01", tz="UTC")
    windows = {"IS(2020-23)": (IS_START, IS_END), "OOS(2024-25)": (IS_END, OOS_END)}

    # ---------------- baseline (no filter) both windows ----------------
    print("\n" + "=" * 130)
    print("BASELINE (no regime filter) — netUSD<=3 mc6 eff_r=1%")
    print("=" * 130)
    base = {}
    for wname, (lo, hi) in windows.items():
        r = run_window(tagged, filt_none, raw, lo, hi)
        base[wname] = r
        print(row(f"baseline {wname}", r))

    # ---------------- IS GRID SEARCH (select threshold on IS ONLY) ----------------
    print("\n" + "=" * 130)
    print("IS GRID SEARCH — threshold chosen to MAX IS robust(ws) median. OOS NOT consulted.")
    print("=" * 130)
    lo_is, hi_is = windows["IS(2020-23)"]
    grids = {
        "F1_ADX":  [("ADX>=15", make_adx(15)), ("ADX>=20", make_adx(20)), ("ADX>=25", make_adx(25))],
        "F2_EMA":  [("EMA50/200_align", filt_ema)],
        "F3_ATR":  [("ATRpct[0.20,0.95]", make_atr(0.20, 0.95)), ("ATRpct[0.30,0.95]", make_atr(0.30, 0.95))],
        "F4_ER":   [("ER>=0.20", make_er(0.20)), ("ER>=0.30", make_er(0.30)), ("ER>=0.40", make_er(0.40))],
    }
    chosen = {}  # filter family -> (label, predicate, is_result)
    for fam, variants in grids.items():
        print(f"\n  -- {fam} --   baseline IS ws={base['IS(2020-23)']['p']['ws_median']:+.2f}%")
        best = None
        for label, pred in variants:
            r = run_window(tagged, pred, raw, lo_is, hi_is)
            ws = r["p"]["ws_median"] if r["p"] else -999
            print("   " + row(label, r))
            # tie-break: prefer higher ws; on near-tie prefer first (loosest threshold listed first)
            if best is None or ws > best[2] + 1e-9:
                best = (label, pred, ws, r)
        # STOP CRITERIA: only carry to OOS if IS ws beats baseline IS ws
        base_is_ws = base["IS(2020-23)"]["p"]["ws_median"]
        if best[2] > base_is_ws:
            chosen[fam] = best
            print(f"   => CHOSEN for OOS: {best[0]} (IS ws={best[2]:+.2f}% > baseline {base_is_ws:+.2f}%)")
        else:
            print(f"   => KILLED in IS: best {best[0]} IS ws={best[2]:+.2f}% <= baseline {base_is_ws:+.2f}% (no OOS burn)")

    # F5 decay downweight (parameterless heuristic) — eval in IS, carry if improves
    r5 = run_window(tagged, filt_none, raw, lo_is, hi_is, decay_downweight=True)
    print(f"\n  -- F5_DECAY (USD/CHF,EUR/GBP x0.5) --")
    print("   " + row("decay_x0.5", r5))
    if r5["p"]["ws_median"] > base["IS(2020-23)"]["p"]["ws_median"]:
        chosen["F5_DECAY"] = ("decay_x0.5", filt_none, r5["p"]["ws_median"], r5)
        print(f"   => CHOSEN for OOS (decay)")
    else:
        print(f"   => KILLED in IS (decay)")

    # ---------------- OOS VALIDATION (frozen thresholds, single test each) ----------------
    print("\n" + "=" * 130)
    print("OOS VALIDATION (2024-25) — frozen IS thresholds, ONE test per filter. Decision lives HERE.")
    print("=" * 130)
    lo_oos, hi_oos = windows["OOS(2024-25)"]
    base_oos = base["OOS(2024-25)"]["p"]
    print(row("baseline OOS", base["OOS(2024-25)"]))
    print("-" * 130)
    verdicts = {}
    for fam, (label, pred, is_ws, _isr) in chosen.items():
        if fam == "F5_DECAY":
            r = run_window(tagged, filt_none, raw, lo_oos, hi_oos, decay_downweight=True)
        else:
            r = run_window(tagged, pred, raw, lo_oos, hi_oos)
        p = r["p"]
        print(row(f"{fam}:{label}", r))
        # PRE-REG decision gate (all three must hold OOS)
        d_med = p["ws_median"] - base_oos["ws_median"]
        d_shrp = p["mo_sharpe"] - base_oos["mo_sharpe"]
        cuts_bad = (r["cut_meanR"] < r["pool_meanR"]) if pd.notna(r["cut_meanR"]) else False
        keep_winners = r["top5_retention"] >= 0.70
        passes = (d_med >= 0.5) and (d_shrp > 0) and cuts_bad and keep_winners
        verdicts[fam] = {
            "label": label, "d_med": d_med, "d_shrp": d_shrp,
            "cuts_bad": cuts_bad, "keep_winners": keep_winners, "pass": passes,
            "oos_ws": p["ws_median"], "oos_shrp": p["mo_sharpe"], "oos_dd": p["realized_contDD"],
            "oos_neg": p["neg"], "cut_meanR": r["cut_meanR"], "pool_meanR": r["pool_meanR"],
            "top5_keep": r["top5_retention"],
        }

    print("\n" + "=" * 130)
    print("PRE-REGISTERED DECISION GATE (OOS) — (i) Δws>=+0.5pp (ii) ΔSharpe>0 (iii) cut meanR<pool (iv) top5keep>=70%")
    print("=" * 130)
    print(f"baseline OOS: ws={base_oos['ws_median']:+.2f}% Sharpe={base_oos['mo_sharpe']:+.2f} "
          f"DD={base_oos['realized_contDD']:+.1f}% neg={base_oos['neg']:.0f}%")
    for fam, v in verdicts.items():
        tick = lambda b: "PASS" if b else "fail"
        print(f"  {fam}:{v['label']:<20} Δws={v['d_med']:>+5.2f}pp[{tick(v['d_med']>=0.5)}] "
              f"ΔShrp={v['d_shrp']:>+5.2f}[{tick(v['d_shrp']>0)}] "
              f"cutR<pool[{tick(v['cuts_bad'])}] top5keep={v['top5_keep']*100:.0f}%[{tick(v['keep_winners'])}] "
              f"=> {'ACCEPT-CANDIDATE' if v['pass'] else 'REJECT'}")

    import json
    pickle.dump({"base": {k: base[k]['p'] for k in base}, "verdicts": verdicts},
                open("/tmp/brooks_regime_verdicts.pkl", "wb"))
    print("\nDONE. verdicts -> /tmp/brooks_regime_verdicts.pkl")


if __name__ == "__main__":
    main()
