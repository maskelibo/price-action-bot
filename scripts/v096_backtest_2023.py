"""v0.9.6 — Backtest from 2023-01-01 with SUPER preset (validated/honest).

Pencere: 2023-01-01 -> 2026-05-12 (~3.4 yil)
Config: configs/risk_super.yaml (causal funding filter)
Karsilastirma: AGGRESSIVE (no funding), BALANCED (halt), DEFENSIVE.

Cikti:
  - Final equity + yillik
  - Aylik P&L + R toplami
  - En karli/zararli 5 trade
  - DD timeline + peak/trough tarihleri
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.backtest.lab import ProductionConfig, production_replay
from scripts.v09_optimize_top10 import _gather, TOP_10


def replay_with_log(trades, cfg):
    """production_replay'in kopyasi ama detayli equity timeline ve trade log uretir."""
    from datetime import timedelta as _td
    if not trades: return None
    drop_strats = cfg.drop_strategies
    drop_pairs = cfg.drop_pairs or frozenset()
    drop_syms = cfg.drop_symbols or frozenset()
    filtered = [t for t in trades
                if t["conf"] >= cfg.conf_min
                and t["strategy"] not in drop_strats
                and t["symbol"] not in drop_syms
                and (t["strategy"], t["symbol"]) not in drop_pairs]
    if not filtered: return None
    filtered = sorted(filtered, key=lambda t: t["entry_ts"])

    equity = cfg.initial_capital
    cash = cfg.initial_capital
    open_pos = []
    eq_curve = [(filtered[0]["entry_ts"], cfg.initial_capital)]
    Rs = []
    log = []

    daily_anchor = weekly_anchor = monthly_anchor = cfg.initial_capital
    first = filtered[0]["entry_ts"]
    last_d = first.date()
    last_w = first.isocalendar()[1]
    last_m = first.month
    blocked_until = None
    last_entry = {}
    consecutive_losses = 0
    cool_until = None
    peak_equity = cfg.initial_capital
    same_day_count = {}

    def close_due(now):
        nonlocal cash, equity, peak_equity, consecutive_losses, cool_until
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                pnl = p["risk"] * p["R"]
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                peak_equity = max(peak_equity, equity)
                Rs.append(p["R"])
                eq_curve.append((p["exit_ts"], equity))
                # log entry
                p["pnl"] = pnl
                p["exit_equity"] = equity
                log.append(p)
                if pnl < 0:
                    consecutive_losses += 1
                    if cfg.consecutive_loss_n and consecutive_losses >= cfg.consecutive_loss_n:
                        cool_until = p["exit_ts"] + _td(days=cfg.consecutive_loss_pause_days)
                        consecutive_losses = 0
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
        if cfg.btc_halt_calendar is not None and cfg.btc_halt_calendar.get(d_key, False):
            continue
        chop_factor = 1.0
        if cfg.chop_calendars is not None:
            sym_cal = cfg.chop_calendars.get(t["symbol"])
            if sym_cal is not None:
                mode = sym_cal.get(d_key, "trend")
                if mode == "chop": chop_factor = cfg.chop_risk_factor
                elif mode == "transition": chop_factor = cfg.transition_risk_factor
            if chop_factor <= 0: continue
        if cfg.alt_data_skip_all is not None and cfg.alt_data_skip_all.get(d_key, False):
            continue
        side_t = t["side"]
        if cfg.alt_data_skip_long is not None and side_t == "long" and cfg.alt_data_skip_long.get(d_key, False):
            continue
        if cfg.alt_data_skip_short is not None and side_t == "short" and cfg.alt_data_skip_short.get(d_key, False):
            continue
        if cfg.same_day_max is not None and same_day_count.get(d_key, 0) >= cfg.same_day_max:
            continue
        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).days < cfg.same_symbol_side_cooldown_days:
            continue
        cd = t["entry_ts"].date(); cw = t["entry_ts"].isocalendar()[1]; cm = t["entry_ts"].month
        if cd != last_d: daily_anchor = equity; last_d = cd
        if cw != last_w: weekly_anchor = equity; last_w = cw
        if cm != last_m: monthly_anchor = equity; last_m = cm
        if blocked_until and t["entry_ts"] < blocked_until: continue
        if (daily_anchor - equity)/max(daily_anchor,1) >= cfg.daily_dd:
            blocked_until = t["entry_ts"] + _td(days=1); continue
        if (weekly_anchor - equity)/max(weekly_anchor,1) >= cfg.weekly_dd:
            blocked_until = t["entry_ts"] + _td(days=7); continue
        if (monthly_anchor - equity)/max(monthly_anchor,1) >= cfg.monthly_dd:
            blocked_until = t["entry_ts"] + _td(days=30); continue
        if len(open_pos) >= cfg.max_concurrent: continue
        dd_peak = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0
        risk_mod = 1.0
        if cfg.equity_protect_50 and dd_peak >= 0.50: continue
        if cfg.equity_protect_30 and dd_peak >= 0.30: risk_mod = 0.5
        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0: continue
        risk_d = equity * cfg.risk_pct * risk_mod * chop_factor
        if cfg.vol_target_enabled:
            vf = max(cfg.vol_min_factor, min(cfg.vol_max_factor, cfg.vol_target_atr_pct / sl_pct))
            risk_d *= vf
        notional = risk_d / sl_pct
        if cfg.max_notional_pct_equity is not None:
            cap = equity * cfg.max_notional_pct_equity
            if notional > cap:
                notional = cap; risk_d = notional * sl_pct
        if cfg.concentration_max_per_symbol_pct is not None:
            sym = t["symbol"]
            existing_sym = sum(p["notional"] for p in open_pos if p.get("symbol") == sym)
            sym_cap = equity * cfg.concentration_max_per_symbol_pct
            if existing_sym + notional > sym_cap: continue
        if cfg.max_same_side_concurrent is not None:
            sc = sum(1 for p in open_pos if p.get("side") == t["side"])
            if sc >= cfg.max_same_side_concurrent: continue
        margin = notional / 3.0
        if margin > cash: continue
        cash -= margin
        last_entry[key] = t["entry_ts"]
        same_day_count[d_key] = same_day_count.get(d_key, 0) + 1
        open_pos.append({
            "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
            "symbol": t["symbol"], "side": t["side"],
            "strategy": t["strategy"], "entry_price": t["entry_price"],
            "margin": margin, "notional": notional, "risk": risk_d,
            "R": t["R"],
        })
    for p in open_pos:
        cash += p["margin"] + p["risk"] * p["R"]
        equity = cash
        Rs.append(p["R"])
        eq_curve.append((p["exit_ts"], equity))
        p["pnl"] = p["risk"] * p["R"]
        p["exit_equity"] = equity
        log.append(p)

    peak = eq_curve[0][1]; max_dd = 0; peak_ts = eq_curve[0][0]; trough_ts = peak_ts
    cur_peak_ts = peak_ts
    for ts, v in eq_curve:
        if v > peak:
            peak = v; cur_peak_ts = ts
        dd = (v - peak)/peak if peak > 0 else 0
        if dd < max_dd:
            max_dd = dd; peak_ts = cur_peak_ts; trough_ts = ts
    win = sum(1 for x in Rs if x > 0)/len(Rs) if Rs else 0
    return {
        "final": equity, "max_dd": max_dd, "trades": len(Rs), "wr": win,
        "peak_ts": peak_ts, "trough_ts": trough_ts, "peak_value": peak,
        "log": log, "eq_curve": eq_curve, "sum_r": sum(Rs) if Rs else 0,
    }


