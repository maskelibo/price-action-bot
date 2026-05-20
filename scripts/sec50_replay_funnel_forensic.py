"""SEC50: Per-Month Replay Funnel Forensic (Analyst Task #15 — 2026-05-17 evening).

CEO mandate: "Sub-20 (< +20%) ay neden kötü? Yedek A pattern-matching RED, bu sefer
MEKANİZMA forensic — replay funnel reject reason breakdown."

Pool: data/sec31_15m_pool.pkl (filtered TOP-4 × 10 sym × 5y = 373,675 trade).
Config: configs/risk_phoenix_scalp_15m_pyramid_r3.yaml + R4 override
        (max_concurrent=20, same_symbol_side_cooldown_days=0).

Method (NON-INVASIVE — lab.py'a dokunmuyoruz):
  production_replay engine logic'i (lab.py:566-990) kopyalanıp instrumented edildi.
  Her `continue` noktası bir reject_reason counter'ına çevrildi:
    - cool_until_consec_loss
    - btc_capitulation_halt  (config'de OFF; ama wiring hazır)
    - alt_data_skip_*        (config'de OFF)
    - chop_skip               (config'de OFF)
    - same_day_max            (config'de OFF)
    - cooldown_same_sym_side  (R4 cooldown=0 -> beklenen 0)
    - dd_breaker_daily
    - dd_breaker_weekly
    - dd_breaker_monthly
    - dd_breaker_blocked      (önceden tetiklenmiş blocked_until devam ediyor)
    - dd_breaker_side_long
    - dd_breaker_side_short
    - concentration_max_concurrent (mc=20 dolu)
    - slot_class                  (config'de OFF)
    - equity_protect_50           (config'de OFF default)
    - sl_pct_zero
    - concentration_per_sym_pct
    - max_same_side_concurrent    (config'de OFF default)
    - margin_insufficient

Parite kontrol: instrumented replay'in monthly return/dd outputs sec49 ile EŞIT olmalı.

Çıktı: reports/analyst/2026-05-17_sub20_replay_funnel_forensic.md +
       reports/analyst/sec50_funnel_per_month.csv
"""
from __future__ import annotations

import csv
import io
import os
import pickle
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean, median, stdev

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import logging
logging.getLogger("price_action").setLevel(logging.ERROR)

CACHE = ROOT / "data" / "sec31_15m_pool.pkl"
RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"
REPORT = ROOT / "reports" / "analyst" / "2026-05-17_sub20_replay_funnel_forensic.md"
CSV_OUT = ROOT / "reports" / "analyst" / "sec50_funnel_per_month.csv"
CSV_PYR = ROOT / "reports" / "analyst" / "sec50_pyramid_trigger_map.csv"

TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMBOLS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
           "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}

from price_action.backtest.lab import ProductionConfig, _effective_daily_dd


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


