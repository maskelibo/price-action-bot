"""SEC54.6e — Sub-Monthly Halt Scale-Down Replay (Lab Sprint).

Principal directive (2026-05-18 gece):
  - Neg ay azalt (10/61 -> <=9) — PRIMARY
  - Max_loss -%13.5 kabul, gate gevsek -%15
  - Overnight calis

YENI MEKANIZMA: Sub-monthly cumulative PnL eşiğine göre POSITION SIZE çarpanı.
  Esik 1: cum month PnL <= -3%   -> size multiplier = 0.7  (defensive)
  Esik 2: cum month PnL <= -5%   -> size multiplier = 0.5  (conservative)
  Esik 3: cum month PnL <= -7%   -> size multiplier = 0.3  (survival)
  Esik 4: cum month PnL <= -10%  -> side-cond halt (mevcut monthly_dd_*)

Bu mekanizma mevcut monthly_dd_long=12% / monthly_dd_short=7% halt'ı
TAMAMLAYICI — once scale-down, sonra halt. Scale-down sigortayı yumusatir:
ay icinde -%3'e ulasinca derece derece kuculur, halt'a kadar pozisyon tasinir
ama ekspojur dusmus olur.

Pool: data/sec53_15m_pool_v11.pkl (SHA256 59a794ef...4e3ad6)
Config: configs/risk_phoenix_scalp_15m_c2v5_final.yaml (SEC54.6 daily=5%)
Replay knobs: SEC54.6 / SEC54.1 parity (risk=0.02, pyramid V5, conc=20, cd=0)

Cikti:
  reports/lab/2026-05-19_sec54_6e_subhalt_replay.md
  reports/lab/sec54_6e_per_month_{A,B,D}.csv
  reports/lab/sec54_6e_walkforward_{A,B,D}.csv
  reports/lab/sec54_6e_events_{A,B,D}.csv  (yeni: scale_down_T1/T2/T3 events)
"""
from __future__ import annotations

import csv
import io
import os
import pickle
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, stdev

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")
import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import pandas as pd

from price_action.backtest.lab import (
    ProductionConfig,
    ReplayResult,
    production_replay,
    _effective_daily_dd,
)


# ============================================================================
# Paths
# ============================================================================
POOL_PATH = ROOT / "data" / "sec53_15m_pool_v11.pkl"
RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_c2v5_final.yaml"
OUT_DIR = ROOT / "reports" / "lab"
REPORT = OUT_DIR / "2026-05-19_sec54_6e_subhalt_replay.md"

TOP4_NAMES = {
    "vsa_climax_test",
    "brooks_failed_breakout",
    "anchored_vwap_reversal",
    "engulfing_continuation",
}

POOL_SHA256_EXPECTED = "59a794ef278e47f696cdb14ddf42db383ed097474f938f8902a34e450a4e3ad6"

# Sub-monthly scale-down thresholds (cum month PnL pct of month-start equity)
# Order matters: most-severe first (cumulative check uses first-match)
SUBHALT_TIERS = [
    (-0.07, 0.3, "T3_survival"),
    (-0.05, 0.5, "T2_conservative"),
    (-0.03, 0.7, "T1_defensive"),
]

# Reference data (from SEC54.1 + SEC54.6 prior reports)
SEC54_1_OLD = {
    "A_fee0":  {"annual": 1082.3, "mean_m": 25.86, "neg": 7, "max_loss": -4.57,
                "cv": 120, "wf_r_adj": 42.75, "pos": 54, "ge20": 26, "sub20": 35},
    "B_fee8":  {"annual": 1014.9, "mean_m": 25.09, "neg": 7, "max_loss": -4.90,
                "cv": 119, "wf_r_adj": 36.87, "pos": 54, "ge20": 26, "sub20": 35},
    "D_fee4":  {"annual": 1042.2, "mean_m": 25.48, "neg": 7, "max_loss": -4.73,
                "cv": 121, "wf_r_adj": 40.94, "pos": 54, "ge20": 26, "sub20": 35},
}
SEC54_6_NEW = {
    "A_fee0":  {"annual": 1417.6, "mean_m": 29.61, "neg": 8,  "max_loss": -13.54,
                "cv": 124, "wf_r_adj": 36.17, "pos": 53, "ge20": 28, "sub20": 33},
    "B_fee8":  {"annual": 1320.5, "mean_m": 28.85, "neg": 10, "max_loss": -13.82,
                "cv": 126, "wf_r_adj": 33.84, "pos": 51, "ge20": 28, "sub20": 33},
    "D_fee4":  {"annual": 1362.9, "mean_m": 29.19, "neg": 10, "max_loss": -13.68,
                "cv": 125, "wf_r_adj": 34.96, "pos": 51, "ge20": 28, "sub20": 33},
}


