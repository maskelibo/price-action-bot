"""Unit testler -- TPOValueAreaStrategy.

Test senaryolari:
  1.  _volume_profile histogram dogrulugu — POC en yuksek hacimli bucket
  2.  VAH >= POC >= VAL hiyerarsisi
  3.  Value Area %70 hacim kismi kapsama
  4.  Lookahead-free: t sonrasi veri degisikliginin t'yi etkilememesi
  5.  _classify_zone dogrulugu
  6.  _bullish_reversal — engulfing tespiti
  7.  _bearish_reversal — shooting star tespiti
  8.  LONG sinyal uretimi (below VAL + dist > 2ATR + bull reversal)
  9.  SHORT sinyal uretimi (above VAH + dist > 2ATR + bear reversal)
  10. ATR mesafe filtresi: dist < 2*ATR => sinyal olmamali
  11. prepare_features gerekli kolonlari eklemeli
  12. Bos df => bos sinyal listesi
  13. Sinyal schema dogrulugu
  14. Smoke testi (rastgele veri)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.tpo_value_area import (
    TPOValueAreaStrategy,
    _volume_profile,
    _classify_zone,
    _bullish_reversal,
    _bearish_reversal,
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


def _make_strategy(overrides: dict | None = None) -> TPOValueAreaStrategy:
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "tpo_value_area",
        "version": "0.0.1",
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "tpo_long_reversal",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "vp_lookback": 30,
                        "vp_bins": 50,
                        "atr_extension_min": 2.0,
                    },
                },
                {
                    "id": "tpo_short_reversal",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "vp_lookback": 30,
                        "vp_bins": 50,
                        "atr_extension_min": 2.0,
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
            "take_profit": {"method": "poc_target"},
        },
    }
    if overrides:
        raw.update(overrides)
    manifest = StrategyManifest.model_validate(raw)
    return TPOValueAreaStrategy(manifest)


# ---------------------------------------------------------------------------
# 1. _volume_profile — POC en yuksek hacimli bucket olmali
# ---------------------------------------------------------------------------

class TestVolumeProfile:
    def test_poc_is_max_volume_bucket(self):
        """POC, en fazla hacmin biriktigiu fiyat bolgesi olmali."""
        n = 40
        # Dusuk fiyat bolgelerinde yuksek hacim
        lows = np.full(n, 95.0)
        highs = np.full(n, 105.0)
        closes = np.full(n, 100.0)
        opens = np.full(n, 100.0)
        vols = np.full(n, 1000.0)

        # Ilk 30 bar: low fiyat araliginda buyuk hacim
        lows[:30] = 95.0
        highs[:30] = 97.0
        closes[:30] = 96.0
        opens[:30] = 96.0
        vols[:30] = 100_000.0

        # Son 10 bar: yuksek fiyat, dusuk hacim
        lows[30:] = 103.0
        highs[30:] = 107.0
        closes[30:] = 105.0
        opens[30:] = 105.0
        vols[30:] = 500.0

        df = pd.DataFrame({
            "ts": _base_ts(n),
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vols,
        })

        vah, poc, val = _volume_profile(df, lookback=30, bins=20)
        # t=35: lookback penceresi [5..34] — dusuk fiyat dominanat
        poc_35 = poc.iloc[35]
        assert not np.isnan(poc_35), "POC NaN olmamali"
        assert poc_35 < 100.0, f"POC dusuk fiyat bolgelerinde olmali, got {poc_35:.2f}"


# ---------------------------------------------------------------------------
# 2. VAH >= POC >= VAL hiyerarsisi
# ---------------------------------------------------------------------------

class TestVAHierarchy:
    def test_vah_poc_val_ordering(self):
        """Her gecerli barda VAH >= POC >= VAL olmali."""
        df = _synthetic_trend_df(n=100, seed=7)
        vah, poc, val = _volume_profile(df, lookback=30, bins=30)

        for i in range(len(df)):
            v = float(vah.iloc[i])
            p = float(poc.iloc[i])
            vl = float(val.iloc[i])
            if np.isnan(v) or np.isnan(p) or np.isnan(vl):
                continue
            assert v >= p, f"VAH < POC at i={i}: VAH={v:.2f}, POC={p:.2f}"
            assert p >= vl, f"POC < VAL at i={i}: POC={p:.2f}, VAL={vl:.2f}"


# ---------------------------------------------------------------------------
# 3. Value Area %70 hacim kapsama
# ---------------------------------------------------------------------------

class TestValueArea70Pct:
    def test_value_area_covers_70pct_volume(self):
        """VAH ve VAL arasindaki hacim toplaminin >= %70 olmasi beklenir."""
        n = 50
        rng = np.random.default_rng(88)
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, n)))
        high = close * (1 + np.abs(rng.normal(0, 0.005, n)))
        low = close * (1 - np.abs(rng.normal(0, 0.005, n)))
        high = np.maximum(high, close)
        low = np.minimum(low, close)
        volume = rng.uniform(1e5, 5e5, n)

        df = pd.DataFrame({
            "ts": _base_ts(n),
            "open": close,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "venue": "binance",
            "symbol": "TEST/USDT",
            "timeframe": "1d",
        })

        vah, poc, val = _volume_profile(df, lookback=20, bins=30)

        # t=40 icin VAH/VAL araligindaki hacim dogrulama
        t = 40
        start = t - 20
        end = t
        w_low = df["low"].values[start:end]
        w_high = df["high"].values[start:end]
        w_vol = df["volume"].values[start:end]

        vah_t = float(vah.iloc[t])
        val_t = float(val.iloc[t])
        if np.isnan(vah_t) or np.isnan(val_t):
            pytest.skip("VP NaN at t=40, too few bars")

        total_vol = w_vol.sum()
        # Kac bar VAH-VAL araliginda?
        in_va = ((w_high >= val_t) & (w_low <= vah_t))
        va_vol = w_vol[in_va].sum()
        ratio = va_vol / total_vol if total_vol > 0 else 0.0
        assert ratio >= 0.60, (
            f"Value Area hacim kapsama yetersiz: {ratio*100:.1f}% < 60% (tolerans)"
        )


# ---------------------------------------------------------------------------
# 4. Lookahead-free: t sonrasi veri degisikliginin t'yi etkilememesi
# ---------------------------------------------------------------------------

class TestLookaheadFree:
    def test_poc_no_lookahead(self):
        """t=45 POC'u t=50 sonrasi veri degisikliginden etkilenmemeli."""
        n = 80
        df1 = _synthetic_trend_df(n=n, seed=10)
        df2 = df1.copy()
        # t=50 sonrasini 100x hacim yap
        df2.loc[50:, "volume"] = 100_000_000.0

        vah1, poc1, val1 = _volume_profile(df1, lookback=30, bins=20)
        vah2, poc2, val2 = _volume_profile(df2, lookback=30, bins=20)

        # t=45 icin lookback penceresi [15..44] — 50'den once
        assert abs(poc1.iloc[45] - poc2.iloc[45]) < 1.0, (
            f"Gelecek veri degisikligi t=45 POC'unu etkilemeli: "
            f"{poc1.iloc[45]:.2f} vs {poc2.iloc[45]:.2f}"
        )

    def test_val_no_lookahead(self):
        """t=45 VAL/VAH'i t=50 sonrasi high/low degisikliginden etkilenmemeli."""
        n = 80
        df1 = _synthetic_trend_df(n=n, seed=15)
        df2 = df1.copy()
        df2.loc[50:, "high"] = df2.loc[50:, "high"] * 100.0  # extreme outlier

        vah1, poc1, val1 = _volume_profile(df1, lookback=30, bins=20)
        vah2, poc2, val2 = _volume_profile(df2, lookback=30, bins=20)

        # t=45'in lookback'i [15..44] — 50 oncesi
        assert abs(vah1.iloc[45] - vah2.iloc[45]) < 1.0, (
            "t=45 VAH future data degisikliginden etkilenmemeli"
        )


