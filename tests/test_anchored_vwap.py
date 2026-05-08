"""Unit testler -- AnchoredVWAPReversalStrategy.

Test senaryolari:
  1. _anchored_vwap formul dogrulugu
  2. _volume_profile_poc bucket hesabi
  3. _rolling_avwap_from_swing lookahead-free
  4. _rsi hesabi
  5. prepare_features gerekli kolonlari eklemeli
  6. AVWAP cross-up sinyal uretimi
  7. AVWAP cross-down (short) sinyal uretimi
  8. POC toleransi disinda sinyal olmamali
  9. 200-EMA filtresi
 10. Sinyal schema dogrulugu + smoke testi
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.anchored_vwap_reversal import (
    AnchoredVWAPReversalStrategy,
    _anchored_vwap,
    _volume_profile_poc,
    _rolling_avwap_from_swing,
    _rsi,
    _default_manifest,
)


# ---------------------------------------------------------------------------
# Yardimci fabrika
# ---------------------------------------------------------------------------

def _base_ts(n: int) -> list[datetime]:
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def _make_df(n: int, base_price: float = 100.0, volume: float = 1_000_000.0) -> pd.DataFrame:
    """Sabit fiyat serisi icin minimal OHLCV DataFrame."""
    ts = _base_ts(n)
    return pd.DataFrame({
        "ts": ts,
        "open": np.full(n, base_price - 1.0),
        "high": np.full(n, base_price + 2.0),
        "low": np.full(n, base_price - 1.5),
        "close": np.full(n, base_price),
        "volume": np.full(n, volume),
        "venue": "binance",
        "symbol": "TEST/USDT",
        "timeframe": "1d",
    })


def _synthetic_trend_df(
    n: int = 120,
    seed: int = 42,
    uptrend: bool = True,
) -> pd.DataFrame:
    """Gercekci uptrend/downtrend sentetik OHLCV."""
    rng = np.random.default_rng(seed)
    drift = 0.002 if uptrend else -0.002
    rets = rng.normal(drift, 0.015, n)
    close = 100.0 * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(500_000.0, 2_000_000.0, n)
    ts = _base_ts(n)
    return pd.DataFrame({
        "ts": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "venue": "binance",
        "symbol": "TEST/USDT",
        "timeframe": "1d",
    })


def _make_strategy(overrides: dict | None = None) -> AnchoredVWAPReversalStrategy:
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "anchored_vwap_reversal",
        "version": "0.0.1",
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "avwap_long_reversal",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "poc_atr_tolerance": 1.5,
                        "rsi_long_max": 55.0,
                        "avwap_swing_lookback": 30,
                        "poc_lookback": 30,
                    },
                },
                {
                    "id": "avwap_short_reversal",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "poc_atr_tolerance": 1.5,
                        "rsi_short_min": 45.0,
                        "avwap_swing_lookback": 30,
                        "poc_lookback": 30,
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
            },
            "confluence": {"method": "weighted_sum", "min_score": 1.0, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "stop_loss": {"method": "structural_atr", "swing_lookback": 10, "atr_buffer": 1.0},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
        },
    }
    if overrides:
        raw.update(overrides)
    manifest = StrategyManifest.model_validate(raw)
    return AnchoredVWAPReversalStrategy(manifest)


# ---------------------------------------------------------------------------
# 1. _anchored_vwap formul dogrulugu
# ---------------------------------------------------------------------------

class TestAnchoredVWAP:
    def test_avwap_formula_correctness(self):
        """AVWAP = sum(typical * vol) / sum(vol) -- el hesabiyla dogrula."""
        n = 5
        df = pd.DataFrame({
            "ts": _base_ts(n),
            "open": [10.0] * n,
            "high": [12.0, 14.0, 11.0, 13.0, 15.0],
            "low": [8.0, 9.0, 7.0, 10.0, 11.0],
            "close": [11.0, 13.0, 10.0, 12.0, 14.0],
            "volume": [1000.0, 2000.0, 1500.0, 3000.0, 500.0],
        })
        anchor = 0
        avwap = _anchored_vwap(df, anchor_idx=anchor)

        # El hesabi: t=2 icin anchor=0..2
        tp = [(12 + 8 + 11) / 3, (14 + 9 + 13) / 3, (11 + 7 + 10) / 3]
        vols = [1000.0, 2000.0, 1500.0]
        expected_t2 = sum(t * v for t, v in zip(tp, vols)) / sum(vols)
        assert abs(avwap.iloc[2] - expected_t2) < 0.001, (
            f"AVWAP formul hatasi: got {avwap.iloc[2]:.4f}, expected {expected_t2:.4f}"
        )

    def test_avwap_anchor_0_first_bar(self):
        """Anchor=0 durumunda ilk bar'da AVWAP tipik fiyata esit olmali."""
        df = _make_df(5, base_price=100.0)
        avwap = _anchored_vwap(df, anchor_idx=0)
        typical_0 = (float(df["high"].iloc[0]) + float(df["low"].iloc[0]) + float(df["close"].iloc[0])) / 3.0
        assert abs(avwap.iloc[0] - typical_0) < 0.001

    def test_avwap_before_anchor_is_nan(self):
        """Anchor oncesi barlar NaN olmali (lookahead yok)."""
        df = _make_df(10, base_price=100.0)
        avwap = _anchored_vwap(df, anchor_idx=5)
        assert all(np.isnan(avwap.iloc[i]) for i in range(5)), "Anchor oncesi NaN olmali"
        assert not np.isnan(avwap.iloc[5]), "Anchor barinda NaN olmamali"

    def test_avwap_invalid_anchor_returns_nan(self):
        """Gecersiz anchor_idx (negatif veya >= len) NaN serisi donemeli."""
        df = _make_df(5)
        avwap_neg = _anchored_vwap(df, anchor_idx=-1)
        avwap_over = _anchored_vwap(df, anchor_idx=10)
        assert avwap_neg.isna().all()
        assert avwap_over.isna().all()

    def test_avwap_monotonic_volume_weight(self):
        """Yuksek hacimli bar'in agirlandirma etkisini kontrol et.

        Eger 2. bar'da cok yuksek hacim varsa, AVWAP 2. bar'in tipik fiyatina
        dogru cekili olmali.
        """
        df = pd.DataFrame({
            "ts": _base_ts(3),
            "open": [100.0, 200.0, 150.0],
            "high": [105.0, 210.0, 155.0],
            "low": [95.0, 190.0, 145.0],
            "close": [102.0, 205.0, 152.0],
            "volume": [100.0, 100_000.0, 100.0],  # 2. bar dominant
        })
        avwap = _anchored_vwap(df, anchor_idx=0)
        tp2 = (210 + 190 + 205) / 3.0  # 2. bar'in tipik fiyati = 201.67
        # t=2'deki AVWAP, yuksek hacim nedeniyle tp1'e cok yakin olmali
        assert abs(avwap.iloc[2] - tp2) < 5.0, (
            f"Agirlikli ortalama 2. bar'a yakin olmali, got {avwap.iloc[2]:.2f}"
        )