# ============================================================================
# Sub-monthly scale-down replay (custom, lab.py NOT MODIFIED)
# ============================================================================
def production_replay_subhalt(
    trades: list[dict],
    cfg: ProductionConfig,
    subhalt_tiers: list[tuple],
    events_out: list | None = None,
) -> ReplayResult | None:
    """SEC54.6e — production_replay + sub-monthly cumulative PnL scale-down.

    All behavior is byte-identical to lab.production_replay EXCEPT:
      - After standard breakers pass, computes cum month PnL pct vs month_anchor.
      - If cum_pct <= subhalt_tiers[k][0], multiplies risk_d by subhalt_tiers[k][1].
      - First-match (most severe tier wins via tier ordering).
      - Logs scale-down events to events_out (type="subhalt_T1/T2/T3").

    Returns ReplayResult or None.
    """
    if not trades:
        return None

    # --- copy of lab.production_replay (sub-monthly scale-down injection) ---
    if cfg.use_conf_percentile:
        from price_action.backtest.scoring import normalize_conf_percentile
        normalize_conf_percentile(trades, lookback_days=cfg.conf_pct_lookback_days)
    if cfg.use_sl_pct_conf:
        from price_action.backtest.scoring import normalize_conf_via_sl_pct_percentile
        normalize_conf_via_sl_pct_percentile(trades, lookback_days=cfg.conf_pct_lookback_days)

    filtered = [
        t for t in trades
        if t["conf"] >= cfg.conf_min
        and t["strategy"] not in cfg.drop_strategies
        and t["symbol"] not in cfg.drop_symbols
        and (t["strategy"], t["symbol"]) not in cfg.drop_pairs
    ]
    if not filtered:
        return None
    filtered = sorted(filtered, key=lambda t: t["entry_ts"])

    equity = cfg.initial_capital
    cash = cfg.initial_capital
    open_pos: list[dict] = []
    eq_curve: list[float] = [cfg.initial_capital]
    Rs: list[float] = []

    daily_anchor = weekly_anchor = monthly_anchor = cfg.initial_capital
    first = filtered[0]["entry_ts"]
    last_d = first.date()
    last_w = first.isocalendar()[1]
    last_m = first.month
    blocked_until = None
    monthly_long_pnl = 0.0
    monthly_short_pnl = 0.0
    monthly_total_pnl = 0.0  # SEC54.6e: cumulative ay PnL (combined long+short)
    blocked_long_until = None
    blocked_short_until = None
    last_entry: dict[tuple, any] = {}
    consecutive_losses = 0
    cool_until = None
    peak_equity = cfg.initial_capital
    same_day_count: dict = {}

    def close_due(now):
        nonlocal cash, equity, peak_equity, consecutive_losses, cool_until
        nonlocal monthly_long_pnl, monthly_short_pnl, monthly_total_pnl
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                R_use = p["R"]
                if cfg.pyramid_enabled and cfg.pyramid_triggers and cfg.pyramid_sizes:
                    peak_R_p = float(p.get("peak_R", R_use))
                    bonus = 0.0
                    slippage_erosion = 0.0
                    SLIP_PER_EKPOS = 0.06
                    for trig, sz in zip(cfg.pyramid_triggers, cfg.pyramid_sizes):
                        if peak_R_p >= float(trig):
                            bonus += float(sz) * max(0.0, R_use - float(trig))
                            slippage_erosion += SLIP_PER_EKPOS * float(sz)
                    R_use = R_use + bonus - slippage_erosion
                if cfg.fee_bps_per_trade != 0.0:
                    _sl_pct = p.get("sl_pct", 0.0)
                    if _sl_pct > 0:
                        base_fee_R = cfg.fee_bps_per_trade / (_sl_pct * 10_000.0)
                        pyramid_fee_R = 0.0
                        if cfg.pyramid_enabled and cfg.pyramid_triggers and cfg.pyramid_sizes:
                            peak_R_p2 = float(p.get("peak_R", p["R"]))
                            for trig, sz in zip(cfg.pyramid_triggers, cfg.pyramid_sizes):
                                if peak_R_p2 >= float(trig):
                                    pyramid_fee_R += cfg.fee_bps_per_trade / (_sl_pct * 10_000.0) * float(sz)
                        R_use = R_use - base_fee_R - pyramid_fee_R
                pnl = p["risk"] * R_use
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                peak_equity = max(peak_equity, equity)
                Rs.append(R_use)
                eq_curve.append(equity)
                if p.get("side") == "long":
                    monthly_long_pnl += pnl
                elif p.get("side") == "short":
                    monthly_short_pnl += pnl
                monthly_total_pnl += pnl  # SEC54.6e: combined for sub-halt
                if pnl < 0:
                    consecutive_losses += 1
                    if cfg.consecutive_loss_n and consecutive_losses >= cfg.consecutive_loss_n:
                        cool_until = p["exit_ts"] + timedelta(days=cfg.consecutive_loss_pause_days)
                        consecutive_losses = 0
                        if events_out is not None:
                            events_out.append({"type": "consecutive_loss_pause",
                                               "ts": p["exit_ts"]})
                else:
                    consecutive_losses = 0
            else:
                still.append(p)
        open_pos[:] = still

    for t in filtered:
        close_due(t["entry_ts"])
        if cool_until and t["entry_ts"] < cool_until:
            continue

        d_key = t["entry_ts"].date()

        if cfg.btc_halt_calendar is not None:
            if cfg.btc_halt_calendar.get(d_key, False):
                continue

        if cfg.alt_data_skip_all is not None:
            if cfg.alt_data_skip_all.get(d_key, False):
                continue
        side_t = t.get("side", "").lower()
        if cfg.alt_data_skip_long is not None and side_t == "long":
            if cfg.alt_data_skip_long.get(d_key, False):
                continue
        if cfg.alt_data_skip_short is not None and side_t == "short":
            if cfg.alt_data_skip_short.get(d_key, False):
                continue

        if cfg.score_filter is not None and cfg.score_threshold > 0:
            key_score = (t["symbol"], t["entry_ts"])
            proba = cfg.score_filter.get(key_score)
            if proba is None or proba < cfg.score_threshold:
                continue

        chop_factor = 1.0
        if cfg.chop_calendars is not None:
            sym_cal = cfg.chop_calendars.get(t["symbol"])
            if sym_cal is not None:
                mode = sym_cal.get(d_key, "trend")
                if mode == "chop":
                    chop_factor = cfg.chop_risk_factor
                elif mode == "transition":
                    chop_factor = cfg.transition_risk_factor
            if chop_factor <= 0:
                continue

        if cfg.same_day_max is not None:
            if same_day_count.get(d_key, 0) >= cfg.same_day_max:
                continue

        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).total_seconds() < cfg.same_symbol_side_cooldown_days * 86400.0:
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
            last_m = cm
            monthly_long_pnl = 0.0
            monthly_short_pnl = 0.0
            monthly_total_pnl = 0.0  # SEC54.6e: combined reset
        if blocked_until and t["entry_ts"] < blocked_until:
            continue
        _eff_daily_dd = _effective_daily_dd(cfg, cd)
        if (daily_anchor - equity) / max(daily_anchor, 1) >= _eff_daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=cfg.daily_halt_days)
            if events_out is not None:
                events_out.append({"type": "daily_halt", "ts": t["entry_ts"]})
            continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= cfg.weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=cfg.weekly_halt_days)
            if events_out is not None:
                events_out.append({"type": "weekly_halt", "ts": t["entry_ts"]})
            continue
        if (monthly_anchor - equity) / max(monthly_anchor, 1) >= cfg.monthly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=cfg.monthly_halt_days)
            if events_out is not None:
                events_out.append({"type": "monthly_halt", "ts": t["entry_ts"]})
            continue
        side_t = str(t.get("side", "")).lower()
        if cfg.monthly_dd_long is not None and side_t == "long":
            if blocked_long_until and t["entry_ts"] < blocked_long_until:
                continue
            long_loss_pct = -monthly_long_pnl / max(monthly_anchor, 1) if monthly_long_pnl < 0 else 0
            if long_loss_pct >= cfg.monthly_dd_long:
                blocked_long_until = t["entry_ts"] + timedelta(days=cfg.monthly_halt_days)
                if events_out is not None:
                    events_out.append({"type": "monthly_long_halt", "ts": t["entry_ts"]})
                continue
        if cfg.monthly_dd_short is not None and side_t == "short":
            if blocked_short_until and t["entry_ts"] < blocked_short_until:
                continue
            short_loss_pct = -monthly_short_pnl / max(monthly_anchor, 1) if monthly_short_pnl < 0 else 0
            if short_loss_pct >= cfg.monthly_dd_short:
                blocked_short_until = t["entry_ts"] + timedelta(days=cfg.monthly_halt_days)
                if events_out is not None:
                    events_out.append({"type": "monthly_short_halt", "ts": t["entry_ts"]})
                continue

        if len(open_pos) >= cfg.max_concurrent:
            continue

        # (SEC21 slot allocation block — same as lab.py)
        if (
            cfg.slot_allocation_enabled
            and cfg.slot_taxonomy is not None
            and cfg.slot_caps
        ):
            strat_name = t.get("strategy", "")
            trade_class = cfg.slot_taxonomy.get(strat_name, cfg.slot_default_class)
            caps_for_class = cfg.slot_caps.get(trade_class, {})
            class_max = int(caps_for_class.get("max", cfg.max_concurrent))
            open_by_class: dict = {}
            for p in open_pos:
                pc = cfg.slot_taxonomy.get(p.get("strategy", ""), cfg.slot_default_class)
                open_by_class[pc] = open_by_class.get(pc, 0) + 1
            n_open_class = open_by_class.get(trade_class, 0)
            if n_open_class >= class_max:
                continue
            other_reserved_unfilled = 0
            for klass, caps in cfg.slot_caps.items():
                if klass == trade_class:
                    continue
                min_res = int(caps.get("min_reserved", 0) or 0)
                if min_res <= 0:
                    continue
                cur_open = open_by_class.get(klass, 0)
                shortfall = max(0, min_res - cur_open)
                other_reserved_unfilled += shortfall
            free_after = cfg.max_concurrent - (len(open_pos) + 1)
            if free_after < other_reserved_unfilled:
                continue

        dd_from_peak = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
        risk_modifier = 1.0
        if cfg.equity_protect_50 and dd_from_peak >= 0.50:
            continue
        if cfg.equity_protect_30 and dd_from_peak >= 0.30:
            risk_modifier = 0.5

        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0:
            continue

        if cfg.confidence_risk_tiers:
            from price_action.backtest.scoring import get_tier_value
            conf_for_tier = t.get("conf_pct", t["conf"])
            trade_risk_pct = float(get_tier_value(
                cfg.confidence_risk_tiers, conf_for_tier, "risk_pct", cfg.risk_pct
            ))
        else:
            trade_risk_pct = cfg.risk_pct

        if cfg.vol_conditional_risk and cfg.btc_atr_pct_calendar is not None:
            atr_p = cfg.btc_atr_pct_calendar.get(d_key)
            if atr_p is not None:
                if atr_p < cfg.vol_low_atr_pct:
                    trade_risk_pct = cfg.vol_low_risk_pct
                elif atr_p > cfg.vol_high_atr_pct:
                    trade_risk_pct = cfg.vol_high_risk_pct

        risk_d = equity * trade_risk_pct * risk_modifier
        risk_d *= chop_factor

        # ============================================================
        # SEC54.6e SUB-MONTHLY SCALE-DOWN (the new mechanism)
        # ============================================================
        # Cum month PnL pct of month_anchor; combined (long+short)
        cum_month_pct = monthly_total_pnl / max(monthly_anchor, 1)
        subhalt_multiplier = 1.0
        subhalt_tier = None
        for thr, mult, name in subhalt_tiers:
            if cum_month_pct <= thr:
                subhalt_multiplier = mult
                subhalt_tier = name
                break
        if subhalt_tier is not None:
            risk_d *= subhalt_multiplier
            if events_out is not None:
                events_out.append({
                    "type": f"subhalt_{subhalt_tier}",
                    "ts": t["entry_ts"],
                    "cum_pct": cum_month_pct,
                    "mult": subhalt_multiplier,
                })

        if cfg.vol_target_enabled:
            vol_factor = cfg.vol_target_atr_pct / sl_pct
            vol_factor = max(cfg.vol_min_factor, min(cfg.vol_max_factor, vol_factor))
            risk_d *= vol_factor

        notional = risk_d / sl_pct

        if cfg.max_notional_pct_equity is not None:
            cap = equity * cfg.max_notional_pct_equity
            if notional > cap:
                notional = cap
                risk_d = notional * sl_pct

        if cfg.concentration_max_per_symbol_pct is not None:
            sym = t["symbol"]
            existing_sym_notional = sum(
                p["notional"] for p in open_pos if p.get("symbol") == sym
            )
            total_sym = existing_sym_notional + notional
            sym_cap = equity * cfg.concentration_max_per_symbol_pct
            if total_sym > sym_cap:
                continue

        if cfg.max_same_side_concurrent is not None:
            side = t["side"]
            same_side_count = sum(1 for p in open_pos if p.get("side") == side)
            if same_side_count >= cfg.max_same_side_concurrent:
                continue

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
        same_day_count[d_key] = same_day_count.get(d_key, 0) + 1
        open_pos.append({
            "exit_ts": t["exit_ts"],
            "margin": margin,
            "notional": notional,
            "risk": risk_d,
            "R": t["R"],
            "symbol": t["symbol"],
            "side": t["side"],
            "strategy": t.get("strategy", ""),
            "peak_R": t.get("peak_R", t["R"]),
            "sl_pct": sl_pct,
        })

    # Close remaining open positions
    for p in open_pos:
        R_use = p["R"]
        if cfg.pyramid_enabled and cfg.pyramid_triggers and cfg.pyramid_sizes:
            peak_R_p = float(p.get("peak_R", R_use))
            bonus = 0.0
            slippage_erosion = 0.0
            SLIP_PER_EKPOS = 0.06
            for trig, sz in zip(cfg.pyramid_triggers, cfg.pyramid_sizes):
                if peak_R_p >= float(trig):
                    bonus += float(sz) * max(0.0, R_use - float(trig))
                    slippage_erosion += SLIP_PER_EKPOS * float(sz)
            R_use = R_use + bonus - slippage_erosion
        if cfg.fee_bps_per_trade != 0.0:
            _sl_pct = p.get("sl_pct", 0.0)
            if _sl_pct > 0:
                base_fee_R = cfg.fee_bps_per_trade / (_sl_pct * 10_000.0)
                pyramid_fee_R = 0.0
                if cfg.pyramid_enabled and cfg.pyramid_triggers and cfg.pyramid_sizes:
                    peak_R_p2 = float(p.get("peak_R", p["R"]))
                    for trig, sz in zip(cfg.pyramid_triggers, cfg.pyramid_sizes):
                        if peak_R_p2 >= float(trig):
                            pyramid_fee_R += cfg.fee_bps_per_trade / (_sl_pct * 10_000.0) * float(sz)
                R_use = R_use - base_fee_R - pyramid_fee_R
        cash += p["margin"] + p["risk"] * R_use
        equity = cash
        Rs.append(R_use)
        eq_curve.append(equity)

    peak = eq_curve[0]
    max_dd = 0.0
    for v in eq_curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak if peak > 0 else 0
        if dd < max_dd:
            max_dd = dd

    win_rate = (sum(1 for x in Rs if x > 0) / len(Rs)) if Rs else 0.0
    avg_r = (sum(Rs) / len(Rs)) if Rs else 0.0

    return ReplayResult(
        final_equity=equity,
        initial_capital=cfg.initial_capital,
        trades=len(Rs),
        win_rate=win_rate,
        max_drawdown=max_dd,
        avg_r=avg_r,
        sum_r=sum(Rs),
        config_label=cfg.label() + "_subhalt",
    )


