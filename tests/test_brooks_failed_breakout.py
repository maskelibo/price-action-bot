"""Unit testler — BrooksFailedBreakoutStrategy.

Test senaryoları (8 test):
  1. Rolling N-bar high lookahead-free (shift(1))
  2. Rolling N-bar low lookahead-free
  3. Breakout bar tespiti — close beyond level
  4. Bull trap (short setup): BO → failure → sinyal üretilmeli
  5. Bear trap (long setup): BO → failure → sinyal üretilmeli
  6. Failure yok (sadece BO) → sinyal yok
  7. SL / TP geometrisi kontrol (short: SL > close > TP; long: TP > close > SL)
  8. Smoke test — rastgele veri, exception yok
  [BONUS]
  9. prepare_features gerekli kolonları eklemeli
  10. _default_manifest geçerli StrategyManifest döndürmeli
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.brooks_failed_breakout import (
    BrooksFailedBreakoutStrategy,
    _default_manifest,
    _rolling_n_bar_high,
    _rolling_n_bar_low,
    _breakout_bar_flag,
    _failed_breakout_flags,
)


# ---------------------------------------------------------------------------
# Yardımcı fabrikalar
# ---------------------------------------------------------------------------

def _base_ts(n: int) -> list[datetime]:
    start = datetime(2022, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def _make_ohlcv(
    n: int,
    base_price: float = 100.0,
    drift: float = 0.0,
    vol: float = 0.5,
    seed: int = 42,
) -> pd.DataFrame:
    """Sade sentetik OHLCV DataFrame."""
    rng = np.random.default_rng(seed)
    noise = rng.normal(drift, vol, n)
    close = np.maximum(base_price + np.cumsum(noise), 1.0)
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + np.abs(rng.normal(0, vol * 0.4, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, vol * 0.4, n))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(1e6, 5e6, n)
    return pd.DataFrame({
        "ts": _base_ts(n),
        "open": open_.astype(float),
        "high": high.astype(float),
        "low": low.astype(float),
        "close": close.astype(float),
        "volume": volume,
        "venue": "binance",
        "symbol": "TEST/USDT",
        "timeframe": "1d",
    })


def _make_strategy(overrides: dict | None = None) -> BrooksFailedBreakoutStrategy:
    """Minimal test manifest ile strateji oluşturur."""
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "brooks_failed_breakout",
        "version": "0.0.1",
        "trend_filter": {"type": "none", "period": 0, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "bull_trap_short",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback_period": 20,
                        "max_bars_to_fail": 3,
                        "require_close_beyond": True,
                        "sl_atr_factor": 0.5,
                        "tp_method": "r_multiple",
                        "primary_R": 2.0,
                    },
                },
                {
                    "id": "bear_trap_long",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback_period": 20,
                        "max_bars_to_fail": 3,
                        "require_close_beyond": True,
                        "sl_atr_factor": 0.5,
                        "tp_method": "r_multiple",
                        "primary_R": 2.0,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 50,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 50,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.0,
                "volume_zscore_min": 0.0,
                "kaufman_er_max_trend": 1.0,
            },
            "confluence": {"method": "weighted_sum", "min_score": 2.0, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
        },
    }
    if overrides:
        raw.update(overrides)
    manifest = StrategyManifest.model_validate(raw)
    return BrooksFailedBreakoutStrategy(manifest)


# ---------------------------------------------------------------------------
# 1. Rolling N-bar high lookahead-free
# ---------------------------------------------------------------------------

class TestRollingNBarHigh:
    def test_rolling_high_equals_shift1_rolling_max(self):
        """_rolling_n_bar_high, shift(1) + rolling(n).max() ile özdeş olmalı."""
        df = _make_ohlcv(80, base_price=100.0)
        result = _rolling_n_bar_high(df, period=20)
        expected = df["high"].shift(1).rolling(20, min_periods=20).max()
        pd.testing.assert_series_equal(
            result.reset_index(drop=True),
            expected.reset_index(drop=True),
            check_names=False,
        )

    def test_rolling_high_nan_before_warmup(self):
        """Warmup (period=20) tamamlanmadan NaN olmalı."""
        df = _make_ohlcv(50, base_price=100.0)
        result = _rolling_n_bar_high(df, period=20)
        # Bar 19: shift(1) → 19 geçmiş bar, period=20 → NaN
        assert pd.isna(result.iloc[19]), "Bar 19'da (warmup dolmadı) NaN bekleniyor"
        # Bar 20: shift(1) → 20 geçmiş bar, period=20 → geçerli
        assert not pd.isna(result.iloc[20]), "Bar 20'de değer bekleniyor"

    def test_rolling_high_excludes_current_bar(self):
        """Bar t'nin high değişimi rolling_high[t]'yi etkilememeli (lookahead-free)."""
        df = _make_ohlcv(60, base_price=100.0)
        original = _rolling_n_bar_high(df.copy(), period=20).iloc[40]

        df2 = df.copy()
        df2.loc[40, "high"] = 99_999.0  # bar 40'ı çok yüksek yap
        result2 = _rolling_n_bar_high(df2, period=20).iloc[40]

        assert abs(result2 - original) < 1e-8, (
            "Bar t'nin high değişimi rolling_high[t]'yi etkilememeli"
        )


# ---------------------------------------------------------------------------
# 2. Rolling N-bar low lookahead-free
# ---------------------------------------------------------------------------

class TestRollingNBarLow:
    def test_rolling_low_equals_shift1_rolling_min(self):
        """_rolling_n_bar_low, shift(1) + rolling(n).min() ile özdeş olmalı."""
        df = _make_ohlcv(80, base_price=100.0)
        result = _rolling_n_bar_low(df, period=20)
        expected = df["low"].shift(1).rolling(20, min_periods=20).min()
        pd.testing.assert_series_equal(
            result.reset_index(drop=True),
            expected.reset_index(drop=True),
            check_names=False,
        )

    def test_rolling_low_excludes_current_bar(self):
        """Bar t'nin low değişimi rolling_low[t]'yi etkilememeli."""
        df = _make_ohlcv(60, base_price=100.0)
        original = _rolling_n_bar_low(df.copy(), period=20).iloc[40]

        df2 = df.copy()
        df2.loc[40, "low"] = 0.001  # bar 40'ı çok düşük yap
        result2 = _rolling_n_bar_low(df2, period=20).iloc[40]

        assert abs(result2 - original) < 1e-8, (
            "Bar t'nin low değişimi rolling_low[t]'yi etkilememeli"
        )


# ---------------------------------------------------------------------------
# 3. Breakout bar tespiti
# ---------------------------------------------------------------------------

class TestBreakoutBarFlag:
    def _make_bo_df(self, n: int = 50) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
        df = _make_ohlcv(n, base_price=100.0)
        nb_high = _rolling_n_bar_high(df, period=10)
        nb_low = _rolling_n_bar_low(df, period=10)
        return df, nb_high, nb_low

    def test_bull_bo_requires_close_beyond_high(self):
        """close > N_bar_high → bull_bo=True; sadece wick → False."""
        n = 50
        df, nb_high, nb_low = self._make_bo_df(n)

        # Bar 40: close'u nb_high[40]'ın üstüne çek
        if not pd.isna(nb_high.iloc[40]):
            level = float(nb_high.iloc[40])
            df.loc[40, "high"] = level * 1.02
            df.loc[40, "close"] = level * 1.01  # close beyond

            nb_high2 = _rolling_n_bar_high(df, period=10)
            nb_low2 = _rolling_n_bar_low(df, period=10)
            bull_bo, _ = _breakout_bar_flag(df, nb_high2, nb_low2, require_close_beyond=True)
            assert bool(bull_bo.iloc[40]), "close > N_high iken bull_bo True olmalı"

    def test_bear_bo_requires_close_below_low(self):
        """close < N_bar_low → bear_bo=True."""
        n = 50
        df, nb_high, nb_low = self._make_bo_df(n)

        if not pd.isna(nb_low.iloc[40]):
            level = float(nb_low.iloc[40])
            df.loc[40, "low"] = level * 0.98
            df.loc[40, "close"] = level * 0.99  # close below

            nb_high2 = _rolling_n_bar_high(df, period=10)
            nb_low2 = _rolling_n_bar_low(df, period=10)
            _, bear_bo = _breakout_bar_flag(df, nb_high2, nb_low2, require_close_beyond=True)
            assert bool(bear_bo.iloc[40]), "close < N_low iken bear_bo True olmalı"

    def test_no_bo_when_close_within_range(self):
        """close N_high ile N_low arasında → BO yok."""
        n = 50
        df, nb_high, nb_low = self._make_bo_df(n)
        # nb_high/nb_low için geçerli bar ara
        valid_idx = None
        for i in range(20, 45):
            if not pd.isna(nb_high.iloc[i]) and not pd.isna(nb_low.iloc[i]):
                valid_idx = i
                break
        if valid_idx is not None:
            level_h = float(nb_high.iloc[valid_idx])
            level_l = float(nb_low.iloc[valid_idx])
            mid = (level_h + level_l) / 2
            df.loc[valid_idx, "high"] = level_h * 0.98
            df.loc[valid_idx, "low"] = level_l * 1.02
            df.loc[valid_idx, "close"] = mid
            nb_h2 = _rolling_n_bar_high(df, period=10)
            nb_l2 = _rolling_n_bar_low(df, period=10)
            bull_bo, bear_bo = _breakout_bar_flag(df, nb_h2, nb_l2, require_close_beyond=True)
            assert not bool(bull_bo.iloc[valid_idx]), "Range içinde bull_bo olmamalı"
            assert not bool(bear_bo.iloc[valid_idx]), "Range içinde bear_bo olmamalı"


# ---------------------------------------------------------------------------
# 4. Bull trap (short setup): BO → failure → sinyal üretilmeli
# ---------------------------------------------------------------------------

class TestBullTrapShortSignal:
    def test_bull_trap_generates_short_signal(self):
        """Bull BO barından 1-3 bar sonra close < level → short sinyal."""
        # Yeterince uzun df (warmup için 20+ bar)
        n = 60
        df = _make_ohlcv(n, base_price=100.0, seed=7)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        # Bar 40'ta bull_trap_short=True olduğundan emin ol (manuel set)
        # Önce atr14'i kontrol et
        atr = float(df_feat["atr14"].iloc[40])
        close = float(df_feat["close"].iloc[40])
        if np.isnan(atr) or atr <= 0:
            pytest.skip("atr14 NaN — warmup yeterli değil")

        df_feat.loc[40, "bull_trap_short"] = True
        df_feat.loc[40, "bull_bo_extreme"] = close + 3.0 * atr  # BO swing high
        df_feat.loc[40, "atr_pct"] = 0.02  # ATR min filtresi geçer

        signals = strat.generate_signals(df_feat)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) >= 1, "Bull trap → en az 1 short sinyal olmalı"

        sig = short_sigs[0]
        assert sig.pattern_id == "bull_trap_short"
        assert sig.confluence_score >= 2.0

    def test_short_signal_sl_above_close(self):
        """Short sinyalin SL'i close'un üstünde olmalı."""
        n = 60
        df = _make_ohlcv(n, base_price=100.0, seed=11)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        atr = float(df_feat["atr14"].iloc[40])
        close = float(df_feat["close"].iloc[40])
        if np.isnan(atr) or atr <= 0:
            pytest.skip("atr14 NaN")

        df_feat.loc[40, "bull_trap_short"] = True
        df_feat.loc[40, "bull_bo_extreme"] = close + 2.5 * atr
        df_feat.loc[40, "atr_pct"] = 0.02

        signals = strat.generate_signals(df_feat)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) >= 1

        for sig in short_sigs:
            assert sig.sl_price > sig.tp_price, "Short: SL > TP olmalı"
            assert sig.sl_price > float(df_feat.loc[40, "close"]), "Short SL close üstünde olmalı"
            assert sig.tp_price < float(df_feat.loc[40, "close"]), "Short TP close altında olmalı"


# ---------------------------------------------------------------------------
# 5. Bear trap (long setup): BO → failure → sinyal üretilmeli
# ---------------------------------------------------------------------------

class TestBearTrapLongSignal:
    def test_bear_trap_generates_long_signal(self):
        """Bear BO barından 1-3 bar sonra close > level → long sinyal."""
        n = 60
        df = _make_ohlcv(n, base_price=100.0, seed=13)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        atr = float(df_feat["atr14"].iloc[40])
        close = float(df_feat["close"].iloc[40])
        if np.isnan(atr) or atr <= 0:
            pytest.skip("atr14 NaN")

        df_feat.loc[40, "bear_trap_long"] = True
        df_feat.loc[40, "bear_bo_extreme"] = close - 3.0 * atr  # BO swing low
        df_feat.loc[40, "atr_pct"] = 0.02

        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) >= 1, "Bear trap → en az 1 long sinyal olmalı"

        sig = long_sigs[0]
        assert sig.pattern_id == "bear_trap_long"
        assert sig.confluence_score >= 2.0

    def test_long_signal_sl_below_close(self):
        """Long sinyalin SL'i close'un altında, TP'si üstünde olmalı."""
        n = 60
        df = _make_ohlcv(n, base_price=100.0, seed=17)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        # Tüm trap flag'lerini kapat, sadece bar 40'ı aç
        df_feat["bull_trap_short"] = False
        df_feat["bear_trap_long"] = False

        atr = float(df_feat["atr14"].iloc[40])
        close_val = float(df_feat["close"].iloc[40])
        if np.isnan(atr) or atr <= 0:
            pytest.skip("atr14 NaN")

        df_feat.loc[40, "bear_trap_long"] = True
        df_feat.loc[40, "bear_bo_extreme"] = close_val - 2.5 * atr
        df_feat.loc[40, "atr_pct"] = 0.02

        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) >= 1, "Bear trap → en az 1 long sinyal olmalı"

        sig = long_sigs[0]
        assert sig.sl_price < sig.tp_price, "Long: SL < TP olmalı"
        assert sig.sl_price < close_val, "Long SL close altında olmalı"
        assert sig.tp_price > close_val, "Long TP close üstünde olmalı"


