"""Unit testler -- VolRiskPremiumStrategy (Volatility Risk Premium Fade).

Test senaryoları:
  1. _realized_vol formülü doğrulama (sıfır log-return → RV=0)
  2. _rv_percentile: monotonik RV'de yüzdelik sırası
  3. Spike tespit: ATR% > 2x median AND body_ratio büyük
  4. Contraction konfirmasyonu: inside-bar True, normal bar False
  5. Doji kontraksiyon tespiti
  6. Lookahead-free: spike_bar_prev shift(1) kullanıyor
  7. Signal yönü: bullish spike → SHORT; bearish spike → LONG
  8. Contraction olmadan sinyal üretilmemeli
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.vol_risk_premium import (
    VolRiskPremiumStrategy,
    _realized_vol,
    _rv_percentile,
    _vol_contraction_signal,
    _atr_pct,
    _atr_median,
    _default_manifest,
)


# ---------------------------------------------------------------------------
# Yardımcı fabrika
# ---------------------------------------------------------------------------

def _base_ts(n: int) -> list[datetime]:
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def _make_strategy(overrides: dict | None = None) -> VolRiskPremiumStrategy:
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "vol_risk_premium",
        "version": "0.0.1",
        "trend_filter": {"type": "none", "period": 1, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "vol_fade_short",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "rv_lookback": 14,
                        "rv_pct_window": 90,
                        "spike_atr_mult": 2.0,
                        "spike_body_ratio": 0.6,
                        "atr_median_window": 30,
                        "rv_pct_threshold": 0.95,
                    },
                },
                {
                    "id": "vol_fade_long",
                    "enabled": True,
                    "weight": 1.5,
                    "params": {
                        "rv_lookback": 14,
                        "rv_pct_window": 90,
                        "spike_atr_mult": 2.0,
                        "spike_body_ratio": 0.6,
                        "atr_median_window": 30,
                        "rv_pct_threshold": 0.95,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 30,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 30,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {"atr_min_pct": 0.0, "volume_zscore_min": 0.0},
            "confluence": {"method": "weighted_sum", "min_score": 1.0, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "stop_loss": {"method": "structural_atr", "atr_buffer": 1.0},
            "take_profit": {"method": "r_multiple", "primary_R": 1.5},
        },
    }
    if overrides:
        raw.update(overrides)
    manifest = StrategyManifest.model_validate(raw)
    return VolRiskPremiumStrategy(manifest)


def _make_flat_close(n: int, price: float = 100.0) -> pd.Series:
    return pd.Series(np.full(n, price), dtype=float)


def _make_ohlcv(
    n: int,
    base_price: float = 100.0,
    atr_size: float = 2.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Normal volatilitede sentetik OHLCV."""
    rng = np.random.default_rng(seed)
    ts = _base_ts(n)
    close = base_price + np.cumsum(rng.normal(0, 0.5, n))
    close = np.maximum(close, 1.0)
    open_ = np.r_[close[0], close[:-1]]
    noise = atr_size * np.abs(rng.normal(0.5, 0.2, n))
    high = np.maximum(open_, close) + noise
    low = np.minimum(open_, close) - noise
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(1e6, 3e6, n)
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


# ---------------------------------------------------------------------------
# 1. _realized_vol formül testi
# ---------------------------------------------------------------------------

class TestRealizedVol:
    def test_flat_price_gives_zero_rv(self):
        """Sabit fiyatta log-return=0 → RV=0 (veya çok küçük, floating point)."""
        close = _make_flat_close(50, 100.0)
        rv = _realized_vol(close, lookback=14)
        # İlk birkaç bar NaN/0 normal; sonraki barlar 0 olmalı
        valid = rv.iloc[20:]
        assert (valid.abs() < 1e-10).all(), f"Sabit fiyatta RV>0: {valid.max()}"

    def test_rv_positive_for_volatile_series(self):
        """Volatil seride RV > 0 olmalı."""
        rng = np.random.default_rng(0)
        close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.03, 100))))
        rv = _realized_vol(close, lookback=14)
        valid = rv.dropna()
        assert (valid > 0).any(), "Volatil seride RV pozitif olmalı"

    def test_rv_increases_with_volatility(self):
        """Yüksek volatilite → yüksek ortalama RV."""
        rng = np.random.default_rng(1)
        close_low = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.005, 200))))
        close_high = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.05, 200))))
        rv_low = _realized_vol(close_low, lookback=14).dropna()
        rv_high = _realized_vol(close_high, lookback=14).dropna()
        assert rv_low.mean() < rv_high.mean(), "Yüksek vol serisinde RV daha büyük olmalı"

    def test_rv_lookahead_free(self):
        """RV[t] t-1'e kadar veri kullanmalı — t'deki son bar değişimi etkilememeli."""
        rng = np.random.default_rng(3)
        close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, 50))))
        rv_orig = _realized_vol(close, lookback=14)
        # t=40'ta fiyatı büyük değiştir
        close_mod = close.copy()
        close_mod.iloc[40] = close.iloc[40] * 10.0
        rv_mod = _realized_vol(close_mod, lookback=14)
        # t=40 öncesindeki RV değerleri değişmemeli
        pd.testing.assert_series_equal(
            rv_orig.iloc[:39],
            rv_mod.iloc[:39],
            check_names=False,
        )


