"""SEC-G16: Side-concentration gate tests (lab.py parity).

HARD REVIEW — 15m phoenix bot, T7 bulgusu: yön-konsantrasyon limiti
(`max_same_side_concurrent`) canlı RiskOfficer'da yoktu. 8 ardışık SHORT
kaybı bu gate yokken birikti, breaker halt'a kadar gitti.

Backtest engine `lab.py` (sat 977-982):
    if cfg.max_same_side_concurrent is not None:
        side = t["side"]
        same_side_count = sum(1 for p in open_pos if p.get("side") == side)
        if same_side_count >= cfg.max_same_side_concurrent:
            continue

Live RiskOfficer.evaluate() artık aynı semantiği uyguluyor (adım 3.5),
reject reason `same_side_concentration`.

Bu testler:
  1. Limit altı (count < limit) → PASS.
  2. Limit aşımı (count >= limit) → REJECT same_side_concentration.
  3. Key yoksa (None) → no-op (limit-aşımı senaryosunda bile PASS).
  4. Yön-bağımsızlık: aynı yön dolu ama karşı yöne izin var.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from price_action.contracts import Position, Signal
from price_action.risk.breaker import DDBreaker
from price_action.risk.sizing import AccountState, RiskOfficer


# =====================================================================
# Fixtures
# =====================================================================

def _scalp_config(max_same_side: int | None = 4) -> dict:
    """C2+V5 final preset benzeri config; max_same_side opsiyonel."""
    conc: dict = {
        "max_open_positions": 16,
        "max_per_category_pct": 0.35,
        "max_per_symbol_pct": 0.15,
    }
    ps: dict = {
        "method": "fixed_fractional",
        "risk_per_trade": 0.020,
        "min_quantity_usdt": 5,
        "max_notional_pct_equity": 0.15,
    }
    # max_same_side_concurrent → position_sizing altında (lab.py + sizing.py parity)
    if max_same_side is not None:
        ps["max_same_side_concurrent"] = max_same_side
    return {
        "position_sizing": ps,
        "stop_loss": {"method": "atr", "atr_period": 14, "atr_multiplier": 1.5},
        "take_profit": {
            "method": "r_multiple",
            "primary_R": 1.2,
            "partial_close_at_R": 0.8,
        },
        "leverage": {
            "enabled": True,
            "max_leverage_per_symbol": 3,
            "max_portfolio_notional_x_equity": 3,
            "margin_safety_ratio": 0.5,
        },
        "drawdown_breakers": {
            "daily_loss_pct": 0.04,
            "weekly_loss_pct": 0.08,
            "monthly_loss_pct": 0.99,
            "consecutive_losses": 5,
        },
        "correlation_gate": {"enabled": False},
        "concentration_limits": conc,
        "liquidity_gate": {
            "max_order_to_minute_volume": 0.01,
            "min_book_depth_usdt": 0,
        },
    }


# Sembol fiyatları — her sembol farklı, per-symbol cap'e takılmasınlar.
_PRICES = {
    "BTC/USDT": 65000.0,
    "ETH/USDT": 3200.0,
    "SOL/USDT": 150.0,
    "BNB/USDT": 600.0,
    "ADA/USDT": 0.45,
    "AVAX/USDT": 35.0,
    "LINK/USDT": 18.0,
    "DOT/USDT": 7.0,
}


def _signal(symbol: str, direction: str) -> Signal:
    price = _PRICES[symbol]
    sl_pct = 0.015
    sl_price = price * (1 - sl_pct) if direction == "long" else price * (1 + sl_pct)
    tp_mult = 1.2
    tp_price = (
        price * (1 + sl_pct * tp_mult)
        if direction == "long"
        else price * (1 - sl_pct * tp_mult)
    )
    return Signal(
        ts=datetime(2026, 5, 18, 16, 30, tzinfo=timezone.utc),
        venue="binance",
        symbol=symbol,
        timeframe="15m",
        direction=direction,
        pattern_id="brooks_failed_breakout",
        confluence_score=0.65,
        sl_price=sl_price,
        tp_price=tp_price,
        suggested_size_atr=price * 0.009,
        metadata={"atr14": price * 0.009},
    )


def _position(symbol: str, side: str) -> Position:
    """Küçük açık pozisyon — per-symbol cap'e takılmayacak kadar minik."""
    price = _PRICES[symbol]
    return Position(
        venue="binance",
        symbol=symbol,
        side=side,
        quantity=0.001,  # minimal notional, conc gate'i tetiklemesin
        entry_price=price,
        current_price=price,
        unrealized_pnl_usdt=0.0,
        realized_pnl_usdt=0.0,
        opened_at=datetime.now(timezone.utc),
        strategy_id="prev",
        last_updated=datetime.now(timezone.utc),
    )


def _account(positions: list[Position], equity: float = 100_000.0) -> AccountState:
    return AccountState(
        equity_usdt=equity,
        free_margin_usdt=equity,
        open_positions=positions,
        realized_pnl_today=0.0,
    )


def _make_officer(cfg: dict, tmp_path) -> RiskOfficer:
    breaker = DDBreaker(cfg["drawdown_breakers"], state_path=tmp_path / "brk.json")
    return RiskOfficer(cfg, breaker=breaker)


# =====================================================================
# 1. Limit altı → PASS
# =====================================================================

def test_below_limit_passes(tmp_path):
    """3 açık SHORT, limit 4 → 4. SHORT sinyali PASS (count 3 < 4)."""
    cfg = _scalp_config(max_same_side=4)
    ro = _make_officer(cfg, tmp_path)
    open_shorts = [
        _position("BTC/USDT", "short"),
        _position("ETH/USDT", "short"),
        _position("SOL/USDT", "short"),
    ]
    acct = _account(open_shorts)
    result = ro.evaluate(_signal("BNB/USDT", "short"), acct, market_price=_PRICES["BNB/USDT"])
    assert hasattr(result, "quantity"), (
        f"Limit altı (3<4) ama REJECT geldi: "
        f"reason={getattr(result, 'reason', '?')}, detail={getattr(result, 'detail', '')}"
    )


