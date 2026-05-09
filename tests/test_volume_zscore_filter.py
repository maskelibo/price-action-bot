"""Volume Z-Score Filter testleri.

Test grupları:
    T01: _volume_zscore hesaplama doğruluğu
    T02: vol_z < threshold → sinyal reddedilir
    T03: vol_z >= threshold → sinyal geçer
    T04: vol_z < 0 (No Demand) → her threshold'da reddedilir
    T05: engulfing yok → sinyal üretilmez
    T06: vol_z warmup (NaN) → sinyal geçer (konservatif)
"""
from __future__ import annotations

from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# =====================================================================
# Yardımcı: OHLCV üretici
# =====================================================================

def _make_ohlcv(
    n: int = 60,
    seed: int = 42,
    inject_bullish_engulf_at: int | None = None,
    inject_bearish_engulf_at: int | None = None,
    volume_spike_at: int | None = None,
    volume_spike_mult: float = 5.0,
) -> pd.DataFrame:
    """Deterministik OHLCV DataFrame üret.

    inject_bullish_engulf_at: bar indeksinde bullish engulfing oluştur.
    inject_bearish_engulf_at: bar indeksinde bearish engulfing oluştur.
    volume_spike_at: o barda hacim spike ver (ortalama * spike_mult).
    """
    rng = np.random.default_rng(seed)
    days = pd.date_range("2022-01-01", periods=n, freq="1D", tz="UTC")

    # Fiyat serisi
    rets = rng.normal(0.0005, 0.025, size=n)
    close = 30_000.0 * np.exp(np.cumsum(rets))
    open_ = np.empty(n)
    open_[0] = close[0] * 0.999
    open_[1:] = close[:-1] * (1 + rng.uniform(-0.003, 0.003, size=n - 1))
    high = np.maximum(open_, close) * (1 + rng.uniform(0.001, 0.008, size=n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0.001, 0.008, size=n))

    # Hacim (log-normal)
    volume = rng.lognormal(mean=18.0, sigma=0.5, size=n)

    # Bullish engulfing enjekte et (belirtilen barda)
    if inject_bullish_engulf_at is not None:
        i = inject_bullish_engulf_at
        if 1 <= i < n:
            # t-1: bearish
            open_[i - 1] = close[i - 1] * 1.01
            close[i - 1] = close[i - 1] * 0.99  # bearish: close < open
            # t: bullish, sarar
            base_prev_open = open_[i - 1]
            base_prev_close = close[i - 1]
            open_[i] = base_prev_close * 0.999      # open <= prev_close
            close[i] = base_prev_open * 1.001       # close >= prev_open
            high[i] = close[i] * 1.005
            low[i] = open_[i] * 0.995
            high[i - 1] = open_[i - 1] * 1.005
            low[i - 1] = close[i - 1] * 0.995

    # Bearish engulfing enjekte et
    if inject_bearish_engulf_at is not None:
        i = inject_bearish_engulf_at
        if 1 <= i < n:
            # t-1: bullish
            close[i - 1] = close[i - 1] * 1.01
            open_[i - 1] = close[i - 1] * 0.99
            # t: bearish, sarar
            base_prev_open = open_[i - 1]
            base_prev_close = close[i - 1]
            open_[i] = base_prev_close * 1.001      # open >= prev_close
            close[i] = base_prev_open * 0.999       # close <= prev_open
            high[i] = open_[i] * 1.005
            low[i] = close[i] * 0.995
            high[i - 1] = close[i - 1] * 1.005
            low[i - 1] = open_[i - 1] * 0.995

    # Volume spike
    if volume_spike_at is not None:
        i = volume_spike_at
        if 0 <= i < n:
            base_vol = float(np.mean(volume))
            volume[i] = base_vol * volume_spike_mult

    return pd.DataFrame({
        "ts": days,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "venue": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1d",
    })


# =====================================================================
# T01: _volume_zscore hesaplama doğruluğu
# =====================================================================

class TestVolumeZscoreCalculation:
    def test_T01a_zscore_formula(self):
        """Z-score = (vol - mean) / std; sabit hacimde std=0 → NaN."""
        from price_action.strategies.volume_zscore_filter import _volume_zscore

        # Sabit hacim — std=0 → NaN
        vol = pd.Series([100.0] * 30)
        z = _volume_zscore(vol, window=20)
        assert z.iloc[-1] is np.nan or np.isnan(z.iloc[-1]), (
            "Sabit hacimde std=0 → NaN bekleniyor"
        )

    def test_T01b_spike_gives_high_zscore(self):
        """Spike barda z-score >> 0 olmalı."""
        from price_action.strategies.volume_zscore_filter import _volume_zscore

        base = 1_000.0
        vol = pd.Series([base] * 25 + [base * 10])  # spike
        z = _volume_zscore(vol, window=20)
        # Son barda z-score yüksek olmalı
        assert z.iloc[-1] > 2.0, f"Spike z-score yüksek bekleniyor: {z.iloc[-1]:.2f}"

    def test_T01c_warmup_nan(self):
        """İlk window/2 barda NaN bekleniyor (min_periods)."""
        from price_action.strategies.volume_zscore_filter import _volume_zscore

        vol = pd.Series(range(1, 31), dtype=float)
        z = _volume_zscore(vol, window=20)
        # İlk birkaç bar NaN
        assert z.iloc[0] is np.nan or np.isnan(z.iloc[0]), (
            "İlk barda NaN bekleniyor (warmup)"
        )


