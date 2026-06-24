"""Vol-target sizing — sweep + replay integration tests.

SEC-SCALP P1 (vol-target sweep, 2026-05-17):
- vol_target modülü zaten mevcut (src/price_action/risk/vol_target.py)
- lab.py içinde SL-bazlı `vol_factor = target_atr_pct / sl_pct` (line 887-890)
- Bu test suite üç şeyi doğrular:
  1. Standalone formül: high-vol -> shrink, low-vol -> boost, clamp tutar
  2. Lab integration: vol_target_enabled=False ile baseline byte-identical
  3. Sweep: farklı target_atr_pct değerlerinde notional değişimi
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from price_action.backtest.lab import ProductionConfig, production_replay
from price_action.risk.vol_target import (
    VolTargetConfig,
    apply_vol_target,
    vol_target_factor,
)


# ---------------------------------------------------------------------------
# 1) Standalone formül (3 senaryo — brief gate)
# ---------------------------------------------------------------------------


class TestVolTargetSweepFormula:
    """Brief Step 3: high-vol shrink, low-vol boost, clamp tutar."""

    def test_high_vol_shrinks_size(self):
        cfg = VolTargetConfig(enabled=True, target_atr_pct=0.04)
        # ATR %12 (extrem high-vol) → raw factor 0.333 → in [0.20, 1.50] range
        f = vol_target_factor(0.12, cfg)
        assert f < 0.5, f"high-vol should shrink size, got factor={f}"
        assert f == pytest.approx(0.04 / 0.12, rel=1e-9)

    def test_low_vol_boosts_size(self):
        cfg = VolTargetConfig(enabled=True, target_atr_pct=0.04)
        # ATR %3 (low-vol) → raw factor 1.333 → in [0.20, 1.50] range
        f = vol_target_factor(0.03, cfg)
        assert f > 1.0, f"low-vol should boost size, got factor={f}"
        assert f == pytest.approx(0.04 / 0.03, rel=1e-9)

    def test_clamp_holds_extremes(self):
        cfg = VolTargetConfig(enabled=True, target_atr_pct=0.04,
                              min_factor=0.20, max_factor=1.50)
        # ATR %50 — extreme high vol → clamp min
        assert vol_target_factor(0.50, cfg) == 0.20
        # ATR %0.5 — extreme low vol → clamp max
        assert vol_target_factor(0.005, cfg) == 1.50

    def test_apply_vol_target_dollars(self):
        """Risk-dollar apply pipeline."""
        cfg = VolTargetConfig(enabled=True, target_atr_pct=0.04)
        # base $200, ATR %8 → factor 0.5 → $100
        assert apply_vol_target(200.0, 0.08, cfg) == 100.0
        # base $200, ATR %2 → factor 1.5 clamped → $300
        assert apply_vol_target(200.0, 0.02, cfg) == 300.0


# ---------------------------------------------------------------------------
# 2) Lab replay parity — vol_target OFF byte-identical
# ---------------------------------------------------------------------------


def _make_trades(n: int, sl_pct: float = 0.02, win_rate: float = 0.5,
                 r_win: float = 2.0, r_loss: float = -1.0,
                 entry_price: float = 100.0):
    """Sentetik trade pool oluştur — replay parity için deterministik.

    lab.py sizing path 'entry_price' + 'initial_sl' ister.
    sl_pct = abs(entry-sl)/entry; long için sl = entry*(1-sl_pct).
    """
    base = datetime(2024, 1, 1, tzinfo=timezone.utc)
    sl_price = entry_price * (1.0 - sl_pct)  # long
    out = []
    for i in range(n):
        is_win = (i % 2 == 0) if win_rate == 0.5 else (i % 10 < int(win_rate * 10))
        R = r_win if is_win else r_loss
        out.append({
            "entry_ts": base + timedelta(days=i),
            "exit_ts": base + timedelta(days=i, hours=4),
            "symbol": "BTC/USDT",
            "side": "long",
            "strategy": "test_strat",
            "R": R,
            "conf": 0.5,
            "conf_pct": 0.5,
            "entry_price": entry_price,
            "initial_sl": sl_price,
        })
    return out


class TestLabReplayParity:
    """Step 4: vol_target.enabled=False ile mevcut replay byte-identical."""

    def test_baseline_off_matches_replace_off(self):
        """vol_target_enabled=False explicit vs implicit default — identical."""
        from dataclasses import replace as dc_replace
        pool = _make_trades(40)
        cfg = ProductionConfig(
            risk_pct=0.02, conf_min=0.0,
            max_concurrent=20,
            same_symbol_side_cooldown_days=0.0,
            initial_capital=10_000.0,
            consecutive_loss_n=None,  # disable breaker
            daily_dd=0.99, weekly_dd=0.99, monthly_dd=0.99,
        )
        # Senaryo A: default vol_target_enabled=False
        r1 = production_replay(pool, cfg)
        # Senaryo B: explicit False (with_overrides path)
        cfg2 = cfg.with_overrides(vol_target_enabled=False, vol_target_atr_pct=0.04)
        r2 = production_replay(pool, cfg2)
        assert r1 is not None and r2 is not None
        assert r1.final_equity == r2.final_equity, (
            f"vol_target OFF byte-identical bekleniyor: {r1.final_equity} vs {r2.final_equity}"
        )
        assert r1.trades == r2.trades
        assert r1.max_drawdown == r2.max_drawdown

    def test_vol_target_on_changes_outcome(self):
        """Sanity: vol_target ON gerçekten sizing'i değiştirir (notional farkı)."""
        pool = _make_trades(40, sl_pct=0.08)  # high-vol pool (ATR%~8)
        cfg = ProductionConfig(
            risk_pct=0.02, conf_min=0.0,
            max_concurrent=20,
            same_symbol_side_cooldown_days=0.0,
            initial_capital=10_000.0,
            consecutive_loss_n=None,
            daily_dd=0.99, weekly_dd=0.99, monthly_dd=0.99,
            max_notional_pct_equity=None,  # cap kapalı, vol_factor net görünsün
        )
        r_off = production_replay(pool, cfg)
        cfg_on = cfg.with_overrides(
            vol_target_enabled=True,
            vol_target_atr_pct=0.02,  # %2 target vs %8 ATR -> factor 0.25 (clamped 0.25)
            vol_min_factor=0.20,
            vol_max_factor=1.50,
        )
        r_on = production_replay(pool, cfg_on)
        assert r_off is not None and r_on is not None
        # vol_factor=0.25 ile risk_d 4x küçük -> final equity de küçük olmalı
        assert r_on.final_equity != r_off.final_equity, "vol_target ON sizing değiştirmedi"


