"""3-strateji portfolio backtest — per-strategy slot limit + capital partition.

Mimari:
- Engulfing: 3 slot, %50 capital share
- Donchian:  1 slot, %30 capital share
- Funding:   1 slot, %20 capital share (DEFER konfig — şimdilik kapalı)

Her stratejinin kendi confidence-based dynamic leverage'i var.
Tek shared $10K hesap üzerinde yıllık + DD ölçümü.
"""
from __future__ import annotations

import sys
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))


SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
           "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]


def _gather_engulfing_trades():
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import (
        EngulfingContinuationStrategy, _default_manifest as engulf_manifest,
    )
    from price_action.signals.filters import rolling_sharpe
    from scripts.run_real_backtest import _load_symbol_ohlcv

    manifest = engulf_manifest()
    out = []
    for sym in SYMBOLS:
        df = _load_symbol_ohlcv(sym, tf="1d")
        df = df.sort_values("ts").reset_index(drop=True)
        s = EngulfingContinuationStrategy(manifest)
        df_feats = s.prepare_features(df)
        df_feats["rolling_sharpe_60"] = rolling_sharpe(df_feats["close"], period=60)
        df_feats["body_ratio"] = (df_feats["close"] - df_feats["open"]).abs() / (df_feats["high"] - df_feats["low"]).replace(0, np.nan)
        ts_map = pd.to_datetime(df_feats["ts"], utc=True)
        def prov(*a, **k): return df_feats.copy()
        e = BacktestEngine(risk_officer=None, store_load=None)
        r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(), end=df["ts"].iloc[-1].to_pydatetime(), timeframe="1d", initial_capital=10_000.0, fees={"taker":0.00075,"maker":-0.00010}, slippage_bps=5.0, ohlcv_provider=prov)
        for _, t in r.trades.iterrows():
            ts = pd.Timestamp(t["entry_ts"])
            if ts.tzinfo is None: ts = ts.tz_localize("UTC")
            mask = ts_map < ts
            if not mask.any(): continue
            idx = ts_map[mask].index[-1]
            er = float(df_feats["kaufman_er"].iloc[idx]) if "kaufman_er" in df_feats else 0
            rs60 = float(df_feats["rolling_sharpe_60"].iloc[idx])
            body = float(df_feats["body_ratio"].iloc[idx])
            if np.isnan(rs60): rs60 = 0
            if np.isnan(body): body = 0
            cn = max(0.0, min(1.0, (float(t["confluence_score"]) - 1.5) / 1.5))
            en = max(0.0, min(1.0, er))
            rn = max(0.0, min(1.0, (rs60 + 1.0) / 2.0))
            bn = max(0.0, min(1.0, body))
            conf = 0.35 * cn + 0.25 * en + 0.25 * rn + 0.15 * bn
            if conf < 0.32: lev = 1.0
            elif conf < 0.42: lev = 2.0
            elif conf < 0.52: lev = 3.0
            elif conf < 0.58: lev = 4.0
            else: lev = 5.0
            out.append({
                "strategy": "engulfing", "symbol": sym,
                "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
                "entry_price": float(t["entry_price"]), "initial_sl": float(t["initial_sl"]),
                "R": float(t["realized_r_multiple"]), "lev": lev,
            })
    return out