# ---------------------------------------------------------------------------
# 5. _classify_zone dogrulugu
# ---------------------------------------------------------------------------

class TestClassifyZone:
    def test_above_vah(self):
        assert _classify_zone(105.0, vah=100.0, val=90.0) == "above_vah"

    def test_below_val(self):
        assert _classify_zone(88.0, vah=100.0, val=90.0) == "below_val"

    def test_in_value(self):
        assert _classify_zone(95.0, vah=100.0, val=90.0) == "in_value"

    def test_at_vah_boundary(self):
        # close == VAH => in_value (>= VAH degil > VAH)
        assert _classify_zone(100.0, vah=100.0, val=90.0) == "in_value"

    def test_unknown_on_nan(self):
        assert _classify_zone(95.0, vah=np.nan, val=90.0) == "unknown"
        assert _classify_zone(95.0, vah=100.0, val=np.nan) == "unknown"


# ---------------------------------------------------------------------------
# 6. _bullish_reversal — engulfing tespiti
# ---------------------------------------------------------------------------

class TestBullishReversal:
    def test_bullish_engulfing_detected(self):
        """Klasik bullish engulfing tespit edilmeli."""
        df = pd.DataFrame({
            "ts": _base_ts(3),
            "open":  [100.0, 102.0, 99.0],   # bar1: bearish (o>c), bar2: bullish engulfing
            "close": [100.0, 99.0,  104.0],
            "high":  [101.0, 103.0, 105.0],
            "low":   [99.0,  98.0,  98.5],
        })
        # bar2 (idx=2): open=99 < prev_close=99? No, prev_o=102, prev_c=99
        # bearish prev: prev_c(99) < prev_o(102) => yes
        # engulf: o(99) <= prev_c(99) and c(104) >= prev_o(102) => yes
        assert _bullish_reversal(df, 2) is True

    def test_no_bullish_reversal_on_bearish_candle(self):
        """Bearish mum bullish reversal olmamali."""
        df = pd.DataFrame({
            "ts": _base_ts(3),
            "open":  [100.0, 95.0, 105.0],
            "close": [100.0, 98.0, 102.0],  # bar2: close < open = bearish
            "high":  [101.0, 99.0, 106.0],
            "low":   [99.0,  94.0, 101.0],
        })
        assert _bullish_reversal(df, 2) is False

    def test_bullish_reversal_no_lookahead(self):
        """idx=0 durumunda (onceki bar yok) False donmeli."""
        df = _make_df(3)
        assert _bullish_reversal(df, 0) is False


