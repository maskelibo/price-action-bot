"""HYP-2026-05-29-mtf-entry-refinement — MTF (4H signal -> sub-TF entry) test.

Pre-reg: memory/researcher/hypotheses/2026-05-29-mtf-entry-refinement.md

4H brooks_failed_breakout signal gives DIRECTION + structure (entry_ts, entry_price,
initial_sl) -- read VERBATIM from the baseline pkl (/tmp/rt_trades.pkl). We then RE-TIME
the entry on a sub-TF (1h/30m/15m) using ONLY sub-TF bars with open_ts >= entry_ts
(lookahead-free: 4H signal is known at entry_ts = signal-bar t close = t+4h).

Exit model: the engine's EXACT multi-target runner-trail (TP1=1R/30%, TP2=1.5R/30%,
runner 40% peak-1.5*ATR trail, BE after TP1, lock +1R after TP2) re-implemented on the
sub-TF bar path. Applied IDENTICALLY to:
  - BASELINE-RESIM: entry = first sub-TF bar open at/after entry_ts (== 4H open within
    rounding). Stop = original 4H initial_sl. -> isolates EXIT-model effect = ~0, anchors fairness.
  - V1 PULLBACK: wait for a dir-favourable retrace to {0.382,0.5} of signal-bar range
    within N sub-TF bars; enter at that level (limit fill). Stop = original 4H sl. R-dist
    SAME (stop unchanged) but BETTER entry -> R lifts mechanically IF target still reached.
  - V1n PULLBACK+NARROW: pullback entry, stop tightened to signal-bar extreme (narrower).
  - V2 CONFIRM: wait for sub-TF momentum confirm (close beyond signal-bar mid in dir)
    within N bars; enter next sub-TF open. Stop = 4H sl. False-signal filter.
  - V3 NARROW: entry == baseline (first sub-TF open) but stop = signal-bar extreme (narrow).

SKIP if window has no trigger (main report) + a 4H-MARKET-FALLBACK variant reported too.

Intrabar SL/TP conflict -> SL FIRST (conservative loss). Slippage 1.0bps on entry+exit.
ATR for runner-trail = 4H ATR14 at signal time (causal, known at entry_ts).

Reproducibility: git e7d0a90, data_hash 90bb22160ab3692c, seed 12345.
Usage: .venv/bin/python scripts/mtf_entry_refinement.py
"""
from __future__ import annotations

import os
import pickle
import sys
from pathlib import Path
from statistics import mean, median, pstdev

os.environ["PA_LOG_QUIET"] = "1"
import warnings

warnings.filterwarnings("ignore")

import duckdb
import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay

DB = ROOT / "data" / "forex_market.duckdb"
CORE = ["EUR/USD", "GBP/USD", "USD/JPY"]
IS_END = pd.Timestamp("2024-01-01", tz="UTC")
OOS_END = pd.Timestamp("2026-01-01", tz="UTC")
SEED = 12345
SLIP = 1.0 / 1e4  # 1.0 bps each side
SUBTF_MIN = {"1h": 60, "30m": 30, "15m": 15}
H4 = pd.Timedelta(hours=4)

# Engine exit-model params (verbatim from engine.py defaults)
TP1_R, TP2_R = 1.0, 1.5
TP1_PCT, TP2_PCT = 0.30, 0.30
TRAIL_MULT = 1.5
TRAIL_ACTIVATE_STAGE = 2  # runner trail engages after TP2

_rng = np.random.default_rng(SEED)


# ---------------------------------------------------------------------------
def load_tf(sym: str, tf: str) -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute(
        "SELECT ts,open,high,low,close FROM ohlcv WHERE symbol=? AND timeframe=? ORDER BY ts",
        [sym, tf],
    ).fetchdf()
    con.close()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.sort_values("ts").reset_index(drop=True)


def atr14(df4: pd.DataFrame) -> pd.Series:
    h, l, c = df4["high"], df4["low"], df4["close"]
    pc = c.shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.rolling(14).mean()