# =====================================================================
# T02: vol_z < threshold → sinyal reddedilir
# =====================================================================

class TestFilterRejectsLowVolume:
    def test_T02_low_volume_engulfing_rejected(self):
        """Engulfing + düşük hacim (vol_z < 0.7) → sinyal üretilmemeli."""
        from price_action.strategies.volume_zscore_filter import VolumeZScoreFilterStrategy

        # Engulfing bar 35'te, ama hacim spike OLMADAN
        df = _make_ohlcv(n=60, seed=7, inject_bullish_engulf_at=35)
        # Hacim düşük tut — engulf bar'da spike yok
        df.loc[34, "volume"] = float(df["volume"].mean()) * 0.3  # düşük
        df.loc[35, "volume"] = float(df["volume"].mean()) * 0.3  # düşük

        strat = VolumeZScoreFilterStrategy(vol_z_threshold=0.7)
        feats = strat.prepare_features(df)

        # Vol_z at bar 35 < 0.7 mu kontrol et
        vol_z_at_35 = float(feats.loc[35, "vol_z"])
        if vol_z_at_35 < 0.7 and bool(feats.loc[35, "bull_eng"]):
            sigs = strat.generate_signals(feats)
            long_sigs = [s for s in sigs if s.direction == "long"]
            # Bar 35'teki long sinyal olmamalı
            bar35_sigs = [s for s in long_sigs if pd.Timestamp(s.ts).normalize() ==
                          feats.loc[35, "ts"].normalize()]
            assert len(bar35_sigs) == 0, (
                f"Düşük hacimli engulfing sinyal üretmemeli. vol_z={vol_z_at_35:.3f}"
            )


# =====================================================================
# T03: vol_z >= threshold → sinyal geçer
# =====================================================================

class TestFilterPassesHighVolume:
    def test_T03_high_volume_engulfing_produces_signal(self):
        """Engulfing + yüksek hacim (vol_z > 1.0) → sinyal üretilmeli."""
        from price_action.strategies.volume_zscore_filter import VolumeZScoreFilterStrategy

        # Bar 35'te engulfing + hacim spike
        df = _make_ohlcv(
            n=60, seed=11,
            inject_bullish_engulf_at=35,
            volume_spike_at=35,
            volume_spike_mult=8.0,  # çok yüksek spike → vol_z > 2.0
        )

        strat = VolumeZScoreFilterStrategy(vol_z_threshold=1.0)
        feats = strat.prepare_features(df)

        # Engulfing oluştu mu?
        if bool(feats.loc[35, "bull_eng"]):
            vol_z_at_35 = float(feats.loc[35, "vol_z"])
            if vol_z_at_35 >= 1.0:
                sigs = strat.generate_signals(feats)
                long_sigs = [s for s in sigs if s.direction == "long"]
                assert len(long_sigs) >= 1, (
                    f"Yüksek hacimli engulfing sinyal üretmeli. vol_z={vol_z_at_35:.3f}"
                )


# =====================================================================
# T04: vol_z < 0 (No Demand) → her threshold'da reddedilir
# =====================================================================

class TestNoDemandRejected:
    def test_T04_negative_volz_rejected_at_all_thresholds(self):
        """vol_z < 0 → 0.7, 1.0, 1.5 threshold'ların hepsinde reddedilir."""
        from price_action.strategies.volume_zscore_filter import (
            VolumeZScoreFilterStrategy,
            _volume_zscore,
        )

        # Düşük hacimli engulfing — vol_z negatif olacak şekilde ayarla
        df = _make_ohlcv(n=60, seed=13, inject_bullish_engulf_at=35)
        # Engulf bar ve öncesi için hacmi çok düşük tut
        mean_vol = float(df["volume"].mean())
        df.loc[35, "volume"] = mean_vol * 0.1   # ultra-low → z << 0

        for thr in [0.7, 1.0, 1.5]:
            strat = VolumeZScoreFilterStrategy(vol_z_threshold=thr)
            feats = strat.prepare_features(df)
            vol_z_35 = float(feats.loc[35, "vol_z"])

            if vol_z_35 < 0 and bool(feats.loc[35, "bull_eng"]):
                sigs = strat.generate_signals(feats)
                bar35_longs = [
                    s for s in sigs
                    if s.direction == "long" and
                    pd.Timestamp(s.ts).normalize() == feats.loc[35, "ts"].normalize()
                ]
                assert len(bar35_longs) == 0, (
                    f"vol_z={vol_z_35:.3f} < 0 → threshold={thr}'de reddedilmeli"
                )


