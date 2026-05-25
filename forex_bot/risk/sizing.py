"""Position sizing for forex (lot-based)."""
from __future__ import annotations

import math

from ..contracts import pip_value


def position_size_pip_risk(
    equity_usd: float,
    risk_pct: float,
    sl_pips: float,
    pair: str,
    lot_step: float = 0.01,
    min_lot: float = 0.01,
    max_lot: float = 100.0,
) -> float:
    """Standard pip-risk sizing.

    risk_usd = equity * risk_pct
    pip_value(1 lot) approx
    lots = risk_usd / (sl_pips * pip_value_per_lot)
    """
    if sl_pips <= 0 or equity_usd <= 0:
        return 0.0
    risk_usd = equity_usd * risk_pct
    pv = pip_value(pair, lots=1.0)
    if pv <= 0:
        return 0.0
    lots = risk_usd / (sl_pips * pv)
    # If computed lots is below broker minimum, REJECT (don't force min_lot — risk overshoot).
    if lots < min_lot:
        return 0.0
    lots = min(max_lot, lots)
    return math.floor(lots / lot_step) * lot_step


def position_size_leverage_target(
    equity_usd: float,
    target_leverage: float,
    sl_pips: float,
    pair: str,
    max_risk_pct: float = 0.50,
    lot_step: float = 0.01,
    min_lot: float = 0.01,
    max_lot: float = 100.0,
) -> tuple[float, float]:
    """Aggressive leverage-target sizing: position notional = equity * target_leverage.

    Returns (lots, implied_risk_pct). implied_risk_pct = potential loss if SL hit / equity.
    This is the AGGRESSIVE mode — uses full leverage, NOT capital-at-risk based.
    A hard cap (max_risk_pct) prevents single-trade account wipe.

    WARNING: high target_leverage → implied_risk can exceed 100% → margin call risk.
    """
    if sl_pips <= 0 or equity_usd <= 0:
        return 0.0, 0.0
    pv = pip_value(pair, lots=1.0)
    if pv <= 0:
        return 0.0, 0.0
    # notional in base currency = equity * leverage; lots = notional / 100_000
    notional = equity_usd * target_leverage
    lots = notional / 100_000.0
    # implied risk: loss if SL hit
    implied_loss = sl_pips * pv * lots
    implied_risk_pct = implied_loss / equity_usd
    # hard cap: if implied risk exceeds max_risk_pct, scale down
    if implied_risk_pct > max_risk_pct:
        scale = max_risk_pct / implied_risk_pct
        lots *= scale
        implied_risk_pct = max_risk_pct
    if lots < min_lot:
        return 0.0, 0.0
    lots = min(max_lot, lots)
    lots = math.floor(lots / lot_step) * lot_step
    return lots, implied_risk_pct


def kelly_fraction(win_rate: float, avg_win_r: float, avg_loss_r: float = 1.0, cap: float = 0.25) -> float:
    """Kelly cap: f* = (bp - q) / b, where b = avg_win_r / avg_loss_r, p = win_rate, q = 1-p."""
    if avg_loss_r <= 0 or avg_win_r <= 0 or win_rate <= 0:
        return 0.0
    b = avg_win_r / avg_loss_r
    p = win_rate
    q = 1.0 - p
    f = (b * p - q) / b
    return max(0.0, min(cap, f))