def simulate_exit(sub: pd.DataFrame, j0: int, side: str, entry_price: float,
                  sl_price: float, atr_for_trail: float) -> tuple[float, pd.Timestamp]:
    """Engine multi-target runner-trail exit on sub-TF bars starting AT bar j0 (entry bar).
    Returns (net_R, exit_ts). SL-first on intrabar conflict (conservative)."""
    R_dist = abs(entry_price - sl_price)
    if R_dist <= 0:
        return 0.0, sub.iloc[j0]["ts"]
    if atr_for_trail <= 0:
        atr_for_trail = R_dist * 0.5
    tp1 = entry_price + TP1_R * R_dist if side == "long" else entry_price - TP1_R * R_dist
    tp2 = entry_price + TP2_R * R_dist if side == "long" else entry_price - TP2_R * R_dist
    q1, q2, qr = TP1_PCT, TP2_PCT, 1.0 - TP1_PCT - TP2_PCT
    stage = 0
    cur_sl = sl_price
    peak = entry_price
    realized = 0.0  # accumulated R-weighted pnl in units of R_dist
    closed_q = 0.0
    n = len(sub)
    last_close = entry_price
    for j in range(j0, n):
        bar = sub.iloc[j]
        hi, lo, cl = float(bar["high"]), float(bar["low"]), float(bar["close"])
        last_close = cl
        if side == "long":
            peak = max(peak, hi)
            # SL FIRST (conservative)
            if lo <= cur_sl:
                rem = 1.0 - closed_q
                fill = cur_sl * (1 - SLIP)
                realized += (fill - entry_price) / R_dist * rem
                return realized, bar["ts"]
            if stage == 0 and hi >= tp1:
                fill = tp1 * (1 - SLIP)
                realized += (fill - entry_price) / R_dist * q1
                closed_q += q1
                stage = 1
                cur_sl = max(cur_sl, entry_price)  # BE
            if stage >= 1 and hi >= tp2:
                fill = tp2 * (1 - SLIP)
                realized += (fill - entry_price) / R_dist * q2
                closed_q += q2
                stage = 2
            if stage >= TRAIL_ACTIVATE_STAGE:
                trail_sl = peak - TRAIL_MULT * atr_for_trail
                cur_sl = max(cur_sl, tp1, trail_sl)
        else:
            peak = min(peak, lo)
            if hi >= cur_sl:
                rem = 1.0 - closed_q
                fill = cur_sl * (1 + SLIP)
                realized += (entry_price - fill) / R_dist * rem
                return realized, bar["ts"]
            if stage == 0 and lo <= tp1:
                fill = tp1 * (1 + SLIP)
                realized += (entry_price - fill) / R_dist * q1
                closed_q += q1
                stage = 1
                cur_sl = min(cur_sl, entry_price)
            if stage >= 1 and lo <= tp2:
                fill = tp2 * (1 + SLIP)
                realized += (entry_price - fill) / R_dist * q2
                closed_q += q2
                stage = 2
            if stage >= TRAIL_ACTIVATE_STAGE:
                trail_sl = peak + TRAIL_MULT * atr_for_trail  # peak=running low; trail above
                cur_sl = min(cur_sl, tp1, trail_sl)
    # ran off end: close runner at last close
    rem = 1.0 - closed_q
    if side == "long":
        realized += (last_close - entry_price) / R_dist * rem
    else:
        realized += (entry_price - last_close) / R_dist * rem
    return realized, sub.iloc[n - 1]["ts"]


def first_idx_at_or_after(sub: pd.DataFrame, ts: pd.Timestamp) -> int | None:
    arr = sub["ts"].values
    pos = np.searchsorted(arr, np.datetime64(ts))
    return int(pos) if pos < len(sub) else None


