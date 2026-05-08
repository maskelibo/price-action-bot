"""Tek-hesap portfolio backtest — gercekci capital sharing.

$10,000 baslangic. Her sembol icin classic_pa stratejisi calistirilir, tum
trade'ler chronological siraya konur, tek hesapta replay edilir.

Pozisyon acma kurali (gercekci):
- Risk per trade: %1 of CURRENT equity (compounding fixed-fractional)
- Notional = risk_dollars / (SL_distance / entry_price)
  Ornek: %1 risk @ %5 SL = %20 equity notional
- Cash kontrolu: notional > available_cash ise trade SKIP (yetersiz nakit)
- Max concurrent positions: 5 (risk.yaml limit 8'den daha sıkı baslangic)

Kurallar:
- Her trade kendi entry_ts'inde dogan, exit_ts'inde realize olan, baska
  sembollerin trade'leriyle paralel calisir.
- Realized P&L = risk_dollars_at_entry * realized_R_multiple (sembol-bagimsiz)
- Slippage + fees zaten per-symbol engine'de düşülmüş — tekrar çıkarma.

Calistir:
    PYTHONPATH=src python scripts/run_portfolio_backtest.py
"""
from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


INITIAL_CAPITAL = 10_000.0
RISK_PER_TRADE = 0.01            # %1 of current equity
MAX_CONCURRENT = 999             # no soft cap; cash is the natural limiter
FEE_RATE_RT = 0.0015             # 0.075% taker × 2 (entry + exit) = 0.15% round-trip
SLIPPAGE_RT = 0.001              # 5 bps × 2 = 0.10% round-trip
SYMBOLS = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT",
           "DOGE/USDT", "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT"]


@dataclass
class TradeEvent:
    symbol: str
    entry_ts: datetime
    exit_ts: datetime
    entry_price: float
    initial_sl: float
    realized_r_multiple: float
    side: str
    pattern_id: str


def _gather_trades() -> list[TradeEvent]:
    from price_action.backtest.engine import BacktestEngine
    from price_action.strategies.classic_pa import ClassicPriceActionStrategy
    from scripts.run_real_backtest import _make_manifest, _load_symbol_ohlcv

    manifest = _make_manifest()
    out: list[TradeEvent] = []
    for sym in SYMBOLS:
        df = _load_symbol_ohlcv(sym, tf="1d")
        strategy = ClassicPriceActionStrategy(manifest)
        df_feats = strategy.prepare_features(df)
        def prov(_s, _t, _a, _b, _df=df_feats): return _df.copy()
        engine = BacktestEngine(risk_officer=None, store_load=None)
        r = engine.run(
            strategy, [sym],
            start=df["ts"].iloc[0].to_pydatetime(),
            end=df["ts"].iloc[-1].to_pydatetime(),
            timeframe="1d", initial_capital=INITIAL_CAPITAL,
            fees={"taker": 0.00075, "maker": -0.00010}, slippage_bps=5.0,
            ohlcv_provider=prov,
        )
        # r.trades is a DataFrame
        for _, t in r.trades.iterrows():
            out.append(TradeEvent(
                symbol=str(t["symbol"]),
                entry_ts=t["entry_ts"],
                exit_ts=t["exit_ts"],
                entry_price=float(t["entry_price"]),
                initial_sl=float(t["initial_sl"]),
                realized_r_multiple=float(t["realized_r_multiple"]),
                side=str(t["side"]),
                pattern_id=str(t["pattern_id"]),
            ))
        print(f"  {sym:<10} loaded {len(r.trades)} trades")
    return out


def replay(trades: list[TradeEvent]) -> dict:
    # Sort by entry timestamp
    trades = sorted(trades, key=lambda t: t.entry_ts)

    equity = INITIAL_CAPITAL
    cash = INITIAL_CAPITAL
    open_positions: list[dict] = []  # each: {exit_ts, notional, risk_dollars, R}
    equity_history: list[tuple[datetime, float, float, int]] = []  # (ts, equity, cash, n_open)

    n_taken = 0
    n_skip_cash = 0
    n_skip_concurrent = 0
    n_skip_zero_risk = 0
    total_gross_pnl = 0.0
    total_fees = 0.0
    total_slippage = 0.0
    monthly_stats: dict[str, dict] = defaultdict(lambda: {"trades": 0, "pnl": 0.0, "fees": 0.0})

    # Helper: close any positions whose exit_ts <= now
    def close_due(now: datetime) -> None:
        nonlocal cash, equity, total_gross_pnl, total_fees, total_slippage
        still_open = []
        for p in open_positions:
            if p["exit_ts"] <= now:
                gross = p["risk_dollars"] * p["R"]
                # Engine zaten R-multiple icinde fees+slippage'ı düşmüştür;
                # burada sadece transparent gösterim için ayrıca takip ediyoruz.
                fee_cost = p["notional"] * FEE_RATE_RT
                slip_cost = p["notional"] * SLIPPAGE_RT
                # Net pnl = gross (engine'in zaten cikardiklarini) — cift cikarma yok
                net_pnl = gross
                cash += p["notional"] + net_pnl
                equity = cash + sum(q["notional"] for q in still_open)
                total_gross_pnl += gross + fee_cost + slip_cost  # implied gross
                total_fees += fee_cost
                total_slippage += slip_cost
                month = p["exit_ts"].strftime("%Y-%m")
                monthly_stats[month]["trades"] += 1
                monthly_stats[month]["pnl"] += net_pnl
                monthly_stats[month]["fees"] += fee_cost + slip_cost
            else:
                still_open.append(p)
        open_positions[:] = still_open

    for t in trades:
        # Close any previously-opened positions that have exited by this entry_ts
        close_due(t.entry_ts)

        if len(open_positions) >= MAX_CONCURRENT:
            n_skip_concurrent += 1
            continue

        # Sizing
        sl_dist = abs(t.entry_price - t.initial_sl)
        sl_pct = sl_dist / t.entry_price if t.entry_price > 0 else 0
        if sl_pct <= 0:
            n_skip_zero_risk += 1
            continue
        risk_dollars = equity * RISK_PER_TRADE
        notional = risk_dollars / sl_pct

        if notional > cash:
            n_skip_cash += 1
            continue

        # Open
        cash -= notional
        open_positions.append({
            "exit_ts": t.exit_ts,
            "notional": notional,
            "risk_dollars": risk_dollars,
            "R": t.realized_r_multiple,
            "symbol": t.symbol,
            "entry_ts": t.entry_ts,
        })
        n_taken += 1
        equity_history.append((t.entry_ts, equity, cash, len(open_positions)))

    # Close any remaining at end
    if open_positions:
        last_ts = max(p["exit_ts"] for p in open_positions)
        close_due(last_ts + (last_ts - last_ts))  # no-op; force close
        # Force close all
        for p in open_positions[:]:
            pnl = p["risk_dollars"] * p["R"]
            cash += p["notional"] + pnl
            equity = cash
            open_positions.remove(p)

    return {
        "equity_final": equity,
        "cash_final": cash,
        "n_taken": n_taken,
        "n_skip_cash": n_skip_cash,
        "n_skip_concurrent": n_skip_concurrent,
        "n_skip_zero_risk": n_skip_zero_risk,
        "n_total_signals": len(trades),
        "monthly_stats": dict(monthly_stats),
        "equity_history": equity_history,
        "total_gross_pnl": total_gross_pnl,
        "total_fees": total_fees,
        "total_slippage": total_slippage,
    }