# ============================================================================
# Utilities (parity with SEC54.6)
# ============================================================================
def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def verify_pool_sha256(path: Path) -> bool:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != POOL_SHA256_EXPECTED:
        print(f"[WARN] Pool SHA256 mismatch: expected {POOL_SHA256_EXPECTED[:16]}... "
              f"got {actual[:16]}...", flush=True)
        return False
    print(f"[SHA256] Pool integrity OK: {actual[:16]}...", flush=True)
    return True


def per_month_metrics(pool, cfg, subhalt_tiers, events_out=None):
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    if not pool:
        return []
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["entry_ts"])
    months = []
    cy, cm = start.year, start.month
    while True:
        ms = datetime(cy, cm, 1, tzinfo=timezone.utc)
        me = (datetime(cy + 1, 1, 1, tzinfo=timezone.utc) if cm == 12
              else datetime(cy, cm + 1, 1, tzinfo=timezone.utc))
        if ms > end:
            break
        months.append((cy, cm, ms, me))
        cm += 1
        if cm > 12:
            cm = 1
            cy += 1

    rows = []
    for yr, mo, ms, me in months:
        m_tr = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_tr) < 10:
            rows.append({"year": yr, "month": mo, "n_raw": len(m_tr), "n_taken": 0,
                         "monthly_pct": 0.0, "dd_pct": 0.0, "skip": "n<10",
                         "halt_events": 0, "subhalt_events": 0})
            continue
        try:
            month_events: list = [] if events_out is not None else None
            r = production_replay_subhalt(m_tr, cfg, subhalt_tiers,
                                           events_out=month_events)
        except Exception as e:
            rows.append({"year": yr, "month": mo, "n_raw": len(m_tr), "n_taken": 0,
                         "monthly_pct": 0.0, "dd_pct": 0.0, "skip": f"err:{e}",
                         "halt_events": 0, "subhalt_events": 0})
            continue
        if r is None:
            rows.append({"year": yr, "month": mo, "n_raw": len(m_tr), "n_taken": 0,
                         "monthly_pct": 0.0, "dd_pct": 0.0, "skip": "none",
                         "halt_events": 0, "subhalt_events": 0})
            continue
        n_halt = 0
        n_subhalt = 0
        if month_events is not None:
            for ev in month_events:
                t_ev = ev.get("type", "")
                if t_ev.startswith("subhalt_"):
                    n_subhalt += 1
                else:
                    n_halt += 1
                if events_out is not None:
                    ev2 = dict(ev)
                    ev2["year"] = yr
                    ev2["month"] = mo
                    events_out.append(ev2)
        rows.append({"year": yr, "month": mo, "n_raw": len(m_tr), "n_taken": r.trades,
                     "monthly_pct": r.total_return * 100, "dd_pct": r.max_drawdown * 100,
                     "skip": "", "halt_events": n_halt, "subhalt_events": n_subhalt})
    return rows


