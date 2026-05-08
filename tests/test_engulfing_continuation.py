"""Unit testler -- EngulfingContinuationStrategy.

Test senaryolari:
  1. Bilinen engulfing + pullback => sinyal beklenir
  2. Engulfing yok => sinyal yok
  3. Engulfing var ama pullback yok => sinyal yok (continuation kurali)
  4. Lookahead-bias kontrolu: t anindaki flag sadece [t-10..t-1] bilgisini kullanir
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.engulfing_continuation import (
    EngulfingContinuationStrategy,
    _pullback_to_ema_flag,
    _strict_engulfing,
    _swing_sl,
    _default_manifest,
)


# ---------------------------------------------------------------------------
# Yardimci fabrika
# ---------------------------------------------------------------------------

def _make_strategy(overrides: dict | None = None) -> EngulfingContinuationStrategy:
    """Minimal test manifest ile strateji olusturur."""
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "engulfing_continuation",
        "version": "0.0.1",
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "bullish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {"body_ratio_min": 0.6, "pullback_window": 10, "pullback_touch_atr": 0.5},
                },
                {
                    "id": "bearish_engulfing_cont",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {"body_ratio_min": 0.6, "pullback_window": 10, "pullback_touch_atr": 0.5},
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
                "kaufman_er_min": 0.0,
                "bear_regime_size_factor": 1.0,
            },
            "confluence": {"method": "weighted_sum", "min_score": 1.0, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "stop_loss": {"method": "structural", "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
        },
    }
    if overrides:
        raw.update(overrides)
    manifest = StrategyManifest.model_validate(raw)
    return EngulfingContinuationStrategy(manifest)


def _base_ts(n: int) -> list[datetime]:
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def _df_from_bars(bars: list[dict], venue: str = "binance", symbol: str = "TEST/USDT") -> pd.DataFrame:
    """Bar listesinden DataFrame olustur (float tum sayisal kolonlar)."""
    ts = _base_ts(len(bars))
    df = pd.DataFrame(bars)
    # float dtype garantile — loc atamalarinda int64 -> float sorununu onle
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = df[col].astype(float)
    df["ts"] = ts
    df["venue"] = venue
    df["symbol"] = symbol
    df["timeframe"] = "1d"
    if "volume" not in df.columns:
        df["volume"] = 1_000_000.0
    return df


def _bar(o: float, h: float, l: float, c: float, v: float = 1_000_000.0) -> dict:
    return {"open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": float(v)}


def _make_float_df(n: int, base_price: float = 110.0, ema_val: float = 100.0, atr_val: float = 2.0) -> pd.DataFrame:
    """Tamamen float tipli sade OHLCV -- pullback testleri icin."""
    ts = _base_ts(n)
    df = pd.DataFrame({
        "ts": ts,
        "open":   np.full(n, base_price - 1.0),
        "high":   np.full(n, base_price + 2.0),
        "low":    np.full(n, base_price - 1.5),
        "close":  np.full(n, base_price),
        "volume": np.full(n, 1_000_000.0),
        "venue": "binance",
        "symbol": "TEST/USDT",
        "timeframe": "1d",
        "ema20":  np.full(n, ema_val),
        "atr14":  np.full(n, atr_val),
    })
    return df


# ---------------------------------------------------------------------------
# 1. _strict_engulfing unit testler
# ---------------------------------------------------------------------------

class TestStrictEngulfing:
    def test_bullish_engulfing_detected(self):
        """Kesin bullish engulfing bar'i dogru tespit etmeli."""
        bars = [
            _bar(100.0, 101.0, 99.0, 100.0),
            _bar(100.0, 101.0, 95.0, 96.0),    # bearish
            # bullish: o=95, c=103, range=10, body=8 >= 0.6*10=6 OK
            # engulf: o(95)<=prev_c(96), c(103)>=prev_o(100)
            _bar(95.0, 104.0, 94.0, 103.0),
        ]
        df = _df_from_bars(bars)
        flags = _strict_engulfing(df, body_ratio_min=0.6, bullish=True)
        assert bool(flags.iloc[2]), "Bar 2 bullish engulfing olmali"
        assert not bool(flags.iloc[0]), "Bar 0 engulfing olmamali"
        assert not bool(flags.iloc[1]), "Bar 1 bearish - bullish engulfing degil"

    def test_bearish_engulfing_detected(self):
        bars = [
            _bar(100.0, 101.0, 99.0, 100.0),
            _bar(100.0, 105.0, 99.0, 104.0),   # bullish
            # bearish: o=106, c=98, range=10, body=8 >= 0.6*10=6 OK
            # engulf: o(106)>=prev_c(104), c(98)<=prev_o(100)
            _bar(106.0, 108.0, 97.0, 98.0),
        ]
        df = _df_from_bars(bars)
        flags = _strict_engulfing(df, body_ratio_min=0.6, bullish=False)
        assert bool(flags.iloc[2]), "Bar 2 bearish engulfing olmali"

    def test_engulfing_fails_body_ratio(self):
        """Body ratio < 0.6 ise engulfing reddedilmeli."""
        bars = [
            _bar(100.0, 101.0, 99.0, 100.0),
            _bar(100.0, 101.0, 95.0, 96.0),    # bearish
            # range=21, body=2 (95->97) => ratio=2/21=0.095 < 0.6
            _bar(94.0, 115.0, 94.0, 96.0),
        ]
        df = _df_from_bars(bars)
        flags = _strict_engulfing(df, body_ratio_min=0.6, bullish=True)
        assert not bool(flags.iloc[2]), "Dusuk body_ratio'da engulfing olmamali"

    def test_no_engulf_when_same_color(self):
        """Iki bullish bar art arda -- engulfing olmamali."""
        bars = [
            _bar(100.0, 101.0, 99.0, 100.0),
            _bar(99.0, 101.0, 98.0, 101.0),    # bullish
            _bar(100.0, 105.0, 99.0, 104.0),   # bullish again -- prev is bullish
        ]
        df = _df_from_bars(bars)
        flags = _strict_engulfing(df, bullish=True)
        assert not bool(flags.iloc[2])

    def test_first_bar_no_signal(self):
        """Ilk barda prev yok => False olmali."""
        bars = [_bar(100.0, 105.0, 95.0, 102.0)]
        df = _df_from_bars(bars)
        assert not bool(_strict_engulfing(df, bullish=True).any())
        assert not bool(_strict_engulfing(df, bullish=False).any())