# ---------------------------------------------------------------------------
# 3) Sweep: target_atr_pct değişimi -> factor mantıklı şekilde değişir
# ---------------------------------------------------------------------------


class TestVolTargetSweep:
    """Sweep matematiği: target_atr_pct artarken (gevşek), factor de artar."""

    @pytest.mark.parametrize("target_atr,current_atr,expected", [
        (0.005, 0.02, 0.25),   # tight target, factor küçük
        (0.010, 0.02, 0.50),
        (0.020, 0.02, 1.00),   # target = current
        (0.030, 0.02, 1.50),   # boost (clamp'e değer)
        (0.040, 0.02, 1.50),   # clamp tutar
    ])
    def test_target_sweep_monotonic(self, target_atr, current_atr, expected):
        cfg = VolTargetConfig(enabled=True, target_atr_pct=target_atr,
                              min_factor=0.20, max_factor=1.50)
        assert vol_target_factor(current_atr, cfg) == pytest.approx(expected, rel=1e-6)

    def test_sweep_factor_increases_with_target(self):
        """Sweep monotonisi: target artarken factor artar."""
        current_atr = 0.05
        targets = [0.01, 0.02, 0.03, 0.05]
        factors = []
        for t in targets:
            cfg = VolTargetConfig(enabled=True, target_atr_pct=t,
                                  min_factor=0.20, max_factor=1.50)
            factors.append(vol_target_factor(current_atr, cfg))
        # Strictly monotonic (clamp dışı zone)
        for a, b in zip(factors, factors[1:]):
            assert b > a, f"sweep not monotonic: {factors}"
