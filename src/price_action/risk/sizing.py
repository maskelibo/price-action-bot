"""Position sizing + RiskOfficer karar motoru.

Tüm hard limit yorumları `agents/risk_officer.md` ve `configs/risk.yaml`'den geliyor.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from price_action.contracts import (
    Position,
    Reject,
    RiskedOrder,
    Signal,
    TPLevel,
    stable_hash,
)
from price_action.logging_config import logger
from price_action.risk.breaker import DDBreaker
from price_action.risk.gates import (
    concentration_gate,
    correlation_gate,
    leverage_gate,
    liquidity_gate,
)


# =====================================================================
# Sizing primitives
# =====================================================================

def fixed_fractional(equity: float, risk_pct: float, sl_distance_pct: float) -> float:
    """Fixed fractional sizing.

    Risk yaml'daki `risk_per_trade` (default %1) — sermayenin sabit oranı SL'ye
    kadar risk edilir. Quantity döner (notional değil); çağıran round_step uygular.
    """
    if equity <= 0 or risk_pct <= 0 or sl_distance_pct <= 0:
        return 0.0
    risk_dollar = equity * risk_pct
    # quantity = risk_dollar / (price * sl_distance_pct) — fakat burada price yok
    # bu yüzden notional bazlı kullanılır; çağıran price ile böler.
    notional_at_risk = risk_dollar / sl_distance_pct
    return float(notional_at_risk)


def kelly_capped(
    win_rate: float, avg_win: float, avg_loss: float, cap: float = 0.25
) -> float:
    """Kelly fraction = W - (1-W)/R.

    `cap` ile sınırlanır (default 0.25 — Risk YAML).
    Negatif Kelly → 0 (edge yok).
    """
    if avg_loss <= 0 or win_rate <= 0 or win_rate >= 1:
        return 0.0
    R = avg_win / avg_loss
    if R <= 0:
        return 0.0
    f = win_rate - (1 - win_rate) / R
    if f <= 0:
        return 0.0
    return float(min(f, cap))


def atr_normalized_size(
    atr: float, equity: float, risk_pct: float, atr_multiplier_for_sl: float
) -> float:
    """ATR-bazlı sizing: SL = k * ATR; quantity = (equity*risk) / (k*ATR).

    Yani SL'in dolar değeri eşittir risk bütçesine.
    """
    if atr <= 0 or equity <= 0 or risk_pct <= 0 or atr_multiplier_for_sl <= 0:
        return 0.0
    risk_dollar = equity * risk_pct
    sl_dist_dollar = atr_multiplier_for_sl * atr
    qty = risk_dollar / sl_dist_dollar
    return float(qty)


# =====================================================================
# Account state
# =====================================================================

@dataclass
class AccountState:
    """Risk ve Portfolio için hafif hesap durumu snapshot'ı."""

    equity_usdt: float
    free_margin_usdt: float
    open_positions: list[Position] = field(default_factory=list)
    realized_pnl_today: float = 0.0
    realized_pnl_week: float = 0.0
    realized_pnl_month: float = 0.0
    consecutive_losses: int = 0
    last_update: datetime = field(default_factory=_utcnow)

    @property
    def total_open_notional(self) -> float:
        return sum(p.quantity * p.current_price for p in self.open_positions)

    @property
    def open_symbols(self) -> set[str]:
        return {p.symbol for p in self.open_positions}


# =====================================================================
# Risk Officer
# =====================================================================

class _RiskConfig(BaseModel):
    """Risk YAML'ın strict olmayan modeli."""
    model_config = ConfigDict(extra="allow")

    position_sizing: dict[str, Any] = Field(default_factory=dict)
    stop_loss: dict[str, Any] = Field(default_factory=dict)
    take_profit: dict[str, Any] = Field(default_factory=dict)
    leverage: dict[str, Any] = Field(default_factory=dict)
    drawdown_breakers: dict[str, Any] = Field(default_factory=dict)
    correlation_gate: dict[str, Any] = Field(default_factory=dict)
    concentration_limits: dict[str, Any] = Field(default_factory=dict)
    liquidity_gate: dict[str, Any] = Field(default_factory=dict)
    execution: dict[str, Any] = Field(default_factory=dict)
    emergency: dict[str, Any] = Field(default_factory=dict)
    live_mode_enabled: bool = False


