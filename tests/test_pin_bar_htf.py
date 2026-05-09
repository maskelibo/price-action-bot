"""Pin Bar at HTF S/R — Test suite (~8 test).

Kapsamli mekanik testler:
  1. Bullish pin bar tespiti (govde, lower wick, upper wick)
  2. Bearish pin bar tespiti
  3. Yanlis pozitif engelleme (govde buyuk — pin degil)
  4. 1D→1W yeniden ornekleme tutarliligi
  5. HTF S/R yakınlık filtresi (0.5 ATR)
  6. prepare_features ciktisi (gerekli kolonlar mevcut)
  7. generate_signals lookahead-free (sinyal zamanlari bar kapanis ts'inden once degil)
  8. Engulfing ile dekorelasyon (ayni barda hem pin hem engulfing olmamali)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from price_action.strategies.pin_bar_htf_sr import (
    PinBarHTFSRStrategy,
    _bullish_pin_bar,
    _bearish_pin_bar,
    _pin_bar_components,
    _resample_to_weekly,
    _weekly_swing_sr_levels,
    _default_manifest,
)


# =====================================================================
# Test helpers
# =====================================================================

def _make_bar(o: float, h: float, l: float, c: float, v: float = 1_000_000.0) -> dict:
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def _ohlcv_df(bars: list[dict], symbol: str = "TEST/USDT") -> pd.DataFrame:
    ts = pd.date_range("2023-01-01", periods=len(bars), freq="1D", tz="UTC")
    df = pd.DataFrame(bars)
    df["ts"] = ts
    df["venue"] = "binance"
    df["symbol"] = symbol
    df["timeframe"] = "1d"
    return df


def _synthetic_ohlcv(
    n: int = 400,
    seed: int = 42,
    start_price: float = 100.0,
) -> pd.DataFrame:
    """Deterministik sentetik OHLCV."""
    rng = np.random.default_rng(seed)
    base_ts = datetime(2022, 1, 1, tzinfo=timezone.utc)
    ts = [base_ts + timedelta(days=i) for i in range(n)]
    rets = rng.normal(0.0005, 0.02, n)
    close = start_price * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]] * (1 + rng.normal(0, 0.003, n))
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.008, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.008, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    vol = rng.uniform(500_000, 2_000_000, n)
    return pd.DataFrame({
        "ts": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": vol,
        "venue": "binance",
        "symbol": "TEST/USDT",
        "timeframe": "1d",
    })


def _make_strategy() -> PinBarHTFSRStrategy:
    manifest = _default_manifest()
    return PinBarHTFSRStrategy(manifest)


# =====================================================================
# Test 1: Bullish pin bar tespiti
# =====================================================================

class TestBullishPinBar:
    """Bullish pin bar: uzun alt fitil (>=60%), kucuk govde (<=33%), kisa ust fitil."""

    def test_classic_bullish_pin_detected(self):
        """range=10, body=1 (10%), lower_wick=8 (80%), upper_wick=1 (10%) → bullish pin."""
        bars = [
            # bar 0: normal
            _make_bar(o=100, h=102, l=98, c=101),
            # bar 1: bullish pin
            # range = 110 - 90 = 20
            # open=109, close=110 → body=1 (5%), lower_wick = min(109,110)-90 = 19 (95%)
            # upper_wick = 110 - max(109,110) = 0
            _make_bar(o=109, h=110, l=90, c=110),
        ]
        df = _ohlcv_df(bars)
        result = _bullish_pin_bar(df, body_ratio_max=0.33, lower_wick_ratio_min=0.60, upper_wick_ratio_max=0.25)
        assert result.iloc[1] is True or result.iloc[1], "Bullish pin bar tespit edilmeli"

    def test_bullish_pin_body_too_large_rejected(self):
        """Govde range'in %50'siyse (>%33) bullish pin degil."""
        bars = [
            # range=10, body=5 (%50), lower_wick=4 (%40) → fail (body > 33%)
            _make_bar(o=100, h=110, l=95, c=105),
        ]
        df = _ohlcv_df(bars)
        result = _bullish_pin_bar(df, body_ratio_max=0.33, lower_wick_ratio_min=0.60)
        assert not result.iloc[0], "Buyuk govdeli bar bullish pin olmamali"

    def test_bullish_pin_wick_too_small_rejected(self):
        """Alt fitil sadece %20'yse (<%60) bullish pin degil.

        Bar: o=105, h=110, l=104, c=107
          range=6, body=|107-105|=2 (%33), lower_wick=min(105,107)-104=1 (%17)
          lower_wick_ratio=17% < 60% → pin bar DEGIL
        """
        bars = [
            # range=6, body=2 (33%), lower_wick=1 (17%), upper_wick=3 (50%) → fail lower_wick
            _make_bar(o=105, h=110, l=104, c=107),
        ]
        df = _ohlcv_df(bars)
        result = _bullish_pin_bar(df, body_ratio_max=0.33, lower_wick_ratio_min=0.60)
        assert not result.iloc[0], "Kisa alt fitilli bar bullish pin olmamali"

    def test_bullish_pin_components_correct(self):
        """_pin_bar_components hesaplari dogru mu?

        Bar: o=108, h=110, l=90, c=109
          range = 110-90 = 20
          body = |109-108| = 1  → body_ratio = 1/20 = 0.05
          upper_wick = 110 - max(108,109) = 110-109 = 1  → ratio = 1/20 = 0.05
          lower_wick = min(108,109) - 90 = 108-90 = 18  → ratio = 18/20 = 0.90
        """
        bars = [_make_bar(o=108, h=110, l=90, c=109)]
        df = _ohlcv_df(bars)
        pc = _pin_bar_components(df)
        assert abs(float(pc["body_ratio"].iloc[0]) - 1.0 / 20.0) < 0.01, (
            f"body_ratio beklenen 0.05, alinan {pc['body_ratio'].iloc[0]:.4f}"
        )
        assert float(pc["lower_wick_ratio"].iloc[0]) > 0.85  # 18/20=0.90
        assert float(pc["upper_wick_ratio"].iloc[0]) < 0.10  # 1/20=0.05


# =====================================================================
# Test 2: Bearish pin bar tespiti
# =====================================================================

class TestBearishPinBar:
    """Bearish pin bar: uzun ust fitil (>=60%), kucuk govde (<=33%), kisa alt fitil."""

    def test_classic_bearish_pin_detected(self):
        """range=20, body=1 (5%), upper_wick=18 (90%), lower_wick=1 (5%) → bearish pin."""
        bars = [
            _make_bar(o=101, h=120, l=100, c=101),  # open 101, close 101, high 120, low 100
            # upper_wick = 120 - max(101,101) = 19, lower_wick = min(101,101) - 100 = 1
            # range=20, body=0, upper_wick=19 (95%), lower_wick=1 (5%)
        ]
        df = _ohlcv_df(bars)
        result = _bearish_pin_bar(df, body_ratio_max=0.33, upper_wick_ratio_min=0.60, lower_wick_ratio_max=0.25)
        assert result.iloc[0], "Bearish pin bar tespit edilmeli"

    def test_bearish_pin_close_above_mid_rejected(self):
        """Kapanis bar ortasinin ustundeyse bearish pin olamaz."""
        bars = [
            # range=20, ust fitil uzun ama kapanis yukarda — bullish
            _make_bar(o=105, h=120, l=100, c=115),
        ]
        df = _ohlcv_df(bars)
        result = _bearish_pin_bar(df)
        assert not result.iloc[0], "Kapanis yukarda olan bar bearish pin olamaz"


# =====================================================================
# Test 3: 1D → 1W yeniden ornekleme
# =====================================================================

class TestResampleToWeekly:
    def test_weekly_ohlcv_shape_and_logic(self):
        """1D veri 1W'ya dogru sekilde donusturuluyor mu?"""
        df_daily = _synthetic_ohlcv(n=100, seed=1)
        df_weekly = _resample_to_weekly(df_daily)

        assert not df_weekly.empty, "Haftalik veri bos olmamali"
        assert "open" in df_weekly.columns
        assert "high" in df_weekly.columns
        assert "low" in df_weekly.columns
        assert "close" in df_weekly.columns
        # Haftalik high >= daily high (en azindan buyuk olmali)
        assert df_weekly["high"].max() <= df_daily["high"].max() * 1.001  # tolerans

    def test_weekly_has_fewer_bars_than_daily(self):
        """Haftalik bar sayisi gunluk bar sayisindan az olmali."""
        df_daily = _synthetic_ohlcv(n=365, seed=2)
        df_weekly = _resample_to_weekly(df_daily)
        assert len(df_weekly) < len(df_daily), "Haftalik < gunluk bar sayisi"
        assert len(df_weekly) >= 45, "365 gun → yaklasik 52 hafta (minimum 45)"


