"""Tam replay trace — lab.py production_replay logic'i HARFIYEN kopya
(DD breakers + side-cond + consecutive_loss_pause dahil) + executed trace.

Bu sefer GERCEK replay sayisini hedefliyoruz:
  - 2025-07 production = -7.29% / 17 trade
  - mini-FIFO        = +63% / 490 trade  → fark = DD breakers

Anlamak istedigimiz:
  - Hangi tarihte halt tetiklendi
  - O halt'a sebebiyet veren ilk kayiplar hangi side/strategy/sym?
  - Halt sonrasi reset'te yine kayiplar mi?
"""
from __future__ import annotations

import io
import os
import pickle
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import datetime, timezone, timedelta
from pathlib import Path

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
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

from price_action.backtest.lab import ProductionConfig, _effective_daily_dd

POOL_15M = ROOT / "data" / "sec31_15m_pool.pkl"
YAML_15M = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"

TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}

NEG_MONTHS = ["2025-07", "2026-02", "2024-02", "2025-01", "2026-03", "2024-10"]
# skip 2023-05 (raw too small, replay=2 trades)


def to_utc(ts):
    if hasattr(ts, "tz_localize"):
        if ts.tzinfo is None:
            return ts.tz_localize("UTC")
        return ts.tz_convert("UTC")
    if ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc)


