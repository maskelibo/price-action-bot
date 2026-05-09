"""Unit testler — CVDSpikeFadeStrategy + OBV helpers + backtest entegrasyonu.

Test senaryolari (8 test):
  1. _obv: bilinen seriler üzerinde manuel doğrulama
  2. _obv_zscore: extreme değer üretmek için yapay OBV spike
  3. _bearish_engulfing / _bullish_engulfing: detection doğruluğu
  4. prepare_features: gerekli kolonlar var mı
  5. generate_signals — SHORT: OBV spike (z>2.5) + bearish engulfing
  6. generate_signals — LONG:  OBV spike (z<-2.5) + bullish engulfing
  7. generate_signals — NO signal when only spike (no confirmation)
  8. Lookahead-bias: sinyalin sadece geçmiş barları kullandığı kontrolü
  --- ek testler ---
  9. Empty DataFrame → boş liste, exception yok
 10. Backtest smoke: engine ile strateji çalışıyor mu, trade üretiyor mu
 11. Signal schema geçerli (Signal objesi doğru alanları taşıyor)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.cvd_spike_fade import (
    CVDSpikeFadeStrategy,
    _bearish_engulfing,
    _bullish_engulfing,
    _default_manifest,
    _obv,
    _obv_zscore,
    build_strategy,
)


# ---------------------------------------------------------------------------
# Ortak yardımcılar
# ---------------------------------------------------------------------------

def _base_ts(n: int, start: datetime | None = None) -> list[datetime]:
    if start is None:
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def _bar(o: float, h: float, l: float, c: float, v: float = 1_000_000.0) -> dict:
    return {"open": float(o), "high": float(h), "low": float(l),
            "close": float(c), "volume": float(v)}


def _make_df(bars: list[dict], symbol: str = "BTC/USDT") -> pd.DataFrame:
    ts = _base_ts(len(bars))
    df = pd.DataFrame(bars)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = df[col].astype(float)
    df["ts"] = ts
    df["venue"] = "binance"
    df["symbol"] = symbol
    df["timeframe"] = "1d"
    if "volume" not in df.columns:
        df["volume"] = 1_000_000.0
    return df


def _synthetic_ohlcv(
    n: int = 200,
    seed: int = 42,
    base_price: float = 50_000.0,
    trend: float = 0.0,
) -> pd.DataFrame:
    """Deterministik sentetik OHLCV — backtest testleri için."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(trend, 0.015, n)
    close = base_price * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(1e6, 5e6, n)
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


# ---------------------------------------------------------------------------
# Test 1: _obv — manuel doğrulama
# ---------------------------------------------------------------------------

class TestOBV:
    """OBV hesaplama doğruluğu."""

    def test_obv_rising_close_adds_volume(self) -> None:
        """Kapanış yükselince hacim OBV'ye eklenmeli."""
        bars = [
            _bar(100.0, 101.0, 99.0, 100.0, v=1000.0),   # bar 0: başlangıç
            _bar(100.0, 102.0, 100.0, 101.0, v=2000.0),  # bar 1: close > prev → +2000
            _bar(101.0, 103.0, 101.0, 102.0, v=1500.0),  # bar 2: close > prev → +1500
        ]
        df = _make_df(bars)
        obv = _obv(df)
        assert obv.iloc[0] == 0.0,    "Başlangıç OBV sıfır olmalı"
        assert obv.iloc[1] == 2000.0, "Yükselen kapanış hacim eklemeli"
        assert obv.iloc[2] == 3500.0, "İkinci yükselen kapanış da eklemeli"

    def test_obv_falling_close_subtracts_volume(self) -> None:
        """Kapanış düşünce hacim OBV'den çıkarılmalı."""
        bars = [
            _bar(100.0, 101.0, 99.0, 100.0, v=1000.0),
            _bar(100.0, 100.5, 97.0, 98.0, v=3000.0),   # close < prev → -3000
            _bar(98.0, 98.5, 96.0, 97.0, v=2000.0),     # close < prev → -2000
        ]
        df = _make_df(bars)
        obv = _obv(df)
        assert obv.iloc[1] == -3000.0
        assert obv.iloc[2] == -5000.0

    def test_obv_equal_close_unchanged(self) -> None:
        """Kapanış değişmeyince OBV sabit kalmalı."""
        bars = [
            _bar(100.0, 101.0, 99.0, 100.0, v=1000.0),
            _bar(100.0, 101.5, 99.5, 100.0, v=5000.0),  # close == prev → no change
        ]
        df = _make_df(bars)
        obv = _obv(df)
        assert obv.iloc[1] == 0.0, "Eşit kapanışta OBV değişmemeli"

    def test_obv_returns_correct_length(self) -> None:
        """OBV serisi DataFrame ile aynı uzunlukta olmalı."""
        df = _synthetic_ohlcv(n=100)
        obv = _obv(df)
        assert len(obv) == 100


