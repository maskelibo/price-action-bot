"""SEC26.C-3 — Numba performance patch testleri.

4 test kategorisi:

N-1  test_numba_python_parity        — CRITICAL: JIT == Python (rtol=1e-9)
N-2  test_numba_jit_compiles         — numba varsa kernel derlenmeli
N-3  test_numba_fallback_on_error    — JIT hatası → python fallback, no crash
N-4  test_use_numba_false_uses_python — use_numba=False → python path kullanılır

Ek:
N-5  test_vectorized_reversal_parity — vektörize reversal == scalar per-bar
N-6  test_prepare_features_use_numba_false — prepare_features(use_numba=False) çalışır
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.naked_poc_mr import (
    _NUMBA_AVAILABLE,
    _compute_long_poc,
    _compute_long_poc_python,
    _compute_bullish_reversal_vectorized,
    _compute_bearish_reversal_vectorized,
    _bullish_reversal_pattern,
    _bearish_reversal_pattern,
    NakedPOCMeanReversionStrategy,
    _poc_jit_fn,
)


# ---------------------------------------------------------------------------
# Yardımcı fabrikalar
# ---------------------------------------------------------------------------

def _base_ts(n: int) -> list[datetime]:
    start = datetime(2022, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def _make_df(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Gerçekçi BTC-benzeri sentetik OHLCV."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0005, 0.018, n)
    close = 30_000.0 * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(1e9, 5e9, n)
    return pd.DataFrame({
        "ts": _base_ts(n),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "venue": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1d",
    })


def _make_strategy() -> NakedPOCMeanReversionStrategy:
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "naked_poc_mr",
        "version": "0.0.1",
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "naked_poc_long",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "vp_lookback": 60,
                        "vp_bins": 50,
                        "untested_lookback": 30,
                        "poc_band_atr": 0.3,
                        "atr_distance_min": 1.0,
                        "drift_lookback": 5,
                    },
                },
                {
                    "id": "naked_poc_short",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "vp_lookback": 60,
                        "vp_bins": 50,
                        "untested_lookback": 30,
                        "poc_band_atr": 0.3,
                        "atr_distance_min": 1.0,
                        "drift_lookback": 5,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 3},
                "support_resistance": {
                    "lookback_bars": 60,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 60,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {"atr_min_pct": 0.0, "volume_zscore_min": 0.0},
            "confluence": {"method": "weighted_sum", "min_score": 1.0, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "stop_loss": {"method": "structural_atr", "swing_lookback": 10, "atr_buffer": 1.5},
            "take_profit": {"method": "poc_target"},
        },
    }
    return NakedPOCMeanReversionStrategy(StrategyManifest.model_validate(raw))


# ---------------------------------------------------------------------------
# N-1: Numba–Python parity (CRITICAL)
# ---------------------------------------------------------------------------

class TestNumbaPythonParity:
    """_compute_long_poc(use_numba=True) == _compute_long_poc(use_numba=False)."""

    def test_numba_python_parity_small(self):
        """200-bar veri: numba ve python path aynı sonuç (rtol=1e-9)."""
        df = _make_df(n=200, seed=7)
        py_poc = _compute_long_poc(df, lookback=60, bins=50, use_numba=False)
        nb_poc = _compute_long_poc(df, lookback=60, bins=50, use_numba=True)

        assert len(py_poc) == len(nb_poc), "Uzunluklar eşit olmalı"

        # NaN pattern aynı olmalı
        py_nan = py_poc.isna()
        nb_nan = nb_poc.isna()
        assert (py_nan == nb_nan).all(), (
            f"NaN pozisyonları farklı: "
            f"py_nan_count={py_nan.sum()} nb_nan_count={nb_nan.sum()}"
        )

        # Sayısal değerler bit-identical veya en azından rtol=1e-9
        valid_mask = ~py_nan
        if valid_mask.any():
            np.testing.assert_allclose(
                nb_poc[valid_mask].values,
                py_poc[valid_mask].values,
                rtol=1e-9,
                err_msg="Numba JIT sonucu Python ile aynı olmalı (rtol=1e-9)",
            )

    def test_numba_python_parity_lookback_bins_variants(self):
        """Farklı lookback/bins kombinasyonlarında parity."""
        df = _make_df(n=300, seed=13)
        for lookback, bins in [(30, 30), (60, 50), (90, 20)]:
            py_poc = _compute_long_poc(df, lookback=lookback, bins=bins, use_numba=False)
            nb_poc = _compute_long_poc(df, lookback=lookback, bins=bins, use_numba=True)

            valid = ~py_poc.isna()
            if valid.any():
                np.testing.assert_allclose(
                    nb_poc[valid].values,
                    py_poc[valid].values,
                    rtol=1e-9,
                    err_msg=f"Parity başarısız: lookback={lookback} bins={bins}",
                )

    def test_prepare_features_numba_python_parity(self):
        """prepare_features(use_numba=True/False) aynı poc serisi üretmeli."""
        df = _make_df(n=200, seed=99)
        strat = _make_strategy()

        df_py = strat.prepare_features(df.copy(), use_numba=False)
        df_nb = strat.prepare_features(df.copy(), use_numba=True)

        valid = ~df_py["poc"].isna()
        if valid.any():
            np.testing.assert_allclose(
                df_nb["poc"][valid].values,
                df_py["poc"][valid].values,
                rtol=1e-9,
                err_msg="prepare_features numba/python poc parity başarısız",
            )

        # Reversal pattern parity (vektörize == vektörize, her iki path aynı kodu kullanır)
        assert (df_py["bull_reversal"] == df_nb["bull_reversal"]).all(), (
            "bull_reversal numba/python path arasında farklı"
        )
        assert (df_py["bear_reversal"] == df_nb["bear_reversal"]).all(), (
            "bear_reversal numba/python path arasında farklı"
        )


# ---------------------------------------------------------------------------
# N-2: Numba JIT derleme testi
# ---------------------------------------------------------------------------

class TestNumbaJITCompiles:
    def test_numba_jit_compiles_if_available(self):
        """Numba varsa _poc_jit_fn callable ve derlenmeli."""
        if not _NUMBA_AVAILABLE:
            pytest.skip("numba yüklü değil — fallback testi N-3'te")

        assert _poc_jit_fn is not None, "_poc_jit_fn None olmamalı (numba varken)"
        assert callable(_poc_jit_fn), "_poc_jit_fn callable olmalı"

        # Küçük veri üzerinde çalışır mı?
        lows = np.array([98.0, 97.5, 98.2, 97.8, 98.0, 98.5, 99.0, 98.7, 98.3, 97.9,
                         98.1, 98.4, 99.1, 98.8, 97.6, 98.9, 99.2, 98.0, 97.5, 98.3,
                         98.6, 99.0, 98.2, 97.8, 98.4, 98.7, 99.1, 98.5, 97.9, 98.2,
                         98.0, 97.6, 98.3, 98.9, 99.2, 98.1, 97.7, 98.5, 99.0, 98.3,
                         98.7, 99.1, 98.4, 97.8, 98.2, 98.6, 99.0, 98.3, 97.9, 98.1])
        highs = lows + 2.5
        vols = np.ones(50) * 1e6

        result = _poc_jit_fn(lows, highs, vols, 20, 10)
        assert isinstance(result, np.ndarray), "JIT çıktı numpy array olmalı"
        assert len(result) == 50, "JIT çıktı uzunluğu girdi ile aynı olmalı"

        # İlk lookback=20 barlar NaN olmalı
        assert np.all(np.isnan(result[:20])), "İlk 20 bar NaN olmalı (lookback=20)"
        # t=20'den sonra değer üretilmeli
        valid_vals = result[20:]
        non_nan = valid_vals[~np.isnan(valid_vals)]
        assert len(non_nan) > 0, "t>=20'de en az bir geçerli POC olmalı"

    def test_numba_module_available(self):
        """numba import ya başarılı ya da _NUMBA_AVAILABLE=False tutarlı."""
        try:
            import numba  # noqa: F401
            # numba yüklüyse _NUMBA_AVAILABLE True olmalı
            assert _NUMBA_AVAILABLE is True, (
                "numba yüklü ama _NUMBA_AVAILABLE=False — import sırasında hata oluştu"
            )
        except ImportError:
            assert _NUMBA_AVAILABLE is False, (
                "numba yüklü değil ama _NUMBA_AVAILABLE=True"
            )


# ---------------------------------------------------------------------------
# N-3: Fallback on error
# ---------------------------------------------------------------------------

class TestNumbaFallbackOnError:
    def test_compute_long_poc_falls_back_when_numba_unavailable(self):
        """_NUMBA_AVAILABLE=False simülasyonu: use_numba=True → python path, no crash."""
        df = _make_df(n=120, seed=55)

        # Numba'yı geçici olarak devre dışı bırak
        import price_action.strategies.naked_poc_mr as mod
        orig = mod._NUMBA_AVAILABLE
        orig_fn = mod._poc_jit_fn
        try:
            mod._NUMBA_AVAILABLE = False
            mod._poc_jit_fn = None

            # use_numba=True bile olsa python fallback çalışmalı
            result = _compute_long_poc(df, lookback=60, bins=50, use_numba=True)

            assert isinstance(result, pd.Series), "Fallback pd.Series dönmeli"
            assert len(result) == len(df), "Fallback uzunluğu girdi ile eşit olmalı"
            # İlk 60 bar NaN
            assert result.iloc[:60].isna().all(), "Fallback: ilk 60 bar NaN olmalı"

        finally:
            mod._NUMBA_AVAILABLE = orig
            mod._poc_jit_fn = orig_fn

    def test_compute_long_poc_falls_back_on_jit_exception(self):
        """JIT fonksiyonu exception fırlatırsa python fallback devreye girmeli."""
        df = _make_df(n=120, seed=66)

        import price_action.strategies.naked_poc_mr as mod
        orig_available = mod._NUMBA_AVAILABLE
        orig_fn = mod._poc_jit_fn

        def _bad_jit(*args, **kwargs):
            raise RuntimeError("simulated JIT error")

        try:
            mod._NUMBA_AVAILABLE = True
            mod._poc_jit_fn = _bad_jit

            # JIT hatasına rağmen sonuç üretmeli
            result = _compute_long_poc(df, lookback=60, bins=50, use_numba=True)
            assert isinstance(result, pd.Series), "JIT hatasında fallback pd.Series dönmeli"
            assert len(result) == len(df)

        finally:
            mod._NUMBA_AVAILABLE = orig_available
            mod._poc_jit_fn = orig_fn

    def test_no_crash_on_empty_df(self):
        """Boş df + use_numba=True → crash yok."""
        df = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        strat = _make_strategy()
        result = strat.generate_signals(df, use_numba=True)
        assert result == []

    def test_no_crash_on_empty_df_use_numba_false(self):
        """Boş df + use_numba=False → crash yok."""
        df = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        strat = _make_strategy()
        result = strat.generate_signals(df, use_numba=False)
        assert result == []


# ---------------------------------------------------------------------------
# N-4: use_numba=False python path kullanır
# ---------------------------------------------------------------------------

class TestUseNumbaFalse:
    def test_use_numba_false_returns_same_as_python_direct(self):
        """use_numba=False ile _compute_long_poc doğrudan python path kullanmalı."""
        df = _make_df(n=150, seed=11)
        lows = df["low"].values.astype(np.float64)
        highs = df["high"].values.astype(np.float64)
        vols = df["volume"].values.astype(np.float64)

        # use_numba=False
        result_flag = _compute_long_poc(df, lookback=60, bins=50, use_numba=False)
        # Doğrudan python impl
        result_direct = _compute_long_poc_python(lows, highs, vols, 60, 50, df.index)

        np.testing.assert_array_equal(
            result_flag.values,
            result_direct.values,
            err_msg="use_numba=False ve _compute_long_poc_python aynı sonuç vermeli",
        )

    def test_generate_signals_use_numba_false_no_crash(self):
        """generate_signals(df, use_numba=False) exception olmadan çalışmalı."""
        df = _make_df(n=200, seed=22)
        strat = _make_strategy()
        signals = strat.generate_signals(df, use_numba=False)
        assert isinstance(signals, list)

    def test_generate_signals_use_numba_true_no_crash(self):
        """generate_signals(df, use_numba=True) exception olmadan çalışmalı."""
        df = _make_df(n=200, seed=33)
        strat = _make_strategy()
        signals = strat.generate_signals(df, use_numba=True)
        assert isinstance(signals, list)

    def test_signal_counts_identical_numba_vs_python(self):
        """use_numba=True ve False aynı sayıda sinyal üretmeli."""
        df = _make_df(n=300, seed=44)
        strat = _make_strategy()

        sigs_py = strat.generate_signals(df.copy(), use_numba=False)
        sigs_nb = strat.generate_signals(df.copy(), use_numba=True)

        assert len(sigs_py) == len(sigs_nb), (
            f"Sinyal sayısı farklı: python={len(sigs_py)} numba={len(sigs_nb)}"
        )


# ---------------------------------------------------------------------------
# N-5: Vektörize reversal parity (vs scalar per-bar)
# ---------------------------------------------------------------------------

class TestVectorizedReversalParity:
    def test_bullish_reversal_vectorized_matches_scalar(self):
        """_compute_bullish_reversal_vectorized == per-bar _bullish_reversal_pattern."""
        df = _make_df(n=200, seed=77)

        vec_flags = _compute_bullish_reversal_vectorized(df)
        scalar_flags = np.array([_bullish_reversal_pattern(df, i) for i in range(len(df))])

        mismatches = np.where(vec_flags != scalar_flags)[0]
        assert len(mismatches) == 0, (
            f"Vektörize ve scalar bullish reversal {len(mismatches)} bar'da farklı: "
            f"indices={mismatches[:10]}"
        )

    def test_bearish_reversal_vectorized_matches_scalar(self):
        """_compute_bearish_reversal_vectorized == per-bar _bearish_reversal_pattern."""
        df = _make_df(n=200, seed=88)

        vec_flags = _compute_bearish_reversal_vectorized(df)
        scalar_flags = np.array([_bearish_reversal_pattern(df, i) for i in range(len(df))])

        mismatches = np.where(vec_flags != scalar_flags)[0]
        assert len(mismatches) == 0, (
            f"Vektörize ve scalar bearish reversal {len(mismatches)} bar'da farklı: "
            f"indices={mismatches[:10]}"
        )

    def test_first_bar_always_false(self):
        """idx=0 için her iki reversal flag daima False olmalı."""
        df = _make_df(n=50, seed=3)
        bull_vec = _compute_bullish_reversal_vectorized(df)
        bear_vec = _compute_bearish_reversal_vectorized(df)
        assert bull_vec[0] is False or bull_vec[0] == False, "İlk bar bull False olmalı"
        assert bear_vec[0] is False or bear_vec[0] == False, "İlk bar bear False olmalı"

    def test_vectorized_engulfing_detected(self):
        """Klasik bullish engulfing vektörize ile doğru tespit edilmeli."""
        df = pd.DataFrame({
            "ts": _base_ts(3),
            "open":  [100.0, 102.0, 98.0],
            "close": [100.0, 98.5,  103.0],
            "high":  [101.0, 103.0, 104.5],
            "low":   [99.0,  97.5,  97.0],
        })
        bull_vec = _compute_bullish_reversal_vectorized(df)
        assert bull_vec[2], "Bullish engulfing vektörize tespit edilmeli"

    def test_vectorized_shooting_star_detected(self):
        """Klasik bearish engulfing vektörize ile doğru tespit edilmeli."""
        df = pd.DataFrame({
            "ts": _base_ts(3),
            "open":  [100.0, 98.0,  103.5],
            "close": [100.0, 103.5, 97.0],
            "high":  [101.0, 104.0, 104.5],
            "low":   [99.0,  97.5,  96.0],
        })
        bear_vec = _compute_bearish_reversal_vectorized(df)
        assert bear_vec[2], "Bearish engulfing vektörize tespit edilmeli"


# ---------------------------------------------------------------------------
# N-6: prepare_features use_numba=False
# ---------------------------------------------------------------------------

class TestPrepareFeaturesFallback:
    def test_prepare_features_use_numba_false_all_columns(self):
        """prepare_features(use_numba=False) tüm gerekli kolonları üretmeli."""
        df = _make_df(n=150, seed=5)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df, use_numba=False)

        required = [
            "ema200", "atr14", "atr_pct",
            "poc", "poc_naked", "poc_drift",
            "bull_reversal", "bear_reversal",
            "struct_sl_long", "struct_sl_short",
            "vol_z", "dist_to_poc_atr",
        ]
        for col in required:
            assert col in df_feat.columns, f"Eksik kolon (use_numba=False): {col}"

    def test_prepare_features_use_numba_true_all_columns(self):
        """prepare_features(use_numba=True) tüm gerekli kolonları üretmeli."""
        df = _make_df(n=150, seed=6)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df, use_numba=True)

        required = [
            "ema200", "atr14", "atr_pct",
            "poc", "poc_naked", "poc_drift",
            "bull_reversal", "bear_reversal",
            "struct_sl_long", "struct_sl_short",
            "vol_z", "dist_to_poc_atr",
        ]
        for col in required:
            assert col in df_feat.columns, f"Eksik kolon (use_numba=True): {col}"