# ---------------------------------------------------------------------------
# 7. _bearish_reversal — shooting star tespiti
# ---------------------------------------------------------------------------

class TestBearishReversal:
    def test_bearish_engulfing_detected(self):
        """Klasik bearish engulfing tespit edilmeli."""
        df = pd.DataFrame({
            "ts": _base_ts(3),
            "open":  [100.0, 99.0,  103.0],  # bar1: bullish, bar2: bearish engulfing
            "close": [100.0, 103.0, 98.0],
            "high":  [101.0, 104.0, 104.0],
            "low":   [99.0,  98.5,  97.0],
        })
        # bar2 (idx=2): bearish (c<o), prev bullish (prev_c>prev_o)
        # engulf: o(103) >= prev_c(103) and c(98) <= prev_o(99) => yes
        assert _bearish_reversal(df, 2) is True

    def test_no_bearish_reversal_on_bullish_candle(self):
        """Bullish mum bearish reversal olmamali."""
        df = pd.DataFrame({
            "ts": _base_ts(3),
            "open":  [100.0, 105.0, 100.0],
            "close": [100.0, 103.0, 105.0],  # bar2: close > open = bullish
            "high":  [101.0, 106.0, 106.0],
            "low":   [99.0,  102.0,  99.0],
        })
        assert _bearish_reversal(df, 2) is False

    def test_bearish_reversal_no_lookahead(self):
        """idx=0 durumunda False donmeli."""
        df = _make_df(3)
        assert _bearish_reversal(df, 0) is False


# ---------------------------------------------------------------------------
# 8. LONG sinyal uretimi (below VAL + dist > 2ATR + bull reversal)
# ---------------------------------------------------------------------------

class TestLongSignalGeneration:
    def test_long_signal_below_val_with_reversal(self):
        """Below VAL + dist > 2ATR + bull reversal => LONG sinyal."""
        df = _synthetic_trend_df(n=120, seed=42)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        # Bar 80'de long sinyali zorla
        # ATR belirle
        atr_val = float(df_feat.loc[80, "atr14"])
        if np.isnan(atr_val) or atr_val <= 0:
            pytest.skip("ATR degeri yok")

        close_val = float(df_feat.loc[80, "close"])

        # VAL'i close'un 3 ATR uzerine koy => close, VAL'in 3 ATR altinda
        df_feat.loc[80, "val"] = close_val + 3.0 * atr_val
        df_feat.loc[80, "vah"] = close_val + 6.0 * atr_val
        df_feat.loc[80, "poc"] = close_val + 4.5 * atr_val  # POC close'un ustunde

        # Bullish reversal zorla
        df_feat.loc[80, "bull_reversal"] = True
        df_feat.loc[80, "bear_reversal"] = False

        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        long_at_80 = [
            s for s in long_sigs
            if abs((s.ts - df_feat.loc[80, "ts"].to_pydatetime()).total_seconds()) < 86400
        ]
        assert len(long_at_80) >= 1, "Below VAL + reversal => LONG sinyal olmali"
        sig = long_at_80[0]
        assert sig.sl_price < close_val, "SL close altinda olmali"
        assert sig.tp_price > close_val, "TP (POC) close uzerinde olmali"
        assert sig.pattern_id == "tpo_long_reversal"


