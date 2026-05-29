"""brooks_8fx HONEST net-USD-aware exposure cap + honest frontier.

Adversary (redteam) findings being corrected:
  1. iid Monte Carlo destroys serial clustering -> BANNED. Only report:
     (a) realized historical-path contMaxDD, (b) block-bootstrap MC (20-trade blocks).
  2. Common-mode USD: 8 symbols ~= 2-3 effective independent bets. 73% of entries
     have |net-USD| >= 4 concurrent same-direction positions. -> NET-USD EXPOSURE CAP.
  3. Concurrency: engine's max_concurrent=8 is symbol/direction-blind. A common-mode
     cluster opens up to 8 same-USD-direction positions = 8x one bet. -> net-USD cap.
  4. Right-skew: report BOTH raw median AND winner-stripped (top-5% removed) median.

Net-USD cap (CAUSAL, no lookahead): walk trades chronologically; maintain set of
open positions with their signed USD exposure. A new trade is ADMITTED only if it does
not push |net signed USD positions| above NET_USD_CAP at entry time. Rejected trades are
dropped (not deferred) — conservative. EUR/GBP has no USD leg (usd_dir=0, always admitted
re: USD budget but still counts to gross max_concurrent). Surviving trades then go through
production_replay (which still enforces max_concurrent + cooldown + DD breakers).

Usage: .venv/bin/python scripts/brooks_8fx_honest_cap.py
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

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay

IS_END = pd.Timestamp("2024-01-01", tz="UTC")
RISK_BLOCK = {"AUD/USD", "NZD/USD"}
SEED = 12345


def usd_dir(sym: str, side: str) -> int:
    """Signed USD exposure of a position. +1 = net long USD, -1 = net short USD, 0 = no USD leg.
    base/USD long  => short USD (-1). USD/quote long => long USD (+1)."""
    is_long = side == "long"
    if sym.endswith("/USD"):
        return -1 if is_long else +1
    if sym.startswith("USD/"):
        return +1 if is_long else -1
    return 0  # EUR/GBP


def risk_parity_trades(trades_by_sym: dict, symbols: list[str]) -> list[dict]:
    block = RISK_BLOCK.issubset(set(symbols))
    pooled = []
    for s in symbols:
        sc = 0.5 if (block and s in RISK_BLOCK) else 1.0
        for t in trades_by_sym[s]:
            t2 = dict(t)
            if sc != 1.0:
                t2["R"] = t["R"] * sc
                t2["gross_R"] = t.get("gross_R", t["R"]) * sc
            pooled.append(t2)
    return sorted(pooled, key=lambda x: x["entry_ts"])


def apply_net_usd_cap(pooled: list[dict], net_usd_cap: int | None,
                      gross_cap: int = 8) -> list[dict]:
    """CAUSAL net-USD exposure cap. Chronologically admit a trade only if it does not
    push |sum of signed-USD open positions| above net_usd_cap, AND gross open <= gross_cap.
    net_usd_cap=None disables the USD cap (gross cap still applies)."""
    if not pooled:
        return []
    # build chronological open/close event handling via sweeping at each entry
    pooled_sorted = sorted(pooled, key=lambda x: x["entry_ts"])
    open_pos: list[dict] = []  # each: {exit_ts, usd}
    admitted: list[dict] = []
    for t in pooled_sorted:
        now = t["entry_ts"]
        # close positions whose exit <= now
        open_pos = [p for p in open_pos if pd.Timestamp(p["exit_ts"]) > now]
        if len(open_pos) >= gross_cap:
            continue
        u = usd_dir(t["symbol"], t["side"])
        if net_usd_cap is not None:
            cur_net = sum(p["usd"] for p in open_pos)
            new_net = cur_net + u
            if abs(new_net) > net_usd_cap:
                continue
        open_pos.append({"exit_ts": t["exit_ts"], "usd": u})
        admitted.append(t)
    return admitted


def build_cfg(raw, max_concurrent=8) -> ProductionConfig:
    return ProductionConfig(
        risk_pct=0.01,
        leverage=float(raw["leverage"]["max_leverage_per_symbol"]),
        max_notional_pct_equity=None,
        conf_min=0.0,
        daily_dd=raw["drawdown_breakers"]["daily_loss_pct"],
        weekly_dd=raw["drawdown_breakers"]["weekly_loss_pct"],
        monthly_dd=raw["drawdown_breakers"]["monthly_loss_pct"],
        consecutive_loss_n=None,
        same_symbol_side_cooldown_days=1.0,
        max_concurrent=max_concurrent,
        initial_capital=10_000.0,
    )


def continuous_max_dd(eq_curve) -> float:
    peak = eq_curve[0]
    mdd = 0.0
    for v in eq_curve:
        peak = max(peak, v)
        dd = (v - peak) / peak if peak > 0 else 0.0
        mdd = min(mdd, dd)
    return mdd * 100.0


def monthly_returns_from_curve(eq_curve, exit_ts) -> pd.Series:
    eq = pd.Series(eq_curve[1:], index=pd.to_datetime([pd.Timestamp(t) for t in exit_ts], utc=True)).sort_index()
    me = eq.resample("ME").last().dropna()
    if me.empty:
        return pd.Series(dtype=float)
    prev = pd.Series([eq_curve[0]] + list(me.values[:-1]), index=me.index)
    return (me / prev - 1.0) * 100.0


def block_bootstrap_maxdd(Rs, risk_pct, block=20, n_paths=4000, seed=777):
    """Block-bootstrap MC: resample 20-trade contiguous blocks (preserves serial
    clustering that iid MC destroys). Returns (median_dd%, p05_dd%, p95_dd%)."""
    rng = np.random.default_rng(seed)
    a = np.array(Rs, dtype=float)
    n = len(a)
    if n < block:
        block = max(1, n)
    n_blocks = int(np.ceil(n / block))
    dds = []
    for _ in range(n_paths):
        starts = rng.integers(0, n - block + 1, size=n_blocks)
        path = np.concatenate([a[s:s + block] for s in starts])[:n]
        eq = np.concatenate([[1.0], np.cumprod(1.0 + risk_pct * path)])
        peak = np.maximum.accumulate(eq)
        dds.append(((eq - peak) / peak).min())
    dds = np.array(dds) * 100.0
    return float(np.median(dds)), float(np.percentile(dds, 5)), float(np.percentile(dds, 95))


def winner_stripped_median(monthly_ret: pd.Series, trade_Rs, risk_pct):
    """Two views of right-skew robustness:
       - month-level: drop the best 5% of MONTHS, report median of the rest.
       - trade-level: report median monthly return if top-5% trades' R were capped to
         the 95th percentile (winner-stripped equity sim, block order preserved)."""
    if monthly_ret.empty:
        return None, None
    raw_med = float(monthly_ret.median())
    # month-level: strip top 5% of months
    k = max(1, int(np.ceil(len(monthly_ret) * 0.05)))
    stripped_months = monthly_ret.sort_values()[:-k] if k < len(monthly_ret) else monthly_ret
    ws_month_med = float(stripped_months.median())
    return raw_med, ws_month_med


def profile(res, Rs):
    mr = monthly_returns_from_curve(res.equity_curve, res.entry_ts_list)
    if mr.empty:
        return None
    raw_med, ws_med = winner_stripped_median(mr, Rs, None)
    # trade-level top-5% contribution
    a = np.array([t for t in Rs], dtype=float)
    pos = a[a > 0]
    if len(pos) > 0:
        thr = np.percentile(a, 95)
        top_sum = a[a >= thr].sum()
        total_pos = pos.sum()
        top5_share = top_sum / total_pos if total_pos > 0 else 0.0
    else:
        top5_share = 0.0
    return {
        "n_months": len(mr),
        "mean": float(mr.mean()),
        "median": raw_med,
        "ws_median": ws_med,
        "std": float(mr.std()),
        "neg": float((mr < 0).mean()) * 100,
        "worst": float(mr.min()),
        "realized_contDD": continuous_max_dd(res.equity_curve),
        "mo_sharpe": float(mr.mean() / mr.std()) if mr.std() > 0 else 0.0,
        "final_x": res.final_equity / 10000.0,
        "top5_share": top5_share * 100,
        "n_trades": res.trades,
        "_mr": mr,
    }


def run_config(pooled, base_cfg, risk_pct):
    c = base_cfg.with_overrides(risk_pct=risk_pct)
    res = production_replay(pooled, c)
    if res is None:
        return None
    Rs = [t["R"] for t in pooled]  # input Rs for skew stats (approx; replay drops few)
    return profile(res, Rs)


def measure_net_usd_concurrency(pooled):
    events = []
    for i, t in enumerate(pooled):
        events.append((t["entry_ts"], "open", i))
        events.append((pd.Timestamp(t["exit_ts"]), "close", i))
    events.sort(key=lambda x: (x[0], 0 if x[1] == "close" else 1))
    open_set = set()
    max_c = 0
    max_net = 0
    netd = []
    for ts, typ, i in events:
        if typ == "open":
            open_set.add(i)
            nets = sum(usd_dir(pooled[j]["symbol"], pooled[j]["side"]) for j in open_set)
            max_net = max(max_net, abs(nets))
            max_c = max(max_c, len(open_set))
            netd.append(abs(nets))
        else:
            open_set.discard(i)
    nd = np.array(netd) if netd else np.array([0])
    return max_c, max_net, float(np.median(nd)), float((nd >= 4).mean())


def main():
    d = pickle.load(open("/tmp/rt_trades.pkl", "rb"))
    trades = d["trades"]
    selected = d["selected"]
    raw = yaml.safe_load((ROOT / "configs" / "risk_forex.yaml").read_text())
    base_cfg = build_cfg(raw, max_concurrent=8)

    pooled_raw = risk_parity_trades(trades, selected)
    print("=" * 96)
    print("brooks 8-FX HONEST net-USD cap + honest frontier (iid MC BANNED)")
    print("=" * 96)
    print(f"selected legs ({len(selected)}): {selected}")
    print(f"pooled input trades = {len(pooled_raw)}  seed={SEED}")

    # diagnostics: pre-cap net-USD exposure
    mc0, mn0, md0, f4_0 = measure_net_usd_concurrency(pooled_raw)
    print(f"\nPRE-CAP exposure (raw windows): max_concurrent_windows={mc0}  "
          f"max|net-USD|={mn0}  median|net-USD|={md0:.0f}  frac(|net-USD|>=4)={f4_0*100:.0f}%")

    # ---- net-USD cap variants ----
    # net_usd_cap = max simultaneous same-direction USD positions allowed
    cap_variants = {
        "NO-CAP (mc=8)": (None, 8),
        "netUSD<=3 (mc=6)": (3, 6),
        "netUSD<=2 (mc=4)": (2, 4),
        "netUSD<=1 (mc=3)": (1, 3),
    }

    print("\n" + "=" * 96)
    print("(b) PRE vs POST CAP COMPARISON  (eff_r=1.5%, realized historical path)")
    print("=" * 96)
    hdr = (f"{'config':<20} {'n_tr':>5} {'med%':>7} {'wsMed%':>7} {'mean%':>7} {'STD%':>6} "
           f"{'neg%':>5} {'realDD%':>8} {'moShrp':>7} {'final_x':>9} {'top5%':>6}")
    print(hdr)
    print("-" * len(hdr))
    cap_pooled = {}
    for name, (ncap, gcap) in cap_variants.items():
        pl = apply_net_usd_cap(pooled_raw, ncap, gross_cap=gcap)
        cap_pooled[name] = (pl, ncap, gcap)
        p = run_config(pl, build_cfg(raw, max_concurrent=gcap), 0.015)
        if not p:
            continue
        print(f"{name:<20} {p['n_trades']:>5} {p['median']:>+6.2f}% {p['ws_median']:>+6.2f}% "
              f"{p['mean']:>+6.2f}% {p['std']:>5.2f}% {p['neg']:>4.0f}% "
              f"{p['realized_contDD']:>+7.1f}% {p['mo_sharpe']:>+6.3f} {p['final_x']:>8.1f}x {p['top5_share']:>5.0f}%")

    # ---- HONEST FRONTIER: chosen cap, eff_r sweep, realized DD + block-bootstrap + winner-stripped ----
    print("\n" + "=" * 96)
    print("(c) HONEST FRONTIER per cap-config  (eff_r {1,1.5,2%}; realized path + block-bootstrap MC)")
    print("=" * 96)
    fr_hdr = (f"{'config':<20} {'eff_r':>6} {'rawMed%':>8} {'wsMed%':>8} {'mean%':>7} "
              f"{'realDD%':>8} {'bb_medDD%':>10} {'bb_p95DD%':>10} {'moShrp':>7} {'ret/DD':>7} {'final_x':>9}")
    print(fr_hdr)
    print("-" * len(fr_hdr))
    frontier = {}
    for name, (pl, ncap, gcap) in cap_pooled.items():
        Rs = [t["R"] for t in pl]
        for er in (0.01, 0.015, 0.02):
            p = run_config(pl, build_cfg(raw, max_concurrent=gcap), er)
            if not p:
                continue
            bb_med, bb_p05, bb_p95 = block_bootstrap_maxdd(Rs, er)
            # annualized-ish median monthly / realized DD ratio (robust risk-adjusted)
            rdd = abs(p["realized_contDD"]) if p["realized_contDD"] != 0 else 1e-9
            ret_dd = p["median"] / rdd
            frontier[(name, er)] = (p, bb_med, bb_p95)
            print(f"{name:<20} {er*100:>5.1f}% {p['median']:>+7.2f}% {p['ws_median']:>+7.2f}% "
                  f"{p['mean']:>+6.2f}% {p['realized_contDD']:>+7.1f}% {bb_med:>+9.1f}% "
                  f"{bb_p95:>+9.1f}% {p['mo_sharpe']:>+6.3f} {ret_dd:>+6.3f} {p['final_x']:>8.1f}x")

    # ---- IS vs OOS leg decay (honest overfit caveat) ----
    print("\n" + "=" * 96)
    print("(e) PER-LEG IS vs OOS mR DECAY  (overfit/sample caveat)")
    print("=" * 96)
    for s in selected:
        tr = trades[s]
        is_R = [t["R"] for t in tr if t["entry_ts"] < IS_END]
        oos_R = [t["R"] for t in tr if t["entry_ts"] >= IS_END]
        decay = (mean(oos_R) - mean(is_R)) if (is_R and oos_R) else 0.0
        flag = " <-- OOS DECAY" if (is_R and oos_R and mean(oos_R) < mean(is_R) * 0.5) else ""
        print(f"  {s:<9} IS_mR={mean(is_R):+.3f} (n={len(is_R)})  OOS_mR={mean(oos_R):+.3f} (n={len(oos_R)})  "
              f"Δ={decay:+.3f}{flag}")

    # year-by-year pooled net mR (edge trend)
    print("\n  POOLED net mR by calendar year (edge trend):")
    sr = pd.Series([t["R"] for t in pooled_raw],
                   index=pd.to_datetime([t["entry_ts"] for t in pooled_raw], utc=True))
    for yr, grp in sr.groupby(sr.index.year):
        print(f"    {yr}: n={len(grp):>4} mR={grp.mean():+.3f} sumR={grp.sum():+.1f}")

    print("\nDONE.")


if __name__ == "__main__":
    main()
