"""Risk gate'leri — likidite, kaldıraç, konsantrasyon, korelasyon.

Her gate `(allow, reason_or_factor)` döner. RiskOfficer tarafından çağırılır.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from price_action.contracts import Position


# =====================================================================
# Liquidity gate
# =====================================================================

def liquidity_gate(
    *,
    order_notional_usdt: float,
    minute_volume_usdt: float | None,
    book_depth_usdt: float | None,
    max_order_to_minute_volume: float = 0.01,
    min_book_depth_usdt: float = 100_000,
) -> tuple[bool, str]:
    """Order/1m_volume ≤ %1 ve book depth ≥ min_book_depth.

    Ölçüm yoksa gate pass eder (data layer'ı yokken backtest'i bloklamaz).
    """
    if minute_volume_usdt is not None:
        if minute_volume_usdt <= 0:
            return False, "zero_minute_volume"
        ratio = order_notional_usdt / minute_volume_usdt
        if ratio > max_order_to_minute_volume:
            return False, f"order_volume_ratio={ratio:.4f}>max={max_order_to_minute_volume}"
    if book_depth_usdt is not None and book_depth_usdt < min_book_depth_usdt:
        return False, f"book_depth={book_depth_usdt}<min={min_book_depth_usdt}"
    return True, "ok"


# =====================================================================
# Leverage gate
# =====================================================================

def leverage_gate(
    *,
    new_notional: float,
    existing_notional: float,
    equity: float,
    max_portfolio_x: float = 4.0,
    per_symbol_leverage: float = 3.0,
) -> tuple[bool, str, float]:
    """Portföy kaldıracı tavanı kontrolü.

    Döner: (allow, reason, leverage_used_for_this_order)
    """
    if equity <= 0:
        return False, "zero_equity", 0.0
    portfolio_x = (existing_notional + new_notional) / equity
    if portfolio_x > max_portfolio_x:
        return (
            False,
            f"portfolio_x={portfolio_x:.2f}>max={max_portfolio_x}",
            per_symbol_leverage,
        )
    # Bu emir için kullanılan kaldıraç (notional / margin) — basitçe min(per_symbol, calc).
    requested_lev = min(per_symbol_leverage, max(1.0, new_notional / equity))
    return True, "ok", requested_lev


# =====================================================================
# Concentration gate
# =====================================================================

def concentration_gate(
    *,
    symbol: str,
    new_notional: float,
    equity: float,
    open_positions: list[Position],
    max_per_symbol_pct: float = 0.20,
    max_per_category_pct: float = 0.40,
    category_map: dict[str, str] | None = None,
) -> tuple[bool, str]:
    """Sembol ve kategori bazlı yoğunlaşma sınırları."""
    if equity <= 0:
        return False, "zero_equity"
    cat_map = category_map or {}

    # Per-symbol
    same_sym_notional = sum(
        p.quantity * p.current_price for p in open_positions if p.symbol == symbol
    )
    sym_pct = (same_sym_notional + new_notional) / equity
    if sym_pct > max_per_symbol_pct:
        return False, f"per_symbol_pct={sym_pct:.3f}>max={max_per_symbol_pct}"

    # Per-category
    cat = cat_map.get(symbol, cat_map.get(symbol.split("/")[0], None))
    if cat is not None:
        cat_notional = sum(
            p.quantity * p.current_price
            for p in open_positions
            if cat_map.get(p.symbol, cat_map.get(p.symbol.split("/")[0], None)) == cat
        )
        cat_pct = (cat_notional + new_notional) / equity
        if cat_pct > max_per_category_pct:
            return False, f"per_category_pct={cat_pct:.3f}>max={max_per_category_pct}"

    return True, "ok"


# =====================================================================
# Correlation gate
# =====================================================================

def correlation_gate(
    *,
    symbol: str,
    open_positions: list[Position],
    returns_df: pd.DataFrame | None,
    max_corr: float = 0.7,
    hard_block_at: float = 0.9,
    reduction_factor: float = 0.5,
) -> tuple[bool, float]:
    """Açık pozisyonlarla 90-günlük korelasyona göre size faktörü.

    Döner: (allow, factor)
      - corr > hard_block_at → (False, 0)
      - corr > max_corr → (True, reduction_factor)
      - değilse → (True, 1.0)

    `returns_df` yoksa konservatif: (True, 1.0). Data layer'ı entegrasyonu
    sağlandığında doldurulur.
    """
    if not open_positions or returns_df is None or returns_df.empty:
        return True, 1.0
    if symbol not in returns_df.columns:
        return True, 1.0

    open_syms = [p.symbol for p in open_positions if p.symbol in returns_df.columns]
    if not open_syms:
        return True, 1.0

    # Son 90 günü kullan
    recent = returns_df.tail(90).dropna(how="all")
    if len(recent) < 20:
        # Yeterli geçmiş yoksa konservatif: pozisyon yarıya
        return True, reduction_factor

    sym_ret = recent[symbol]
    max_obs = 0.0
    for s in open_syms:
        r = recent[s]
        joined = pd.concat([sym_ret, r], axis=1).dropna()
        if len(joined) < 20:
            continue
        c = float(joined.iloc[:, 0].corr(joined.iloc[:, 1]))
        if np.isnan(c):
            continue
        max_obs = max(max_obs, abs(c))

    if max_obs >= hard_block_at:
        return False, 0.0
    if max_obs > max_corr:
        return True, reduction_factor
    return True, 1.0