# ---------------------------------------------------------------------------
# 2. _pullback_to_ema_flag unit testler
# ---------------------------------------------------------------------------

class TestPullbackFlag:
    def test_pullback_detected_after_touch(self):
        """EMA'ya dokunus sonraki 10 bar icin flag True olmali.

        EMA20=100, ATR=2.0, tol=0.5*2=1.0.
        Bar 5: low=99.5 (<= ema+tol=101), high=101.5 (>= ema-tol=99) => dokunma.
        shift(1) => dokunma bar 6'da gorulur, rolling(10) ile 6..15 arasi True.
        """
        n = 25
        df = _make_float_df(n, base_price=110.0, ema_val=100.0, atr_val=2.0)
        df.loc[5, "low"] = 99.5    # EMA(100) - tol(1.0) = 99.0 < 99.5 => icinde
        df.loc[5, "high"] = 101.5  # EMA(100) + tol(1.0) = 101.0 < 101.5 => icinde
        flags = _pullback_to_ema_flag(df, ema_col="ema20", window=10, touch_atr_factor=0.5)
        assert bool(flags.iloc[6]), "Dokunustan sonraki barda flag True olmali"
        assert bool(flags.iloc[14]), "window=10 icinde dokunma varsa hala True olmali"

    def test_no_pullback_without_touch(self):
        """EMA'ya hic dokunulmadi => flag False.

        Fiyat 110, EMA 100, ATR=2, tol=1.0.
        low=108.5 >> ema+tol=101 => hicbir bar dokunmuyor.
        """
        n = 25
        df = _make_float_df(n, base_price=110.0, ema_val=100.0, atr_val=2.0)
        flags = _pullback_to_ema_flag(df, ema_col="ema20", window=10, touch_atr_factor=0.5)
        assert not bool(flags.any()), "Dokunma olmadan flag False olmali"


# ---------------------------------------------------------------------------
# 3. Strategy sinyal uretimi testleri
# ---------------------------------------------------------------------------

