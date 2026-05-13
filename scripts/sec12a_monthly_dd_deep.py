"""SEC12A: monthly_dd DERIN optimization.

Mevcut prod v1.2.0: yıllık +%51.2 / DD -%34.2 / r-adj 1.498
  monthly_dd=0.08, tp2_R=1.5, TOP_11 (FVG eklendi)

Sorun: monthly_dd=0.08 1 ay icinde %8 dustugunde 30 gun halt veriyor.
Iyi/kotu trade'leri ayirt etmiyor.

Pre-registered grid:
  STATIC: monthly_dd ∈ {0.05, 0.06, 0.07, 0.08*, 0.09, 0.10, 0.12, 0.15, 0.20}
  HALT_DAYS: blocked period {7, 14, 21, 30*}
  COMBINED: 9 x 4 = 36 hücre

Adaptive variants (manual replay):
  V_A: BTC vol-aware — ATR%>5 -> dd=0.12, ATR%<3 -> dd=0.06
  V_B: Smooth re-entry — halt sonrası 7g %50 risk
  V_C: Side-conditional — long_dd ve short_dd ayrı

Statistical gates:
  - yıllık ≥ baseline + 1pp
  - DD tolerans baseline + 5pp
  - 13 pencere 0 negatif
  - r-adj ≥ 1.5

Output: reports/lab/sec12a_monthly_dd_deep.md
"""
from __future__ import annotations

import os
import sys
import pickle
from pathlib import Path
from statistics import mean, median
from datetime import timedelta

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.engine import BacktestEngine
from price_action.backtest.lab import (
    ProductionConfig, production_replay, _lazy_build_funding_filters,
)
from price_action.backtest.regime import compute_btc_capitulation_halt
from scripts.run_real_backtest import _load_symbol_ohlcv
from scripts.v09_optimize_top10 import _gather, TOP_10, SYMBOLS_11
from scripts.v097_balanced_optimization import DROP_PAIRS, build_fng_short_skip
from price_action.signals.filters import volume_zscore

# v1.2.0 stack
TOP_11 = TOP_10 + [("fvg_fill_reversal", "FVGFillReversalStrategy")]

CACHE_PATH = ROOT / "data" / "sec12a_v12_pool.pkl"
REPORT_PATH = ROOT / "reports" / "lab" / "sec12a_monthly_dd_deep.md"


# =====================================================================
# Pool generation (sec11_final_stack.gather_with_engine kopyasi)
# =====================================================================

def gather_with_engine(module_name, class_name, *,
                       runner_trail_mult=1.0, trail_activate_stage=2,
                       tp1_R=1.0, tp2_R=2.0, tp1_close_pct=0.30, tp2_close_pct=0.30):
    try:
        mod = __import__(f"price_action.strategies.{module_name}",
                         fromlist=[class_name, "_default_manifest"])
        cls = getattr(mod, class_name)
        manifest_fn = getattr(mod, "_default_manifest", None)
        if not manifest_fn:
            return []
        s = cls(manifest_fn())
    except Exception as e:
        print(f"  [WARN] {module_name}: {e}")
        return []

    out = []
    for sym in SYMBOLS_11:
        try:
            df = _load_symbol_ohlcv(sym, tf="1d")
            if df is None or df.empty:
                continue
            df = df.sort_values("ts").reset_index(drop=True)
            df["symbol"] = sym
            df["venue"] = "binance"
            df["timeframe"] = "1d"
            try:
                df["vol_z_pre"] = volume_zscore(df["volume"], period=20)
            except Exception:
                rolling = df["volume"].rolling(20)
                df["vol_z_pre"] = (df["volume"] - rolling.mean()) / rolling.std()

            def prov(*a, **k):
                return df.copy()

            e = BacktestEngine(
                risk_officer=None, store_load=None,
                runner_trail_mult=runner_trail_mult,
                trail_activate_stage=trail_activate_stage,
                tp1_R=tp1_R, tp2_R=tp2_R,
                tp1_close_pct=tp1_close_pct, tp2_close_pct=tp2_close_pct,
            )
            r = e.run(
                s, [sym],
                start=df["ts"].iloc[0].to_pydatetime(),
                end=df["ts"].iloc[-1].to_pydatetime(),
                timeframe="1d", initial_capital=10_000.0,
                fees={"taker": 0.00075, "maker": -0.00010}, slippage_bps=5.0,
                ohlcv_provider=prov,
            )
            ts_map = pd.to_datetime(df["ts"], utc=True)
            for _, t in r.trades.iterrows():
                conf = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
                ts_e = pd.Timestamp(t["entry_ts"])
                if ts_e.tzinfo is None:
                    ts_e = ts_e.tz_localize("UTC")
                ts_x = pd.Timestamp(t["exit_ts"])
                if ts_x.tzinfo is None:
                    ts_x = ts_x.tz_localize("UTC")
                mask = ts_map < ts_e
                vz = 0.0
                if mask.any():
                    idx = ts_map[mask].index[-1]
                    val = df["vol_z_pre"].iloc[idx]
                    if pd.notna(val):
                        vz = float(val)
                out.append({
                    "entry_ts": ts_e, "exit_ts": ts_x,
                    "entry_price": float(t["entry_price"]),
                    "initial_sl": float(t["initial_sl"]),
                    "R": float(t["realized_r_multiple"]),
                    "symbol": sym, "side": str(t["side"]).lower(),
                    "conf": conf, "strategy": module_name, "vol_z": vz,
                })
        except Exception as e:
            print(f"  [WARN] {module_name} on {sym}: {e}")
    return out