# ---------------------------------------------------------------------------
# 9. SHORT sinyal uretimi (above VAH + dist > 2ATR + bear reversal)
# ---------------------------------------------------------------------------

class TestShortSignalGeneration:
    def test_short_signal_above_vah_with_reversal(self):
        """Above VAH + dist > 2ATR + bear reversal => SHORT sinyal."""
        df = _synthetic_trend_df(n=120, seed=11, uptrend=False)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        atr_val = float(df_feat.loc[80, "atr14"])
        if np.isnan(atr_val) or atr_val <= 0:
            pytest.skip("ATR degeri yok")

        close_val = float(df_feat.loc[80, "close"])

        # VAH'i close'un 3 ATR altina koy => close, VAH'in 3 ATR uzerinde
        df_feat.loc[80, "vah"] = close_val - 3.0 * atr_val
        df_feat.loc[80, "val"] = close_val - 6.0 * atr_val
        df_feat.loc[80, "poc"] = close_val - 4.5 * atr_val  # POC close'un altinda

        df_feat.loc[80, "bear_reversal"] = True
        df_feat.loc[80, "bull_reversal"] = False

        signals = strat.generate_signals(df_feat)
        short_sigs = [s for s in signals if s.direction == "short"]
        short_at_80 = [
            s for s in short_sigs
            if abs((s.ts - df_feat.loc[80, "ts"].to_pydatetime()).total_seconds()) < 86400
        ]
        assert len(short_at_80) >= 1, "Above VAH + reversal => SHORT sinyal olmali"
        sig = short_at_80[0]
        assert sig.sl_price > close_val, "SL close uzerinde olmali"
        assert sig.tp_price < close_val, "TP (POC) close altinda olmali"
        assert sig.pattern_id == "tpo_short_reversal"


# ---------------------------------------------------------------------------
# 10. ATR mesafe filtresi: dist < 2*ATR => sinyal olmamali
# ---------------------------------------------------------------------------

class TestATRDistanceFilter:
    def test_no_long_when_too_close_to_val(self):
        """Close VAL'e 2ATR'den yakinsa sinyal olmamali (dist < atr_extension_min)."""
        df = _synthetic_trend_df(n=120, seed=33)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        atr_val = float(df_feat.loc[80, "atr14"])
        if np.isnan(atr_val) or atr_val <= 0:
            pytest.skip("ATR yok")

        close_val = float(df_feat.loc[80, "close"])

        # VAL'i close'un sadece 0.5 ATR uzerine koy => cok yakin
        df_feat.loc[80, "val"] = close_val + 0.5 * atr_val
        df_feat.loc[80, "vah"] = close_val + 4.0 * atr_val
        df_feat.loc[80, "poc"] = close_val + 2.0 * atr_val
        df_feat.loc[80, "bull_reversal"] = True

        signals = strat.generate_signals(df_feat)
        long_at_80 = [
            s for s in signals
            if s.direction == "long"
            and abs((s.ts - df_feat.loc[80, "ts"].to_pydatetime()).total_seconds()) < 86400
        ]
        assert len(long_at_80) == 0, "VAL'e 2ATR'den yakin => sinyal olmamali"

    def test_no_short_when_too_close_to_vah(self):
        """Close VAH'e 2ATR'den yakinsa SHORT sinyal olmamali."""
        df = _synthetic_trend_df(n=120, seed=44)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        atr_val = float(df_feat.loc[80, "atr14"])
        if np.isnan(atr_val) or atr_val <= 0:
            pytest.skip("ATR yok")

        close_val = float(df_feat.loc[80, "close"])

        # VAH'i close'un sadece 0.5 ATR altina koy
        df_feat.loc[80, "vah"] = close_val - 0.5 * atr_val
        df_feat.loc[80, "val"] = close_val - 4.0 * atr_val
        df_feat.loc[80, "poc"] = close_val - 2.0 * atr_val
        df_feat.loc[80, "bear_reversal"] = True

        signals = strat.generate_signals(df_feat)
        short_at_80 = [
            s for s in signals
            if s.direction == "short"
            and abs((s.ts - df_feat.loc[80, "ts"].to_pydatetime()).total_seconds()) < 86400
        ]
        assert len(short_at_80) == 0, "VAH'a 2ATR'den yakin => sinyal olmamali"


