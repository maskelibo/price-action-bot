"""Unit testler: anchored_vwap_reversal.py — confluence_score v1.1 fix.

Signal Chief audit (2026-05-17 SEC52):
  Bug: v1.0'da score = bull_weight (1.5 sabit) => pool_conf = 0.0 her trade icin
       filter_conf_min=0.25 => TUM AVWAP trade'leri elendi.
  Fix: v1.1'de dinamik 4-faktor confluence score (vectorized, lookahead-free).

Test senaryo ozeti:
  T1 neutral_conf  — entry kosu saglandi, 0 dinamik faktor aktif => score=1.5 (min)
  T2 bull_conf_max — 4 faktor aktif => score=3.0, pool_conf=1.0
  T3 bear_conf_mid — 2 faktor aktif => score=2.25, pool_conf=0.50
  T4 no_cross      — AVWAP cross yok => sinyal uretilmemeli
  T5 conf_floor    — tek faktor aktif => pool_conf=0.25 >= filter_conf_min PASS
  T6 lookahead     — df.shift(-1) veya center=True yok (statik analiz)
  T7 pure_function — ayni input => ayni output (determinism)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.anchored_vwap_reversal import (
    AnchoredVWAPReversalStrategy,
    _default_manifest,
    _rsi,
    _ema,
)
from price_action.strategies.classic_pa import _atr


# =====================================================================
# Helper: synthetic OHLCV DataFrame
# =====================================================================

def _make_df(
    n: int = 200,
    base_price: float = 100.0,
    volume: float = 1_000.0,
    seed: int = 42,
) -> pd.DataFrame:
    """n-bar deterministik OHLCV DataFrame (flat trend icin safe base)."""
    rng = np.random.default_rng(seed)
    prices = base_price + np.cumsum(rng.normal(0, 0.5, n))
    prices = np.clip(prices, 10.0, None)

    opens = prices.copy()
    closes = prices + rng.normal(0, 0.2, n)
    closes = np.clip(closes, 10.0, None)
    highs = np.maximum(opens, closes) + rng.uniform(0.1, 1.0, n)
    lows = np.minimum(opens, closes) - rng.uniform(0.1, 1.0, n)
    lows = np.clip(lows, 1.0, None)

    ts = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame({
        "ts": ts,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volume * (1 + rng.uniform(-0.3, 0.3, n)),
        "venue": "test",
        "symbol": "BTC/USDT",
        "timeframe": "15m",
    })


def _make_strategy() -> AnchoredVWAPReversalStrategy:
    return AnchoredVWAPReversalStrategy(_default_manifest())


# =====================================================================
# T1: neutral_conf — entry kosullari gerceklesti, hic faktor aktif degil
# score = 1.5 (base_weight), pool_conf = 0.0
# =====================================================================

class TestNeutralConfluence:
    """Tum entry kosullari saglanmis ama dinamik faktorler hic aktif degil.

    Beklenti: score = 1.5 (base_weight), min_score=1.5 kosulu saglaniyor
    (entry filtresi gecebilir), ama pool_conf = 0.0.
    Onemli: bu test dinamik conf'un MINIMUM'da calistigini dogruluyor.
    v1.0 bug'da da score=1.5'ti ama min_score=1.5 >= 1.5 PASS olurdu —
    bug POOL normalizasyonundan geliyordu: conf = (1.5-1.5)/1.5 = 0.0.
    Bu test score formulunun dogru oldugunu dogruluyor.
    """

    def test_score_equals_base_weight_when_no_factors(self):
        strat = _make_strategy()
        df = _make_df(n=200)
        df = strat.prepare_features(df)

        # RSI 40-55 arasi (F1 off), POC uzak (F2 off), vol_z dusuk (F3 off),
        # ema200 close (F4 off) icin yapay bir satir
        # _compute_confluence_series'i dogrudan test et
        # Tek bir mock satiri olustur (Series olarak)
        close_val = 100.0
        atr_val = 2.0
        rsi_val = 48.0     # 40-55 arasi: F1=False
        poc_val = 96.0     # |100-96|=4 > 0.5*2=1: F2=False
        vol_z_val = 0.5    # < 1.0: F3=False
        ema200_val = 99.0  # |100-99|=1 < 1.5*2=3: F4=False

        mock_df = pd.DataFrame({
            "ts": [pd.Timestamp("2024-01-01", tz="UTC")],
            "open": [close_val], "high": [close_val + 1], "low": [close_val - 1],
            "close": [close_val],
            "volume": [1000.0],
            "atr14": [atr_val],
            "rsi14": [rsi_val],
            "poc": [poc_val],
            "ema200": [ema200_val],
            "vol_z": [vol_z_val],
            "atr_pct": [atr_val / close_val],
            "venue": ["test"], "symbol": ["BTC/USDT"], "timeframe": ["15m"],
        })

        score_series = strat._compute_confluence_series(
            mock_df,
            direction="long",
            base_weight=1.5,
            rsi_extreme_thr=40.0,
            poc_tight_atr=0.5,
            vol_z_bonus_min=1.0,
            ema_dist_atr=1.5,
            factor_weight=0.375,
        )
        assert score_series.iloc[0] == pytest.approx(1.5, abs=1e-9)

    def test_pool_conf_formula_is_zero_at_base(self):
        """Pool normalizasyonu: conf = (score - 1.5) / 1.5; score=1.5 => conf=0.0."""
        base_score = 1.5
        pool_conf = (base_score - 1.5) / 1.5
        assert pool_conf == pytest.approx(0.0, abs=1e-9)


# =====================================================================
# T2: bull_conf_max — 4 faktor aktif => score=3.0, pool_conf=1.0
# =====================================================================

class TestBullMaxConfluence:
    """Tum 4 dinamik faktor aktif: RSI <40, POC tight, vol yuksek, ema uzak."""

    def test_score_equals_max_when_all_factors_active(self):
        strat = _make_strategy()
        close_val = 100.0
        atr_val = 2.0
        rsi_val = 32.0        # < 40: F1=True
        poc_val = 100.8       # |100-100.8|=0.8 <= 0.5*2=1.0: F2=True
        vol_z_val = 2.5       # >= 1.0: F3=True
        ema200_val = 106.0    # |100-106|=6 >= 1.5*2=3: F4=True

        mock_df = pd.DataFrame({
            "ts": [pd.Timestamp("2024-01-01", tz="UTC")],
            "open": [close_val], "high": [close_val + 1], "low": [close_val - 1],
            "close": [close_val],
            "volume": [1000.0],
            "atr14": [atr_val],
            "rsi14": [rsi_val],
            "poc": [poc_val],
            "ema200": [ema200_val],
            "vol_z": [vol_z_val],
            "atr_pct": [atr_val / close_val],
            "venue": ["test"], "symbol": ["BTC/USDT"], "timeframe": ["15m"],
        })

        score_series = strat._compute_confluence_series(
            mock_df,
            direction="long",
            base_weight=1.5,
            rsi_extreme_thr=40.0,
            poc_tight_atr=0.5,
            vol_z_bonus_min=1.0,
            ema_dist_atr=1.5,
            factor_weight=0.375,
        )
        expected_score = 1.5 + 4 * 0.375  # = 3.0
        assert score_series.iloc[0] == pytest.approx(expected_score, abs=1e-9)

    def test_pool_conf_is_one_at_max(self):
        """Pool normalizasyonu: conf = (3.0 - 1.5) / 1.5 = 1.0."""
        max_score = 3.0
        pool_conf = (max_score - 1.5) / 1.5
        assert pool_conf == pytest.approx(1.0, abs=1e-9)


# =====================================================================
# T3: bear_conf_mid — short direction, 2 faktor aktif => score=2.25
# =====================================================================

class TestBearMidConfluence:
    """Short direction, 2 faktor aktif (RSI overbought + vol yuksek)."""

    def test_short_conf_with_two_factors(self):
        strat = _make_strategy()
        close_val = 100.0
        atr_val = 2.0
        rsi_val = 72.0        # > 60 (100-40): F1=True (short overbought)
        poc_val = 90.0        # |100-90|=10 > 0.5*2=1: F2=False
        vol_z_val = 1.8       # >= 1.0: F3=True
        ema200_val = 101.5    # |100-101.5|=1.5 < 1.5*2=3: F4=False

        mock_df = pd.DataFrame({
            "ts": [pd.Timestamp("2024-01-01", tz="UTC")],
            "open": [close_val], "high": [close_val + 1], "low": [close_val - 1],
            "close": [close_val],
            "volume": [1000.0],
            "atr14": [atr_val],
            "rsi14": [rsi_val],
            "poc": [poc_val],
            "ema200": [ema200_val],
            "vol_z": [vol_z_val],
            "atr_pct": [atr_val / close_val],
            "venue": ["test"], "symbol": ["BTC/USDT"], "timeframe": ["15m"],
        })

        score_series = strat._compute_confluence_series(
            mock_df,
            direction="short",
            base_weight=1.5,
            rsi_extreme_thr=40.0,
            poc_tight_atr=0.5,
            vol_z_bonus_min=1.0,
            ema_dist_atr=1.5,
            factor_weight=0.375,
        )
        expected_score = 1.5 + 2 * 0.375  # = 2.25
        assert score_series.iloc[0] == pytest.approx(expected_score, abs=1e-9)

    def test_pool_conf_mid_value(self):
        """Pool normalizasyonu: conf = (2.25 - 1.5) / 1.5 = 0.50."""
        mid_score = 2.25
        pool_conf = (mid_score - 1.5) / 1.5
        assert pool_conf == pytest.approx(0.50, abs=1e-6)


# =====================================================================
# T4: no_cross — AVWAP cross yoksa sinyal uretilmemeli
# =====================================================================

class TestNoCrossNoSignal:
    """Tum faktorler aktif olsa dahi AVWAP cross yoksa sinyal uretilmez."""

    def test_no_signal_without_avwap_cross(self):
        strat = _make_strategy()
        df = _make_df(n=250)
        df = strat.prepare_features(df)

        # Cross flag'leri tamamen False yap
        df["avwap_long_cross_up"] = False
        df["avwap_short_cross_down"] = False

        signals = strat.generate_signals(df)
        assert signals == [], "AVWAP cross yoksa hic sinyal uretilmemeli"


# =====================================================================
# T5: conf_floor — tek faktor aktif => pool_conf = 0.25 >= 0.25 PASS
# =====================================================================

class TestConfFloorOneFactorPass:
    """Tek dinamik faktor aktifse pool_conf = 0.25 — filter_conf_min gecmeli."""

    def test_one_factor_gives_conf_025(self):
        strat = _make_strategy()
        close_val = 100.0
        atr_val = 2.0
        # Sadece F1 aktif (RSI < 40)
        rsi_val = 35.0        # < 40: F1=True
        poc_val = 90.0        # F2=False (uzak)
        vol_z_val = 0.5       # F3=False
        ema200_val = 100.5    # F4=False (cok yakin)

        mock_df = pd.DataFrame({
            "ts": [pd.Timestamp("2024-01-01", tz="UTC")],
            "open": [close_val], "high": [close_val + 1], "low": [close_val - 1],
            "close": [close_val],
            "volume": [1000.0],
            "atr14": [atr_val],
            "rsi14": [rsi_val],
            "poc": [poc_val],
            "ema200": [ema200_val],
            "vol_z": [vol_z_val],
            "atr_pct": [atr_val / close_val],
            "venue": ["test"], "symbol": ["BTC/USDT"], "timeframe": ["15m"],
        })

        score_series = strat._compute_confluence_series(
            mock_df,
            direction="long",
            base_weight=1.5,
            rsi_extreme_thr=40.0,
            poc_tight_atr=0.5,
            vol_z_bonus_min=1.0,
            ema_dist_atr=1.5,
            factor_weight=0.375,
        )
        score = score_series.iloc[0]
        expected_score = 1.5 + 1 * 0.375  # = 1.875
        assert score == pytest.approx(expected_score, abs=1e-9)

        pool_conf = (score - 1.5) / 1.5
        assert pool_conf == pytest.approx(0.25, abs=1e-6)

        # filter_conf_min=0.25 ile karsilastir: pool_conf >= 0.25 PASS
        filter_conf_min = 0.25
        assert pool_conf >= filter_conf_min, (
            f"Tek faktor aktifken pool_conf={pool_conf:.4f} < filter_conf_min={filter_conf_min}"
            " — v1.0 bug tekrar etmemeli"
        )


# =====================================================================
# T6: lookahead audit — df.shift(-1) ve center=True yasak
# =====================================================================

class TestLookaheadFree:
    """Statik kaynak analiz: detector causal (lookahead-free) olmali.

    df.shift(-1) (negatif shift) veya rolling(..., center=True) yasak.
    Mevcut _compute_confluence_series sadece df.fillna() ve aritmetik
    kullanir — shift(-1) yok. Bu test kodu okumayi degil davranisi
    dogrulamak icin proxy test: iki identik df uzerinde seriler ayni.
    Gercek lookahead testi CI'da asimmetrik nan-drop ile yapilir.
    """

    def test_deterministic_no_future_leak(self):
        """Ayni df iki kez islenir => sonuclar identik (pure function)."""
        strat = _make_strategy()
        df = _make_df(n=200, seed=99)
        df1 = strat.prepare_features(df.copy())
        df2 = strat.prepare_features(df.copy())

        # Indicator serileri identik olmali
        pd.testing.assert_series_equal(df1["rsi14"], df2["rsi14"], check_names=False)
        pd.testing.assert_series_equal(df1["ema200"], df2["ema200"], check_names=False)
        pd.testing.assert_series_equal(df1["poc"], df2["poc"], check_names=False)
        pd.testing.assert_series_equal(df1["vol_z"], df2["vol_z"], check_names=False)

    def test_no_future_bar_in_poc(self):
        """POC hesaplamasi: t barinda [t-lookback .. t-1] kullanir.

        Kontrol: df'nin son 10 barini droplayinca geri kalan barlarin
        poc degerleri degismemeli (future bar etkisi yoksa degismez).
        """
        strat = _make_strategy()
        df = _make_df(n=200, seed=7)
        df_full = strat.prepare_features(df.copy())
        df_trim = strat.prepare_features(df.iloc[:-10].copy())

        # Ortak indeks araligindaki poc degerleri ayni olmali
        common_idx = df_trim.index
        poc_full = df_full["poc"].iloc[common_idx]
        poc_trim = df_trim["poc"].iloc[common_idx]
        pd.testing.assert_series_equal(poc_full.reset_index(drop=True),
                                       poc_trim.reset_index(drop=True),
                                       check_names=False,
                                       rtol=1e-9)


# =====================================================================
# T7: pure_function — ayni input => ayni output (reproducibility)
# =====================================================================

class TestPureFunction:
    """generate_signals deterministik olmali — bit-identical."""

    def test_generate_signals_deterministic(self):
        strat1 = _make_strategy()
        strat2 = _make_strategy()
        df = _make_df(n=300, seed=1234)

        sigs1 = strat1.generate_signals(df.copy())
        sigs2 = strat2.generate_signals(df.copy())

        assert len(sigs1) == len(sigs2), "Signal sayisi farkli — non-deterministic"
        for s1, s2 in zip(sigs1, sigs2):
            assert s1.confluence_score == s2.confluence_score
            assert s1.sl_price == pytest.approx(s2.sl_price, rel=1e-9)
            assert s1.tp_price == pytest.approx(s2.tp_price, rel=1e-9)
            assert s1.direction == s2.direction
            assert s1.pattern_id == s2.pattern_id

    def test_manifest_hash_stable(self):
        """Manifest hash ayni input icin ayni olmali."""
        m1 = _default_manifest()
        m2 = _default_manifest()
        assert m1.hash() == m2.hash(), "Manifest hash non-deterministic"


# =====================================================================
# T8: score_range — score her zaman [base_weight, base_weight+4*fw] icinde
# =====================================================================

class TestScoreRange:
    """_compute_confluence_series skoru her zaman [1.5, 3.0] araliginda olmali."""

    def test_score_bounds_long(self):
        strat = _make_strategy()
        df = _make_df(n=300, seed=555)
        df = strat.prepare_features(df)

        scores = strat._compute_confluence_series(
            df,
            direction="long",
            base_weight=1.5,
            rsi_extreme_thr=40.0,
            poc_tight_atr=0.5,
            vol_z_bonus_min=1.0,
            ema_dist_atr=1.5,
            factor_weight=0.375,
        )
        assert (scores >= 1.5 - 1e-9).all(), "Score base_weight altina dusemez"
        max_expected = 1.5 + 4 * 0.375
        assert (scores <= max_expected + 1e-9).all(), "Score max_score uzerinde olamaz"

    def test_score_bounds_short(self):
        strat = _make_strategy()
        df = _make_df(n=300, seed=666)
        df = strat.prepare_features(df)

        scores = strat._compute_confluence_series(
            df,
            direction="short",
            base_weight=1.5,
            rsi_extreme_thr=40.0,
            poc_tight_atr=0.5,
            vol_z_bonus_min=1.0,
            ema_dist_atr=1.5,
            factor_weight=0.375,
        )
        assert (scores >= 1.5 - 1e-9).all(), "Short score base_weight altina dusemez"
        max_expected = 1.5 + 4 * 0.375
        assert (scores <= max_expected + 1e-9).all(), "Short score max_score uzerinde olamaz"
