"""Aşama D — classic_pa (Aşama B) + engulfing_continuation kombinasyonu.

Tek $10K hesapta capital paylaşan portföy backtest. İki stratejiden gelen
sinyaller chronological siraya konur, max concurrent kontrolüyle replay edilir.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT))


INITIAL_CAPITAL = 10_000.0
RISK_PER_TRADE = 0.01
MAX_CONCURRENT = 5
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
           "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]


def _gather_classic_trades() -> list[dict]:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.classic_pa import ClassicPriceActionStrategy
    from scripts.run_real_backtest import _make_manifest, _load_symbol_ohlcv
    manifest = _make_manifest()
    out = []
    for sym in SYMBOLS:
        df = _load_symbol_ohlcv(sym, tf="1d")
        s = ClassicPriceActionStrategy(manifest)
        df_feats = s.prepare_features(df)
        def prov(*a, **k): return df_feats.copy()
        e = BacktestEngine(risk_officer=None, store_load=None)
        r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(), end=df["ts"].iloc[-1].to_pydatetime(), timeframe="1d", initial_capital=INITIAL_CAPITAL, fees={"taker":0.00075,"maker":-0.00010}, slippage_bps=5.0, ohlcv_provider=prov)
        for _, t in r.trades.iterrows():
            out.append({
                "strategy": "classic_pa",
                "symbol": sym, "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
                "entry_price": float(t["entry_price"]), "initial_sl": float(t["initial_sl"]),
                "R": float(t["realized_r_multiple"]),
            })
    return out


def _gather_engulfing_trades() -> list[dict]:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.engulfing_continuation import (
        EngulfingContinuationStrategy, _default_manifest as engulf_manifest,
    )
    from scripts.run_real_backtest import _load_symbol_ohlcv
    manifest = engulf_manifest()
    out = []
    for sym in SYMBOLS:
        df = _load_symbol_ohlcv(sym, tf="1d")
        s = EngulfingContinuationStrategy(manifest)
        df_feats = s.prepare_features(df)
        def prov(*a, **k): return df_feats.copy()
        e = BacktestEngine(risk_officer=None, store_load=None)
        r = e.run(s, [sym], start=df["ts"].iloc[0].to_pydatetime(), end=df["ts"].iloc[-1].to_pydatetime(), timeframe="1d", initial_capital=INITIAL_CAPITAL, fees={"taker":0.00075,"maker":-0.00010}, slippage_bps=5.0, ohlcv_provider=prov)
        for _, t in r.trades.iterrows():
            out.append({
                "strategy": "engulfing_continuation",
                "symbol": sym, "entry_ts": t["entry_ts"], "exit_ts": t["exit_ts"],
                "entry_price": float(t["entry_price"]), "initial_sl": float(t["initial_sl"]),
                "R": float(t["realized_r_multiple"]),
            })
    return out


def replay(trades: list[dict], priority: dict[str, int] | None = None) -> dict:
    """priority: dict mapping strategy name -> priority (lower = higher priority).
    Sıralama: (entry_ts asc, priority asc). Aynı bar'da hangi strateji önce geliyor?
    """
    if priority:
        trades = sorted(trades, key=lambda t: (t["entry_ts"], priority.get(t["strategy"], 99)))
    else:
        trades = sorted(trades, key=lambda t: t["entry_ts"])
    equity = INITIAL_CAPITAL
    cash = INITIAL_CAPITAL
    open_positions: list[dict[str, Any]] = []
    n_taken = 0
    n_skip_concurrent = 0
    n_skip_cash = 0
    fee_rt = 0.0015
    slip_rt = 0.001
    total_fees = 0.0
    total_slip = 0.0
    by_strategy = {"classic_pa": {"n":0,"pnl":0.0}, "engulfing_continuation": {"n":0,"pnl":0.0}}

    def close_due(now):
        nonlocal cash, equity, total_fees, total_slip
        still = []
        for p in open_positions:
            if p["exit_ts"] <= now:
                pnl = p["risk"] * p["R"]
                fees_cost = p["notional"] * fee_rt
                slip_cost = p["notional"] * slip_rt
                cash += p["notional"] + pnl
                equity = cash + sum(q["notional"] for q in still)
                total_fees += fees_cost
                total_slip += slip_cost
                by_strategy[p["strategy"]]["n"] += 1
                by_strategy[p["strategy"]]["pnl"] += pnl
            else:
                still.append(p)
        open_positions[:] = still

    for t in trades:
        close_due(t["entry_ts"])
        if len(open_positions) >= MAX_CONCURRENT:
            n_skip_concurrent += 1
            continue
        sl_pct = abs(t["entry_price"] - t["initial_sl"]) / t["entry_price"] if t["entry_price"] > 0 else 0
        if sl_pct <= 0:
            continue
        risk_d = equity * RISK_PER_TRADE
        notional = risk_d / sl_pct
        if notional > cash:
            n_skip_cash += 1
            continue
        cash -= notional
        open_positions.append({
            "exit_ts": t["exit_ts"], "notional": notional, "risk": risk_d,
            "R": t["R"], "strategy": t["strategy"],
        })
        n_taken += 1

    # Force close at end
    if open_positions:
        for p in open_positions[:]:
            pnl = p["risk"] * p["R"]
            cash += p["notional"] + pnl
            equity = cash
            by_strategy[p["strategy"]]["n"] += 1
            by_strategy[p["strategy"]]["pnl"] += pnl

    return {
        "equity_final": equity, "n_taken": n_taken, "n_total": len(trades),
        "n_skip_concurrent": n_skip_concurrent, "n_skip_cash": n_skip_cash,
        "fees": total_fees, "slippage": total_slip,
        "by_strategy": by_strategy,
    }


def main():
    print("=== Aşama D — classic_pa + engulfing_continuation kombinasyonu ===\n")
    print("Loading classic_pa trades...")
    cls = _gather_classic_trades()
    print(f"  {len(cls)} trade")
    print("Loading engulfing_continuation trades...")
    eng = _gather_engulfing_trades()
    print(f"  {len(eng)} trade")
    print()

    # 3 senaryo: sadece classic, sadece engulfing, kombine
    print("--- Senaryo 1: SADECE classic_pa ---")
    r1 = replay(cls)
    print(f"  $10K → ${r1['equity_final']:,.0f}  ({(r1['equity_final']/10000-1)*100:+.2f}% 3y, {((r1['equity_final']/10000)**(1/3)-1)*100:+.2f}% yıllık)")
    print(f"  açılan {r1['n_taken']}/{r1['n_total']}, skip concurrent {r1['n_skip_concurrent']}, cash {r1['n_skip_cash']}")

    print("\n--- Senaryo 2: SADECE engulfing_continuation ---")
    r2 = replay(eng)
    print(f"  $10K → ${r2['equity_final']:,.0f}  ({(r2['equity_final']/10000-1)*100:+.2f}% 3y, {((r2['equity_final']/10000)**(1/3)-1)*100:+.2f}% yıllık)")
    print(f"  açılan {r2['n_taken']}/{r2['n_total']}, skip concurrent {r2['n_skip_concurrent']}, cash {r2['n_skip_cash']}")

    print("\n--- Senaryo 3: KOMBİNE (FIFO entry_ts) ---")
    r3 = replay(cls + eng)
    print(f"  $10K → ${r3['equity_final']:,.0f}  ({(r3['equity_final']/10000-1)*100:+.2f}% 3y, {((r3['equity_final']/10000)**(1/3)-1)*100:+.2f}% yıllık)")
    print(f"  açılan {r3['n_taken']}/{r3['n_total']}, skip concurrent {r3['n_skip_concurrent']}, cash {r3['n_skip_cash']}")
    print(f"  Strateji başına:")
    for st, s in r3['by_strategy'].items():
        print(f"    {st:<25} closed={s['n']:>3} pnl=${s['pnl']:>+8,.2f}")

    print(f"\n--- Komisyon + Slippage (tüm senaryolar engine içinde dahil) ---")
    print(f"  Senaryo 3 — toplam exec maliyet: ${r3['fees']+r3['slippage']:,.2f}")

    print("\n--- Senaryo 4: KOMBİNE — engulfing PRIORITY ---")
    r4 = replay(cls + eng, priority={"engulfing_continuation": 0, "classic_pa": 1})
    print(f"  $10K → ${r4['equity_final']:,.0f}  ({(r4['equity_final']/10000-1)*100:+.2f}% 3y, {((r4['equity_final']/10000)**(1/3)-1)*100:+.2f}% yıllık)")
    print(f"  açılan {r4['n_taken']}/{r4['n_total']}, skip concurrent {r4['n_skip_concurrent']}")
    print(f"  Strateji başına:")
    for st, s in r4['by_strategy'].items():
        print(f"    {st:<25} closed={s['n']:>3} pnl=${s['pnl']:>+8,.2f}")

    print("\n--- KARSILASTIRMA TABLOSU ---")
    print(f"{'senaryo':<40} {'final$':>10} {'3y%':>8} {'yıllık%':>8} {'açılan':>7}")
    print("-"*80)
    for label, r in [
        ("Sadece classic_pa", r1),
        ("Sadece engulfing_continuation", r2),
        ("KOMBİNE FIFO", r3),
        ("KOMBİNE engulfing-priority", r4),
    ]:
        print(f"{label:<40} ${r['equity_final']:>9,.0f} {(r['equity_final']/10000-1)*100:>+7.2f}% {((r['equity_final']/10000)**(1/3)-1)*100:>+7.2f}% {r['n_taken']:>7}")


if __name__ == "__main__":
    main()