# ---------------------------------------------------------------------------
# 2. _volume_profile_poc bucket hesabi
# ---------------------------------------------------------------------------

class TestVolumeProfilePOC:
    def test_poc_is_highest_volume_price(self):
        """POC, en fazla hacmin biriktigui fiyat bolgesi olmali.

        Dusuk fiyatli barlar cok volume, yuksek fiyatli barlar az volume =>
        POC dusuk fiyat bolgelerinde olmali.
        """
        n = 40
        lows = np.full(n, 95.0)
        highs = np.full(n, 105.0)
        closes = np.full(n, 100.0)
        opens = np.full(n, 100.0)
        # Ilk 30 bar: volume 100k ve low=95..97 => dusuk fiyat dominant
        vols = np.full(n, 1000.0)
        vols[:30] = 100_000.0
        # Dusuk fiyatli barlar icin range 95-97
        lows[:30] = 95.0
        highs[:30] = 97.0
        closes[:30] = 96.0
        opens[:30] = 96.0
        # Son 10 bar: yuksek fiyat, dusuk hacim
        lows[30:] = 103.0
        highs[30:] = 107.0
        closes[30:] = 105.0
        opens[30:] = 105.0

        df = pd.DataFrame({
            "ts": _base_ts(n),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols,
        })
        poc = _volume_profile_poc(df, lookback=30, n_buckets=20)
        # t=35 (lookback=30 => bar 5..34) POC dusuk fiyat bolgelerinde olmali
        poc_35 = poc.iloc[35]
        assert not np.isnan(poc_35), "POC NaN olmamali"
        assert poc_35 < 100.0, f"POC dusuk fiyat bolgelerinde olmali, got {poc_35:.2f}"

    def test_poc_nan_before_lookback(self):
        """lookback bari dolmadan POC NaN olmali."""
        df = _make_df(10)
        poc = _volume_profile_poc(df, lookback=15, n_buckets=10)
        # lookback=15, df uzunlugu=10 => tumune NaN
        assert poc.isna().all(), "lookback buyukse tumune NaN olmali"

    def test_poc_no_lookahead(self):
        """t aninda POC sadece [t-lookback..t-1] kullanmali.

        t+1 verisi degistirildiginde t'nin POC'u degismemeli.
        """
        n = 60
        df1 = _synthetic_trend_df(n=n, seed=10)
        df2 = df1.copy()
        # t+1'den sonra volume'u 100x artir
        df2.loc[50:, "volume"] = 100_000_000.0

        poc1 = _volume_profile_poc(df1, lookback=30, n_buckets=20)
        poc2 = _volume_profile_poc(df2, lookback=30, n_buckets=20)

        # t=45 icin POC lookback penceresi [15..44] -- 50'den once, degismemeli
        assert abs(poc1.iloc[45] - poc2.iloc[45]) < 1.0, (
            "Gelecek bar degisikliginin t=45 POC'unu etkilememesi gerekir (lookahead yok)"
        )