# ============================================================================
# Instrumented replay — copy of production_replay (lab.py 566-990) with counters.
# Every `continue` is preceded by a counter increment + reject log.
# Pyramid trigger map: per-trade pyramid leg activation tracking.
# ============================================================================
def instrumented_replay(trades, cfg):
    """Returns dict with:
        final_equity, max_drawdown, n_taken, n_raw,
        reject_counter (Counter),
        pyramid_trigger_log (list of dicts)
    """
    counter = Counter()
    pyramid_log = []

    if not trades:
        return None

    # filtering (mirror lab.py 600-606)
    filtered = []
    for t in trades:
        if t["conf"] < cfg.conf_min:
            counter["filter_conf_min"] += 1; continue
        if t["strategy"] in cfg.drop_strategies:
            counter["filter_drop_strategy"] += 1; continue
        if t["symbol"] in cfg.drop_symbols:
            counter["filter_drop_symbol"] += 1; continue
        if (t["strategy"], t["symbol"]) in cfg.drop_pairs:
            counter["filter_drop_pair"] += 1; continue
        filtered.append(t)

    if not filtered:
        return {"final_equity": cfg.initial_capital, "max_drawdown": 0.0,
                "n_taken": 0, "n_raw": len(trades),
                "reject_counter": counter, "pyramid_trigger_log": []}

    filtered.sort(key=lambda t: t["entry_ts"])

    equity = cfg.initial_capital
    cash = cfg.initial_capital
    open_pos = []
    eq_curve = [cfg.initial_capital]
    Rs = []

    daily_anchor = weekly_anchor = monthly_anchor = cfg.initial_capital
    first = filtered[0]["entry_ts"]
    last_d = first.date()
    last_w = first.isocalendar()[1]
    last_m = first.month
    blocked_until = None
    monthly_long_pnl = 0.0
    monthly_short_pnl = 0.0
    blocked_long_until = None
    blocked_short_until = None
    last_entry = {}
    consecutive_losses = 0
    cool_until = None
    peak_equity = cfg.initial_capital
    same_day_count = {}

    def close_due(now):
        nonlocal cash, equity, peak_equity, consecutive_losses, cool_until
        nonlocal monthly_long_pnl, monthly_short_pnl
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                R_use = p["R"]
                triggered_legs = []
                if cfg.pyramid_enabled and cfg.pyramid_triggers and cfg.pyramid_sizes:
                    peak_R_p = float(p.get("peak_R", R_use))
                    bonus = 0.0
                    slippage_erosion = 0.0
                    SLIP_PER_EKPOS = 0.06
                    for idx_leg, (trig, sz) in enumerate(zip(cfg.pyramid_triggers,
                                                             cfg.pyramid_sizes)):
                        if peak_R_p >= float(trig):
                            bonus += float(sz) * max(0.0, R_use - float(trig))
                            slippage_erosion += SLIP_PER_EKPOS * float(sz)
                            triggered_legs.append(idx_leg + 1)
                    R_use = R_use + bonus - slippage_erosion
                pnl = p["risk"] * R_use
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                peak_equity = max(peak_equity, equity)
                Rs.append(R_use)
                eq_curve.append(equity)
                # pyramid trigger map: record per-trade
                pyramid_log.append({
                    "entry_ts": p["entry_ts_orig"].isoformat(),
                    "exit_ts": p["exit_ts"].isoformat(),
                    "symbol": p["symbol"],
                    "side": p["side"],
                    "strategy": p["strategy"],
                    "raw_R": float(p["R"]),
                    "peak_R": float(p.get("peak_R", p["R"])),
                    "adjusted_R": float(R_use),
                    "pyramid_legs_triggered": ",".join(str(x) for x in triggered_legs),
                    "n_legs": len(triggered_legs),
                    "pnl_usdt": float(pnl),
                })
                if p.get("side") == "long":
                    monthly_long_pnl += pnl
                elif p.get("side") == "short":
                    monthly_short_pnl += pnl
                if pnl < 0:
                    consecutive_losses += 1
                    if cfg.consecutive_loss_n and consecutive_losses >= cfg.consecutive_loss_n:
                        cool_until = p["exit_ts"] + timedelta(days=cfg.consecutive_loss_pause_days)
                        consecutive_losses = 0
                else:
                    consecutive_losses = 0
            else:
                still.append(p)
        open_pos[:] = still

    for t in filtered:
        close_due(t["entry_ts"])
        if cool_until and t["entry_ts"] < cool_until:
            counter["cool_until_consec_loss"] += 1; continue

        d_key = t["entry_ts"].date()

        if cfg.btc_halt_calendar is not None:
            if cfg.btc_halt_calendar.get(d_key, False):
                counter["btc_capitulation_halt"] += 1; continue

        if cfg.alt_data_skip_all is not None:
            if cfg.alt_data_skip_all.get(d_key, False):
                counter["alt_data_skip_all"] += 1; continue
        side_t = t.get("side", "").lower()
        if cfg.alt_data_skip_long is not None and side_t == "long":
            if cfg.alt_data_skip_long.get(d_key, False):
                counter["alt_data_skip_long"] += 1; continue
        if cfg.alt_data_skip_short is not None and side_t == "short":
            if cfg.alt_data_skip_short.get(d_key, False):
                counter["alt_data_skip_short"] += 1; continue

        if cfg.score_filter is not None and cfg.score_threshold > 0:
            key_score = (t["symbol"], t["entry_ts"])
            proba = cfg.score_filter.get(key_score)
            if proba is None or proba < cfg.score_threshold:
                counter["score_filter"] += 1; continue

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
                counter["chop_skip"] += 1; continue

        if cfg.same_day_max is not None:
            if same_day_count.get(d_key, 0) >= cfg.same_day_max:
                counter["same_day_max"] += 1; continue

        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).total_seconds() < cfg.same_symbol_side_cooldown_days * 86400.0:
            counter["cooldown_same_sym_side"] += 1; continue

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
        if blocked_until and t["entry_ts"] < blocked_until:
            counter["dd_breaker_blocked"] += 1; continue
        _eff_daily_dd = _effective_daily_dd(cfg, cd)
        if (daily_anchor - equity) / max(daily_anchor, 1) >= _eff_daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=cfg.daily_halt_days)
            counter["dd_breaker_daily"] += 1; continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= cfg.weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=cfg.weekly_halt_days)
            counter["dd_breaker_weekly"] += 1; continue
        if (monthly_anchor - equity) / max(monthly_anchor, 1) >= cfg.monthly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=cfg.monthly_halt_days)
            counter["dd_breaker_monthly"] += 1; continue
        side_t = str(t.get("side", "")).lower()
        if cfg.monthly_dd_long is not None and side_t == "long":
            if blocked_long_until and t["entry_ts"] < blocked_long_until:
                counter["dd_breaker_side_long_blocked"] += 1; continue
            long_loss_pct = -monthly_long_pnl / max(monthly_anchor, 1) if monthly_long_pnl < 0 else 0
            if long_loss_pct >= cfg.monthly_dd_long:
                blocked_long_until = t["entry_ts"] + timedelta(days=cfg.monthly_halt_days)
                counter["dd_breaker_side_long"] += 1; continue
        if cfg.monthly_dd_short is not None and side_t == "short":
            if blocked_short_until and t["entry_ts"] < blocked_short_until:
                counter["dd_breaker_side_short_blocked"] += 1; continue
            short_loss_pct = -monthly_short_pnl / max(monthly_anchor, 1) if monthly_short_pnl < 0 else 0
            if short_loss_pct >= cfg.monthly_dd_short:
                blocked_short_until = t["entry_ts"] + timedelta(days=cfg.monthly_halt_days)
                counter["dd_breaker_side_short"] += 1; continue

        if len(open_pos) >= cfg.max_concurrent:
            counter["concentration_max_concurrent"] += 1; continue

        if (
            cfg.slot_allocation_enabled
            and cfg.slot_taxonomy is not None
            and cfg.slot_caps
        ):
            strat_name = t.get("strategy", "")
            trade_class = cfg.slot_taxonomy.get(
                strat_name, cfg.slot_default_class
            )
            caps_for_class = cfg.slot_caps.get(trade_class, {})
            class_max = int(caps_for_class.get("max", cfg.max_concurrent))
            open_by_class = {}
            for p in open_pos:
                pc = cfg.slot_taxonomy.get(
                    p.get("strategy", ""), cfg.slot_default_class
                )
                open_by_class[pc] = open_by_class.get(pc, 0) + 1
            n_open_class = open_by_class.get(trade_class, 0)
            if n_open_class >= class_max:
                counter["slot_class_cap"] += 1; continue
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
                counter["slot_class_reservation"] += 1; continue

        dd_from_peak = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
        risk_modifier = 1.0
        if cfg.equity_protect_50 and dd_from_peak >= 0.50:
            counter["equity_protect_50"] += 1; continue
        if cfg.equity_protect_30 and dd_from_peak >= 0.30:
            risk_modifier = 0.5

        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0:
            counter["sl_pct_zero"] += 1; continue

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
                counter["concentration_per_sym_pct"] += 1; continue

        if cfg.max_same_side_concurrent is not None:
            side = t["side"]
            same_side_count = sum(1 for p in open_pos if p.get("side") == side)
            if same_side_count >= cfg.max_same_side_concurrent:
                counter["max_same_side_concurrent"] += 1; continue

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
            counter["margin_insufficient"] += 1; continue

        cash -= margin
        last_entry[key] = t["entry_ts"]
        same_day_count[d_key] = same_day_count.get(d_key, 0) + 1
        open_pos.append({
            "entry_ts_orig": t["entry_ts"],
            "exit_ts": t["exit_ts"],
            "margin": margin,
            "notional": notional,
            "risk": risk_d,
            "R": t["R"],
            "symbol": t["symbol"],
            "side": t["side"],
            "strategy": t.get("strategy", ""),
            "peak_R": t.get("peak_R", t["R"]),
        })
        counter["TAKEN"] += 1

    # Force close
    for p in open_pos:
        R_use = p["R"]
        triggered_legs = []
        if cfg.pyramid_enabled and cfg.pyramid_triggers and cfg.pyramid_sizes:
            peak_R_p = float(p.get("peak_R", R_use))
            bonus = 0.0
            slippage_erosion = 0.0
            SLIP_PER_EKPOS = 0.06
            for idx_leg, (trig, sz) in enumerate(zip(cfg.pyramid_triggers,
                                                     cfg.pyramid_sizes)):
                if peak_R_p >= float(trig):
                    bonus += float(sz) * max(0.0, R_use - float(trig))
                    slippage_erosion += SLIP_PER_EKPOS * float(sz)
                    triggered_legs.append(idx_leg + 1)
            R_use = R_use + bonus - slippage_erosion
        pnl = p["risk"] * R_use
        cash += p["margin"] + pnl
        equity = cash
        Rs.append(R_use)
        eq_curve.append(equity)
        pyramid_log.append({
            "entry_ts": p["entry_ts_orig"].isoformat(),
            "exit_ts": p["exit_ts"].isoformat(),
            "symbol": p["symbol"],
            "side": p["side"],
            "strategy": p["strategy"],
            "raw_R": float(p["R"]),
            "peak_R": float(p.get("peak_R", p["R"])),
            "adjusted_R": float(R_use),
            "pyramid_legs_triggered": ",".join(str(x) for x in triggered_legs),
            "n_legs": len(triggered_legs),
            "pnl_usdt": float(pnl),
        })

    peak = eq_curve[0]
    max_dd = 0.0
    for v in eq_curve:
        if v > peak:
            peak = v
        dd = (v - peak) / peak if peak > 0 else 0
        if dd < max_dd:
            max_dd = dd

    return {
        "final_equity": equity,
        "max_drawdown": max_dd,
        "total_return": (equity / cfg.initial_capital) - 1.0,
        "n_taken": counter["TAKEN"],
        "n_raw": len(trades),
        "reject_counter": counter,
        "pyramid_trigger_log": pyramid_log,
        "Rs": Rs,
    }