def month_bounds(yyyy_mm):
    y, m = map(int, yyyy_mm.split("-"))
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    if m == 12:
        end = datetime(y + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(y, m + 1, 1, tzinfo=timezone.utc)
    return start, end


def replay_with_trace(trades, cfg):
    """lab.py logic'in tam clonu + reject reason kaydi + executed trace."""
    filtered = [
        t for t in trades
        if t["conf"] >= cfg.conf_min
        and t["strategy"] not in cfg.drop_strategies
        and t["symbol"] not in cfg.drop_symbols
    ]
    filtered.sort(key=lambda t: t["entry_ts"])
    if not filtered:
        return [], [], cfg.initial_capital

    equity = cfg.initial_capital
    cash = cfg.initial_capital
    open_pos = []
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
    executed = []
    rejected = []  # (entry_ts, sym, side, strat, reason)

    def close_due(now):
        nonlocal cash, equity, peak_equity, consecutive_losses, cool_until
        nonlocal monthly_long_pnl, monthly_short_pnl
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                R_use = p["R"]
                if cfg.pyramid_enabled and cfg.pyramid_triggers and cfg.pyramid_sizes:
                    peak_R_p = float(p.get("peak_R", R_use))
                    bonus = 0.0
                    slip = 0.0
                    for trig, sz in zip(cfg.pyramid_triggers, cfg.pyramid_sizes):
                        if peak_R_p >= float(trig):
                            bonus += float(sz) * max(0.0, R_use - float(trig))
                            slip += 0.06 * float(sz)
                    R_use = R_use + bonus - slip
                pnl = p["risk"] * R_use
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                peak_equity = max(peak_equity, equity)
                Rs.append(R_use)
                executed.append({
                    "entry_ts": p["entry_ts"], "exit_ts": p["exit_ts"],
                    "symbol": p["symbol"], "side": p["side"], "strategy": p["strategy"],
                    "R_raw": p["R"], "R_final": R_use, "pnl": pnl,
                    "equity_after": equity,
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
            rejected.append((t["entry_ts"], t["symbol"], t["side"], t.get("strategy", ""), f"consec_pause_until_{cool_until}"))
            continue
        d_key = t["entry_ts"].date()
        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).total_seconds() < cfg.same_symbol_side_cooldown_days * 86400.0:
            rejected.append((t["entry_ts"], t["symbol"], t["side"], t.get("strategy", ""), "cooldown"))
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
        if blocked_until and t["entry_ts"] < blocked_until:
            rejected.append((t["entry_ts"], t["symbol"], t["side"], t.get("strategy", ""), f"halt_until_{blocked_until}"))
            continue
        _eff_daily_dd = _effective_daily_dd(cfg, cd)
        if (daily_anchor - equity) / max(daily_anchor, 1) >= _eff_daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=cfg.daily_halt_days)
            rejected.append((t["entry_ts"], t["symbol"], t["side"], t.get("strategy", ""), f"daily_dd_trigger_{_eff_daily_dd:.3f}"))
            continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= cfg.weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=cfg.weekly_halt_days)
            rejected.append((t["entry_ts"], t["symbol"], t["side"], t.get("strategy", ""), "weekly_dd"))
            continue
        if (monthly_anchor - equity) / max(monthly_anchor, 1) >= cfg.monthly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=cfg.monthly_halt_days)
            rejected.append((t["entry_ts"], t["symbol"], t["side"], t.get("strategy", ""), "monthly_dd"))
            continue
        side_t = str(t.get("side", "")).lower()
        if cfg.monthly_dd_long is not None and side_t == "long":
            if blocked_long_until and t["entry_ts"] < blocked_long_until:
                rejected.append((t["entry_ts"], t["symbol"], t["side"], t.get("strategy", ""), "side_long_halt"))
                continue
            long_loss_pct = -monthly_long_pnl / max(monthly_anchor, 1) if monthly_long_pnl < 0 else 0
            if long_loss_pct >= cfg.monthly_dd_long:
                blocked_long_until = t["entry_ts"] + timedelta(days=cfg.monthly_halt_days)
                rejected.append((t["entry_ts"], t["symbol"], t["side"], t.get("strategy", ""), f"side_long_dd_{cfg.monthly_dd_long}"))
                continue
        if cfg.monthly_dd_short is not None and side_t == "short":
            if blocked_short_until and t["entry_ts"] < blocked_short_until:
                rejected.append((t["entry_ts"], t["symbol"], t["side"], t.get("strategy", ""), "side_short_halt"))
                continue
            short_loss_pct = -monthly_short_pnl / max(monthly_anchor, 1) if monthly_short_pnl < 0 else 0
            if short_loss_pct >= cfg.monthly_dd_short:
                blocked_short_until = t["entry_ts"] + timedelta(days=cfg.monthly_halt_days)
                rejected.append((t["entry_ts"], t["symbol"], t["side"], t.get("strategy", ""), f"side_short_dd_{cfg.monthly_dd_short}"))
                continue
        if len(open_pos) >= cfg.max_concurrent:
            rejected.append((t["entry_ts"], t["symbol"], t["side"], t.get("strategy", ""), "max_conc"))
            continue
        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0:
            continue
        trade_risk_pct = cfg.risk_pct
        if cfg.confidence_risk_tiers:
            from price_action.backtest.scoring import get_tier_value
            conf_for_tier = t.get("conf_pct", t["conf"])
            trade_risk_pct = float(get_tier_value(
                cfg.confidence_risk_tiers, conf_for_tier, "risk_pct", cfg.risk_pct
            ))
        risk_d = equity * trade_risk_pct
        if cfg.vol_target_enabled:
            vf = cfg.vol_target_atr_pct / sl_pct
            vf = max(cfg.vol_min_factor, min(cfg.vol_max_factor, vf))
            risk_d *= vf
        notional = risk_d / sl_pct
        if cfg.max_notional_pct_equity is not None:
            cap = equity * cfg.max_notional_pct_equity
            if notional > cap:
                notional = cap
                risk_d = notional * sl_pct
        if cfg.leverage_tiers:
            from price_action.backtest.scoring import get_tier_value
            conf_for_tier = t.get("conf_pct", t["conf"])
            trade_lev = float(get_tier_value(cfg.leverage_tiers, conf_for_tier, "leverage", cfg.leverage))
        else:
            trade_lev = cfg.leverage
        if trade_lev <= 0:
            trade_lev = 1.0
        margin = notional / trade_lev
        if margin > cash:
            rejected.append((t["entry_ts"], t["symbol"], t["side"], t.get("strategy", ""), "no_cash"))
            continue
        cash -= margin
        last_entry[key] = t["entry_ts"]
        open_pos.append({
            "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
            "margin": margin, "notional": notional, "risk": risk_d,
            "R": t["R"], "symbol": t["symbol"], "side": t["side"],
            "strategy": t.get("strategy", ""), "peak_R": t.get("peak_R", t["R"]),
        })
    # close all
    for p in open_pos:
        R_use = p["R"]
        if cfg.pyramid_enabled and cfg.pyramid_triggers and cfg.pyramid_sizes:
            peak_R_p = float(p.get("peak_R", R_use))
            bonus = 0.0
            slip = 0.0
            for trig, sz in zip(cfg.pyramid_triggers, cfg.pyramid_sizes):
                if peak_R_p >= float(trig):
                    bonus += float(sz) * max(0.0, R_use - float(trig))
                    slip += 0.06 * float(sz)
            R_use = R_use + bonus - slip
        pnl = p["risk"] * R_use
        cash += p["margin"] + pnl
        equity = cash
        Rs.append(R_use)
        executed.append({
            "entry_ts": p["entry_ts"], "exit_ts": p["exit_ts"],
            "symbol": p["symbol"], "side": p["side"], "strategy": p["strategy"],
            "R_raw": p["R"], "R_final": R_use, "pnl": pnl,
            "equity_after": equity,
        })
    return executed, rejected, cash