def refine_trade(t: dict, sub: pd.DataFrame, df4: pd.DataFrame, atr_map: dict,
                 variant: str, depth: float, N: int, fallback: bool) -> dict | None:
    """Return refined trade dict (entry_ts, exit_ts, R, side, symbol) or None (skip).
    LOOKAHEAD: only sub bars with open_ts >= entry_ts (== signal known time)."""
    entry_ts = pd.Timestamp(t["entry_ts"])
    side = t["side"]
    h4_entry_px = float(t["entry_price"])  # 4H bar open (with slip already in pkl)
    h4_sl = float(t["initial_sl"])
    sym = t["symbol"]
    # signal bar = the 4H bar that CLOSED at entry_ts (open at entry_ts - 4h)
    sig_open_ts = entry_ts - H4
    srow = df4[df4["ts"] == sig_open_ts]
    if srow.empty:
        return None
    sig_hi = float(srow["high"].iloc[0])
    sig_lo = float(srow["low"].iloc[0])
    sig_rng = sig_hi - sig_lo
    atr_t = atr_map.get(sig_open_ts, sig_rng * 0.5)
    if not np.isfinite(atr_t) or atr_t <= 0:
        atr_t = sig_rng * 0.5

    j_start = first_idx_at_or_after(sub, entry_ts)
    if j_start is None or j_start >= len(sub):
        return None
    win_end = min(j_start + N, len(sub))

    new_entry_px = None
    new_sl = h4_sl
    entry_j = None

    if variant == "baseline":
        # enter at first sub-TF bar open at/after entry_ts; stop = 4H sl
        entry_j = j_start
        op = float(sub.iloc[entry_j]["open"])
        new_entry_px = op * (1 + SLIP) if side == "long" else op * (1 - SLIP)
        new_sl = h4_sl

    elif variant in ("v1_pullback", "v1n_pullback_narrow"):
        # dir-favourable retrace to `depth` of signal-bar range, limit fill within window
        if side == "long":
            target_lvl = sig_hi - depth * sig_rng
        else:
            target_lvl = sig_lo + depth * sig_rng
        for j in range(j_start, win_end):
            lo = float(sub.iloc[j]["low"]); hi = float(sub.iloc[j]["high"])
            touched = (side == "long" and lo <= target_lvl) or (side == "short" and hi >= target_lvl)
            if touched:
                entry_j = j
                # limit fill at target_lvl (better price); slip adverse
                new_entry_px = target_lvl * (1 + SLIP) if side == "long" else target_lvl * (1 - SLIP)
                break
        if entry_j is None:
            if not fallback:
                return None
            entry_j = j_start
            op = float(sub.iloc[entry_j]["open"])
            new_entry_px = op * (1 + SLIP) if side == "long" else op * (1 - SLIP)
        if variant == "v1n_pullback_narrow":
            # stop at signal-bar extreme (narrower than 4H sl if 4H sl was wider)
            new_sl = sig_lo if side == "long" else sig_hi
        else:
            new_sl = h4_sl

    elif variant == "v2_confirm":
        # wait for sub-TF momentum confirm: a bar that CLOSES beyond signal-bar mid in dir
        sig_mid = (sig_hi + sig_lo) / 2.0
        conf_j = None
        for j in range(j_start, win_end):
            cl = float(sub.iloc[j]["close"])
            ok = (side == "long" and cl > sig_mid) or (side == "short" and cl < sig_mid)
            if ok:
                conf_j = j
                break
        if conf_j is None:
            if not fallback:
                return None
            entry_j = j_start
        else:
            entry_j = conf_j + 1  # enter NEXT sub-TF bar open after confirm close
            if entry_j >= len(sub):
                return None
        op = float(sub.iloc[entry_j]["open"])
        new_entry_px = op * (1 + SLIP) if side == "long" else op * (1 - SLIP)
        new_sl = h4_sl

    elif variant == "v3_narrow":
        # entry == baseline first sub open, stop = signal-bar extreme (narrow)
        entry_j = j_start
        op = float(sub.iloc[entry_j]["open"])
        new_entry_px = op * (1 + SLIP) if side == "long" else op * (1 - SLIP)
        new_sl = sig_lo if side == "long" else sig_hi

    else:
        return None

    # sanity: stop must be on correct side of entry
    if side == "long" and new_sl >= new_entry_px:
        return None
    if side == "short" and new_sl <= new_entry_px:
        return None

    R, exit_ts = simulate_exit(sub, entry_j, side, new_entry_px, new_sl, atr_t)
    # swap haircut (reuse original proportion: nights * 0.3bps / sl_bps)
    sl_pct = abs(new_entry_px - new_sl) / new_entry_px
    sl_bps = sl_pct * 1e4
    nights = int(t.get("nights", 0))
    swap_R = (nights * 0.3) / sl_bps if sl_bps > 0 else 0.0
    R_net = R - swap_R
    return {
        "entry_ts": pd.Timestamp(sub.iloc[entry_j]["ts"]),
        "exit_ts": pd.Timestamp(exit_ts),
        "entry_price": new_entry_px,
        "initial_sl": new_sl,
        "R": R_net,
        "gross_R": R,
        "side": side,
        "symbol": sym,
        "conf": t.get("conf", 0.33),
        "strategy": "brooks_mtf",
    }


# ---------------------------------------------------------------------------
def build_cfg(raw, mc=8) -> ProductionConfig:
    return ProductionConfig(
        risk_pct=0.01,
        leverage=float(raw["leverage"]["max_leverage_per_symbol"]),
        max_notional_pct_equity=None, conf_min=0.0,
        daily_dd=raw["drawdown_breakers"]["daily_loss_pct"],
        weekly_dd=raw["drawdown_breakers"]["weekly_loss_pct"],
        monthly_dd=raw["drawdown_breakers"]["monthly_loss_pct"],
        consecutive_loss_n=None, same_symbol_side_cooldown_days=1.0,
        max_concurrent=mc, initial_capital=10_000.0,
    )