def _gather_donchian_trades():
    """Donchian Tune D: 20/10, no-squeeze, ER 0.20."""
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.donchian_breakout import DonchianBreakoutStrategy
    from price_action.strategies.base import StrategyManifest
    from scripts.run_real_backtest import _load_symbol_ohlcv

    raw = {
        "name": "donchian_tune_d", "version": "1.0",
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [{
                "id": "donchian_breakout", "enabled": True, "weight": 1.0,
                "params": {
                    "donchian_entry_period": 20, "donchian_exit_period": 10,
                    "squeeze_required": False, "squeeze_lookback": 10,
                },
            }],
            "structure": {"swing": {"fractal_n": 2}, "support_resistance": {"lookback_bars": 60, "cluster_atr_multiplier": 0.5, "min_touches": 2}, "require_proximity_to_sr_atr": 0.0},
            "filters": {"atr_min_pct": 0.005, "kaufman_er_period": 14, "kaufman_er_min": 0.20},
            "confluence": {"method": "weighted_sum", "min_score": 0.5, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "stop_loss": {"method": "structural"},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    manifest = StrategyManifest.model_validate(raw)
    out = []
    for sym in SYMBOLS:
        df = _load_symbol_ohlcv(sym, tf="1d")
        df = df.sort_values("ts").reset_index(drop=True)
        s = DonchianBreakoutStrategy(manifest)
        df_feats = s.prepare_features(df)
        def prov(*a, **k): return df_feats.copy()
        e = BacktestEngine(risk_officer=None, store_load=None)
        try:
            r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(), end=df["ts"].iloc[-1].to_pydatetime(), timeframe="1d", initial_capital=10_000.0, fees={"taker":0.00075,"maker":-0.00010}, slippage_bps=5.0, ohlcv_provider=prov)
        except Exception as exc:
            print(f"  donchian {sym} skip: {exc}")
            continue
        for _, t in r.trades.iterrows():
            # Donchian'da basit confidence: konfluens score + ER
            conf = 0.5  # placeholder, donchian'da değişken yok
            lev = 3.0  # tüm donchian trade'leri lev 3x
            out.append({
                "strategy": "donchian", "symbol": sym,
                "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
                "entry_price": float(t["entry_price"]), "initial_sl": float(t["initial_sl"]),
                "R": float(t["realized_r_multiple"]), "lev": lev,
            })
    return out


def replay_partition(trades, allocations, daily_dd=0.05, weekly_dd=0.10, monthly_dd=0.15, fund=0.10):
    """Per-strategy slot + capital partition.

    allocations = {
      "engulfing": {"slots": 3, "capital_pct": 0.50, "risk_pct": 0.02},
      "donchian":  {"slots": 1, "capital_pct": 0.30, "risk_pct": 0.02},
    }
    Her strateji kendi capital partition'ı içinde çalışır.
    Toplam equity = tüm partition'ların toplamı.
    """
    if not trades:
        return None
    trades = sorted(trades, key=lambda t: t["entry_ts"])

    # Per-strategy state
    state = {}
    total_initial = 10_000.0
    for strat, cfg in allocations.items():
        state[strat] = {
            "equity": total_initial * cfg["capital_pct"],
            "cash": total_initial * cfg["capital_pct"],
            "open_pos": [],
            "slots": cfg["slots"],
            "risk_pct": cfg["risk_pct"],
            "Rs": [],
        }

    def total_equity():
        return sum(s["equity"] for s in state.values())

    fund_d = fund / 365
    eq_curve = [total_initial]

    # Anchors for breakers (global)
    daily_anchor = total_initial
    weekly_anchor = total_initial
    monthly_anchor = total_initial
    last_d = trades[0]["entry_ts"].date()
    last_w = trades[0]["entry_ts"].isocalendar()[1]
    last_m = trades[0]["entry_ts"].month
    blocked_until = None

    n_taken_per_strat = {s: 0 for s in allocations}
    n_skip_slot = {s: 0 for s in allocations}
    n_skip_cash = {s: 0 for s in allocations}

    def close_due(now):
        for s_state in state.values():
            still = []
            for p in s_state["open_pos"]:
                if p["exit_ts"] <= now:
                    holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
                    f = p["margin"] * p["leverage"] * fund_d * holding
                    pnl = p["risk"] * p["R"] * p["leverage"] - f
                    s_state["cash"] += p["margin"] + pnl
                    s_state["equity"] = s_state["cash"] + sum(q["margin"] for q in still)
                    s_state["Rs"].append(p["R"])
                else:
                    still.append(p)
            s_state["open_pos"] = still
        eq_curve.append(total_equity())

    for t in trades:
        close_due(t["entry_ts"])

        cur_eq = total_equity()
        cd = t["entry_ts"].date()
        cw = t["entry_ts"].isocalendar()[1]
        cm = t["entry_ts"].month
        if cd != last_d: daily_anchor = cur_eq; last_d = cd
        if cw != last_w: weekly_anchor = cur_eq; last_w = cw
        if cm != last_m: monthly_anchor = cur_eq; last_m = cm

        if blocked_until and t["entry_ts"] < blocked_until: continue
        if (daily_anchor - cur_eq) / max(daily_anchor, 1) >= daily_dd:
            blocked_until = t["entry_ts"] + timedelta(days=1); continue
        if (weekly_anchor - cur_eq) / max(weekly_anchor, 1) >= weekly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=7); continue
        if (monthly_anchor - cur_eq) / max(monthly_anchor, 1) >= monthly_dd:
            blocked_until = t["entry_ts"] + timedelta(days=30); continue

        strat = t["strategy"]
        if strat not in state:
            continue
        s_state = state[strat]
        if len(s_state["open_pos"]) >= s_state["slots"]:
            n_skip_slot[strat] += 1
            continue
        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"]
        if sl_pct <= 0: continue
        risk_d = s_state["equity"] * s_state["risk_pct"]
        notional = risk_d / sl_pct
        margin = notional / t["lev"]
        if margin > s_state["cash"]:
            n_skip_cash[strat] += 1
            continue
        s_state["cash"] -= margin
        s_state["open_pos"].append({
            "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
            "margin": margin, "risk": risk_d, "R": t["R"], "leverage": t["lev"],
        })
        n_taken_per_strat[strat] += 1

    # Force close
    for s_state in state.values():
        for p in s_state["open_pos"]:
            holding = (p["exit_ts"] - p["entry_ts"]).total_seconds() / 86400
            f = p["margin"] * p["leverage"] * fund_d * holding
            s_state["cash"] += p["margin"] + p["risk"] * p["R"] * p["leverage"] - f
            s_state["equity"] = s_state["cash"]
            s_state["Rs"].append(p["R"])
    eq_curve.append(total_equity())

    peak = eq_curve[0]
    max_dd = 0
    for v in eq_curve:
        if v > peak: peak = v
        dd = (v - peak) / peak
        if dd < max_dd: max_dd = dd

    final = total_equity()
    return {
        "final": final,
        "n_taken": n_taken_per_strat,
        "n_skip_slot": n_skip_slot,
        "n_skip_cash": n_skip_cash,
        "max_dd": max_dd,
        "per_strategy": {s: {"equity": st["equity"], "trades": len(st["Rs"])} for s, st in state.items()},
    }