# ---------------------------------------------------------------------------
# 6. Failure yok (sadece BO) → sinyal yok
# ---------------------------------------------------------------------------

class TestNoSignalWithoutFailure:
    def test_no_signal_when_only_bo_no_failure(self):
        """Breakout var ama failure yok → sinyal üretilmemeli."""
        n = 60
        df = _make_ohlcv(n, base_price=100.0, seed=21)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        # Tüm trap flag'lerini False yap
        df_feat["bull_trap_short"] = False
        df_feat["bear_trap_long"] = False

        signals = strat.generate_signals(df_feat)
        assert signals == [], "Trap flag olmadan sinyal üretilmemeli"

    def test_empty_df_returns_no_signals(self):
        """Boş DataFrame → boş liste."""
        strat = _make_strategy()
        empty = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        signals = strat.generate_signals(empty)
        assert signals == []


# ---------------------------------------------------------------------------
# 7. SL / TP geometrisi — end-to-end
# ---------------------------------------------------------------------------

class TestSLTPGeometry:
    def test_2r_tp_at_correct_distance(self):
        """TP = close - 2 * risk (short, R=2.0)."""
        n = 60
        df = _make_ohlcv(n, base_price=100.0, seed=31)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        atr = float(df_feat["atr14"].iloc[40])
        close_val = float(df_feat["close"].iloc[40])
        if np.isnan(atr) or atr <= 0:
            pytest.skip("atr14 NaN")

        bo_extreme = close_val + 3.0 * atr
        df_feat.loc[40, "bull_trap_short"] = True
        df_feat.loc[40, "bull_bo_extreme"] = bo_extreme
        df_feat.loc[40, "atr_pct"] = 0.02

        signals = strat.generate_signals(df_feat)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) >= 1

        sig = short_sigs[0]
        risk = sig.sl_price - close_val
        expected_tp = close_val - 2.0 * risk
        assert abs(sig.tp_price - expected_tp) < 0.01, (
            f"TP beklenen={expected_tp:.4f}, gelen={sig.tp_price:.4f}"
        )


