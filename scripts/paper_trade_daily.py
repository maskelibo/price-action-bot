"""Paper Trade Daily — MVP

Günlük 1d bar kapanışından sonra tüm TOP_11 stratejisi × 11 sym tarama,
sinyal üret, paper broker'a submit, journal'a kaydet.

Usage:
    python scripts/paper_trade_daily.py [--dry-run] [--days 1]

--dry-run: signals üret ama broker'a göndermeden log
--days N: son N gün için backfill (test/recovery)

Schedule (production):
    UTC 00:05 her gün — 1d bar kapanış sonrası tarama
"""
from __future__ import annotations

import argparse
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["PA_LOG_QUIET"] = "1"

import warnings
warnings.filterwarnings("ignore")

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from price_action.execution.ccxt_paper import CCXTPaperBroker
from price_action.execution.paper_state import PaperState
from price_action.execution.order_manager import OrderManager
from price_action.contracts import Signal, OrderInstruction, RiskedOrder
from price_action.backtest.engine import BacktestEngine
from price_action.backtest.lab import ProductionConfig
from scripts.run_real_backtest import _load_symbol_ohlcv
from scripts.v09_optimize_top10 import TOP_10

TOP_11 = TOP_10 + [("fvg_fill_reversal", "FVGFillReversalStrategy")]

SYMBOLS = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","ADA/USDT","AVAX/USDT","LINK/USDT","DOT/USDT","DOGE/USDT","XRP/USDT","MATIC/USDT"]

JOURNAL = ROOT / "data" / "paper_journal.duckdb"


def init_journal():
    """Journal tabloları (mevcut ise kullan)."""
    con = duckdb.connect(str(JOURNAL))
    con.execute("""
        CREATE TABLE IF NOT EXISTS paper_signals (
            signal_id VARCHAR PRIMARY KEY,
            ts TIMESTAMP,
            symbol VARCHAR,
            strategy VARCHAR,
            side VARCHAR,
            entry_price DOUBLE,
            sl_price DOUBLE,
            tp_price DOUBLE,
            confluence DOUBLE,
            status VARCHAR,
            notes VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS paper_equity_snapshots (
            snapshot_id VARCHAR PRIMARY KEY,
            ts TIMESTAMP,
            equity DOUBLE,
            open_positions INTEGER,
            realized_pnl_total DOUBLE,
            daily_pnl DOUBLE
        )
    """)
    con.commit()
    con.close()


def scan_signals(target_date: datetime) -> list[dict]:
    """target_date için tüm TOP_11 × 11 sym tarama, sinyal listesi döner."""
    signals = []
    print(f"\n[SCAN] target_date: {target_date.date()}")
    print(f"  TOP_11: {len(TOP_11)} strategy × {len(SYMBOLS)} sym = {len(TOP_11)*len(SYMBOLS)} cell")

    for module_name, class_name in TOP_11:
        try:
            mod = __import__(f"price_action.strategies.{module_name}", fromlist=[class_name, "_default_manifest"])
            cls = getattr(mod, class_name)
            manifest_fn = getattr(mod, "_default_manifest", None)
            if not manifest_fn:
                continue
            s = cls(manifest_fn())
        except Exception as e:
            print(f"  [SKIP] {module_name}: {e}")
            continue

        for sym in SYMBOLS:
            try:
                df = _load_symbol_ohlcv(sym, tf='1d')
                if df is None or df.empty:
                    continue
                df = df.sort_values('ts').reset_index(drop=True)
                df['symbol'] = sym
                df['venue'] = 'binance'
                df['timeframe'] = '1d'
                df['vol_z_pre'] = 0
                # Filter: only bars up to target_date (causal — no future)
                df_filtered = df[df['ts'].dt.date <= target_date.date()]
                if df_filtered.empty:
                    continue
                # Generate signals
                df_prep = s.prepare_features(df_filtered)
                sigs = s.generate_signals(df_prep)
                # Sadece son barda emit edilenler
                last_bar_ts = df_filtered['ts'].iloc[-1]
                for sig in sigs:
                    sig_ts = pd.Timestamp(sig.ts)
                    if sig_ts.tzinfo is None:
                        sig_ts = sig_ts.tz_localize('UTC')
                    if sig_ts.date() == target_date.date():
                        signals.append({
                            'ts': sig_ts,
                            'symbol': sym,
                            'strategy': module_name,
                            'side': sig.direction,
                            'entry_price': sig.metadata.get('atr14', 0) if sig.metadata else 0,
                            'sl_price': sig.sl_price,
                            'tp_price': sig.tp_price,
                            'confluence': sig.confluence_score,
                            'signal_obj': sig,
                        })
            except Exception as e:
                continue

    print(f"  Sinyal: {len(signals)}")
    return signals


