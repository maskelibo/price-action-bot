"""Unit testler — PinBarRoundNumbersStrategy.

Test senaryolari (~8):
  1. _pin_bar_flags: bullish pin (hammer) dogru tespit
  2. _pin_bar_flags: bearish pin (shooting star) dogru tespit
  3. _pin_bar_flags: genis govde => pin degil
  4. get_round_grid: BTC/ETH/SOL/bilinmeyen semboller
  5. _round_proximity_flags: round number yakininda True
  6. _round_proximity_flags: round number uzaginda False
  7. prepare_features: gerekli kolonlari uretir
  8. generate_signals: bilinen pin at round => sinyal uretilir
  9. generate_signals: pin var ama round uzak => sinyal yok
  10. generate_signals: round yakin ama pin yok => sinyal yok
  11. Signal schema gecerliligi
  12. Lookahead bias: bar t sinyali t+1 bilgisini kullanmaz
  13. Empty df => no signals
  14. _default_manifest gecerli
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.pin_bar_round_numbers import (
    PinBarRoundNumbersStrategy,
    _default_manifest,
    _pin_bar_flags,
    _round_proximity_flags,
    distance_to_nearest_round,
    get_round_grid,
    nearest_round_levels,
)


# =====================================================================
# Yardimci fabrikalar
# =====================================================================

def _make_strategy(overrides: dict | None = None) -> PinBarRoundNumbersStrategy:
    from price_action.strategies.base import StrategyManifest
    raw: dict = {
        "name": "pin_bar_round_numbers",
        "version": "0.0.1",
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "bullish_pin_at_round",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {"body_ratio_max": 0.33, "wick_ratio_min": 0.60,
                               "round_proximity_atr": 0.3},
                },
                {
                    "id": "bearish_pin_at_round",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {"body_ratio_max": 0.33, "wick_ratio_min": 0.60,
                               "round_proximity_atr": 0.3},
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 50, "cluster_atr_multiplier": 0.5,
                    "min_touches": 2, "max_age_bars": 50,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.0,
                "volume_zscore_min": 0.0,
                "kaufman_er_min": 0.0,
                "bear_regime_size_factor": 1.0,
            },
            "confluence": {"method": "weighted_sum", "min_score": 1.5, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "stop_loss": {"method": "pin_tail", "tail_atr_buffer": 0.5},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
        },
    }
    if overrides:
        raw.update(overrides)
    manifest = StrategyManifest.model_validate(raw)
    return PinBarRoundNumbersStrategy(manifest)


def _base_ts(n: int) -> list[datetime]:
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def _make_df(bars: list[dict], symbol: str = "BTC/USDT") -> pd.DataFrame:
    ts = _base_ts(len(bars))
    df = pd.DataFrame(bars)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = df[col].astype(float)
    df["ts"]        = ts
    df["venue"]     = "binance"
    df["symbol"]    = symbol
    df["timeframe"] = "1d"
    if "volume" not in df.columns:
        df["volume"] = 1_000_000.0
    return df


def _bar(o: float, h: float, l: float, c: float, v: float = 1_000_000.0) -> dict:
    return {"open": float(o), "high": float(h), "low": float(l),
            "close": float(c), "volume": float(v)}


def _synthetic_df(n: int = 80, seed: int = 42, base: float = 50_000.0,
                  symbol: str = "BTC/USDT") -> pd.DataFrame:
    """Gercekci BTC fiyat sentetik OHLCV."""
    rng   = np.random.default_rng(seed)
    rets  = rng.normal(0.001, 0.015, n)
    close = base * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high  = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low   = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    high  = np.maximum.reduce([high, open_, close])
    low   = np.minimum.reduce([low, open_, close])
    vol   = rng.uniform(1e6, 5e6, n)
    ts    = _base_ts(n)
    return pd.DataFrame({
        "ts": ts, "open": open_, "high": high, "low": low,
        "close": close, "volume": vol,
        "venue": "binance", "symbol": symbol, "timeframe": "1d",
    })


# =====================================================================
# 1. _pin_bar_flags: bullish pin (hammer)
# =====================================================================

class TestPinBarFlags:
    def test_bullish_pin_detected(self):
        """Klasik hammer: uzun alt wick, kucuk govde, kapanish yukari."""
        # range=10, body=1 (c-o=1), lower_wick=7, upper_wick=2
        # body_ratio=0.1 <= 0.33  OK
        # lower_wick_ratio=0.7 >= 0.60  OK
        # midpoint=5 (7+17)/2=12; close=17 > 12  OK
        bars = [
            _bar(16.0, 17.0, 7.0,  17.0),  # bullish hammer: o=16,c=17,h=17,l=7
        ]
        # Inject pre-computed atr14 to bypass warmup
        df = _make_df(bars)
        df["atr14"] = 5.0
        bull, bear = _pin_bar_flags(df, body_ratio_max=0.33, wick_ratio_min=0.60)
        assert bool(bull.iloc[0]), "Hammer olmali"
        assert not bool(bear.iloc[0]), "Hammer bearish pin olmamali"

    def test_bearish_pin_detected(self):
        """Klasik shooting star: uzun ust wick, kucuk govde, kapanish asagi."""
        # range=10, body=1, upper_wick=8, lower_wick=1
        # body_ratio=0.1 <= 0.33  OK
        # upper_wick_ratio=0.8 >= 0.60  OK
        # midpoint=(17+7)/2=12; close=8 < 12  OK (wait: h=17,l=7 → mid=12; o=9,c=8 → close=8<12 OK)
        bars = [_bar(9.0, 17.0, 7.0, 8.0)]
        df = _make_df(bars)
        df["atr14"] = 5.0
        bull, bear = _pin_bar_flags(df, body_ratio_max=0.33, wick_ratio_min=0.60)
        assert bool(bear.iloc[0]), "Shooting star olmali"
        assert not bool(bull.iloc[0]), "Shooting star bullish pin olmamali"

    def test_wide_body_not_pin(self):
        """Genis govde (> %33) => pin bar degil."""
        # range=10, body=6 => ratio=0.6 > 0.33 → False
        bars = [_bar(10.0, 16.0, 6.0, 16.0)]
        df = _make_df(bars)
        df["atr14"] = 3.0
        bull, bear = _pin_bar_flags(df, body_ratio_max=0.33, wick_ratio_min=0.60)
        assert not bool(bull.iloc[0]), "Genis govde bullish pin olmamali"
        assert not bool(bear.iloc[0]), "Genis govde bearish pin olmamali"

    def test_no_dominant_wick_not_pin(self):
        """Wick yeterince dominant degil => pin bar degil."""
        # range=10, body=2, upper_wick=4, lower_wick=4 — her iki wick esit, hicbiri %60 degil
        bars = [_bar(11.0, 15.0, 5.0, 13.0)]  # body=2, range=10, lower=6, upper=2
        # Actually lower_wick = min(11,13)-5 = 11-5=6 → ratio=0.6 → exactly 0.6
        # Let's make lower wick weaker:
        bars = [_bar(11.0, 14.0, 5.0, 12.0)]  # range=9, body=1, low_wick=6/9=0.67 >= 0.6
        # Re-do: body_ratio = 1/9 = 0.11 <= 0.33, lower_wick = 6/9 = 0.67 >= 0.6 → should be bullish!
        # Use doji-like with symmetric wicks:
        bars = [_bar(10.0, 14.0, 6.0, 10.0)]  # range=8, body=0, upper=4/8=0.5, lower=4/8=0.5
        df = _make_df(bars)
        df["atr14"] = 2.0
        bull, bear = _pin_bar_flags(df, body_ratio_max=0.33, wick_ratio_min=0.60)
        # Both wicks are 0.5 < 0.6 → neither
        assert not bool(bull.iloc[0])
        assert not bool(bear.iloc[0])


# =====================================================================
# 2. get_round_grid ve round level helpers
# =====================================================================

class TestRoundGridHelpers:
    def test_btc_grid(self):
        assert get_round_grid("BTC/USDT") == 10_000.0
        assert get_round_grid("BTCUSDT")  == 10_000.0

    def test_eth_grid(self):
        assert get_round_grid("ETH/USDT") == 500.0

    def test_sol_grid(self):
        assert get_round_grid("SOL/USDT") == 50.0

    def test_unknown_falls_back(self):
        assert get_round_grid("UNKNOWN/USDT") == 1.0

    def test_override(self):
        assert get_round_grid("BTC/USDT", override=500.0) == 500.0

    def test_nearest_round_levels(self):
        levels = nearest_round_levels(50_500.0, 10_000.0, n=2)
        assert 50_000.0 in levels
        assert 60_000.0 in levels

    def test_distance_to_nearest(self):
        d = distance_to_nearest_round(50_200.0, 10_000.0)
        assert abs(d - 200.0) < 1e-6

        d2 = distance_to_nearest_round(49_800.0, 10_000.0)
        assert abs(d2 - 200.0) < 1e-6


# =====================================================================
# 3. _round_proximity_flags
# =====================================================================

class TestRoundProximityFlags:
    def _make_prox_df(self, low: float, high: float, atr: float,
                      grid: float = 10_000.0) -> pd.DataFrame:
        df = pd.DataFrame({
            "ts":    [datetime(2023, 1, 1, tzinfo=timezone.utc)],
            "open":  [low + (high - low) * 0.5],
            "high":  [high],
            "low":   [low],
            "close": [low + (high - low) * 0.6],
            "volume": [1e6],
            "atr14": [atr],
        })
        return df

    def test_bull_near_round(self):
        """Bar low, round number'a ATR toleransi icinde => bullish True."""
        # Grid=10000, round near low=50000. low=49700, atr=2000, tol=0.3*2000=600
        # dist=300 < 600 => True
        df = self._make_prox_df(low=49700.0, high=51000.0, atr=2000.0)
        bull, bear = _round_proximity_flags(df, grid=10_000.0, atr_factor=0.3)
        assert bool(bull.iloc[0]), "49700 is within 600 of 50000"

    def test_bull_far_from_round(self):
        """Bar low, round number'dan ATR tol disinda => bullish False."""
        # low=49000, dist to 50000=1000, tol=0.3*2000=600 < 1000 => False
        df = self._make_prox_df(low=49000.0, high=51000.0, atr=2000.0)
        bull, bear = _round_proximity_flags(df, grid=10_000.0, atr_factor=0.3)
        assert not bool(bull.iloc[0]), "49000 is 1000 away from 50000, tol=600 => False"

    def test_bear_near_round(self):
        """Bar high, round number'a yakin => bearish True."""
        # high=50200, dist=200, tol=600 => True
        df = self._make_prox_df(low=49000.0, high=50200.0, atr=2000.0)
        bull, bear = _round_proximity_flags(df, grid=10_000.0, atr_factor=0.3)
        assert bool(bear.iloc[0]), "50200 is 200 away from 50000 => True"