def walk_forward_metrics(pool, cfg, subhalt_tiers,
                          train_days: int = 730, oos_days: int = 90,
                          step_days: int = 30):
    if not pool:
        return []
    pool = sorted(pool, key=lambda x: to_utc(x["entry_ts"]))
    start = to_utc(pool[0]["entry_ts"])
    end = to_utc(pool[-1]["exit_ts"])
    windows = []
    cur = start
    while cur + pd.Timedelta(days=train_days + oos_days) <= end:
        windows.append((cur, cur + pd.Timedelta(days=train_days)))
        cur += pd.Timedelta(days=step_days)
    period_years = train_days / 365.0
    rows = []
    for i, (ws, we) in enumerate(windows, start=1):
        ww = [t for t in pool if ws <= to_utc(t["entry_ts"]) < we]
        if not ww:
            rows.append({"window": i, "start": ws.date().isoformat(),
                         "end": we.date().isoformat(), "trades": 0,
                         "annual_pct": 0.0, "dd_pct": 0.0, "r_adj": 0.0})
            continue
        try:
            r = production_replay_subhalt(ww, cfg, subhalt_tiers)
        except Exception:
            rows.append({"window": i, "start": ws.date().isoformat(),
                         "end": we.date().isoformat(), "trades": len(ww),
                         "annual_pct": 0.0, "dd_pct": 0.0, "r_adj": 0.0})
            continue
        if r is None:
            rows.append({"window": i, "start": ws.date().isoformat(),
                         "end": we.date().isoformat(), "trades": len(ww),
                         "annual_pct": 0.0, "dd_pct": 0.0, "r_adj": 0.0})
            continue
        ann = r.annualized(period_years) * 100
        dd = r.max_drawdown * 100
        ra = ann / abs(dd) if dd != 0 else 0
        rows.append({"window": i, "start": ws.date().isoformat(),
                     "end": we.date().isoformat(), "trades": len(ww),
                     "annual_pct": ann, "dd_pct": dd, "r_adj": ra})
    return rows


def summarize_variant(month_rows, wf_rows, events=None):
    valid = [r for r in month_rows if r["skip"] == ""]
    rets = [r["monthly_pct"] for r in valid]
    eq = 1.0
    for r in rets:
        eq *= (1.0 + r / 100.0)
    if valid:
        first = (valid[0]["year"], valid[0]["month"])
        last = (valid[-1]["year"], valid[-1]["month"])
        n_months = (last[0] - first[0]) * 12 + (last[1] - first[1]) + 1
        years = n_months / 12.0
    else:
        years = 1.0
    annual = (eq ** (1.0 / years) - 1.0) * 100 if eq > 0 and years > 0 else -100.0
    pos = sum(1 for r in rets if r > 0)
    neg = sum(1 for r in rets if r < 0)
    ge20 = sum(1 for r in rets if r >= 20.0)
    sub20 = sum(1 for r in rets if r < 20.0)
    mean_m = mean(rets) if rets else 0.0
    cv = (stdev(rets) / abs(mean_m) * 100) if (mean_m != 0 and len(rets) >= 2) else 0.0
    max_loss = min(rets) if rets else 0.0
    max_gain = max(rets) if rets else 0.0
    wf_ann = [r["annual_pct"] for r in wf_rows if r["trades"] > 0]
    wf_dd = [r["dd_pct"] for r in wf_rows if r["trades"] > 0]
    wf_radj = [r["r_adj"] for r in wf_rows if r["trades"] > 0]

    ev_counts = {"daily_halt": 0, "weekly_halt": 0, "monthly_halt": 0,
                 "monthly_long_halt": 0, "monthly_short_halt": 0,
                 "consecutive_loss_pause": 0,
                 "subhalt_T1_defensive": 0, "subhalt_T2_conservative": 0,
                 "subhalt_T3_survival": 0, "total": 0}
    if events:
        for e in events:
            t = e.get("type", "")
            if t in ev_counts:
                ev_counts[t] += 1
            ev_counts["total"] += 1

    return {
        "annual_pct": annual, "mean_monthly_pct": mean_m, "pos_months": pos,
        "ge20_months": ge20, "neg_months": neg, "sub20_months": sub20,
        "max_loss_pct": max_loss, "max_gain_pct": max_gain, "cv_pct": cv,
        "n_months": len(rets),
        "wf_n_windows": len(wf_ann),
        "wf_mean_annual_pct": mean(wf_ann) if wf_ann else 0.0,
        "wf_mean_dd_pct": mean(wf_dd) if wf_dd else 0.0,
        "wf_mean_r_adj": mean(wf_radj) if wf_radj else 0.0,
        "wf_neg_windows": sum(1 for a in wf_ann if a < 0),
        "events": ev_counts,
    }