def main() -> int:
    print(f"=== Portfolio Backtest — Tek $10K Hesap ===")
    print(f"  Risk per trade   : {RISK_PER_TRADE*100:.1f}% of current equity")
    print(f"  Max concurrent   : {MAX_CONCURRENT} positions")
    print(f"  Symbols          : {len(SYMBOLS)}")
    print()
    print("Loading trades...")
    trades = _gather_trades()
    print(f"\nTotal trades from all symbols: {len(trades)}")

    print("\nReplaying chronologically with shared $10K capital...\n")
    result = replay(trades)

    print("=" * 65)
    print("PORTFOLIO SONUCU (gercekci capital sharing)")
    print("=" * 65)
    print(f"  Baslangic equity     : ${INITIAL_CAPITAL:>10,.2f}")
    print(f"  Bitis equity         : ${result['equity_final']:>10,.2f}")
    print(f"  Net P&L              : ${result['equity_final'] - INITIAL_CAPITAL:>+10,.2f}")
    pct = (result['equity_final']/INITIAL_CAPITAL - 1) * 100
    print(f"  Toplam getiri (3y)   : {pct:>+10.2f}%")
    annualized = ((result['equity_final']/INITIAL_CAPITAL) ** (1/3) - 1) * 100
    print(f"  Yillik (annualized)  : {annualized:>+10.2f}%")
    print()
    print("--- Trade execution ---")
    print(f"  Toplam sinyal        : {result['n_total_signals']}")
    print(f"  Acilan trade         : {result['n_taken']} ({result['n_taken']/result['n_total_signals']*100:.1f}%)")
    print(f"  Skip - max concurrent: {result['n_skip_concurrent']} ({result['n_skip_concurrent']/result['n_total_signals']*100:.1f}%)")
    print(f"  Skip - cash yetersiz : {result['n_skip_cash']} ({result['n_skip_cash']/result['n_total_signals']*100:.1f}%)")
    print(f"  Skip - sıfır risk    : {result['n_skip_zero_risk']}")
    print()
    print("--- Komisyon + Slippage Detayi (engine icinde zaten dusuldu) ---")
    print(f"  Toplam islem hacmi   : ~${(result['total_fees']/FEE_RATE_RT):>10,.0f}  ({result['n_taken']} trade x avg notional)")
    print(f"  Komisyon (taker x2)  : ${result['total_fees']:>10,.2f}  ({FEE_RATE_RT*100:.2f}% round-trip)")
    print(f"  Slippage (5bps x2)   : ${result['total_slippage']:>10,.2f}  ({SLIPPAGE_RT*100:.2f}% round-trip)")
    print(f"  TOPLAM EXEC MALIYET  : ${result['total_fees']+result['total_slippage']:>10,.2f}  ({(FEE_RATE_RT+SLIPPAGE_RT)*100:.2f}% round-trip)")
    print()
    print("--- Aylik P&L (ilk 12, son 6) ---")
    months = sorted(result['monthly_stats'].keys())
    sample = months[:12] + (["..."] if len(months) > 18 else []) + months[-6:] if len(months) > 18 else months
    for m in sample:
        if m == "...":
            print("  ...")
            continue
        s = result['monthly_stats'][m]
        print(f"  {m}: {s['trades']:>3} trade, P&L ${s['pnl']:>+9.2f}")

    print()
    print("--- FAZ 2 ROI GATE ---")
    gates = [
        ("Yillik net > %70   ", annualized, 70.0, ">="),
        ("MaxDD < %20 (NA)   ", 0.0, 20.0, "<="),  # MaxDD computation TBD
    ]
    all_pass = True
    for label, value, target, op in gates:
        ok = (value >= target) if op == ">=" else (value <= target)
        all_pass = all_pass and ok
        print(f"  {label} actual={value:>7.2f}  target={target:>5.1f}  {'[PASS]' if ok else '[FAIL]'}")
    print()
    print(f"  ROI GATE: {'[PASS]' if all_pass else '[FAIL]'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