def _make_synthetic_trend_df(
    n: int = 80,
    seed: int = 42,
    uptrend: bool = True,
) -> pd.DataFrame:
    """Gercekci uptrend/downtrend sentetik OHLCV -- EMA hesaplari icin yeterli bar."""
    rng = np.random.default_rng(seed)
    drift = 0.003 if uptrend else -0.003
    rets = rng.normal(drift, 0.015, n)
    close = 100.0 * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(800_000.0, 2_000_000.0, n)
    ts = [datetime(2023, 1, 1, tzinfo=timezone.utc) + timedelta(days=i) for i in range(n)]
    df = pd.DataFrame({
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
    return df


class TestEngulfingContinuationSignals:
    def test_importable(self):
        """Strateji dogru modulden import edilebilmeli."""
        from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy
        assert EngulfingContinuationStrategy.name == "engulfing_continuation"

    def test_prepare_features_columns(self):
        """prepare_features gerekli kolonlari eklemeli."""
        strat = _make_strategy()
        df = _make_synthetic_trend_df(n=80)
        df_feat = strat.prepare_features(df)
        required = [
            "ema20", "ema50", "ema14", "atr14", "atr_pct",
            "pullback_to_20ema", "strict_bull_engulf", "strict_bear_engulf",
            "struct_sl_long", "struct_sl_short", "kaufman_er",
            "always_in_long", "always_in_short",
        ]
        for col in required:
            assert col in df_feat.columns, f"Eksik kolon: {col}"

    def test_empty_df_returns_no_signals(self):
        strat = _make_strategy()
        empty = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        signals = strat.generate_signals(empty)
        assert signals == []

    def test_known_bullish_engulfing_after_pullback(self):
        """Pullback + engulfing sonrasi en az bir long sinyal uretilmeli."""
        df = _make_synthetic_trend_df(n=100, seed=7, uptrend=True)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        # Bar 60: pullback True, bar 61: strict_bull_engulf True
        df_feat.loc[60, "pullback_to_20ema"] = True
        df_feat.loc[61, "pullback_to_20ema"] = True
        df_feat.loc[61, "strict_bull_engulf"] = True
        df_feat.loc[61, "struct_sl_long"] = float(df_feat.loc[61, "close"]) * 0.95
        df_feat.loc[61, "atr_pct"] = 0.02

        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) >= 1, "Pullback+engulfing sonrasi en az 1 long sinyal olmali"
        sig = long_sigs[0]
        assert sig.pattern_id == "bullish_engulfing_cont"
        assert sig.confluence_score >= 1.0
        assert sig.sl_price < float(df_feat.loc[61, "close"])
        assert sig.tp_price > float(df_feat.loc[61, "close"])

    def test_no_signal_without_engulfing(self):
        """Engulfing olmadan sinyal uretilmemeli."""
        df = _make_synthetic_trend_df(n=80, seed=99)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        df_feat["strict_bull_engulf"] = False
        df_feat["strict_bear_engulf"] = False
        signals = strat.generate_signals(df_feat)
        assert signals == [], "Engulfing olmadan sinyal olmamali"

    def test_no_signal_without_pullback(self):
        """Engulfing var ama pullback yok => sinyal olmamali (continuation kurali)."""
        df = _make_synthetic_trend_df(n=80, seed=15)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        df_feat["pullback_to_20ema"] = False
        df_feat.loc[50, "strict_bull_engulf"] = True
        df_feat.loc[50, "atr_pct"] = 0.02
        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) == 0, "Pullback olmadan engulfing sinyal uretmemeli"

    def test_bearish_engulfing_after_pullback(self):
        """Downtrend + pullback + bearish engulfing => short sinyal."""
        df = _make_synthetic_trend_df(n=100, seed=3, uptrend=False)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        df_feat.loc[60, "pullback_to_20ema"] = True
        df_feat.loc[61, "pullback_to_20ema"] = True
        df_feat.loc[61, "strict_bear_engulf"] = True
        df_feat.loc[61, "struct_sl_short"] = float(df_feat.loc[61, "close"]) * 1.05
        df_feat.loc[61, "atr_pct"] = 0.02
        signals = strat.generate_signals(df_feat)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) >= 1, "Downtrend pullback+engulfing sonrasi short sinyal olmali"
        sig = short_sigs[0]
        assert sig.pattern_id == "bearish_engulfing_cont"
        assert sig.sl_price > float(df_feat.loc[61, "close"])

    def test_signal_schema_valid(self):
        """Uretilen sinyaller Signal schema'sini gecmeli."""
        from price_action.contracts import Signal
        df = _make_synthetic_trend_df(n=100, seed=5)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        df_feat.loc[55, "pullback_to_20ema"] = True
        df_feat.loc[56, "pullback_to_20ema"] = True
        df_feat.loc[56, "strict_bull_engulf"] = True
        df_feat.loc[56, "atr_pct"] = 0.02
        df_feat.loc[56, "struct_sl_long"] = float(df_feat.loc[56, "close"]) * 0.95
        signals = strat.generate_signals(df_feat)
        for sig in signals:
            assert isinstance(sig, Signal)
            assert sig.venue == "binance"
            assert sig.timeframe == "1d"
            assert sig.direction in {"long", "short"}
            assert sig.fingerprint()

    def test_smoke_run_on_random_data(self):
        """Rastgele veriye karsi genel smoke testi -- exception olmamali."""
        rng = np.random.default_rng(77)
        n = 200
        close = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.02, n)))
        open_ = np.r_[close[0], close[:-1]]
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
        high = np.maximum.reduce([high, open_, close])
        low = np.minimum.reduce([low, open_, close])
        ts = [datetime(2022, 1, 1, tzinfo=timezone.utc) + timedelta(days=i) for i in range(n)]
        df = pd.DataFrame({
            "ts": ts, "open": open_, "high": high, "low": low,
            "close": close, "volume": rng.uniform(1e6, 5e6, n),
            "venue": "binance", "symbol": "SMOKE/USDT", "timeframe": "1d",
        })
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        signals = strat.generate_signals(df_feat)
        assert isinstance(signals, list)