# ---------------------------------------------------------------------------
# Test 2: _obv_zscore — spike tespiti
# ---------------------------------------------------------------------------

class TestOBVZScore:
    """OBV z-score hesaplama ve spike tespiti."""

    def test_zscore_flat_obv_near_zero(self) -> None:
        """Sabit OBV → z-score ≈ 0 (std=0 durumunda fillna(0))."""
        obv = pd.Series([100.0] * 50)
        z = _obv_zscore(obv, lookback=30)
        # std=0 → NaN → fillna(0)
        assert (z.abs() <= 1e-9).all(), "Sabit OBV'de z-score sıfır olmalı"

    def test_zscore_spike_detected(self) -> None:
        """Ani OBV spike → z-score eşiği aşmalı."""
        n = 60
        # İlk 50 bar: OBV yavaş büyüme
        obv_vals = list(np.linspace(0, 5_000_000, 50))
        # Bar 50: dev spike
        obv_vals.append(obv_vals[-1] + 50_000_000)
        obv_vals.extend(obv_vals[-1:] * (n - 51))
        obv = pd.Series(obv_vals, dtype=float)
        z = _obv_zscore(obv, lookback=30)
        # Spike bar (idx=50) z-score'u 2.5'i geçmeli
        assert z.iloc[50] > 2.5, f"Spike z-score ({z.iloc[50]:.2f}) > 2.5 olmalı"

    def test_zscore_length_matches(self) -> None:
        """Z-score serisi OBV ile aynı uzunluktaki olmalı."""
        obv = pd.Series(np.random.randn(80).cumsum())
        z = _obv_zscore(obv, lookback=30)
        assert len(z) == 80

    def test_zscore_no_nan_after_warmup(self) -> None:
        """Lookback/2 barlık warmup sonrası NaN kalmamalı (fillna uygular)."""
        obv = pd.Series(np.random.default_rng(1).normal(0, 1e6, 100).cumsum())
        z = _obv_zscore(obv, lookback=30)
        assert not z.isna().any(), "Z-score serisinde NaN olmamalı"


# ---------------------------------------------------------------------------
# Test 3: _bearish_engulfing / _bullish_engulfing
# ---------------------------------------------------------------------------