class RiskOfficer:
    """Deterministik risk karar motoru.

    Decision flow `agents/risk_officer.md`'de — herhangi bir adım reject ise dur.
    Hard limit'ler bypass edilemez; CEO bile yapamaz.
    """

    def __init__(
        self,
        config: dict[str, Any] | _RiskConfig,
        breaker: DDBreaker | None = None,
    ) -> None:
        if isinstance(config, dict):
            self.config = _RiskConfig.model_validate(config)
        else:
            self.config = config
        self.breaker = breaker or DDBreaker(self.config.drawdown_breakers)
        self._log = logger.bind(component="risk_officer")

    @classmethod
    def from_yaml(cls, path: str | Path, breaker: DDBreaker | None = None) -> RiskOfficer:
        with Path(path).open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return cls(raw or {}, breaker=breaker)

    # ----- core -----
    def evaluate(
        self,
        signal: Signal,
        account_state: AccountState,
        *,
        market_price: float | None = None,
        atr: float | None = None,
        returns_df: Any = None,  # pandas.DataFrame (her sembol bir kolon, daily returns)
        order_book_depth_usdt: float | None = None,
        minute_volume_usdt: float | None = None,
        category_map: dict[str, str] | None = None,
    ) -> RiskedOrder | Reject:
        """Tek sinyal için decision flow."""
        cfg = self.config

        # 1) Breaker check
        # Neden: agents/risk_officer.md - "Breaker tetiklendi → REJECT"
        breaker_status = self.breaker.snapshot(account_state)
        if any(breaker_status.values()):
            return Reject(
                signal=signal,
                rejected_by="risk",
                reason="dd_breaker_active",
                detail={"breakers": breaker_status},
            )

        # 2) Sermaye check
        # Neden: free margin yoksa giriş yok
        if account_state.free_margin_usdt <= 0:
            return Reject(
                signal=signal, rejected_by="risk", reason="insufficient_free_margin"
            )

        # 3) Pozisyon limiti
        # Neden: risk.yaml concentration_limits.max_open_positions (default 8)
        max_open = int(cfg.concentration_limits.get("max_open_positions", 8))
        if len(account_state.open_positions) >= max_open:
            return Reject(
                signal=signal,
                rejected_by="risk",
                reason="max_open_positions_reached",
                detail={"current": len(account_state.open_positions), "max": max_open},
            )

        # 4) Likidite check
        # Neden: agents/risk_officer.md "Order/1m_volume ≤ %1?"
        max_v = float(cfg.liquidity_gate.get("max_order_to_minute_volume", 0.01))
        min_book = float(cfg.liquidity_gate.get("min_book_depth_usdt", 100_000))
        # Provisional notional — sizing aşamasında hassaslaşır.
        liq_ok, liq_reason = liquidity_gate(
            order_notional_usdt=account_state.equity_usdt
            * float(cfg.position_sizing.get("risk_per_trade", 0.01))
            * 50,  # provisional 50x kabaca yeterli; size hesabından sonra net check
            minute_volume_usdt=minute_volume_usdt,
            book_depth_usdt=order_book_depth_usdt,
            max_order_to_minute_volume=max_v,
            min_book_depth_usdt=min_book,
        )
        if not liq_ok:
            return Reject(
                signal=signal,
                rejected_by="risk",
                reason="liquidity_gate",
                detail={"why": liq_reason},
            )

        # 5) Sizing — fixed_fractional / atr_normalized
        # Neden: risk.yaml position_sizing.method
        risk_pct = float(cfg.position_sizing.get("risk_per_trade", 0.01))
        method = str(cfg.position_sizing.get("method", "fixed_fractional"))
        price = float(market_price if market_price is not None else _entry_price(signal))
        sl_dist_dollar = abs(price - signal.sl_price)
        if sl_dist_dollar <= 0:
            return Reject(signal=signal, rejected_by="risk", reason="invalid_sl_distance")

        if method == "atr_normalized" and atr is not None:
            atr_mult = float(cfg.stop_loss.get("atr_multiplier", 2.0))
            quantity = atr_normalized_size(atr, account_state.equity_usdt, risk_pct, atr_mult)
        else:
            sl_pct = sl_dist_dollar / price
            notional_at_risk = fixed_fractional(account_state.equity_usdt, risk_pct, sl_pct)
            quantity = notional_at_risk / price if price > 0 else 0.0

        # min notional
        min_notional = float(cfg.position_sizing.get("min_quantity_usdt", 20))
        notional = quantity * price
        if notional < min_notional:
            return Reject(
                signal=signal,
                rejected_by="risk",
                reason="below_min_notional",
                detail={"notional": notional, "min": min_notional},
            )

        # 6) Kaldıraç check
        # Neden: risk.yaml leverage.max_portfolio_notional_x_equity (default 4)
        max_x = float(cfg.leverage.get("max_portfolio_notional_x_equity", 4))
        max_per_sym_lev = float(cfg.leverage.get("max_leverage_per_symbol", 3))
        lev_ok, lev_reason, leverage_used = leverage_gate(
            new_notional=notional,
            existing_notional=account_state.total_open_notional,
            equity=account_state.equity_usdt,
            max_portfolio_x=max_x,
            per_symbol_leverage=max_per_sym_lev,
        )
        if not lev_ok:
            return Reject(
                signal=signal,
                rejected_by="risk",
                reason="leverage_gate",
                detail={"why": lev_reason},
            )

        # 7) Konsantrasyon check
        # Neden: max_per_symbol_pct, max_per_category_pct
        sym_cap = float(cfg.concentration_limits.get("max_per_symbol_pct", 0.20))
        cat_cap = float(cfg.concentration_limits.get("max_per_category_pct", 0.40))
        conc_ok, conc_reason = concentration_gate(
            symbol=signal.symbol,
            new_notional=notional,
            equity=account_state.equity_usdt,
            open_positions=account_state.open_positions,
            max_per_symbol_pct=sym_cap,
            max_per_category_pct=cat_cap,
            category_map=category_map or {},
        )
        if not conc_ok:
            return Reject(
                signal=signal,
                rejected_by="risk",
                reason="concentration_gate",
                detail={"why": conc_reason},
            )

        # 8) Korelasyon check
        # Neden: yüksek korelasyon = gizli konsantrasyon. > 0.7 → size yarı; > 0.9 REJECT.
        corr_factor = 1.0
        if cfg.correlation_gate.get("enabled", True):
            max_corr = float(cfg.correlation_gate.get("max_pairwise_corr", 0.7))
            hard_block = float(cfg.correlation_gate.get("hard_block_at", 0.9))
            reduction = float(cfg.correlation_gate.get("reduction_factor", 0.5))
            allow, corr_factor = correlation_gate(
                symbol=signal.symbol,
                open_positions=account_state.open_positions,
                returns_df=returns_df,
                max_corr=max_corr,
                hard_block_at=hard_block,
                reduction_factor=reduction,
            )
            if not allow:
                return Reject(
                    signal=signal,
                    rejected_by="risk",
                    reason="correlation_gate_hard_block",
                    detail={"corr_factor": corr_factor},
                )
            if corr_factor < 1.0:
                quantity *= corr_factor
                notional = quantity * price

        # 9) SL final — atr/structural daha sıkısı kazanır
        sl_price = signal.sl_price  # signal layer'ı zaten ATR/structural max'i yapmış kabul

        # 10) TP — partial close planı: 1R'da %50 kapat, kalan trail
        primary_R = float(cfg.take_profit.get("primary_R", 2.0))
        partial_R = float(cfg.take_profit.get("partial_close_at_R", 1.0))
        side = signal.direction
        sl_dist = abs(price - sl_price)
        if side == "long":
            tp1 = price + partial_R * sl_dist
            tp2 = price + primary_R * sl_dist
        else:
            tp1 = price - partial_R * sl_dist
            tp2 = price - primary_R * sl_dist
        tp_levels = [
            TPLevel(price=tp1, fraction=0.5),
            TPLevel(price=tp2, fraction=0.5),
        ]

        # 11) Margin safety — likidasyon mesafesi >= 50%
        # Neden: risk.yaml leverage.margin_safety_ratio (0.5)
        margin_safety = float(cfg.leverage.get("margin_safety_ratio", 0.5))
        # Cross margin yaklaşık model: liq_dist_pct ≈ 1/leverage. SL_pct ≤ liq_dist*margin_safety.
        if leverage_used > 0:
            liq_dist_pct = 1.0 / leverage_used
            sl_pct_check = sl_dist / price if price > 0 else 1.0
            if sl_pct_check > liq_dist_pct * margin_safety:
                return Reject(
                    signal=signal,
                    rejected_by="risk",
                    reason="margin_safety_violation",
                    detail={
                        "sl_pct": sl_pct_check,
                        "max_sl_pct": liq_dist_pct * margin_safety,
                    },
                )

        # 12) Final stamp — manifest hash
        risked = RiskedOrder(
            signal=signal,
            quantity=quantity,
            notional_usdt=notional,
            leverage=leverage_used,
            sl_price=sl_price,
            tp_levels=tp_levels,
            margin_used=notional / max(leverage_used, 1.0),
            risk_budget_consumed=risk_pct,
            breakers_status=breaker_status,
            correlation_factor=corr_factor,
            manifest_hash=stable_hash(
                {
                    "sig_fp": signal.fingerprint(),
                    "config": cfg.model_dump(),
                    "qty": round(quantity, 8),
                }
            ),
        )
        self._log.bind(
            symbol=signal.symbol,
            qty=quantity,
            notional=notional,
            leverage=leverage_used,
            corr=corr_factor,
        ).info("risk.evaluate.accept")
        return risked


def _entry_price(signal: Signal) -> float:
    """Signal'da explicit `entry_price` yoksa SL ve TP arası referansla yaklaşık.

    Backtest çağıranı genelde `market_price` parametresini geçer; bu yardımcı
    yalnızca emergency fallback'tır.
    """
    md = signal.metadata or {}
    if "entry_price" in md:
        try:
            return float(md["entry_price"])  # type: ignore[arg-type]
        except Exception:
            pass
    # tp ile sl ortalaması iyi bir tahmin değildir — sl/tp arası giriş daha yakın olur.
    if signal.direction == "long":
        return float(signal.sl_price + 0.5 * (signal.tp_price - signal.sl_price) / 3)
    return float(signal.sl_price - 0.5 * (signal.sl_price - signal.tp_price) / 3)


__all__ = [
    "AccountState",
    "RiskOfficer",
    "atr_normalized_size",
    "fixed_fractional",
    "kelly_capped",
]