def cont_dd(eq):
    peak = eq[0]; mdd = 0.0
    for v in eq:
        peak = max(peak, v); mdd = min(mdd, (v - peak) / peak if peak > 0 else 0.0)
    return mdd * 100.0


def monthly_ret(eq, ex_ts):
    s = pd.Series(eq[1:], index=pd.to_datetime([pd.Timestamp(t) for t in ex_ts], utc=True)).sort_index()
    me = s.resample("ME").last().dropna()
    if me.empty:
        return pd.Series(dtype=float)
    prev = pd.Series([eq[0]] + list(me.values[:-1]), index=me.index)
    return (me / prev - 1.0) * 100.0


def robust_median(mr):
    if mr.empty:
        return None
    k = max(1, int(np.ceil(len(mr) * 0.05)))
    return float(mr.sort_values()[:-k].median()) if k < len(mr) else float(mr.median())


def r_stats(trs):
    Rs = [t["R"] for t in trs]
    if not Rs:
        return dict(n=0, mR=0.0, wr=0.0, pf=0.0, top5=0.0)
    a = np.array(Rs)
    wins = a[a > 0]; losses = a[a < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    thr = np.percentile(a, 95)
    top5 = a[a >= thr].sum() / wins.sum() * 100 if wins.sum() > 0 else 0.0
    return dict(n=len(Rs), mR=float(a.mean()), wr=len(wins) / len(a) * 100, pf=pf, top5=top5)


def portfolio_profile(pooled, base_cfg, eff_r):
    if not pooled:
        return None
    c = base_cfg.with_overrides(risk_pct=eff_r)
    res = production_replay(sorted(pooled, key=lambda x: x["entry_ts"]), c)
    if res is None:
        return None
    mr = monthly_ret(res.equity_curve, res.entry_ts_list)
    if mr.empty:
        return None
    return dict(
        n_tr=res.trades, robmed=robust_median(mr), med=float(mr.median()),
        mean=float(mr.mean()), std=float(mr.std()),
        sharpe=float(mr.mean() / mr.std()) if mr.std() > 0 else 0.0,
        dd=cont_dd(res.equity_curve), final=res.final_equity / 10000.0,
    )


def shuffle_p(trs, n_iter=4000):
    Rs = np.array([t["R"] for t in trs], dtype=float)
    if len(Rs) == 0:
        return 1.0
    obs = Rs.mean(); absR = np.abs(Rs); cnt = 0
    for _ in range(n_iter):
        if (absR * _rng.choice([-1.0, 1.0], size=len(Rs))).mean() >= obs:
            cnt += 1
    return (cnt + 1) / (n_iter + 1)


# ---------------------------------------------------------------------------
def main():
    d = pickle.load(open("/tmp/rt_trades.pkl", "rb"))
    base_trades = {s: [t for t in d["trades"][s]] for s in CORE}
    raw = yaml.safe_load((ROOT / "configs" / "risk_forex.yaml").read_text())
    base_cfg = build_cfg(raw)

    print("=" * 110)
    print("MTF ENTRY REFINEMENT — 4H brooks signal -> sub-TF entry  (HYP-2026-05-29-mtf-entry-refinement)")
    print("=" * 110)
    print("git=e7d0a90 data_hash=90bb22160ab3692c seed=12345  cost: slip 1.0bps/side fee=0 swap haircut")
    print("IS=[2020,2024) OOS=[2024,2026)  core 3sym  intrabar conflict=SL-first  exit=engine multi-target trail")
    n_base = sum(len(base_trades[s]) for s in CORE)
    print(f"baseline 4H trades (3 core): {n_base}  (EUR={len(base_trades['EUR/USD'])} GBP={len(base_trades['GBP/USD'])} JPY={len(base_trades['USD/JPY'])})")

    # preload sub-TF + 4H + ATR per symbol
    sub_data = {}
    df4_data = {}
    atr_data = {}
    for s in CORE:
        df4 = load_tf(s, "4h")
        df4_data[s] = df4
        a = atr14(df4)
        atr_data[s] = {pd.Timestamp(ts): float(v) for ts, v in zip(df4["ts"], a)}
        for tf in SUBTF_MIN:
            sub_data[(s, tf)] = load_tf(s, tf)

    # variant grid (pre-reg). depth only used by v1*
    VARIANTS = [
        ("baseline", None, None),
        ("v1_pullback", 0.382, None),
        ("v1_pullback", 0.5, None),
        ("v1n_pullback_narrow", 0.5, None),
        ("v2_confirm", None, None),
        ("v3_narrow", None, None),
    ]
    TFS = ["1h", "30m", "15m"]
    NWINDOW = {"1h": 8, "30m": 16, "15m": 32}  # ~ same wall-clock window (~8h..) ; pre-reg N

    # First: build baseline-resim per TF (sanity: should ~match across TFs, entry≈4H open)
    def build_variant(variant, depth, tf, fallback):
        N = NWINDOW[tf]
        pooled = []
        skips = {s: 0 for s in CORE}
        for s in CORE:
            sub = sub_data[(s, tf)]
            df4 = df4_data[s]
            am = atr_data[s]
            for t in base_trades[s]:
                rt = refine_trade(t, sub, df4, am, variant, depth, N, fallback)
                if rt is None:
                    skips[s] += 1
                else:
                    pooled.append(rt)
        return pooled, skips

    # ---- engine-R baseline reference (original pkl R, multi-target on 4H) ----
    orig_pooled = []
    for s in CORE:
        orig_pooled.extend(dict(t) for t in base_trades[s])
    orig_R = [t["R"] for t in orig_pooled]
    is_orig = [t for t in orig_pooled if pd.Timestamp(t["entry_ts"]) < IS_END]
    oos_orig = [t for t in orig_pooled if pd.Timestamp(t["entry_ts"]) >= IS_END]
    print("\n" + "-" * 110)
    print("REFERENCE — original engine-R 4H baseline (multi-target trail on 4H bars, from pkl):")
    so = r_stats(orig_pooled); si = r_stats(is_orig); ss = r_stats(oos_orig)
    pe = portfolio_profile(orig_pooled, base_cfg, 0.015)
    print(f"  FULL n={so['n']} mR={so['mR']:+.3f} wr={so['wr']:.1f}% pf={so['pf']:.2f} top5={so['top5']:.0f}%"
          f"  | IS mR={si['mR']:+.3f}(n{si['n']}) OOS mR={ss['mR']:+.3f}(n{ss['n']})")
    if pe:
        print(f"  portfolio@1.5%: robMed={pe['robmed']:+.2f}% med={pe['med']:+.2f}% mean={pe['mean']:+.2f}% "
              f"Sharpe={pe['sharpe']:+.3f} realDD={pe['dd']:+.1f}% final={pe['final']:.1f}x")

    # ---- run full grid: collect per (variant,depth,tf,fallback) ----
    print("\n" + "=" * 110)
    print("(b) VARIANT GRID — net mean R, win%, robust-median, Sharpe, DD  (SKIP-mode; fallback shown separately)")
    print("=" * 110)
    hdr = (f"{'variant':<22} {'tf':>4} {'N':>3} {'n':>5} {'skip%':>6} {'IS_mR':>8} {'OOS_mR':>8} "
           f"{'OOS_wr':>7} {'OOS_pf':>7} {'OOS_top5':>8} {'robMed%':>8} {'Sharpe':>7} {'DD%':>7} {'sh_p':>6}")
    print(hdr); print("-" * len(hdr))

    results = {}
    for variant, depth, _ in VARIANTS:
        for tf in TFS:
            # baseline only needs one TF-independent run but TF affects entry granularity; run all
            pooled, skips = build_variant(variant, depth, tf, fallback=False)
            n_total = n_base
            n_skip = sum(skips.values())
            is_tr = [t for t in pooled if pd.Timestamp(t["entry_ts"]) < IS_END]
            oos_tr = [t for t in pooled if pd.Timestamp(t["entry_ts"]) >= IS_END]
            si = r_stats(is_tr); so = r_stats(oos_tr)
            prof = portfolio_profile(pooled, base_cfg, 0.015)
            sp = shuffle_p(oos_tr) if oos_tr else 1.0
            key = (variant, depth, tf)
            results[key] = dict(pooled=pooled, is_mR=si["mR"], oos_mR=so["mR"],
                                oos_wr=so["wr"], oos_pf=so["pf"], oos_top5=so["top5"],
                                prof=prof, sp=sp, n=len(pooled), skip=n_skip / n_total * 100)
            dlbl = f"{depth}" if depth else "-"
            name = f"{variant}[{dlbl}]"
            rob = prof["robmed"] if prof else float("nan")
            shp = prof["sharpe"] if prof else float("nan")
            dd = prof["dd"] if prof else float("nan")
            print(f"{name:<22} {tf:>4} {NWINDOW[tf]:>3} {len(pooled):>5} {n_skip/n_total*100:>5.0f}% "
                  f"{si['mR']:>+8.3f} {so['mR']:>+8.3f} {so['wr']:>6.1f}% {so['pf']:>7.2f} {so['top5']:>7.0f}% "
                  f"{rob:>+7.2f}% {shp:>+6.3f} {dd:>+6.1f}% {sp:>6.3f}")

    # ---- baseline-resim reference (entry=first sub open, 4H stop) for fair Δ ----
    print("\n" + "=" * 110)
    print("(c) NARROW-STOP TRADE-OFF + fair Δ vs BASELINE-RESIM (same exit model, entry=4H-equiv)")
    print("=" * 110)
    # use 1h baseline-resim as the fair anchor (finest causal granularity that always has data)
    base_anchor = {tf: results[("baseline", None, tf)] for tf in TFS}
    print("baseline-resim (sub-TF re-sim of 4H-open entry; isolates entry effect):")
    for tf in TFS:
        b = base_anchor[tf]
        bp = b["prof"]
        print(f"  [{tf}] n={b['n']} IS_mR={b['is_mR']:+.3f} OOS_mR={b['oos_mR']:+.3f} "
              f"OOS_wr={b['oos_wr']:.1f}% robMed={bp['robmed']:+.2f}% Sharpe={bp['sharpe']:+.3f} top5={b['oos_top5']:.0f}%")

    print("\nΔ vs baseline-resim (same TF):  R↑ from entry/stop ; whipsaw shows as wr↓ ; net = OOS_mR Δ")
    dh = (f"{'variant':<22} {'tf':>4} {'ΔIS_mR':>8} {'ΔOOS_mR':>9} {'ΔOOS_wr':>9} {'ΔrobMed':>9} "
          f"{'ΔSharpe':>9} {'Δtop5':>8} {'net?':>6}")
    print(dh); print("-" * len(dh))
    for variant, depth, _ in VARIANTS:
        if variant == "baseline":
            continue
        for tf in TFS:
            r = results[(variant, depth, tf)]; b = base_anchor[tf]
            if not r["prof"] or not b["prof"]:
                continue
            d_is = r["is_mR"] - b["is_mR"]
            d_oos = r["oos_mR"] - b["oos_mR"]
            d_wr = r["oos_wr"] - b["oos_wr"]
            d_rob = r["prof"]["robmed"] - b["prof"]["robmed"]
            d_sh = r["prof"]["sharpe"] - b["prof"]["sharpe"]
            d_t5 = r["oos_top5"] - b["oos_top5"]
            net = "WIN" if (d_oos > 0 and d_rob > 0) else ("part" if d_oos > 0 or d_rob > 0 else "lose")
            dlbl = f"{depth}" if depth else "-"
            print(f"{variant+'['+dlbl+']':<22} {tf:>4} {d_is:>+8.3f} {d_oos:>+9.3f} {d_wr:>+8.1f}% "
                  f"{d_rob:>+8.2f}% {d_sh:>+8.3f} {d_t5:>+7.0f}% {net:>6}")

    # ---- IS->OOS decay check on best candidates (overfit gate) ----
    print("\n" + "=" * 110)
    print("(d) IS->OOS DECAY (overfit gate; entry-optimization prime overfit zone)")
    print("=" * 110)
    print(f"{'variant':<22} {'tf':>4} {'IS_mR':>8} {'OOS_mR':>8} {'decay%':>8} {'flag':>14}")
    for variant, depth, _ in VARIANTS:
        for tf in TFS:
            r = results[(variant, depth, tf)]
            if r["is_mR"] == 0:
                continue
            decay = (r["oos_mR"] - r["is_mR"]) / abs(r["is_mR"]) * 100
            flag = "OOS COLLAPSE" if r["oos_mR"] < r["is_mR"] * 0.5 else ("ok" if r["oos_mR"] > 0 else "OOS NEG")
            dlbl = f"{depth}" if depth else "-"
            print(f"{variant+'['+dlbl+']':<22} {tf:>4} {r['is_mR']:>+8.3f} {r['oos_mR']:>+8.3f} {decay:>+7.0f}% {flag:>14}")

    print("\nDONE. Verdict in researcher report (not auto-promoted).")


if __name__ == "__main__":
    main()