def build_v12_pool():
    """v1.2.0 stack pool: TOP_11 (FVG eklendi) + tp2_R=1.5"""
    if CACHE_PATH.exists():
        print(f"Cache hit: {CACHE_PATH.name}")
        with CACHE_PATH.open("rb") as f:
            return pickle.load(f)
    print("Pool gen v1.2 (TOP_11 + tp2_R=1.5) ...")
    pool = []
    for m, c in TOP_11:
        ts = gather_with_engine(m, c, runner_trail_mult=1.0, tp1_R=1.0, tp2_R=1.5)
        pool.extend(ts)
        print(f"  {m}: {len(ts)} trade")
    pool.sort(key=lambda x: x["entry_ts"])
    with CACHE_PATH.open("wb") as f:
        pickle.dump(pool, f)
    print(f"  Toplam: {len(pool)} trade -> cache {CACHE_PATH.name}")
    return pool


# =====================================================================
# Manual replay — halt_days override + adaptive variants
# =====================================================================

def replay_with_monthly_dd(trades_in, cfg, monthly_dd, halt_days=30,
                           adaptive_btc_vol=None, smooth_reentry_days=0,
                           smooth_reentry_factor=0.5,
                           side_dd_long=None, side_dd_short=None,
                           strategy_excluded=None,
                           track_halt=False):
    """
    monthly_dd halt + opsiyonel:
      - halt_days override (default 30)
      - adaptive_btc_vol: dict[date -> atr_pct]. Veriliyorsa monthly_dd dynamic.
      - smooth_reentry_days: halt sonrası %50 risk N gun
      - side_dd_long/short: long ve short ayrı dd thresholdlari (set edilirse monthly_dd ignore)
      - strategy_excluded: set of strategy names — bu strateji halt'tan etkilenmez (always allowed)
    """
    trades = sorted(trades_in, key=lambda t: t["entry_ts"])
    if not trades:
        return None
    equity = cfg.initial_capital
    cash = cfg.initial_capital
    open_pos = []
    Rs = []
    eq_curve = [cfg.initial_capital]
    last_d = trades[0]["entry_ts"].date()
    last_w = trades[0]["entry_ts"].isocalendar()[1]
    last_m = trades[0]["entry_ts"].month
    daily_anchor = weekly_anchor = monthly_anchor = cfg.initial_capital
    monthly_anchor_long = cfg.initial_capital
    monthly_anchor_short = cfg.initial_capital
    blocked_until = None
    blocked_until_long = None
    blocked_until_short = None
    last_entry = {}
    consec_loss = 0
    cool_until = None
    peak = cfg.initial_capital
    smooth_until = None
    halt_log = []  # (entry_ts, type) — for forensic

    def close_due(now):
        nonlocal cash, equity, peak, consec_loss, cool_until
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                pnl = p["risk"] * p["R"]
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                peak = max(peak, equity)
                Rs.append(p["R"])
                eq_curve.append(equity)
                if pnl < 0:
                    consec_loss += 1
                    if cfg.consecutive_loss_n and consec_loss >= cfg.consecutive_loss_n:
                        cool_until = p["exit_ts"] + timedelta(days=cfg.consecutive_loss_pause_days)
                        consec_loss = 0
                else:
                    consec_loss = 0
            else:
                still.append(p)
        open_pos[:] = still

    for t in trades:
        close_due(t["entry_ts"])
        if cool_until and t["entry_ts"] < cool_until:
            continue

        d_key = t["entry_ts"].date()

        # halt + alt-data filters (production_replay parity)
        if cfg.btc_halt_calendar is not None:
            if cfg.btc_halt_calendar.get(d_key, False):
                continue
        side_t = t.get("side", "").lower()
        if cfg.alt_data_skip_long is not None and side_t == "long":
            if cfg.alt_data_skip_long.get(d_key, False):
                continue
        if cfg.alt_data_skip_short is not None and side_t == "short":
            if cfg.alt_data_skip_short.get(d_key, False):
                continue
        if cfg.drop_pairs and (t["strategy"], t["symbol"]) in cfg.drop_pairs:
            continue
        if t["conf"] < cfg.conf_min:
            continue

        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).days < cfg.same_symbol_side_cooldown_days:
            continue

        cd = t["entry_ts"].date()
        cw = t["entry_ts"].isocalendar()[1]
        cm = t["entry_ts"].month
        if cd != last_d:
            daily_anchor = equity
            last_d = cd
        if cw != last_w:
            weekly_anchor = equity
            last_w = cw
        if cm != last_m:
            monthly_anchor = equity
            monthly_anchor_long = equity
            monthly_anchor_short = equity
            last_m = cm

        # daily / weekly halt (degismez)
        if blocked_until and t["entry_ts"] < blocked_until:
            continue
        if (daily_anchor - equity) / max(daily_anchor, 1) >= cfg.daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=1)
            continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= cfg.weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=7)
            continue

        # MONTHLY DD — esas test ettigimiz
        # Strategy exclusion: bu trade halt'tan muaf mi?
        is_excluded = (strategy_excluded is not None
                       and t["strategy"] in strategy_excluded)

        if side_dd_long is not None or side_dd_short is not None:
            # Side-conditional mode
            sl = side_dd_long if side_dd_long is not None else monthly_dd
            ss = side_dd_short if side_dd_short is not None else monthly_dd
            if side_t == "long":
                if blocked_until_long and t["entry_ts"] < blocked_until_long and not is_excluded:
                    if track_halt:
                        halt_log.append((t["entry_ts"], "long_blocked"))
                    continue
                if (monthly_anchor_long - equity) / max(monthly_anchor_long, 1) >= sl:
                    blocked_until_long = t["entry_ts"] + timedelta(days=halt_days)
                    smooth_until = t["entry_ts"] + timedelta(days=halt_days + smooth_reentry_days)
                    if track_halt:
                        halt_log.append((t["entry_ts"], "long_trigger"))
                    continue
            else:
                if blocked_until_short and t["entry_ts"] < blocked_until_short and not is_excluded:
                    if track_halt:
                        halt_log.append((t["entry_ts"], "short_blocked"))
                    continue
                if (monthly_anchor_short - equity) / max(monthly_anchor_short, 1) >= ss:
                    blocked_until_short = t["entry_ts"] + timedelta(days=halt_days)
                    smooth_until = t["entry_ts"] + timedelta(days=halt_days + smooth_reentry_days)
                    if track_halt:
                        halt_log.append((t["entry_ts"], "short_trigger"))
                    continue
        else:
            # Single monthly dd (opt. adaptive)
            mdd = monthly_dd
            if adaptive_btc_vol is not None:
                atr_pct = adaptive_btc_vol.get(d_key, None)
                if atr_pct is not None:
                    if atr_pct > 5.0:
                        mdd = 0.12
                    elif atr_pct < 3.0:
                        mdd = 0.06
                    else:
                        mdd = monthly_dd
            # blocked check
            if blocked_until and t["entry_ts"] < blocked_until and not is_excluded:
                if track_halt:
                    halt_log.append((t["entry_ts"], "blocked"))
                continue
            if (monthly_anchor - equity) / max(monthly_anchor, 1) >= mdd:
                blocked_until = t["entry_ts"] + timedelta(days=halt_days)
                smooth_until = t["entry_ts"] + timedelta(days=halt_days + smooth_reentry_days)
                if track_halt:
                    halt_log.append((t["entry_ts"], "trigger"))
                continue

        if len(open_pos) >= cfg.max_concurrent:
            continue

        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0:
            continue

        # confidence-based dynamic risk_pct
        if cfg.confidence_risk_tiers:
            from price_action.backtest.scoring import get_tier_value
            conf_for_tier = t.get("conf_pct", t["conf"])
            trade_risk_pct = float(get_tier_value(
                cfg.confidence_risk_tiers, conf_for_tier, "risk_pct", cfg.risk_pct
            ))
        else:
            trade_risk_pct = cfg.risk_pct

        risk_modifier = 1.0
        # Smooth re-entry: halt biter bitmez 7g %50 risk
        if smooth_until and t["entry_ts"] < smooth_until and (
            blocked_until is None or t["entry_ts"] >= blocked_until
        ):
            risk_modifier = smooth_reentry_factor

        risk_d = equity * trade_risk_pct * risk_modifier
        notional = risk_d / sl_pct
        if cfg.max_notional_pct_equity is not None:
            cap = equity * cfg.max_notional_pct_equity
            if notional > cap:
                notional = cap
                risk_d = notional * sl_pct
        # Concentration gate
        if cfg.concentration_max_per_symbol_pct is not None:
            existing = sum(p["notional"] for p in open_pos if p.get("symbol") == t["symbol"])
            sym_cap = equity * cfg.concentration_max_per_symbol_pct
            if existing + notional > sym_cap:
                continue

        # Leverage tiers
        if cfg.leverage_tiers:
            from price_action.backtest.scoring import get_tier_value
            conf_for_tier = t.get("conf_pct", t["conf"])
            trade_lev = float(get_tier_value(
                cfg.leverage_tiers, conf_for_tier, "leverage", cfg.leverage
            ))
        else:
            trade_lev = cfg.leverage
        if trade_lev <= 0:
            trade_lev = 1.0
        margin = notional / trade_lev
        if margin > cash:
            continue

        cash -= margin
        last_entry[key] = t["entry_ts"]
        open_pos.append({
            "exit_ts": t["exit_ts"], "margin": margin, "notional": notional,
            "risk": risk_d, "R": t["R"],
            "symbol": t["symbol"], "side": t["side"],
        })

    for p in open_pos:
        cash += p["margin"] + p["risk"] * p["R"]
        equity = cash
        Rs.append(p["R"])
        eq_curve.append(equity)

    # max DD
    peak = eq_curve[0]
    max_dd = 0.0
    for v in eq_curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak if peak > 0 else 0
        if dd < max_dd:
            max_dd = dd
    return {
        "final": equity, "max_dd": max_dd, "n_trades": len(Rs),
        "halt_log": halt_log,
    }


