"""Departmanlar arası contract — tek doğru kaynak.

Bu dosyadaki sınıflar tüm departmanların ortak dilidir. Değişiklik ADR ister.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def _utcnow() -> datetime:
    """Timezone-aware UTC now. Pydantic default_factory için."""
    return datetime.now(timezone.utc)

# =====================================================================
# Yardımcılar
# =====================================================================

Direction = Literal["long", "short"]
Mode = Literal["backtest", "paper", "live"]
TF = Literal["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w"]


def stable_hash(payload: Any) -> str:
    """Reproducibility için kararlı hash."""
    text = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# =====================================================================
# Manifest
# =====================================================================

class ReproducibilityManifest(BaseModel):
    """Her trade / backtest sonucu bu manifestoyla etiketlenir."""

    model_config = ConfigDict(frozen=True)

    git_hash: str
    config_hash: str
    data_hash: str
    code_hash: str
    created_at: datetime = Field(default_factory=_utcnow)

    @property
    def composite(self) -> str:
        return f"{self.git_hash[:8]}-{self.config_hash[:8]}-{self.data_hash[:8]}"


# =====================================================================
# Signal Engineering
# =====================================================================

class Signal(BaseModel):
    """Signal Chief'ten Risk Officer'a gönderilen olay."""

    model_config = ConfigDict(frozen=True)

    ts: datetime                     # bar kapanış ts'i
    venue: str
    symbol: str
    timeframe: TF
    direction: Direction
    pattern_id: str
    confluence_score: float
    sl_price: float
    tp_price: float
    suggested_size_atr: float        # ATR cinsinden risk genişliği
    metadata: dict[str, Any] = Field(default_factory=dict)
    manifest_hash: str = ""

    def fingerprint(self) -> str:
        """İdempotency anahtarı."""
        return stable_hash(
            (self.ts.isoformat(), self.venue, self.symbol, self.timeframe,
             self.direction, self.pattern_id, round(self.sl_price, 8))
        )


# =====================================================================
# Risk Management
# =====================================================================

class TPLevel(BaseModel):
    model_config = ConfigDict(frozen=True)
    price: float
    fraction: float                  # toplam pozisyonun ne kadarı bu seviyede kapanıyor (0..1)


class RiskedOrder(BaseModel):
    """Risk Officer onayından geçmiş emir adayı."""

    model_config = ConfigDict(frozen=True)

    signal: Signal
    quantity: float
    notional_usdt: float
    leverage: float
    sl_price: float                  # final
    tp_levels: list[TPLevel]
    margin_used: float
    risk_budget_consumed: float
    breakers_status: dict[str, bool] = Field(default_factory=dict)
    correlation_factor: float = 1.0
    reject_reason: str | None = None  # Reject ise burada
    manifest_hash: str = ""


class Reject(BaseModel):
    """Risk reddi veya akış halkası boyunca herhangi bir reddediş."""

    model_config = ConfigDict(frozen=True)

    signal: Signal
    rejected_by: str                 # "risk" | "portfolio" | "execution"
    reason: str
    detail: dict[str, Any] = Field(default_factory=dict)


# =====================================================================
# Portfolio
# =====================================================================

class OrderInstruction(BaseModel):
    """Portfolio Manager'dan Execution'a gönderilen final talimat."""

    model_config = ConfigDict(frozen=True)

    risked_order: RiskedOrder
    priority: float                  # daha yüksek önce
    order_type: Literal["market", "post_only_limit", "limit"] = "post_only_limit"
    limit_price: float | None = None
    time_in_force: Literal["GTC", "IOC", "FOK", "PO"] = "PO"
    reduce_only: bool = False


# =====================================================================
# Execution
# =====================================================================

class Fill(BaseModel):
    """Borsa'dan dönen fill bilgisi."""

    model_config = ConfigDict(frozen=True)

    order_id: str
    venue: str
    symbol: str
    side: Direction
    price: float
    quantity: float
    fee_usdt: float
    fee_currency: str = "USDT"
    timestamp: datetime
    is_maker: bool
    expected_price: float
    slippage_bps: float
    mode: Mode
    manifest_hash: str = ""


class Position(BaseModel):
    """Açık pozisyon snapshot."""

    venue: str
    symbol: str
    side: Direction
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl_usdt: float
    realized_pnl_usdt: float
    sl_price: float | None = None
    tp_price: float | None = None
    opened_at: datetime
    strategy_id: str
    last_updated: datetime


# =====================================================================
# Analytics
# =====================================================================

class TradeRecord(BaseModel):
    """Açılıp kapanmış tek trade — journal'a yazılan."""

    trade_id: str
    venue: str
    symbol: str
    side: Direction
    entry_ts: datetime
    exit_ts: datetime
    entry_price: float
    exit_price: float
    quantity: float
    realized_pnl_usdt: float
    realized_r_multiple: float
    fees_usdt: float
    slippage_bps: float
    strategy_id: str
    pattern_id: str
    confluence_score: float
    initial_sl: float
    initial_tp: float
    mae_pct: float                   # max adverse excursion
    mfe_pct: float                   # max favorable excursion
    classification: str | None = None  # post-mortem (Analyst doldurur)
    notes: str | None = None
    manifest_hash: str = ""


# =====================================================================
# Memory & Agent
# =====================================================================

class AgentMessage(BaseModel):
    """LLM agent'lar arası mesaj."""

    sender: str
    recipient: str
    topic: str
    body: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    ts: datetime = Field(default_factory=_utcnow)
    correlation_id: str | None = None


class MemoryEntry(BaseModel):
    """Episodic JSONL satırı."""

    agent: str
    type: Literal["identity", "know_how", "learning", "decision", "episodic"]
    slug: str
    body: str
    ts: datetime = Field(default_factory=_utcnow)
    confidence: Literal["low", "med", "high"] = "med"
    tags: list[str] = Field(default_factory=list)


# =====================================================================
# Sembol meta
# =====================================================================

class Instrument(BaseModel):
    venue: str
    symbol: str
    market_type: Literal["spot", "linear_perp", "inverse_perp"]
    base: str
    quote: str
    listing_date: datetime | None = None
    delisting_date: datetime | None = None
    tick_size: Decimal | None = None
    lot_step: Decimal | None = None
    min_notional_usdt: Decimal | None = None
    is_active: bool = True
