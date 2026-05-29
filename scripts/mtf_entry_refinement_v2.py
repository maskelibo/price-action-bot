"""HYP-2026-05-29-mtf-entry-refinement v2 — ENGINE-FAITHFUL re-injection.

v1 LESSON (Feynman: don't fool yourself): re-implementing the engine's multi-target
runner-trail by hand DID NOT reproduce engine-R (right-tail winners 7.3R -> -4.9R). The
hand exit model is unfaithful => any comparison built on it is invalid. RED on v1 method.

v2 fix: feed REFINED entries back through the REAL BacktestEngine on sub-TF bars via a
signal-injection strategy. Same engine = same exit logic = exit fidelity guaranteed.
We re-run the 4H brooks signals to capture each signal's ts / sl / atr14 / direction
(verbatim from the strategy), then:
  - re-emit each signal on the 4H df -> ROUND-TRIP check (must reproduce engine-R baseline).
  - re-emit on sub-TF df at a refined entry bar (lookahead-free) with refined SL.

Lookahead: refined entry sub-TF bar open_ts must be >= original 4H entry_ts (= signal
known time). We set sig.ts = (refined_entry_bar - 1) so engine enters AT refined_entry_bar.

Reproducibility: git e7d0a90, data_hash 90bb22160ab3692c, seed 12345.
Usage: .venv/bin/python scripts/mtf_entry_refinement_v2.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from statistics import mean, pstdev

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

import scripts.forex_4h_research as fx
from price_action.backtest.engine import BacktestEngine
from price_action.backtest.lab import ProductionConfig, production_replay
from price_action.contracts import Signal
from price_action.strategies.base import Strategy, StrategyManifest

DB = ROOT / "data" / "forex_market.duckdb"
CORE = ["EUR/USD", "GBP/USD", "USD/JPY"]
IS_END = pd.Timestamp("2024-01-01", tz="UTC")
SEED = 12345
SLIP_BPS = 1.0
H4 = pd.Timedelta(hours=4)
SUBTF_MIN = {"1h": 60, "30m": 30, "15m": 15}
_rng = np.random.default_rng(SEED)


# ---------------------------------------------------------------------------
class ReplayStrategy(Strategy):
    """Emits a fixed, pre-built list of Signals; identity feature-prep. The engine's
    _simulate_symbol then enters next-bar and applies its EXACT multi-target exit."""

    def __init__(self, signals: list[Signal], name: str = "brooks_replay"):
        man = StrategyManifest(name=name, version="mtf", venue="forex",
                               timeframe="x", signals={}, risk={})
        super().__init__(man)
        self._signals = signals
        self.name = name

    def prepare_features(self, df: pd.DataFrame) -> pd.DataFrame:
        return df

    def generate_signals(self, df: pd.DataFrame) -> list[Signal]:
        return self._signals


def load_tf(sym: str, tf: str) -> pd.DataFrame:
    con = duckdb.connect(str(DB), read_only=True)
    df = con.execute(
        "SELECT ts,open,high,low,close,volume FROM ohlcv WHERE symbol=? AND timeframe=? ORDER BY ts",
        [sym, tf],
    ).fetchdf()
    con.close()
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.sort_values("ts").reset_index(drop=True)
    df["symbol"] = sym
    df["venue"] = "forex"
    df["timeframe"] = tf
    return df


def capture_signals(sym: str) -> tuple[list[Signal], pd.DataFrame]:
    """Run the real brooks strategy to get its signals (ts, dir, sl, atr14, tp)."""
    fx.SYMBOL = sym
    fx.TF = "4h"
    df = load_tf(sym, "4h")
    strat = fx.build_strategy("brooks_failed_breakout", "BrooksFailedBreakoutStrategy")
    dfp = strat.prepare_features(df.copy())
    sigs = strat.generate_signals(dfp)
    return sigs, dfp


def run_engine(signals: list[Signal], df: pd.DataFrame, sym: str, tf: str) -> list[dict]:
    def prov(*a, **k):
        return df.copy()
    e = BacktestEngine(risk_officer=None, store_load=None)
    r = e.run(ReplayStrategy(signals), [sym],
              start=df["ts"].iloc[0].to_pydatetime(), end=df["ts"].iloc[-1].to_pydatetime(),
              timeframe=tf, initial_capital=10_000.0, fees=fx.FEES,
              slippage_bps=SLIP_BPS, ohlcv_provider=prov)
    out = []
    if r.trades is None or r.trades.empty:
        return out
    for _, t in r.trades.iterrows():
        ts_e = pd.Timestamp(t["entry_ts"]); ts_e = ts_e.tz_localize("UTC") if ts_e.tzinfo is None else ts_e.tz_convert("UTC")
        ts_x = pd.Timestamp(t["exit_ts"]); ts_x = ts_x.tz_localize("UTC") if ts_x.tzinfo is None else ts_x.tz_convert("UTC")
        if not fx.in_session(ts_e) or fx.is_weekend_block(ts_e):
            continue
        R = float(t["realized_r_multiple"])
        ep = float(t["entry_price"]); sl = float(t["initial_sl"])
        sl_pct = abs(ep - sl) / ep if ep > 0 else 0.0
        sl_bps = sl_pct * 1e4
        nh = fx.nights_held(ts_e, ts_x)
        swap_R = (nh * fx.SWAP_BPS_PER_NIGHT) / sl_bps if sl_bps > 0 else 0.0
        out.append({"entry_ts": ts_e, "exit_ts": ts_x, "entry_price": ep, "initial_sl": sl,
                    "R": R - swap_R, "gross_R": R, "side": str(t["side"]).lower(), "symbol": sym,
                    "conf": 0.333, "strategy": "brooks_replay"})
    return sorted(out, key=lambda x: x["entry_ts"])


def refined_signals(sigs_4h: list[Signal], df4: pd.DataFrame, sub: pd.DataFrame,
                    sym: str, tf: str, variant: str, depth, N: int, fallback: bool):
    """Build sub-TF signals from 4H signals. Returns (signals, n_skip).
    Engine enters at bar AFTER sig.ts. To enter at sub bar k, set sig.ts = sub[k-1].ts."""
    sub_ts = sub["ts"].values
    df4_idx = {pd.Timestamp(ts): i for i, ts in enumerate(df4["ts"])}
    out: list[Signal] = []
    n_skip = 0
    for sg in sigs_4h:
        s_ts = pd.Timestamp(sg.ts).tz_convert("UTC") if pd.Timestamp(sg.ts).tzinfo else pd.Timestamp(sg.ts).tz_localize("UTC")
        # original 4H entry = bar after signal bar
        i4 = df4_idx.get(s_ts)
        if i4 is None or i4 + 1 >= len(df4):
            continue
        entry_ts_4h = pd.Timestamp(df4["ts"].iloc[i4 + 1])
        # session/weekend filter on 4H entry bar (match baseline universe)
        if not fx.in_session(entry_ts_4h) or fx.is_weekend_block(entry_ts_4h):
            continue
        side = sg.direction
        sig_hi = float(df4["high"].iloc[i4]); sig_lo = float(df4["low"].iloc[i4])
        sig_rng = sig_hi - sig_lo
        atr14 = float(sg.metadata.get("atr14", 0.0)) if sg.metadata else 0.0
        sl_4h = float(sg.sl_price)
        # window of sub bars: first sub bar open >= entry_ts_4h
        k0 = int(np.searchsorted(sub_ts, np.datetime64(entry_ts_4h)))
        if k0 <= 0 or k0 >= len(sub):  # need k0-1 >= 0 for sig.ts
            continue
        k_end = min(k0 + N, len(sub))
        entry_k = None
        new_sl = sl_4h

        if variant == "baseline":
            entry_k = k0
            new_sl = sl_4h
        elif variant in ("v1_pullback", "v1n_pullback_narrow"):
            tgt = (sig_hi - depth * sig_rng) if side == "long" else (sig_lo + depth * sig_rng)
            for k in range(k0, k_end):
                lo = float(sub["low"].iloc[k]); hi = float(sub["high"].iloc[k])
                if (side == "long" and lo <= tgt) or (side == "short" and hi >= tgt):
                    entry_k = k
                    break
            if entry_k is None:
                if not fallback:
                    n_skip += 1; continue
                entry_k = k0
            if variant == "v1n_pullback_narrow":
                new_sl = sig_lo if side == "long" else sig_hi
        elif variant == "v2_confirm":
            sig_mid = (sig_hi + sig_lo) / 2.0
            conf_k = None
            for k in range(k0, k_end):
                cl = float(sub["close"].iloc[k])
                if (side == "long" and cl > sig_mid) or (side == "short" and cl < sig_mid):
                    conf_k = k; break
            if conf_k is None:
                if not fallback:
                    n_skip += 1; continue
                entry_k = k0
            else:
                entry_k = conf_k + 1
                if entry_k >= len(sub):
                    n_skip += 1; continue
        elif variant == "v3_narrow":
            entry_k = k0
            new_sl = sig_lo if side == "long" else sig_hi

        if entry_k is None or entry_k - 1 < 0:
            continue
        # sanity: stop on correct side of the entry-bar OPEN
        entry_open = float(sub["open"].iloc[entry_k])
        if side == "long" and new_sl >= entry_open:
            n_skip += 1; continue
        if side == "short" and new_sl <= entry_open:
            n_skip += 1; continue
        sig_ts = pd.Timestamp(sub["ts"].iloc[entry_k - 1]).to_pydatetime()
        tp = entry_open + 3 * abs(entry_open - new_sl) if side == "long" else entry_open - 3 * abs(entry_open - new_sl)
        # Signal.timeframe is a constrained literal (no '30m'); use a valid one — engine
        # bar logic uses run(timeframe=) kwarg + the injected df, NOT sig.timeframe.
        sig_tf = "1h" if tf == "30m" else tf
        out.append(Signal(
            timeframe=sig_tf, ts=sig_ts, venue="forex", symbol=sym, direction=side,
            pattern_id="brooks_mtf", confluence_score=2.0, sl_price=float(new_sl),
            tp_price=float(tp), suggested_size_atr=1.0,
            metadata={"atr14": atr14}, manifest_hash="mtf",
        ))
    return out, n_skip


# ---------------------------------------------------------------------------
def build_cfg(raw, mc=8) -> ProductionConfig:
    return ProductionConfig(
        risk_pct=0.01, leverage=float(raw["leverage"]["max_leverage_per_symbol"]),
        max_notional_pct_equity=None, conf_min=0.0,
        daily_dd=raw["drawdown_breakers"]["daily_loss_pct"],
        weekly_dd=raw["drawdown_breakers"]["weekly_loss_pct"],
        monthly_dd=raw["drawdown_breakers"]["monthly_loss_pct"],
        consecutive_loss_n=None, same_symbol_side_cooldown_days=1.0,
        max_concurrent=mc, initial_capital=10_000.0)


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
    a = np.array(Rs); wins = a[a > 0]; losses = a[a < 0]
    pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
    thr = np.percentile(a, 95)
    top5 = a[a >= thr].sum() / wins.sum() * 100 if wins.sum() > 0 else 0.0
    return dict(n=len(Rs), mR=float(a.mean()), wr=len(wins) / len(a) * 100, pf=pf, top5=top5)


def portfolio_profile(pooled, base_cfg, eff_r):
    if not pooled:
        return None
    res = production_replay(sorted(pooled, key=lambda x: x["entry_ts"]),
                            base_cfg.with_overrides(risk_pct=eff_r))
    if res is None:
        return None
    mr = monthly_ret(res.equity_curve, res.entry_ts_list)
    if mr.empty:
        return None
    return dict(n_tr=res.trades, robmed=robust_median(mr), med=float(mr.median()),
                mean=float(mr.mean()), std=float(mr.std()),
                sharpe=float(mr.mean() / mr.std()) if mr.std() > 0 else 0.0,
                dd=cont_dd(res.equity_curve), final=res.final_equity / 10000.0)


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
    raw = yaml.safe_load((ROOT / "configs" / "risk_forex.yaml").read_text())
    base_cfg = build_cfg(raw)
    print("=" * 112)
    print("MTF ENTRY REFINEMENT v2 — ENGINE-FAITHFUL re-injection (HYP-2026-05-29-mtf-entry-refinement)")
    print("=" * 112)
    print("git=e7d0a90 data_hash=90bb22160ab3692c seed=12345  slip 1.0bps fee=0 swap haircut")
    print("IS=[2020,2024) OOS=[2024,2026)  core 3sym  exit=REAL engine multi-target trail (injection)")

    sigs4 = {}; df4 = {}
    for s in CORE:
        sg, dfp = capture_signals(s)
        sigs4[s] = sg; df4[s] = dfp
    print(f"captured 4H signals: " + " ".join(f"{s}={len(sigs4[s])}" for s in CORE))

    # ---- ROUND-TRIP fidelity: re-inject 4H signals on 4H df, compare to baseline pkl ----
    print("\n" + "-" * 112)
    print("[FIDELITY CHECK] re-inject 4H signals on 4H bars -> must reproduce engine-R baseline")
    import pickle
    pkl = pickle.load(open("/tmp/rt_trades.pkl", "rb"))
    rt_pooled = []
    for s in CORE:
        trs = run_engine(sigs4[s], df4[s], s, "4h")
        rt_pooled.extend(trs)
        base = [t for t in pkl["trades"][s]]
        rmatch = "n/a"
        if base and trs:
            rb = np.array(sorted([round(t["R"], 4) for t in base]))
            rt = np.array(sorted([round(t["R"], 4) for t in trs]))
            if len(rb) == len(rt):
                rmatch = f"max|Δ|={np.abs(rb - rt).max():.4f}"
            else:
                rmatch = f"N MISMATCH base={len(rb)} rt={len(rt)}"
        print(f"  {s}: pkl_n={len(pkl['trades'][s])} reinjected_n={len(trs)}  R-sorted {rmatch}")
    rt_stat = r_stats(rt_pooled)
    pe = portfolio_profile(rt_pooled, base_cfg, 0.015)
    print(f"  RE-INJECTED 4H FULL: n={rt_stat['n']} mR={rt_stat['mR']:+.3f} wr={rt_stat['wr']:.1f}% "
          f"pf={rt_stat['pf']:.2f} top5={rt_stat['top5']:.0f}%  port@1.5%: robMed={pe['robmed']:+.2f}% "
          f"Sharpe={pe['sharpe']:+.3f} DD={pe['dd']:+.1f}%" if pe else "")

    # ---- variant grid ----
    VARIANTS = [("baseline", None), ("v1_pullback", 0.382), ("v1_pullback", 0.5),
                ("v1n_pullback_narrow", 0.5), ("v2_confirm", None), ("v3_narrow", None)]
    TFS = ["1h", "30m", "15m"]
    NWIN = {"1h": 8, "30m": 16, "15m": 32}
    sub_data = {(s, tf): load_tf(s, tf) for s in CORE for tf in TFS}

    print("\n" + "=" * 112)
    print("(b) VARIANT GRID (SKIP-mode). All R via REAL engine on sub-TF bars.")
    print("=" * 112)
    hdr = (f"{'variant':<22} {'tf':>4} {'n':>5} {'skip%':>6} {'IS_mR':>8} {'OOS_mR':>8} {'OOS_wr':>7} "
           f"{'OOS_pf':>7} {'top5':>6} {'robMed%':>8} {'Sharpe':>7} {'DD%':>7} {'sh_p':>6}")
    print(hdr); print("-" * len(hdr))
    results = {}
    for variant, depth in VARIANTS:
        for tf in TFS:
            pooled = []; skip = 0; ntot = 0
            for s in CORE:
                sigs, nsk = refined_signals(sigs4[s], df4[s], sub_data[(s, tf)], s, tf,
                                            variant, depth, NWIN[tf], fallback=False)
                ntot += len(sigs) + nsk
                skip += nsk
                pooled.extend(run_engine(sigs, sub_data[(s, tf)], s, tf))
            is_tr = [t for t in pooled if t["entry_ts"] < IS_END]
            oos_tr = [t for t in pooled if t["entry_ts"] >= IS_END]
            si = r_stats(is_tr); so = r_stats(oos_tr)
            prof = portfolio_profile(pooled, base_cfg, 0.015)
            sp = shuffle_p(oos_tr) if oos_tr else 1.0
            results[(variant, depth, tf)] = dict(is_mR=si["mR"], oos_mR=so["mR"], oos_wr=so["wr"],
                                                  oos_pf=so["pf"], top5=so["top5"], prof=prof,
                                                  n=len(pooled), skip=skip / ntot * 100 if ntot else 0)
            dl = f"{depth}" if depth else "-"
            rob = prof["robmed"] if prof else float("nan")
            shp = prof["sharpe"] if prof else float("nan")
            dd = prof["dd"] if prof else float("nan")
            print(f"{variant+'['+dl+']':<22} {tf:>4} {len(pooled):>5} {results[(variant,depth,tf)]['skip']:>5.0f}% "
                  f"{si['mR']:>+8.3f} {so['mR']:>+8.3f} {so['wr']:>6.1f}% {so['pf']:>7.2f} {so['top5']:>5.0f}% "
                  f"{rob:>+7.2f}% {shp:>+6.3f} {dd:>+6.1f}% {sp:>6.3f}")

    # ---- Δ vs baseline-resim (same TF) ----
    print("\n" + "=" * 112)
    print("(c) NARROW-STOP TRADE-OFF + Δ vs baseline-resim (engine re-sim of 4H-open entry, same TF)")
    print("=" * 112)
    for tf in TFS:
        b = results[("baseline", None, tf)]; bp = b["prof"]
        print(f"  base-resim[{tf}] n={b['n']} IS_mR={b['is_mR']:+.3f} OOS_mR={b['oos_mR']:+.3f} "
              f"OOS_wr={b['oos_wr']:.1f}% robMed={bp['robmed']:+.2f}% Sharpe={bp['sharpe']:+.3f} top5={b['top5']:.0f}%")
    dh = (f"{'variant':<22} {'tf':>4} {'ΔIS_mR':>8} {'ΔOOS_mR':>9} {'ΔOOSwr':>8} {'ΔrobMed':>9} "
          f"{'ΔSharpe':>9} {'Δtop5':>7} {'net?':>6}")
    print("\n" + dh); print("-" * len(dh))
    for variant, depth in VARIANTS:
        if variant == "baseline":
            continue
        for tf in TFS:
            r = results[(variant, depth, tf)]; b = results[("baseline", None, tf)]
            if not r["prof"] or not b["prof"]:
                continue
            d_oos = r["oos_mR"] - b["oos_mR"]; d_rob = r["prof"]["robmed"] - b["prof"]["robmed"]
            net = "WIN" if (d_oos > 0 and d_rob > 0) else ("part" if (d_oos > 0 or d_rob > 0) else "lose")
            dl = f"{depth}" if depth else "-"
            print(f"{variant+'['+dl+']':<22} {tf:>4} {r['is_mR']-b['is_mR']:>+8.3f} {d_oos:>+9.3f} "
                  f"{r['oos_wr']-b['oos_wr']:>+7.1f}% {d_rob:>+8.2f}% "
                  f"{r['prof']['sharpe']-b['prof']['sharpe']:>+8.3f} {r['top5']-b['top5']:>+6.0f}% {net:>6}")

    # ---- IS->OOS decay ----
    print("\n" + "=" * 112)
    print("(d) IS->OOS DECAY (overfit gate)")
    print("=" * 112)
    for variant, depth in VARIANTS:
        for tf in TFS:
            r = results[(variant, depth, tf)]
            if r["is_mR"] == 0:
                continue
            decay = (r["oos_mR"] - r["is_mR"]) / abs(r["is_mR"]) * 100
            flag = "OOS NEG" if r["oos_mR"] < 0 else ("COLLAPSE" if r["oos_mR"] < r["is_mR"] * 0.5 else "ok")
            dl = f"{depth}" if depth else "-"
            print(f"  {variant+'['+dl+']':<22} {tf:>4} IS_mR={r['is_mR']:+.3f} OOS_mR={r['oos_mR']:+.3f} "
                  f"decay={decay:+.0f}% {flag}")
    print("\nDONE. Verdict in researcher report.")


if __name__ == "__main__":
    main()