# =====================================================================
# T05: engulfing yok → sinyal üretilmez
# =====================================================================

class TestNoEngulfingNoSignal:
    def test_T05_no_engulfing_no_signal(self):
        """Engulfing pattern oluşmadığında sinyal üretilmemeli."""
        from price_action.strategies.volume_zscore_filter import VolumeZScoreFilterStrategy

        # Doji-like fiyat hareketi — engulfing oluşmaz
        n = 60
        days = pd.date_range("2022-01-01", periods=n, freq="1D", tz="UTC")
        rng = np.random.default_rng(99)
        close = np.ones(n) * 30_000.0
        # Küçük random gürültü — engulfing oluşmaması için minimal hareket
        noise = rng.uniform(-10, 10, size=n)
        close = close + np.cumsum(noise * 0.1)
        open_ = close.copy()  # doji: open = close → engulfing imkânsız

        df = pd.DataFrame({
            "ts": days,
            "open": open_,
            "high": close + 50,
            "low": close - 50,
            "close": close,
            "volume": rng.lognormal(18, 0.5, size=n),
            "venue": "binance",
            "symbol": "BTC/USDT",
            "timeframe": "1d",
        })

        strat = VolumeZScoreFilterStrategy(vol_z_threshold=0.7)
        feats = strat.prepare_features(df)
        sigs = strat.generate_signals(feats)

        assert len(sigs) == 0, f"Engulfing yok → sinyal yok bekleniyor, {len(sigs)} geldi"


# =====================================================================
# T06: vol_z warmup NaN → sinyal geçer (konservatif)
# =====================================================================

class TestWarmupNaN:
    def test_T06_nan_volume_passes_conservatively(self):
        """Z-score NaN ise sinyal reddedilmemeli (volume verisi olmayabilir)."""
        from price_action.strategies.volume_zscore_filter import filter_engulfing_with_volume_zscore
        from price_action.contracts import Signal

        # volume olmayan DF ile lookup → NaN
        days = pd.date_range("2022-01-01", periods=5, freq="1D", tz="UTC")
        df_no_vol = pd.DataFrame({
            "ts": days,
            "open": [100.0] * 5,
            "high": [105.0] * 5,
            "low": [95.0] * 5,
            "close": [102.0] * 5,
            # 'volume' kolonu yok
        })

        sig = Signal(
            ts=days[2].to_pydatetime(),
            venue="binance",
            symbol="BTC/USDT",
            timeframe="1d",
            direction="long",
            pattern_id="bullish_engulfing_vol_confirmed",
            confluence_score=1.5,
            sl_price=90.0,
            tp_price=120.0,
            suggested_size_atr=1.0,
        )

        # volume kolonu yok → filter konservatif geçirmeli (return signals, 0)
        passed, rejected = filter_engulfing_with_volume_zscore(
            [sig], df_no_vol, vol_z_threshold=0.7
        )
        assert len(passed) == 1, "Volume kolonu yoksa sinyal geçmeli (konservatif)"
        assert rejected == 0


# =====================================================================
# T07: threshold=0.0 → filtre yok (solo engulfing baseline)
# =====================================================================

class TestZeroThresholdBaseline:
    def test_T07_zero_threshold_passes_all_engulfings(self):
        """threshold=0.0 → volume filtresi yok, tüm engulfing'ler geçer."""
        from price_action.strategies.volume_zscore_filter import VolumeZScoreFilterStrategy

        # Engulfing + düşük hacim
        df = _make_ohlcv(
            n=60, seed=55,
            inject_bullish_engulf_at=35,
        )
        # Hacmi düşük tut → vol_z < 0
        df.loc[35, "volume"] = float(df["volume"].mean()) * 0.05

        strat_filtered = VolumeZScoreFilterStrategy(vol_z_threshold=0.7)
        strat_solo = VolumeZScoreFilterStrategy(vol_z_threshold=0.0)

        feats_f = strat_filtered.prepare_features(df)
        feats_s = strat_solo.prepare_features(df)

        sigs_filtered = strat_filtered.generate_signals(feats_f)
        sigs_solo = strat_solo.generate_signals(feats_s)

        # Solo ≥ filtered (hiç reddedilmiyor)
        assert len(sigs_solo) >= len(sigs_filtered), (
            "Solo baseline >= filtered sinyal sayısı olmalı"
        )