# ---------------------------------------------------------------------------
# 8. Smoke test — rastgele veri, exception yok
# ---------------------------------------------------------------------------

def test_smoke_run_random_data():
    """Rastgele veriye karşı smoke testi — exception olmamalı."""
    rng = np.random.default_rng(2026)
    n = 300
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.001, 0.018, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(1e6, 5e6, n)
    df = pd.DataFrame({
        "ts": _base_ts(n),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "venue": "binance",
        "symbol": "SMOKE/USDT",
        "timeframe": "1d",
    })
    strat = _make_strategy()
    df_feat = strat.prepare_features(df)
    signals = strat.generate_signals(df_feat)
    assert isinstance(signals, list)

    # SL/TP tutarlılık
    for sig in signals:
        if sig.direction == "short":
            assert sig.sl_price > sig.tp_price, "Short: SL > TP olmalı"
        elif sig.direction == "long":
            assert sig.sl_price < sig.tp_price, "Long: SL < TP olmalı"


# ---------------------------------------------------------------------------
# 9. prepare_features kolon kontrolü
# ---------------------------------------------------------------------------

def test_prepare_features_required_columns():
    """prepare_features gerekli tüm kolonları eklemeli."""
    strat = _make_strategy()
    df = _make_ohlcv(80)
    df_feat = strat.prepare_features(df)

    required_cols = [
        "atr14", "atr_pct", "ema20", "ema50",
        "rolling_20b_high", "rolling_20b_low",
        "bull_bo_bar", "bear_bo_bar",
        "bull_trap_short", "bear_trap_long",
        "bull_bo_extreme", "bear_bo_extreme",
        "range_center", "kaufman_er", "vol_z",
    ]
    for col in required_cols:
        assert col in df_feat.columns, f"Eksik kolon: {col}"


# ---------------------------------------------------------------------------
# 10. Default manifest
# ---------------------------------------------------------------------------

def test_default_manifest_valid():
    """_default_manifest() geçerli StrategyManifest döndürmeli."""
    m = _default_manifest()
    assert m.name == "brooks_failed_breakout"
    assert len(m.signals.patterns) == 2
    pattern_ids = {p.id for p in m.signals.patterns}
    assert "bull_trap_short" in pattern_ids
    assert "bear_trap_long" in pattern_ids
    assert m.risk.get("take_profit", {}).get("primary_R", 0) == 2.0


def test_default_manifest_strategy_instantiation():
    """Default manifest ile strateji oluşturulabilmeli."""
    m = _default_manifest()
    strat = BrooksFailedBreakoutStrategy(m)
    assert strat.name == "brooks_failed_breakout"
    assert strat.version == "1.0.0"