def main():
    print("=== Multi-Strategy Portfolio (Engulfing + Donchian) ===")
    print("Engulfing trade'leri topluyor...")
    engulf = _gather_engulfing_trades()
    print(f"  {len(engulf)} trade")
    print("Donchian Tune D trade'leri topluyor...")
    donchian = _gather_donchian_trades()
    print(f"  {len(donchian)} trade")
    print()

    all_trades = engulf + donchian
    all_trades.sort(key=lambda t: t["entry_ts"])
    start = all_trades[0]["entry_ts"]

    # Senaryo 1: Engulfing solo (Production A baseline)
    sa = replay_partition(engulf, {"engulfing": {"slots": 5, "capital_pct": 1.0, "risk_pct": 0.02}})
    print(f"Senaryo 1 — Engulfing solo (5 slots, %100 cap, R%2):")
    print(f"  Final: ${sa['final']:,.2f}  yıllık {((sa['final']/10000)**(1/3)-1)*100:+.2f}%  DD {sa['max_dd']*100:+.1f}%")
    print(f"  Trade {sa['n_taken']}, slot skip {sa['n_skip_slot']}")
    print()

    # Senaryo 2: Engulfing 5/100% + Donchian 5/100% (no partition - geri dönüş)
    sb = replay_partition(all_trades, {"engulfing": {"slots": 5, "capital_pct": 0.5, "risk_pct": 0.02}, "donchian": {"slots": 5, "capital_pct": 0.5, "risk_pct": 0.02}})
    print(f"Senaryo 2 — Eşit partition (50/50, slots 5/5):")
    print(f"  Final: ${sb['final']:,.2f}  yıllık {((sb['final']/10000)**(1/3)-1)*100:+.2f}%  DD {sb['max_dd']*100:+.1f}%")
    print(f"  Trade {sb['n_taken']}, slot skip {sb['n_skip_slot']}")
    print()

    # Senaryo 3: Engulfing 3/70% + Donchian 1/30% (mantıklı partition)
    sc = replay_partition(all_trades, {"engulfing": {"slots": 3, "capital_pct": 0.70, "risk_pct": 0.02}, "donchian": {"slots": 1, "capital_pct": 0.30, "risk_pct": 0.02}})
    print(f"Senaryo 3 — Engulfing dominant (3/70%, donchian 1/30%):")
    print(f"  Final: ${sc['final']:,.2f}  yıllık {((sc['final']/10000)**(1/3)-1)*100:+.2f}%  DD {sc['max_dd']*100:+.1f}%")
    print(f"  Trade {sc['n_taken']}, slot skip {sc['n_skip_slot']}")
    print()

    # Senaryo 4: Engulfing 4/80% + Donchian 1/20%
    sd = replay_partition(all_trades, {"engulfing": {"slots": 4, "capital_pct": 0.80, "risk_pct": 0.02}, "donchian": {"slots": 1, "capital_pct": 0.20, "risk_pct": 0.02}})
    print(f"Senaryo 4 — Engulfing daha dominant (4/80%, donchian 1/20%):")
    print(f"  Final: ${sd['final']:,.2f}  yıllık {((sd['final']/10000)**(1/3)-1)*100:+.2f}%  DD {sd['max_dd']*100:+.1f}%")
    print(f"  Trade {sd['n_taken']}, slot skip {sd['n_skip_slot']}")
    print()

    # Karşılaştırma tablosu
    print("=" * 80)
    print(f"{'Senaryo':<45} {'final$':>10} {'yıllık':>9} {'DD':>7}")
    print("-" * 80)
    for label, r in [("Engulfing solo (Production A)", sa),
                     ("50/50 partition (slots 5/5)", sb),
                     ("70/30 partition (slots 3/1)", sc),
                     ("80/20 partition (slots 4/1)", sd)]:
        ret = ((r["final"]/10000)**(1/3)-1)*100
        print(f"{label:<45} ${r['final']:>9,.0f} {ret:>+7.2f}% {r['max_dd']*100:>+5.1f}%")


if __name__ == "__main__":
    main()