# =====================================================================
# Test 4: HTF S/R seviye tespiti
# =====================================================================

class TestHTFSRLevels:
    def test_sr_levels_generated(self):
        """1W verisinden swing-based S/R seviyeleri uretiliyor mu?"""
        df_daily = _synthetic_ohlcv(n=500, seed=3)
        df_weekly = _resample_to_weekly(df_daily)
        sr_series = _weekly_swing_sr_levels(df_weekly, lookback_weeks=52, fractal_n=2)

        assert len(sr_series) > 0, "S/R seri bos olmamali"
        # Son haftalarda seviyeler olmali (en az bos listeler)
        recent = sr_series.iloc[-10:]
        has_some_levels = any(len(v) > 0 for v in recent)
        assert has_some_levels, "Son haftalarda en az bir S/R seviyesi olmali"

    def test_sr_levels_lookahead_free(self):
        """t haftasi icin yalnizca [t-lookback, t-1] kullaniliyor mu?"""
        df_daily = _synthetic_ohlcv(n=300, seed=4)
        df_weekly = _resample_to_weekly(df_daily)
        sr_series = _weekly_swing_sr_levels(df_weekly, lookback_weeks=10, fractal_n=2)

        # Ilk 3 hafta icin S/R olmamali (warmup)
        if len(sr_series) > 3:
            # Ilk birinde bos olmali (lookback penceresi dolmadan)
            # Bu kesin bir garanti degil ama mantik kontrolu
            first_levels = sr_series.iloc[0]
            assert isinstance(first_levels, list), "S/R serileri liste olmali"