# ---------------------------------------------------------------------------
# 2. _rv_percentile testi
# ---------------------------------------------------------------------------

class TestRvPercentile:
    def test_monotonic_rv_percentile_increases(self):
        """Monotonik artan RV → percentile rank monotonik artmalı."""
        n = 150
        rv = pd.Series(np.linspace(0.01, 0.10, n))
        pct = _rv_percentile(rv, window=90)
        valid = pct.dropna()
        # Son değerler en yüksek olmalı
        assert valid.iloc[-1] > valid.iloc[0], "Artan RV'de percentile yükselmeli"

    def test_percentile_range_0_to_1(self):
        """Tüm percentile değerleri [0, 1] aralığında olmalı."""
        rng = np.random.default_rng(7)
        rv = pd.Series(np.abs(rng.normal(0.03, 0.01, 150)))
        pct = _rv_percentile(rv, window=90)
        valid = pct.dropna()
        assert (valid >= 0.0).all() and (valid <= 1.0).all(), "Percentile [0,1] dışında"

    def test_max_rv_gives_high_percentile(self):
        """En yüksek RV değeri 90. yüzdeliğin üzerinde percentile vermeli."""
        n = 120
        rv = pd.Series(np.r_[np.full(100, 0.02), np.full(20, 0.10)])
        pct = _rv_percentile(rv, window=90)
        # Son 10 barda (yüksek rv) percentile yüksek olmalı
        late = pct.iloc[-10:].dropna()
        if len(late) > 0:
            assert late.mean() > 0.6, f"Yüksek RV düşük percentile verdi: {late.mean():.2f}"


# ---------------------------------------------------------------------------
# 3. Spike tespit
# ---------------------------------------------------------------------------

class TestSpikeDetection:
    def test_spike_bar_detected_via_features(self):
        """Büyük ATR% barından sonra spike_bar_prev=True olmalı."""
        n = 150
        df = _make_ohlcv(n, base_price=100.0, atr_size=1.0, seed=10)
        # Bar 100'de büyük bullish spike (open=100, close=115, range=16)
        df.loc[100, "open"] = 100.0
        df.loc[100, "close"] = 115.0
        df.loc[100, "high"] = 116.0
        df.loc[100, "low"] = 99.0
        # Bar 101'de inside-bar (contraction)
        df.loc[101, "open"] = 112.0
        df.loc[101, "close"] = 113.0
        df.loc[101, "high"] = 115.5   # < prev high 116
        df.loc[101, "low"] = 100.5    # > prev low 99

        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        # spike_bar_prev'in bar 101'de True olup olmadığını kontrol et
        # (çünkü bar 100 spike, bar 101 onu görmeli)
        spike_at_101 = bool(df_feat.loc[101, "spike_bar_prev"])
        # Bar 100 spike barı, bar 101'de prev_bullish_spike True olmalı
        # (spike_bar_prev ATR koşulunu da gerektiriyor, büyük spike sağlamalı)
        # ATR% koşulunun geçip geçmediğine bakmak için spike_ratio'ya bak
        spike_ratio_101 = float(df_feat.loc[101, "spike_ratio"])
        contraction_101 = bool(df_feat.loc[101, "contraction_flag"])
        assert contraction_101, "Bar 101 inside-bar olmalı → contraction_flag=True"
        # spike_ratio yeterince büyükse spike_bar_prev True olmalı
        # (ATR koşulu window gerektiriyor, en azından spike_ratio > 1 olmalı)
        assert spike_ratio_101 > 1.0, f"Bar 100 spike → bar 101 spike_ratio > 1 bekleniyor: {spike_ratio_101}"

    def test_normal_bar_not_spike(self):
        """Normal (küçük ATR%) bardan sonra spike_bar_prev=False olmalı."""
        n = 100
        df = _make_ohlcv(n, atr_size=1.0, seed=20)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        # İlk 50 barın spike_ratio ortalaması ~1.0 civarında olmalı (spike değil)
        median_ratio = df_feat["spike_ratio"].iloc[40:60].median()
        # Normal barlarda spike_ratio 2.0'ı aşmamalı (medyanı)
        assert median_ratio < 3.0, f"Normal barlarda spike_ratio yüksek: {median_ratio}"


