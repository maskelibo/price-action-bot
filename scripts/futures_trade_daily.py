"""Futures Testnet Trade Daily — Binance USDM Futures Testnet.

Spot testnet'in (testnet.binance.vision) tam tersi:
  - testnet.binancefuture.com hesabi
  - LONG + SHORT (margin var)
  - Leverage 1-125x (biz 3x kullaniyoruz, balanced preset)
  - TP/SL ayri ayri yerlestirilir (TAKE_PROFIT_MARKET + STOP_MARKET)
  - reduceOnly=True → sadece pozisyonu kapatir
  - Backtest mantiginin %100'u burada calisir

Usage:
    python scripts/futures_trade_daily.py [--dry-run] [--days 1]
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# sys.stdout wrapping sadece __main__'de (import durumunda Streamlit'i bozar)
if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

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
import yaml

from scripts.paper_trade_daily import scan_signals, init_journal
from scripts.lib.risk_integration import (
    build_futures_account_state,
    build_returns_df,
    build_signal_from_scan,
    load_risk_officer,
)
from scripts.lib.cooldown import filter_signals_by_cooldown
from price_action.contracts import Position
from price_action.execution.capital_cap import load_capital_cap, check_warn_threshold
from price_action.execution.post_only_router import (
    SlippageExceededError,
    place_post_only_with_fallback,
)

# Multi-bot futures support — PA_BOT_NAME env var (atlas | phoenix | rsi2 | vwap | …)
# FIX 2026-05-27 (Faz 14.26): generic — herhangi bir bot adı per-bot journal alır.
# Önceki bug: rsi2/vwap (ve diğer yeni bot'lar) else dalına düşüp LIVE journal'a
# yazıyordu → DuckDB lock conflict, journal init fail, kritik veri kaybı riski.
_BOT_NAME = os.environ.get("PA_BOT_NAME", "").lower().strip()
if _BOT_NAME == "atlas":
    JOURNAL = ROOT / "data" / "futures_journal_atlas.duckdb"
    RISK_YAML = ROOT / "configs" / "risk_atlas_v203.yaml"
    BREAKER_STATE = ROOT / "logs" / "risk" / "futures_breaker_state_atlas.json"
elif _BOT_NAME == "phoenix":
    JOURNAL = ROOT / "data" / "futures_journal_phoenix.duckdb"
    RISK_YAML = ROOT / "configs" / "risk_phoenix_v204.yaml"
    BREAKER_STATE = ROOT / "logs" / "risk" / "futures_breaker_state_phoenix.json"
elif _BOT_NAME and _BOT_NAME not in ("default", ""):
    # Generic: PA_BOT_NAME=rsi2 → futures_journal_rsi2.duckdb
    # RISK_YAML burada placeholder (15m daemon PA_15M_CONFIG'ten okuyor, bu sadece 1d için)
    JOURNAL = ROOT / "data" / f"futures_journal_{_BOT_NAME}.duckdb"
    RISK_YAML = ROOT / "configs" / "risk_balanced.yaml"
    BREAKER_STATE = ROOT / "logs" / "risk" / f"futures_breaker_state_{_BOT_NAME}.json"
else:
    JOURNAL = ROOT / "data" / "futures_journal.duckdb"
    RISK_YAML = ROOT / "configs" / "risk_balanced.yaml"
    BREAKER_STATE = ROOT / "logs" / "risk" / "futures_breaker_state.json"
BREAKER_STATE.parent.mkdir(parents=True, exist_ok=True)
print(f"[futures_trade_daily] BOT={_BOT_NAME or 'default'} | journal={JOURNAL.name} | risk={RISK_YAML.name}")

SYMBOLS = ["BTC/USDT","ETH/USDT","SOL/USDT","BNB/USDT","ADA/USDT","AVAX/USDT","LINK/USDT","DOT/USDT","DOGE/USDT","XRP/USDT"]
# Fallback sabitler — artık RiskOfficer/risk_balanced.yaml'dan okunuyor.
# Sadece dry-run printlerinde gösterilmek için tutuluyor.
LEVERAGE = 3
RISK_PCT = 0.04
MAX_NOTIONAL_PCT = 0.30


def get_futures_exchange():
    """Binance USDM Futures Testnet ccxt instance.

    NOT: ccxt 4.5+ set_sandbox_mode futures icin deprecated, manuel URL override.
    """
    api_key = os.getenv("BINANCE_FUTURES_TESTNET_API_KEY")
    api_secret = os.getenv("BINANCE_FUTURES_TESTNET_API_SECRET")
    if not api_key or not api_secret:
        raise RuntimeError(".env'de BINANCE_FUTURES_TESTNET_API_KEY/SECRET yok")
    ex = ccxt.binance({
        'apiKey': api_key,
        'secret': api_secret,
        'enableRateLimit': True,
        'options': {
            'defaultType': 'future',
            'warnOnFetchOpenOrdersWithoutSymbol': False,
            'adjustForTimeDifference': True,
            'recvWindow': 10000,
            'fetchMarkets': ['linear'],  # sadece USDM futures, sapi/spot atla
        },
    })
    # Manuel testnet URL override (sandbox mode futures icin deprecated)
    TESTNET_FAPI = 'https://testnet.binancefuture.com/fapi'
    for ver, suffix in [('fapiPublic', '/v1'), ('fapiPublicV2', '/v2'), ('fapiPublicV3', '/v3'),
                        ('fapiPrivate', '/v1'), ('fapiPrivateV2', '/v2'), ('fapiPrivateV3', '/v3')]:
        ex.urls['api'][ver] = TESTNET_FAPI + suffix
    # ccxt fetch_currencies sapi.binance.com (mainnet) cagiriyor — testnet key reject ediliyor
    ex.has['fetchCurrencies'] = False
    # Time sync
    try:
        ex.load_time_difference()
    except Exception:
        pass
    return ex


def init_futures_journal():
    con = duckdb.connect(str(JOURNAL))
    con.execute("""
        CREATE TABLE IF NOT EXISTS futures_signals (
            signal_id VARCHAR PRIMARY KEY,
            ts TIMESTAMP,
            symbol VARCHAR,
            strategy VARCHAR,
            side VARCHAR,
            sl_price DOUBLE,
            tp_price DOUBLE,
            confluence DOUBLE,
            leverage INTEGER,
            status VARCHAR,
            order_id VARCHAR,
            fill_price DOUBLE,
            fill_qty DOUBLE,
            notional_usdt DOUBLE,
            margin_usdt DOUBLE,
            notes VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS futures_protection_orders (
            prot_id VARCHAR PRIMARY KEY,
            ts TIMESTAMP,
            signal_id VARCHAR,
            symbol VARCHAR,
            side VARCHAR,
            qty DOUBLE,
            tp_price DOUBLE,
            sl_price DOUBLE,
            tp_order_id VARCHAR,
            sl_order_id VARCHAR,
            status VARCHAR,
            notes VARCHAR
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS futures_equity_snapshots (
            snapshot_id VARCHAR PRIMARY KEY,
            ts TIMESTAMP,
            wallet_balance DOUBLE,
            unrealized_pnl DOUBLE,
            margin_balance DOUBLE,
            available_balance DOUBLE,
            n_positions INTEGER,
            n_open_orders INTEGER,
            notes VARCHAR
        )
    """)
    # SEC26.B-3 + SEC26.B-4: Closed-trade journal (consecutive loss counter + realized PnL).
    # Canonical writer: src/price_action/execution/trade_journal.TradeJournal.
    # Schema buradaki CREATE TradeJournal._ensure_schema() ile birebir tutuluyor.
    # CREATE IF NOT EXISTS idempotent — TradeJournal init aynı tabloyu yaratırsa konflikt yok.
    con.execute("""
        CREATE TABLE IF NOT EXISTS futures_trades_closed (
            trade_id TEXT PRIMARY KEY,
            ts_open TIMESTAMP,
            ts_close TIMESTAMP,
            sym TEXT,
            side TEXT,
            strategy TEXT,
            entry_price DOUBLE,
            exit_price DOUBLE,
            qty DOUBLE,
            realized_pnl_usdt DOUBLE,
            realized_r DOUBLE,
            win BOOLEAN,
            close_reason TEXT
        )
    """)
    con.execute("CREATE INDEX IF NOT EXISTS idx_ftc_close_ts ON futures_trades_closed (ts_close)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_ftc_sym ON futures_trades_closed (sym)")
    con.commit()
    con.close()


def fetch_futures_state(exchange):
    """Futures testnet hesap durumu."""
    raw = exchange.fapiPrivateV2GetAccount()
    wallet = float(raw.get('totalWalletBalance', 0))
    unrealized = float(raw.get('totalUnrealizedProfit', 0))
    margin_bal = float(raw.get('totalMarginBalance', wallet))
    available = float(raw.get('availableBalance', 0))

    # A3 fix: rate-limit ban'de (binance 418) silently boş liste dönerse pos_check
    # "tüm pozisyonlar kapanmış" sanıp journal'a yanlış 'filled' yazıyordu.
    # Şimdi her endpoint için 'ok' flag tutuyoruz; consumer rate-limit'te skip eder.
    positions_ok = True
    try:
        positions = exchange.fetch_positions()
        active_pos = [p for p in positions if abs(float(p.get('contracts', 0))) > 0]
    except Exception:
        active_pos = []
        positions_ok = False

    regular_orders_ok = True
    try:
        regular_orders = exchange.fapiPrivateGetOpenOrders()
    except Exception:
        regular_orders = []
        regular_orders_ok = False

    algo_orders_ok = True
    try:
        algo_orders = exchange.fapiPrivateGetOpenAlgoOrders()
        if not isinstance(algo_orders, list):
            algo_orders = []
    except Exception:
        algo_orders = []
        algo_orders_ok = False

    return {
        'wallet_balance': wallet,
        'unrealized_pnl': unrealized,
        'margin_balance': margin_bal,
        'available_balance': available,
        'n_positions': len(active_pos),
        'n_open_orders': len(regular_orders) + len(algo_orders),
        'n_regular_orders': len(regular_orders),
        'n_algo_orders': len(algo_orders),
        'positions': active_pos,
        'algo_orders': algo_orders,
        'positions_ok': positions_ok,
        'regular_orders_ok': regular_orders_ok,
        'algo_orders_ok': algo_orders_ok,
    }


def setup_leverage(exchange, symbol: str, leverage: int):
    """Sym icin leverage set et (idempotent)."""
    try:
        exchange.set_leverage(leverage, symbol)
        return True
    except Exception as e:
        # Already set ise OK
        if 'No need to change' in str(e) or 'leverage not modified' in str(e).lower():
            return True
        print(f"    [LEV] {symbol} set_leverage fail: {str(e)[:100]}")
        return False


def _is_margin_error(exc: Exception) -> bool:
    """Borsa hatasının margin/yetersiz fon kaynakli olup olmadığını kontrol et.

    SEC58-M6: ccxt InsufficientFunds + Binance -2019 (margin insufficient) +
    -1100 (invalid qty at lower leverage) yakalanir.
    """
    msg = str(exc).lower()
    margin_keywords = (
        "insufficient",
        "margin",
        "balance",
        "-2019",    # binance: insufficient margin
        "-1100",    # binance: qty precision / margin at lower leverage
        "notional must be no smaller",
        "not enough",
    )
    return any(kw in msg for kw in margin_keywords)


def _submit_order_with_adaptive_leverage(
    exchange,
    symbol: str,
    order_side: str,
    qty: float,
    base_leverage: int,
    *,
    post_only_enabled: bool = False,
    post_only_timeout_sec: int = 30,
    slippage_limit_bps: float = 25.0,
    target_price: float | None = None,
) -> tuple[dict, int, str]:
    """Market/post-only emir gönder; margin hatası varsa leverage düşür ve yeniden dene.

    SEC58-M6: Cascade: base_leverage → 2x → 1x (3 deneme max).
    Her denemede setup_leverage() + emir. Başarıda (order, kullanılan_lev, method) döner.
    Hiçbiri başaramadıysa son exception raise.

    Args:
        exchange: ccxt exchange instance.
        symbol: "BTC/USDT"
        order_side: "buy" | "sell"
        qty: base miktarı (leverage'dan bağımsız — notional değişmez).
        base_leverage: RiskOfficer'dan gelen ilk leverage teklifi.
        post_only_enabled: SEC26.B-5 flag.
        post_only_timeout_sec: post-only timeout.
        slippage_limit_bps: market fallback slip cap.
        target_price: post-only için hedef fiyat (None → caller'ın cur_px'i kullanılır).

    Returns:
        (order_dict, leverage_used, order_method)

    Raises:
        Exception: tüm cascade başarısız oldu.
    """
    # Cascade dizisi: istenen leverage'dan geriye doğru 1x'e kadar
    # Örnek: base=3 → [3, 2, 1]; base=1 → [1]
    cascade = list(dict.fromkeys([base_leverage, 2, 1]))  # deduped, sıralı azalan
    cascade = [lv for lv in cascade if 1 <= lv <= base_leverage]

    last_exc: Exception | None = None
    for attempt_lev in cascade:
        setup_leverage(exchange, symbol, attempt_lev)
        try:
            if post_only_enabled and target_price is not None:
                order, method = place_post_only_with_fallback(
                    exchange,
                    symbol=symbol,
                    side=order_side,
                    qty=qty,
                    target_price=target_price,
                    fallback_after_sec=post_only_timeout_sec,
                    slippage_limit_bps=slippage_limit_bps,
                )
            else:
                order = exchange.create_market_order(symbol, order_side, qty)
                method = "market_only"

            if attempt_lev != base_leverage:
                print(f"    [LEV_CASCADE] {symbol} leverage {base_leverage}x→{attempt_lev}x "
                      f"(margin insufficient retry #{cascade.index(attempt_lev) + 1})")
            return order, attempt_lev, method
        except SlippageExceededError:
            # Slippage aşımı — leverage cascade değil, direkt raise
            raise
        except Exception as exc:
            last_exc = exc
            if _is_margin_error(exc):
                if attempt_lev > 1:
                    print(f"    [LEV_CASCADE] {symbol} margin err at {attempt_lev}x, "
                          f"trying lower... ({str(exc)[:80]})")
                    continue
            # Margin dışı hata — direkt raise, cascade yok
            raise

    # Tüm cascade tükendi
    assert last_exc is not None
    raise last_exc


def place_protection_orders(exchange, symbol: str, side: str, qty: float,
                             tp_price: float, sl_price: float,
                             entry_price: float | None = None) -> dict:
    """LONG icin SELL TP+SL, SHORT icin BUY TP+SL.

    SEC26.A FIX: Multi-target TP placement — backtest engine parity.
    Backtest engine: TP1 (1R, %30 qty) + TP2 (1.5R, %30 qty) + SL (full remaining).
    Burada tp_price = sig.tp_price (strateji'nin ham TP'si = TP1 seviyesi ~1R).
    TP2 = entry + 1.5 * (entry - sl) (entry_price verilirse hesaplanir).

    Elestiri: Binance'a 3 ayri order:
      - TAKE_PROFIT_MARKET TP1 fiyatinda %30 qty (partial close)
      - TAKE_PROFIT_MARKET TP2 fiyatinda %30 qty (partial close)
      - STOP_MARKET sl_price'da tam qty (reduceOnly=True — partial fill sonra kalan qty kapatir)

    NOTE: Binance futures'ta reduceOnly partial orders race condition riski var.
    Eger TP1 fill olunca SL hala tam qty'de ise SL bir sonraki tick pozisyon boyutuna
    uyum saglar (reduceOnly = kalan pozisyon buyuklugunde). Bu kabul edilebilir.

    entry_price verilmezse eski davranis (tek TP + SL) korunur.
    """
    close_side = 'SELL' if side == 'long' else 'BUY'

    # Multi-target quantities — 25/25/50 (kullanıcı kararı 2026-05-20).
    # Backtest 30/30/40 idi; runner %40 → %50 büyütüldü ki trailing stop
    # (Faz 2) daha geniş runner ile trendi daha çok yakalasın.
    TP1_FRAC = 0.25   # %25 TP1'de kapat
    TP2_FRAC = 0.25   # %25 TP2'de kapat
    # Kalan %50 runner: trailing stop yönetir (daemon position_check)

    qty_tp1 = qty * TP1_FRAC
    qty_tp2 = qty * TP2_FRAC

    try:
        results = {}

        if entry_price is not None and entry_price > 0:
            # Multi-target mode
            sl_dist = abs(entry_price - sl_price)
            tp2_R = 1.5  # backtest engine default tp2_R
            if side == 'long':
                tp2_price = entry_price + tp2_R * sl_dist
            else:
                tp2_price = entry_price - tp2_R * sl_dist

            qty1_str = exchange.amount_to_precision(symbol, qty_tp1)
            qty2_str = exchange.amount_to_precision(symbol, qty_tp2)
            tp1_str = exchange.price_to_precision(symbol, tp_price)
            tp2_str = exchange.price_to_precision(symbol, tp2_price)
            sl_str = exchange.price_to_precision(symbol, sl_price)

            # TP1: partial close at 1R
            tp1_order = exchange.create_order(
                symbol=symbol,
                type='TAKE_PROFIT_MARKET',
                side=close_side,
                amount=float(qty1_str),
                params={
                    'stopPrice': tp1_str,
                    'reduceOnly': True,
                    'workingType': 'MARK_PRICE',
                }
            )
            # TP2: partial close at 1.5R
            tp2_order = exchange.create_order(
                symbol=symbol,
                type='TAKE_PROFIT_MARKET',
                side=close_side,
                amount=float(qty2_str),
                params={
                    'stopPrice': tp2_str,
                    'reduceOnly': True,
                    'workingType': 'MARK_PRICE',
                }
            )
            # SL: full qty reduceOnly (covers remaining runner)
            qty_full_str = exchange.amount_to_precision(symbol, qty)
            sl_order = exchange.create_order(
                symbol=symbol,
                type='STOP_MARKET',
                side=close_side,
                amount=float(qty_full_str),
                params={
                    'stopPrice': sl_str,
                    'reduceOnly': True,
                    'workingType': 'MARK_PRICE',
                }
            )
            return {
                'status': 'placed',
                'mode': 'multi_target',
                'tp_order_id': str(tp1_order.get('id')),     # primary TP (TP1) id
                'tp2_order_id': str(tp2_order.get('id')),    # TP2 id
                'sl_order_id': str(sl_order.get('id')),
                'tp_price': float(tp1_str),
                'tp2_price': float(tp2_str),
                'sl_price': float(sl_str),
                'qty_tp1': float(qty1_str),
                'qty_tp2': float(qty2_str),
                'qty_sl': float(qty_full_str),
            }
        else:
            # Legacy single-TP mode (backward compat)
            qty_str = exchange.amount_to_precision(symbol, qty)
            tp_str = exchange.price_to_precision(symbol, tp_price)
            sl_str = exchange.price_to_precision(symbol, sl_price)
            tp_order = exchange.create_order(
                symbol=symbol,
                type='TAKE_PROFIT_MARKET',
                side=close_side,
                amount=float(qty_str),
                params={
                    'stopPrice': tp_str,
                    'reduceOnly': True,
                    'workingType': 'MARK_PRICE',
                }
            )
            sl_order = exchange.create_order(
                symbol=symbol,
                type='STOP_MARKET',
                side=close_side,
                amount=float(qty_str),
                params={
                    'stopPrice': sl_str,
                    'reduceOnly': True,
                    'workingType': 'MARK_PRICE',
                }
            )
            return {
                'status': 'placed',
                'mode': 'single_target',
                'tp_order_id': str(tp_order.get('id')),
                'sl_order_id': str(sl_order.get('id')),
                'tp_price': float(tp_str),
                'sl_price': float(sl_str),
            }
    except Exception as e:
        return {'status': 'error', 'reason': f'{type(e).__name__}: {str(e)[:200]}'}


def submit_to_futures(signals: list[dict], dry_run: bool = False, max_pos_usdt: float | None = None,
                      execution_cfg: dict | None = None) -> int:
    """Sinyalleri Binance USDM Futures Testnet'e gönder.

    LONG ve SHORT ikisi de calisir (margin var).
    Risk-based sizing: notional = (equity * RISK_PCT) / sl_distance_pct
    Cap: notional <= equity * MAX_NOTIONAL_PCT

    Args:
        execution_cfg: configs/risk_balanced.yaml -> execution: bolumu.
                       SEC26.B-5 post-only limit gate (default DISABLED).
                       {
                         'post_only_limit_enabled': bool (default False),
                         'post_only_fallback_seconds': int (default 30),
                         'slippage_limit_bps': float (default 25.0),
                       }
    """
    if not signals:
        print("[SUBMIT] Sinyal yok, atlandı.")
        return 0

    # SEC26.B-5 — execution config (default OFF, replay etkisi sifir)
    execution_cfg = execution_cfg or {}
    post_only_enabled = bool(execution_cfg.get("post_only_limit_enabled", False))
    post_only_timeout_sec = int(execution_cfg.get(
        "post_only_fallback_seconds",
        execution_cfg.get("fallback_to_market_after_sec", 30),
    ))
    slippage_limit_bps = float(execution_cfg.get(
        "slippage_limit_bps",
        execution_cfg.get("max_slippage_bps", 25.0),
    ))
    if post_only_enabled:
        print(f"[EXECUTION] POST-ONLY enabled: timeout={post_only_timeout_sec}s, "
              f"slippage_limit={slippage_limit_bps:.1f}bps")
    else:
        print(f"[EXECUTION] MARKET-ONLY (post-only disabled, sec26.b-5 paper test pending)")

    exchange = get_futures_exchange()
    state = fetch_futures_state(exchange)
    print(f"\n[SUBMIT] Futures hesap: wallet=${state['wallet_balance']:.2f}, "
          f"available=${state['available_balance']:.2f}, "
          f"unrealized={state['unrealized_pnl']:+.2f}, "
          f"pozisyon={state['n_positions']}, açik order={state['n_open_orders']}")

    if dry_run:
        print(f"\n[DRY-RUN] {len(signals)} sinyal LOG ONLY:")
        for s in signals:
            print(f"  {s['ts'].strftime('%Y-%m-%d')} {s['symbol']:<10} {s['strategy']:<35} {s['side']:<5}")
        if max_pos_usdt is not None:
            print(f"[DRY-RUN][CAPITAL_CAP] enabled=True max={max_pos_usdt:.1f} USDT — "
                  f"live'da bu sınır her emir için kontrol edilir")
        return 0

    # ===== RiskOfficer entegrasyonu =====
    # Backtest +canlı parity: aynı YAML, aynı gate'ler, aynı breaker.
    risk_officer = load_risk_officer(yaml_path=RISK_YAML, breaker_state_path=BREAKER_STATE)
    open_sym_names = [p.get("symbol", "") for p in state.get("positions", []) or []]
    return_universe = sorted({*SYMBOLS, *(s for s in open_sym_names if s)})
    returns_df = build_returns_df(return_universe, days=90, market_db=ROOT / "data" / "market.duckdb")
    account = build_futures_account_state(state, journal_path=JOURNAL)
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

        if sym not in SYMBOLS:
            print(f"  [SKIP] {sym} symbol list'te yok")
            continue

        # SEC26.A FIX — Stale signal guard
        # Sinyal bar tarihi bugünden 2 günden eskiyse REJECT.
        # Backtest bar_ts = bar kapanış günü (UTC). Paper scan = dünkü gün (target_date = now - 1d).
        # Tolerans: 2 gün (1 gün bar close lag + 1 gün buffer).
        # 7 gün eski sinyal: piyasa o tarihten bu yana hareket etmiş → entry/SL anlamını yitirdi.
        try:
            sig_ts = s.get('ts')
            if sig_ts is not None:
                if hasattr(sig_ts, 'tzinfo'):
                    sig_date = sig_ts.date() if hasattr(sig_ts, 'date') else sig_ts.to_pydatetime().date()
                else:
                    sig_date = pd.Timestamp(sig_ts).date()
                today_utc = datetime.now(timezone.utc).date()
                stale_days = (today_utc - sig_date).days
                if stale_days > 2:
                    rejected += 1
                    print(f"  [REJECT-STALE] {sym:<10} {s['strategy']:<25} "
                          f"signal_age={stale_days}d (sig_ts={sig_date}, today={today_utc})")
                    con.execute("""
                        INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (sig_id, s['ts'], sym, s['strategy'], s['side'], float(s['sl_price']),
                          float(s['tp_price']), float(s['confluence']), 0, 'reject:stale_signal',
                          None, None, None, None, None, f'age={stale_days}d>2d'))
                    continue
        except Exception as stale_err:
            print(f"  [WARN] stale check err {sym}: {stale_err}")

        try:
            ticker = exchange.fetch_ticker(sym)
            cur_px = ticker['last']

            # 1) Signal contract + RiskOfficer.evaluate
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
                # Reject — Risk Officer reddetti
                reject_reason = getattr(decision, "reason", "unknown")
                reject_detail = getattr(decision, "detail", {}) or {}
                rejected += 1
                print(f"  [REJECT-RISK] {sym:<10} {s['strategy']:<25} {reject_reason} {reject_detail}")
                con.execute("""
                    INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (sig_id, s['ts'], sym, s['strategy'], s['side'], float(s['sl_price']),
                      float(s['tp_price']), float(s['confluence']), 0, f'reject:{reject_reason}',
                      None, None, None, None, None, str(reject_detail)[:200]))
                continue

            # 2) RiskedOrder — quantity ve leverage RiskOfficer'dan
            risked = decision
            qty = float(risked.quantity)
            notional = float(risked.notional_usdt)
            leverage_used = max(1, min(5, int(round(risked.leverage)))) or 1
            margin = notional / leverage_used if leverage_used > 0 else notional

            # 2b) Capital cap kontrolü — kısmi gönderme YOK, tamamen reddet
            if max_pos_usdt is not None and notional > max_pos_usdt:
                rejected += 1
                print(f"  [REJECT-CAP] {sym:<10} {s['strategy']:<25} "
                      f"notional=${notional:.2f} > cap=${max_pos_usdt:.2f} USDT")
                con.execute("""
                    INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (sig_id, s['ts'], sym, s['strategy'], s['side'], float(s['sl_price']),
                      float(s['tp_price']), float(s['confluence']), leverage_used,
                      'reject:capital_cap_exceeded', None, None, None, notional, margin,
                      f'cap={max_pos_usdt:.2f}'))
                continue

            # 3) Margin check (RiskOfficer free_margin'i hesapladı ama broker side ek check)
            if margin > state['available_balance'] * 0.9:
                rejected += 1
                print(f"  [SKIP-MARGIN] {sym} need=${margin:.2f}, have=${state['available_balance']:.2f}")
                con.execute("""
                    INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (sig_id, s['ts'], sym, s['strategy'], s['side'], float(s['sl_price']),
                      float(s['tp_price']), float(s['confluence']), leverage_used, 'reject:broker_margin',
                      None, None, None, notional, margin, None))
                continue

            # 4) Leverage + order
            # SEC58-M6: setup_leverage artık _submit_order_with_adaptive_leverage
            # içinde yapılıyor. Adaptive cascade: base_lev → 2x → 1x on margin error.
            order_side = 'buy' if s['side'] == 'long' else 'sell'
            order_method = 'market_only'

            try:
                order, leverage_used, order_method = _submit_order_with_adaptive_leverage(
                    exchange,
                    sym,
                    order_side,
                    qty,
                    leverage_used,
                    post_only_enabled=post_only_enabled,
                    post_only_timeout_sec=post_only_timeout_sec,
                    slippage_limit_bps=slippage_limit_bps,
                    target_price=cur_px,
                )
                # leverage_used cascade sonrası güncellenmiş olabilir → notional / margin yeniden
                margin = notional / leverage_used if leverage_used > 0 else notional
            except SlippageExceededError as slip_err:
                rejected += 1
                print(f"  [REJECT-SLIPPAGE] {sym:<10} {s['strategy']:<25} {slip_err}")
                con.execute(
                    """
                    INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (sig_id, s['ts'], sym, s['strategy'], s['side'], float(s['sl_price']),
                     float(s['tp_price']), float(s['confluence']), leverage_used,
                     f'reject:slippage_exceeded:{slip_err.slippage_bps:.1f}bps',
                     None, None, None, notional, margin,
                     f'limit={slippage_limit_bps:.1f}bps,actual={slip_err.slippage_bps:.1f}bps'),
                )
                continue

            submitted += 1
            filled_qty = float(order.get('filled', qty))
            avg_px = float(order.get('average', cur_px))

            print(f"  [{s['side'].upper()}] {sym:<10} {s['strategy']:<25} "
                  f"qty={filled_qty:.4f} notional=${notional:.2f} margin=${margin:.2f} "
                  f"fill=${avg_px:.4f} lev={leverage_used}x conf={s['confluence']:.2f} id={order['id']} "
                  f"method={order_method}")

            con.execute("""
                INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sig_id, s['ts'], sym, s['strategy'], s['side'], float(s['sl_price']),
                  float(s['tp_price']), float(s['confluence']), leverage_used, 'filled',
                  str(order['id']), avg_px, filled_qty, notional, margin, None))

            # 5) Protection orders (SEC26.A: multi-target TP — backtest engine parity)
            # entry_price=avg_px geçildiğinde TP1+TP2+SL mode aktif olur.
            prot = place_protection_orders(exchange, sym, s['side'], filled_qty,
                                           float(s['tp_price']), float(s['sl_price']),
                                           entry_price=avg_px)
            if prot['status'] == 'placed':
                mode = prot.get('mode', 'single_target')
                if mode == 'multi_target':
                    print(f"    [PROTECT-MULTI] tp1=${prot['tp_price']:.4f} "
                          f"tp2=${prot.get('tp2_price', 0):.4f} sl=${prot['sl_price']:.4f} "
                          f"tp1_id={prot['tp_order_id']} tp2_id={prot.get('tp2_order_id','?')} "
                          f"sl_id={prot['sl_order_id']}")
                    notes = f"mode=multi_target tp2={prot.get('tp2_price', 0):.4f} tp2_id={prot.get('tp2_order_id','')}"
                else:
                    print(f"    [PROTECT] tp=${prot['tp_price']:.4f} sl=${prot['sl_price']:.4f} "
                          f"tp_id={prot['tp_order_id']} sl_id={prot['sl_order_id']}")
                    notes = None
                con.execute("""
                    INSERT INTO futures_protection_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (uuid.uuid4().hex[:16], datetime.now(timezone.utc), sig_id, sym, s['side'],
                      filled_qty, prot['tp_price'], prot['sl_price'],
                      prot['tp_order_id'], prot['sl_order_id'], 'placed', notes))
            else:
                print(f"    [PROTECT] ERROR: {prot.get('reason')}")
                con.execute("""
                    INSERT INTO futures_protection_orders VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (uuid.uuid4().hex[:16], datetime.now(timezone.utc), sig_id, sym, s['side'],
                      filled_qty, float(s['tp_price']), float(s['sl_price']),
                      None, None, 'error', prot.get('reason')))

            # 6) In-memory state update — sonraki sinyalin RiskOfficer kararı için
            try:
                account.open_positions.append(
                    Position(
                        venue="binance",
                        symbol=sym,
                        side=s['side'],  # type: ignore[arg-type]
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
                account.free_margin_usdt = max(0.0, account.free_margin_usdt - margin)
            except Exception:
                pass
            state['available_balance'] -= margin
        except Exception as e:
            rejected += 1
            print(f"  [ERR] {sym:<10} {type(e).__name__}: {str(e)[:100]}")
            con.execute("""
                INSERT INTO futures_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sig_id, s['ts'], sym, s['strategy'], s['side'], float(s['sl_price']),
                  float(s['tp_price']), float(s['confluence']), LEVERAGE, 'error',
                  None, None, None, None, None, str(e)[:200]))

    con.commit()
    con.close()

    state_after = fetch_futures_state(exchange)
    print(f"\n[RESULT] Submitted: {submitted}, Rejected: {rejected}, Total: {len(signals)}")
    print(f"[STATE] Wallet=${state_after['wallet_balance']:.2f}, "
          f"available=${state_after['available_balance']:.2f}, "
          f"pozisyon={state_after['n_positions']}, açik order={state_after['n_open_orders']}")
    return submitted


def load_risk_yaml() -> dict:
    """risk_balanced.yaml'ı parse et (raw dict döndür)."""
    with open(RISK_YAML, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def daily_run(target_date: datetime, dry_run: bool = False):
    init_journal()
    init_futures_journal()

    # Capital cap — YAML'dan oku, PA_RUN_MODE=live değilse None
    risk_cfg = load_risk_yaml()
    cap_usdt = load_capital_cap(risk_cfg)
    if cap_usdt is not None:
        print(f"[CAPITAL_CAP] enabled=True max={cap_usdt:.1f} USDT "
              f"expires={risk_cfg.get('live_capital_cap', {}).get('cap_expires_at', 'N/A')}")
    else:
        print("[CAPITAL_CAP] inactive (paper/backtest mode veya disabled/expired)")

    signals = scan_signals(target_date)

    # Cooldown filter — lab.py semantik parity (same_symbol_side_cooldown_days)
    # Key: (symbol, side) — strategy farkı gözetilmez (lab.py birebir aynı kural)
    cooldown_days = int(
        risk_cfg.get("strategy_portfolio", {}).get("same_symbol_side_cooldown_days", 3)
    )
    if cooldown_days > 0:
        n_before = len(signals)
        signals = filter_signals_by_cooldown(
            signals,
            cooldown_days=cooldown_days,
            journal_path=JOURNAL,
            table="futures_signals",
        )
        n_after = len(signals)
        if n_before != n_after:
            print(
                f"[COOLDOWN] {n_before - n_after}/{n_before} signal rejected "
                f"(cooldown={cooldown_days}d, key=sym+side)"
            )
        else:
            print(f"[COOLDOWN] No signals in cooldown (cooldown={cooldown_days}d)")
    else:
        print("[COOLDOWN] Disabled (cooldown_days=0)")

    # SEC26.B-5 — execution config (post-only limit + slippage gate, default OFF)
    execution_cfg = risk_cfg.get("execution", {}) or {}
    submit_to_futures(signals, dry_run=dry_run, max_pos_usdt=cap_usdt,
                      execution_cfg=execution_cfg)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--days", type=int, default=1)
    args = parser.parse_args()

    print("=" * 80)
    print("FUTURES TRADE DAILY (Binance USDM Futures Testnet)")
    print("=" * 80)
    print(f"Mode: {'DRY-RUN' if args.dry_run else 'LIVE TESTNET'}")
    print(f"Leverage: {LEVERAGE}x | Risk: {RISK_PCT*100:.1f}% | Max notional: {MAX_NOTIONAL_PCT*100:.0f}% wallet")
    print(f"LONG + SHORT ikisi de calisir, TP+SL Binance tarafinda otomatik")

    today = datetime.now(timezone.utc)
    for d in range(args.days, 0, -1):
        target = today - timedelta(days=d)
        print(f"\n{'='*80}\nDay {target.date()}\n{'='*80}", flush=True)
        daily_run(target, dry_run=args.dry_run)
        sys.stdout.flush()