# ---------------------------------------------------------------------------
# 3. _rolling_avwap_from_swing lookahead-free
# ---------------------------------------------------------------------------

class TestRollingAVWAPFromSwing:
    def test_rolling_avwap_returns_series(self):
        """Rolling AVWAP serisi dogru uzunlukta ve float tipinde olmali."""
        df = _synthetic_trend_df(n=80, seed=5)
        from price_action.strategies.classic_pa import _fractal_swings
        sh, sl = _fractal_swings(df, n=2)
        df["swing_high"] = sh
        df["swing_low"] = sl
        avwap_s = _rolling_avwap_from_swing(df, swing_col="swing_low", lookback=30)
        assert len(avwap_s) == len(df)
        assert avwap_s.dtype == float

    def test_rolling_avwap_nan_before_first_swing(self):
        """Ilk swing'ten once AVWAP NaN olmali."""
        n = 40
        df = _make_df(n)
        # Swing_low kolonu: sadece bar 20'de bir swing var
        df["swing_low"] = np.nan
        df.loc[20, "swing_low"] = 98.5
        avwap_s = _rolling_avwap_from_swing(df, swing_col="swing_low", lookback=30)
        # Bar 20 oncesinde swing yok => NaN
        assert avwap_s.iloc[15:20].isna().all(), "Swing oncesinde AVWAP NaN olmali"


# ---------------------------------------------------------------------------
# 4. RSI hesabi
# ---------------------------------------------------------------------------

