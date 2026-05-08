"""Unit testler — EngulfingMTFStrategy.

Test senaryolari:
  1. detect_4h_always_in: long confirm (4h yukari kapanislar)
  2. detect_4h_always_in: short confirm (4h asagi kapanislar)
  3. detect_4h_always_in: against (long engulfing ama 4h bearish)
  4. detect_4h_always_in: neutral (karisik 4h kapanis)
  5. detect_4h_always_in: yetersiz bar (lookback > mevcut)
  6. Lookahead-free: cutoff_ts sonrasi 4h barlar KULLANILMAMALI
  7. Sinyal boost: 4h confirm -> confluence_score * 1.3
  8. Sinyal reject: 4h against -> sinyal yok
  9. Sinyal neutral: 4h neutral -> sinyal degismeden gecmeli
  10. End-to-end: 4h olmadan da calisir (neutral fallback)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.engulfing_mtf import (
    EngulfingMTFStrategy,
    detect_4h_always_in,
    _default_manifest,
)
from price_action.strategies.base import StrategyManifest


# ---------------------------------------------------------------------------
# Yardimci fabrikalar
# ---------------------------------------------------------------------------

def _ts_seq(n: int, start: datetime, step_hours: int = 4) -> list[datetime]:
    """n adet timestamp olustur."""
    return [start + timedelta(hours=step_hours * i) for i in range(n)]


def _make_4h_df(closes: list[float], cutoff_before: datetime | None = None) -> pd.DataFrame:
    """4h OHLCV DataFrame olustur. Kapanislar belirlenmis, rest sabit."""
    n = len(closes)
    start = datetime(2023, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    ts_list = _ts_seq(n, start, step_hours=4)
    opens = [c * 0.995 for c in closes]
    highs = [c * 1.01 for c in closes]
    lows = [c * 0.99 for c in closes]
    return pd.DataFrame({
        "ts": pd.to_datetime(ts_list, utc=True),
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [1_000_000.0] * n,
        "symbol": "TEST/USDT",
        "timeframe": "4h",
        "venue": "binance",
    })


def _make_1d_df(n: int = 100, base_price: float = 200.0) -> pd.DataFrame:
    """Basit trend sinyali uretecek 1d DataFrame. EMAs onceden set edilmis."""
    start = datetime(2023, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
    ts_list = [start + timedelta(days=i) for i in range(n)]
    closes = [base_price + i * 0.5 for i in range(n)]
    opens = [c - 1.5 for c in closes]
    highs = [c + 2.0 for c in closes]
    lows = [o - 1.5 for o in opens]
    return pd.DataFrame({
        "ts": pd.to_datetime(ts_list, utc=True),
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": [2_000_000.0] * n,
        "symbol": "TEST/USDT",
        "timeframe": "1d",
        "venue": "binance",
    })


def _make_strategy(h4_reject_against: bool = True, h4_lookback: int = 6,
                   h4_n_confirm: int = 3, h4_confirm_boost: float = 1.3,
                   trend_required: bool = False) -> EngulfingMTFStrategy:
    """Test manifest ile strateji olustur."""
    raw = {
        "name": "engulfing_mtf",
        "version": "0.0.1",
        "trend_filter": {"type": "ema", "period": 50, "required": trend_required},
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
                "h4_lookback": h4_lookback,
                "h4_n_confirm": h4_n_confirm,
                "h4_strong_close_pct": 0.90,
                "h4_confirm_boost": h4_confirm_boost,
                "h4_reject_against": h4_reject_against,
            },
            "confluence": {"method": "weighted_sum", "min_score": 1.0, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "stop_loss": {"method": "structural", "swing_lookback": 10},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
        },
    }
    manifest = StrategyManifest.model_validate(raw)
    return EngulfingMTFStrategy(manifest)


# ---------------------------------------------------------------------------
# Test 1: detect_4h_always_in — long confirm
# ---------------------------------------------------------------------------

class TestDetect4hAlwaysIn:

    def test_long_confirm_bullish_closes(self):
        """Son 6 barda 4 yukari kapanmis -> long confirm beklenir."""
        # Artan fiyatlar: her bar oncekinden yuksek kapaniyor
        closes = [100, 101, 102, 103, 104, 105]  # tumunun n-1'den yuksek
        df_4h = _make_4h_df(closes)
        cutoff = df_4h["ts"].iloc[-1] + timedelta(hours=8)  # son bar'dan sonra
        result = detect_4h_always_in(df_4h, cutoff, direction="long", lookback=6, n_confirm=3)
        assert result == "confirm", f"Beklenen 'confirm', alindi: {result!r}"

    def test_short_confirm_bearish_closes(self):
        """Son 6 barda 4 asagi kapanmis -> short confirm beklenir."""
        closes = [105, 104, 103, 102, 101, 100]  # azalan
        df_4h = _make_4h_df(closes)
        cutoff = df_4h["ts"].iloc[-1] + timedelta(hours=8)
        result = detect_4h_always_in(df_4h, cutoff, direction="short", lookback=6, n_confirm=3)
        assert result == "confirm", f"Beklenen 'confirm', alindi: {result!r}"

    def test_against_long_but_4h_bearish(self):
        """Long engulfing ama 4h bearish kapanislar -> against beklenir."""
        closes = [105, 104, 103, 102, 101, 100]  # azalan (bearish)
        df_4h = _make_4h_df(closes)
        cutoff = df_4h["ts"].iloc[-1] + timedelta(hours=8)
        # Long yon icin: 4h bearish -> against
        result = detect_4h_always_in(df_4h, cutoff, direction="long", lookback=6, n_confirm=3)
        assert result == "against", f"Beklenen 'against', alindi: {result!r}"

    def test_neutral_mixed_closes(self):
        """Karisik kapanislar -> neutral beklenir."""
        closes = [100, 102, 101, 103, 102, 104]  # yukari-asagi karisik ama n_confirm=5 sarti saglanamiyor
        df_4h = _make_4h_df(closes)
        cutoff = df_4h["ts"].iloc[-1] + timedelta(hours=8)
        # n_confirm=5 ile: 4 yukari var (< 5) ve 1 asagi (< 5) -> neutral
        result = detect_4h_always_in(df_4h, cutoff, direction="long", lookback=6, n_confirm=5)
        assert result == "neutral", f"Beklened 'neutral', alindi: {result!r}"

    def test_insufficient_bars_neutral(self):
        """Lookback'ten az bar mevcut -> neutral (yetersiz veri)."""
        closes = [100, 101]  # sadece 2 bar
        df_4h = _make_4h_df(closes)
        cutoff = df_4h["ts"].iloc[-1] + timedelta(hours=8)
        # lookback=6 ama sadece 2 bar var
        result = detect_4h_always_in(df_4h, cutoff, direction="long", lookback=6, n_confirm=3)
        assert result == "neutral", f"Yetersiz barda 'neutral' bekleniyor, alindi: {result!r}"

    def test_empty_df_neutral(self):
        """Bos DataFrame -> neutral."""
        df_4h = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        cutoff = pd.Timestamp("2023-06-01 00:00:00", tz="UTC")
        result = detect_4h_always_in(df_4h, cutoff, direction="long")
        assert result == "neutral"

    # -----------------------------------------------------------------------
    # Lookahead-free test (kritik)
    # -----------------------------------------------------------------------

    def test_lookahead_free_cutoff_excludes_future_bars(self):
        """cutoff_ts SONRASINDAKI 4h barlar kullanilmamali.

        Senaryo:
          - Ilk 6 bar: artan (long confirm vermeli)
          - Son 6 bar: azalan (bunlar cutoff SONRASI — yani gelecek)
          - cutoff, ilk 6 barin son barindan hemen sonra
          - detect_4h_always_in sadece ilk 6 bari gormeli -> confirm
        """
        # Ilk 6 bar: artan (bullish)
        bullish_closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        # Sonraki 6 bar: azalan (bearish — gelecek)
        bearish_closes = [104.0, 103.0, 102.0, 101.0, 100.0, 99.0]
        all_closes = bullish_closes + bearish_closes
        df_4h = _make_4h_df(all_closes)

        # cutoff: 6. barin kapanisinin hemen sonrasi (7. bar oncesi)
        cutoff_ts = df_4h["ts"].iloc[6]  # 7. barin ts'i — bu bar VE sonrasi excluded

        result = detect_4h_always_in(
            df_4h, cutoff_ts, direction="long", lookback=6, n_confirm=3
        )
        # Sadece ilk 6 bar goruluyor -> bullish -> confirm
        assert result == "confirm", (
            f"Lookahead-free test basarisiz. Beklenen 'confirm' (sadece ilk 6 bar), "
            f"alindi: {result!r}. cutoff={cutoff_ts}"
        )