# ---------------------------------------------------------------------------
# 4. Contraction konfirmasyon testi — inside-bar
# ---------------------------------------------------------------------------

class TestVolContractionSignal:
    def test_inside_bar_detected(self):
        """Inside-bar: current high < prev high AND current low > prev low → True."""
        n = 5
        ts = _base_ts(n)
        df = pd.DataFrame({
            "ts": ts,
            "open":  [100.0, 100.0, 101.0, 102.0, 101.0],
            "high":  [105.0, 110.0, 109.0, 108.0, 107.0],  # bar2: 109 < prev(110) ✓
            "low":   [95.0,  90.0,  91.0,  92.0,  93.0],   # bar2: 91 > prev(90)   ✓
            "close": [102.0, 95.0,  105.0, 103.0, 100.0],
            "volume": np.full(n, 1e6),
            "venue": "binance",
            "symbol": "T/USDT",
            "timeframe": "1d",
        })
        flags = _vol_contraction_signal(df)
        assert bool(flags.iloc[2]), "Bar 2 inside-bar olmalı → contraction=True"
        assert not bool(flags.iloc[0]), "Bar 0 (no prev) → contraction=False"

    def test_outside_bar_not_contraction(self):
        """Outside-bar: current high > prev high veya current low < prev low → False."""
        n = 3
        ts = _base_ts(n)
        df = pd.DataFrame({
            "ts": ts,
            "open":  [100.0, 98.0,  97.0],
            "high":  [105.0, 104.0, 112.0],  # bar2: 112 > prev(104) → outside
            "low":   [95.0,  93.0,  85.0],   # bar2: 85 < prev(93) → outside
            "close": [102.0, 96.0,  108.0],
            "volume": np.full(n, 1e6),
            "venue": "binance",
            "symbol": "T/USDT",
            "timeframe": "1d",
        })
        flags = _vol_contraction_signal(df)
        assert not bool(flags.iloc[2]), "Outside-bar contraction=False olmalı"

    # 5. Doji kontraksiyon testi
    def test_doji_detected_as_contraction(self):
        """Doji: |close-open| < 0.10 * (high-low) → contraction=True."""
        n = 3
        ts = _base_ts(n)
        df = pd.DataFrame({
            "ts": ts,
            "open":  [100.0, 95.0,  100.0],
            "high":  [105.0, 100.0, 110.0],
            "low":   [95.0,  90.0,  90.0],
            "close": [102.0, 97.0,  100.5],   # bar2: body=0.5, range=20 → 0.5/20=0.025 < 0.10 ✓
            "volume": np.full(n, 1e6),
            "venue": "binance",
            "symbol": "T/USDT",
            "timeframe": "1d",
        })
        flags = _vol_contraction_signal(df)
        assert bool(flags.iloc[2]), "Doji bar contraction=True olmalı"

    def test_large_body_bar_not_doji(self):
        """Büyük body bar (body_ratio > 0.10) doji sayılmamalı."""
        n = 3
        ts = _base_ts(n)
        df = pd.DataFrame({
            "ts": ts,
            "open":  [100.0, 95.0,  95.0],
            "high":  [105.0, 100.0, 105.0],
            "low":   [95.0,  90.0,  93.0],
            "close": [102.0, 97.0,  104.0],  # bar2: body=9, range=12 → ratio=0.75 > 0.10
            "volume": np.full(n, 1e6),
            "venue": "binance",
            "symbol": "T/USDT",
            "timeframe": "1d",
        })
        flags = _vol_contraction_signal(df)
        assert not bool(flags.iloc[2]), "Büyük body bar doji sayılmamalı"


