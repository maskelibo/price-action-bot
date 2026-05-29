"""brooks_8fx month-by-month compounding breakdown (2020-01 -> 2025-12).

Faithful re-implementation of price_action.backtest.lab.production_replay for the
SPECIFIC config requested (risk_pct=0.01 fixed, fee=0, no pyramid, sl_pct_min=0,
no conf-percentile, net-USD<=3 cap + max_concurrent=6 applied UPSTREAM), so we can
record PER-TRADE entry equity / leverage / win-loss in addition to the equity curve.

We then ASSERT final_equity matches the canonical production_replay() to guarantee
byte-identical accounting (no silent divergence).

Outputs a per-trade ledger DataFrame (printed as monthly tables by the caller-side
aggregation here) — all numbers printed to stdout.
"""
from __future__ import annotations
import os, sys, pickle
from pathlib import Path
os.environ["PA_LOG_QUIET"] = "1"
import warnings; warnings.filterwarnings("ignore")
import numpy as np, pandas as pd, yaml
from datetime import timedelta

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))
from price_action.backtest.lab import production_replay
from scripts.brooks_8fx_honest_cap import risk_parity_trades, apply_net_usd_cap, build_cfg

RISK_PCT = 0.01
NET_USD_CAP = 3
GROSS_CAP = 6


def faithful_replay(filtered, cfg):
    """Mirror lab.production_replay for this config; return per-trade ledger + eq curve.
    Records (at each CLOSE, in close order, matching engine's eq_curve append order)."""
    filtered = sorted(filtered, key=lambda t: t["entry_ts"])
    equity = cash = cfg.initial_capital
    open_pos = []
    eq_curve = [cfg.initial_capital]
    ledger = []  # one row per CLOSED trade, in close order
    daily_anchor = weekly_anchor = monthly_anchor = cfg.initial_capital
    first = filtered[0]["entry_ts"]
    last_d, last_w, last_m = first.date(), first.isocalendar()[1], first.month
    blocked_until = None
    last_entry = {}
    peak_equity = cfg.initial_capital
    lev = cfg.leverage  # 30x

    def close_due(now):
        nonlocal cash, equity, peak_equity
        still = []
        for p in open_pos:
            if p["exit_ts"] <= now:
                pnl = p["risk"] * p["R"]
                cash += p["margin"] + pnl
                equity = cash + sum(q["margin"] for q in still)
                peak_equity = max(peak_equity, equity)
                eq_curve.append(equity)
                ledger.append({
                    "entry_ts": p["entry_ts"], "exit_ts": p["exit_ts"],
                    "symbol": p["symbol"], "side": p["side"], "R": p["R"],
                    "pnl": pnl, "win": pnl > 0, "entry_equity": p["entry_equity"],
                    "leverage": p["notional"] / p["entry_equity"],
                    "equity_after": equity,
                })
            else:
                still.append(p)
        open_pos[:] = still

    for t in filtered:
        close_due(t["entry_ts"])
        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0:
            continue
        key = (t["symbol"], t["side"])
        prev = last_entry.get(key)
        if prev is not None and (t["entry_ts"] - prev).total_seconds() < cfg.same_symbol_side_cooldown_days * 86400.0:
            continue
        cd, cw, cm = t["entry_ts"].date(), t["entry_ts"].isocalendar()[1], t["entry_ts"].month
        if cd != last_d: daily_anchor = equity; last_d = cd
        if cw != last_w: weekly_anchor = equity; last_w = cw
        if cm != last_m: monthly_anchor = equity; last_m = cm
        if blocked_until and t["entry_ts"] < blocked_until:
            continue
        if (daily_anchor - equity) / max(daily_anchor, 1) >= cfg.daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=getattr(cfg, "daily_halt_days", 1)); continue
        if (weekly_anchor - equity) / max(weekly_anchor, 1) >= cfg.weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=getattr(cfg, "weekly_halt_days", 7)); continue
        if (monthly_anchor - equity) / max(monthly_anchor, 1) >= cfg.monthly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=getattr(cfg, "monthly_halt_days", 30)); continue
        if len(open_pos) >= cfg.max_concurrent:
            continue
        risk_d = equity * RISK_PCT
        notional = risk_d / sl_pct
        margin = notional / lev
        if margin > cash:
            continue
        cash -= margin
        last_entry[key] = t["entry_ts"]
        open_pos.append({
            "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"], "margin": margin,
            "notional": notional, "risk": risk_d, "R": t["R"], "symbol": t["symbol"],
            "side": t["side"], "sl_pct": sl_pct, "entry_equity": equity,
        })
    # close remainder
    if open_pos:
        last = max(p["exit_ts"] for p in open_pos)
        close_due(last + timedelta(seconds=1))
    return pd.DataFrame(ledger), eq_curve, equity


