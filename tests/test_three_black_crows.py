"""Unit testler -- ThreeBlackCrowsStrategy.

Test senaryolari (8 test):
  1. Pattern dedektoru: 3 iyi crow bar => True
  2. Pattern dedektoru: 2 crow bar yeterli degil => False
  3. Pattern dedektoru: Body ratio kucuk => False
  4. Pattern dedektoru: Alt golge cok buyuk => False
  5. Pattern dedektoru: Volume eskalasyonu yok => False
  6. 200-EMA filtresi: Close EMA altinda => short sinyal yok
  7. Uçtan uca: Sentetic pattern => short sinyal uretilmeli (SL/TP kontrolu)
  8. Smoke testi: Rastgele veri => exception yok, sadece short sinyaller
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.three_black_crows import (
    ThreeBlackCrowsStrategy,
    _three_black_crows,
    _pattern_stop,
    _default_manifest,
)


# ---------------------------------------------------------------------------
# Yardimci fabrika
# ---------------------------------------------------------------------------

def _base_ts(n: int) -> list[datetime]:
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def _bar(o: float, h: float, l: float, c: float, v: float = 1_000_000.0) -> dict:
    return {
        "open": float(o), "high": float(h),
        "low": float(l), "close": float(c), "volume": float(v)
    }


def _df_from_bars(
    bars: list[dict],
    venue: str = "binance",
    symbol: str = "TEST/USDT",
) -> pd.DataFrame:
    ts = _base_ts(len(bars))
    df = pd.DataFrame(bars)
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


def _make_strategy(require_ema200: bool = False) -> ThreeBlackCrowsStrategy:
    """Test manifest ile strateji olusturur."""
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "three_black_crows",
        "version": "0.0.1",
        "trend_filter": {"type": "ema", "period": 200, "required": require_ema200},
        "signals": {
            "patterns": [
                {
                    "id": "three_black_crows",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "body_ratio_min": 0.50,
                        "lower_shadow_max": 0.20,
                        "open_proximity_pct": 0.50,
                        "volume_escalation": True,
                        "vol_avg_window": 5,
                    },
                }
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
            "confluence": {"method": "weighted_sum", "min_score": 2.0, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "stop_loss": {"method": "pattern_high", "bar_lookback": 2},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
        },
    }
    manifest = StrategyManifest.model_validate(raw)
    return ThreeBlackCrowsStrategy(manifest)


def _crow_bar(base: float, size: float = 10.0, vol: float = 1_000_000.0) -> dict:
    """Iyi bir 'crow' bar olusturur.

    body = 80% range, alt golge = 10% range (her ikisi kurali karsiliyor).
    base = open, close = base - 0.8*size
    """
    o = base
    c = base - size * 0.80   # bearish body = 80% of range
    h = base + size * 0.05   # minimal upper shadow
    l = c - size * 0.10      # lower shadow = 10% of range (tolerable)
    return _bar(o, h, l, c, vol)


# ---------------------------------------------------------------------------
# Test 1: Iyi 3 crow bar => pattern True
# ---------------------------------------------------------------------------

class TestThreeBlackCrowsDetector:

    def test_three_good_crow_bars_detected(self):
        """3 gecerli crow bar art arda => son barda sinyal True."""
        warmup = [_bar(100, 102, 98, 101, 500_000) for _ in range(12)]
        # Bar1 @ 100, Bar2 @ 94 (closes lower), Bar3 @ 88 (closes lower)
        crow1 = _crow_bar(100.0, size=8.0, vol=1_000_000)
        crow2 = _crow_bar(93.0, size=8.0, vol=1_200_000)
        crow3 = _crow_bar(86.0, size=8.0, vol=1_500_000)
        bars = warmup + [crow1, crow2, crow3]
        df = _df_from_bars(bars)
        flags = _three_black_crows(
            df,
            body_ratio_min=0.50,
            lower_shadow_max=0.20,
            open_proximity_pct=0.60,
            volume_escalation=True,
            vol_avg_window=5,
        )
        assert bool(flags.iloc[-1]), "3 gecerli crow bar sonunda sinyal olmali"
        assert not bool(flags.iloc[-2]), "Onceki barda henuz ucuncu bar yok"

    def test_only_two_crow_bars_no_signal(self):
        """Sadece 2 crow bar varsa sinyal olmamali."""
        warmup = [_bar(100, 102, 98, 101, 500_000) for _ in range(12)]
        neutral = _bar(95, 97, 93, 96, 900_000)   # bullish/neutral — LL yok
        crow2 = _crow_bar(93.0, size=8.0, vol=1_200_000)
        crow3 = _crow_bar(86.0, size=8.0, vol=1_500_000)
        bars = warmup + [neutral, crow2, crow3]
        df = _df_from_bars(bars)
        flags = _three_black_crows(
            df,
            body_ratio_min=0.50,
            lower_shadow_max=0.20,
            open_proximity_pct=0.60,
            volume_escalation=True,
            vol_avg_window=5,
        )
        assert not bool(flags.iloc[-1]), "Ilk bar neutral ise sinyal olmamali"

    def test_low_body_ratio_rejected(self):
        """Body ratio < 0.5 olan bar => pattern False."""
        warmup = [_bar(100, 102, 98, 101, 500_000) for _ in range(12)]
        # range=20, body=4 => ratio=0.20 < 0.50
        bad_bar = _bar(100.0, 105.0, 85.0, 96.0, 1_000_000)
        crow2 = _crow_bar(94.0, size=8.0, vol=1_200_000)
        crow3 = _crow_bar(88.0, size=8.0, vol=1_500_000)
        bars = warmup + [bad_bar, crow2, crow3]
        df = _df_from_bars(bars)
        flags = _three_black_crows(
            df,
            body_ratio_min=0.50,
            lower_shadow_max=0.20,
            open_proximity_pct=0.60,
            volume_escalation=True,
            vol_avg_window=5,
        )
        assert not bool(flags.iloc[-1]), "Dusuk body_ratio birinci barda sinyal olmamali"

    def test_large_lower_shadow_rejected(self):
        """Alt golge > %20 range olan bar => pattern False."""
        warmup = [_bar(100, 102, 98, 101, 500_000) for _ in range(12)]
        # range=10, body=6 (60%), lower_shadow=3.5 => shadow_ratio=35% > 20%
        # open=100, close=94, low=90.5, high=100.5
        # lower_shadow = close - low = 94 - 90.5 = 3.5 / range(10) = 35%
        bad_bar = _bar(100.0, 100.5, 90.5, 94.0, 1_000_000)
        crow2 = _crow_bar(92.0, size=8.0, vol=1_200_000)
        crow3 = _crow_bar(85.0, size=8.0, vol=1_500_000)
        bars = warmup + [bad_bar, crow2, crow3]
        df = _df_from_bars(bars)
        flags = _three_black_crows(
            df,
            body_ratio_min=0.50,
            lower_shadow_max=0.20,
            open_proximity_pct=0.60,
            volume_escalation=True,
            vol_avg_window=5,
        )
        assert not bool(flags.iloc[-1]), "Buyuk alt golge olan bar pattern saglamali"

    def test_no_volume_escalation_rejected(self):
        """Volume eskalasyonu olmadan sinyal olmamali."""
        warmup = [_bar(100, 102, 98, 101, 500_000) for _ in range(12)]
        # Volume: 1.5M, 1.0M, 0.8M — azalan, artmayan
        crow1 = _crow_bar(100.0, size=8.0, vol=1_500_000)
        crow2 = _crow_bar(93.0, size=8.0, vol=1_000_000)
        crow3 = _crow_bar(86.0, size=8.0, vol=800_000)
        bars = warmup + [crow1, crow2, crow3]
        df = _df_from_bars(bars)
        flags = _three_black_crows(
            df,
            body_ratio_min=0.50,
            lower_shadow_max=0.20,
            open_proximity_pct=0.60,
            volume_escalation=True,
            vol_avg_window=5,
        )
        assert not bool(flags.iloc[-1]), "Azalan volume ile sinyal olmamali"


# ---------------------------------------------------------------------------
# Test 6: 200-EMA filtresi
# ---------------------------------------------------------------------------

class TestEmaFilter:

    def test_close_below_200ema_no_short_signal(self):
        """Close 200-EMA altinda oldugunda short sinyal uretilmemeli."""
        strat = _make_strategy(require_ema200=True)
        n = 220

        rng = np.random.default_rng(42)
        # Downtrend: close will be below any 200-EMA
        close = 50.0 * np.exp(np.cumsum(rng.normal(-0.002, 0.015, n)))
        open_ = np.r_[close[0], close[:-1]]
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
        high = np.maximum.reduce([high, open_, close])
        low = np.minimum.reduce([low, open_, close])
        ts = _base_ts(n)
        df = pd.DataFrame({
            "ts": ts, "open": open_, "high": high, "low": low,
            "close": close, "volume": rng.uniform(8e5, 2e6, n),
            "venue": "binance", "symbol": "BEAR/USDT", "timeframe": "1d",
        })
        df_feat = strat.prepare_features(df)
        # Force some pattern signals
        df_feat.loc[150, "tbc_signal"] = True
        df_feat.loc[150, "tbc_stop"] = float(df_feat.loc[150, "close"]) * 1.05

        signals = strat.generate_signals(df_feat)
        # All signals where ema200 filter is active should produce no signal when close < ema200
        # Check: at bar 150, close is below ema200 (downtrend), so no signal at that bar
        sig_at_150 = [
            s for s in signals
            if pd.Timestamp(s.ts) == pd.Timestamp(df_feat.loc[150, "ts"])
        ]
        # The close at bar 150 should be below ema200 since we're in a deep downtrend from 50
        # Verify no signal was generated at that point (it would pass if below EMA200)
        ema200_val = float(df_feat.loc[150, "ema200"])
        close_val = float(df_feat.loc[150, "close"])
        if close_val <= ema200_val:
            assert len(sig_at_150) == 0, "Close EMA200 altinda short sinyal olmamali"


# ---------------------------------------------------------------------------
# Test 7: End-to-end short sinyal uretimi
# ---------------------------------------------------------------------------

class TestEndToEnd:

    def test_synthetic_pattern_produces_short_signal(self):
        """Synthetic three black crows => en az bir short sinyal."""
        strat = _make_strategy(require_ema200=False)
        n = 100

        rng = np.random.default_rng(7)
        # Uptrend (so 200-EMA filter off; close > EMA makes sense for distribution)
        close = 120.0 * np.exp(np.cumsum(rng.normal(0.002, 0.012, n)))
        open_ = np.r_[close[0], close[:-1]]
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
        high = np.maximum.reduce([high, open_, close])
        low = np.minimum.reduce([low, open_, close])
        ts = _base_ts(n)
        df = pd.DataFrame({
            "ts": ts, "open": open_, "high": high, "low": low,
            "close": close, "volume": rng.uniform(8e5, 2e6, n),
            "venue": "binance", "symbol": "TEST/USDT", "timeframe": "1d",
        })
        df_feat = strat.prepare_features(df)

        # Inject a clean pattern at bar 70
        base = float(df_feat.loc[70, "close"])
        size = base * 0.05  # 5% range per bar

        # Bar1 (idx 68), Bar2 (idx 69), Bar3 (idx 70)
        o1 = base + 2 * size
        c1 = o1 - size * 0.80
        h1 = o1 + size * 0.05
        l1 = c1 - size * 0.10
        v1 = 1_200_000.0

        o2 = c1 + size * 0.10   # opens near bar1 close
        c2 = o2 - size * 0.80
        h2 = o2 + size * 0.05
        l2 = c2 - size * 0.10
        v2 = 1_500_000.0

        o3 = c2 + size * 0.10
        c3 = o3 - size * 0.80
        h3 = o3 + size * 0.05
        l3 = c3 - size * 0.10
        v3 = 1_800_000.0

        df_feat.loc[68, ["open", "high", "low", "close", "volume"]] = [o1, h1, l1, c1, v1]
        df_feat.loc[69, ["open", "high", "low", "close", "volume"]] = [o2, h2, l2, c2, v2]
        df_feat.loc[70, ["open", "high", "low", "close", "volume"]] = [o3, h3, l3, c3, v3]

        # Recompute pattern signal on modified data
        flags = _three_black_crows(
            df_feat,
            body_ratio_min=0.50,
            lower_shadow_max=0.20,
            open_proximity_pct=0.60,
            volume_escalation=True,
            vol_avg_window=5,
        )
        df_feat["tbc_signal"] = flags
        df_feat["tbc_stop"] = _pattern_stop(df_feat)

        signals = strat.generate_signals(df_feat)
        short_signals = [s for s in signals if s.direction == "short"]
        assert len(short_signals) >= 1, "Pattern sonrasi en az 1 short sinyal olmali"

        sig = short_signals[0]
        assert sig.pattern_id == "three_black_crows"
        assert sig.direction == "short"
        assert sig.sl_price > sig.tp_price, "Short: SL > close > TP"
        assert sig.confluence_score >= 2.0

    def test_only_short_signals_generated(self):
        """Bu strateji SADECE short sinyal uretmeli."""
        strat = _make_strategy(require_ema200=False)
        n = 150
        rng = np.random.default_rng(99)
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, n)))
        open_ = np.r_[close[0], close[:-1]]
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.006, n)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.006, n)))
        high = np.maximum.reduce([high, open_, close])
        low = np.minimum.reduce([low, open_, close])
        ts = _base_ts(n)
        df = pd.DataFrame({
            "ts": ts, "open": open_, "high": high, "low": low,
            "close": close, "volume": rng.uniform(8e5, 3e6, n),
            "venue": "binance", "symbol": "SMOKE/USDT", "timeframe": "1d",
        })
        df_feat = strat.prepare_features(df)
        signals = strat.generate_signals(df_feat)
        long_signals = [s for s in signals if s.direction == "long"]
        assert len(long_signals) == 0, "Three Black Crows sadece short sinyal uretmeli"

    def test_smoke_no_exception(self):
        """Rastgele veri icin exception atilmamali."""
        strat = _make_strategy(require_ema200=False)
        rng = np.random.default_rng(55)
        n = 250
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.001, 0.018, n)))
        open_ = np.r_[close[0], close[:-1]]
        high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.005, n)))
        low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.005, n)))
        high = np.maximum.reduce([high, open_, close])
        low = np.minimum.reduce([low, open_, close])
        ts = _base_ts(n)
        df = pd.DataFrame({
            "ts": ts, "open": open_, "high": high, "low": low,
            "close": close, "volume": rng.uniform(5e5, 5e6, n),
            "venue": "binance", "symbol": "RAND/USDT", "timeframe": "1d",
        })
        df_feat = strat.prepare_features(df)
        signals = strat.generate_signals(df_feat)
        assert isinstance(signals, list)
        for sig in signals:
            assert sig.direction == "short"
            assert sig.sl_price > sig.tp_price


# ---------------------------------------------------------------------------
# Default manifest testi
# ---------------------------------------------------------------------------

def test_default_manifest_valid():
    """_default_manifest() gecerli StrategyManifest dondurmeli."""
    m = _default_manifest()
    assert m.name == "three_black_crows"
    assert m.trend_filter.period == 200
    assert m.trend_filter.required is True
    assert len(m.signals.patterns) == 1
    assert m.signals.patterns[0].id == "three_black_crows"


def test_default_manifest_instantiation():
    """Default manifest ile strateji olusturulabilmeli."""
    m = _default_manifest()
    strat = ThreeBlackCrowsStrategy(m)
    assert strat.name == "three_black_crows"