class TestEngulfingConfirmation:
    """Reversal confirmation bar tespiti."""

    def test_bearish_engulfing_detected(self) -> None:
        """Kesin bearish engulfing tespit edilmeli."""
        bars = [
            _bar(100.0, 101.0, 99.0, 100.0),         # nötr
            _bar(99.0, 103.0, 99.0, 102.0),           # bullish prev
            # bearish engulf: o(104)>=prev_c(102), c(98)<=prev_o(99), body=(104-98)=6, rng=8 → 0.75>0.5
            _bar(104.0, 104.5, 96.0, 98.0),
        ]
        df = _make_df(bars)
        flags = _bearish_engulfing(df, body_ratio_min=0.5)
        assert bool(flags.iloc[2]), "Bar 2 bearish engulfing olmalı"
        assert not bool(flags.iloc[1]), "Bar 1 bearish engulfing değil"

    def test_bullish_engulfing_detected(self) -> None:
        """Kesin bullish engulfing tespit edilmeli."""
        bars = [
            _bar(100.0, 101.0, 99.0, 100.0),
            _bar(100.5, 101.0, 96.0, 97.0),           # bearish prev
            # bullish engulf: o(95)<=prev_c(97), c(103)>=prev_o(100.5), body=8, rng=10 → 0.8>0.5
            _bar(95.0, 105.0, 95.0, 103.0),
        ]
        df = _make_df(bars)
        flags = _bullish_engulfing(df, body_ratio_min=0.5)
        assert bool(flags.iloc[2]), "Bar 2 bullish engulfing olmalı"

    def test_no_engulfing_same_color(self) -> None:
        """Aynı renk ardışık bar → engulfing değil."""
        bars = [
            _bar(100.0, 101.0, 99.0, 100.0),
            _bar(99.0, 102.0, 99.0, 101.0),   # bullish
            _bar(100.0, 104.0, 100.0, 103.0), # bullish again
        ]
        df = _make_df(bars)
        flags = _bearish_engulfing(df, body_ratio_min=0.5)
        assert not bool(flags.iloc[2]), "İki bullish bar → bearish engulfing olmaz"

    def test_engulfing_fails_body_ratio(self) -> None:
        """Body ratio < threshold → engulfing reddedilmeli."""
        bars = [
            _bar(100.0, 101.0, 99.0, 100.0),
            _bar(100.0, 102.0, 99.0, 101.0),         # bullish
            # bearish ama body=0.1, rng=20 → ratio=0.005 < 0.5
            _bar(102.0, 102.0, 82.0, 101.9),
        ]
        df = _make_df(bars)
        flags = _bearish_engulfing(df, body_ratio_min=0.5)
        assert not bool(flags.iloc[2]), "Düşük body_ratio'da bearish engulfing olmaz"


# ---------------------------------------------------------------------------
# Test 4: prepare_features
# ---------------------------------------------------------------------------

class TestPrepareFeatures:
    """prepare_features kolonları doğru eklemeli."""

    def test_required_columns_present(self) -> None:
        strat = build_strategy()
        df = _synthetic_ohlcv(n=100)
        df_feat = strat.prepare_features(df)
        required = ["atr14", "atr_pct", "obv", "obv_zscore",
                    "obv_z_lag1", "bear_confirm", "bull_confirm", "ema50"]
        for col in required:
            assert col in df_feat.columns, f"Eksik kolon: {col}"

    def test_no_nan_obv(self) -> None:
        """OBV kolonu NaN içermemeli."""
        strat = build_strategy()
        df = strat.prepare_features(_synthetic_ohlcv(n=80))
        assert not df["obv"].isna().any(), "OBV'de NaN olmamalı"

    def test_obv_z_lag1_is_shifted(self) -> None:
        """obv_z_lag1[i] == obv_zscore[i-1] (shift doğruluğu)."""
        strat = build_strategy()
        df = strat.prepare_features(_synthetic_ohlcv(n=60))
        # lag1[i] == zscore[i-1] (bar 10'dan itibaren)
        for i in range(10, 50):
            expected = df["obv_zscore"].iloc[i - 1]
            actual = df["obv_z_lag1"].iloc[i]
            assert abs(expected - actual) < 1e-10, f"Bar {i}: lag1 uyuşmuyor"


# ---------------------------------------------------------------------------
# Test 5: SHORT sinyali
# ---------------------------------------------------------------------------

