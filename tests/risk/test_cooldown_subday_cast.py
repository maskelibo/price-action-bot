"""SEC-SCALP-P0: lab.py production_replay sub-day cooldown cast regression.

Bug (forensic 2026-05-17 §5):
  - lab.py:378 `int(sp.get("same_symbol_side_cooldown_days", 3))`
  - YAML 0.010 (15dk) -> int(0.010)=0 -> cooldown no-op
  - lab.py:731 `(t-prev).days < N` -> sub-day mesafede .days=0 -> True asla

Fix:
  - Field type int -> float
  - from_yaml cast int() -> float()
  - replay karşılaştırma `(t-prev).total_seconds() < N*86400`

Bu test:
  1. Field type float (1d/4h integer YAML byte-identical replay tutar)
  2. YAML 0.010 -> cfg.same_symbol_side_cooldown_days == 0.010 (float)
  3. Sub-day cooldown (10dk) gerçekten 2. trade'i reddediyor
  4. Sub-day cooldown sınır üstü (16dk sonra) trade kabul ediyor
  5. 1d cooldown=3 ile day-boundary parity (regression koruması)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from price_action.backtest.lab import ProductionConfig, production_replay


def _trade(*, sym: str, side: str, entry_ts: datetime, R: float = 1.0,
           conf: float = 0.5, strategy: str = "test_strat") -> dict:
    """production_replay'in beklediği minimal trade dict."""
    return {
        "symbol": sym,
        "side": side,
        "entry_ts": entry_ts,
        "exit_ts": entry_ts + timedelta(hours=1),
        "entry_price": 100.0,
        "initial_sl": 99.0 if side == "long" else 101.0,
        "R": R,
        "conf": conf,
        "strategy": strategy,
        "mfe_pct": 0.02,
        "atr14": 1.0,
    }


# =====================================================================
# 1. Field type float (default 3.0)
# =====================================================================

def test_default_field_type_is_float():
    """Field type float — int değil. Backward-compat 3 == 3.0."""
    cfg = ProductionConfig()
    assert isinstance(cfg.same_symbol_side_cooldown_days, float)
    assert cfg.same_symbol_side_cooldown_days == 3.0


# =====================================================================
# 2. YAML sub-day cooldown doğru parse ediliyor
# =====================================================================

def test_yaml_subday_cooldown_loaded_as_float(tmp_path):
    """YAML 0.010 -> cfg.same_symbol_side_cooldown_days == 0.010 (önceki int cast=0)."""
    yaml_path = tmp_path / "test_subday.yaml"
    yaml_path.write_text("""
position_sizing:
  backtest_risk_pct: 0.02
  risk_per_trade: 0.02
strategy_portfolio:
  signal_confidence_min: 0.20
  max_concurrent_positions: 8
  same_symbol_side_cooldown_days: 0.010
drawdown_breakers:
  daily_loss_pct: 0.99
  weekly_loss_pct: 0.99
  monthly_loss_pct: 0.99
""")
    cfg = ProductionConfig.from_yaml(str(yaml_path))
    assert isinstance(cfg.same_symbol_side_cooldown_days, float)
    assert cfg.same_symbol_side_cooldown_days == pytest.approx(0.010, abs=1e-9)


# =====================================================================
# 3. Sub-day cooldown enforce: 10dk içinde 2. trade reject
# =====================================================================

def test_subday_cooldown_rejects_within_window():
    """cooldown=0.010d (~864s = 14.4dk). 10dk sonra 2. trade reject."""
    t0 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    trades = [
        _trade(sym="BTC/USDT", side="long", entry_ts=t0),
        _trade(sym="BTC/USDT", side="long", entry_ts=t0 + timedelta(minutes=10)),
        _trade(sym="BTC/USDT", side="long", entry_ts=t0 + timedelta(minutes=20)),
    ]
    cfg = ProductionConfig(
        same_symbol_side_cooldown_days=0.010,  # 14.4 dk
        max_concurrent=4,
        conf_min=0.0,
        daily_dd=0.99, weekly_dd=0.99, monthly_dd=0.99,
        initial_capital=10_000.0,
    )
    res = production_replay(trades, cfg)
    # 1. trade kabul (t0), 2. trade reject (10dk < 14.4dk), 3. trade kabul (20dk >= 14.4dk)
    # ReplayResult.trade_count alanı varsa kullan; aksi halde Rs uzunluğu
    assert res is not None
    assert res.trades == 2, f"Beklenen 2 trade (1+3 kabul), bulundu: {res.trades}"