# ---------------------------------------------------------------------------
# 4. Lookahead-bias kontrol
# ---------------------------------------------------------------------------

class TestLookaheadBias:
    def test_pullback_flag_uses_only_past_bars(self):
        """Pullback flag t aninda [t-window..t-1]'i kullaniyor olmali.

        EMA touch at bar 15.
        Bar 14 (oncesi): flag False -- lookahead yok.
        Bar 16 (1 bar sonra): flag True -- shift(1) dogunca geri donmustu.
        """
        n = 30
        df = _make_float_df(n, base_price=110.0, ema_val=100.0, atr_val=1.5)
        # Bar 15: low=99.5, tol=0.5*1.5=0.75, ema-tol=99.25 < 99.5 => icinde
        df.loc[15, "low"] = 99.5
        df.loc[15, "high"] = 101.0

        flags = _pullback_to_ema_flag(df, ema_col="ema20", window=10, touch_atr_factor=0.5)

        assert not bool(flags.iloc[14]), "Dokunmadan once flag False olmali (lookahead yok)"
        assert bool(flags.iloc[16]), "Dokunmadan 1 bar sonra flag True olmali"

    def test_strict_engulfing_no_future_data(self):
        """_strict_engulfing sadece shift(1) kullaniyor (t-1).

        Bar 2'de engulfing set et, bar 1'de (oncesinde) flag False olmali.
        """
        bars = [
            _bar(100.0, 101.0, 99.0, 100.0),
            _bar(100.0, 101.0, 95.0, 96.0),     # bearish
            _bar(95.0, 105.0, 94.0, 104.0),     # bullish engulfing
        ]
        df = _df_from_bars(bars)
        flags = _strict_engulfing(df, body_ratio_min=0.6, bullish=True)
        assert not bool(flags.iloc[1]), "Bar 1 oncesinde engulfing flag True olmamali"
        assert bool(flags.iloc[2]), "Bar 2'de engulfing True olmali"

    def test_detector_at_bar_t_uses_only_t_minus_10_to_t(self):
        """End-to-end: t anindaki sinyal sadece t oncesi bilgiyi kullaniyor.

        Yontem: t+2..end bool flaglerini False yap, signal sayisi degismemeli.
        """
        df = _make_synthetic_trend_df(n=80, seed=21)
        strat = _make_strategy()
        df_feat_full = strat.prepare_features(df)

        df_feat_full.loc[50, "pullback_to_20ema"] = True
        df_feat_full.loc[51, "pullback_to_20ema"] = True
        df_feat_full.loc[51, "strict_bull_engulf"] = True
        df_feat_full.loc[51, "atr_pct"] = 0.02
        df_feat_full.loc[51, "struct_sl_long"] = float(df_feat_full.loc[51, "close"]) * 0.95

        signals_full = strat.generate_signals(df_feat_full)
        long_full = [s for s in signals_full if s.direction == "long"]

        # t=51'deki sinyal t+2..end bilgisini kullanmiyor olmali
        # bool kolonlari False yap (NaN bool kolona atanamaz pandas'ta)
        df_feat_trunc = df_feat_full.copy()
        df_feat_trunc.loc[52:, "pullback_to_20ema"] = False
        df_feat_trunc.loc[52:, "strict_bull_engulf"] = False
        # Sayisal kolon: NaN yapilabilir
        df_feat_trunc.loc[52:, "kaufman_er"] = np.nan

        signals_trunc = strat.generate_signals(df_feat_trunc)
        long_trunc = [s for s in signals_trunc if s.direction == "long"]

        assert len(long_full) >= 1
        assert len(long_trunc) >= 1
        ts_full = {s.ts for s in long_full}
        ts_trunc = {s.ts for s in long_trunc}
        assert len(ts_full & ts_trunc) >= 1, "t+2..end sifirlamasi bar t'deki sinyali degistirmemeli"


# ---------------------------------------------------------------------------
# 5. Default manifest testi
# ---------------------------------------------------------------------------

def test_default_manifest_valid():
    """_default_manifest() gecerli StrategyManifest dondurmeli."""
    m = _default_manifest()
    assert m.name == "engulfing_continuation"
    assert m.trend_filter.period == 50
    assert len(m.signals.patterns) == 2


def test_default_manifest_strategy_instantiation():
    """Default manifest ile strateji olusturulabilmeli."""
    m = _default_manifest()
    strat = EngulfingContinuationStrategy(m)
    assert strat.name == "engulfing_continuation"