class TestRSI:
    def test_rsi_bounds(self):
        """RSI 0-100 arasinda olmali."""
        rng = np.random.default_rng(99)
        close = pd.Series(100.0 * np.exp(np.cumsum(rng.normal(0.001, 0.02, 100))))
        rsi = _rsi(close, period=14)
        assert (rsi >= 0).all() and (rsi <= 100).all(), "RSI 0-100 arasinda olmali"

    def test_rsi_neutral_constant_close(self):
        """Sabit fiyatta RSI 50 olmali (diff=0)."""
        close = pd.Series(np.full(50, 100.0))
        rsi = _rsi(close, period=14)
        # Sabit fiyatta fillna(50) ile 50 donmeli
        assert abs(float(rsi.iloc[-1]) - 50.0) < 1.0


# ---------------------------------------------------------------------------
# 5. prepare_features kolonlari
# ---------------------------------------------------------------------------

class TestPrepareFeatures:
    def test_prepare_features_required_columns(self):
        """prepare_features gerekli kolonlari df'e eklemeli."""
        strat = _make_strategy()
        df = _synthetic_trend_df(n=120, seed=7)
        df_feat = strat.prepare_features(df)
        required = [
            "ema200", "atr14", "atr_pct", "rsi14",
            "swing_high", "swing_low",
            "avwap_long", "avwap_short",
            "poc",
            "avwap_long_cross_up", "avwap_short_cross_down",
            "struct_sl_long", "struct_sl_short",
        ]
        for col in required:
            assert col in df_feat.columns, f"Eksik kolon: {col}"

    def test_empty_df_returns_empty(self):
        strat = _make_strategy()
        empty = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        result = strat.prepare_features(empty)
        assert result.empty


# ---------------------------------------------------------------------------
# 6. AVWAP cross-up sinyal uretimi (long)
# ---------------------------------------------------------------------------

class TestSignalGenerationLong:
    def test_long_signal_on_forced_crossup(self):
        """Zorlanmis cross_up + poc yakini + 200-EMA yukari => long sinyal olmali."""
        df = _synthetic_trend_df(n=120, seed=42, uptrend=True)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        # Bar 80'de sinyali zorla:
        # 1) ema200 altinda olmali -- False kil (close > ema200)
        df_feat["ema200"] = df_feat["close"] * 0.5  # close her zaman > ema200
        # 2) avwap_long_cross_up True
        df_feat.loc[80, "avwap_long_cross_up"] = True
        df_feat.loc[80, "avwap_long"] = float(df_feat.loc[80, "close"]) * 0.99
        # 3) POC yakin: close ile ayni
        df_feat.loc[80, "poc"] = float(df_feat.loc[80, "close"])
        # 4) RSI < 55
        df_feat.loc[80, "rsi14"] = 48.0
        # 5) ATR min pass
        df_feat.loc[80, "atr_pct"] = 0.02

        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) >= 1, "Zorlanmis kosullarda en az 1 long sinyal olmali"
        sig = long_sigs[0]
        assert sig.pattern_id == "avwap_long_reversal"
        assert sig.sl_price < sig.tp_price
        assert sig.tp_price > float(df_feat.iloc[sig.ts.timestamp() > 0 and 80 or 80]["close"])


# ---------------------------------------------------------------------------
# 7. AVWAP cross-down sinyal uretimi (short)
# ---------------------------------------------------------------------------

class TestSignalGenerationShort:
    def test_short_signal_on_forced_crossdown(self):
        """Zorlanmis cross_down + 200-EMA asagi => short sinyal olmali."""
        df = _synthetic_trend_df(n=120, seed=11, uptrend=False)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        df_feat["ema200"] = df_feat["close"] * 2.0  # close her zaman < ema200
        df_feat.loc[80, "avwap_short_cross_down"] = True
        df_feat.loc[80, "avwap_short"] = float(df_feat.loc[80, "close"]) * 1.01
        df_feat.loc[80, "poc"] = float(df_feat.loc[80, "close"])
        df_feat.loc[80, "rsi14"] = 58.0
        df_feat.loc[80, "atr_pct"] = 0.02

        signals = strat.generate_signals(df_feat)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) >= 1, "Zorlanmis short kosullarda sinyal olmali"
        sig = short_sigs[0]
        assert sig.sl_price > float(df_feat.loc[80, "close"])
        assert sig.tp_price < float(df_feat.loc[80, "close"])