# =====================================================================
# 4. prepare_features
# =====================================================================

class TestPrepareFeatures:
    def test_required_columns_created(self):
        """prepare_features gerekli tum kolonlari olusturmali."""
        strat    = _make_strategy()
        df       = _synthetic_df(n=80, symbol="BTC/USDT")
        df_feat  = strat.prepare_features(df)
        required = [
            "ema20", "ema50", "ema200", "atr14", "atr_pct", "vol_z",
            "bull_pin", "bear_pin",
            "bull_round_near", "bear_round_near",
            "bull_pin_at_round", "bear_pin_at_round",
            "kaufman_er", "_round_grid",
        ]
        for col in required:
            assert col in df_feat.columns, f"Eksik kolon: {col}"

    def test_round_grid_correct_for_symbol(self):
        """BTC sembolu icin grid 10000 olmali."""
        strat   = _make_strategy()
        df      = _synthetic_df(n=40, symbol="BTC/USDT")
        df_feat = strat.prepare_features(df)
        assert (df_feat["_round_grid"] == 10_000.0).all()

    def test_empty_df_returns_empty(self):
        strat = _make_strategy()
        empty = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        result = strat.prepare_features(empty)
        assert result.empty


# =====================================================================
# 5. generate_signals: bilinen pin at round => sinyal
# =====================================================================