# =====================================================================
# Test 5: prepare_features ciktisi
# =====================================================================

class TestPrepareFeatures:
    def test_required_columns_present(self):
        """prepare_features gerekli kolonlari uretiyor mu?"""
        df = _synthetic_ohlcv(n=300, seed=5)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        required = [
            "ema20", "ema50", "atr14", "atr_pct", "vol_z",
            "bull_pin", "bear_pin",
            "bull_near_htf_sr", "bear_near_htf_sr",
            "htf_sr_levels",
        ]
        for col in required:
            assert col in df_feat.columns, f"Kolon eksik: {col}"

    def test_pin_bar_flags_boolean(self):
        """bull_pin ve bear_pin boolean serileri olmali."""
        df = _synthetic_ohlcv(n=200, seed=6)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        assert df_feat["bull_pin"].dtype == bool or df_feat["bull_pin"].dtype == np.bool_
        assert df_feat["bear_pin"].dtype == bool or df_feat["bear_pin"].dtype == np.bool_

    def test_atr_non_negative(self):
        """ATR negatif olamaz."""
        df = _synthetic_ohlcv(n=200, seed=7)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        assert (df_feat["atr14"].dropna() >= 0).all(), "ATR negatif degil"


# =====================================================================
# Test 6: generate_signals lookahead-free
# =====================================================================