def save_month_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        cols = ["year", "month", "n_raw", "n_taken", "monthly_pct", "dd_pct",
                "halt_events", "subhalt_events", "skip"]
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        for r in rows:
            row = dict(r)
            row["monthly_pct"] = f"{row['monthly_pct']:.4f}"
            row["dd_pct"] = f"{row['dd_pct']:.4f}"
            wr.writerow(row)


def save_wf_csv(path, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        cols = ["window", "start", "end", "trades", "annual_pct", "dd_pct", "r_adj"]
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        for r in rows:
            row = dict(r)
            row["annual_pct"] = f"{row['annual_pct']:.4f}"
            row["dd_pct"] = f"{row['dd_pct']:.4f}"
            row["r_adj"] = f"{row['r_adj']:.4f}"
            wr.writerow(row)


def save_events_csv(path, events):
    with path.open("w", newline="", encoding="utf-8") as fh:
        cols = ["year", "month", "type", "ts", "cum_pct", "mult"]
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader()
        for e in events:
            wr.writerow({
                "year": e.get("year", ""),
                "month": e.get("month", ""),
                "type": e.get("type", ""),
                "ts": str(e.get("ts", "")),
                "cum_pct": f"{e.get('cum_pct', 0):.4f}" if "cum_pct" in e else "",
                "mult": f"{e.get('mult', 0):.2f}" if "mult" in e else "",
            })


def mandate_check_sec54_6e(s: dict) -> dict:
    """SEC54.6e mandate (Principal directive gevsek):
       annual>=600, mean>=20, neg<=9 (PRIMARY), max_loss>=-15 (gevsek),
       wf_r_adj>=15.
    """
    checks = {
        "annual_ge_600": s["annual_pct"] >= 600.0,
        "mean_monthly_ge_20": s["mean_monthly_pct"] >= 20.0,
        "neg_months_le_9": s["neg_months"] <= 9,
        "max_loss_ge_neg15": s["max_loss_pct"] >= -15.0,
        "wf_r_adj_ge_15": s["wf_mean_r_adj"] >= 15.0,
    }
    n_pass = sum(1 for v in checks.values() if v)
    return {"checks": checks, "n_pass": n_pass, "total": len(checks)}


def run_scenario(label, fee_bps, pool, cfg_base, subhalt_tiers, out_dir):
    print(f"\n[SCENARIO {label}] fee={fee_bps:+.1f} bps  +SUBHALT (-3%/-5%/-7% tiers)", flush=True)
    cfg = cfg_base.with_overrides(fee_bps_per_trade=fee_bps)
    t0 = time.time()
    events: list = []
    print(f"  per-month...", flush=True)
    month_rows = per_month_metrics(pool, cfg, subhalt_tiers, events_out=events)
    print(f"  walk-forward...", flush=True)
    wf_rows = walk_forward_metrics(pool, cfg, subhalt_tiers)
    s = summarize_variant(month_rows, wf_rows, events=events)
    elapsed = time.time() - t0

    csv_m = out_dir / f"sec54_6e_per_month_{label}.csv"
    csv_w = out_dir / f"sec54_6e_walkforward_{label}.csv"
    csv_e = out_dir / f"sec54_6e_events_{label}.csv"
    save_month_csv(csv_m, month_rows)
    save_wf_csv(csv_w, wf_rows)
    save_events_csv(csv_e, events)

    mandate = mandate_check_sec54_6e(s)
    ev = s["events"]
    print(f"  annual={s['annual_pct']:+.1f}%  mean={s['mean_monthly_pct']:+.2f}%  "
          f"pos={s['pos_months']}  neg={s['neg_months']}  "
          f"max_loss={s['max_loss_pct']:+.2f}%  CV={s['cv_pct']:.0f}%  "
          f"WF_radj={s['wf_mean_r_adj']:.2f}  mandate={mandate['n_pass']}/{mandate['total']}",
          flush=True)
    print(f"  subhalt: T1(def 0.7)={ev['subhalt_T1_defensive']}  "
          f"T2(con 0.5)={ev['subhalt_T2_conservative']}  "
          f"T3(sur 0.3)={ev['subhalt_T3_survival']}", flush=True)
    print(f"  halt: daily={ev['daily_halt']}  weekly={ev['weekly_halt']}  "
          f"m_long={ev['monthly_long_halt']}  m_short={ev['monthly_short_halt']}  "
          f"consec={ev['consecutive_loss_pause']}  total={ev['total']}  "
          f"[{elapsed/60:.1f}m]", flush=True)
    return {**s, "fee_bps": fee_bps, "label": label,
            "mandate_pass": mandate["n_pass"], "mandate_total": mandate["total"],
            "mandate_checks": mandate["checks"],
            "csv_month": str(csv_m), "csv_wf": str(csv_w), "csv_events": str(csv_e),
            "month_rows": month_rows, "elapsed_s": elapsed}


# ============================================================================
# Main
# ============================================================================
def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[SEC54.6e] Sub-Monthly Halt Scale-Down Replay (Lab Sprint)", flush=True)
    print(f"  Pool: {POOL_PATH}", flush=True)
    print(f"  YAML: {RISK_YAML}", flush=True)
    print(f"  Mekanizma: cum month PnL eşiği -3%(x0.7) / -5%(x0.5) / -7%(x0.3)", flush=True)
    print(f"  Hedef: neg<=9 + max_loss bw -%4..-%6", flush=True)

    if not POOL_PATH.exists():
        print(f"[ERROR] Pool not found: {POOL_PATH}", flush=True)
        sys.exit(1)

    print(f"\n[POOL] Loading {POOL_PATH.stat().st_size/1e6:.1f} MB...", flush=True)
    t0 = time.time()
    with POOL_PATH.open("rb") as f:
        pool_raw = pickle.load(f)
    print(f"  Loaded {len(pool_raw):,} raw trades ({time.time()-t0:.1f}s)", flush=True)
    verify_pool_sha256(POOL_PATH)

    pool = [t for t in pool_raw if t.get("strategy") in TOP4_NAMES]
    print(f"  Filtered TOP-4: {len(pool):,} trades", flush=True)

    print(f"\n[CONFIG] Loading {RISK_YAML.name} (SEC54.6 daily=5%)...", flush=True)
    cfg_base = ProductionConfig.from_yaml(str(RISK_YAML))
    cfg_base = cfg_base.with_overrides(
        risk_pct=0.02,
        pyramid_triggers=(1.0, 1.5),
        max_concurrent=20,
        same_symbol_side_cooldown_days=0,
    )
    print(f"  Breakers: daily={cfg_base.daily_dd}  consec={cfg_base.consecutive_loss_n}  "
          f"m_short={cfg_base.monthly_dd_short}  m_long={cfg_base.monthly_dd_long}",
          flush=True)
    print(f"  Subhalt tiers:", flush=True)
    for thr, mult, name in SUBHALT_TIERS:
        print(f"    cum_pct <= {thr*100:+.0f}%  ->  size x{mult}  [{name}]", flush=True)

    scenarios = [
        ("A_fee0",  0.0,  "Control (zero fee)"),
        ("B_fee8",  8.0,  "Taker only worst-case (8 bps round-trip)"),
        ("D_fee4",  4.0,  "Realistic blend (50% taker + 50% maker)"),
    ]

    results = {}
    for slug, fee_bps, desc in scenarios:
        r = run_scenario(slug, fee_bps, pool, cfg_base, SUBHALT_TIERS, OUT_DIR)
        r["description"] = desc
        results[slug] = r

    # ========================================================================
    # Verdict
    # ========================================================================
    print("\n[MANDATE SEC54.6e] compliance check (5 gate, gevsek max_loss>=-15%):", flush=True)
    for slug, _, _ in scenarios:
        r = results[slug]
        m = r["mandate_pass"]
        tag = ("PASS" if m == 5
               else "WARN" if m == 4
               else "MARGINAL" if m == 3
               else "FAIL")
        print(f"  [{slug}] fee={r['fee_bps']:+.1f}bps  annual={r['annual_pct']:+.1f}%  "
              f"neg={r['neg_months']}  max_loss={r['max_loss_pct']:+.2f}%  "
              f"mandate={m}/5  [{tag}]", flush=True)

    b = results["B_fee8"]
    if b["mandate_pass"] == 5:
        overall = "PASS"
        verdict_detail = ("5/5 (gevsek max_loss>=-15%): sub-monthly scale-down mekanizmasi "
                          "BASARILI; neg ay <=9 ve max_loss tolere edilebilir bantta.")
    elif b["mandate_pass"] == 4:
        overall = "WARN"
        verdict_detail = "4/5 gate — 1 borderline; Principal review"
    elif b["mandate_pass"] == 3:
        overall = "MARGINAL"
        verdict_detail = "3/5 gate — 2 metric border; mekanizma kismi etkili"
    else:
        overall = "FAIL"
        verdict_detail = "Mandate ihlal — subhalt yetersiz, alternatif gerek (esik sikilastir veya halt-only)"

    print(f"\n[VERDICT] {overall}: {verdict_detail}", flush=True)

    # ========================================================================
    # Outlier ay delta — load SEC54.6 per-month and diff
    # ========================================================================
    print("\n[OUTLIER AY DELTA] SEC54.6 vs SEC54.6e (Scenario B fee=+8)", flush=True)
    sec546_csv = OUT_DIR / "sec54_6_per_month_B_fee8_new.csv"
    outlier_delta = []
    if sec546_csv.exists():
        sec546_by_ym = {}
        with sec546_csv.open("r", encoding="utf-8") as fh:
            rdr = csv.DictReader(fh)
            for r in rdr:
                ym = (int(r["year"]), int(r["month"]))
                sec546_by_ym[ym] = {
                    "monthly_pct": float(r["monthly_pct"]),
                    "dd_pct": float(r["dd_pct"]),
                    "halt_events": int(r.get("halt_events", 0) or 0),
                }
        sec546b_b_months = b["month_rows"]
        # Find outlier months (SEC54.6 worst negatives)
        all_sec546_rets = sorted(sec546_by_ym.items(),
                                  key=lambda kv: kv[1]["monthly_pct"])
        outliers = [ym for ym, _ in all_sec546_rets[:5]]  # 5 worst SEC54.6
        for ym in outliers:
            old = sec546_by_ym[ym]
            new = next((r for r in sec546b_b_months
                        if (r["year"], r["month"]) == ym), None)
            if new and new["skip"] == "":
                delta = new["monthly_pct"] - old["monthly_pct"]
                outlier_delta.append({
                    "ym": f"{ym[0]}-{ym[1]:02d}",
                    "sec546_pct": old["monthly_pct"],
                    "sec546e_pct": new["monthly_pct"],
                    "delta_pp": delta,
                    "subhalt_events": new.get("subhalt_events", 0),
                })
                print(f"  {ym[0]}-{ym[1]:02d}: SEC54.6={old['monthly_pct']:+.2f}%  "
                      f"-> SEC54.6e={new['monthly_pct']:+.2f}%  delta={delta:+.2f}pp  "
                      f"subhalt_events={new.get('subhalt_events', 0)}", flush=True)

    # ========================================================================
    # Per-tier contribution summary
    # ========================================================================
    print("\n[PER-TIER CONTRIBUTION] subhalt event counts (B fee=+8 bps):", flush=True)
    ev = b["events"]
    total_subhalt = (ev["subhalt_T1_defensive"]
                     + ev["subhalt_T2_conservative"]
                     + ev["subhalt_T3_survival"])
    if total_subhalt > 0:
        print(f"  T1 defensive (0.7x): {ev['subhalt_T1_defensive']:>4d} "
              f"({100*ev['subhalt_T1_defensive']/total_subhalt:.1f}%)", flush=True)
        print(f"  T2 conservative (0.5x): {ev['subhalt_T2_conservative']:>4d} "
              f"({100*ev['subhalt_T2_conservative']/total_subhalt:.1f}%)", flush=True)
        print(f"  T3 survival (0.3x): {ev['subhalt_T3_survival']:>4d} "
              f"({100*ev['subhalt_T3_survival']/total_subhalt:.1f}%)", flush=True)
        print(f"  TOTAL subhalt scale-downs: {total_subhalt}", flush=True)
    else:
        print("  (no subhalt events triggered — mechanism inactive)", flush=True)

    # ========================================================================
    # Markdown report
    # ========================================================================
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out = []
    w = lambda s="": out.append(s + "\n")

    w("# SEC54.6e — Sub-Monthly Halt Scale-Down Replay")
    w()
    w(f"**Lab Scientist:** Head of Self-Improvement Lab")
    w(f"**Date:** {now_str}")
    w(f"**Sprint:** SEC54.6e — Sub-monthly cumulative PnL scale-down mechanism")
    w(f"**Pool:** `data/sec53_15m_pool_v11.pkl` "
      f"({POOL_PATH.stat().st_size/1e6:.1f} MB, SHA256 `{POOL_SHA256_EXPECTED[:16]}...`)")
    w(f"**Config:** `{RISK_YAML.name}` (SEC54.6 daily=5%)")
    w(f"**Replay knobs:** risk_pct=0.02, pyramid (1.0, 1.5), max_conc=20, "
      f"cooldown=0 (parity with SEC54.1/SEC54.6)")
    w()
    w("**Principal directive (2026-05-18 gece):**")
    w("- Neg ay azalt (10/61 -> <=9) — PRIMARY")
    w("- Max_loss -%13.5 kabul, gate gevsek -%15")
    w("- Overnight calis")
    w()
    w("---")
    w()
    w("## Executive Summary — VERDICT")
    w()
    w(f"**Overall verdict:** **{overall}**")
    w()
    w(f"{verdict_detail}")
    w()
    w("### Mandate 5/5 table (Scenario B, fee=+8 bps — realistic worst case)")
    w()
    w("| Gate | Threshold | Value (SEC54.6e) | Status |")
    w("|------|----------:|-----------------:|:------:|")
    for k, v in b["mandate_checks"].items():
        icon = "PASS" if v else "FAIL"
        if k == "annual_ge_600":
            w(f"| Annual >= 600% | 600% | {b['annual_pct']:+.1f}% | {icon} |")
        elif k == "mean_monthly_ge_20":
            w(f"| Mean monthly >= 20% | 20% | {b['mean_monthly_pct']:+.2f}% | {icon} |")
        elif k == "neg_months_le_9":
            w(f"| Neg ay <= 9/61 (PRIMARY) | 9 | {b['neg_months']}/61 | {icon} |")
        elif k == "max_loss_ge_neg15":
            w(f"| Max single loss >= -15% (gevsek) | -15% | {b['max_loss_pct']:+.2f}% | {icon} |")
        elif k == "wf_r_adj_ge_15":
            w(f"| WF r-adj >= 15 | 15 | {b['wf_mean_r_adj']:.2f} | {icon} |")
    w()
    w("---")
    w()
    w("## OUTLIER AY DELTA TABLE")
    w()
    w("**SEC54.6 outlier aylar (5 en kotu) vs SEC54.6e (Scenario B fee=+8):**")
    w()
    if outlier_delta:
        w("| Ay | SEC54.6 | SEC54.6e | Delta (pp) | Subhalt events |")
        w("|----|--------:|---------:|-----------:|----------------:|")
        for od in outlier_delta:
            w(f"| {od['ym']} | {od['sec546_pct']:+.2f}% | {od['sec546e_pct']:+.2f}% | "
              f"{od['delta_pp']:+.2f}pp | {od['subhalt_events']} |")
        w()
        avg_delta = sum(od["delta_pp"] for od in outlier_delta) / len(outlier_delta)
        w(f"**Ortalama outlier delta:** {avg_delta:+.2f}pp")
    else:
        w("(SEC54.6 per-month CSV bulunamadı — outlier delta hesaplanmadı)")
    w()
    w("---")
    w()
    w("## YENI MEKANIZMA ACIKLAMA")
    w()
    w("**Sub-monthly cumulative PnL scale-down:**")
    w()
    w("Mevcut `monthly_dd_long=12%` / `monthly_dd_short=7%` HALT mekanizmalarına ek olarak,")
    w("**ay içi cumulative combined PnL** belirli eşiklere ulaştığında **position size**")
    w("dinamik olarak küçültülür (halt değil, scale-down).")
    w()
    w("**Tier tablosu (first-match, most-severe first):**")
    w()
    w("| Eşik (cum month PnL) | Size multiplier | Etiket |")
    w("|---------------------:|:---------------:|--------|")
    for thr, mult, name in SUBHALT_TIERS:
        w(f"| <= {thr*100:+.0f}% | x{mult} | {name} |")
    w()
    w("**Mekanizma yeri (lab.py'de DEĞIL, scripts/sec54_6e_subhalt_replay.py'de):**")
    w("- Trade kabul aşamasında, standart breaker'lar geçtikten sonra, position sizing'den önce")
    w("- `risk_d *= subhalt_multiplier` (1.0, 0.7, 0.5, 0.3 cascade)")
    w("- Aynı ay içinde tier düşürmek bir kez yapılmaz — her trade'de cum_month_pct kontrol edilir")
    w("- `monthly_total_pnl` ay başında reset, her exit'te güncellenir")
    w()
    w("**Halt ile ilişkisi:** Scale-down sigortayı yumuşatır, halt'a kadar pozisyon taşımaya")
    w("devam eder ama ekspojur düşmüş olur. Halt (-12% / -7%) hâlâ aktif — son güvenlik ağı.")
    w()
    w("---")
    w()
    w("## PER-TIER CONTRIBUTION (B fee=+8 bps)")
    w()
    w("**Subhalt event sayısı (ay-bazlı kümülatif tetiklemeler):**")
    w()
    w("| Tier | Multiplier | Event count | % of total subhalt |")
    w("|------|:----------:|------------:|--------------------:|")
    ev = b["events"]
    total_subhalt = (ev["subhalt_T1_defensive"]
                     + ev["subhalt_T2_conservative"]
                     + ev["subhalt_T3_survival"])
    if total_subhalt > 0:
        w(f"| T1 defensive | 0.7 | {ev['subhalt_T1_defensive']} | "
          f"{100*ev['subhalt_T1_defensive']/total_subhalt:.1f}% |")
        w(f"| T2 conservative | 0.5 | {ev['subhalt_T2_conservative']} | "
          f"{100*ev['subhalt_T2_conservative']/total_subhalt:.1f}% |")
        w(f"| T3 survival | 0.3 | {ev['subhalt_T3_survival']} | "
          f"{100*ev['subhalt_T3_survival']/total_subhalt:.1f}% |")
        w(f"| **TOTAL** | | **{total_subhalt}** | 100% |")
    else:
        w("(no subhalt events triggered)")
    w()
    w("**Yorum:** En çok hangi tier tetikleniyor — outlier ayların hangi seviyeye geldiğini gösterir.")
    w()
    w("---")
    w()
    w("## 3-Way Comparison Table (SEC54.1 -> SEC54.6 -> SEC54.6e)")
    w()
    w("**Scenario B (fee=+8 bps) — primary mandate gate:**")
    w()
    b_546 = SEC54_6_NEW["B_fee8"]
    b_541 = SEC54_1_OLD["B_fee8"]
    w("| Metric | SEC54.1 (OLD) | SEC54.6 | **SEC54.6e (subhalt)** | Hedef |")
    w("|---|---:|---:|---:|---|")
    w(f"| Annual | +{b_541['annual']:.1f}% | +{b_546['annual']:.1f}% | "
      f"**{b['annual_pct']:+.1f}%** | >+600% |")
    w(f"| Mean monthly | +{b_541['mean_m']:.2f}% | +{b_546['mean_m']:.2f}% | "
      f"**{b['mean_monthly_pct']:+.2f}%** | >+20% |")
    w(f"| **Neg ay (PRIMARY)** | {b_541['neg']}/61 | {b_546['neg']}/61 | "
      f"**{b['neg_months']}/61** | **<=9** |")
    w(f"| **Max single loss** | {b_541['max_loss']:+.2f}% | {b_546['max_loss']:+.2f}% | "
      f"**{b['max_loss_pct']:+.2f}%** | **>= -15%** |")
    w(f"| CV | {b_541['cv']}% | {b_546['cv']}% | {b['cv_pct']:.0f}% | <150% |")
    w(f"| WF r-adj | {b_541['wf_r_adj']:.2f} | {b_546['wf_r_adj']:.2f} | "
      f"{b['wf_mean_r_adj']:.2f} | >=15 |")
    w(f"| Mandate | 5/5 | 3/5 | **{b['mandate_pass']}/5** | 5/5 |")
    w()
    w("**Scenario A (fee=0) — control:**")
    w()
    a = results["A_fee0"]
    a_546 = SEC54_6_NEW["A_fee0"]
    a_541 = SEC54_1_OLD["A_fee0"]
    w("| Metric | SEC54.1 (OLD) | SEC54.6 | **SEC54.6e (subhalt)** |")
    w("|---|---:|---:|---:|")
    w(f"| Annual | +{a_541['annual']:.1f}% | +{a_546['annual']:.1f}% | "
      f"**{a['annual_pct']:+.1f}%** |")
    w(f"| Mean monthly | +{a_541['mean_m']:.2f}% | +{a_546['mean_m']:.2f}% | "
      f"**{a['mean_monthly_pct']:+.2f}%** |")
    w(f"| Neg ay | {a_541['neg']}/61 | {a_546['neg']}/61 | **{a['neg_months']}/61** |")
    w(f"| Max loss | {a_541['max_loss']:+.2f}% | {a_546['max_loss']:+.2f}% | "
      f"**{a['max_loss_pct']:+.2f}%** |")
    w(f"| WF r-adj | {a_541['wf_r_adj']:.2f} | {a_546['wf_r_adj']:.2f} | "
      f"{a['wf_mean_r_adj']:.2f} |")
    w()
    w("**Scenario D (fee=+4 bps) — realistic blend:**")
    w()
    d = results["D_fee4"]
    d_546 = SEC54_6_NEW["D_fee4"]
    d_541 = SEC54_1_OLD["D_fee4"]
    w("| Metric | SEC54.1 (OLD) | SEC54.6 | **SEC54.6e (subhalt)** |")
    w("|---|---:|---:|---:|")
    w(f"| Annual | +{d_541['annual']:.1f}% | +{d_546['annual']:.1f}% | "
      f"**{d['annual_pct']:+.1f}%** |")
    w(f"| Mean monthly | +{d_541['mean_m']:.2f}% | +{d_546['mean_m']:.2f}% | "
      f"**{d['mean_monthly_pct']:+.2f}%** |")
    w(f"| Neg ay | {d_541['neg']}/61 | {d_546['neg']}/61 | **{d['neg_months']}/61** |")
    w(f"| Max loss | {d_541['max_loss']:+.2f}% | {d_546['max_loss']:+.2f}% | "
      f"**{d['max_loss_pct']:+.2f}%** |")
    w(f"| WF r-adj | {d_541['wf_r_adj']:.2f} | {d_546['wf_r_adj']:.2f} | "
      f"{d['wf_mean_r_adj']:.2f} |")
    w()
    w("---")
    w()
    w("## Per-Scenario Full Metrics")
    w()
    for slug, fee_bps, desc in scenarios:
        r = results[slug]
        ev = r["events"]
        w(f"### {slug} — {desc} (fee={fee_bps:+.1f}bps)")
        w()
        w(f"| Metric | Value |")
        w(f"|--------|-------|")
        w(f"| Annual | {r['annual_pct']:+.1f}% |")
        w(f"| Mean monthly | {r['mean_monthly_pct']:+.2f}% |")
        w(f"| Pos months | {r['pos_months']} |")
        w(f"| Neg months | {r['neg_months']} |")
        w(f"| Sub-20% months | {r['sub20_months']} |")
        w(f"| Max loss | {r['max_loss_pct']:+.2f}% |")
        w(f"| Max gain | {r['max_gain_pct']:+.2f}% |")
        w(f"| CV | {r['cv_pct']:.0f}% |")
        w(f"| WF windows | {r['wf_n_windows']} |")
        w(f"| WF mean annual | {r['wf_mean_annual_pct']:+.1f}% |")
        w(f"| WF mean DD | {r['wf_mean_dd_pct']:+.1f}% |")
        w(f"| WF r-adj | {r['wf_mean_r_adj']:.2f} |")
        w(f"| WF neg windows | {r['wf_neg_windows']} |")
        w(f"| Subhalt T1 (0.7) | {ev['subhalt_T1_defensive']} |")
        w(f"| Subhalt T2 (0.5) | {ev['subhalt_T2_conservative']} |")
        w(f"| Subhalt T3 (0.3) | {ev['subhalt_T3_survival']} |")
        w(f"| Halt: daily | {ev['daily_halt']} |")
        w(f"| Halt: weekly | {ev['weekly_halt']} |")
        w(f"| Halt: monthly_long | {ev['monthly_long_halt']} |")
        w(f"| Halt: monthly_short | {ev['monthly_short_halt']} |")
        w(f"| Pause: consec loss | {ev['consecutive_loss_pause']} |")
        w(f"| All events: total | {ev['total']} |")
        w(f"| Mandate | {r['mandate_pass']}/{r['mandate_total']} |")
        w(f"| per-month CSV | `{Path(r['csv_month']).name}` |")
        w(f"| walk-forward CSV | `{Path(r['csv_wf']).name}` |")
        w(f"| events CSV | `{Path(r['csv_events']).name}` |")
        w()
    w("---")
    w()
    w("## Verdict & Next Step Recommendation")
    w()
    w(f"**Overall verdict:** **{overall}**")
    w()
    w(f"{verdict_detail}")
    w()
    if overall == "PASS":
        w("**Önerilen sonraki adımlar (Lab tavsiyesi):**")
        w()
        w("1. CEO brief: SEC54.6e sub-monthly scale-down 5/5 mandate PASS (gevsek max_loss>=-15%).")
        w("2. Mekanizmayı lab.py'a port + RiskOfficer live wiring (Engineering ticket).")
        w("3. Testnet smoke 7g pencere — scale-down event'leri logla, backtest oranlarıyla karşılaştır.")
        w("4. MEMORY.md update: v3.2 CHAMPION satırına SEC54.6e sayılarını ekle.")
    elif overall in ("WARN", "MARGINAL"):
        w("**Önerilen sonraki adımlar (Lab tavsiyesi):**")
        w()
        w("1. CEO brief: Sub-monthly scale-down kısmi etkili — Principal kararı:")
        w("   - SEÇENEK 1: Eşikleri sıkılaştır (-2/-4/-6 cascade) veya multiplier'ı düşür (0.6/0.4/0.2).")
        w("   - SEÇENEK 2: SEC54.6b (daily=4%) hibrit ile birleştir.")
        w("   - SEÇENEK 3: Mevcut sonucu kabul + testnet'te 1 ay gözlemle.")
        w("2. Outlier ay delta'sını incele — hangi tier en etkili olmuş, hangi outlier kapanmamış.")
    else:
        w("**Önerilen sonraki adımlar (Lab tavsiyesi):**")
        w()
        w("1. CEO brief: Sub-monthly scale-down mekanizması YETERSİZ.")
        w("2. SEC54.6f alternatif: daha agresif eşik (-2%/-4%/-6%) veya halt-based fallback.")
        w("3. Mevcut champion (SEC54.1 OLD daily=3%, mandate 5/5) korunmaya devam.")
    w()
    w("---")
    w()
    w(f"*Generated: {now_str} by SEC54.6e subhalt_replay sprint*")

    report_text = "".join(out)
    with REPORT.open("w", encoding="utf-8") as fh:
        fh.write(report_text)
    print(f"\n[REPORT] {REPORT}", flush=True)
    print("[SEC54.6e] DONE", flush=True)


if __name__ == "__main__":
    main()