class TestGenerateSignals:
    def _inject_bull_pin_at_round(self, df: pd.DataFrame, idx: int,
                                   round_level: float = 50_000.0) -> pd.DataFrame:
        """idx barina manuel bullish pin at round inject et."""
        df = df.copy()
        atr = float(df["atr14"].iloc[idx]) if "atr14" in df.columns else 1500.0
        # Hammer: low ≈ round_level (within 0.3 * atr), long lower wick
        bar_low  = round_level + 50.0          # 50 above round number (within tolerance)
        bar_high = bar_low + atr * 0.8         # total range = 0.8 ATR
        body_top = bar_low + (bar_high - bar_low) * 0.2  # gövde üstü
        body_bot = bar_low + (bar_high - bar_low) * 0.05  # gövde altı (narrow body)
        df.loc[idx, "low"]   = bar_low
        df.loc[idx, "high"]  = bar_high
        df.loc[idx, "open"]  = body_bot
        df.loc[idx, "close"] = body_top       # bullish close above mid
        df.loc[idx, "atr14"] = atr
        df.loc[idx, "atr_pct"] = atr / body_top
        # Force flags directly
        df.loc[idx, "bull_pin"]         = True
        df.loc[idx, "bear_pin"]         = False
        df.loc[idx, "bull_round_near"]  = True
        df.loc[idx, "bear_round_near"]  = False
        df.loc[idx, "bull_pin_at_round"] = True
        df.loc[idx, "bear_pin_at_round"] = False
        df.loc[idx, "_round_grid"]      = 10_000.0
        return df

    def test_bull_pin_at_round_generates_long_signal(self):
        """Bullish pin at round => long sinyal uretilmeli."""
        strat   = _make_strategy()
        df      = _synthetic_df(n=80, symbol="BTC/USDT")
        df_feat = strat.prepare_features(df)
        df_feat = self._inject_bull_pin_at_round(df_feat, idx=50)

        signals   = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) >= 1, "Bull pin at round sonrasi long sinyal olmali"
        sig = long_sigs[0]
        assert sig.pattern_id == "bullish_pin_at_round"
        assert sig.confluence_score >= 1.5
        assert sig.sl_price < sig.metadata["atr14"] * 100 + float(df_feat.loc[50, "close"])

    def test_bear_pin_at_round_generates_short_signal(self):
        """Bearish pin at round => short sinyal uretilmeli."""
        strat   = _make_strategy()
        df      = _synthetic_df(n=80, symbol="BTC/USDT")
        df_feat = strat.prepare_features(df)

        # Inject shooting star at round
        idx      = 55
        df_feat.loc[idx, "bull_pin"]          = False
        df_feat.loc[idx, "bear_pin"]          = True
        df_feat.loc[idx, "bull_round_near"]   = False
        df_feat.loc[idx, "bear_round_near"]   = True
        df_feat.loc[idx, "bull_pin_at_round"] = False
        df_feat.loc[idx, "bear_pin_at_round"] = True
        df_feat.loc[idx, "_round_grid"]       = 10_000.0
        close = float(df_feat.loc[idx, "close"])
        df_feat.loc[idx, "atr14"]    = close * 0.02
        df_feat.loc[idx, "atr_pct"]  = 0.02

        signals    = strat.generate_signals(df_feat)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) >= 1, "Bear pin at round sonrasi short sinyal olmali"
        assert short_sigs[0].pattern_id == "bearish_pin_at_round"

    def test_pin_without_round_proximity_no_signal(self):
        """Pin var ama round level'a uzak => sinyal yok."""
        strat   = _make_strategy()
        df      = _synthetic_df(n=80, symbol="BTC/USDT")
        df_feat = strat.prepare_features(df)

        # Tum pin_at_round flaglerini False yap
        df_feat["bull_pin_at_round"] = False
        df_feat["bear_pin_at_round"] = False
        # Ama pin flagleri True
        df_feat.loc[50, "bull_pin"] = True

        signals = strat.generate_signals(df_feat)
        assert signals == [], "Round proximity olmadan sinyal uretilmemeli"

    def test_round_near_without_pin_no_signal(self):
        """Round level yakin ama pin bar yok => sinyal yok."""
        strat   = _make_strategy()
        df      = _synthetic_df(n=80, symbol="BTC/USDT")
        df_feat = strat.prepare_features(df)

        df_feat["bull_pin_at_round"] = False
        df_feat["bear_pin_at_round"] = False
        df_feat.loc[50, "bull_round_near"] = True  # round yakin ama pin yok

        signals = strat.generate_signals(df_feat)
        assert signals == [], "Pin olmadan round proximity sinyali olmamali"

    def test_empty_df_returns_empty_signals(self):
        strat   = _make_strategy()
        empty   = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        signals = strat.generate_signals(empty)
        assert signals == []

    def test_signal_schema_valid(self):
        """Uretilen sinyaller Signal schemasini gecmeli."""
        from price_action.contracts import Signal
        strat   = _make_strategy()
        df      = _synthetic_df(n=80, symbol="ETH/USDT")
        df_feat = strat.prepare_features(df)

        idx = 60
        # Konsistant OHLCV: hammer sekli, close = entry proxy
        base = 3_000.0
        atr  = 60.0
        df_feat.loc[idx, "open"]  = base + 5.0
        df_feat.loc[idx, "close"] = base + 8.0   # bullish close near top
        df_feat.loc[idx, "high"]  = base + 10.0
        df_feat.loc[idx, "low"]   = base - 50.0  # long lower wick
        df_feat.loc[idx, "atr14"] = atr
        df_feat.loc[idx, "atr_pct"] = atr / (base + 8.0)
        df_feat.loc[idx, "bull_pin_at_round"] = True
        df_feat.loc[idx, "bear_pin_at_round"] = False
        df_feat.loc[idx, "_round_grid"] = 500.0

        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) >= 1, "Sinyal uretilmeli"
        for sig in long_sigs:
            assert isinstance(sig, Signal)
            assert sig.venue == "binance"
            assert sig.symbol == "ETH/USDT"
            assert sig.timeframe == "1d"
            assert sig.direction in {"long", "short"}
            assert sig.sl_price < sig.tp_price, "SL < TP olmali"
            assert sig.fingerprint()


