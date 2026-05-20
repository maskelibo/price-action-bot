"""RiskOfficer: serialized gate evaluation for forex signals.

Gate order (BLOCKER fixes applied):
  1. Breaker (global + side-conditional)
  2. NewsGuard blackout
  3. Max concurrent positions
  4. Correlation gate
  5. RR sanity (+ sl_pips positive)
  6. Sizing (optional Kelly)
  7. Leverage cap (total + per-pair)
  8. Per-pair concentration (notional/equity ≤ max_per_pair_pct)
  9. Capital cap (live mode only)
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from ..contracts import Reject, RiskedOrder, Signal, pip_value
from ..news.guard import NewsGuard
from .breaker import BreakerConfig, DDBreaker
from .correlation import CorrelationGate
from .sizing import kelly_fraction, position_size_pip_risk, position_size_leverage_target
from .vol_target import VolTargetConfig, vol_target_factor


@dataclass
class AccountState:
    equity_usd: float
    free_margin_usd: float
    open_positions: dict
    daily_pnl: float = 0.0
    weekly_pnl: float = 0.0
    monthly_pnl: float = 0.0
    monthly_pnl_long: float = 0.0
    monthly_pnl_short: float = 0.0
    consecutive_losses: int = 0
    mode: str = "paper"  # paper | live


@dataclass
class RiskConfig:
    risk_per_trade_pct: float = 0.015
    max_risk_per_trade_pct: float = 0.03
    use_kelly: bool = False
    kelly_cap: float = 0.20
    leverage_max: float = 30.0
    max_per_pair_leverage: float = 10.0
    max_open_positions: int = 6
    max_per_pair_pct: float = 0.20
    correlation_gate: CorrelationGate = field(default_factory=CorrelationGate)
    breaker: BreakerConfig = field(default_factory=BreakerConfig)
    vol_target: VolTargetConfig = field(default_factory=VolTargetConfig)
    min_rr: float = 1.5
    capital_cap_usd: float = 1_000.0
    enforce_capital_cap_modes: tuple = ("live",)
    # Sizing mode: "risk_based" (capital-at-risk %) or "leverage_target" (aggressive, full leverage)
    sizing_mode: str = "risk_based"
    target_leverage: float = 5.0          # used only in leverage_target mode
    leverage_target_max_risk: float = 0.50  # hard cap on implied single-trade loss


class RiskOfficer:
    def __init__(self, cfg: Optional[RiskConfig] = None,
                 news_guard: Optional[NewsGuard] = None,
                 breaker_state_path=None):
        self.cfg = cfg or RiskConfig()
        self.breaker = DDBreaker(self.cfg.breaker, state_path=breaker_state_path)
        self.news_guard = news_guard

    def evaluate(self, signal: Signal, account: AccountState, now: datetime) -> RiskedOrder | Reject:
        # 1) Breaker (global)
        blocked, reason = self.breaker.update(
            account.equity_usd, account.daily_pnl, account.weekly_pnl, account.monthly_pnl,
            account.consecutive_losses, now,
            monthly_pnl_long=account.monthly_pnl_long,
            monthly_pnl_short=account.monthly_pnl_short,
        )
        if blocked:
            return Reject(signal=signal, rejected_by="breaker", reason=reason)
        # 1b) Side-conditional breaker
        blocked_side, side_reason = self.breaker.check_side(signal.side, now)
        if blocked_side:
            return Reject(signal=signal, rejected_by="breaker", reason=side_reason)

        # 2) News guard
        if self.news_guard is not None:
            blackout, evt = self.news_guard.is_blackout(signal.ts, signal.pair)
            if blackout:
                return Reject(signal=signal, rejected_by="news_guard",
                              reason=f"news_blackout({evt.title if evt else 'unknown'})")

        # 3) Max concurrent
        if len(account.open_positions) >= self.cfg.max_open_positions:
            return Reject(signal=signal, rejected_by="portfolio", reason="max_positions")

        # 4) Correlation gate
        side_map = {p: meta["side"] for p, meta in account.open_positions.items()}
        allow, size_mult, corr_reason = self.cfg.correlation_gate.evaluate(
            signal.pair, list(account.open_positions.keys()), signal.side, side_map,
        )
        if not allow:
            return Reject(signal=signal, rejected_by="correlation", reason=corr_reason)

        # 5) RR + sl_pips sanity
        if signal.sl_pips <= 0:
            return Reject(signal=signal, rejected_by="risk_officer", reason="invalid_sl_pips")
        if signal.rr < self.cfg.min_rr:
            return Reject(signal=signal, rejected_by="risk_officer", reason=f"rr_low({signal.rr:.2f})")

        # 6) Sizing
        if self.cfg.sizing_mode == "leverage_target":
            # AGGRESSIVE: position notional = equity * target_leverage (full leverage usage)
            lots, risk_pct = position_size_leverage_target(
                equity_usd=account.equity_usd,
                target_leverage=self.cfg.target_leverage,
                sl_pips=signal.sl_pips, pair=signal.pair,
                max_risk_pct=self.cfg.leverage_target_max_risk,
            )
        else:
            # risk_based (default, conservative)
            risk_pct = self.cfg.risk_per_trade_pct * size_mult
            atr_pct = signal.meta.get("atr_pct_at_entry", 0.0)
            if atr_pct > 0:
                risk_pct *= vol_target_factor(atr_pct, self.cfg.vol_target)
            if self.cfg.use_kelly and signal.confluence > 0:
                k = kelly_fraction(win_rate=0.55, avg_win_r=signal.rr, avg_loss_r=1.0, cap=self.cfg.kelly_cap)
                risk_pct = min(risk_pct, k)
            risk_pct = min(risk_pct, self.cfg.max_risk_per_trade_pct)
            lots = position_size_pip_risk(
                equity_usd=account.equity_usd, risk_pct=risk_pct,
                sl_pips=signal.sl_pips, pair=signal.pair,
            )
        if lots <= 0:
            return Reject(signal=signal, rejected_by="risk_officer", reason="zero_size")

        notional = lots * 100_000.0  # standard lot in base currency
        # 7) Leverage cap
        existing_notional = sum(p["notional"] for p in account.open_positions.values())
        total_leverage = (existing_notional + notional) / max(1.0, account.equity_usd)
        if total_leverage > self.cfg.leverage_max:
            return Reject(signal=signal, rejected_by="leverage", reason=f"total_lev({total_leverage:.1f})")
        per_pair_lev = notional / max(1.0, account.equity_usd)
        # per-pair leverage cap only enforced in risk_based mode (leverage_target uses target directly)
        if self.cfg.sizing_mode == "risk_based" and per_pair_lev > self.cfg.max_per_pair_leverage:
            return Reject(signal=signal, rejected_by="leverage", reason=f"per_pair_lev({per_pair_lev:.1f})")

        # 8) Per-pair concentration
        if account.open_positions.get(signal.pair):
            return Reject(signal=signal, rejected_by="portfolio", reason="pair_already_open")
        if self.cfg.sizing_mode == "risk_based" and risk_pct > self.cfg.max_per_pair_pct:
            return Reject(signal=signal, rejected_by="portfolio", reason="per_pair_pct_exceeded")

        # 9) Capital cap
        if account.mode in self.cfg.enforce_capital_cap_modes:
            if account.equity_usd >= self.cfg.capital_cap_usd:
                return Reject(signal=signal, rejected_by="capital_cap",
                              reason=f"capital_cap({account.equity_usd:.0f}>={self.cfg.capital_cap_usd:.0f})")

        return RiskedOrder(
            signal=signal, lots=lots, notional_quote=notional,
            risk_usd=account.equity_usd * risk_pct,
            sl_price=signal.sl_price, tp_prices=signal.tp_prices,
            leverage=total_leverage, decision_id=str(uuid.uuid4()),
            meta={"size_mult": size_mult, "corr_reason": corr_reason, "risk_pct_effective": risk_pct},
        )