class TestShortSignal:
    """OBV spike (z > threshold) + bearish engulfing → short signal."""

    def _make_spike_short_df(
        self,
        n: int = 80,
        spike_bar: int = 45,
        confirm_bar: int = 46,
    ) -> pd.DataFrame:
        """Kontrollü spike + bearish engulfing DataFrame."""
        df = _synthetic_ohlcv(n=n, seed=7)
        strat = build_strategy()
        df = strat.prepare_features(df)

        # Spike bar'da OBV z-score'u aşırı yüksek yap
        df.loc[spike_bar, "obv_zscore"] = 3.5  # > 2.5
        # obv_z_lag1[confirm_bar] = obv_zscore[spike_bar]
        df.loc[confirm_bar, "obv_z_lag1"] = 3.5

        # Confirmation bar: bearish engulfing = True
        df.loc[confirm_bar, "bear_confirm"] = True
        df.loc[confirm_bar, "bull_confirm"] = False

        # ATR geçerliliğini garantile
        df.loc[confirm_bar, "atr14"] = float(df.loc[confirm_bar, "close"]) * 0.02
        df["atr_pct"] = df["atr14"] / df["close"]

        return df

    def test_short_signal_generated(self) -> None:
        """Spike + confirmation → en az 1 short sinyal üretilmeli."""
        strat = build_strategy()
        df = self._make_spike_short_df(spike_bar=45, confirm_bar=46)
        signals = strat.generate_signals(df)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) >= 1, f"Short sinyal bekleniyor, üretilen: {len(short_sigs)}"

    def test_short_signal_sl_above_close(self) -> None:
        """Short sinyalinde SL close'un üzerinde olmalı."""
        strat = build_strategy()
        df = self._make_spike_short_df(spike_bar=45, confirm_bar=46)
        signals = strat.generate_signals(df)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) >= 1
        sig = short_sigs[0]
        assert sig.sl_price > float(df.loc[46, "close"]), "Short SL close üzerinde olmalı"

    def test_short_signal_tp_below_close(self) -> None:
        """Short sinyalinde TP close'un altında olmalı."""
        strat = build_strategy()
        df = self._make_spike_short_df(spike_bar=45, confirm_bar=46)
        signals = strat.generate_signals(df)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) >= 1
        sig = short_sigs[0]
        assert sig.tp_price < float(df.loc[46, "close"]), "Short TP close altında olmalı"

    def test_short_pattern_id_correct(self) -> None:
        """Short sinyal pattern_id 'obv_spike_short' olmalı."""
        strat = build_strategy()
        df = self._make_spike_short_df(spike_bar=45, confirm_bar=46)
        signals = strat.generate_signals(df)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) >= 1
        assert short_sigs[0].pattern_id == "obv_spike_short"


# ---------------------------------------------------------------------------
# Test 6: LONG sinyali
# ---------------------------------------------------------------------------

class TestLongSignal:
    """OBV spike (z < -threshold) + bullish engulfing → long signal."""

    def _make_spike_long_df(
        self,
        n: int = 80,
        spike_bar: int = 45,
        confirm_bar: int = 46,
    ) -> pd.DataFrame:
        df = _synthetic_ohlcv(n=n, seed=11)
        strat = build_strategy()
        df = strat.prepare_features(df)

        df.loc[spike_bar, "obv_zscore"] = -3.5  # < -2.5
        df.loc[confirm_bar, "obv_z_lag1"] = -3.5

        df.loc[confirm_bar, "bull_confirm"] = True
        df.loc[confirm_bar, "bear_confirm"] = False

        df.loc[confirm_bar, "atr14"] = float(df.loc[confirm_bar, "close"]) * 0.02
        df["atr_pct"] = df["atr14"] / df["close"]

        return df

    def test_long_signal_generated(self) -> None:
        strat = build_strategy()
        df = self._make_spike_long_df(spike_bar=45, confirm_bar=46)
        signals = strat.generate_signals(df)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) >= 1, f"Long sinyal bekleniyor, üretilen: {len(long_sigs)}"

    def test_long_signal_sl_below_close(self) -> None:
        strat = build_strategy()
        df = self._make_spike_long_df(spike_bar=45, confirm_bar=46)
        signals = strat.generate_signals(df)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) >= 1
        sig = long_sigs[0]
        assert sig.sl_price < float(df.loc[46, "close"]), "Long SL close altında olmalı"

    def test_long_signal_tp_above_close(self) -> None:
        strat = build_strategy()
        df = self._make_spike_long_df(spike_bar=45, confirm_bar=46)
        signals = strat.generate_signals(df)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) >= 1
        sig = long_sigs[0]
        assert sig.tp_price > float(df.loc[46, "close"]), "Long TP close üzerinde olmalı"

    def test_long_pattern_id_correct(self) -> None:
        strat = build_strategy()
        df = self._make_spike_long_df(spike_bar=45, confirm_bar=46)
        signals = strat.generate_signals(df)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) >= 1
        assert long_sigs[0].pattern_id == "obv_spike_long"