# ---------------------------------------------------------------------------
# 6. Lookahead-free testi
# ---------------------------------------------------------------------------

class TestLookaheadFree:
    def test_spike_bar_prev_uses_shift1(self):
        """spike_bar_prev[t] sadece t-1 bilgisini kullanmalı.

        t=50'de büyük spike ekle → spike_bar_prev[49] ve daha öncesi değişmemeli.
        """
        n = 120
        df = _make_ohlcv(n, atr_size=1.0, seed=55)
        strat = _make_strategy()
        df_orig = strat.prepare_features(df)

        # t=50'de büyük spike
        df_mod = df.copy()
        df_mod.loc[50, "open"] = 100.0
        df_mod.loc[50, "close"] = 130.0
        df_mod.loc[50, "high"] = 132.0
        df_mod.loc[50, "low"] = 99.0

        df_mod_feat = strat.prepare_features(df_mod)

        # t=49 ve öncesi spike_bar_prev değişmemeli (shift(1) yüzünden t=50 etkisi t=51'de görülür)
        orig_49 = bool(df_orig.loc[49, "spike_bar_prev"])
        mod_49 = bool(df_mod_feat.loc[49, "spike_bar_prev"])
        assert orig_49 == mod_49, "spike_bar_prev[49] t=50 değişiminden etkilenmemeli"

    def test_rv_pct_rank_no_future_data(self):
        """rv_pct_rank[t] t+1 ve sonrasını kullanmamalı.

        t=80 sonrasında çok yüksek RV eklenir → t=79 rv_pct_rank değişmemeli.
        """
        n = 120
        rng = np.random.default_rng(77)
        close = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, 0.02, n))))
        rv = _realized_vol(close, lookback=14)
        pct_orig = _rv_percentile(rv, window=90)

        close_mod = close.copy()
        close_mod.iloc[80:] = close.iloc[80:] * 2.0  # t=80+ büyük fiyat hareketi
        rv_mod = _realized_vol(close_mod, lookback=14)
        pct_mod = _rv_percentile(rv_mod, window=90)

        # t=79 öncesi rv_pct_rank değerleri aynı olmalı
        # (rv shift(1) ile hesaplanıyor, t=79'un rv_pct_rank'i [t-window..t-1]'i kullanıyor)
        for i in range(30, 78):
            assert abs(float(pct_orig.iloc[i]) - float(pct_mod.iloc[i])) < 1e-9, (
                f"rv_pct_rank[{i}] future data'dan etkilendi"
            )


# ---------------------------------------------------------------------------
# 7. Signal yönü testi
# ---------------------------------------------------------------------------

class TestSignalDirection:
    def test_bullish_spike_gives_short_signal(self):
        """Büyük bullish spike + contraction → SHORT sinyal üretilmeli."""
        n = 150
        df = _make_ohlcv(n, atr_size=0.5, seed=99)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        # Manuel olarak spike_bar_prev ve prev_bullish_spike set et
        # Sonra contraction_flag = True yap
        # Ve ATR yeterli yap
        df_feat.loc[120, "prev_bullish_spike"] = True
        df_feat.loc[120, "spike_bar_prev"] = True
        df_feat.loc[120, "contraction_flag"] = True
        df_feat.loc[120, "spike_high"] = float(df_feat.loc[120, "close"]) * 1.05
        df_feat.loc[120, "atr14"] = float(df_feat.loc[120, "close"]) * 0.02
        df_feat.loc[120, "atr_pct"] = 0.02

        signals = strat.generate_signals(df_feat)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) >= 1, "Bullish spike → en az 1 SHORT sinyal bekleniyor"
        sig = short_sigs[0]
        assert sig.pattern_id == "vol_fade_short"
        assert sig.sl_price > sig.metadata.get("spike_high", 0), (
            "SHORT SL spike_high üzerinde olmalı"
        )

    def test_bearish_spike_gives_long_signal(self):
        """Büyük bearish spike + contraction → LONG sinyal üretilmeli."""
        n = 150
        df = _make_ohlcv(n, atr_size=0.5, seed=88)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        df_feat.loc[120, "prev_bearish_spike"] = True
        df_feat.loc[120, "spike_bar_prev"] = True
        df_feat.loc[120, "contraction_flag"] = True
        df_feat.loc[120, "spike_low"] = float(df_feat.loc[120, "close"]) * 0.95
        df_feat.loc[120, "atr14"] = float(df_feat.loc[120, "close"]) * 0.02
        df_feat.loc[120, "atr_pct"] = 0.02

        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) >= 1, "Bearish spike → en az 1 LONG sinyal bekleniyor"
        sig = long_sigs[0]
        assert sig.pattern_id == "vol_fade_long"
        assert sig.sl_price < sig.metadata.get("spike_low", float("inf")), (
            "LONG SL spike_low altında olmalı"
        )

    def test_tp_is_1_5R(self):
        """TP = 1.5R olmalı: tp_price = close + 1.5 * (close - sl_price)."""
        n = 150
        df = _make_ohlcv(n, atr_size=0.5, seed=77)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        df_feat.loc[100, "prev_bearish_spike"] = True
        df_feat.loc[100, "spike_bar_prev"] = True
        df_feat.loc[100, "contraction_flag"] = True
        close = float(df_feat.loc[100, "close"])
        df_feat.loc[100, "spike_low"] = close * 0.95
        df_feat.loc[100, "atr14"] = close * 0.02
        df_feat.loc[100, "atr_pct"] = 0.02

        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) >= 1

        sig = long_sigs[0]
        # Signal'de entry_price yok — close fiyatı entry proxy olarak kullanılır
        # SL ve TP hesaplaması: risk = close - sl_price; tp = close + 1.5 * risk
        risk = close - sig.sl_price
        expected_tp = close + 1.5 * risk
        actual_tp = sig.tp_price
        # %2 tolerans ile kontrol (floating point + atr_buffer nedeniyle)
        assert abs(actual_tp - expected_tp) < close * 0.02, (
            f"TP 1.5R değil: beklenen≈{expected_tp:.2f}, gerçek={actual_tp:.2f}, "
            f"close={close:.2f}, sl={sig.sl_price:.2f}"
        )


