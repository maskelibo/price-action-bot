"""Mini-FIFO replay simulator — executed trade dump per neg month.

Lab.py production_replay()'in trade-selection logic'ini birebir kopyaliyor
(cooldown + max_concurrent + halt-OFF + pyramid R-adjust) AMA executed
trade'lerin listesini de döndürüyor. Replay total_return'ünü reprodüksiyon
sadece KARSILASTIRMA icin (yakin ama tam degil — equity-feedback sirasi
kucuk farklar dogurabilir).

Asil amac: post-filter trade'lerin side/strategy/symbol/R dagilimi.
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

from price_action.backtest.lab import ProductionConfig

POOL_15M = ROOT / "data" / "sec31_15m_pool.pkl"
YAML_15M = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"

TOP4 = {"vsa_climax_test", "brooks_failed_breakout",
        "anchored_vwap_reversal", "engulfing_continuation"}
SYMS = {"BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT",
        "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT", "XRP/USDT"}

NEG_MONTHS = ["2025-07", "2026-02", "2024-02", "2025-01", "2023-05", "2026-03", "2024-10"]


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


def mini_replay_executed(trades, cfg):
    """Lab.py production_replay clone — executed_trades de dondurur."""
    filtered = [
        t for t in trades
        if t["conf"] >= cfg.conf_min
        and t["strategy"] not in cfg.drop_strategies
        and t["symbol"] not in cfg.drop_symbols
    ]
    filtered.sort(key=lambda t: t["entry_ts"])
    if not filtered:
        return [], 0.0

    equity = cfg.initial_capital
    cash = cfg.initial_capital
    open_pos = []
    Rs = []
    last_entry = {}
    consecutive_losses = 0
    cool_until = None
    executed = []  # log: (entry_ts, exit_ts, symbol, side, strategy, R_final, peak_R, sl_pct, risk_d, notional)

    def close_due(now):
        nonlocal cash, equity, consecutive_losses, cool_until
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                R_use = p["R"]
                if cfg.pyramid_enabled and cfg.pyramid_triggers and cfg.pyramid_sizes:
                    peak_R_p = float(p.get("peak_R", R_use))
                    bonus = 0.0
                    slip = 0.0
                    SLIP = 0.06
                    for trig, sz in zip(cfg.pyramid_triggers, cfg.pyramid_sizes):
                        if peak_R_p >= float(trig):
                            bonus += float(sz) * max(0.0, R_use - float(trig))
                            slip += SLIP * float(sz)
                    R_use = R_use + bonus - slip
                pnl = p["risk"] * R_use
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                Rs.append(R_use)
                executed.append({
                    "entry_ts": p["entry_ts"], "exit_ts": p["exit_ts"],
                    "symbol": p["symbol"], "side": p["side"],
                    "strategy": p["strategy"], "R_raw": p["R"], "R_final": R_use,
                    "peak_R": p.get("peak_R", p["R"]),
                    "pnl": pnl, "risk": p["risk"], "notional": p["notional"],
                })
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
            continue
        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).total_seconds() < cfg.same_symbol_side_cooldown_days * 86400.0:
            continue
        if len(open_pos) >= cfg.max_concurrent:
            continue
        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0:
            continue
        # CONF-tier sizing
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
        # leverage
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
            "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
            "margin": margin, "notional": notional, "risk": risk_d,
            "R": t["R"], "symbol": t["symbol"], "side": t["side"],
            "strategy": t.get("strategy", ""),
            "peak_R": t.get("peak_R", t["R"]),
        })
    # close all remaining at last
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
        cash += p["margin"] + p["risk"] * R_use
        Rs.append(R_use)
        executed.append({
            "entry_ts": p["entry_ts"], "exit_ts": p["exit_ts"],
            "symbol": p["symbol"], "side": p["side"],
            "strategy": p["strategy"], "R_raw": p["R"], "R_final": R_use,
            "peak_R": p.get("peak_R", p["R"]),
            "pnl": p["risk"] * R_use, "risk": p["risk"], "notional": p["notional"],
        })
    final = cash
    return executed, final


def main():
    print("=" * 100)
    print("MINI-FIFO REPLAY — neg month executed trade dump")
    print("=" * 100)

    with POOL_15M.open("rb") as fh:
        pool_raw = pickle.load(fh)
    pool = [t for t in pool_raw if t.get("strategy") in TOP4 and t.get("symbol") in SYMS]
    pool.sort(key=lambda x: to_utc(x["entry_ts"]))

    cfg = ProductionConfig.from_yaml(str(YAML_15M))
    cfg = cfg.with_overrides(max_concurrent=20, same_symbol_side_cooldown_days=0)
    cfg = replace(cfg, btc_halt_calendar=None)
    print(f"\n[cfg] pyramid={cfg.pyramid_enabled} triggers={cfg.pyramid_triggers} sizes={cfg.pyramid_sizes}")
    print(f"      conf_min={cfg.conf_min} max_conc={cfg.max_concurrent} cooldown_days={cfg.same_symbol_side_cooldown_days}")
    print(f"      conf_tiers={cfg.confidence_risk_tiers}")

    for ym in NEG_MONTHS:
        start, end = month_bounds(ym)
        m_raw = [t for t in pool if start <= to_utc(t["entry_ts"]) < end]
        executed, final = mini_replay_executed(m_raw, cfg)
        n = len(executed)
        if n == 0:
            print(f"\n[{ym}] no executed (raw n={len(m_raw)})")
            continue
        ret = (final / cfg.initial_capital - 1) * 100
        sum_R_raw = sum(e["R_raw"] for e in executed)
        sum_R_final = sum(e["R_final"] for e in executed)
        amp = sum_R_final / sum_R_raw if sum_R_raw != 0 else 0

        print(f"\n=== {ym} | mini_ret={ret:+.2f}% | executed={n} | sum_R_raw={sum_R_raw:+.2f} | sum_R_final(pyr)={sum_R_final:+.2f} | amp={amp:.2f}x ===")

        # side breakdown (final R)
        side_R, strat_R, sym_R = defaultdict(list), defaultdict(list), defaultdict(list)
        for e in executed:
            side_R[e["side"]].append(e["R_final"])
            strat_R[e["strategy"]].append(e["R_final"])
            sym_R[e["symbol"]].append(e["R_final"])
        print(f"  SIDE  : " + " | ".join([f"{k}: n={len(v)} sum_R={sum(v):+.2f}" for k,v in sorted(side_R.items())]))
        print(f"  STRAT : " + " | ".join([f"{k}: n={len(v)} sum_R={sum(v):+.2f}" for k,v in sorted(strat_R.items(), key=lambda x: sum(x[1]))]))
        print(f"  SYM   : " + " | ".join([f"{k}: n={len(v)} sum_R={sum(v):+.2f}" for k,v in sorted(sym_R.items(), key=lambda x: sum(x[1]))]))

        # worst-K trade dump
        sorted_ex = sorted(executed, key=lambda x: x["R_final"])
        print(f"  WORST 10 trades:")
        for e in sorted_ex[:10]:
            ets = to_utc(e["entry_ts"]).strftime("%m-%d %H:%M")
            print(f"    {ets}  {e['symbol']:<10} {e['side']:<5} {e['strategy']:<25} R_raw={e['R_raw']:+.2f} R_final={e['R_final']:+.2f} peak_R={e['peak_R']:+.2f} pnl=${e['pnl']:+.0f}")
        # pyramid amplification check: trades where R_final << R_raw?
        amplified_losses = [e for e in executed if e["R_final"] < e["R_raw"] - 0.5]  # pyramid-cost net loss
        if amplified_losses:
            print(f"  PYRAMID-AMPLIFIED LOSSES: n={len(amplified_losses)} (R_final çok daha düştü)")
            for e in sorted(amplified_losses, key=lambda x: x["R_final"])[:5]:
                print(f"    {to_utc(e['entry_ts']).strftime('%m-%d %H:%M')} {e['symbol']:<10} {e['side']:<5} peak={e['peak_R']:+.2f} R_raw={e['R_raw']:+.2f} → R_final={e['R_final']:+.2f}")


if __name__ == "__main__":
    main()