# ---------------------------------------------------------------------------
# 8. POC toleransi disinda sinyal olmamali
# ---------------------------------------------------------------------------

class TestPOCFilter:
    def test_no_signal_when_poc_far(self):
        """POC uzaksa (> poc_atr_tolerance * ATR) sinyal olmamali."""
        df = _synthetic_trend_df(n=120, seed=33)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        df_feat["ema200"] = df_feat["close"] * 0.5
        df_feat.loc[80, "avwap_long_cross_up"] = True
        df_feat.loc[80, "avwap_long"] = float(df_feat.loc[80, "close"]) * 0.99
        # POC cok uzakta: 20 ATR mesafede
        atr_val = float(df_feat.loc[80, "atr14"])
        df_feat.loc[80, "poc"] = float(df_feat.loc[80, "close"]) + 20.0 * atr_val
        df_feat.loc[80, "rsi14"] = 48.0

        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        # Bar 80'de POC cok uzak => sinyal olmamali
        sigs_at_80 = [
            s for s in long_sigs
            if abs((s.ts - df_feat.loc[80, "ts"].to_pydatetime()).total_seconds()) < 86400
        ]
        assert len(sigs_at_80) == 0, "POC toleransi disinda sinyal uretilmemeli"


# ---------------------------------------------------------------------------
# 9. 200-EMA filtresi
# ---------------------------------------------------------------------------

class TestEMA200Filter:
    def test_no_long_when_below_ema200(self):
        """Close < 200-EMA => long sinyal olmamali (trend_filter required=True ile)."""
        from price_action.strategies.base import StrategyManifest
        raw = {
            "name": "anchored_vwap_reversal",
            "version": "0.0.1",
            "trend_filter": {"type": "ema", "period": 200, "required": True},
            "signals": {
                "patterns": [
                    {"id": "avwap_long_reversal", "enabled": True, "weight": 1.5,
                     "params": {"poc_atr_tolerance": 99.0, "rsi_long_max": 99.0,
                                "avwap_swing_lookback": 30, "poc_lookback": 30}},
                    {"id": "avwap_short_reversal", "enabled": True, "weight": 1.5,
                     "params": {"poc_atr_tolerance": 99.0, "rsi_short_min": 1.0,
                                "avwap_swing_lookback": 30, "poc_lookback": 30}},
                ],
                "structure": {"swing": {"fractal_n": 2}, "support_resistance": {
                    "lookback_bars": 50, "cluster_atr_multiplier": 0.5,
                    "min_touches": 2, "max_age_bars": 50,
                }, "require_proximity_to_sr_atr": 0.0},
                "filters": {"atr_min_pct": 0.0, "volume_zscore_min": 0.0},
                "confluence": {"method": "weighted_sum", "min_score": 1.0, "bonus_if_at_sr": 0.0},
            },
            "risk": {
                "stop_loss": {"method": "structural_atr", "swing_lookback": 10, "atr_buffer": 1.0},
                "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            },
        }
        manifest = StrategyManifest.model_validate(raw)
        strat = AnchoredVWAPReversalStrategy(manifest)
        df = _synthetic_trend_df(n=120, seed=55)
        df_feat = strat.prepare_features(df)

        # Tum barlarda close < ema200 yap
        df_feat["ema200"] = df_feat["close"] * 2.0
        # Cross-up zorla
        df_feat.loc[80, "avwap_long_cross_up"] = True
        df_feat.loc[80, "avwap_long"] = float(df_feat.loc[80, "close"]) * 0.99
        df_feat.loc[80, "poc"] = float(df_feat.loc[80, "close"])
        df_feat.loc[80, "rsi14"] = 40.0

        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) == 0, "200-EMA altinda long sinyal olmamali"


# ---------------------------------------------------------------------------
# 10. Sinyal schema + smoke testi
# ---------------------------------------------------------------------------