# =====================================================================
# BTC vol calendar
# =====================================================================

def build_btc_atr_calendar(period=14):
    """BTC daily ATR% (smoothed) -> dict[date -> atr_pct]."""
    df = _load_symbol_ohlcv("BTC/USDT", tf="1d")
    if df.empty:
        return {}
    df = df.sort_values("ts").reset_index(drop=True)
    high = df["high"].values
    low = df["low"].values
    close = df["close"].values
    tr = np.zeros(len(df))
    for i in range(len(df)):
        if i == 0:
            tr[i] = high[i] - low[i]
        else:
            tr[i] = max(
                high[i] - low[i],
                abs(high[i] - close[i - 1]),
                abs(low[i] - close[i - 1]),
            )
    atr = pd.Series(tr).rolling(period).mean().values
    atr_pct = atr / close * 100.0
    cal = {}
    for i in range(len(df)):
        d = pd.Timestamp(df["ts"].iloc[i]).date()
        if not np.isnan(atr_pct[i]):
            cal[d] = float(atr_pct[i])
    return cal


# =====================================================================
# Window utility
# =====================================================================

def window_metrics(pool, cfg, replay_fn, **kw):
    """13 pencere 3y rolling — ann/dd/halt aggregate."""
    if not pool:
        return None
    start = pool[0]["entry_ts"]
    end = pool[-1]["exit_ts"]
    windows = []
    cur = start
    while cur + pd.Timedelta(days=3 * 365) <= end:
        windows.append((cur, cur + pd.Timedelta(days=3 * 365)))
        cur += pd.Timedelta(days=60)
    anns, dds, halts, per_window = [], [], [], []
    for ws, we in windows:
        ww_t = [t for t in pool if ws <= t["entry_ts"] < we]
        r = replay_fn(ww_t, cfg, **kw)
        if r is None or r["n_trades"] == 0:
            continue
        ret = r["final"] / cfg.initial_capital - 1.0
        ann = (1.0 + ret) ** (1.0 / 3.0) - 1.0
        anns.append(ann * 100)
        dds.append(r["max_dd"] * 100)
        n_trig = sum(1 for _, k in r.get("halt_log", []) if "trigger" in k)
        halts.append(n_trig)
        per_window.append({
            "start": ws.strftime("%Y-%m-%d"),
            "end": we.strftime("%Y-%m-%d"),
            "ann": ann * 100,
            "dd": r["max_dd"] * 100,
            "halts": n_trig,
        })
    if not anns:
        return None
    return {
        "ann_mean": mean(anns),
        "ann_med": median(anns),
        "ann_min": min(anns),
        "ann_max": max(anns),
        "dd_mean": mean(dds),
        "halts_mean": mean(halts) if halts else 0,
        "neg": sum(1 for a in anns if a < 0),
        "n_windows": len(anns),
        "per_window": per_window,
    }