def submit_to_paper_broker(signals: list[dict], dry_run: bool = False) -> int:
    """Sinyalleri paper broker'a submit, journal'a kaydet."""
    if not signals:
        print("[SUBMIT] Sinyal yok, atlandı.")
        return 0

    if dry_run:
        print(f"\n[DRY-RUN] {len(signals)} sinyal LOG ONLY (broker'a gönderilmedi):")
        con = duckdb.connect(str(JOURNAL))
        for s in signals:
            sig_id = uuid.uuid4().hex[:16]
            print(f"  {s['ts'].strftime('%Y-%m-%d')} {s['symbol']:<10} {s['strategy']:<35} {s['side']:<5} "
                  f"sl={s['sl_price']:.4f} tp={s['tp_price']:.4f}")
            con.execute("""
                INSERT INTO paper_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sig_id, s['ts'], s['symbol'], s['strategy'], s['side'],
                  float(s['entry_price']), float(s['sl_price']), float(s['tp_price']),
                  float(s['confluence']), 'dry_run', None))
        con.commit()
        con.close()
        return len(signals)

    # Paper broker setup
    state = PaperState(initial_balance_usdt=10000.0)
    broker = CCXTPaperBroker(state=state, force_offline=False)
    om = OrderManager(broker=broker)

    equity = state.wallet.balances.get('USDT', 10000.0)
    print(f"\n[SUBMIT] Paper broker initial equity: ${equity:.2f}")
    submitted = 0
    rejected = 0
    con = duckdb.connect(str(JOURNAL))
    for s in signals:
        sig_id = uuid.uuid4().hex[:16]
        try:
            # Risk Officer simulasyonu (basit: %2 risk)
            risk_dollar = equity * 0.02
            sl_dist = abs(float(s['signal_obj'].sl_price) - float(s['signal_obj'].metadata.get('atr14', 0) or 0))
            if sl_dist <= 0:
                continue
            qty = risk_dollar / sl_dist

            # OrderInstruction kur
            from price_action.contracts import RiskedOrder, TPLevel
            entry_p = float(s['signal_obj'].metadata.get('atr14', 0) or 0) or s['sl_price']
            # entry price as last close approx (signal'ın ts'sinde)
            entry_p_actual = (s['sl_price'] + s['tp_price']) / 2  # midpoint approx
            notional = qty * entry_p_actual
            risked = RiskedOrder(
                signal=s['signal_obj'],
                quantity=qty,
                notional_usdt=notional,
                leverage=3.0,
                sl_price=s['sl_price'],
                tp_levels=[TPLevel(price=s['tp_price'], fraction=1.0)],
                margin_used=notional / 3.0,
                risk_budget_consumed=risk_dollar,
            )
            instr = OrderInstruction(
                risked_order=risked,
                priority=1.0,
                order_type="market",
            )
            result = om.submit(instr)
            from price_action.contracts import Fill, Reject
            if isinstance(result, Fill):
                submitted += 1
                status = 'filled'
                notes = f"fill_price={result.price:.4f} qty={result.quantity:.4f} fee={result.fee_usdt:.2f}"
                print(f"  ✓ {s['symbol']:<10} {s['strategy']:<25} {s['side']:<5} qty={result.quantity:.4f} fill={result.price:.4f}")
            elif isinstance(result, Reject):
                rejected += 1
                status = 'rejected'
                notes = f"reason={result.reason}"
                print(f"  ✗ {s['symbol']:<10} {s['strategy']:<25} {s['side']:<5} REJECTED: {result.reason}")
            else:
                rejected += 1
                status = 'unknown'
                notes = f"type={type(result).__name__}"
                print(f"  ? {s['symbol']:<10} {s['strategy']:<25} {s['side']:<5} UNKNOWN: {type(result).__name__}")

            con.execute("""
                INSERT INTO paper_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sig_id, s['ts'], s['symbol'], s['strategy'], s['side'],
                  float(s['entry_price']), float(s['sl_price']), float(s['tp_price']),
                  float(s['confluence']), status, notes))
        except Exception as e:
            print(f"  ! {s['symbol']:<10} ERROR: {str(e)[:60]}")
            con.execute("""
                INSERT INTO paper_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sig_id, s['ts'], s['symbol'], s['strategy'], s['side'],
                  float(s['entry_price']), float(s['sl_price']), float(s['tp_price']),
                  float(s['confluence']), 'error', str(e)[:200]))
    con.commit()
    con.close()

    final_equity = state.wallet.balances.get('USDT', equity)
    print(f"\n[RESULT] Submitted: {submitted}, Rejected: {rejected}, Total: {len(signals)}")
    print(f"[STATE] Equity: ${final_equity:.2f}, Open positions: {len(state.wallet.positions)}")
    return submitted


def daily_run(target_date: datetime | None = None, dry_run: bool = False):
    """Tek günlük tarama + submit."""
    if target_date is None:
        target_date = datetime.now(timezone.utc) - timedelta(days=1)  # dün kapanışı
    init_journal()
    signals = scan_signals(target_date)
    submitted = submit_to_paper_broker(signals, dry_run=dry_run)

    # Equity snapshot
    if not dry_run and submitted > 0:
        con = duckdb.connect(str(JOURNAL))
        snap_id = uuid.uuid4().hex[:16]
        con.execute("""
            INSERT INTO paper_equity_snapshots VALUES (?, ?, ?, ?, ?, ?)
        """, (snap_id, datetime.now(timezone.utc), 10000.0, 0, 0.0, 0.0))
        con.commit()
        con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Sinyal üret ama broker'a gönderme")
    parser.add_argument("--days", type=int, default=1, help="Son N gün için backfill")
    args = parser.parse_args()

    print("=" * 80)
    print("PAPER TRADE DAILY")
    print("=" * 80)
    print(f"Mode: {'DRY-RUN (signals only)' if args.dry_run else 'LIVE PAPER'}")
    print(f"Days: {args.days}")

    today = datetime.now(timezone.utc)
    for d in range(args.days, 0, -1):
        target = today - timedelta(days=d)
        print(f"\n{'='*80}\nDay {target.date()}", flush=True)
        print("=" * 80, flush=True)
        daily_run(target, dry_run=args.dry_run)
        sys.stdout.flush()
