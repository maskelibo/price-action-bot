"""Quick-screen of 5 NEW EUR/USD 4H price-action edge families vs honest cost.

Pre-registered (code-after-prereg):
  F1 london_open_breakout     memory/.../2026-05-29-forex-london-open-breakout.md
  F2 ny_session_fade          memory/.../2026-05-29-forex-ny-session-fade.md
  F3 ema20_pullback           memory/.../2026-05-29-forex-ema20-pullback.md
  F4 bollinger_fade           memory/.../2026-05-29-forex-bollinger-fade.md
  F5 atr_squeeze_breakout     memory/.../2026-05-29-forex-atr-squeeze-breakout.md

Honest cost model is IDENTICAL to scripts/forex_4h_research.py:
  fee=0, slip 1.0bps round-trip, swap 0.3bps/night (Wed triple),
  session bar-OPEN 07-16 UTC, weekend no-entry, cooldown 6 bars (24h).

Lookahead paranoia:
  - All signal logic uses bars <= t only.
  - Entry is ALWAYS next bar (t+1) OPEN.
  - Intrabar fill: if both SL and TP touched in same bar, assume SL-first (conservative).
  - SL/TP computed at signal time t (no future info).

IS=2020-2023, OOS=2024-2025 frozen. Verdict per pre-reg:
  IS net mR<=0 -> KILL ; 0<mR<0.10 -> ITERATE ; mR>=0.10 & OOS>0 & p<0.05 -> GO else ITERATE.

Usage: .venv/bin/python scripts/forex_4h_newfamilies_screen.py
"""
from __future__ import annotations

import hashlib
import math
import os
import subprocess
import sys
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

DB = ROOT / "data" / "forex_market.duckdb"
SYMBOL = "EUR/USD"
TF = "4h"

SLIPPAGE_BPS = 1.0          # round-trip spread proxy (split entry+exit)
SLIPPAGE_BPS_STRESS = 1.7
SWAP_BPS_PER_NIGHT = 0.3
SESSION_START_H = 7
SESSION_END_H = 16
SEED = 12345
rng = np.random.default_rng(SEED)

IS_START = pd.Timestamp("2020-01-01", tz="UTC")
IS_END = pd.Timestamp("2024-01-01", tz="UTC")
OOS_START = IS_END
OOS_END = pd.Timestamp("2026-01-01", tz="UTC")

COOLDOWN_BARS = 6


# --------------------------------------------------------------------------- data
def load_ohlcv() -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute(
        "SELECT ts, open, high, low, close FROM ohlcv WHERE symbol=? AND timeframe=? ORDER BY ts",
        [SYMBOL, TF],
    ).fetchdf()
    con.close()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    return df


