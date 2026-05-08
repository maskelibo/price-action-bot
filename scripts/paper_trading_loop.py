"""Faz 6 — Paper Trading Orchestrator: engulfing_continuation strategy.

Production config (passed walk-forward 2/3 gate):
  - Risk: %2 per trade
  - Leverage: 1x-5x dynamic based on confidence score
  - Symbols: 10 major crypto pairs (1d timeframe)
  - Risk breakers: daily %5, weekly %10, monthly %15
  - Max concurrent: 5 positions

Usage:
    python scripts/paper_trading_loop.py --once               # single shot
    python scripts/paper_trading_loop.py --once --dry-run     # dry run (no orders)
    python scripts/paper_trading_loop.py --watchdog           # continuous 00:30 UTC
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# Allow running from project root without installation
_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import numpy as np
import pandas as pd

from price_action.contracts import (
    OrderInstruction,
    Position,
    Reject,
    RiskedOrder,
    Signal,
    TPLevel,
    stable_hash,
)
from price_action.execution.ccxt_paper import CCXTPaperBroker
from price_action.execution.order_manager import OrderManager
from price_action.execution.paper_state import PaperState
from price_action.logging_config import logger
from price_action.risk.breaker import DDBreaker
from price_action.risk.sizing import AccountState, RiskOfficer
from price_action.settings import get_settings
from price_action.strategies.engulfing_continuation import (
    EngulfingContinuationStrategy,
    _default_manifest,
)


# =====================================================================
# Constants — Production config
# =====================================================================

SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "XRP/USDT",
    "DOGE/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "DOT/USDT",
]

TIMEFRAME = "1d"
LOOKBACK_BARS = 250
RISK_PER_TRADE = float(os.environ.get("PA_PAPER_RISK_PER_TRADE", "0.02"))
INITIAL_CAPITAL = float(os.environ.get("PA_PAPER_INITIAL_CAPITAL", "10000"))
MAX_CONCURRENT = 5

# Confidence → leverage tiers (from configs/risk.yaml)
CONFIDENCE_TIERS = [
    {"min": 0.00, "max": 0.32, "leverage": 1},
    {"min": 0.32, "max": 0.42, "leverage": 2},
    {"min": 0.42, "max": 0.52, "leverage": 3},
    {"min": 0.52, "max": 0.58, "leverage": 4},
    {"min": 0.58, "max": 1.01, "leverage": 5},
]

VENUE = "binance"
STRATEGY_ID = "engulfing_continuation_v1_faz6"

# Journal path
JOURNAL_PATH = _ROOT / "data" / "paper_journal.duckdb"
LOG_PATH = _ROOT / "logs" / "paper_trading.log"


# =====================================================================
# Confidence score — production formula
# =====================================================================

def compute_confidence_score(
    confluence_score: float,
    kaufman_er: float,
    rolling_sharpe: float,
    body_ratio: float,
) -> float:
    """Production confidence formula.

    0.35 * confluence_norm
    + 0.25 * kaufman_er          (already 0..1)
    + 0.25 * rolling_sharpe_norm (clipped 0..1)
    + 0.15 * body_ratio          (already 0..1)
    """
    # Confluence score from engulfing strategy is typically 1.5–2.5
    # Normalize to 0..1 by dividing by 3 (practical max)
    confluence_norm = min(max(confluence_score / 3.0, 0.0), 1.0)

    # KER is already 0..1
    kaufman_er_norm = min(max(kaufman_er, 0.0), 1.0)

    # Rolling Sharpe: normalize from (-2..+3) range to 0..1
    sharpe_norm = min(max((rolling_sharpe + 2.0) / 5.0, 0.0), 1.0)

    # Body ratio is already 0..1
    body_ratio_norm = min(max(body_ratio, 0.0), 1.0)

    score = (
        0.35 * confluence_norm
        + 0.25 * kaufman_er_norm
        + 0.25 * sharpe_norm
        + 0.15 * body_ratio_norm
    )
    return float(score)


def confidence_to_leverage(confidence: float) -> int:
    """Map confidence score to leverage tier."""
    for tier in CONFIDENCE_TIERS:
        if tier["min"] <= confidence < tier["max"]:
            return int(tier["leverage"])
    return 1  # fallback


# =====================================================================
# OHLCV fetch — with testnet & offline fallback
# =====================================================================

def _build_ccxt_exchange(dry_run: bool = False) -> Any | None:
    """Build CCXT exchange for data fetching. Returns None in dry-run / no-ccxt."""
    if dry_run or os.environ.get("PA_LLM_DRY_RUN") == "true":
        return None
    try:
        import ccxt  # type: ignore
        s = get_settings()
        api_key = os.environ.get("BINANCE_TESTNET_API_KEY", s.binance_api_key)
        api_secret = os.environ.get("BINANCE_TESTNET_API_SECRET", s.binance_api_secret)
        exchange = ccxt.binance({
            "enableRateLimit": True,
            "apiKey": api_key,
            "secret": api_secret,
        })
        # Use testnet for data fetching (public endpoint still works on mainnet)
        return exchange
    except Exception as exc:
        logger.bind(err=str(exc)).warning("paper_loop.ccxt_init_fail")
        return None


def fetch_ohlcv(symbol: str, timeframe: str, limit: int, exchange: Any | None) -> pd.DataFrame | None:
    """Fetch OHLCV bars. Returns None on failure (caller generates synthetic data in dry-run)."""
    if exchange is None:
        return None
    try:
        raw = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        if not raw:
            return None
        df = pd.DataFrame(raw, columns=["ts_ms", "open", "high", "low", "close", "volume"])
        df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms", utc=True)
        df["venue"] = VENUE
        df["symbol"] = symbol
        df["timeframe"] = timeframe
        df = df.drop(columns=["ts_ms"]).sort_values("ts").reset_index(drop=True)
        return df
    except Exception as exc:
        logger.bind(err=str(exc), symbol=symbol).warning("paper_loop.fetch_ohlcv_fail")
        return None


def _make_synthetic_ohlcv(symbol: str, n: int = 250) -> pd.DataFrame:
    """Deterministic synthetic OHLCV for dry-run / offline mode."""
    seed = abs(hash(symbol)) % (2 ** 31)
    rng = np.random.default_rng(seed)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    ts = pd.date_range(start, periods=n, freq="1D", tz="UTC")
    rets = rng.normal(0.0005, 0.025, size=n)
    close = 100.0 * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.001, 0.025, size=n))
    low = close * (1 - rng.uniform(0.001, 0.025, size=n))
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(500, 5000, size=n)
    df = pd.DataFrame({
        "ts": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "venue": VENUE,
        "symbol": symbol,
        "timeframe": TIMEFRAME,
    })
    return df


# =====================================================================
# Journal — DuckDB append
# =====================================================================

class PaperJournal:
    """Append-only DuckDB journal for paper trades."""

    def __init__(self, path: Path = JOURNAL_PATH) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_conn(self) -> Any:
        try:
            import duckdb  # type: ignore
            return duckdb.connect(str(self.path))
        except ImportError:
            return None

    def _init_db(self) -> None:
        conn = self._get_conn()
        if conn is None:
            logger.warning("paper_journal.duckdb_unavailable — journal disabled")
            return
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_trades (
                    trade_id TEXT PRIMARY KEY,
                    symbol TEXT,
                    side TEXT,
                    entry_ts TIMESTAMP,
                    entry_price DOUBLE,
                    quantity DOUBLE,
                    leverage INT,
                    confidence DOUBLE,
                    sl_price DOUBLE,
                    tp_price DOUBLE,
                    pattern_id TEXT,
                    confluence_score DOUBLE,
                    strategy_id TEXT,
                    dry_run BOOLEAN,
                    status TEXT,
                    exit_ts TIMESTAMP,
                    exit_price DOUBLE,
                    exit_reason TEXT,
                    realized_pnl DOUBLE,
                    r_multiple DOUBLE,
                    risk_check_result TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS paper_equity_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    ts TIMESTAMP,
                    equity DOUBLE,
                    open_positions INT,
                    realized_pnl_total DOUBLE,
                    daily_pnl DOUBLE
                )
            """)
            conn.close()
        except Exception as exc:
            logger.bind(err=str(exc)).error("paper_journal.init_fail")

    def log_trade_open(
        self,
        *,
        trade_id: str,
        symbol: str,
        side: str,
        entry_ts: datetime,
        entry_price: float,
        quantity: float,
        leverage: int,
        confidence: float,
        sl_price: float,
        tp_price: float,
        pattern_id: str,
        confluence_score: float,
        dry_run: bool,
    ) -> None:
        conn = self._get_conn()
        if conn is None:
            return
        try:
            conn.execute(
                """INSERT OR REPLACE INTO paper_trades
                   (trade_id, symbol, side, entry_ts, entry_price, quantity,
                    leverage, confidence, sl_price, tp_price, pattern_id,
                    confluence_score, strategy_id, dry_run, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open')""",
                [
                    trade_id, symbol, side, entry_ts, entry_price, quantity,
                    leverage, confidence, sl_price, tp_price, pattern_id,
                    confluence_score, STRATEGY_ID, dry_run,
                ],
            )
            conn.close()
        except Exception as exc:
            logger.bind(err=str(exc)).error("paper_journal.log_open_fail")

    def log_trade_close(
        self,
        *,
        trade_id: str,
        exit_ts: datetime,
        exit_price: float,
        exit_reason: str,
        realized_pnl: float,
        r_multiple: float,
    ) -> None:
        conn = self._get_conn()
        if conn is None:
            return
        try:
            conn.execute(
                """UPDATE paper_trades SET
                   status='closed', exit_ts=?, exit_price=?,
                   exit_reason=?, realized_pnl=?, r_multiple=?
                   WHERE trade_id=?""",
                [exit_ts, exit_price, exit_reason, realized_pnl, r_multiple, trade_id],
            )
            conn.close()
        except Exception as exc:
            logger.bind(err=str(exc)).error("paper_journal.log_close_fail")

    def log_equity_snapshot(
        self,
        *,
        ts: datetime,
        equity: float,
        open_positions: int,
        realized_pnl_total: float,
        daily_pnl: float,
    ) -> None:
        conn = self._get_conn()
        if conn is None:
            return
        try:
            conn.execute(
                """INSERT OR REPLACE INTO paper_equity_snapshots
                   (snapshot_id, ts, equity, open_positions, realized_pnl_total, daily_pnl)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                [
                    uuid.uuid4().hex[:16], ts, equity,
                    open_positions, realized_pnl_total, daily_pnl,
                ],
            )
            conn.close()
        except Exception as exc:
            logger.bind(err=str(exc)).error("paper_journal.snapshot_fail")

    def get_open_trade_ids(self) -> list[str]:
        conn = self._get_conn()
        if conn is None:
            return []
        try:
            rows = conn.execute(
                "SELECT trade_id FROM paper_trades WHERE status='open'"
            ).fetchall()
            conn.close()
            return [r[0] for r in rows]
        except Exception:
            return []

    def trade_exists_for_bar(self, symbol: str, entry_ts: datetime) -> bool:
        """Idempotency: check if trade for this exact bar already exists."""
        conn = self._get_conn()
        if conn is None:
            return False
        try:
            rows = conn.execute(
                "SELECT COUNT(*) FROM paper_trades WHERE symbol=? AND entry_ts=?",
                [symbol, entry_ts],
            ).fetchone()
            conn.close()
            return bool(rows and rows[0] > 0)
        except Exception:
            return False


# =====================================================================
# Active positions tracker (in-memory, reconciled from paper_state)
# =====================================================================

class ActivePositionTracker:
    """Track open positions with TP/SL for intraday check."""

    def __init__(self) -> None:
        # trade_id -> {symbol, side, entry_price, sl, tp, quantity, leverage, confidence}
        self._positions: dict[str, dict[str, Any]] = {}

    def add(self, trade_id: str, meta: dict[str, Any]) -> None:
        self._positions[trade_id] = meta

    def check_tp_sl(self, prices: dict[str, float]) -> list[tuple[str, str, float]]:
        """Return list of (trade_id, reason, exit_price) for hit TP/SL."""
        hits = []
        for trade_id, pos in list(self._positions.items()):
            symbol = pos["symbol"]
            price = prices.get(symbol)
            if price is None:
                continue
            side = pos["side"]
            sl = pos.get("sl")
            tp = pos.get("tp")
            if side == "long":
                if sl and price <= sl:
                    hits.append((trade_id, "sl_hit", price))
                elif tp and price >= tp:
                    hits.append((trade_id, "tp_hit", price))
            else:
                if sl and price >= sl:
                    hits.append((trade_id, "sl_hit", price))
                elif tp and price <= tp:
                    hits.append((trade_id, "tp_hit", price))
        return hits

    def remove(self, trade_id: str) -> None:
        self._positions.pop(trade_id, None)

    def count(self) -> int:
        return len(self._positions)

    def all_symbols(self) -> list[str]:
        return [p["symbol"] for p in self._positions.values()]


# =====================================================================
# Core daily run logic
# =====================================================================

def run_daily(
    *,
    dry_run: bool = False,
    log: Any = None,
) -> dict[str, Any]:
    """Execute one daily decision cycle.

    Returns a summary dict with signals found, orders placed, rejects.
    """
    if log is None:
        log = logger.bind(component="paper_loop")

    now_utc = datetime.now(timezone.utc)
    log.info(f"paper_loop.daily_run.start ts={now_utc.isoformat()} dry_run={dry_run}")

    # Setup
    s = get_settings()
    risk_yaml_path = s.configs_dir / "risk.yaml"

    # Ensure logs/data dirs
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Paper state — persists wallet & positions
    paper_state_path = _ROOT / "logs" / "execution" / "paper_state_faz6.json"
    paper_state = PaperState(
        path=paper_state_path,
        initial_balance_usdt=INITIAL_CAPITAL,
    )

    # Paper broker — force_offline=dry_run: in dry-run don't attempt live prices
    broker = CCXTPaperBroker(
        venue=VENUE,
        force_offline=dry_run,
        state=paper_state,
    )

    # Risk Officer with production config
    risk_officer = RiskOfficer.from_yaml(risk_yaml_path)
    # Override risk_per_trade to production %2
    risk_officer.config.position_sizing["risk_per_trade"] = RISK_PER_TRADE
    # Override max_open_positions to 5
    risk_officer.config.concentration_limits["max_open_positions"] = MAX_CONCURRENT
    # Override max_leverage to 5x
    risk_officer.config.leverage["max_leverage_per_symbol"] = 5
    risk_officer.config.leverage["max_portfolio_notional_x_equity"] = 5

    # Order manager
    om = OrderManager(broker=broker, risk_officer=None)  # We do risk check manually below

    # Strategy — use default manifest (Aşama B filters, production config)
    strategy = EngulfingContinuationStrategy(manifest=_default_manifest())

    # Journal
    journal = PaperJournal()

    # Active positions tracker (in-memory; reconcile from paper_state)
    tracker = ActivePositionTracker()

    # CCXT exchange for live data
    exchange = _build_ccxt_exchange(dry_run=dry_run)

    # ---- Account state snapshot ----
    balance = broker.fetch_balance()
    equity = float(balance.get("USDT", INITIAL_CAPITAL))
    open_positions = broker.fetch_positions()

    log.info(
        f"paper_loop.account equity={equity:.2f} USDT "
        f"open_positions={len(open_positions)}"
    )

    # ---- Daily equity snapshot ----
    journal.log_equity_snapshot(
        ts=now_utc,
        equity=equity,
        open_positions=len(open_positions),
        realized_pnl_total=paper_state.wallet.realized_pnl_total,
        daily_pnl=0.0,  # would need anchor tracking; simplified here
    )

    # ---- Risk Officer account state ----
    account_state = AccountState(
        equity_usdt=equity,
        free_margin_usdt=equity,
        open_positions=open_positions,
        realized_pnl_today=0.0,
        realized_pnl_week=0.0,
        realized_pnl_month=0.0,
        consecutive_losses=0,
    )

    # ---- Breaker check (before processing any signals) ----
    dd_breaker = DDBreaker(
        config={
            "daily_loss_pct": 0.05,
            "weekly_loss_pct": 0.10,
            "monthly_loss_pct": 0.15,
            "consecutive_losses": 6,
        },
        state_path=_ROOT / "logs" / "risk" / "breaker_state_faz6.json",
    )
    breaker_status = dd_breaker.snapshot(account_state)
    any_breaker = any(breaker_status.values())

    if any_breaker:
        log.warning(
            f"paper_loop.dd_breaker_active breakers={breaker_status} — "
            "NO new positions will be opened today"
        )

    # ---- Process each symbol ----
    signals_found: list[dict[str, Any]] = []
    orders_placed: list[dict[str, Any]] = []
    rejects: list[dict[str, Any]] = []

    open_symbol_set = {p.symbol for p in open_positions}

    for symbol in SYMBOLS:
        sym_log = log.bind(symbol=symbol)

        # Skip if max concurrent reached
        if len(open_positions) + len(orders_placed) >= MAX_CONCURRENT:
            sym_log.info("paper_loop.max_concurrent_reached — skip")
            break

        # Skip if already have a position in this symbol
        if symbol in open_symbol_set:
            sym_log.info("paper_loop.symbol_already_open — skip")
            continue

        # Fetch OHLCV
        df = fetch_ohlcv(symbol, TIMEFRAME, LOOKBACK_BARS, exchange)
        if df is None:
            if dry_run or os.environ.get("PA_LLM_DRY_RUN") == "true":
                df = _make_synthetic_ohlcv(symbol, n=LOOKBACK_BARS)
                sym_log.info("paper_loop.using_synthetic_ohlcv")
            else:
                sym_log.warning("paper_loop.ohlcv_fetch_fail — skip")
                continue

        if len(df) < 100:
            sym_log.warning(f"paper_loop.insufficient_bars bars={len(df)} — skip")
            continue

        # Prepare features + generate signals
        try:
            df_feat = strategy.prepare_features(df)
            signals = strategy.generate_signals(df_feat)
        except Exception as exc:
            sym_log.bind(err=str(exc)).error("paper_loop.strategy_error")
            continue

        # We only care about the LAST bar (today's closed bar)
        last_bar = df_feat.iloc[-1]
        last_ts = pd.Timestamp(last_bar["ts"]).to_pydatetime()

        # Filter signals to last bar only
        last_signals = [
            sig for sig in signals
            if abs((sig.ts - last_ts).total_seconds()) < 86400  # within today's bar
        ]

        if not last_signals:
            sym_log.info("paper_loop.no_signal_today")
            continue

        for sig in last_signals:
            # ---- Idempotency: skip if already traded this bar ----
            if journal.trade_exists_for_bar(symbol, sig.ts):
                sym_log.info(
                    f"paper_loop.idempotent_skip symbol={symbol} bar_ts={sig.ts.isoformat()}"
                )
                continue

            # ---- Extract metadata for confidence ----
            meta = sig.metadata or {}
            kaufman_er = float(meta.get("kaufman_er", 0.3))
            rolling_sharpe_val = float(last_bar.get("rolling_sharpe", 0.0) or 0.0)
            # Body ratio: compute from last bar
            open_p = float(last_bar.get("open", 0.0))
            close_p = float(last_bar.get("close", 0.0))
            high_p = float(last_bar.get("high", 0.0))
            low_p = float(last_bar.get("low", 0.0))
            rng_val = high_p - low_p
            body_ratio = abs(close_p - open_p) / rng_val if rng_val > 0 else 0.0

            # ---- Compute confidence score ----
            confidence = compute_confidence_score(
                confluence_score=sig.confluence_score,
                kaufman_er=kaufman_er,
                rolling_sharpe=rolling_sharpe_val,
                body_ratio=body_ratio,
            )

            # ---- Map confidence → leverage ----
            leverage = confidence_to_leverage(confidence)

            signal_info = {
                "symbol": symbol,
                "direction": sig.direction,
                "pattern_id": sig.pattern_id,
                "confluence_score": round(sig.confluence_score, 4),
                "confidence": round(confidence, 4),
                "leverage": leverage,
                "sl_price": round(sig.sl_price, 6),
                "tp_price": round(sig.tp_price, 6),
                "bar_ts": sig.ts.isoformat(),
            }
            signals_found.append(signal_info)

            sym_log.info(
                f"paper_loop.signal_found direction={sig.direction} "
                f"confluence={sig.confluence_score:.3f} confidence={confidence:.3f} "
                f"leverage={leverage}x sl={sig.sl_price:.4f} tp={sig.tp_price:.4f}"
            )

            # ---- Risk Officer check ----
            if any_breaker:
                rejects.append({**signal_info, "reason": "dd_breaker_active"})
                continue

            # Build production-adjusted account state
            current_positions = broker.fetch_positions()
            current_equity = float(broker.fetch_balance().get("USDT", equity))
            acc = AccountState(
                equity_usdt=current_equity,
                free_margin_usdt=current_equity,
                open_positions=current_positions,
            )

            market_price = close_p  # entry at next bar open ≈ current close (paper simplification)
            risked_or_reject = risk_officer.evaluate(
                sig,
                acc,
                market_price=market_price,
            )

            if isinstance(risked_or_reject, Reject):
                rejects.append({
                    **signal_info,
                    "reason": risked_or_reject.reason,
                    "detail": risked_or_reject.detail,
                })
                sym_log.warning(
                    f"paper_loop.risk_reject reason={risked_or_reject.reason}"
                )
                continue

            risked_order: RiskedOrder = risked_or_reject

            # Override leverage to confidence-based tier value
            # (RiskOfficer calculates its own; we override with conf-based)
            final_leverage = leverage

            # Compute adjusted quantity based on confidence-leverage
            # quantity = (equity * risk_pct) / sl_distance_dollar * leverage_factor
            sl_dist_dollar = abs(market_price - sig.sl_price)
            if sl_dist_dollar <= 0:
                rejects.append({**signal_info, "reason": "zero_sl_distance"})
                continue

            risk_dollar = current_equity * RISK_PER_TRADE
            quantity = (risk_dollar / sl_dist_dollar) * final_leverage

            # Reconstruct risked order with correct quantity
            tp1_price = sig.tp_price
            tp_levels = [TPLevel(price=tp1_price, fraction=1.0)]
            final_risked = RiskedOrder(
                signal=sig,
                quantity=quantity,
                notional_usdt=quantity * market_price,
                leverage=float(final_leverage),
                sl_price=sig.sl_price,
                tp_levels=tp_levels,
                margin_used=(quantity * market_price) / final_leverage,
                risk_budget_consumed=RISK_PER_TRADE,
                breakers_status=breaker_status,
                correlation_factor=risked_order.correlation_factor,
                manifest_hash=stable_hash({
                    "sig": sig.fingerprint(),
                    "conf": confidence,
                    "lev": final_leverage,
                }),
            )

            instruction = OrderInstruction(
                risked_order=final_risked,
                priority=confidence,
                order_type="market",
            )

            # ---- Submit or dry-run ----
            trade_id = f"paper-faz6-{uuid.uuid4().hex[:12]}"

            if dry_run:
                sym_log.info(
                    f"paper_loop.DRY_RUN would_place "
                    f"direction={sig.direction} qty={quantity:.6f} "
                    f"price={market_price:.4f} leverage={final_leverage}x "
                    f"notional={quantity * market_price:.2f} USDT "
                    f"trade_id={trade_id}"
                )
                orders_placed.append({
                    **signal_info,
                    "trade_id": trade_id,
                    "quantity": round(quantity, 8),
                    "market_price": market_price,
                    "notional": round(quantity * market_price, 2),
                    "status": "dry_run",
                })
                # Log to journal even in dry-run for consistency
                journal.log_trade_open(
                    trade_id=trade_id,
                    symbol=symbol,
                    side=sig.direction,
                    entry_ts=sig.ts,
                    entry_price=market_price,
                    quantity=quantity,
                    leverage=final_leverage,
                    confidence=confidence,
                    sl_price=sig.sl_price,
                    tp_price=sig.tp_price,
                    pattern_id=sig.pattern_id,
                    confluence_score=sig.confluence_score,
                    dry_run=True,
                )
                tracker.add(trade_id, {
                    "symbol": symbol,
                    "side": sig.direction,
                    "entry_price": market_price,
                    "sl": sig.sl_price,
                    "tp": sig.tp_price,
                    "quantity": quantity,
                    "leverage": final_leverage,
                    "confidence": confidence,
                })
            else:
                fill = om.submit(instruction)
                if hasattr(fill, "order_id"):
                    # Success
                    orders_placed.append({
                        **signal_info,
                        "trade_id": trade_id,
                        "order_id": fill.order_id,
                        "fill_price": fill.price,
                        "quantity": fill.quantity,
                        "slippage_bps": fill.slippage_bps,
                        "status": "filled",
                    })
                    journal.log_trade_open(
                        trade_id=trade_id,
                        symbol=symbol,
                        side=sig.direction,
                        entry_ts=sig.ts,
                        entry_price=fill.price,
                        quantity=fill.quantity,
                        leverage=final_leverage,
                        confidence=confidence,
                        sl_price=sig.sl_price,
                        tp_price=sig.tp_price,
                        pattern_id=sig.pattern_id,
                        confluence_score=sig.confluence_score,
                        dry_run=False,
                    )
                    tracker.add(trade_id, {
                        "symbol": symbol,
                        "side": sig.direction,
                        "entry_price": fill.price,
                        "sl": sig.sl_price,
                        "tp": sig.tp_price,
                        "quantity": fill.quantity,
                        "leverage": final_leverage,
                        "confidence": confidence,
                    })
                    sym_log.info(
                        f"paper_loop.order_filled order_id={fill.order_id} "
                        f"price={fill.price:.4f} qty={fill.quantity:.6f}"
                    )
                else:
                    reject: Reject = fill  # type: ignore
                    rejects.append({
                        **signal_info,
                        "reason": reject.reason,
                    })
                    sym_log.warning(f"paper_loop.order_rejected reason={reject.reason}")

    # ---- Summary ----
    summary = {
        "run_ts": now_utc.isoformat(),
        "dry_run": dry_run,
        "equity_usdt": equity,
        "signals_found": len(signals_found),
        "orders_placed": len(orders_placed),
        "rejects": len(rejects),
        "breakers_active": breaker_status,
        "signals": signals_found,
        "orders": orders_placed,
        "rejected": rejects,
    }

    # Write text log
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary, default=str) + "\n")
    except Exception as exc:
        log.bind(err=str(exc)).warning("paper_loop.log_write_fail")

    log.info(
        f"paper_loop.daily_run.done "
        f"signals={len(signals_found)} orders={len(orders_placed)} "
        f"rejects={len(rejects)}"
    )
    return summary


# =====================================================================
# Intraday TP/SL monitor (per-minute, runs in watchdog mode)
# =====================================================================

def check_tp_sl_intraday(
    broker: CCXTPaperBroker,
    tracker: ActivePositionTracker,
    journal: PaperJournal,
    dry_run: bool = False,
    log: Any = None,
) -> None:
    """Fetch current prices and close any positions that hit TP/SL."""
    if log is None:
        log = logger.bind(component="paper_loop_intraday")

    symbols_to_check = list(set(tracker.all_symbols()))
    if not symbols_to_check:
        return

    prices: dict[str, float] = {}
    for sym in symbols_to_check:
        price = broker._fetch_price(sym)
        if price:
            prices[sym] = price

    if not prices:
        return

    hits = tracker.check_tp_sl(prices)
    for trade_id, reason, exit_price in hits:
        log.info(f"paper_loop.{reason} trade_id={trade_id} price={exit_price}")
        tracker.remove(trade_id)
        if not dry_run:
            # Find matching position in broker state and close it
            for pos in broker.fetch_positions():
                pos_sym = prices.get(pos.symbol)
                if pos_sym:
                    broker.close_position(pos, exit_price=exit_price)
                    break
        # Log close to journal
        journal.log_trade_close(
            trade_id=trade_id,
            exit_ts=datetime.now(timezone.utc),
            exit_price=exit_price,
            exit_reason=reason,
            realized_pnl=0.0,  # simplified — actual from paper_state
            r_multiple=0.0,
        )


# =====================================================================
# Timing
# =====================================================================

def _seconds_until_next_run(target_hour: int = 0, target_minute: int = 30) -> float:
    """Compute seconds until next 00:30 UTC."""
    now = datetime.now(timezone.utc)
    target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


# =====================================================================
# Entry point
# =====================================================================

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Faz 6 Paper Trading Orchestrator — engulfing_continuation"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single daily decision cycle and exit",
    )
    parser.add_argument(
        "--watchdog",
        action="store_true",
        help="Continuous mode: run at 00:30 UTC each day",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute signals and log without submitting orders",
    )
    args = parser.parse_args()

    if not args.once and not args.watchdog:
        parser.print_help()
        sys.exit(1)

    log = logger.bind(component="paper_loop_main")

    if args.once:
        summary = run_daily(dry_run=args.dry_run, log=log)
        print(json.dumps(summary, indent=2, default=str))
        return

    # Watchdog mode
    log.info("paper_loop.watchdog_mode started — runs daily at 00:30 UTC")
    iteration = 0
    while True:
        iteration += 1
        try:
            summary = run_daily(dry_run=args.dry_run, log=log)
            log.info(
                f"paper_loop.watchdog_iter={iteration} "
                f"signals={summary['signals_found']} "
                f"orders={summary['orders_placed']}"
            )
        except Exception as exc:
            log.bind(err=str(exc)).error("paper_loop.watchdog_error")

        wait_secs = _seconds_until_next_run(0, 30)
        log.info(
            f"paper_loop.watchdog_sleeping wait_secs={wait_secs:.0f} "
            f"next_run={datetime.now(timezone.utc) + timedelta(seconds=wait_secs)}"
        )
        time.sleep(wait_secs)


if __name__ == "__main__":
    main()