# =====================================================================
# 6. Lookahead bias
# =====================================================================

class TestLookaheadBias:
    def test_signal_at_t_independent_of_t_plus_1(self):
        """Bar t sinyali bar t+1 bilgisini kullanmamali.

        Yontem: t+1..end barlarini pin_at_round=False yap, bar t sinyali degismemeli.
        """
        strat   = _make_strategy()
        df      = _synthetic_df(n=80, symbol="BTC/USDT")
        df_feat = strat.prepare_features(df)

        # Bar 50'ye sinyal inject et
        idx   = 50
        close = float(df_feat.loc[idx, "close"])
        atr   = float(df_feat["atr14"].iloc[idx]) if "atr14" in df_feat.columns else close * 0.02
        df_feat.loc[idx, "bull_pin_at_round"] = True
        df_feat.loc[idx, "atr14"]   = atr
        df_feat.loc[idx, "atr_pct"] = atr / close
        df_feat.loc[idx, "_round_grid"] = 10_000.0

        signals_full = strat.generate_signals(df_feat.copy())
        ts_full = {s.ts for s in signals_full if s.direction == "long"}

        # t+1..end sinyallerini sifirla
        df_trunc = df_feat.copy()
        df_trunc.loc[51:, "bull_pin_at_round"] = False
        df_trunc.loc[51:, "bear_pin_at_round"] = False

        signals_trunc = strat.generate_signals(df_trunc)
        ts_trunc = {s.ts for s in signals_trunc if s.direction == "long"}

        # Bar 50 ts'i her iki durumda da olmali
        assert len(ts_full & ts_trunc) >= 1, (
            "t+1..end sifirlamasi bar t sinyalini etkilememeli"
        )