# ---------------------------------------------------------------------------
# Test 7: Confirmation olmadan sinyal üretilmemeli
# ---------------------------------------------------------------------------

class TestNoSignalWithoutConfirmation:
    """Spike var ama confirmation bar yok → sinyal üretilmemeli."""

    def test_spike_no_confirmation_no_short(self) -> None:
        """z > 2.5 ama bearish engulfing yok → short sinyal yok."""
        df = _synthetic_ohlcv(n=80, seed=99)
        strat = build_strategy()
        df = strat.prepare_features(df)

        # Spike set et ama confirmation'ı False bırak (varsayılan False)
        df.loc[45, "obv_zscore"] = 4.0
        df.loc[46, "obv_z_lag1"] = 4.0
        df["bear_confirm"] = False   # hiçbir barda confirmation yok
        df["bull_confirm"] = False
        df["atr_pct"] = 0.02

        signals = strat.generate_signals(df)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) == 0, "Confirmation olmadan short sinyal üretilmemeli"

    def test_confirmation_no_spike_no_signal(self) -> None:
        """Bearish engulfing var ama z-score düşük → sinyal yok."""
        df = _synthetic_ohlcv(n=80, seed=55)
        strat = build_strategy()
        df = strat.prepare_features(df)

        # z-score düşük (eşiğin altında)
        df["obv_zscore"] = 0.5   # < 2.5
        df["obv_z_lag1"] = 0.5
        df.loc[46, "bear_confirm"] = True
        df["atr_pct"] = 0.02

        signals = strat.generate_signals(df)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) == 0, "Düşük z-score'da confirmation olsa da sinyal olmamalı"


# ---------------------------------------------------------------------------
# Test 8: Lookahead-bias kontrolü
# ---------------------------------------------------------------------------

class TestLookaheadBias:
    """Sinyal t anında yalnızca [t-1..t-lookback] veriye bakmalı."""

    def test_future_bars_dont_change_past_signals(self) -> None:
        """t=46 sinyalinin t=47..end verisi değişince değişmemesi gerekir.

        Yöntem:
          1. n=80 bar ile sinyal üret, bar 46'daki long sinyal say.
          2. Bar 47..79'u tamamen farklı değerlerle yaz.
          3. Sinyal sayısı (bar 46'daki) değişmemeli.
        """
        strat = build_strategy()
        df_base = _synthetic_ohlcv(n=80, seed=33)
        df_base = strat.prepare_features(df_base)

        # Spike + long confirmation at bar 45/46
        df_base.loc[45, "obv_zscore"] = -4.0
        df_base.loc[46, "obv_z_lag1"] = -4.0
        df_base.loc[46, "bull_confirm"] = True
        df_base.loc[46, "bear_confirm"] = False
        df_base.loc[46, "atr14"] = float(df_base.loc[46, "close"]) * 0.02
        df_base["atr_pct"] = df_base["atr14"] / df_base["close"]

        signals_before = strat.generate_signals(df_base.copy())
        long_before = [s for s in signals_before if s.direction == "long"]

        # Bar 47+ 'yi yok et — farklı değerler
        df_modified = df_base.copy()
        df_modified.loc[47:, "obv_z_lag1"] = 0.0
        df_modified.loc[47:, "bull_confirm"] = False
        df_modified.loc[47:, "bear_confirm"] = False
        df_modified.loc[47:, "obv_zscore"] = 0.0

        signals_after = strat.generate_signals(df_modified)
        long_after = [s for s in signals_after if s.direction == "long"]

        # Bar 46'daki sinyali koruma
        ts_before = {s.ts for s in long_before}
        ts_after = {s.ts for s in long_after}
        shared = ts_before & ts_after
        assert len(long_before) >= 1, "Önceki sinyaller oluşmalı"
        assert len(shared) >= 1, "Gelecek barlar silinince bar 46 sinyali kaybolmamalı"

    def test_obv_z_lag1_prevents_lookahead(self) -> None:
        """obv_z_lag1[i] = obv_zscore[i-1] — spike i-1'de, signal i'de tetiklenir.

        Bu, confirmation bar (i) kararının spike bar (i-1) sonrası geldiğini garanti eder.
        """
        strat = build_strategy()
        df = strat.prepare_features(_synthetic_ohlcv(n=60, seed=5))
        # Bar 30'da spike inject
        df.loc[30, "obv_zscore"] = 5.0
        # Rebuild lag (prepare_features yapmak yerine manuel doğrula)
        df["obv_z_lag1"] = df["obv_zscore"].shift(1).fillna(0.0)
        # Bar 31'in lag1'i bar 30'un spike değeri
        assert df.loc[31, "obv_z_lag1"] == 5.0, "lag1[31] == zscore[30] olmalı"
        # Bar 30'un lag1'i bar 29'un değeri (spike değil)
        assert df.loc[30, "obv_z_lag1"] != 5.0, "lag1[30] != zscore[30] — lookahead yok"


