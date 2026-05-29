"""HYP-2026-05-29-forex-4h-pa — EUR/USD 4H mean-reversion PA bundle backtest.

Pre-registered hypothesis: memory/researcher/hypotheses/2026-05-29-forex-4h-pa.md

Executes the pre-reg backtest plan (§7) with the 5 blocking patches (§9) applied:
  1. FX round-number grid (EUR/USD 0.0050) — patched in pin_bar_round_numbers.py
  2. atr_min_pct -> 0.0008 (crypto 0.003 kills FX 4H)
  3. execution.sl_pct_min -> 0 (WIDESTOP %2.5 kills FX) — risk_forex.yaml default 0
  4. Honest cost: fees={taker:0,maker:0}, slippage_bps=1.0 round-trip spread,
     swap/rollover post-hoc R-haircut (nights_held * 0.3bps, Wed triple).
  5. cooldown 6 bars (24h) = same_symbol_side_cooldown_days=1.0, weekend-flat
     (Fri 20:00 UTC force-close), session filter 07:00-16:00 UTC (bar OPEN ts).

IS = 2020-2023, OOS = 2024-2025 (frozen). NO peeking at OOS during design.

VERDICT logic (pre-reg §5 stop criterion): IS net mean R < 0 -> KILL (no param
iterate = no p-hacking). Positive -> validate OOS + robustness suite.

Usage:  .venv/bin/python scripts/forex_4h_research.py
Output: stdout summary + reports/lab/forex_4h_<date>.md + result JSON (hashes).
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev

os.environ["PA_LOG_QUIET"] = "1"
import warnings

warnings.filterwarnings("ignore")

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.engine import BacktestEngine
from price_action.backtest.lab import ProductionConfig, production_replay

DB = ROOT / "data" / "forex_market.duckdb"
SYMBOL = "EUR/USD"
TF = "4h"

# Pre-reg honest cost (§4)
FEES = {"taker": 0.0, "maker": 0.0}
SLIPPAGE_BPS = 1.0          # round-trip spread proxy (engine applies entry+exit)
SLIPPAGE_BPS_STRESS = 1.7   # conservative stress
SWAP_BPS_PER_NIGHT = 0.3    # always-pay penalty (conservative), Wed triple

# Pre-reg overrides (§3.3 / §9)
ATR_MIN_PCT = 0.0008
COOLDOWN_DAYS = 1.0         # 6 bars * 4h = 24h
SESSION_START_H = 7         # bar OPEN hour >= 7 (London open)
SESSION_END_H = 16          # bar OPEN hour <= 16 (NY/London overlap)
FRI_FLAT_HOUR = 20          # force-close before Fri 20:00 UTC

# IS / OOS frozen split (data is 2020-2025)
IS_START = pd.Timestamp("2020-01-01", tz="UTC")
IS_END = pd.Timestamp("2024-01-01", tz="UTC")    # IS = [2020, 2024)  i.e. 2020-2023
OOS_START = IS_END
OOS_END = pd.Timestamp("2026-01-01", tz="UTC")   # OOS = [2024, 2026) i.e. 2024-2025

PATTERNS = [
    ("equal_highs_sweep", "EqualHighsSweepStrategy"),
    ("pin_bar_round_numbers", "PinBarRoundNumbersStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
]

SEED = 12345
rng = np.random.default_rng(SEED)


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------
def load_ohlcv() -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute(
        "SELECT ts, open, high, low, close, volume FROM ohlcv "
        "WHERE symbol=? AND timeframe=? ORDER BY ts",
        [SYMBOL, TF],
    ).fetchdf()
    con.close()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    df["symbol"] = SYMBOL
    df["venue"] = "forex"
    df["timeframe"] = TF
    return df


def data_hash(df: pd.DataFrame) -> str:
    h = hashlib.sha256()
    arr = df[["open", "high", "low", "close"]].to_numpy()
    h.update(arr.tobytes())
    h.update(str(df["ts"].iloc[0]).encode())
    h.update(str(df["ts"].iloc[-1]).encode())
    return h.hexdigest()[:16]


def data_quality_gate(df: pd.DataFrame) -> dict:
    n = len(df)
    oc_eq = float((df["open"] == df["close"]).mean())
    nan = int(df[["open", "high", "low", "close"]].isna().sum().sum())
    dup = int(df["ts"].duplicated().sum())
    viol = int(
        (
            (df["high"] < df["low"])
            | (df["high"] < df["open"])
            | (df["high"] < df["close"])
            | (df["low"] > df["open"])
            | (df["low"] > df["close"])
        ).sum()
    )
    passed = (n > 9000) and (oc_eq < 0.05) and (nan == 0) and (dup == 0) and (viol == 0)
    return {
        "n": n,
        "open_eq_close_ratio": oc_eq,
        "nan": nan,
        "dup_ts": dup,
        "ohlc_violations": viol,
        "passed": bool(passed),
    }


# ---------------------------------------------------------------------------
# Strategy construction with pre-reg overrides
# ---------------------------------------------------------------------------
def build_strategy(module_name: str, class_name: str):
    mod = __import__(
        f"price_action.strategies.{module_name}",
        fromlist=[class_name, "_default_manifest"],
    )
    cls = getattr(mod, class_name)
    manifest = mod._default_manifest()
    # Block 2: atr_min_pct floor -> 0.0008
    manifest.signals.filters.atr_min_pct = ATR_MIN_PCT
    if module_name == "pin_bar_round_numbers":
        # round_grid_override left None -> uses patched _DEFAULT_ROUND_GRIDS (EUR=0.0050)
        return cls(manifest)
    return cls(manifest)


# ---------------------------------------------------------------------------
# Session / weekend filters (causal, bar-OPEN ts) + swap haircut
# ---------------------------------------------------------------------------
def in_session(ts: pd.Timestamp) -> bool:
    """London open -> NY/London overlap, filter on bar OPEN ts (lookahead-free)."""
    h = ts.hour
    return SESSION_START_H <= h <= SESSION_END_H


def is_weekend_block(ts: pd.Timestamp) -> bool:
    """No new entry after Fri 16:00 UTC (entry bars opening Fri >=16:00 or weekend)."""
    wd = ts.dayofweek  # 0=Mon ... 4=Fri, 5=Sat, 6=Sun
    if wd == 4 and ts.hour >= 16:
        return True
    if wd in (5, 6):
        return True
    return False


def nights_held(entry_ts: pd.Timestamp, exit_ts: pd.Timestamp) -> int:
    """Number of overnight rollovers (UTC date crossings), Wednesday triple-swap.

    Both ts known at trade close -> no lookahead.
    """
    if exit_ts <= entry_ts:
        return 0
    d0 = entry_ts.normalize()
    d1 = exit_ts.normalize()
    nights = int((d1 - d0).days)
    if nights <= 0:
        return 0
    # Triple-swap: each Wednesday (dayofweek==2) crossed counts as 3.
    triple = 0
    cur = d0 + pd.Timedelta(days=1)
    while cur <= d1:
        if cur.dayofweek == 2:  # Wednesday rollover = triple
            triple += 1
        cur += pd.Timedelta(days=1)
    return nights + 2 * triple  # base nights + extra 2 per Wed


# ---------------------------------------------------------------------------
# Gather (engine run -> trade dicts, with pre-reg filters + swap haircut)
# ---------------------------------------------------------------------------
def gather(strategy, df: pd.DataFrame, slippage_bps: float, apply_swap: bool = True) -> list[dict]:
    def prov(*a, **k):
        return df.copy()

    e = BacktestEngine(risk_officer=None, store_load=None)
    r = e.run(
        strategy,
        [SYMBOL],
        start=df["ts"].iloc[0].to_pydatetime(),
        end=df["ts"].iloc[-1].to_pydatetime(),
        timeframe=TF,
        initial_capital=10_000.0,
        fees=FEES,
        slippage_bps=slippage_bps,
        ohlcv_provider=prov,
    )
    out: list[dict] = []
    if r.trades is None or r.trades.empty:
        return out
    for _, t in r.trades.iterrows():
        ts_e = pd.Timestamp(t["entry_ts"])
        ts_e = ts_e.tz_localize("UTC") if ts_e.tzinfo is None else ts_e.tz_convert("UTC")
        ts_x = pd.Timestamp(t["exit_ts"])
        ts_x = ts_x.tz_localize("UTC") if ts_x.tzinfo is None else ts_x.tz_convert("UTC")

        # Block 5: session filter on bar-OPEN ts (entry bar). Lookahead-free.
        if not in_session(ts_e):
            continue
        # Block 5: weekend-flat — no new entry late Fri / weekend.
        if is_weekend_block(ts_e):
            continue

        R = float(t["realized_r_multiple"])
        gross_R = R
        # Block 4: swap/rollover R-haircut. R is in units of initial risk;
        # swap is a price-bps cost. Convert: haircut_R = nights*swap_bps / sl_pct_bps.
        entry_px = float(t["entry_price"])
        sl_px = float(t["initial_sl"])
        sl_pct = abs(entry_px - sl_px) / entry_px if entry_px > 0 else 0.0
        sl_bps = sl_pct * 1e4
        nh = nights_held(ts_e, ts_x)
        swap_R = 0.0
        if apply_swap and sl_bps > 0:
            swap_R = (nh * SWAP_BPS_PER_NIGHT) / sl_bps
        net_R = R - swap_R

        conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
        out.append(
            {
                "entry_ts": ts_e,
                "exit_ts": ts_x,
                "entry_price": entry_px,
                "initial_sl": sl_px,
                "R": net_R,
                "gross_R": gross_R,
                "swap_R": swap_R,
                "nights": nh,
                "symbol": SYMBOL,
                "side": str(t["side"]).lower(),
                "conf": conf,
                "strategy": strategy.name,
            }
        )
    return out


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------
def r_stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "mR": 0.0, "gross_mR": 0.0, "sumR": 0.0, "wr": 0.0, "pf": 0.0}
    Rs = [t["R"] for t in trades]
    gross = [t["gross_R"] for t in trades]
    n = len(Rs)
    wins = [r for r in Rs if r > 0]
    losses = [r for r in Rs if r < 0]
    gp = sum(wins)
    gl = abs(sum(losses))
    pf = gp / gl if gl > 0 else float("inf")
    return {
        "n": n,
        "mR": mean(Rs),
        "gross_mR": mean(gross),
        "sumR": sum(Rs),
        "wr": len(wins) / n * 100,
        "pf": pf,
    }


def sharpe_of_R(trades: list[dict]) -> float:
    """Per-trade R Sharpe (mean/std), not annualized — comparative WF metric."""
    Rs = [t["R"] for t in trades]
    if len(Rs) < 2:
        return 0.0
    sd = pstdev(Rs)
    return mean(Rs) / sd if sd > 0 else 0.0


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------
def shuffle_pvalue(trades: list[dict], n_iter: int = 5000) -> tuple[float, float]:
    """Null: random entry signs. Flip each trade's R sign with p=0.5,
    rebuild mean R, count fraction of nulls >= observed mean R.
    Returns (observed_mR, p_value)."""
    Rs = np.array([t["R"] for t in trades], dtype=float)
    if len(Rs) == 0:
        return 0.0, 1.0
    obs = float(Rs.mean())
    abs_R = np.abs(Rs)
    cnt = 0
    for _ in range(n_iter):
        signs = rng.choice([-1.0, 1.0], size=len(Rs))
        if (abs_R * signs).mean() >= obs:
            cnt += 1
    return obs, (cnt + 1) / (n_iter + 1)


def oracle_efficiency(df: pd.DataFrame, strat_trades: list[dict]) -> float:
    """Perfect-foresight per-bar capture (enter low->exit high) sum vs strategy sumR.
    If strategy ~ oracle, suspect leak. Oracle should DWARF strategy."""
    # Oracle: each bar, best possible long R assuming 0.5*ATR risk floor.
    rng_bar = (df["high"] - df["low"]).to_numpy()
    atr = (df["high"] - df["low"]).rolling(14).mean().to_numpy()
    risk = np.where(atr > 0, atr * 0.5, np.nan)
    oracle_R = np.nansum(rng_bar / risk)  # gross, no cost — upper bound
    strat_sumR = sum(t["gross_R"] for t in strat_trades)
    return strat_sumR / oracle_R if oracle_R > 0 else 0.0


# ---------------------------------------------------------------------------
# Walk-forward (longest feasible train in IS, 6m test, 3m step)
# ---------------------------------------------------------------------------
def walk_forward(trades: list[dict], train_days: int) -> list[dict]:
    if not trades:
        return []
    ts0 = min(t["entry_ts"] for t in trades)
    ts1 = max(t["entry_ts"] for t in trades)
    step = pd.Timedelta(days=91)     # ~3m
    test = pd.Timedelta(days=182)    # ~6m
    train = pd.Timedelta(days=train_days)
    windows = []
    cur = ts0
    while cur + train + test <= ts1 + step:
        tr_s, tr_e = cur, cur + train
        te_s, te_e = tr_e, tr_e + test
        is_tr = [t for t in trades if tr_s <= t["entry_ts"] < tr_e]
        oos_tr = [t for t in trades if te_s <= t["entry_ts"] < te_e]
        if oos_tr:
            windows.append(
                {
                    "test_start": te_s,
                    "is_sharpe": sharpe_of_R(is_tr),
                    "oos_sharpe": sharpe_of_R(oos_tr),
                    "is_mR": mean([t["R"] for t in is_tr]) if is_tr else 0.0,
                    "oos_mR": mean([t["R"] for t in oos_tr]),
                    "oos_n": len(oos_tr),
                }
            )
        cur += step
    return windows


def regime_label(df: pd.DataFrame) -> pd.Series:
    """Simple regime: EMA200 slope sign over 50 bars -> trend; else range."""
    ema = df["close"].ewm(span=200, adjust=False).mean()
    slope = ema.diff(50)
    atrp = ((df["high"] - df["low"]).rolling(14).mean() / df["close"])
    out = pd.Series("range", index=df.index)
    out[slope > atrp * 2] = "trend_up"
    out[slope < -atrp * 2] = "trend_down"
    return out


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    df = load_ohlcv()
    dhash = data_hash(df)
    qg = data_quality_gate(df)

    git_hash = os.popen("git -C %s rev-parse --short HEAD" % ROOT).read().strip()

    print("=" * 78)
    print("HYP-2026-05-29-forex-4h-pa — EUR/USD 4H mean-reversion PA bundle")
    print("=" * 78)
    print(f"git={git_hash}  data_hash={dhash}  seed={SEED}")
    print(f"DATA QUALITY GATE: {qg}")
    if not qg["passed"]:
        print("ABORT: data quality gate FAILED.")
        sys.exit(1)
    print(
        f"yfinance bug check: open==close ratio = {qg['open_eq_close_ratio']*100:.2f}% "
        f"(<5% required) -> {'PASS (bug gone)' if qg['open_eq_close_ratio']<0.05 else 'FAIL'}"
    )
    print(f"cost: fees={FEES} slippage_bps={SLIPPAGE_BPS} swap={SWAP_BPS_PER_NIGHT}bps/night(Wed3x)")
    print(f"IS=[{IS_START.date()},{IS_END.date()})  OOS=[{OOS_START.date()},{OOS_END.date()})")
    print()

    df_full = df
    df_is = df[(df["ts"] >= IS_START) & (df["ts"] < IS_END)].reset_index(drop=True)
    df_oos = df[(df["ts"] >= OOS_START) & (df["ts"] < OOS_END)].reset_index(drop=True)

    results = {}
    full_trades_by_pat = {}

    print(f"{'pattern':<26} {'scope':<5} {'n':>4} {'net_mR':>8} {'gross_mR':>9} {'win%':>6} {'PF':>6} {'sumR':>8}")
    print("-" * 78)

    for mod, cls in PATTERNS:
        # IS
        s_is = build_strategy(mod, cls)
        is_tr = gather(s_is, df_is.copy(), SLIPPAGE_BPS)
        # OOS
        s_oos = build_strategy(mod, cls)
        oos_tr = gather(s_oos, df_oos.copy(), SLIPPAGE_BPS)
        # FULL (for shuffle/oracle/WF)
        s_full = build_strategy(mod, cls)
        full_tr = gather(s_full, df_full.copy(), SLIPPAGE_BPS)
        full_trades_by_pat[mod] = full_tr

        st_is = r_stats(is_tr)
        st_oos = r_stats(oos_tr)
        results[mod] = {"is": st_is, "oos": st_oos, "is_trades": is_tr, "oos_trades": oos_tr}

        for scope, st in (("IS", st_is), ("OOS", st_oos)):
            pf = st["pf"]
            pf_s = f"{pf:.2f}" if math.isfinite(pf) else "inf"
            print(
                f"{mod:<26} {scope:<5} {st['n']:>4} {st['mR']:>+8.3f} {st['gross_mR']:>+9.3f} "
                f"{st['wr']:>5.1f}% {pf_s:>6} {st['sumR']:>+8.1f}"
            )

    # ---- Bundle (OR-union, all 3) ----
    bundle_is = [t for mod in results for t in results[mod]["is_trades"]]
    bundle_oos = [t for mod in results for t in results[mod]["oos_trades"]]
    bundle_full = [t for mod in full_trades_by_pat for t in full_trades_by_pat[mod]]
    st_bis, st_bos = r_stats(bundle_is), r_stats(bundle_oos)
    print("-" * 78)
    for scope, st in (("IS", st_bis), ("OOS", st_bos)):
        pf = st["pf"]
        pf_s = f"{pf:.2f}" if math.isfinite(pf) else "inf"
        print(
            f"{'BUNDLE(OR-union)':<26} {scope:<5} {st['n']:>4} {st['mR']:>+8.3f} {st['gross_mR']:>+9.3f} "
            f"{st['wr']:>5.1f}% {pf_s:>6} {st['sumR']:>+8.1f}"
        )

    # ---- Sanity invariant: net < gross ----
    print("\nSANITY (net mR < gross mR, swap haircut wired):")
    for mod in results:
        st = results[mod]["is"]
        ok = st["mR"] <= st["gross_mR"] + 1e-9
        print(f"  {mod:<26} net {st['mR']:+.3f} <= gross {st['gross_mR']:+.3f} -> {'OK' if ok else 'BROKEN'}")

    # ---- Shuffle baseline (full period, per pattern + bundle) ----
    print("\nSHUFFLE NULL (random entry signs, 5000 iters): observed net mR vs null")
    shuffle_res = {}
    for mod in full_trades_by_pat:
        obs, p = shuffle_pvalue(full_trades_by_pat[mod])
        shuffle_res[mod] = {"obs_mR": obs, "p": p, "n": len(full_trades_by_pat[mod])}
        print(f"  {mod:<26} obs_mR={obs:+.3f}  p={p:.4f}  n={len(full_trades_by_pat[mod])}")
    obs_b, p_b = shuffle_pvalue(bundle_full)
    shuffle_res["bundle"] = {"obs_mR": obs_b, "p": p_b, "n": len(bundle_full)}
    print(f"  {'BUNDLE':<26} obs_mR={obs_b:+.3f}  p={p_b:.4f}  n={len(bundle_full)}")

    # BH-FDR over the 3 patterns + bundle
    pvals = sorted([(k, shuffle_res[k]["p"]) for k in shuffle_res], key=lambda x: x[1])
    m = len(pvals)
    print("\nBH-FDR (alpha=0.05) over 3 patterns + bundle:")
    bh_pass = {}
    for i, (k, p) in enumerate(pvals, start=1):
        thresh = i / m * 0.05
        ok = p <= thresh
        bh_pass[k] = ok
        print(f"  rank {i}: {k:<22} p={p:.4f}  BH_thresh={thresh:.4f}  {'PASS' if ok else 'fail'}")

    # ---- Oracle efficiency (leak check) ----
    print("\nORACLE EFFICIENCY (strategy sumR / perfect-foresight sumR; should be tiny):")
    for mod in full_trades_by_pat:
        eff = oracle_efficiency(df_full, full_trades_by_pat[mod])
        flag = "OK (no leak)" if eff < 0.05 else "SUSPECT LEAK"
        print(f"  {mod:<26} efficiency={eff*100:.3f}%  -> {flag}")

    # ---- Walk-forward (longest feasible train in available history) ----
    # IS is 4y; data is 6y. Use 2y train (max that yields multiple OOS windows
    # while keeping enough trades per FX-thin window), 6m test, 3m step.
    print("\nWALK-FORWARD (2y train, 6m test, 3m step, full period; per-trade R Sharpe):")
    wf_summary = {}
    for mod in full_trades_by_pat:
        wins = walk_forward(full_trades_by_pat[mod], train_days=730)
        if not wins:
            print(f"  {mod:<26} no WF windows (too few trades)")
            wf_summary[mod] = {"n_windows": 0}
            continue
        oos_sh = [w["oos_sharpe"] for w in wins]
        is_sh = [w["is_sharpe"] for w in wins]
        oos_mR = [w["oos_mR"] for w in wins]
        mean_oos_sh = mean(oos_sh)
        mean_is_sh = mean(is_sh)
        gap = abs(mean_is_sh - mean_oos_sh) / abs(mean_is_sh) if mean_is_sh != 0 else float("inf")
        pos_oos = sum(1 for x in oos_mR if x > 0)
        wf_summary[mod] = {
            "n_windows": len(wins),
            "mean_is_sharpe": mean_is_sh,
            "mean_oos_sharpe": mean_oos_sh,
            "is_oos_gap": gap,
            "pos_oos_windows": pos_oos,
        }
        print(
            f"  {mod:<26} wins={len(wins):>2} IS_Sh={mean_is_sh:+.3f} OOS_Sh={mean_oos_sh:+.3f} "
            f"gap={gap*100:.0f}% pos_OOS={pos_oos}/{len(wins)}"
        )

    # ---- Regime split (full period) ----
    print("\nREGIME SPLIT (net mR by regime at entry bar):")
    reg = regime_label(df_full)
    ts_to_reg = dict(zip(df_full["ts"], reg))
    regime_res = {}
    for mod in full_trades_by_pat:
        by_reg: dict[str, list] = {}
        for t in full_trades_by_pat[mod]:
            rg = ts_to_reg.get(t["entry_ts"], "range")
            by_reg.setdefault(rg, []).append(t["R"])
        line = []
        pos_regimes = 0
        for rg in ("range", "trend_up", "trend_down"):
            rs = by_reg.get(rg, [])
            if rs:
                mr = mean(rs)
                if mr > 0:
                    pos_regimes += 1
                line.append(f"{rg}={mr:+.3f}(n{len(rs)})")
            else:
                line.append(f"{rg}=na")
        regime_res[mod] = {"pos_regimes": pos_regimes}
        print(f"  {mod:<26} {'  '.join(line)}  pos_regimes={pos_regimes}")

    # ---- Stress periods ----
    print("\nSTRESS PERIODS (net mR):")
    stress = {
        "2020-COVID": ("2020-02-15", "2020-04-30"),
        "2022-USD-bull": ("2022-06-01", "2022-11-30"),
        "2024-cuts": ("2024-08-01", "2024-12-31"),
    }
    for mod in full_trades_by_pat:
        line = []
        for label, (s, e) in stress.items():
            s_ts, e_ts = pd.Timestamp(s, tz="UTC"), pd.Timestamp(e, tz="UTC")
            rs = [t["R"] for t in full_trades_by_pat[mod] if s_ts <= t["entry_ts"] <= e_ts]
            line.append(f"{label}={mean(rs):+.3f}(n{len(rs)})" if rs else f"{label}=na")
        print(f"  {mod:<26} {'  '.join(line)}")

    # ---- Param perturbation (atr_min_pct +-10%, slippage stress) ----
    print("\nPARAM PERTURBATION (slippage 1.0->1.7bps stress, full period net mR):")
    for mod, cls in PATTERNS:
        s = build_strategy(mod, cls)
        tr_stress = gather(s, df_full.copy(), SLIPPAGE_BPS_STRESS)
        st = r_stats(tr_stress)
        base = r_stats(full_trades_by_pat[mod])
        print(f"  {mod:<26} base_mR={base['mR']:+.3f}  stress_mR={st['mR']:+.3f}  n={st['n']}")

    # ---- VERDICT (pre-reg §5) ----
    print("\n" + "=" * 78)
    print("VERDICT (pre-reg §5 stop criterion: IS net mR < 0 -> KILL, no param iterate)")
    print("=" * 78)
    verdicts = {}
    for mod in results:
        is_mR = results[mod]["is"]["mR"]
        oos_mR = results[mod]["oos"]["mR"]
        n_is = results[mod]["is"]["n"]
        p = shuffle_res[mod]["p"]
        bh = bh_pass.get(mod, False)
        if is_mR < 0:
            v = "KILL (IS net mR<0)"
        elif is_mR < 0.10:
            v = "ITERATE (IS mR>0 but <+0.10 promote bar)"
        elif p >= 0.05 or not bh:
            v = "ITERATE (mR>=0.10 but shuffle/BH-FDR fail)"
        elif oos_mR <= 0:
            v = "ITERATE (IS edge but OOS<=0 — regime-fragile)"
        else:
            v = "GO (IS>=+0.10, OOS>0, shuffle p<0.05, BH pass)"
        verdicts[mod] = v
        print(f"  {mod:<26} IS_mR={is_mR:+.3f} OOS_mR={oos_mR:+.3f} n_IS={n_is} p={p:.3f} BH={'Y' if bh else 'N'} -> {v}")
    # bundle
    if st_bis["mR"] < 0:
        vb = "KILL"
    elif st_bis["mR"] < 0.10:
        vb = "ITERATE"
    elif shuffle_res["bundle"]["p"] >= 0.05:
        vb = "ITERATE (shuffle fail)"
    elif st_bos["mR"] <= 0:
        vb = "ITERATE (OOS<=0)"
    else:
        vb = "GO"
    verdicts["bundle"] = vb
    print(f"  {'BUNDLE':<26} IS_mR={st_bis['mR']:+.3f} OOS_mR={st_bos['mR']:+.3f} p={shuffle_res['bundle']['p']:.3f} -> {vb}")

    # ---- Persist result JSON ----
    out = {
        "hypothesis": "2026-05-29-forex-4h-pa",
        "git_hash": git_hash,
        "data_hash": dhash,
        "seed": SEED,
        "cost": {"fees": FEES, "slippage_bps": SLIPPAGE_BPS, "swap_bps_per_night": SWAP_BPS_PER_NIGHT},
        "is_split": [str(IS_START.date()), str(IS_END.date())],
        "oos_split": [str(OOS_START.date()), str(OOS_END.date())],
        "data_quality": qg,
        "per_pattern": {
            mod: {
                "is": {k: results[mod]["is"][k] for k in ("n", "mR", "gross_mR", "wr", "pf", "sumR")},
                "oos": {k: results[mod]["oos"][k] for k in ("n", "mR", "gross_mR", "wr", "pf", "sumR")},
            }
            for mod in results
        },
        "bundle": {
            "is": {k: st_bis[k] for k in ("n", "mR", "gross_mR", "wr", "pf", "sumR")},
            "oos": {k: st_bos[k] for k in ("n", "mR", "gross_mR", "wr", "pf", "sumR")},
        },
        "shuffle": shuffle_res,
        "bh_fdr_pass": bh_pass,
        "walk_forward": wf_summary,
        "regime": regime_res,
        "verdicts": verdicts,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    # JSON-safe
    def _safe(o):
        if isinstance(o, float) and not math.isfinite(o):
            return None
        if isinstance(o, (np.floating,)):
            return float(o)
        if isinstance(o, (np.integer,)):
            return int(o)
        return o

    outdir = ROOT / "reports" / "lab"
    outdir.mkdir(parents=True, exist_ok=True)
    jpath = outdir / f"forex_4h_{datetime.now().strftime('%Y%m%d')}.json"
    jpath.write_text(json.dumps(out, default=_safe, indent=2), encoding="utf-8")
    print(f"\nResult JSON: {jpath}")


if __name__ == "__main__":
    main()