# =====================================================================
# MAIN
# =====================================================================

def main():
    print("=" * 110)
    print("SEC12A: monthly_dd DERIN OPTIMIZATION — 13 pencere 3y rolling")
    print("=" * 110)

    # Pool gen v1.2 (TOP_11 + tp2_R=1.5)
    pool = build_v12_pool()
    if not pool:
        print("EMPTY POOL — abort"); return

    # Config (v1.2 baseline = monthly_dd=0.08)
    base = ProductionConfig.from_yaml("configs/risk_balanced.yaml")
    halt_cal = compute_btc_capitulation_halt()
    fund_long, fund_short = _lazy_build_funding_filters({
        "funding_filter_enabled": True, "funding_aggregation_mode": "00:00_only",
    })
    fng_short_20 = build_fng_short_skip(20)
    combined_short_skip = {**dict(fund_short or {}), **dict(fng_short_20)}
    cfg_v12 = base.with_overrides(
        alt_data_skip_long=fund_long,
        alt_data_skip_short=combined_short_skip,
        drop_pairs=DROP_PAIRS,
        btc_halt_calendar=halt_cal,
        monthly_dd=0.08,
    )

    # =================================================================
    # STAGE 1: production_replay BASELINE (v1.2 sanity)
    # =================================================================
    print("\nSTAGE 1: production_replay v1.2 baseline (sanity)")
    base_metrics = window_metrics(
        pool, cfg_v12,
        lambda tr, c: _wrap_pr(production_replay(tr, c)),
    )
    if base_metrics:
        print(f"  prod_replay v1.2 (monthly_dd=0.08): "
              f"yıllık {base_metrics['ann_mean']:+.2f}% / "
              f"DD {base_metrics['dd_mean']:+.2f}% / "
              f"r-adj {base_metrics['ann_mean']/abs(base_metrics['dd_mean']):.3f} / "
              f"neg {base_metrics['neg']}/{base_metrics['n_windows']}")

    # Manual replay sanity (replay_with_monthly_dd dd=0.08 days=30 == prod)
    print("\nSTAGE 1.b: manual_replay sanity (must match prod)")
    s_metrics = window_metrics(
        pool, cfg_v12, replay_with_monthly_dd,
        monthly_dd=0.08, halt_days=30, track_halt=True,
    )
    if s_metrics:
        print(f"  manual v1.2 baseline:   "
              f"yıllık {s_metrics['ann_mean']:+.2f}% / "
              f"DD {s_metrics['dd_mean']:+.2f}% / "
              f"r-adj {s_metrics['ann_mean']/abs(s_metrics['dd_mean']):.3f} / "
              f"neg {s_metrics['neg']}/{s_metrics['n_windows']} / "
              f"halts/win {s_metrics['halts_mean']:.1f}")

    # =================================================================
    # STAGE 2: STATIC monthly_dd grid (halt_days=30)
    # =================================================================
    print("\nSTAGE 2: STATIC monthly_dd grid (halt_days=30)")
    print(f"  {'mdd':<6} {'yillik':>8} {'med':>7} {'min':>7} {'max':>7} {'DD':>7} {'r-adj':>7} {'neg':>7} {'halts/w':>7}")
    static_rows = []
    for mdd in [0.05, 0.06, 0.07, 0.08, 0.09, 0.10, 0.12, 0.15, 0.20]:
        m = window_metrics(pool, cfg_v12, replay_with_monthly_dd,
                          monthly_dd=mdd, halt_days=30, track_halt=True)
        if not m: continue
        ra = m["ann_mean"] / abs(m["dd_mean"]) if m["dd_mean"] != 0 else 0
        print(f"  {mdd:<6.2f} {m['ann_mean']:>+7.2f}% {m['ann_med']:>+5.2f}% {m['ann_min']:>+5.2f}% {m['ann_max']:>+5.2f}% {m['dd_mean']:>+5.2f}% {ra:>6.3f} {m['neg']:>3}/{m['n_windows']} {m['halts_mean']:>6.1f}")
        static_rows.append((mdd, 30, m, ra))

    # =================================================================
    # STAGE 3: HALT_DAYS grid (mdd=0.08)
    # =================================================================
    print("\nSTAGE 3: HALT_DAYS grid (mdd=0.08)")
    print(f"  {'days':<6} {'yillik':>8} {'med':>7} {'min':>7} {'max':>7} {'DD':>7} {'r-adj':>7} {'neg':>7} {'halts/w':>7}")
    halt_rows = []
    for hd in [7, 14, 21, 30]:
        m = window_metrics(pool, cfg_v12, replay_with_monthly_dd,
                          monthly_dd=0.08, halt_days=hd, track_halt=True)
        if not m: continue
        ra = m["ann_mean"] / abs(m["dd_mean"]) if m["dd_mean"] != 0 else 0
        print(f"  {hd:<6d} {m['ann_mean']:>+7.2f}% {m['ann_med']:>+5.2f}% {m['ann_min']:>+5.2f}% {m['ann_max']:>+5.2f}% {m['dd_mean']:>+5.2f}% {ra:>6.3f} {m['neg']:>3}/{m['n_windows']} {m['halts_mean']:>6.1f}")
        halt_rows.append((0.08, hd, m, ra))

    # =================================================================
    # STAGE 4: COMBINED grid (mdd x halt_days)
    # =================================================================
    print("\nSTAGE 4: COMBINED mdd x halt_days grid")
    print(f"  {'mdd':<6} {'days':<6} {'yillik':>8} {'DD':>7} {'r-adj':>7} {'neg':>7} {'halts/w':>7}")
    combo_rows = []
    for mdd in [0.06, 0.08, 0.10, 0.12, 0.15]:
        for hd in [7, 14, 21, 30]:
            m = window_metrics(pool, cfg_v12, replay_with_monthly_dd,
                              monthly_dd=mdd, halt_days=hd, track_halt=True)
            if not m: continue
            ra = m["ann_mean"] / abs(m["dd_mean"]) if m["dd_mean"] != 0 else 0
            print(f"  {mdd:<6.2f} {hd:<6d} {m['ann_mean']:>+7.2f}% {m['dd_mean']:>+5.2f}% {ra:>6.3f} {m['neg']:>3}/{m['n_windows']} {m['halts_mean']:>6.1f}")
            combo_rows.append((mdd, hd, m, ra))

    # =================================================================
    # STAGE 5: ADAPTIVE VARIANTS
    # =================================================================
    print("\nSTAGE 5.A: BTC vol-aware adaptive (ATR%>5 -> 0.12, ATR%<3 -> 0.06, mid -> 0.08)")
    btc_atr_cal = build_btc_atr_calendar(period=14)
    print(f"  BTC ATR cal: {len(btc_atr_cal)} gun")
    high_vol_days = sum(1 for v in btc_atr_cal.values() if v > 5)
    low_vol_days = sum(1 for v in btc_atr_cal.values() if v < 3)
    print(f"  high-vol (>5%): {high_vol_days}, low-vol (<3%): {low_vol_days}")
    m_a = window_metrics(pool, cfg_v12, replay_with_monthly_dd,
                        monthly_dd=0.08, halt_days=30,
                        adaptive_btc_vol=btc_atr_cal, track_halt=True)
    if m_a:
        ra = m_a["ann_mean"] / abs(m_a["dd_mean"])
        print(f"  V_A adaptive: yıllık {m_a['ann_mean']:+.2f}% / DD {m_a['dd_mean']:+.2f}% / r-adj {ra:.3f} / neg {m_a['neg']}/{m_a['n_windows']} / halts/w {m_a['halts_mean']:.1f}")

    print("\nSTAGE 5.B: SMOOTH RE-ENTRY (halt sonrası 7g %50 risk)")
    smooth_rows = []
    for sd in [7, 14]:
        m = window_metrics(pool, cfg_v12, replay_with_monthly_dd,
                          monthly_dd=0.08, halt_days=30,
                          smooth_reentry_days=sd, smooth_reentry_factor=0.5,
                          track_halt=True)
        if not m: continue
        ra = m["ann_mean"] / abs(m["dd_mean"])
        print(f"  V_B smooth_{sd}d: yıllık {m['ann_mean']:+.2f}% / DD {m['dd_mean']:+.2f}% / r-adj {ra:.3f} / neg {m['neg']}/{m['n_windows']}")
        smooth_rows.append((sd, m, ra))

    print("\nSTAGE 5.C: SIDE-CONDITIONAL (long_dd, short_dd ayri)")
    side_rows = []
    for sl, ss in [(0.08, 0.08), (0.10, 0.06), (0.06, 0.10), (0.12, 0.06), (0.06, 0.12)]:
        m = window_metrics(pool, cfg_v12, replay_with_monthly_dd,
                          monthly_dd=0.08, halt_days=30,
                          side_dd_long=sl, side_dd_short=ss,
                          track_halt=True)
        if not m: continue
        ra = m["ann_mean"] / abs(m["dd_mean"])
        print(f"  V_C long={sl:.2f} short={ss:.2f}: yıllık {m['ann_mean']:+.2f}% / DD {m['dd_mean']:+.2f}% / r-adj {ra:.3f} / neg {m['neg']}/{m['n_windows']}")
        side_rows.append((sl, ss, m, ra))

    # =================================================================
    # STAGE 6: HALT INTERACTION TIMELINE — kritik aylar inceleme
    # =================================================================
    print("\nSTAGE 6: HALT INTERACTION TIMELINE — kritik aylar (loss-forensics)")
    # Kritik aylar: 2026-04, 2023-01, 2022-03, 2024-06
    # 13 pencere baseline ile detayli halt log
    print("  Window-level karsılastırma (baseline mdd=0.08 vs gevsek mdd=0.12, halt 30g):")
    base_w = window_metrics(pool, cfg_v12, replay_with_monthly_dd,
                           monthly_dd=0.08, halt_days=30, track_halt=True)
    loose_w = window_metrics(pool, cfg_v12, replay_with_monthly_dd,
                            monthly_dd=0.12, halt_days=30, track_halt=True)
    short_w = window_metrics(pool, cfg_v12, replay_with_monthly_dd,
                            monthly_dd=0.08, halt_days=14, track_halt=True)
    interact = []
    if base_w and loose_w and short_w:
        for i, (b, l, s) in enumerate(zip(base_w["per_window"], loose_w["per_window"], short_w["per_window"])):
            interact.append({
                "window": f"{b['start'][:7]}->{b['end'][:7]}",
                "base_ann": b["ann"], "loose_ann": l["ann"], "short_ann": s["ann"],
                "base_dd": b["dd"], "loose_dd": l["dd"], "short_dd": s["dd"],
                "base_halts": b["halts"], "loose_halts": l["halts"], "short_halts": s["halts"],
            })
        print(f"  {'window':<24} {'b_ann':>8} {'L_ann':>8} {'S_ann':>8} {'b_DD':>6} {'L_DD':>6} {'S_DD':>6} {'b_h':>4} {'L_h':>4} {'S_h':>4}")
        for w in interact:
            print(f"  {w['window']:<24} {w['base_ann']:>+7.1f}% {w['loose_ann']:>+7.1f}% {w['short_ann']:>+7.1f}% "
                  f"{w['base_dd']:>+5.1f}% {w['loose_dd']:>+5.1f}% {w['short_dd']:>+5.1f}% "
                  f"{w['base_halts']:>3d} {w['loose_halts']:>3d} {w['short_halts']:>3d}")

    # =================================================================
    # MARKDOWN REPORT
    # =================================================================
    print("\nWriting report...")
    write_report(REPORT_PATH, base_metrics, s_metrics,
                 static_rows, halt_rows, combo_rows,
                 m_a, smooth_rows, side_rows, interact,
                 high_vol_days, low_vol_days, len(btc_atr_cal))
    print(f"  -> {REPORT_PATH}")

    # =================================================================
    # FINAL DECISION
    # =================================================================
    print("\n" + "=" * 110)
    print("FINAL — STATISTICAL GATES (v1.2 baseline +%51.2 / DD -%34.2 / r-adj 1.498)")
    print("=" * 110)
    BASE_ANN = 51.2
    BASE_DD = -34.2
    BASE_RA = 1.498

    candidates = []
    # Static
    for mdd, hd, m, ra in static_rows:
        candidates.append((f"STATIC mdd={mdd:.2f} hd={hd}", m, ra))
    # Halt-days
    for mdd, hd, m, ra in halt_rows:
        if hd == 30: continue  # zaten static'te
        candidates.append((f"HALT mdd={mdd:.2f} hd={hd}", m, ra))
    # Combo
    for mdd, hd, m, ra in combo_rows:
        candidates.append((f"COMBO mdd={mdd:.2f} hd={hd}", m, ra))
    # V_A
    if m_a:
        ra_a = m_a["ann_mean"] / abs(m_a["dd_mean"])
        candidates.append(("V_A adaptive(BTC vol)", m_a, ra_a))
    # V_B
    for sd, m, ra in smooth_rows:
        candidates.append((f"V_B smooth_{sd}d", m, ra))
    # V_C
    for sl, ss, m, ra in side_rows:
        candidates.append((f"V_C long={sl:.2f}/short={ss:.2f}", m, ra))

    # Apply gates
    passing = []
    for label, m, ra in candidates:
        ann_ok = m["ann_mean"] >= BASE_ANN + 1.0
        dd_ok = m["dd_mean"] >= BASE_DD - 5.0  # tolerans (DD -%39'a kadar OK)
        neg_ok = m["neg"] == 0
        ra_ok = ra >= 1.5
        ok = ann_ok and dd_ok and neg_ok and ra_ok
        passing.append((label, m, ra, ok, ann_ok, dd_ok, neg_ok, ra_ok))

    # Hard pass
    pass_only = [p for p in passing if p[3]]
    if pass_only:
        pass_only.sort(key=lambda x: -x[1]["ann_mean"])
        print(f"\nHARD PASS ({len(pass_only)} aday) — yıllık top 3:")
        for label, m, ra, *_ in pass_only[:3]:
            print(f"  {label:<40} yıllık {m['ann_mean']:+.2f}% / DD {m['dd_mean']:+.2f}% / r-adj {ra:.3f}")
        best = pass_only[0]
        print(f"\nWINNER: {best[0]} -> ann {best[1]['ann_mean']:+.2f}% (vs base {BASE_ANN:+.1f}% = +{best[1]['ann_mean']-BASE_ANN:+.2f}pp)")
    else:
        # Show baseline-equivalent ones
        print("\nNO HARD PASS — gates: ann>=+%52.2 + DD>=-%39.2 + neg=0 + r-adj>=1.5")
        # Most ROI gain
        gain = sorted(passing, key=lambda x: -x[1]["ann_mean"])[:5]
        print("\nTop 5 ROI (gate fail breakdown):")
        for label, m, ra, ok, ann_ok, dd_ok, neg_ok, ra_ok in gain:
            flags = []
            if not ann_ok: flags.append("ANN")
            if not dd_ok: flags.append("DD")
            if not neg_ok: flags.append(f"NEG({m['neg']})")
            if not ra_ok: flags.append("RADJ")
            print(f"  {label:<40} ann {m['ann_mean']:+.2f}% / DD {m['dd_mean']:+.2f}% / r-adj {ra:.3f}  fail:[{','.join(flags) or 'NONE'}]")