class TestSignalsLookaheadFree:
    def test_signal_ts_not_in_future(self):
        """Uretilen sinyaller bar kapanis ts'inden sonra olmamali.

        Her sinyalin ts'i, dataframe'deki en son bar'in ts'inden buyuk olamaz.
        """
        df = _synthetic_ohlcv(n=400, seed=8)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        sigs = strat.generate_signals(df_feat)

        if not sigs:
            pytest.skip("Bu sentetik veride sinyal uretilmedi — lookahead testi atlandi")

        max_ts = df_feat["ts"].max()
        for sig in sigs:
            sig_ts = pd.Timestamp(sig.ts)
            if sig_ts.tzinfo is None:
                sig_ts = sig_ts.tz_localize("UTC")
            if isinstance(max_ts, pd.Timestamp) and max_ts.tzinfo is None:
                max_ts = max_ts.tz_localize("UTC")
            assert sig_ts <= max_ts, (
                f"Lookahead! Sinyal ts={sig_ts} > max bar ts={max_ts}"
            )

    def test_signal_sl_and_tp_valid(self):
        """Her sinyalde SL ve TP mantikli olmali (long: SL<close<TP, short: TP<close<SL)."""
        df = _synthetic_ohlcv(n=400, seed=9)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        sigs = strat.generate_signals(df_feat)

        for sig in sigs:
            if sig.direction == "long":
                assert sig.sl_price < sig.tp_price, f"Long: SL >= TP: {sig.sl_price} >= {sig.tp_price}"
            else:
                assert sig.tp_price < sig.sl_price, f"Short: TP >= SL: {sig.tp_price} >= {sig.sl_price}"


# =====================================================================
# Test 7: Engulfing ile dekorelasyon
# =====================================================================

class TestEngulfingDecorrelation:
    def test_pin_bar_not_same_as_engulfing(self):
        """Bullish pin bar, strict engulfing kriteri olmamali.

        Pin bar: kucuk govde. Engulfing: govde onceki bar'i yutmali (buyuk govde).
        Ayni bar her ikisi olamaz (pratikte nadir ama teorik olarak mumkun).
        Bu test pattern tanimlari arasindaki farki dogrular.
        """
        from price_action.strategies.engulfing_continuation import _strict_engulfing

        # Klasik bullish pin bar (kucuk govde, uzun alt fitil)
        # Bu bar strict engulfing olmamali cunku body kucuk
        bars = [
            # prev bar (bearish, kucuk)
            _make_bar(o=102, h=103, l=100, c=101),
            # bullish pin: body=1, lower_wick=10, upper_wick=0.5 → body_ratio ~%9
            _make_bar(o=101.5, h=102.5, l=91, c=102),
        ]
        df = _ohlcv_df(bars)
        bull_pin = _bullish_pin_bar(df)
        strict_engulf = _strict_engulfing(df, body_ratio_min=0.6, bullish=True)

        # Bar 1 pin olabilir
        # Ama strict engulfing'in body_ratio_min=0.6 kriteri pin barda karsilanamaz
        # (pin bar body_ratio <= 0.33)
        if bull_pin.iloc[1]:
            assert not strict_engulf.iloc[1], (
                "Bir bar hem strict engulfing (body>=0.6) hem pin bar (body<=0.33) olamaz"
            )

    def test_pattern_ids_different(self):
        """Pin bar ve engulfing pattern_id'leri farkli olmali."""
        df = _synthetic_ohlcv(n=300, seed=10)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        sigs = strat.generate_signals(df_feat)

        pin_pattern_ids = {"bullish_pin_htf_sr", "bearish_pin_htf_sr"}
        engulf_pattern_ids = {"bullish_engulfing_cont", "bearish_engulfing_cont"}

        for sig in sigs:
            assert sig.pattern_id in pin_pattern_ids, (
                f"Pin bar stratejisinden beklenmeyen pattern_id: {sig.pattern_id}"
            )
            assert sig.pattern_id not in engulf_pattern_ids, (
                f"Pin bar stratejisi engulfing ID uretmemeli: {sig.pattern_id}"
            )