class TestSignalSchema:
    def test_signal_schema_valid(self):
        """Uretilen sinyaller Signal schema'sini gecmeli."""
        from price_action.contracts import Signal
        df = _synthetic_trend_df(n=120, seed=77)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        df_feat["ema200"] = df_feat["close"] * 0.5
        df_feat.loc[80, "avwap_long_cross_up"] = True
        df_feat.loc[80, "avwap_long"] = float(df_feat.loc[80, "close"]) * 0.99
        df_feat.loc[80, "poc"] = float(df_feat.loc[80, "close"])
        df_feat.loc[80, "rsi14"] = 45.0
        df_feat.loc[80, "atr_pct"] = 0.02

        signals = strat.generate_signals(df_feat)
        for sig in signals:
            assert isinstance(sig, Signal)
            assert sig.venue == "binance"
            assert sig.timeframe == "1d"
            assert sig.direction in {"long", "short"}
            assert sig.sl_price > 0
            assert sig.tp_price > 0
            assert sig.fingerprint()

    def test_empty_df_no_signals(self):
        """Bos df => bos sinyal listesi."""
        strat = _make_strategy()
        empty = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        signals = strat.generate_signals(empty)
        assert signals == []

    def test_smoke_random_data_no_crash(self):
        """Rastgele veri ile exception olmamali."""
        rng = np.random.default_rng(123)
        n = 200
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, n)))
        open_ = np.r_[close[0], close[:-1]]
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
        high = np.maximum.reduce([high, open_, close])
        low = np.minimum.reduce([low, open_, close])
        df = pd.DataFrame({
            "ts": _base_ts(n),
            "open": open_, "high": high, "low": low, "close": close,
            "volume": rng.uniform(5e5, 5e6, n),
            "venue": "binance", "symbol": "SMOKE/USDT", "timeframe": "1d",
        })
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        signals = strat.generate_signals(df_feat)
        assert isinstance(signals, list)

    def test_default_manifest_valid(self):
        """_default_manifest() gecerli StrategyManifest donemeli."""
        m = _default_manifest()
        assert m.name == "anchored_vwap_reversal"
        assert m.trend_filter.period == 200
        assert len(m.signals.patterns) == 2

    def test_avwap_no_lookahead_end_to_end(self):
        """t=80 sinyali t=81..end bilgisine bagimli olmamali.

        Yontem: t=81..end bar'larini NaN yap, t=80'deki sinyal degismemeli.
        """
        df = _synthetic_trend_df(n=120, seed=13)
        strat = _make_strategy()
        df_feat_full = strat.prepare_features(df)

        df_feat_full["ema200"] = df_feat_full["close"] * 0.5
        df_feat_full.loc[80, "avwap_long_cross_up"] = True
        df_feat_full.loc[80, "avwap_long"] = float(df_feat_full.loc[80, "close"]) * 0.99
        df_feat_full.loc[80, "poc"] = float(df_feat_full.loc[80, "close"])
        df_feat_full.loc[80, "rsi14"] = 45.0
        df_feat_full.loc[80, "atr_pct"] = 0.02

        sigs_full = strat.generate_signals(df_feat_full)
        long_full = [s for s in sigs_full if s.direction == "long"]

        df_feat_trunc = df_feat_full.copy()
        df_feat_trunc.loc[81:, "avwap_long_cross_up"] = False
        df_feat_trunc.loc[81:, "avwap_long"] = np.nan
        df_feat_trunc.loc[81:, "poc"] = np.nan

        sigs_trunc = strat.generate_signals(df_feat_trunc)
        long_trunc = [s for s in sigs_trunc if s.direction == "long"]

        ts_full = {s.ts for s in long_full}
        ts_trunc = {s.ts for s in long_trunc}
        assert len(ts_full & ts_trunc) >= 1, (
            "t=81..end sifirlamasi bar t=80'deki sinyali etkilememeli (lookahead yok)"
        )