def _wrap_pr(r):
    """ReplayResult -> dict shim (window_metrics expects)."""
    if r is None:
        return None
    return {
        "final": r.final_equity, "max_dd": r.max_drawdown,
        "n_trades": r.trades, "halt_log": [],
    }


def write_report(path, base_metrics, s_metrics,
                 static_rows, halt_rows, combo_rows,
                 m_a, smooth_rows, side_rows, interact,
                 high_vol, low_vol, atr_n):
    lines = []
    lines.append("# SEC12A — monthly_dd Derin Optimization\n")
    lines.append("**Pre-registered grid + walk-forward + statistical gates**\n")
    lines.append("**Tarih:** 2026-05-13\n")
    lines.append("**Pool:** v1.2.0 (TOP_11 = TOP_10 + FVG + tp2_R=1.5)\n")
    lines.append("**Baseline:** monthly_dd=0.08, halt_days=30 -> yıllık +%51.2, DD -%34.2, r-adj 1.498\n")
    lines.append("\n## Gates\n")
    lines.append("- Yıllık ≥ baseline + 1pp (+%52.2)\n")
    lines.append("- DD baseline + 5pp tolerans (≥ -%39.2)\n")
    lines.append("- 13/13 pencere ≥ 0 (neg=0)\n")
    lines.append("- r-adj ≥ 1.5\n")

    if base_metrics:
        lines.append("\n## Stage 1 — production_replay v1.2 sanity\n")
        lines.append(f"Yıllık {base_metrics['ann_mean']:+.2f}% / DD {base_metrics['dd_mean']:+.2f}% / r-adj {base_metrics['ann_mean']/abs(base_metrics['dd_mean']):.3f} / neg {base_metrics['neg']}/{base_metrics['n_windows']}\n")
    if s_metrics:
        lines.append(f"\nManual replay sanity (mdd=0.08 hd=30): yıllık {s_metrics['ann_mean']:+.2f}% / DD {s_metrics['dd_mean']:+.2f}% / halts/win {s_metrics['halts_mean']:.1f}\n")

    lines.append("\n## Stage 2 — STATIC monthly_dd grid (halt_days=30)\n")
    lines.append("| mdd | yıllık | med | min | max | DD | r-adj | neg | halts/w |\n")
    lines.append("|-----|--------|-----|-----|-----|-----|-------|-----|---------|\n")
    for mdd, hd, m, ra in static_rows:
        lines.append(f"| {mdd:.2f} | {m['ann_mean']:+.2f}% | {m['ann_med']:+.2f}% | {m['ann_min']:+.2f}% | {m['ann_max']:+.2f}% | {m['dd_mean']:+.2f}% | {ra:.3f} | {m['neg']}/{m['n_windows']} | {m['halts_mean']:.1f} |\n")

    lines.append("\n## Stage 3 — HALT_DAYS grid (mdd=0.08)\n")
    lines.append("| days | yıllık | med | min | max | DD | r-adj | neg | halts/w |\n")
    lines.append("|------|--------|-----|-----|-----|-----|-------|-----|---------|\n")
    for mdd, hd, m, ra in halt_rows:
        lines.append(f"| {hd} | {m['ann_mean']:+.2f}% | {m['ann_med']:+.2f}% | {m['ann_min']:+.2f}% | {m['ann_max']:+.2f}% | {m['dd_mean']:+.2f}% | {ra:.3f} | {m['neg']}/{m['n_windows']} | {m['halts_mean']:.1f} |\n")

    lines.append("\n## Stage 4 — COMBINED mdd x halt_days\n")
    lines.append("| mdd | days | yıllık | DD | r-adj | neg | halts/w |\n")
    lines.append("|-----|------|--------|-----|-------|-----|---------|\n")
    for mdd, hd, m, ra in combo_rows:
        lines.append(f"| {mdd:.2f} | {hd} | {m['ann_mean']:+.2f}% | {m['dd_mean']:+.2f}% | {ra:.3f} | {m['neg']}/{m['n_windows']} | {m['halts_mean']:.1f} |\n")

    lines.append("\n## Stage 5.A — BTC vol-aware adaptive\n")
    lines.append(f"BTC ATR cal: {atr_n} gün, high-vol (>5%): {high_vol}, low-vol (<3%): {low_vol}\n\n")
    if m_a:
        ra = m_a['ann_mean']/abs(m_a['dd_mean'])
        lines.append(f"V_A adaptive: yıllık {m_a['ann_mean']:+.2f}% / DD {m_a['dd_mean']:+.2f}% / r-adj {ra:.3f} / neg {m_a['neg']}/{m_a['n_windows']} / halts/w {m_a['halts_mean']:.1f}\n")

    lines.append("\n## Stage 5.B — SMOOTH RE-ENTRY (halt sonrası N gün %50 risk)\n")
    lines.append("| smooth_days | yıllık | DD | r-adj | neg |\n")
    lines.append("|-------------|--------|-----|-------|-----|\n")
    for sd, m, ra in smooth_rows:
        lines.append(f"| {sd} | {m['ann_mean']:+.2f}% | {m['dd_mean']:+.2f}% | {ra:.3f} | {m['neg']}/{m['n_windows']} |\n")

    lines.append("\n## Stage 5.C — SIDE-CONDITIONAL (long_dd / short_dd ayri)\n")
    lines.append("| long_dd | short_dd | yıllık | DD | r-adj | neg |\n")
    lines.append("|---------|----------|--------|-----|-------|-----|\n")
    for sl, ss, m, ra in side_rows:
        lines.append(f"| {sl:.2f} | {ss:.2f} | {m['ann_mean']:+.2f}% | {m['dd_mean']:+.2f}% | {ra:.3f} | {m['neg']}/{m['n_windows']} |\n")

    lines.append("\n## Stage 6 — Window-level Interaction (base / loose=0.12 / short=14d)\n")
    lines.append("| window | base_ann | loose_ann | short_ann | base_DD | loose_DD | short_DD | b_halts | L_halts | S_halts |\n")
    lines.append("|--------|----------|-----------|-----------|---------|----------|----------|---------|---------|----------|\n")
    for w in interact:
        lines.append(f"| {w['window']} | {w['base_ann']:+.1f}% | {w['loose_ann']:+.1f}% | {w['short_ann']:+.1f}% | {w['base_dd']:+.1f}% | {w['loose_dd']:+.1f}% | {w['short_dd']:+.1f}% | {w['base_halts']} | {w['loose_halts']} | {w['short_halts']} |\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)


if __name__ == "__main__":
    main()