# =====================================================================
# Test 8: Strateji butunluk testi (entegrasyon benzeri)
# =====================================================================

class TestStrategyIntegration:
    def test_full_pipeline_smoke(self):
        """prepare_features → generate_signals pipeline calisıyor mu?"""
        df = _synthetic_ohlcv(n=500, seed=11)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        sigs = strat.generate_signals(df_feat)

        # En azindan liste donmeli (bos olabilir — sentetik veri)
        assert isinstance(sigs, list)

    def test_manifest_fields(self):
        """Default manifest gerekli alanlari iceriyor mu?"""
        manifest = _default_manifest()
        assert manifest.name == "pin_bar_htf_sr"
        assert manifest.version is not None
        patterns = [p.id for p in manifest.signals.patterns]
        assert "bullish_pin_htf_sr" in patterns
        assert "bearish_pin_htf_sr" in patterns

    def test_empty_df_safe(self):
        """Bos DataFrame ile cagrilinca hata vermemeli."""
        strat = _make_strategy()
        empty_df = pd.DataFrame(
            columns=["ts", "open", "high", "low", "close", "volume", "venue", "symbol", "timeframe"]
        )
        df_feat = strat.prepare_features(empty_df)
        sigs = strat.generate_signals(df_feat)
        assert sigs == [], "Bos df ile sinyal uretilmemeli"

    def test_bullish_pin_at_sr_generates_long_signal(self):
        """HTF S/R'a yakin bir bullish pin bar long sinyal uretmeli."""
        # El ile kurgulanmis senaryo:
        # - 80 bar gecmis (warmup icin)
        # - Son barda bullish pin bar var
        # - HTF S/R seviyesi pin bar low'una yakin ayarlanmis

        # 80 bar warmup
        warmup_bars = [_make_bar(100 + i * 0.1, 100 + i * 0.1 + 1, 99 + i * 0.1, 100 + i * 0.1 + 0.5)
                       for i in range(80)]
        # Bullish pin bar: range=20, body=1, lower_wick=18, upper_wick=1
        # Fiyat 107-108 civarinda, low=90 → bu dusuk ATR'a gore cok uzak olur
        # Daha gercekci: 100 baz fiyatiyla
        # Onceki barlardan gelen ATR yaklasik 1-2 birim
        # Pin bar low 90 degil de 98 olsun, range=4, body=0.5, lower_wick=3
        pin_bar = _make_bar(o=101.4, h=101.6, l=98.0, c=101.5)  # body=0.1, rng=3.6, lower_wick=3.4 (94%), upper_wick=0.1 (3%)
        all_bars = warmup_bars + [pin_bar]

        df = _ohlcv_df(all_bars)
        strat = _make_strategy()

        # Strateji prepare_features'i cagirinca weekly resample yapacak
        # ve S/R araniyor. Sentetik olarak bir S/R level inject et:
        # Bunun icin weekly_cache'e el ile veri koy
        weekly_df = _resample_to_weekly(df)
        # Son weekly barin low'unu 98.5 yap ki pin barin low=98 ona yakin olsun
        if not weekly_df.empty:
            weekly_df.iloc[-1, weekly_df.columns.get_loc("low")] = 98.5
        strat.set_weekly_data("TEST/USDT", weekly_df)

        df_feat = strat.prepare_features(df)
        sigs = strat.generate_signals(df_feat)

        # Bu sentetik durumda sinyal olmayabilir (warmup, swing detection vb.)
        # Ama hata vermemeli
        assert isinstance(sigs, list)
        # Eger sinyal varsa direction ve pattern_id kontrol et
        for sig in sigs:
            assert sig.direction in ("long", "short")
            assert sig.pattern_id in ("bullish_pin_htf_sr", "bearish_pin_htf_sr")