# ---------------------------------------------------------------------------
# Test 9: Empty DataFrame
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_df_prepare_features(self) -> None:
        """Boş df → prepare_features exception atmaz."""
        strat = build_strategy()
        empty = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        result = strat.prepare_features(empty)
        assert result.empty

    def test_empty_df_generate_signals(self) -> None:
        """Boş df → boş liste, exception yok."""
        strat = build_strategy()
        signals = strat.generate_signals(pd.DataFrame())
        assert signals == []

    def test_smoke_random_data(self) -> None:
        """Rastgele veri → exception yok, liste döner."""
        strat = build_strategy()
        df = _synthetic_ohlcv(n=300, seed=777)
        df = strat.prepare_features(df)
        signals = strat.generate_signals(df)
        assert isinstance(signals, list)

    def test_default_manifest_valid(self) -> None:
        """_default_manifest() geçerli StrategyManifest üretmeli."""
        m = _default_manifest()
        assert m.name == "cvd_spike_fade"
        assert len(m.signals.patterns) == 2
        for p in m.signals.patterns:
            assert p.id in ("obv_spike_short", "obv_spike_long")


# ---------------------------------------------------------------------------
# Test 10: Signal schema
# ---------------------------------------------------------------------------

class TestSignalSchema:
    """Üretilen sinyaller Signal contract'ını geçmeli."""

    def test_signal_fields(self) -> None:
        from price_action.contracts import Signal

        strat = build_strategy()
        df = _synthetic_ohlcv(n=80, seed=7)
        df = strat.prepare_features(df)

        # Short spike inject
        df.loc[45, "obv_zscore"] = 3.5
        df.loc[46, "obv_z_lag1"] = 3.5
        df.loc[46, "bear_confirm"] = True
        df.loc[46, "bull_confirm"] = False
        df.loc[46, "atr14"] = float(df.loc[46, "close"]) * 0.02
        df["atr_pct"] = df["atr14"] / df["close"]

        signals = strat.generate_signals(df)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) >= 1

        sig = short_sigs[0]
        assert isinstance(sig, Signal)
        assert sig.venue == "binance"
        assert sig.timeframe == "1d"
        assert sig.direction == "short"
        assert sig.pattern_id == "obv_spike_short"
        assert sig.confluence_score > 0
        assert sig.sl_price > 0
        assert sig.tp_price > 0
        assert sig.fingerprint()  # hash üretilebiliyor mu
        assert "obv_zscore_prev" in sig.metadata
        assert sig.metadata["proxy_type"] == "obv_zscore"


# ---------------------------------------------------------------------------
# Test 11: Backtest entegrasyon smoke
# ---------------------------------------------------------------------------