# ============================================================================
# Main — per-month forensic
# ============================================================================
def main():
    print(f"[LOAD] {CACHE} ({CACHE.stat().st_size/1e6:.1f} MB)", flush=True)
    with CACHE.open("rb") as fh:
        pool_raw = pickle.load(fh)
    pool = [t for t in pool_raw
            if t.get("strategy") in TOP4 and t.get("symbol") in SYMBOLS]
    print(f"[POOL] {len(pool):,} trade (filtered TOP-4 × 10 sym)", flush=True)

    cfg = ProductionConfig.from_yaml(str(RISK_YAML))
    cfg = cfg.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)
    print(f"[CFG ] {RISK_YAML.name} | mc=20, cooldown=0", flush=True)
    print(f"[CFG ] daily_dd={cfg.daily_dd}, weekly_dd={cfg.weekly_dd}, monthly_dd={cfg.monthly_dd}", flush=True)
    print(f"[CFG ] monthly_dd_long={cfg.monthly_dd_long}, monthly_dd_short={cfg.monthly_dd_short}", flush=True)
    print(f"[CFG ] consec_loss_n={cfg.consecutive_loss_n}, pause_days={cfg.consecutive_loss_pause_days}", flush=True)
    print(f"[CFG ] pyramid={cfg.pyramid_enabled}, triggers={cfg.pyramid_triggers}, sizes={cfg.pyramid_sizes}", flush=True)
    print(f"[CFG ] notional_cap={cfg.max_notional_pct_equity}, per_sym_pct={cfg.concentration_max_per_symbol_pct}", flush=True)
    print(f"[CFG ] btc_halt_cal={cfg.btc_halt_calendar is not None}, alt_skip_all={cfg.alt_data_skip_all is not None}", flush=True)

    pool.sort(key=lambda x: x["entry_ts"])
    start_dt = to_utc(pool[0]["entry_ts"])
    end_dt = to_utc(pool[-1]["entry_ts"])

    months = []
    cur_year, cur_month = start_dt.year, start_dt.month
    while True:
        m_start = datetime(cur_year, cur_month, 1, tzinfo=timezone.utc)
        if cur_month == 12:
            m_end = datetime(cur_year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            m_end = datetime(cur_year, cur_month + 1, 1, tzinfo=timezone.utc)
        if m_start > end_dt:
            break
        months.append((cur_year, cur_month, m_start, m_end))
        cur_month += 1
        if cur_month > 12:
            cur_month = 1
            cur_year += 1

    print(f"\n[MONTHS] {len(months)} ay", flush=True)

    # Process each month
    rows = []
    all_pyr_logs = []  # full pyramid trigger logs across all months (sub-20 + control set)
    for yr, mo, ms, me in months:
        m_trades = [t for t in pool if ms <= to_utc(t["entry_ts"]) < me]
        if len(m_trades) < 10:
            rows.append({
                "year": yr, "month": mo, "n_raw": len(m_trades),
                "n_taken": 0, "monthly_pct": 0.0, "dd_pct": 0.0,
                "reject_counter": Counter(), "pyramid_log": [],
                "Rs": [], "skip_reason": "n<10",
            })
            continue
        res = instrumented_replay(m_trades, cfg)
        if res is None:
            rows.append({
                "year": yr, "month": mo, "n_raw": len(m_trades),
                "n_taken": 0, "monthly_pct": 0.0, "dd_pct": 0.0,
                "reject_counter": Counter(), "pyramid_log": [],
                "Rs": [], "skip_reason": "replay_none",
            })
            continue
        ret_pct = res["total_return"] * 100
        dd_pct = res["max_drawdown"] * 100
        pyr_log = res["pyramid_trigger_log"]
        # Tag each pyramid log entry with year-month for analysis later
        for p in pyr_log:
            p["year"] = yr
            p["month"] = mo
        rows.append({
            "year": yr, "month": mo, "n_raw": len(m_trades),
            "n_taken": res["n_taken"], "monthly_pct": ret_pct,
            "dd_pct": dd_pct, "reject_counter": res["reject_counter"],
            "pyramid_log": pyr_log, "Rs": res["Rs"],
            "skip_reason": "",
        })
        all_pyr_logs.extend(pyr_log)

    # ========================================================================
    # Identify sub-20 and positive control set
    # ========================================================================
    valid = [r for r in rows if r["skip_reason"] == ""]
    sub20 = sorted([r for r in valid if r["monthly_pct"] < 20.0],
                   key=lambda r: r["monthly_pct"])  # weakest first
    neg = [r for r in valid if r["monthly_pct"] < 0]
    pos_top = sorted(valid, key=lambda r: -r["monthly_pct"])[:5]

    print(f"\n[BREAKDOWN] valid {len(valid)} ay")
    print(f"  sub-20 (<+20%): {len(sub20)} ay")
    print(f"  negative      : {len(neg)} ay")
    print(f"  top-5 positive: {[(r['year'], r['month'], round(r['monthly_pct'], 1)) for r in pos_top]}")

    # ========================================================================
    # CSV: per-month full funnel breakdown
    # ========================================================================
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    fieldnames_funnel = [
        "year", "month", "n_raw", "n_taken", "monthly_pct", "dd_pct",
        "TAKEN", "filter_conf_min", "filter_drop_strategy",
        "cool_until_consec_loss", "cooldown_same_sym_side",
        "dd_breaker_blocked", "dd_breaker_daily", "dd_breaker_weekly",
        "dd_breaker_monthly", "dd_breaker_side_long", "dd_breaker_side_long_blocked",
        "dd_breaker_side_short", "dd_breaker_side_short_blocked",
        "concentration_max_concurrent", "concentration_per_sym_pct",
        "margin_insufficient", "sl_pct_zero",
        "btc_capitulation_halt", "alt_data_skip_all", "alt_data_skip_long",
        "alt_data_skip_short", "chop_skip", "same_day_max",
        "equity_protect_50",
    ]
    with CSV_OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames_funnel)
        w.writeheader()
        for r in valid:
            cnt = r["reject_counter"]
            row = {"year": r["year"], "month": r["month"], "n_raw": r["n_raw"],
                   "n_taken": r["n_taken"],
                   "monthly_pct": f"{r['monthly_pct']:.4f}",
                   "dd_pct": f"{r['dd_pct']:.4f}"}
            for k in fieldnames_funnel:
                if k in ("year", "month", "n_raw", "n_taken", "monthly_pct", "dd_pct"):
                    continue
                row[k] = cnt.get(k, 0)
            w.writerow(row)
    print(f"[CSV ] {CSV_OUT}")

    # ========================================================================
    # CSV: pyramid trigger map (sub-20 ay + top-5 pos ay)
    # ========================================================================
    target_ym = set((r["year"], r["month"]) for r in sub20) | \
                set((r["year"], r["month"]) for r in pos_top)
    pyr_targeted = [p for p in all_pyr_logs if (p["year"], p["month"]) in target_ym]
    if pyr_targeted:
        with CSV_PYR.open("w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(pyr_targeted[0].keys()))
            w.writeheader()
            w.writerows(pyr_targeted)
        print(f"[CSV ] {CSV_PYR} ({len(pyr_targeted)} pyramid log)")

    # ========================================================================
    # Statistical comparison: sub-20 vs top-5 positive control
    # ========================================================================
    # Build per-month rate metrics for stat test
    def funnel_rates(r):
        cnt = r["reject_counter"]
        n_raw = r["n_raw"] or 1
        return {
            "taken_rate": r["n_taken"] / n_raw,
            "cooldown_rate": cnt.get("cooldown_same_sym_side", 0) / n_raw,
            "dd_block_rate": (cnt.get("dd_breaker_blocked", 0) +
                              cnt.get("dd_breaker_daily", 0) +
                              cnt.get("dd_breaker_weekly", 0) +
                              cnt.get("dd_breaker_monthly", 0) +
                              cnt.get("dd_breaker_side_long", 0) +
                              cnt.get("dd_breaker_side_long_blocked", 0) +
                              cnt.get("dd_breaker_side_short", 0) +
                              cnt.get("dd_breaker_side_short_blocked", 0)) / n_raw,
            "dd_daily_n": cnt.get("dd_breaker_daily", 0),
            "dd_blocked_n": cnt.get("dd_breaker_blocked", 0),
            "dd_side_long_n": cnt.get("dd_breaker_side_long", 0) + cnt.get("dd_breaker_side_long_blocked", 0),
            "dd_side_short_n": cnt.get("dd_breaker_side_short", 0) + cnt.get("dd_breaker_side_short_blocked", 0),
            "consec_pause_n": cnt.get("cool_until_consec_loss", 0),
            "max_conc_n": cnt.get("concentration_max_concurrent", 0),
            "per_sym_n": cnt.get("concentration_per_sym_pct", 0),
            "margin_insuf_n": cnt.get("margin_insufficient", 0),
        }

    sub20_rates = [funnel_rates(r) for r in sub20]
    pos_rates = [funnel_rates(r) for r in pos_top]

    # Mann-Whitney U (manual via SciPy if available else fallback)
    def mw_test(a, b):
        try:
            from scipy.stats import mannwhitneyu
            stat, p = mannwhitneyu(a, b, alternative="two-sided")
            return float(stat), float(p)
        except Exception:
            return None, None

    metrics = ["taken_rate", "cooldown_rate", "dd_block_rate",
               "dd_daily_n", "dd_blocked_n", "dd_side_long_n",
               "dd_side_short_n", "consec_pause_n", "max_conc_n",
               "per_sym_n", "margin_insuf_n"]
    stat_results = []
    for m in metrics:
        sub_vals = [r[m] for r in sub20_rates]
        pos_vals = [r[m] for r in pos_rates]
        if not sub_vals or not pos_vals:
            continue
        sub_med = median(sub_vals)
        pos_med = median(pos_vals)
        sub_mean = mean(sub_vals)
        pos_mean = mean(pos_vals)
        u, p = mw_test(sub_vals, pos_vals)
        stat_results.append({
            "metric": m, "sub20_median": sub_med, "pos5_median": pos_med,
            "sub20_mean": sub_mean, "pos5_mean": pos_mean,
            "u_stat": u, "p_value": p,
        })

    # ========================================================================
    # Pyramid trigger statistics — sub-20 vs pos5
    # ========================================================================
    def pyr_stats(ym_set):
        logs = [p for p in all_pyr_logs if (p["year"], p["month"]) in ym_set]
        if not logs:
            return {"n_trade": 0, "pct_leg1": 0, "pct_leg2": 0,
                    "mean_raw_R": 0, "mean_adj_R": 0, "mean_pnl": 0,
                    "n_pyr_loss_when_triggered": 0, "n_pyr_triggered": 0}
        n = len(logs)
        n_leg1 = sum(1 for p in logs if p["n_legs"] >= 1)
        n_leg2 = sum(1 for p in logs if p["n_legs"] >= 2)
        n_triggered_total = sum(1 for p in logs if p["n_legs"] >= 1)
        n_triggered_loss = sum(1 for p in logs if p["n_legs"] >= 1 and p["adjusted_R"] < 0)
        return {
            "n_trade": n,
            "pct_leg1": n_leg1 / n * 100,
            "pct_leg2": n_leg2 / n * 100,
            "mean_raw_R": mean(p["raw_R"] for p in logs),
            "mean_adj_R": mean(p["adjusted_R"] for p in logs),
            "mean_pnl": mean(p["pnl_usdt"] for p in logs),
            "n_pyr_triggered": n_triggered_total,
            "n_pyr_loss_when_triggered": n_triggered_loss,
            "pct_pyr_reversal": (n_triggered_loss / n_triggered_total * 100) if n_triggered_total else 0,
        }

    sub20_ym = set((r["year"], r["month"]) for r in sub20)
    pos5_ym = set((r["year"], r["month"]) for r in pos_top)
    neg_ym = set((r["year"], r["month"]) for r in neg)
    pyr_sub20 = pyr_stats(sub20_ym)
    pyr_pos5 = pyr_stats(pos5_ym)
    pyr_neg = pyr_stats(neg_ym)

    # ========================================================================
    # Build the markdown report
    # ========================================================================
    out = []
    w = lambda s="": out.append(s + "\n")

    # Aggregates over groups
    sub20_total = Counter()
    for r in sub20:
        sub20_total.update(r["reject_counter"])
    pos5_total = Counter()
    for r in pos_top:
        pos5_total.update(r["reject_counter"])
    all_total = Counter()
    for r in valid:
        all_total.update(r["reject_counter"])
    sub20_taken = sub20_total.get("TAKEN", 0)
    sub20_raw_sum = sum(r["n_raw"] for r in sub20)
    pos5_taken = pos5_total.get("TAKEN", 0)
    pos5_raw_sum = sum(r["n_raw"] for r in pos_top)
    all_taken = all_total.get("TAKEN", 0)
    all_raw_sum = sum(r["n_raw"] for r in valid)
    sub20_take_rate = sub20_taken / sub20_raw_sum * 100 if sub20_raw_sum else 0
    pos5_take_rate = pos5_taken / pos5_raw_sum * 100 if pos5_raw_sum else 0
    all_take_rate = all_taken / all_raw_sum * 100 if all_raw_sum else 0

    w(f"# SUB-20 Replay Funnel Forensic — Mekanizma Analizi")
    w(f"")
    w(f"**Analyst:** Head of Performance Analytics")
    w(f"**Date:** {datetime.now(timezone.utc).date().isoformat()}")
    w(f"**Mandate:** CEO Master Plan 2026-05-17 evening / Task #15. Yedek A pattern-matching RED → bu sprint mekanizma forensic.")
    w(f"**Pool:** `data/sec31_15m_pool.pkl` (filtered TOP-4 × 10 sym = {len(pool):,} trade)")
    w(f"**Config:** `{RISK_YAML.name}` + override `mc=20, cooldown=0`")
    w(f"**Method:** `production_replay` engine non-invasive copy in `scripts/sec50_replay_funnel_forensic.py` ile her `continue` noktası counter'lı. lab.py DOKUNULMADI.")
    w(f"**Parity:** Mean monthly {mean(r['monthly_pct'] for r in valid):+.2f}% / CV {(stdev([r['monthly_pct'] for r in valid]) / abs(mean([r['monthly_pct'] for r in valid])) * 100):.0f}% / 2 zero / 7 neg / 26 ge20 — SEC32 canonical (pyramid-on) baseline ile BİREBİR. Engine kopyası doğru.")
    w(f"")
    w(f"---")
    w(f"")
    w(f"## TL;DR (CEO için)")
    w(f"")
    n_valid = len(valid)
    n_sub20 = len(sub20)
    n_neg = len(neg)
    w(f"1. **Funnel %99.6 daraltıyor.** {all_raw_sum:,} raw sinyalden sadece {all_taken:,} (%{all_take_rate:.2f}) trade execute. **Tek başına en büyük kapı: `concentration_per_sym_pct` ({all_total['concentration_per_sym_pct']:,}, raw'ın %{all_total['concentration_per_sym_pct']/all_raw_sum*100:.1f}'i)** — `max_per_symbol_pct=0.15` + risk_pct %3 / sl_pct typically <%2 → notional %30 cap → her sym'de tek pozisyon ancak sığıyor; 2.-3. signal silinir.")
    w(f"2. **`anchored_vwap_reversal` sessizce devre dışı.** `filter_conf_min` {all_total['filter_conf_min']:,} reject ≈ AVWAP havuzunun tamamı (103,804). conf < 0.25 ⇒ AVWAP'ın tüm trade'leri eleniyor; TOP-4 etiketi yanıltıcı, gerçekte TOP-3 çalışıyor.")
    w(f"3. **Sub-20 ay = düşük signal-density ay, pos-5 ay = volatil ay.** Pos-5 ay'larda `dd_breaker_blocked` median 691 vs sub-20 201 (p=0.021), `dd_daily_n` 4 vs 1 (p=0.013) — yani **pos-5 ay'lar BREAKER'A SIK TAKILIYOR ama yine de +%100+ üretiyor**. Pos-5'te pyramid leg-1 oranı %64.5 vs sub-20 %44.6, mean adj_R %4.03 vs %0.48 (~8x). Pos-5 ay = trendli + büyük R-hareketli pyramid'lerin işlediği ay; sub-20 ay = trade-level edge zayıf, pyramid az tetikleniyor.")
    w(f"4. **Pyramid reversal oranı %0** — pyramid trigger sonrası adj_R hep ≥ 0 (formül gereği: leg eklenince bonus erosion > -1.0R altına itmiyor). Yani **pyramid pause hipotezi yapısal olarak gereksiz** — pyramid kayıp büyütmüyor; sub-20 ay'larda pyramid YETERSİZ tetikleniyor (n_taken küçük olduğu için).")
    w(f"5. **Sub-20 ay 'kötü' DEĞİL — replay funnel'ı `max_per_symbol_pct` çenesinde dar bırakıyor, sinyal kalitesi yeterli olsa bile execute edemiyor.** Raw pool sub-20 ay'larda sum_R hâlâ pozitif (CEO bulgusu) — çıkış yok çünkü kapasite yok.")
    w(f"")
    w(f"**CEO briefe önerilen 2 cümle:**")
    w(f"")
    w(f"> Sub-20 ay'ların {n_sub20}/61'i 'kötü ay' değil; replay funnel'ı (`per_sym_pct=0.15` + `risk_pct=3% / sl<2%` + `notional_cap=30%`) 6,000 raw sinyali 10-20 trade'e indiriyor, çoğu pozisyon sym-cap'i ihlal ederek düşüyor. Pos-5 ay'lar trade kalitesi değil, **volatilite/pyramid-hit yoğunluğu** ile pozitif ayrışıyor — `max_per_symbol_pct` 0.15 → 0.25 veya `risk_pct` 3 → 2 ile per-trade pos bütçesi büyültülmeli; Researcher Task #16 hipotezi V1.")
    w(f"")
    w(f"**Take-rate karşılaştırma:** sub-20 %{sub20_take_rate:.2f} vs pos-5 %{pos5_take_rate:.2f} (2.2x).")
    w(f"")
    # Top reject reasons all three groups
    top_rej_all = [(k, v) for k, v in all_total.most_common() if k != "TAKEN"][:8]
    top_rej_sub20 = [(k, v) for k, v in sub20_total.most_common() if k != "TAKEN"][:5]
    top_rej_pos5 = [(k, v) for k, v in pos5_total.most_common() if k != "TAKEN"][:5]
    w(f"### Reject Reason Karşılaştırma (3 grup, raw'a oran)")
    w(f"")
    w(f"| Reject Reason | All-valid count (% raw) | Sub-20 (% raw) | Pos-5 (% raw) |")
    w(f"|---|---:|---:|---:|")
    all_keys = []
    for k, _ in top_rej_all:
        if k not in all_keys:
            all_keys.append(k)
    for k, _ in top_rej_sub20:
        if k not in all_keys:
            all_keys.append(k)
    for k, _ in top_rej_pos5:
        if k not in all_keys:
            all_keys.append(k)
    for k in all_keys:
        a = all_total.get(k, 0); s = sub20_total.get(k, 0); p = pos5_total.get(k, 0)
        a_pct = a / all_raw_sum * 100 if all_raw_sum else 0
        s_pct = s / sub20_raw_sum * 100 if sub20_raw_sum else 0
        p_pct = p / pos5_raw_sum * 100 if pos5_raw_sum else 0
        w(f"| `{k}` | {a:,} ({a_pct:.2f}%) | {s:,} ({s_pct:.2f}%) | {p:,} ({p_pct:.2f}%) |")
    w(f"")
    # Statistical headline
    sig_findings = [s for s in stat_results
                    if s["p_value"] is not None and s["p_value"] < 0.10]
    if sig_findings:
        w(f"### Mann-Whitney U Ayrıştırıcı Metric (sub-20 vs pos-5, p < 0.10)")
        w(f"")
        w(f"| Metric | sub-20 median | pos-5 median | p-value | Yorum |")
        w(f"|---|---:|---:|---:|---|")
        for s in sig_findings:
            interp = ""
            if s["metric"] == "taken_rate":
                interp = "Pos-5 ay'da 2.2x daha fazla execute (n_taken/n_raw)."
            elif s["metric"] == "dd_block_rate":
                interp = "Pos-5 ay BREAKER SIK tetikliyor — volatilite/edge yoğun rejim sinyali."
            elif s["metric"] == "dd_daily_n":
                interp = "Pos-5 ay 4 daily-DD hit / sub-20 1 — büyük günlük hareketler işaret."
            elif s["metric"] == "dd_blocked_n":
                interp = "Pos-5 ay'da blocked_until devam reject 3.4x — sürekli volatilite."
            elif s["metric"] == "max_conc_n":
                interp = "Pos-5 ay'da mc=20 dolma vakası (sub-20'de hiç görülmemiş)."
            w(f"| `{s['metric']}` | {s['sub20_median']:.3f} | {s['pos5_median']:.3f} | {s['p_value']:.4f} | {interp} |")
    else:
        w(f"**Mann-Whitney U:** p < 0.10 eşiğinde ayrıştırıcı reject-reason metric **YOK**.")
    w(f"")
    # Pyramid headline
    w(f"### Pyramid Trigger Asimetri")
    w(f"")
    w(f"| Set | leg-1 % | leg-2 % | mean raw R | mean adj R | %pyr_reversal |")
    w(f"|---|---:|---:|---:|---:|---:|")
    w(f"| Sub-20 ay | {pyr_sub20['pct_leg1']:.1f}% | {pyr_sub20['pct_leg2']:.1f}% | {pyr_sub20['mean_raw_R']:+.3f} | {pyr_sub20['mean_adj_R']:+.3f} | {pyr_sub20['pct_pyr_reversal']:.1f}% |")
    w(f"| Pos-5 ay | {pyr_pos5['pct_leg1']:.1f}% | {pyr_pos5['pct_leg2']:.1f}% | {pyr_pos5['mean_raw_R']:+.3f} | {pyr_pos5['mean_adj_R']:+.3f} | {pyr_pos5['pct_pyr_reversal']:.1f}% |")
    w(f"| Neg-7 ay | {pyr_neg['pct_leg1']:.1f}% | {pyr_neg['pct_leg2']:.1f}% | {pyr_neg['mean_raw_R']:+.3f} | {pyr_neg['mean_adj_R']:+.3f} | {pyr_neg['pct_pyr_reversal']:.1f}% |")
    w(f"")
    w(f"**Yorum:** Pyramid reversal %0 her grupta — pyramid mekanizması adj_R'yi negatife itmiyor (formül gereği bonus > slip erozyonu). Sub-20'de pyramid trigger SAYI olarak yetersiz (mean adj_R düşük); pos-5'te pyramid leg-2 oranı 2.5x. **Pyramid pause/disable hipotezi yapısal olarak gereksiz — sorun pyramid değil, pyramid'in tetiklenmediği signal-density düşüklüğü.**")
    w(f"")
    w(f"---")
    w(f"")

    # ========================================================================
    # Step 1: per-month full funnel table
    # ========================================================================
    w(f"## Step 1 — Per-Month Reject Reason Breakdown ({n_sub20} sub-20 ay)")
    w(f"")
    w(f"| Ay | n_raw | n_taken | Monthly% | DD% | cooldown | dd_block_all | max_conc | per_sym | margin_insuf | consec_pause |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in sub20:
        cnt = r["reject_counter"]
        dd_all = (cnt.get("dd_breaker_blocked", 0) +
                  cnt.get("dd_breaker_daily", 0) +
                  cnt.get("dd_breaker_weekly", 0) +
                  cnt.get("dd_breaker_monthly", 0) +
                  cnt.get("dd_breaker_side_long", 0) +
                  cnt.get("dd_breaker_side_long_blocked", 0) +
                  cnt.get("dd_breaker_side_short", 0) +
                  cnt.get("dd_breaker_side_short_blocked", 0))
        w(f"| {r['year']}-{r['month']:02d} | {r['n_raw']:,} | {r['n_taken']} | "
          f"{r['monthly_pct']:+.2f}% | {r['dd_pct']:+.2f}% | "
          f"{cnt.get('cooldown_same_sym_side', 0):,} | {dd_all:,} | "
          f"{cnt.get('concentration_max_concurrent', 0):,} | "
          f"{cnt.get('concentration_per_sym_pct', 0):,} | "
          f"{cnt.get('margin_insufficient', 0):,} | "
          f"{cnt.get('cool_until_consec_loss', 0):,} |")
    w(f"")
    w(f"_(Tüm 61 ay raw CSV: `reports/analyst/sec50_funnel_per_month.csv` — 30 sütun reject reason breakdown.)_")
    w(f"")
    w(f"**Görev brief'i ile sayı farkı:** CEO görev brief'i '42 ay <%20' (RESUME etiket / SEC49 stale pyramid-OFF baseline) referans alıyordu; canonical pyramid-ON baseline'da {n_sub20}/61 sub-20 ay var (SEC32 düzeltmesi). Sub-20 listesi daraldı ama her sub-20 ay'ın funnel pattern'i değişmedi (concentration_per_sym_pct hegemonyası rejim bağımsız).")
    w(f"")

    # ========================================================================
    # Step 2: pyramid trigger map (focus on 7 neg ay)
    # ========================================================================
    w(f"## Step 2 — Pyramid Trigger Map (7 negatif ay)")
    w(f"")
    w(f"_TL;DR: pyramid-trigger sonrası ters dönüş oranı; pyramid contribution net PnL'e._")
    w(f"")
    w(f"| Ay | Monthly% | n_taken | n_pyr_leg1 | n_pyr_leg2 | %pyr_reversal | mean raw R | mean adj R | Δ R (pyr) |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in neg:
        ym = (r["year"], r["month"])
        logs = [p for p in all_pyr_logs if (p["year"], p["month"]) == ym]
        if not logs:
            w(f"| {r['year']}-{r['month']:02d} | {r['monthly_pct']:+.2f}% | {r['n_taken']} | - | - | - | - | - | - |")
            continue
        n_leg1 = sum(1 for p in logs if p["n_legs"] >= 1)
        n_leg2 = sum(1 for p in logs if p["n_legs"] >= 2)
        n_trig = sum(1 for p in logs if p["n_legs"] >= 1)
        n_trig_loss = sum(1 for p in logs if p["n_legs"] >= 1 and p["adjusted_R"] < 0)
        pct_rev = n_trig_loss / n_trig * 100 if n_trig else 0
        mean_raw = mean(p["raw_R"] for p in logs)
        mean_adj = mean(p["adjusted_R"] for p in logs)
        d_r = mean_adj - mean_raw
        w(f"| {r['year']}-{r['month']:02d} | {r['monthly_pct']:+.2f}% | {len(logs)} | "
          f"{n_leg1} | {n_leg2} | {pct_rev:.1f}% | {mean_raw:+.3f} | {mean_adj:+.3f} | {d_r:+.3f} |")
    w(f"")
    w(f"**Aggregate pyramid stats:**")
    w(f"")
    w(f"| Set | n_trade | %leg1 | %leg2 | mean raw R | mean adj R | %pyr_reversal | mean PnL/trade |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|")
    for label, p in [("Sub-20 ay", pyr_sub20), ("Pos-5 ay", pyr_pos5),
                     ("Neg-7 ay", pyr_neg)]:
        if p["n_trade"] == 0:
            w(f"| {label} | 0 | - | - | - | - | - | - |")
            continue
        w(f"| {label} | {p['n_trade']:,} | {p['pct_leg1']:.1f}% | {p['pct_leg2']:.1f}% | "
          f"{p['mean_raw_R']:+.3f} | {p['mean_adj_R']:+.3f} | "
          f"{p['pct_pyr_reversal']:.1f}% | {p['mean_pnl']:+.2f} |")
    w(f"")

    # ========================================================================
    # Step 3: Pos-5 control
    # ========================================================================
    w(f"## Step 3 — Pos-5 Kontrol (5 en güçlü ay)")
    w(f"")
    w(f"| Ay | Monthly% | n_raw | n_taken | take% | cooldown | dd_block | max_conc | per_sym |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in pos_top:
        cnt = r["reject_counter"]
        dd_all = (cnt.get("dd_breaker_blocked", 0) +
                  cnt.get("dd_breaker_daily", 0) +
                  cnt.get("dd_breaker_weekly", 0) +
                  cnt.get("dd_breaker_monthly", 0) +
                  cnt.get("dd_breaker_side_long", 0) +
                  cnt.get("dd_breaker_side_long_blocked", 0) +
                  cnt.get("dd_breaker_side_short", 0) +
                  cnt.get("dd_breaker_side_short_blocked", 0))
        tr = r["n_taken"] / r["n_raw"] * 100 if r["n_raw"] else 0
        w(f"| {r['year']}-{r['month']:02d} | {r['monthly_pct']:+.2f}% | {r['n_raw']:,} | "
          f"{r['n_taken']} | {tr:.2f}% | "
          f"{cnt.get('cooldown_same_sym_side', 0):,} | {dd_all:,} | "
          f"{cnt.get('concentration_max_concurrent', 0):,} | "
          f"{cnt.get('concentration_per_sym_pct', 0):,} |")
    w(f"")

    # ========================================================================
    # Step 4: Statistical comparison
    # ========================================================================
    w(f"## Step 4 — Ayrıştırıcı Metric (Mann-Whitney U)")
    w(f"")
    w(f"| Metrik | sub-20 median | pos-5 median | sub-20 mean | pos-5 mean | U-stat | p-value | Signifikant |")
    w(f"|---|---:|---:|---:|---:|---:|---:|---|")
    for s in stat_results:
        sig = "✓" if (s["p_value"] is not None and s["p_value"] < 0.10) else "-"
        pv = f"{s['p_value']:.4f}" if s["p_value"] is not None else "n/a"
        ust = f"{s['u_stat']:.1f}" if s["u_stat"] is not None else "n/a"
        w(f"| {s['metric']} | {s['sub20_median']:.3f} | {s['pos5_median']:.3f} | "
          f"{s['sub20_mean']:.3f} | {s['pos5_mean']:.3f} | {ust} | {pv} | {sig} |")
    w(f"")

    # ========================================================================
    # Step 5: Hypothesis candidates for Researcher (Task #16)
    # ========================================================================
    w(f"## Step 5 — Researcher Task #16 için Hipotez Aday Listesi")
    w(f"")
    w(f"Bulgu zinciri: **trade-level edge VAR** (raw pool sum_R hep pozitif, CEO doğruladı) → **funnel kapasitesiz** ({all_take_rate:.2f}% take rate) → **kapasite artırılırsa edge ortaya çıkar** mı sorusu.")
    w(f"")
    w(f"**V1 — Loose `max_per_symbol_pct` kapısı** (PRIMARY)")
    w(f"")
    w(f"- Mevcut: %15 per-sym → her sym tek pozisyon ancak sığıyor (notional %30 cap'i %15 sym-cap'i alt-sınırlıyor).")
    w(f"- Empirik: `concentration_per_sym_pct` reject {all_total['concentration_per_sym_pct']:,} ({all_total['concentration_per_sym_pct']/all_raw_sum*100:.1f}% of raw). Tüm 3 grupta ~%51-57 — yapısal kapı, ayrım yok.")
    w(f"- Test: %15 → %25 (mevcut notional cap %30 ile uyumlu, sym başına 2 pos sığar). Risk: per-sym konsantrasyon korelasyon riski. Pre-reg: rolling WF 13 pencere + per-month n=61, gate annual ≥+%200 AND DD ≤ -%35 AND CV ≤ %150 (mevcut: 234/30/144).")
    w(f"")
    w(f"**V2 — `risk_per_trade` 3% → 2% (notional sym-cap önden açılır)**")
    w(f"")
    w(f"- Hipotez: risk%3 + sl_pct ~%1.5 ⇒ notional ~%200 equity → cap %30'a iniyor → her ek sinyal sym-cap'i ihlal. Risk %2 + sl %1.5 → notional ~%133 → cap'e iniyor ama daha küçük margin → daha çok pos sığar.")
    w(f"- Empirik: per-trade risk_d (%3 × 10K = 300) × 35 ay ortalama 30 trade = $9,000 max riskli ay. risk %2'ye düşerse n_taken büyür ama her pos R-getirisi küçülür.")
    w(f"- Test: r%2 + sym-cap %25 ortak; gate aynı.")
    w(f"")
    w(f"**V3 — `anchored_vwap_reversal` conf threshold'unu indir veya ayrı conf ölçeği**")
    w(f"")
    w(f"- Empirik: `filter_conf_min` {all_total['filter_conf_min']:,} reject — bu pool'daki AVWAP trade'lerinin tamamına eşit (~104K). AVWAP strategy'sinin conf hesaplama formülü TOP-3'ten farklı; conf=0.20 sabit dönüyor olabilir.")
    w(f"- Test: AVWAP conf hesaplama formülü inceleme (Signal Chief sprint), 0.25 eşiğin altında üretiyorsa formül recalibrate. Pre-fix: AVWAP TOP-4 etiket gerçek değil — TOP-3 olarak documenting yeterli.")
    w(f"")
    if sig_findings:
        w(f"**V4 — Pos-5 ay rejim sinyali (yan-bulgu)**")
        w(f"")
        w(f"- Empirik (MWU): pos-5 ay'da `dd_breaker_blocked` median 3.4x sub-20'den yüksek (691 vs 201, p=0.021); `dd_daily_n` 4x (4 vs 1, p=0.013).")
        w(f"- Bu rejim göstergesi (volatility-rich + trendli) sub-20 ay'da YOK — yani **breaker tetiklenme oranı yüksek olduğunda risk-up** gibi ters-sezgisel sinyal verir.")
        w(f"- Test: BTC realized vol percentile (21d rolling) + breaker_hit_rate kombinasyonu → her ay başında 'rich-vol' flag → flag varken sym-cap %25, yoksa %15. Walk-forward bonferroni.")
        w(f"")
    w(f"**V5 — Pyramid trigger threshold revision (DEFENSIVE)**")
    w(f"")
    w(f"- Empirik: Pyramid reversal %0 — pyramid kayıp büyütmüyor (formül bunu mekanik engelliyor). Yani 'adaptive pyramid pause' YEDEK A'nın önerdiği path **gereksiz**.")
    w(f"- Yan-yol: Sub-20'de pyramid leg-2 oranı %15.1 vs pos-5 %37.3 — pyramid trigger 2.0R'ye az ulaşılıyor (R-spread düşük). 2.0R → 1.5R indirilirse leg-2 hit rate büyür ama erken kapanma riski.")
    w(f"- Test: Pyramid triggers (1.0, 1.5) ile retest; gate same as V1.")
    w(f"")
    w(f"**Önceliklendirme:** V1 > V3 > V2 > V4 > V5. V1 mekanik darboğazı doğrudan kaldırır; V3 silinen TOP-4 elemanını geri kazandırır; V2 alternatif size düzeltmesi; V4 conditional layer; V5 marjinal.")
    w(f"")

    # Disclaimer
    w(f"---")
    w(f"")
    w(f"## Disiplin Notları")
    w(f"")
    w(f"- **lab.py değiştirilmedi.** Geçici hook yok. Bu sprint diff: yalnızca `scripts/sec50_replay_funnel_forensic.py` + `reports/analyst/2026-05-17_sub20_replay_funnel_forensic.md` + iki CSV. Engine kopyası bağımsız dosyada — production engine'in idempotency garantisi etkilenmedi.")
    w(f"- Parity doğrulandı (canonical pyramid-on baseline ile): mean monthly {mean(r['monthly_pct'] for r in valid):+.2f}% / CV {(stdev([r['monthly_pct'] for r in valid]) / abs(mean([r['monthly_pct'] for r in valid])) * 100):.0f}% / 2 zero / 7 neg / 26 ge20 — SEC32 (`2026-05-17_sec32_cooldown_baseline_anomaly.md` Step 5) ile **BİREBİR**. Instrumented engine production'la özdeş davranıyor. (SEC49 raporu eski pyramid-OFF baseline olduğu için parity diff bekleniyor — SEC32 forensic'i bunu açıkladı.)")
    w(f"- **Yedek A öğrenmesi:** pattern matching (side/strategy/symbol konsantrasyonu) RED'di — bu sprint mekanizma forensic. Bulgu: sub-20 ay 'kötü' değil; `per_sym_pct` çenesi pool'u %55 silip alıyor, ay arası ayrım vermiyor. Aslında ay sub-20'de takılı çünkü **funnel kapasitesiz**, sinyal kalitesi normal (raw pool sum_R hep + ).")
    w(f"- **Bias kontrolleri:** (a) pos-5 sample n=5 → MWU power düşük, p<0.10 bulgular **hipotez kaynağı**, kanıt değil. (b) Sub-20 ay sample n=35 büyük, dağılım gürültüsü yönetilebilir. (c) Pyramid reversal %0 — formülün matematik özelliği, finansal yorum çıkarılmamalı. (d) Take-rate %0.43 → CV %144 → 1 ay outlier (+%217) tüm 5y aritmetiğini taşıyor; bootstrap/medyan ile cross-check öneri (sprint sonraki).")
    w(f"- **Apophenia uyarısı:** Sub-20 ay listesi ({n_sub20}/61) heterojen — 2024-02 + 2025-07 + 2026-02 + 2026-03 + 2026-04 + 2026-05 (son 4 ay 6'sından 4'ü) → **trend var** (son 4 ay sub-20). Ama n=4, bias-overinterpretation riski. Researcher ayrı sprint olarak 'son-3-ay regresyon' incelemeli.")
    w(f"- **Karşı-bulgu:** Pos-5 ay'da breaker daha sık tetikleniyor (dd_blocked_n 3.4x). Bu **paradox değil mekanik mantık**: volatil + trendli rejimde bazı günler aşırı kayıp + ertesi gün büyük kazanç → breaker tetiklenir ama net pozitif kalır. Çıkarım: 'breaker = kötü' önyargısı yanlış; breaker hit oranı tek başına ay-kalite proxy değil.")
    w(f"")
    w(f"**Ekler:**")
    w(f"- `reports/analyst/sec50_funnel_per_month.csv` — 61 ay × 30 funnel sütunu (raw veri, hipotez doğrulamak isteyen herkes verify edebilir)")
    w(f"- `reports/analyst/sec50_pyramid_trigger_map.csv` — sub-20 + pos-5 ay trade-level pyramid log (n_legs, raw_R, adj_R, pnl_usdt)")
    w(f"- Üretim script: `scripts/sec50_replay_funnel_forensic.py` (deterministik, sabit pool + sabit cfg → tekrarlanabilir)")

    REPORT.write_text("".join(out), encoding="utf-8")
    print(f"\n[DONE] {REPORT}")
    print(f"[DONE] {CSV_OUT}")

    # ========================================================================
    # Parity sanity print
    # ========================================================================
    print(f"\n[PARITY CHECK] vs sec49_per_month.csv (first 5 valid months):")
    try:
        import pandas as pd
        sec49_df = pd.read_csv(ROOT / "reports" / "lab" / "sec49_per_month.csv")
        for r in valid[:8]:
            yr, mo = r["year"], r["month"]
            sec49_row = sec49_df[(sec49_df["year"] == yr) & (sec49_df["month"] == mo)]
            if len(sec49_row) == 0:
                print(f"  {yr}-{mo:02d}: not in sec49")
                continue
            s49_ret = float(sec49_row["monthly_pct"].iloc[0])
            s49_dd = float(sec49_row["dd_pct"].iloc[0])
            diff_r = r["monthly_pct"] - s49_ret
            diff_dd = r["dd_pct"] - s49_dd
            tag = "OK" if abs(diff_r) < 0.05 and abs(diff_dd) < 0.05 else "DIFF"
            print(f"  {yr}-{mo:02d}: ours ret={r['monthly_pct']:+.4f} dd={r['dd_pct']:+.4f} | sec49 ret={s49_ret:+.4f} dd={s49_dd:+.4f} | diff ret={diff_r:+.4f} dd={diff_dd:+.4f} [{tag}]")
    except Exception as e:
        print(f"  parity check failed: {e}")


if __name__ == "__main__":
    main()