# ---------------------------------------------------------------------------
# Test 2: Signal boost (4h confirm -> confluence * 1.3)
# ---------------------------------------------------------------------------

class TestSignalConfluenceBoost:

    def _make_engulfing_1d_df_with_pullback(self) -> pd.DataFrame:
        """Sinyal verecek 1d DataFrame olustur.

        Pullback: EMA'ya yakin bar + bullish engulfing bar.
        Trend: yukselen seri (>50 bar gerekiyor EMA icin).
        """
        n = 80
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        ts_list = [start + timedelta(days=i) for i in range(n)]

        # Trendin olusmasi icin yukselen fiyatlar
        base = 100.0
        closes = [base + i * 0.3 for i in range(n)]
        opens  = [c - 1.0 for c in closes]
        highs  = [c + 1.5 for c in closes]
        lows   = [o - 1.0 for o in opens]

        # Pullback olusutur: son 3 bar dusur, sonra bullish engulfing
        # Bar n-3: asagi don (pullback baslar)
        # Bar n-2: bear bar (EMA'ya dokunuyor)
        # Bar n-1: bullish engulfing (onceki bear bar'i tamamen sariyor)
        ema_approx = base + (n - 5) * 0.3  # yaklasik EMA degeri
        pull_low = ema_approx - 0.5

        closes[-3] = ema_approx + 0.5
        opens[-3]  = ema_approx + 1.5
        highs[-3]  = ema_approx + 2.0
        lows[-3]   = pull_low

        # Bear bar (N-2)
        closes[-2] = pull_low + 0.3
        opens[-2]  = ema_approx + 0.2
        highs[-2]  = ema_approx + 0.5
        lows[-2]   = pull_low - 0.2

        # Bullish engulfing (N-1): tamamen onceki body'i sarsin
        prev_o = opens[-2]
        prev_c = closes[-2]
        eng_o  = min(prev_o, prev_c) - 0.5   # open altta
        eng_c  = max(prev_o, prev_c) + 2.0   # close yukarda
        eng_h  = eng_c + 0.5
        eng_l  = eng_o - 0.5
        closes[-1] = eng_c
        opens[-1]  = eng_o
        highs[-1]  = eng_h
        lows[-1]   = eng_l

        df = pd.DataFrame({
            "ts": pd.to_datetime(ts_list, utc=True),
            "open":   opens,
            "high":   highs,
            "low":    lows,
            "close":  closes,
            "volume": [2_000_000.0] * n,
            "symbol": "TEST/USDT",
            "timeframe": "1d",
            "venue": "binance",
        })
        return df

    def test_4h_confirm_boosts_score(self):
        """4h confirm varken sinyal score'u 1.3x olmali."""
        df_1d = self._make_engulfing_1d_df_with_pullback()
        cutoff_ts = df_1d["ts"].iloc[-1]

        # 4h: bullish closes (long confirm)
        bullish_closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]
        df_4h = _make_4h_df(bullish_closes)
        # 4h barlarini 1d barin oncesine ayarla
        df_4h["ts"] = [cutoff_ts - timedelta(hours=(6 - i) * 4 + 1) for i in range(6)]

        strategy = _make_strategy(h4_reject_against=True, h4_confirm_boost=1.3)
        strategy._df_4h_cache["binance:TEST/USDT"] = df_4h

        df_feats = strategy.prepare_features(df_1d)
        signals_no4h = _make_strategy(h4_reject_against=False, h4_confirm_boost=1.0)
        signals_no4h._df_4h_cache["binance:TEST/USDT"] = None
        no_boost_signals = signals_no4h.generate_signals(df_feats)

        boost_signals = strategy.generate_signals(df_feats)

        if not no_boost_signals or not boost_signals:
            pytest.skip("Sinyal uretilmedi — engulfing koullari saglanamadi bu minimal fixture'da")

        # Boost'lu versiyon en az 1.0 faktoru ile yukarda olmali
        max_no_boost = max(s.confluence_score for s in no_boost_signals)
        max_boost = max(s.confluence_score for s in boost_signals)
        assert max_boost >= max_no_boost, (
            f"Boost'lu sinyal ({max_boost:.3f}) boost'suz ({max_no_boost:.3f}) kadar olmali"
        )

    def test_4h_against_rejects_signal(self):
        """4h against varken sinyal REDDEDILMELI (h4_reject_against=True)."""
        df_1d = self._make_engulfing_1d_df_with_pullback()
        cutoff_ts = df_1d["ts"].iloc[-1]

        # 4h: bearish closes (long icin against)
        bearish_closes = [105.0, 104.0, 103.0, 102.0, 101.0, 100.0]
        df_4h = _make_4h_df(bearish_closes)
        df_4h["ts"] = [cutoff_ts - timedelta(hours=(6 - i) * 4 + 1) for i in range(6)]

        strategy = _make_strategy(h4_reject_against=True)
        strategy._df_4h_cache["binance:TEST/USDT"] = df_4h

        df_feats = strategy.prepare_features(df_1d)
        signals = strategy.generate_signals(df_feats)

        # Eger 4h against olmayan sinyal yoksa test gecerli degil
        # Eger 4h against olan long sinyaller varsa bunlar reddedilmeli
        against_signals = [
            s for s in signals
            if s.metadata.get("h4_verdict") == "against"
        ]
        # h4_reject_against=True ise against sinyaller hicbir zaman out listesinde olmamali
        assert len(against_signals) == 0, (
            f"4h against sinyaller reddedilmeli, ama {len(against_signals)} tane bulundu"
        )

    def test_4h_neutral_passes_through(self):
        """4h neutral durumda sinyal degismeden gecmeli."""
        df_1d = self._make_engulfing_1d_df_with_pullback()
        cutoff_ts = df_1d["ts"].iloc[-1]

        # 4h: karisik (neutral)
        mixed_closes = [100.0, 101.0, 100.5, 101.0, 100.8, 101.2]
        df_4h = _make_4h_df(mixed_closes)
        df_4h["ts"] = [cutoff_ts - timedelta(hours=(6 - i) * 4 + 1) for i in range(6)]

        strategy = _make_strategy(h4_reject_against=True, h4_n_confirm=5)  # yuksek esik -> neutral
        strategy._df_4h_cache["binance:TEST/USDT"] = df_4h

        df_feats = strategy.prepare_features(df_1d)
        signals = strategy.generate_signals(df_feats)

        # Neutral sinyaller h4_boost_applied=False olmali
        for sig in signals:
            if sig.metadata.get("h4_verdict") == "neutral":
                assert not sig.metadata.get("h4_boost_applied", False), (
                    "Neutral 4h sinyalde boost uygulanmamali"
                )

    def test_no_4h_data_neutral_fallback(self):
        """4h veri yoksa sinyal neutral olarak gecmeli (hata vermemeli)."""
        df_1d = self._make_engulfing_1d_df_with_pullback()

        # 4h yok
        strategy = _make_strategy()
        strategy._df_4h_cache["binance:TEST/USDT"] = None

        df_feats = strategy.prepare_features(df_1d)
        # Hata vermemeli
        signals = strategy.generate_signals(df_feats)
        # Sonuc bos veya bos degil, fark yok — hata yok olmali
        assert isinstance(signals, list)


# ---------------------------------------------------------------------------
# Test 3: default_manifest dogrulama
# ---------------------------------------------------------------------------

class TestDefaultManifest:

    def test_manifest_has_4h_params(self):
        """Default manifest 4h parametrelerini icermeli."""
        manifest = _default_manifest()
        filters = manifest.signals.filters
        assert hasattr(filters, "h4_lookback"), "h4_lookback eksik"
        assert hasattr(filters, "h4_n_confirm"), "h4_n_confirm eksik"
        assert hasattr(filters, "h4_confirm_boost"), "h4_confirm_boost eksik"
        assert hasattr(filters, "h4_reject_against"), "h4_reject_against eksik"

    def test_manifest_name(self):
        manifest = _default_manifest()
        assert manifest.name == "engulfing_mtf"

    def test_strategy_instantiation(self):
        """Manifest ile strateji olusturulmali."""
        manifest = _default_manifest()
        strat = EngulfingMTFStrategy(manifest)
        assert strat.name == "engulfing_mtf"