def main():
    print("=" * 110)
    print("FULL REPLAY TRACE — neg month executed + reject reasons")
    print("=" * 110)

    with POOL_15M.open("rb") as fh:
        pool_raw = pickle.load(fh)
    pool = [t for t in pool_raw if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    pool.sort(key=lambda x: to_utc(x["entry_ts"]))

    cfg = ProductionConfig.from_yaml(str(YAML_15M))
    cfg = cfg.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)
    cfg = replace(cfg, btc_halt_calendar=None)

    print(f"\n[CFG] daily_dd={cfg.daily_dd} weekly_dd={cfg.weekly_dd} monthly_dd={cfg.monthly_dd}")
    print(f"      monthly_dd_long={cfg.monthly_dd_long} monthly_dd_short={cfg.monthly_dd_short}")
    print(f"      halt_days: daily={cfg.daily_halt_days} weekly={cfg.weekly_halt_days} monthly={cfg.monthly_halt_days}")
    print(f"      consec_n={cfg.consecutive_loss_n} consec_pause_days={cfg.consecutive_loss_pause_days}")
    print(f"      pyramid={cfg.pyramid_enabled} triggers={cfg.pyramid_triggers} sizes={cfg.pyramid_sizes}")

    for ym in NEG_MONTHS:
        start, end = month_bounds(ym)
        m_raw = [t for t in pool if start <= to_utc(t["entry_ts"]) < end]
        executed, rejected, final = replay_with_trace(m_raw, cfg)
        ret = (final / cfg.initial_capital - 1) * 100
        n_exec = len(executed)
        n_rej = len(rejected)

        print(f"\n{'='*110}")
        print(f"{ym} | replay ret={ret:+.2f}% | executed={n_exec} | rejected={n_rej}")
        print(f"{'='*110}")

        if n_exec > 0:
            side_R = defaultdict(list)
            strat_R = defaultdict(list)
            sym_R = defaultdict(list)
            for e in executed:
                side_R[e["side"]].append(e["R_final"])
                strat_R[e["strategy"]].append(e["R_final"])
                sym_R[e["symbol"]].append(e["R_final"])
            print(f"\n  EXECUTED breakdown:")
            print(f"    SIDE : " + " | ".join([f"{k}: n={len(v)} sum_R={sum(v):+.2f}" for k,v in sorted(side_R.items())]))
            print(f"    STRAT: " + " | ".join([f"{k}: n={len(v)} sum_R={sum(v):+.2f}" for k,v in sorted(strat_R.items(), key=lambda x: sum(x[1]))]))
            print(f"    SYM  : " + " | ".join([f"{k}: n={len(v)} sum_R={sum(v):+.2f}" for k,v in sorted(sym_R.items(), key=lambda x: sum(x[1]))]))
            print(f"\n  ALL EXECUTED trades (chronological):")
            for e in sorted(executed, key=lambda x: x["entry_ts"]):
                ets = to_utc(e["entry_ts"]).strftime("%m-%d %H:%M")
                xts = to_utc(e["exit_ts"]).strftime("%m-%d %H:%M")
                print(f"    {ets} → {xts}  {e['symbol']:<10} {e['side']:<5} {e['strategy']:<25} R={e['R_final']:+.2f} pnl=${e['pnl']:+8.0f} equity=${e['equity_after']:,.0f}")

        # Reject reasons breakdown
        rej_counter = Counter(r[4].split('_until_')[0].split('_trigger_')[0] for r in rejected)
        print(f"\n  REJECT REASONS:")
        for reason, cnt in rej_counter.most_common():
            print(f"    {reason:<25} {cnt}")


if __name__ == "__main__":
    main()