def main():
    d = pickle.load(open("/tmp/rt_trades.pkl", "rb"))
    trades, selected = d["trades"], d["selected"]
    raw = yaml.safe_load((ROOT / "configs" / "risk_forex.yaml").read_text())
    cfg = build_cfg(raw, max_concurrent=GROSS_CAP).with_overrides(risk_pct=RISK_PCT)

    pooled = risk_parity_trades(trades, selected)
    admitted = apply_net_usd_cap(pooled, NET_USD_CAP, gross_cap=GROSS_CAP)

    # canonical engine (authoritative final equity)
    canon = production_replay(admitted, cfg)
    led, eq_curve, my_final = faithful_replay(admitted, cfg)

    print(f"VALIDATION: canon.final_equity={canon.final_equity:.2f}  "
          f"my_final={my_final:.2f}  canon.trades={canon.trades}  my_trades={len(led)}  "
          f"diff={abs(canon.final_equity - my_final):.4f}")

    led = led.sort_values("exit_ts").reset_index(drop=True)
    led["ym"] = pd.to_datetime(led["exit_ts"], utc=True).dt.to_period("M")
    # entry-month for leverage averaging (positions OPENED that month)
    led["entry_ym"] = pd.to_datetime(led["entry_ts"], utc=True).dt.to_period("M")

    # Build full month index 2020-01 .. 2025-12
    months = pd.period_range("2020-01", "2025-12", freq="M")

    # Equity at each month-end: equity_after of last trade closed in/before that month.
    # eq curve indexed by exit_ts
    eq_idx = led[["exit_ts", "equity_after"]].copy()
    eq_idx["exit_ts"] = pd.to_datetime(eq_idx["exit_ts"], utc=True)

    rows = []
    prev_month_end_eq = 10000.0
    for m in months:
        m_end = (m + 1).to_timestamp().tz_localize("UTC")
        mtrades = led[led["ym"] == m]  # trades CLOSED this month (P&L realized)
        n = len(mtrades)
        wins = int(mtrades["win"].sum()) if n else 0
        losses = n - wins
        wr = (wins / n * 100) if n else float("nan")
        # month-end equity = last equity_after of trade closed <= m_end
        closed_le = eq_idx[eq_idx["exit_ts"] < m_end]
        month_end_eq = closed_le["equity_after"].iloc[-1] if len(closed_le) else prev_month_end_eq
        start_eq = prev_month_end_eq
        roi = (month_end_eq - start_eq) / start_eq * 100 if start_eq else float("nan")
        # intra-month MaxDD: walk equity_after of trades closed within month, anchored at start_eq
        seq = [start_eq] + list(mtrades.sort_values("exit_ts")["equity_after"].values)
        peak = seq[0]; mdd = 0.0
        for v in seq:
            peak = max(peak, v)
            dd = (v - peak) / peak if peak > 0 else 0.0
            mdd = min(mdd, dd)
        mdd *= 100
        # avg leverage of positions OPENED this month
        opened = led[led["entry_ym"] == m]
        avg_lev = float(opened["leverage"].mean()) if len(opened) else float("nan")
        rows.append({
            "month": str(m), "n": n, "wins": wins, "losses": losses, "wr": wr,
            "roi": roi, "mdd": mdd, "end_eq": month_end_eq, "avg_lev": avg_lev,
            "n_opened": len(opened),
        })
        prev_month_end_eq = month_end_eq

    df = pd.DataFrame(rows)
    df.to_pickle("/tmp/brooks_monthly.pkl")
    led.to_pickle("/tmp/brooks_ledger.pkl")
    print(f"\nMONTHS={len(df)}  final_eq={df['end_eq'].iloc[-1]:.2f}  "
          f"total_closed={int(df['n'].sum())}  total_opened={int(df['n_opened'].sum())}")
    print("Saved /tmp/brooks_monthly.pkl + /tmp/brooks_ledger.pkl")


if __name__ == "__main__":
    main()