def main():
    print("=" * 100)
    print("v0.9.6 BACKTEST 2023-01-01 -> SIMDI (SUPER preset, honest causal funding)")
    print("=" * 100)

    print("\nTrade topluyor...")
    all_trades = []
    for m, c in TOP_10:
        all_trades.extend(_gather(m, c))
    all_trades.sort(key=lambda x: x["entry_ts"])

    start = pd.Timestamp("2023-01-01", tz="UTC")
    end = pd.Timestamp("2026-05-12", tz="UTC")
    window = [t for t in all_trades if start <= t["entry_ts"] < end]
    years = (end - start).total_seconds() / (365.25 * 86400)
    print(f"Toplam {len(all_trades)} sinyal, pencere ({start.date()} -> {end.date()}): {len(window)} sinyal")
    print(f"Pencere sure: {years:.2f} yil")

    presets = [
        ("AGGRESSIVE", "configs/risk_aggressive.yaml"),
        ("BALANCED",   "configs/risk_balanced.yaml"),
        ("DEFENSIVE",  "configs/risk_defensive.yaml"),
        ("SUPER ⭐",   "configs/risk_super.yaml"),
    ]

    print(f"\n{'preset':<14}  {'final$':>10}  {'toplam%':>8}  {'yillik%':>8}  {'DD%':>6}  {'WR%':>5}  {'n':>4}")
    print("-" * 70)
    super_result = None
    for name, yml in presets:
        cfg = ProductionConfig.from_yaml(yml)
        r = replay_with_log(window, cfg)
        if r is None: print(f"  {name}: NO RESULT"); continue
        ret = (r["final"]/10_000 - 1) * 100
        ann = ((r["final"]/10_000) ** (1/years) - 1) * 100
        print(f"  {name:<14}  {r['final']:>10,.0f}  {ret:>+7.1f}%  {ann:>+7.2f}%  {r['max_dd']*100:>+5.1f}%  {r['wr']*100:>4.1f}%  {r['trades']:>4}")
        if "SUPER" in name:
            super_result = r

    if super_result is None:
        print("SUPER sonucu yok"); return

    # SUPER detayli analiz
    print()
    print("=" * 100)
    print("⭐ SUPER PRESET DETAYI (2023-01 -> 2026-05)")
    print("=" * 100)

    log = super_result["log"]
    print(f"\n  Final equity     : ${super_result['final']:>10,.2f}")
    print(f"  Toplam getiri    : {(super_result['final']/10_000-1)*100:+.2f}%")
    print(f"  Yillik (compound): {((super_result['final']/10_000)**(1/years)-1)*100:+.2f}%")
    print(f"  Max DD           : {super_result['max_dd']*100:+.2f}%")
    print(f"  DD peak -> trough: {super_result['peak_ts'].date()} -> {super_result['trough_ts'].date()}")
    print(f"  DD peak equity   : ${super_result['peak_value']:,.0f}")
    print(f"  Trade sayisi     : {super_result['trades']}")
    print(f"  Win rate         : {super_result['wr']*100:.1f}%")
    print(f"  Sum R            : {super_result['sum_r']:+.2f}")

    # Aylik P&L
    print(f"\n  AYLIK P&L:")
    monthly = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0, "r": 0.0})
    for p in log:
        ym = f"{p['exit_ts'].year}-{p['exit_ts'].month:02d}"
        monthly[ym]["n"] += 1
        monthly[ym]["pnl"] += p["pnl"]
        monthly[ym]["r"] += p["R"]
        if p["R"] > 0: monthly[ym]["wins"] += 1
    print(f"    {'ay':<10} {'n':>3} {'W':>3} {'WR%':>5} {'sum_R':>7} {'PNL$':>10}")
    eq_running = 10_000.0
    for ym, s in sorted(monthly.items()):
        wr = s["wins"]/s["n"]*100 if s["n"] else 0
        eq_running += s["pnl"]
        print(f"    {ym:<10} {s['n']:>3} {s['wins']:>3} {wr:>4.0f}% {s['r']:>+6.2f} {s['pnl']:>+9.0f}  -> eq ${eq_running:>9,.0f}")

    # En karli/zararli 5
    print(f"\n  EN KARLI 5 TRADE:")
    sorted_pnl = sorted(log, key=lambda x: -x["pnl"])
    for p in sorted_pnl[:5]:
        print(f"    {p['entry_ts'].date()} {p['symbol']:<10} {p['side']:<5} {p['strategy']:<25}  R={p['R']:+.2f}  +${p['pnl']:,.0f}")
    print(f"\n  EN ZARARLI 5 TRADE:")
    for p in sorted_pnl[-5:]:
        print(f"    {p['entry_ts'].date()} {p['symbol']:<10} {p['side']:<5} {p['strategy']:<25}  R={p['R']:+.2f}  ${p['pnl']:,.0f}")

    # CSV export
    out_csv = ROOT / "reports" / "v096_backtest_2023_super.csv"
    out_csv.parent.mkdir(exist_ok=True)
    import csv
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["entry_ts","exit_ts","symbol","side","strategy","entry_price","notional","risk_$","R","pnl_$","exit_equity"])
        for p in sorted(log, key=lambda x: x["entry_ts"]):
            w.writerow([p["entry_ts"].strftime("%Y-%m-%d"), p["exit_ts"].strftime("%Y-%m-%d"),
                       p["symbol"], p["side"], p["strategy"], f"{p['entry_price']:.4f}",
                       f"{p['notional']:.2f}", f"{p['risk']:.2f}", f"{p['R']:.4f}",
                       f"{p['pnl']:.2f}", f"{p['exit_equity']:.2f}"])
    print(f"\n  CSV: {out_csv}")


if __name__ == "__main__":
    main()