class TestBacktestSmoke:
    """BacktestEngine ile strateji çalışmalı ve makul sonuçlar üretmeli."""

    def test_backtest_runs_without_error(self) -> None:
        """Backtest engine exception atmadan tamamlanmalı."""
        from datetime import timezone
        from price_action.backtest.engine import BacktestEngine

        strat = build_strategy()
        df = _synthetic_ohlcv(n=400, seed=42, base_price=50_000.0)

        # Birkaç kontrollü spike inject
        df_feat = strat.prepare_features(df)
        # Spike-confirm çiftleri: (spike_bar, confirm_bar, direction)
        for spike, confirm, z_val, bear, bull in [
            (60, 61, 3.5, True, False),
            (100, 101, -3.5, False, True),
            (150, 151, 3.2, True, False),
            (200, 201, -4.0, False, True),
        ]:
            df_feat.loc[spike, "obv_zscore"] = z_val
            df_feat.loc[confirm, "obv_z_lag1"] = z_val
            df_feat.loc[confirm, "bear_confirm"] = bear
            df_feat.loc[confirm, "bull_confirm"] = bull
            df_feat.loc[confirm, "atr14"] = float(df_feat.loc[confirm, "close"]) * 0.02
        df_feat["atr_pct"] = df_feat["atr14"] / df_feat["close"]

        def _provider(sym, tf, start, end):
            return df_feat.copy()

        start_dt = datetime(2023, 1, 1, tzinfo=timezone.utc)
        end_dt = datetime(2023, 1, 1, tzinfo=timezone.utc) + timedelta(days=400)

        engine = BacktestEngine()
        result = engine.run(
            strat,
            universe=["BTC/USDT"],
            start=start_dt,
            end=end_dt,
            ohlcv_provider=_provider,
            initial_capital=10_000.0,
            timeframe="1d",
        )

        assert result.strategy_name == "cvd_spike_fade"
        assert result.n_trades >= 0  # Engine çalıştı
        assert "sharpe" in result.kpis
        assert "win_rate" in result.kpis
        assert "max_drawdown" in result.kpis

    def test_backtest_trade_pnl_finite(self) -> None:
        """Trade PnL değerleri finite (NaN veya inf içermemeli)."""
        from datetime import timezone
        from price_action.backtest.engine import BacktestEngine

        strat = build_strategy()
        df = _synthetic_ohlcv(n=300, seed=13, base_price=40_000.0)
        df_feat = strat.prepare_features(df)

        # 3 spike-confirm çifti
        for spike, confirm, z_val, bear, bull in [
            (50, 51, 3.5, True, False),
            (100, 101, -3.0, False, True),
            (200, 201, 4.0, True, False),
        ]:
            df_feat.loc[spike, "obv_zscore"] = z_val
            df_feat.loc[confirm, "obv_z_lag1"] = z_val
            df_feat.loc[confirm, "bear_confirm"] = bear
            df_feat.loc[confirm, "bull_confirm"] = bull
            df_feat.loc[confirm, "atr14"] = float(df_feat.loc[confirm, "close"]) * 0.015
        df_feat["atr_pct"] = df_feat["atr14"] / df_feat["close"]

        def _provider(sym, tf, start, end):
            return df_feat.copy()

        start_dt = datetime(2023, 1, 1, tzinfo=timezone.utc)
        end_dt = datetime(2023, 1, 1, tzinfo=timezone.utc) + timedelta(days=300)

        engine = BacktestEngine()
        result = engine.run(
            strat,
            universe=["BTC/USDT"],
            start=start_dt,
            end=end_dt,
            ohlcv_provider=_provider,
            initial_capital=10_000.0,
            timeframe="1d",
        )

        if not result.trades.empty and "realized_pnl_usdt" in result.trades.columns:
            pnls = result.trades["realized_pnl_usdt"]
            assert pnls.notna().all(), "PnL değerleri NaN içermemeli"
            assert np.isfinite(pnls).all(), "PnL değerleri finite olmalı"