def data_hash(df: pd.DataFrame) -> str:
    h = hashlib.sha256()
    h.update(df[["open", "high", "low", "close"]].to_numpy().tobytes())
    h.update(str(df["ts"].iloc[0]).encode())
    h.update(str(df["ts"].iloc[-1]).encode())
    return h.hexdigest()[:16]


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - c.shift(1)).abs(),
        (df["low"] - c.shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr14"] = tr.rolling(14, min_periods=14).mean()
    df["ema20"] = c.ewm(span=20, adjust=False).mean()
    df["ema50"] = c.ewm(span=50, adjust=False).mean()
    df["ema200"] = c.ewm(span=200, adjust=False).mean()
    df["sma20"] = c.rolling(20, min_periods=20).mean()
    df["bb_std"] = c.rolling(20, min_periods=20).std(ddof=0)
    df["bb_up"] = df["sma20"] + 2.0 * df["bb_std"]
    df["bb_dn"] = df["sma20"] - 2.0 * df["bb_std"]
    # Donchian 20 using bars [t-20..t-1]
    df["don20_hi"] = df["high"].shift(1).rolling(20, min_periods=20).max()
    df["don20_lo"] = df["low"].shift(1).rolling(20, min_periods=20).min()
    df["atr_med50"] = df["atr14"].rolling(50, min_periods=50).median()
    df["hour"] = df["ts"].dt.hour
    df["dow"] = df["ts"].dt.dayofweek
    return df


# --------------------------------------------------------------------------- filters
def in_session(ts: pd.Timestamp) -> bool:
    return SESSION_START_H <= ts.hour <= SESSION_END_H


def is_weekend_block(ts: pd.Timestamp) -> bool:
    wd = ts.dayofweek
    if wd == 4 and ts.hour >= 16:
        return True
    return wd in (5, 6)


def nights_held(entry_ts: pd.Timestamp, exit_ts: pd.Timestamp) -> int:
    if exit_ts <= entry_ts:
        return 0
    d0 = entry_ts.normalize()
    d1 = exit_ts.normalize()
    nights = int((d1 - d0).days)
    if nights <= 0:
        return 0
    triple = 0
    cur = d0 + pd.Timedelta(days=1)
    while cur <= d1:
        if cur.dayofweek == 2:
            triple += 1
        cur += pd.Timedelta(days=1)
    return nights + 2 * triple


# --------------------------------------------------------------------------- signal detectors
# Each returns list of dicts: {sig_idx, side, sl, tp} where sig_idx is the bar index t
# at which the signal is CONFIRMED (decision bar). Entry happens at t+1 OPEN.

def sig_f1_london_breakout(df: pd.DataFrame) -> list[dict]:
    """08:00 UTC bar range; break confirmed on 12:00 UTC bar in trend direction.
    Decision bar t = the 12:00 bar; entry t+1 open. SL=08:00 opp extreme, TP 2R."""
    out = []
    h, l, c, o = df["high"].values, df["low"].values, df["close"].values, df["open"].values
    e50, e200 = df["ema50"].values, df["ema200"].values
    hour = df["hour"].values
    for t in range(1, len(df)):
        if hour[t] != 12 or hour[t - 1] != 8:
            continue
        if np.isnan(e200[t]):
            continue
        rng_hi, rng_lo = h[t - 1], l[t - 1]  # 08:00 bar range
        up_trend = e50[t] > e200[t]
        # breakout confirmed on the 12:00 bar (close beyond 08:00 extreme)
        if up_trend and c[t] > rng_hi:
            entry_ref = c[t]  # proxy; real entry t+1 open
            sl = rng_lo
            risk = entry_ref - sl
            if risk <= 0:
                continue
            out.append({"sig_idx": t, "side": "long", "sl": sl, "tp": entry_ref + 2 * risk})
        elif (not up_trend) and c[t] < rng_lo:
            entry_ref = c[t]
            sl = rng_hi
            risk = sl - entry_ref
            if risk <= 0:
                continue
            out.append({"sig_idx": t, "side": "short", "sl": sl, "tp": entry_ref - 2 * risk})
    return out


def sig_f2_ny_fade(df: pd.DataFrame) -> list[dict]:
    """European 08:00+12:00 extension >=1 ATR -> fade at 16:00 bar.
    Decision bar t = 16:00 bar's PRIOR info: we use the two completed bars
    (t-2=08:00, t-1=12:00) and decide at t (16:00) close? NO — entry must be next bar.
    To keep next-bar-open execution: decision at t-1 (12:00 close), entry at t (16:00) open.
    So sig_idx = the 12:00 bar; entry = 16:00 open (t+1)."""
    out = []
    h, l, c, o = df["high"].values, df["low"].values, df["close"].values, df["open"].values
    atr = df["atr14"].values
    hour = df["hour"].values
    for t in range(2, len(df)):
        # t is the 12:00 bar (decision), t-1 = 08:00 bar
        if hour[t] != 12 or hour[t - 1] != 8:
            continue
        if np.isnan(atr[t]):
            continue
        ext = c[t] - o[t - 1]            # move across 08:00 open -> 12:00 close
        sess_hi = max(h[t], h[t - 1])
        sess_lo = min(l[t], l[t - 1])
        mid = 0.5 * (sess_hi + sess_lo)
        if ext >= 1.0 * atr[t]:
            # over-extended UP -> fade SHORT at 16:00 open
            entry_ref = c[t]
            sl = sess_hi + 0.25 * atr[t]
            risk = sl - entry_ref
            tp = mid
            if risk <= 0 or tp >= entry_ref:
                continue
            out.append({"sig_idx": t, "side": "short", "sl": sl, "tp": tp})
        elif ext <= -1.0 * atr[t]:
            entry_ref = c[t]
            sl = sess_lo - 0.25 * atr[t]
            risk = entry_ref - sl
            tp = mid
            if risk <= 0 or tp <= entry_ref:
                continue
            out.append({"sig_idx": t, "side": "long", "sl": sl, "tp": tp})
    return out


def sig_f3_ema20_pullback(df: pd.DataFrame) -> list[dict]:
    """Trend (EMA50/200) + pullback touch EMA20 + resumption close. Entry t+1 open, 2R."""
    out = []
    h, l, c, o = df["high"].values, df["low"].values, df["close"].values, df["open"].values
    e20, e50, e200, atr = df["ema20"].values, df["ema50"].values, df["ema200"].values, df["atr14"].values
    for t in range(3, len(df)):
        if np.isnan(e200[t]) or np.isnan(atr[t]):
            continue
        band = 0.25 * atr[t]
        if e50[t] > e200[t]:  # uptrend, look for long
            touched = l[t] <= e20[t] + band and l[t] >= e20[t] - 3 * band  # dipped to value
            # prior 1-3 bars net counter-trend (pullback down)
            pulled = c[t - 1] < c[t - 3]
            resume = c[t] > e20[t] and c[t] > o[t]
            if touched and pulled and resume:
                sw_lo = min(l[t - 2], l[t - 1], l[t])
                sl = sw_lo - 0.5 * atr[t]
                entry_ref = c[t]
                risk = entry_ref - sl
                if risk <= 0:
                    continue
                out.append({"sig_idx": t, "side": "long", "sl": sl, "tp": entry_ref + 2 * risk})
        elif e50[t] < e200[t]:  # downtrend, short
            touched = h[t] >= e20[t] - band and h[t] <= e20[t] + 3 * band
            pulled = c[t - 1] > c[t - 3]
            resume = c[t] < e20[t] and c[t] < o[t]
            if touched and pulled and resume:
                sw_hi = max(h[t - 2], h[t - 1], h[t])
                sl = sw_hi + 0.5 * atr[t]
                entry_ref = c[t]
                risk = sl - entry_ref
                if risk <= 0:
                    continue
                out.append({"sig_idx": t, "side": "short", "sl": sl, "tp": entry_ref - 2 * risk})
    return out


def sig_f4_bollinger_fade(df: pd.DataFrame) -> list[dict]:
    """Fresh 2sigma pierce -> fade to SMA20 midline. Entry t+1 open."""
    out = []
    h, l, c = df["high"].values, df["low"].values, df["close"].values
    up, dn, mid, atr = df["bb_up"].values, df["bb_dn"].values, df["sma20"].values, df["atr14"].values
    for t in range(1, len(df)):
        if np.isnan(up[t]) or np.isnan(up[t - 1]) or np.isnan(atr[t]):
            continue
        fresh_up = c[t] > up[t] and c[t - 1] <= up[t - 1]
        fresh_dn = c[t] < dn[t] and c[t - 1] >= dn[t - 1]
        if fresh_up:
            entry_ref = c[t]
            sl = h[t] + 0.5 * atr[t]
            tp = mid[t]
            risk = sl - entry_ref
            if risk <= 0 or tp >= entry_ref:
                continue
            out.append({"sig_idx": t, "side": "short", "sl": sl, "tp": tp})
        elif fresh_dn:
            entry_ref = c[t]
            sl = l[t] - 0.5 * atr[t]
            tp = mid[t]
            risk = entry_ref - sl
            if risk <= 0 or tp <= entry_ref:
                continue
            out.append({"sig_idx": t, "side": "long", "sl": sl, "tp": tp})
    return out


def sig_f5_atr_squeeze_breakout(df: pd.DataFrame) -> list[dict]:
    """Vol squeeze (ATR14 <= 0.7*median50) + Donchian20 close breakout. Entry t+1 open, 2R."""
    out = []
    c = df["close"].values
    dhi, dlo, atr, amed = df["don20_hi"].values, df["don20_lo"].values, df["atr14"].values, df["atr_med50"].values
    for t in range(1, len(df)):
        if np.isnan(dhi[t]) or np.isnan(amed[t]) or amed[t] <= 0:
            continue
        squeeze = atr[t] <= 0.7 * amed[t]
        if not squeeze:
            continue
        if c[t] > dhi[t]:
            entry_ref = c[t]
            sl = dlo[t]
            risk = entry_ref - sl
            if risk <= 0:
                continue
            out.append({"sig_idx": t, "side": "long", "sl": sl, "tp": entry_ref + 2 * risk})
        elif c[t] < dlo[t]:
            entry_ref = c[t]
            sl = dhi[t]
            risk = sl - entry_ref
            if risk <= 0:
                continue
            out.append({"sig_idx": t, "side": "short", "sl": sl, "tp": entry_ref - 2 * risk})
    return out


DETECTORS = {
    "F1_london_breakout": sig_f1_london_breakout,
    "F2_ny_fade": sig_f2_ny_fade,
    "F3_ema20_pullback": sig_f3_ema20_pullback,
    "F4_bollinger_fade": sig_f4_bollinger_fade,
    "F5_atr_squeeze_bo": sig_f5_atr_squeeze_breakout,
}


# --------------------------------------------------------------------------- simulator
def simulate(df: pd.DataFrame, signals: list[dict], slippage_bps: float) -> list[dict]:
    """Next-bar OPEN entry; SL-first conservative intrabar; session+weekend+cooldown;
    slippage split entry/exit; swap haircut. SL/TP are RECOMPUTED off the real entry
    price (next-bar open) keeping the original risk distance so R is honest."""
    o = df["open"].values
    h = df["high"].values
    l = df["low"].values
    c = df["close"].values
    ts = df["ts"]
    n = len(df)
    half_slip = (slippage_bps / 2.0) / 1e4  # per side, fraction of price
    out = []
    last_exit_idx = -10 ** 9
    for s in signals:
        t = s["sig_idx"]
        ei = t + 1  # entry bar
        if ei >= n:
            continue
        ets = ts.iloc[ei]
        # session + weekend on ENTRY bar open ts (lookahead-free)
        if not in_session(ets) or is_weekend_block(ets):
            continue
        # cooldown: 6 bars since last trade exit
        if ei - last_exit_idx < COOLDOWN_BARS:
            continue
        side = s["side"]
        entry_px = o[ei]
        # apply entry slippage adverse
        if side == "long":
            entry_fill = entry_px * (1 + half_slip)
        else:
            entry_fill = entry_px * (1 - half_slip)
        # recompute risk/tp distance from the signal reference (sig bar close);
        # entry/SL/TP then re-anchored on the real next-bar OPEN fill (honest R).
        sig_ref = c[t]
        if side == "long":
            risk_dist = sig_ref - s["sl"]
            tp_dist = s["tp"] - sig_ref
        else:
            risk_dist = s["sl"] - sig_ref
            tp_dist = sig_ref - s["tp"]
        if risk_dist <= 0 or tp_dist <= 0:
            continue
        if side == "long":
            sl_px = entry_fill - risk_dist
            tp_px = entry_fill + tp_dist
        else:
            sl_px = entry_fill + risk_dist
            tp_px = entry_fill - tp_dist
        # walk forward bars to find exit
        exit_idx = None
        exit_px = None
        for j in range(ei, n):
            bj_h, bj_l = h[j], l[j]
            # weekend force-close: if bar opens into weekend block AND we still hold, close at open
            if j > ei and is_weekend_block(ts.iloc[j]):
                exit_idx, exit_px = j, o[j]
                break
            if side == "long":
                hit_sl = bj_l <= sl_px
                hit_tp = bj_h >= tp_px
            else:
                hit_sl = bj_h >= sl_px
                hit_tp = bj_l <= tp_px
            if hit_sl and hit_tp:
                exit_idx, exit_px = j, sl_px  # SL-first conservative
                break
            if hit_sl:
                exit_idx, exit_px = j, sl_px
                break
            if hit_tp:
                exit_idx, exit_px = j, tp_px
                break
        if exit_idx is None:
            exit_idx, exit_px = n - 1, c[n - 1]  # close at last bar
        # exit slippage adverse
        if side == "long":
            exit_fill = exit_px * (1 - half_slip)
            gross_R = (exit_fill - entry_fill) / risk_dist
        else:
            exit_fill = exit_px * (1 + half_slip)
            gross_R = (entry_fill - exit_fill) / risk_dist
        # swap haircut
        ets_x = ts.iloc[exit_idx]
        nh = nights_held(ets, ets_x)
        sl_bps = (risk_dist / entry_fill) * 1e4 if entry_fill > 0 else 0.0
        swap_R = (nh * SWAP_BPS_PER_NIGHT) / sl_bps if sl_bps > 0 else 0.0
        net_R = gross_R - swap_R
        out.append({
            "entry_ts": ets, "exit_ts": ets_x, "side": side,
            "R": net_R, "gross_R": gross_R, "swap_R": swap_R, "nights": nh,
        })
        last_exit_idx = exit_idx
    return out


# --------------------------------------------------------------------------- stats
def r_stats(trades: list[dict]) -> dict:
    if not trades:
        return {"n": 0, "mR": 0.0, "gross_mR": 0.0, "sumR": 0.0, "wr": 0.0, "pf": 0.0}
    Rs = [t["R"] for t in trades]
    g = [t["gross_R"] for t in trades]
    wins = [r for r in Rs if r > 0]
    losses = [r for r in Rs if r < 0]
    gl = abs(sum(losses))
    return {
        "n": len(Rs), "mR": mean(Rs), "gross_mR": mean(g), "sumR": sum(Rs),
        "wr": len(wins) / len(Rs) * 100, "pf": (sum(wins) / gl) if gl > 0 else float("inf"),
    }


def shuffle_pvalue(trades: list[dict], n_iter: int = 5000) -> tuple[float, float]:
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


def monthly_R_series(trades: list[dict], idx: pd.DatetimeIndex) -> pd.Series:
    s = pd.Series(0.0, index=idx)
    for t in trades:
        key = pd.Timestamp(t["entry_ts"]).to_period("M").to_timestamp().tz_localize("UTC")
        if key in s.index:
            s[key] += t["R"]
    return s


# --------------------------------------------------------------------------- brooks (for correlation)
def brooks_trades(df_full: pd.DataFrame) -> list[dict]:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.brooks_failed_breakout import _default_manifest, BrooksFailedBreakoutStrategy
    m = _default_manifest()
    m.signals.filters.atr_min_pct = 0.0008
    strat = BrooksFailedBreakoutStrategy(m)

    def prov(*a, **k):
        d = df_full.copy()
        d["symbol"] = SYMBOL
        d["venue"] = "forex"
        d["timeframe"] = TF
        d["volume"] = 0.0
        return d

    e = BacktestEngine(risk_officer=None, store_load=None)
    r = e.run(strat, [SYMBOL], start=df_full["ts"].iloc[0].to_pydatetime(),
              end=df_full["ts"].iloc[-1].to_pydatetime(), timeframe=TF,
              initial_capital=10_000.0, fees={"taker": 0.0, "maker": 0.0},
              slippage_bps=SLIPPAGE_BPS, ohlcv_provider=prov)
    out = []
    if r.trades is None or r.trades.empty:
        return out
    for _, t in r.trades.iterrows():
        ts_e = pd.Timestamp(t["entry_ts"])
        ts_e = ts_e.tz_localize("UTC") if ts_e.tzinfo is None else ts_e.tz_convert("UTC")
        if not in_session(ts_e) or is_weekend_block(ts_e):
            continue
        out.append({"entry_ts": ts_e, "R": float(t["realized_r_multiple"]),
                    "gross_R": float(t["realized_r_multiple"]), "side": str(t["side"]).lower()})
    return out


# --------------------------------------------------------------------------- main
def main() -> None:
    df = add_indicators(load_ohlcv())
    dhash = data_hash(df)
    git_hash = subprocess.run(
        ["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    print("=" * 86)
    print("NEW EDGE FAMILIES quick-screen — EUR/USD 4H honest cost")
    print("=" * 86)
    print(f"git={git_hash}  data_hash={dhash}  seed={SEED}  n_bars={len(df)}")
    print(f"cost: fee=0 slip={SLIPPAGE_BPS}bps swap={SWAP_BPS_PER_NIGHT}bps/night(Wed3x) "
          f"session{SESSION_START_H}-{SESSION_END_H}UTC weekend-flat cooldown{COOLDOWN_BARS}bars")
    print(f"IS=[{IS_START.date()},{IS_END.date()})  OOS=[{OOS_START.date()},{OOS_END.date()})\n")

    is_mask = (df["ts"] >= IS_START) & (df["ts"] < IS_END)
    oos_mask = (df["ts"] >= OOS_START) & (df["ts"] < OOS_END)

    # month index for correlation
    midx = pd.period_range(IS_START, OOS_END, freq="M").to_timestamp().tz_localize("UTC")

    all_full = {}
    print(f"{'family':<20} {'scope':<4} {'n':>4} {'net_mR':>8} {'gross_mR':>9} {'win%':>6} {'PF':>6} {'sumR':>8}")
    print("-" * 86)
    rows = {}
    for name, fn in DETECTORS.items():
        sigs = fn(df)
        full = simulate(df, sigs, SLIPPAGE_BPS)
        all_full[name] = full
        is_tr = [t for t in full if IS_START <= t["entry_ts"] < IS_END]
        oos_tr = [t for t in full if OOS_START <= t["entry_ts"] < OOS_END]
        st_is, st_oos = r_stats(is_tr), r_stats(oos_tr)
        rows[name] = {"is": st_is, "oos": st_oos}
        for scope, st in (("IS", st_is), ("OOS", st_oos)):
            pf = st["pf"]; pfs = f"{pf:.2f}" if math.isfinite(pf) else "inf"
            print(f"{name:<20} {scope:<4} {st['n']:>4} {st['mR']:>+8.3f} {st['gross_mR']:>+9.3f} "
                  f"{st['wr']:>5.1f}% {pfs:>6} {st['sumR']:>+8.1f}")
    print("-" * 86)

    # sanity: net <= gross
    print("\nSANITY (net mR <= gross mR):")
    for name in DETECTORS:
        st = rows[name]["is"]
        ok = st["mR"] <= st["gross_mR"] + 1e-9
        print(f"  {name:<20} net {st['mR']:+.3f} <= gross {st['gross_mR']:+.3f} -> {'OK' if ok else 'BROKEN'}")

    # shuffle + BH-FDR
    print("\nSHUFFLE NULL (5000 iters, full period):")
    shuf = {}
    for name in DETECTORS:
        obs, p = shuffle_pvalue(all_full[name])
        shuf[name] = p
        print(f"  {name:<20} obs_mR={obs:+.3f} p={p:.4f} n={len(all_full[name])}")
    pvals = sorted(shuf.items(), key=lambda x: x[1])
    m = len(pvals)
    print("\nBH-FDR (alpha=0.05) over 5 families:")
    bh = {}
    for i, (k, p) in enumerate(pvals, 1):
        thr = i / m * 0.05
        bh[k] = p <= thr
        print(f"  rank {i}: {k:<20} p={p:.4f} thr={thr:.4f} {'PASS' if bh[k] else 'fail'}")

    # slippage stress
    print("\nSLIPPAGE STRESS (1.0->1.7bps, full net mR):")
    for name, fn in DETECTORS.items():
        sigs = fn(df)
        stress = simulate(df, sigs, SLIPPAGE_BPS_STRESS)
        base = r_stats(all_full[name])
        st = r_stats(stress)
        print(f"  {name:<20} base_mR={base['mR']:+.3f} stress_mR={st['mR']:+.3f} n={st['n']}")

    # correlation vs brooks (monthly R series, full period)
    print("\nCORRELATION vs brooks_failed_breakout (monthly R P&L, full period):")
    bk = brooks_trades(df)
    bk_m = monthly_R_series(bk, midx)
    print(f"  (brooks n={len(bk)} trades, monthly series sumR={bk_m.sum():+.1f})")
    for name in DETECTORS:
        fam_m = monthly_R_series(all_full[name], midx)
        # only months where at least one side traded
        active = (fam_m != 0) | (bk_m != 0)
        if active.sum() < 4 or fam_m[active].std() == 0 or bk_m[active].std() == 0:
            corr = float("nan")
        else:
            corr = float(np.corrcoef(fam_m[active], bk_m[active])[0, 1])
        # also overlap of trade months
        fam_months = {pd.Timestamp(t["entry_ts"]).to_period("M") for t in all_full[name]}
        bk_months = {pd.Timestamp(t["entry_ts"]).to_period("M") for t in bk}
        overlap = len(fam_months & bk_months) / max(1, len(fam_months | bk_months))
        print(f"  {name:<20} monthly_R_corr={corr:+.3f}  month_overlap={overlap*100:.0f}%")

    # verdicts
    print("\n" + "=" * 86)
    print("VERDICT (pre-reg: IS mR<=0 KILL; 0<mR<0.10 ITERATE; mR>=0.10 & OOS>0 & p<0.05 GO)")
    print("=" * 86)
    for name in DETECTORS:
        is_mR = rows[name]["is"]["mR"]; oos_mR = rows[name]["oos"]["mR"]
        n_is = rows[name]["is"]["n"]; p = shuf[name]; bhp = bh[name]
        if n_is < 30 and is_mR > 0:
            v = f"ITERATE (underpowered n_IS={n_is}<30)"
        elif is_mR <= 0:
            v = "KILL (IS net mR<=0)"
        elif is_mR < 0.10:
            v = "ITERATE (IS mR>0 but <+0.10)"
        elif p >= 0.05 or not bhp:
            v = "ITERATE (mR>=0.10 but shuffle/BH fail)"
        elif oos_mR <= 0:
            v = "ITERATE (IS edge but OOS<=0)"
        else:
            v = "GO (IS>=0.10, OOS>0, p<0.05, BH pass)"
        print(f"  {name:<20} IS_mR={is_mR:+.3f} OOS_mR={oos_mR:+.3f} n_IS={n_is} p={p:.3f} "
              f"BH={'Y' if bhp else 'N'} -> {v}")


if __name__ == "__main__":
    main()
