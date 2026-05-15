"""Testnet Trade Daily — Binance Spot Testnet üzerinde gerçek paper trading.

paper_trade_daily.py'nin testnet versiyonu:
- Bizim sahte CCXTPaperBroker yerine BinanceSpotTestnet (gerçek matching engine)
- Sinyal üretimi aynı (TOP_11 × 11 sym tarama)
- Order ccxt ile testnet endpoint'ine gönderilir
- Fill detection real-time (Binance dönüş)
- State Binance hesabından fetch (paper_state.json değil)

Önemli: Spot only (futures yok testnet'te), leverage 1x

Usage:
    python scripts/testnet_trade_daily.py [--dry-run] [--days 1]
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# UTF-8 stdout (Windows charmap fix)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

os.environ["PA_LOG_QUIET"] = "1"
import warnings
warnings.filterwarnings("ignore")

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# .env load (python-dotenv: quote+comment trim, mevcut env korunur)
from dotenv import load_dotenv
load_dotenv(ROOT / ".env", override=False)

import ccxt

from scripts.paper_trade_daily import scan_signals, init_journal
from scripts.v09_optimize_top10 import TOP_10
from scripts.lib.risk_integration import (
    build_returns_df,
    build_signal_from_scan,
    build_spot_account_state,
    load_risk_officer,
)
from price_action.contracts import Position

JOURNAL = ROOT / "data" / "testnet_journal.duckdb"
SYMBOLS = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","ADA/USDT","AVAX/USDT","LINK/USDT","DOT/USDT","DOGE/USDT","XRP/USDT"]
RISK_YAML = ROOT / "configs" / "risk_balanced.yaml"
BREAKER_STATE = ROOT / "logs" / "risk" / "spot_breaker_state.json"
BREAKER_STATE.parent.mkdir(parents=True, exist_ok=True)
# MATIC removed — testnet'te listelenmeyebilir


def get_testnet_exchange():
    """Binance Spot Testnet ccxt instance."""
    api_key = os.getenv("BINANCE_TESTNET_API_KEY")
    api_secret = os.getenv("BINANCE_TESTNET_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError(".env'de BINANCE_TESTNET_API_KEY/SECRET yok")
    ex = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'spot',
            'warnOnFetchOpenOrdersWithoutSymbol': False,
            'adjustForTimeDifference': True,  # clock skew fix
            'recvWindow': 10000,
        },
    })
    ex.set_sandbox_mode(True)
    try:
        ex.load_time_difference()
    except Exception:
        pass
    return ex


def init_testnet_journal():
    """Testnet trade journal."""
    con = duckdb.connect(str(JOURNAL))
    con.execute("""
        CREATE TABLE IF NOT EXISTS testnet_signals (
            signal_id VARCHAR PRIMARY KEY,
            ts TIMESTAMP,
            symbol VARCHAR,
            strategy VARCHAR,
            side VARCHAR,
            sl_price DOUBLE,
            tp_price DOUBLE,
            confluence DOUBLE,
            status VARCHAR,
            order_id VARCHAR,
            fill_price DOUBLE,
            fill_qty DOUBLE,
            cost_usdt DOUBLE,
            notes VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS testnet_equity_snapshots (
            snapshot_id VARCHAR PRIMARY KEY,
            ts TIMESTAMP,
            usdt_balance DOUBLE,
            total_value_usdt DOUBLE,
            n_open_orders INTEGER,
            notes VARCHAR
        )
    """)
    con.commit()
    con.close()


def fetch_account_state(exchange):
    """Testnet hesap durumu."""
    bal = exchange.fetch_balance()
    usdt = bal['USDT']['total']
    # Toplam USDT-değer (tüm coinler current price ile)
    total_value = usdt
    for ccy, amt in bal['total'].items():
        if amt > 0 and ccy != 'USDT':
            try:
                ticker = exchange.fetch_ticker(f'{ccy}/USDT')
                total_value += amt * ticker['last']
            except Exception:
                pass
    open_orders = exchange.fetch_open_orders()
    return {
        'usdt_balance': usdt,
        'total_value_usdt': total_value,
        'n_open_orders': len(open_orders),
    }


def submit_to_testnet(signals: list[dict], dry_run: bool = False, max_pos_usdt: float = 500.0) -> int:
    """Sinyalleri Binance testnet'e gönder.

    max_pos_usdt: her trade max $X notional (testnet'te küçük başla)
    """
    if not signals:
        print("[SUBMIT] Sinyal yok, atlandı.")
        return 0

    exchange = get_testnet_exchange()
    state = fetch_account_state(exchange)
    print(f"\n[SUBMIT] Testnet hesap: ${state['usdt_balance']:.2f} USDT, total ${state['total_value_usdt']:.2f}, açık order {state['n_open_orders']}")

    if dry_run:
        print(f"\n[DRY-RUN] {len(signals)} sinyal LOG ONLY (testnet'e gönderilmedi):")
        for s in signals:
            print(f"  {s['ts'].strftime('%Y-%m-%d')} {s['symbol']:<10} {s['strategy']:<35} {s['side']:<5}")
        return 0

    # ===== RiskOfficer entegrasyonu (spot) =====
    risk_officer = load_risk_officer(yaml_path=RISK_YAML, breaker_state_path=BREAKER_STATE)
    return_universe = sorted(set(SYMBOLS))
    returns_df = build_returns_df(return_universe, days=90, market_db=ROOT / "data" / "market.duckdb")
    account = build_spot_account_state(exchange, journal_path=JOURNAL)
    breaker_snap = risk_officer.breaker.snapshot(account)
    print(f"[RISK] equity=${account.equity_usdt:.2f}, free=${account.free_margin_usdt:.2f}, "
          f"open_pos={len(account.open_positions)}, pnl_today=${account.realized_pnl_today:+.2f}, "
          f"breakers={ {k:v for k,v in breaker_snap.items() if v} or 'clear'}")

    submitted = 0
    rejected = 0
    con = duckdb.connect(str(JOURNAL))

    for s in signals:
        sig_id = uuid.uuid4().hex[:16]
        sym = s['symbol']

        # Sym filter — sadece testnet'te listed olanlar
        if sym not in [f'{x.replace("/", "")[:-4]}/USDT' for x in SYMBOLS] and sym not in SYMBOLS:
            print(f"  [SKIP] {sym} testnet'te yok")
            continue

        try:
            # Spot short skip (margin yok testnet'te) — RiskOfficer öncesi
            if s['side'] == 'short':
                print(f"  [SKIP-SHORT] {sym} {s['strategy']} short — spot testnet'te short yok")
                con.execute("""
                    INSERT INTO testnet_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (sig_id, s['ts'], sym, s['strategy'], s['side'], float(s['sl_price']),
                      float(s['tp_price']), float(s['confluence']), 'skip_short', None, None, None, None,
                      'spot testnet does not support short'))
                continue

            ticker = exchange.fetch_ticker(sym)
            cur_px = float(ticker['last'])

            # RiskOfficer.evaluate
            try:
                signal_obj = build_signal_from_scan(s, venue="binance")
            except Exception as build_err:
                print(f"  [SKIP-CONTRACT] {sym} signal_build_fail: {build_err}")
                continue

            decision = risk_officer.evaluate(
                signal_obj,
                account,
                market_price=cur_px,
                returns_df=returns_df,
            )

            if not hasattr(decision, "quantity"):
                reject_reason = getattr(decision, "reason", "unknown")
                reject_detail = getattr(decision, "detail", {}) or {}
                rejected += 1
                print(f"  [REJECT-RISK] {sym:<10} {s['strategy']:<25} {reject_reason} {reject_detail}")
                con.execute("""
                    INSERT INTO testnet_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (sig_id, s['ts'], sym, s['strategy'], s['side'], float(s['sl_price']),
                      float(s['tp_price']), float(s['confluence']), f'reject:{reject_reason}',
                      None, None, None, None, str(reject_detail)[:200]))
                continue

            risked = decision
            qty = float(risked.quantity)
            notional = float(risked.notional_usdt)

            # Spot: user cash hard cap + min notional + max_pos_usdt override
            usdt_avail = state['usdt_balance']
            order_usdt = min(notional, max_pos_usdt, usdt_avail * 0.95)
            if order_usdt < 10:
                rejected += 1
                print(f"  [SKIP-CASH] {sym} order=${order_usdt:.2f} <$10 min (cash=${usdt_avail:.2f})")
                con.execute("""
                    INSERT INTO testnet_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (sig_id, s['ts'], sym, s['strategy'], s['side'], float(s['sl_price']),
                      float(s['tp_price']), float(s['confluence']), 'reject:cash_below_min',
                      None, None, None, None, f'order_usdt={order_usdt:.2f}'))
                continue

            # qty'i cash limit'e göre yeniden ölçekle
            qty = order_usdt / cur_px

            # LONG market buy
            order = exchange.create_market_buy_order(sym, qty)
            submitted += 1
            filled_qty = float(order.get('filled', 0))
            cost = float(order.get('cost', 0))
            avg_px = float(order.get('average', 0))
            print(f"  [BUY] {sym:<10} {s['strategy']:<25} qty={filled_qty:.6f} cost=${cost:.2f} fill=${avg_px:.4f} id={order['id']}")
            con.execute("""
                INSERT INTO testnet_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sig_id, s['ts'], sym, s['strategy'], s['side'], float(s['sl_price']),
                  float(s['tp_price']), float(s['confluence']), 'filled', str(order['id']),
                  avg_px, filled_qty, cost, None))

            # IMMEDIATELY place OCO sell (auto SL/TP) — bot self-manages exit
            try:
                from scripts.testnet_add_oco import place_oco_for_long, init_oco_table
                init_oco_table()
                oco = place_oco_for_long(exchange, sym, filled_qty, float(s['tp_price']), float(s['sl_price']))
                if oco['status'] == 'placed':
                    print(f"    [OCO] tp=${oco['tp_price']:.4f} sl=${oco['sl_trigger']:.4f} list_id={oco['order_list_id']}")
                    con.execute("""
                        INSERT INTO testnet_oco_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (uuid.uuid4().hex[:16], datetime.now(timezone.utc), sig_id, sym, 'sell',
                          oco['qty'], oco['tp_price'], oco['sl_trigger'], oco['sl_limit'],
                          str(oco['orders'][0].get('orderId')) if oco['orders'] else None,
                          str(oco['orders'][1].get('orderId')) if len(oco['orders']) > 1 else None,
                          str(oco['list_client_id']), 'placed', None))
                else:
                    print(f"    [OCO] SKIP: {oco.get('reason')}")
            except Exception as oco_err:
                print(f"    [OCO] ERROR: {oco_err}")

            # Update state
            state['usdt_balance'] -= order.get('cost', 0)
            # In-memory account update — sonraki sinyalin RiskOfficer kararı için
            try:
                account.open_positions.append(
                    Position(
                        venue="binance",
                        symbol=sym,
                        side="long",
                        quantity=filled_qty,
                        entry_price=avg_px,
                        current_price=avg_px,
                        unrealized_pnl_usdt=0.0,
                        realized_pnl_usdt=0.0,
                        opened_at=datetime.now(timezone.utc),
                        strategy_id=s['strategy'],
                        last_updated=datetime.now(timezone.utc),
                    )
                )
                account.free_margin_usdt = max(0.0, account.free_margin_usdt - cost)
                account.equity_usdt = account.equity_usdt  # marked-to-mark aynı kalır
            except Exception:
                pass
        except Exception as e:
            rejected += 1
            print(f"  [ERR] {sym:<10} {type(e).__name__}: {str(e)[:80]}")
            con.execute("""
                INSERT INTO testnet_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sig_id, s['ts'], sym, s['strategy'], s['side'], float(s['sl_price']),
                  float(s['tp_price']), float(s['confluence']), 'error', None, None, None, None,
                  str(e)[:200]))

    con.commit()
    con.close()

    state_after = fetch_account_state(exchange)
    print(f"\n[RESULT] Submitted: {submitted}, Rejected: {rejected}, Total: {len(signals)}")
    print(f"[STATE] USDT: ${state_after['usdt_balance']:.2f}, Total value: ${state_after['total_value_usdt']:.2f}, Open orders: {state_after['n_open_orders']}")
    return submitted


def daily_run(target_date: datetime, dry_run: bool = False):
    init_journal()
    init_testnet_journal()
    signals = scan_signals(target_date)
    submitted = submit_to_testnet(signals, dry_run=dry_run)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Sinyal üret ama testnet'e gönderme")
    parser.add_argument("--days", type=int, default=1, help="Son N gün backfill")
    args = parser.parse_args()

    print("=" * 80)
    print("TESTNET TRADE DAILY (Binance Spot Testnet)")
    print("=" * 80)
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE TESTNET'}")
    print(f"Days: {args.days}")
    print(f"Note: Spot only — short sinyalleri SKIP edilir (margin trading yok testnet'te)")

    today = datetime.now(timezone.utc)
    for d in range(args.days, 0, -1):
        target = today - timedelta(days=d)
        print(f"\n{'='*80}\nDay {target.date()}\n{'='*80}", flush=True)
        daily_run(target, dry_run=args.dry_run)
        sys.stdout.flush()