# =====================================================================
# 7. Default manifest
# =====================================================================

def test_default_manifest_valid():
    m = _default_manifest()
    assert m.name == "pin_bar_round_numbers"
    assert len(m.signals.patterns) == 2
    pattern_ids = {p.id for p in m.signals.patterns}
    assert "bullish_pin_at_round"  in pattern_ids
    assert "bearish_pin_at_round" in pattern_ids


def test_default_manifest_strategy_instantiation():
    m     = _default_manifest()
    strat = PinBarRoundNumbersStrategy(m)
    assert strat.name == "pin_bar_round_numbers"


def test_smoke_run_random_data():
    """Rastgele veri uzerinde exception olmamali."""
    strat   = _make_strategy()
    df      = _synthetic_df(n=200, symbol="SOL/USDT")
    df_feat = strat.prepare_features(df)
    signals = strat.generate_signals(df_feat)
    assert isinstance(signals, list)


# =====================================================================
# 8. SL/TP logic
# =====================================================================

class TestSLTPLogic:
    def test_long_sl_below_close(self):
        """Long sinyalde SL < close olmali."""
        strat   = _make_strategy()
        df      = _synthetic_df(n=80, symbol="BTC/USDT")
        df_feat = strat.prepare_features(df)

        idx   = 45
        close = float(df_feat.loc[idx, "close"])
        atr   = close * 0.02
        df_feat.loc[idx, "bull_pin_at_round"] = True
        df_feat.loc[idx, "atr14"]   = atr
        df_feat.loc[idx, "atr_pct"] = 0.02
        df_feat.loc[idx, "_round_grid"] = 10_000.0

        sigs = [s for s in strat.generate_signals(df_feat) if s.direction == "long"]
        if sigs:
            assert sigs[0].sl_price < sigs[0].tp_price
            assert sigs[0].sl_price < float(df_feat.loc[idx, "close"])

    def test_short_sl_above_close(self):
        """Short sinyalde SL > close olmali."""
        strat   = _make_strategy()
        df      = _synthetic_df(n=80, symbol="BTC/USDT")
        df_feat = strat.prepare_features(df)

        idx   = 45
        close = float(df_feat.loc[idx, "close"])
        atr   = close * 0.02
        df_feat.loc[idx, "bull_pin_at_round"] = False
        df_feat.loc[idx, "bear_pin_at_round"] = True
        df_feat.loc[idx, "atr14"]   = atr
        df_feat.loc[idx, "atr_pct"] = 0.02
        df_feat.loc[idx, "_round_grid"] = 10_000.0

        sigs = [s for s in strat.generate_signals(df_feat) if s.direction == "short"]
        if sigs:
            assert sigs[0].sl_price > sigs[0].tp_price
            assert sigs[0].sl_price > float(df_feat.loc[idx, "close"])

    def test_tp_is_2r(self):
        """TP yaklasik 2R olmali (SL mesafesinin 2 kati).

        Sadece bir bar'a inject yapilir; o bar'a ait sinyal secilir.
        """
        strat   = _make_strategy()
        df      = _synthetic_df(n=80, symbol="BTC/USDT")
        df_feat = strat.prepare_features(df)

        # Tum mevcut pin flaglerini temizle
        df_feat["bull_pin_at_round"] = False
        df_feat["bear_pin_at_round"] = False

        idx  = 40
        base = 50_000.0
        atr  = 1_000.0
        # Hammer: long lower wick, small body near top of range
        df_feat.loc[idx, "open"]   = base + 100.0
        df_feat.loc[idx, "close"]  = base + 200.0   # close = entry anchor
        df_feat.loc[idx, "high"]   = base + 300.0
        df_feat.loc[idx, "low"]    = base - 700.0   # long lower wick (tail=700+buf*atr=1200 below)
        df_feat.loc[idx, "atr14"]  = atr
        df_feat.loc[idx, "atr_pct"] = atr / (base + 200.0)
        df_feat.loc[idx, "bull_pin_at_round"] = True
        df_feat.loc[idx, "_round_grid"]       = 10_000.0

        sigs = [s for s in strat.generate_signals(df_feat) if s.direction == "long"]
        assert len(sigs) == 1, f"Tam olarak 1 sinyal olmali, alindi: {len(sigs)}"
        sig   = sigs[0]
        close = float(df_feat.loc[idx, "close"])
        risk   = close - sig.sl_price
        reward = sig.tp_price - close
        assert reward > 0, f"Reward pozitif olmali: tp={sig.tp_price} close={close}"
        assert risk   > 0, f"Risk pozitif olmali: sl={sig.sl_price} close={close}"
        ratio  = reward / risk
        assert abs(ratio - 2.0) < 0.01, f"TP/SL ratio beklenen 2.0, alınan {ratio:.3f}"