# =====================================================================
# 2. Limit aşımı → REJECT same_side_concentration
# =====================================================================

def test_at_limit_rejects(tmp_path):
    """4 açık SHORT, limit 4 → 5. SHORT sinyali REJECT (count 4 >= 4)."""
    cfg = _scalp_config(max_same_side=4)
    ro = _make_officer(cfg, tmp_path)
    open_shorts = [
        _position("BTC/USDT", "short"),
        _position("ETH/USDT", "short"),
        _position("SOL/USDT", "short"),
        _position("BNB/USDT", "short"),
    ]
    acct = _account(open_shorts)
    result = ro.evaluate(_signal("ADA/USDT", "short"), acct, market_price=_PRICES["ADA/USDT"])
    assert not hasattr(result, "quantity"), "4 SHORT açıkken 5. SHORT PASS geldi"
    assert result.reason == "same_side_concentration", (
        f"Yanlış reject reason: {result.reason}"
    )
    assert result.detail["current"] == 4
    assert result.detail["max"] == 4
    assert result.detail["side"] == "short"


def test_above_limit_rejects(tmp_path):
    """8 ardışık SHORT senaryosu (T7 bulgusu) — limit 4, 5. SHORT bile REJECT."""
    cfg = _scalp_config(max_same_side=4)
    ro = _make_officer(cfg, tmp_path)
    open_shorts = [
        _position(sym, "short")
        for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT")
    ]
    acct = _account(open_shorts)
    result = ro.evaluate(_signal("AVAX/USDT", "short"), acct, market_price=_PRICES["AVAX/USDT"])
    assert not hasattr(result, "quantity")
    assert result.reason == "same_side_concentration"
    assert result.detail["current"] == 5


# =====================================================================
# 3. Key yoksa → no-op (backward-compat, byte-identical davranış)
# =====================================================================

def test_no_key_is_noop(tmp_path):
    """max_same_side_concurrent key YOK → limit-aşımı senaryosunda bile PASS."""
    cfg = _scalp_config(max_same_side=None)
    assert "max_same_side_concurrent" not in cfg["position_sizing"]
    ro = _make_officer(cfg, tmp_path)
    open_shorts = [
        _position(sym, "short")
        for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "ADA/USDT")
    ]
    acct = _account(open_shorts)
    result = ro.evaluate(_signal("AVAX/USDT", "short"), acct, market_price=_PRICES["AVAX/USDT"])
    # Key yoksa side-concentration gate hiç çalışmaz → başka sebep yoksa PASS.
    assert hasattr(result, "quantity"), (
        f"Key yokken side-gate çalıştı (no-op değil): "
        f"reason={getattr(result, 'reason', '?')}"
    )


# =====================================================================
# 4. Yön-bağımsızlık: aynı yön dolu ama karşı yöne izin
# =====================================================================

def test_opposite_side_allowed_when_same_side_full(tmp_path):
    """4 SHORT açık (limit dolu) ama LONG sinyali PASS — gate yön-spesifik."""
    cfg = _scalp_config(max_same_side=4)
    ro = _make_officer(cfg, tmp_path)
    open_shorts = [
        _position(sym, "short")
        for sym in ("BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT")
    ]
    acct = _account(open_shorts)
    result = ro.evaluate(_signal("ADA/USDT", "long"), acct, market_price=_PRICES["ADA/USDT"])
    assert hasattr(result, "quantity"), (
        f"SHORT dolu iken LONG da REJECT oldu (yön-bağımsızlık kırık): "
        f"reason={getattr(result, 'reason', '?')}"
    )


def test_mixed_positions_counts_only_same_side(tmp_path):
    """3 SHORT + 3 LONG açık, limit 4. Yeni SHORT PASS (sadece 3 SHORT sayılır)."""
    cfg = _scalp_config(max_same_side=4)
    ro = _make_officer(cfg, tmp_path)
    positions = [
        _position("BTC/USDT", "short"),
        _position("ETH/USDT", "short"),
        _position("SOL/USDT", "short"),
        _position("BNB/USDT", "long"),
        _position("ADA/USDT", "long"),
        _position("AVAX/USDT", "long"),
    ]
    acct = _account(positions)
    result = ro.evaluate(_signal("LINK/USDT", "short"), acct, market_price=_PRICES["LINK/USDT"])
    assert hasattr(result, "quantity"), (
        f"Karışık pozisyonda SHORT sayımı yanlış (LONG'ları da saydı): "
        f"reason={getattr(result, 'reason', '?')}"
    )


# =====================================================================
# 5. lab.py parity: >= eşik semantiği (count == limit → reject)
# =====================================================================

def test_exact_equality_rejects_not_just_strict_greater(tmp_path):
    """count == limit (tam eşit) → REJECT. lab.py `>=` semantiği, `>` değil."""
    cfg = _scalp_config(max_same_side=2)
    ro = _make_officer(cfg, tmp_path)
    open_shorts = [
        _position("BTC/USDT", "short"),
        _position("ETH/USDT", "short"),
    ]
    acct = _account(open_shorts)
    result = ro.evaluate(_signal("SOL/USDT", "short"), acct, market_price=_PRICES["SOL/USDT"])
    assert not hasattr(result, "quantity"), "count==limit (2==2) PASS geldi — `>` kullanılmış"
    assert result.reason == "same_side_concentration"