# =====================================================================
# 4. Sub-day cooldown boundary: 16dk sonra kabul
# =====================================================================

def test_subday_cooldown_accepts_after_window():
    """cooldown=0.010d. 2 trade 16dk arayla — ikisi de kabul."""
    t0 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    trades = [
        _trade(sym="BTC/USDT", side="long", entry_ts=t0),
        _trade(sym="BTC/USDT", side="long", entry_ts=t0 + timedelta(minutes=16)),
    ]
    cfg = ProductionConfig(
        same_symbol_side_cooldown_days=0.010,
        max_concurrent=4,
        conf_min=0.0,
        daily_dd=0.99, weekly_dd=0.99, monthly_dd=0.99,
        initial_capital=10_000.0,
    )
    res = production_replay(trades, cfg)
    assert res is not None
    assert res.trades == 2, f"Beklenen 2 trade kabul, bulundu: {res.trades}"


# =====================================================================
# 5. 1d cooldown=3 byte-identical (regression: integer day boundary)
# =====================================================================

def test_integer_day_cooldown_boundary_identical():
    """cooldown=3 (1d/4h preset). .days < 3 ile total_seconds() < 3*86400 aynı."""
    t0 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    trades = [
        _trade(sym="BTC/USDT", side="long", entry_ts=t0),
        # +2.5 gün: eski .days==2 < 3 True (reject); yeni total_seconds=2.5*86400 < 3*86400 True (reject)
        _trade(sym="BTC/USDT", side="long", entry_ts=t0 + timedelta(days=2, hours=12)),
        # +3.0 gün tam: eski .days==3 < 3 False (kabul); yeni total_seconds=3*86400 < 3*86400 False (kabul)
        _trade(sym="BTC/USDT", side="long", entry_ts=t0 + timedelta(days=3)),
    ]
    cfg = ProductionConfig(
        same_symbol_side_cooldown_days=3.0,
        max_concurrent=4,
        conf_min=0.0,
        daily_dd=0.99, weekly_dd=0.99, monthly_dd=0.99,
        initial_capital=10_000.0,
    )
    res = production_replay(trades, cfg)
    assert res is not None
    # 1. kabul (t0), 2. reject (2.5d), 3. kabul (3.0d)
    assert res.trades == 2, f"Beklenen 2 trade kabul (1+3), bulundu: {res.trades}"


# =====================================================================
# 6. cooldown=0 explicit override -> hiçbir trade reddedilmez
# =====================================================================

def test_zero_cooldown_no_filter():
    """cooldown=0 explicit -> aynı bara aynı sym+side 2 trade kabul."""
    t0 = datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)
    trades = [
        _trade(sym="BTC/USDT", side="long", entry_ts=t0),
        _trade(sym="BTC/USDT", side="long", entry_ts=t0 + timedelta(seconds=1)),
        _trade(sym="BTC/USDT", side="long", entry_ts=t0 + timedelta(seconds=2)),
    ]
    cfg = ProductionConfig(
        same_symbol_side_cooldown_days=0.0,
        max_concurrent=4,
        conf_min=0.0,
        daily_dd=0.99, weekly_dd=0.99, monthly_dd=0.99,
        initial_capital=10_000.0,
    )
    res = production_replay(trades, cfg)
    assert res is not None
    assert res.trades == 3, f"Beklenen 3 trade kabul (cooldown=0), bulundu: {res.trades}"
