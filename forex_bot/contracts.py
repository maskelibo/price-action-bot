"""Forex-flavored contracts: Signal, RiskedOrder, Fill, Position, TradeRecord, Reject."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional


Side = Literal["long", "short"]
Session = Literal["asia", "london", "ny", "london_ny_overlap", "off"]


@dataclass
class Signal:
    pair: str
    side: Side
    ts: datetime
    entry_price: float
    sl_price: float
    tp_prices: list[float]
    confluence: float
    strategy: str
    session: Session
    pattern: str
    sl_pips: float
    rr: float
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class RiskedOrder:
    signal: Signal
    lots: float
    notional_quote: float
    risk_usd: float
    sl_price: float
    tp_prices: list[float]
    leverage: float
    decision_id: str
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class Fill:
    order_id: str
    pair: str
    side: Side
    lots: float
    fill_price: float
    ts: datetime
    spread_paid_pips: float
    commission_usd: float
    slippage_pips: float


@dataclass
class Position:
    pair: str
    side: Side
    lots: float
    entry_price: float
    current_price: float
    sl_price: float
    tp_prices: list[float]
    opened_at: datetime
    unrealized_usd: float


@dataclass
class TradeRecord:
    trade_id: str
    pair: str
    side: Side
    strategy: str
    session: Session
    pattern: str
    entry_ts: datetime
    exit_ts: datetime
    entry_price: float
    exit_price: float
    lots: float
    sl_price: float
    realized_usd: float
    realized_r: float
    win: bool
    close_reason: str  # tp1|tp2|runner|sl|time|news_close|breaker|weekend_gap
    spread_paid_pips: float
    commission_usd: float
    swap_usd: float
    slippage_pips: float
    duration_min: int


@dataclass
class Reject:
    signal: Signal
    rejected_by: str  # risk_officer | news_guard | session_filter | portfolio | breaker
    reason: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReproducibilityManifest:
    git_hash: str
    config_hash: str
    data_hash: str
    backtest_ts: datetime
    universe: list[str]
    timeframe: str
    cost_model: dict[str, Any]


PIP_SIZE = {
    "EURUSD": 0.0001, "GBPUSD": 0.0001, "AUDUSD": 0.0001, "NZDUSD": 0.0001,
    "USDCAD": 0.0001, "USDCHF": 0.0001, "EURGBP": 0.0001,
    "USDJPY": 0.01, "EURJPY": 0.01, "GBPJPY": 0.01,
}


def pip_value(pair: str, lots: float = 1.0, account_ccy: str = "USD") -> float:
    """USD value of 1 pip move for given lots. Approximation for JPY pairs at ~150."""
    standard_lot = 100_000.0
    pip = PIP_SIZE[pair]
    if pair.endswith("USD"):
        return pip * standard_lot * lots
    if pair.startswith("USD"):
        if pair == "USDJPY":
            return (pip * standard_lot * lots) / 150.0
        if pair == "USDCAD":
            return (pip * standard_lot * lots) / 1.35
        if pair == "USDCHF":
            return (pip * standard_lot * lots) / 0.90
    # JPY crosses
    if pair == "EURJPY" or pair == "GBPJPY":
        return (pip * standard_lot * lots) / 150.0
    if pair == "EURGBP":
        return (pip * standard_lot * lots) * 1.27
    return pip * standard_lot * lots


def price_to_pips(pair: str, price_distance: float) -> float:
    """Return SIGNED pips (preserves direction). Callers that need magnitude must abs() explicitly.

    CRITICAL: previous version returned abs() which combined with hand-rolled sign multiplier in
    engine produced wrong-sign PnL on long SL hits. All callers updated.
    """
    return price_distance / PIP_SIZE.get(pair, 0.0001)


def pip_distance_abs(pair: str, price_distance: float) -> float:
    """Convenience: magnitude in pips (for sl_pips, risk_pips computation)."""
    return abs(price_distance) / PIP_SIZE.get(pair, 0.0001)