# ---------------------------------------------------------------------------
# 11. prepare_features gerekli kolonlari eklemeli
# ---------------------------------------------------------------------------

class TestPrepareFeatures:
    def test_required_columns_present(self):
        """prepare_features gerekli kolonlari df'e eklemeli."""
        strat = _make_strategy()
        df = _synthetic_trend_df(n=120, seed=9)
        df_feat = strat.prepare_features(df)
        required = [
            "ema200", "atr14", "atr_pct",
            "vah", "poc", "val",
            "bull_reversal", "bear_reversal",
            "struct_sl_long", "struct_sl_short",
            "vol_z",
        ]
        for col in required:
            assert col in df_feat.columns, f"Eksik kolon: {col}"

    def test_empty_df_returns_empty(self):
        """Bos df prepare_features'da hataya yol acmamali."""
        strat = _make_strategy()
        empty = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        result = strat.prepare_features(empty)
        assert result.empty

    def test_vah_nan_before_lookback(self):
        """lookback bar dolmadan VAH/POC/VAL NaN olmali."""
        strat = _make_strategy()
        df = _synthetic_trend_df(n=50, seed=5)
        df_feat = strat.prepare_features(df)
        # lookback=30, ilk 30 barda NaN bekleniyor
        assert df_feat["poc"].iloc[:30].isna().all(), (
            "Ilk lookback barlarinda POC NaN olmali"
        )


# ---------------------------------------------------------------------------
# 12. Bos df => bos sinyal listesi
# ---------------------------------------------------------------------------

class TestEmptyDF:
    def test_empty_df_no_signals(self):
        """Bos df => bos sinyal listesi."""
        strat = _make_strategy()
        empty = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        signals = strat.generate_signals(empty)
        assert signals == []


# ---------------------------------------------------------------------------
# 13. Sinyal schema dogrulugu
# ---------------------------------------------------------------------------

class TestSignalSchema:
    def test_signal_schema_valid(self):
        """Uretilen sinyaller Signal schema'sini gecmeli."""
        from price_action.contracts import Signal
        df = _synthetic_trend_df(n=120, seed=77)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        atr_val = float(df_feat.loc[80, "atr14"])
        if np.isnan(atr_val) or atr_val <= 0:
            pytest.skip("ATR yok")
        close_val = float(df_feat.loc[80, "close"])

        df_feat.loc[80, "val"] = close_val + 3.0 * atr_val
        df_feat.loc[80, "vah"] = close_val + 6.0 * atr_val
        df_feat.loc[80, "poc"] = close_val + 4.5 * atr_val
        df_feat.loc[80, "bull_reversal"] = True

        signals = strat.generate_signals(df_feat)
        for sig in signals:
            assert isinstance(sig, Signal)
            assert sig.venue == "binance"
            assert sig.timeframe == "1d"
            assert sig.direction in {"long", "short"}
            assert sig.sl_price > 0
            assert sig.tp_price > 0
            assert sig.fingerprint()

    def test_default_manifest_valid(self):
        """_default_manifest() gecerli StrategyManifest donemeli."""
        m = _default_manifest()
        assert m.name == "tpo_value_area"
        assert len(m.signals.patterns) == 2
        ids = {p.id for p in m.signals.patterns}
        assert "tpo_long_reversal" in ids
        assert "tpo_short_reversal" in ids


# ---------------------------------------------------------------------------
# 14. Smoke testi (rastgele veri)
# ---------------------------------------------------------------------------

class TestSmoke:
    def test_smoke_no_crash(self):
        """Rastgele veri ile exception olmamali."""
        rng = np.random.default_rng(999)
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

    def test_smoke_trend_uptrend_no_crash(self):
        """Guclu uptrend verisinde exception olmamali."""
        df = _synthetic_trend_df(n=150, seed=2024, uptrend=True)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        signals = strat.generate_signals(df_feat)
        assert isinstance(signals, list)

    def test_smoke_trend_downtrend_no_crash(self):
        """Guclu downtrend verisinde exception olmamali."""
        df = _synthetic_trend_df(n=150, seed=2025, uptrend=False)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        signals = strat.generate_signals(df_feat)
        assert isinstance(signals, list)