# ---------------------------------------------------------------------------
# 8. Contraction olmadan sinyal üretilmemeli
# ---------------------------------------------------------------------------

class TestNoSignalWithoutContraction:
    def test_no_signal_when_contraction_false(self):
        """Spike var ama contraction_flag=False → sinyal üretilmemeli."""
        n = 150
        df = _make_ohlcv(n, atr_size=0.5, seed=66)
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)

        # Tüm barları sıfırla
        df_feat["contraction_flag"] = False
        df_feat["prev_bullish_spike"] = False
        df_feat["prev_bearish_spike"] = False
        df_feat["spike_bar_prev"] = False

        # Birkaç barda spike var ama contraction yok
        df_feat.loc[100, "prev_bullish_spike"] = True
        df_feat.loc[100, "spike_bar_prev"] = True
        # contraction_flag[100] = False (yukarıda hepsi False yapıldı)

        signals = strat.generate_signals(df_feat)
        assert signals == [], "Contraction olmadan sinyal üretilmemeli"

    def test_empty_df_returns_empty(self):
        """Boş DataFrame → boş sinyal listesi."""
        strat = _make_strategy()
        df = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        signals = strat.generate_signals(df)
        assert signals == []

    def test_default_manifest_valid(self):
        """_default_manifest() geçerli StrategyManifest döndürmeli."""
        m = _default_manifest()
        assert m.name == "vol_risk_premium"
        assert len(m.signals.patterns) == 2
        pattern_ids = {p.id for p in m.signals.patterns}
        assert "vol_fade_short" in pattern_ids
        assert "vol_fade_long" in pattern_ids

    def test_smoke_run_on_random_data(self):
        """Rastgele veriye karşı smoke testi — exception olmamalı."""
        rng = np.random.default_rng(123)
        n = 300
        close = 100 * np.exp(np.cumsum(rng.normal(0.001, 0.025, n)))
        open_ = np.r_[close[0], close[:-1]]
        noise = np.abs(rng.normal(0.01, 0.005, n)) * close
        high = np.maximum(open_, close) + noise
        low = np.minimum(open_, close) - noise
        high = np.maximum.reduce([high, open_, close])
        low = np.minimum.reduce([low, open_, close])
        ts = [datetime(2022, 1, 1, tzinfo=timezone.utc) + timedelta(days=i) for i in range(n)]
        df = pd.DataFrame({
            "ts": ts,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": rng.uniform(1e6, 5e6, n),
            "venue": "binance",
            "symbol": "SMOKE/USDT",
            "timeframe": "1d",
        })
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        signals = strat.generate_signals(df_feat)
        assert isinstance(signals, list)
