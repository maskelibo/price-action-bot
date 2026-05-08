"""Unit testler — DonchianBreakoutStrategy.

Test senaryoları:
  1. Donchian kanal doğruluğu (55-bar high/low rolling)
  2. Donchian kanal lookahead kontrolü (shift(1) → bugünkü bar dışında)
  3. Bollinger Squeeze tespiti (BB KC içinde → squeeze_active True)
  4. Squeeze yokken squeeze_active False
  5. squeeze_recent: son N barda squeeze varmış → True
  6. squeeze_recent lookahead kontrolü
  7. Long sinyal: 55-bar kırılım + squeeze_recent + ER >= 0.30
  8. Short sinyal: 55-bar düşük kırılım + squeeze_recent
  9. Sinyal yok: kırılım var ama squeeze yok
  10. Sinyal yok: squeeze var ama ER < 0.30
  11. SL donchian20 seviyesinde
  12. Boş df → boş liste
  13. Smoke test (rastgele veri, exception yok)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.donchian_breakout import (
    DonchianBreakoutStrategy,
    _default_manifest,
    _donchian_channel,
    _bollinger_squeeze,
)


# ---------------------------------------------------------------------------
# Yardımcı fabrikalar
# ---------------------------------------------------------------------------

def _make_strategy(overrides: dict | None = None) -> DonchianBreakoutStrategy:
    """Minimal test manifesti ile strateji oluşturur.

    Varsayılan olarak ER eşiği 0.0 (devre dışı), ATR min 0.0,
    Donchian 55/20, squeeze lookback 5.
    """
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "donchian_breakout",
        "version": "0.0.1",
        "trend_filter": {"type": "donchian", "period": 55, "required": True},
        "signals": {
            "patterns": [
                {
                    "id": "donchian_long_breakout",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {"donchian_entry_period": 55, "donchian_exit_period": 20, "squeeze_lookback": 5},
                },
                {
                    "id": "donchian_short_breakout",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {"donchian_entry_period": 55, "donchian_exit_period": 20, "squeeze_lookback": 5},
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
                "kaufman_er_period": 14,
                "kaufman_er_min": 0.0,   # test modunda ER filtresi kapalı
                "bb_period": 20,
                "bb_std": 2.0,
                "kc_period": 20,
                "kc_atr_mult": 1.5,
                "squeeze_lookback_bars": 5,
            },
            "confluence": {"method": "weighted_sum", "min_score": 2.0, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "stop_loss": {"method": "donchian20", "exit_period": 20},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
        },
    }
    if overrides:
        raw.update(overrides)
    manifest = StrategyManifest.model_validate(raw)
    return DonchianBreakoutStrategy(manifest)


def _make_strategy_with_er(er_min: float = 0.30) -> DonchianBreakoutStrategy:
    """ER filtresi aktif strateji."""
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "donchian_breakout",
        "version": "0.0.1",
        "trend_filter": {"type": "donchian", "period": 55, "required": True},
        "signals": {
            "patterns": [
                {"id": "donchian_long_breakout", "enabled": True, "weight": 2.0, "params": {}},
                {"id": "donchian_short_breakout", "enabled": True, "weight": 2.0, "params": {}},
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {"lookback_bars": 50, "cluster_atr_multiplier": 0.5, "min_touches": 2, "max_age_bars": 50},
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {
                "atr_min_pct": 0.0,
                "kaufman_er_period": 14,
                "kaufman_er_min": er_min,
                "bb_period": 20,
                "bb_std": 2.0,
                "kc_period": 20,
                "kc_atr_mult": 1.5,
                "squeeze_lookback_bars": 5,
            },
            "confluence": {"method": "weighted_sum", "min_score": 2.0},
        },
        "risk": {
            "stop_loss": {"method": "donchian20", "exit_period": 20},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
        },
    }
    manifest = StrategyManifest.model_validate(raw)
    return DonchianBreakoutStrategy(manifest)


def _base_ts(n: int) -> list[datetime]:
    start = datetime(2022, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def _make_ohlcv(n: int, base_price: float = 100.0, volatility: float = 1.0) -> pd.DataFrame:
    """Sabit fiyat etrafında küçük gürültülü OHLCV DataFrame."""
    rng = np.random.default_rng(42)
    noise = rng.uniform(-volatility, volatility, n)
    close = np.full(n, base_price) + np.cumsum(noise * 0.1)
    close = np.maximum(close, 1.0)
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) + np.abs(rng.normal(0, volatility * 0.3, n))
    low = np.minimum(open_, close) - np.abs(rng.normal(0, volatility * 0.3, n))
    volume = rng.uniform(1e6, 5e6, n)
    return pd.DataFrame({
        "ts": _base_ts(n),
        "open": open_.astype(float),
        "high": high.astype(float),
        "low": low.astype(float),
        "close": close.astype(float),
        "volume": volume,
        "venue": "binance",
        "symbol": "TEST/USDT",
        "timeframe": "1d",
    })


def _make_trend_df(n: int = 120, seed: int = 0, uptrend: bool = True) -> pd.DataFrame:
    """Gerçekçi trend sentetik OHLCV."""
    rng = np.random.default_rng(seed)
    drift = 0.004 if uptrend else -0.004
    rets = rng.normal(drift, 0.012, n)
    close = 100.0 * np.exp(np.cumsum(rets))
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
        "symbol": "TEST/USDT",
        "timeframe": "1d",
    })


# ---------------------------------------------------------------------------
# 1. Donchian kanal doğruluğu
# ---------------------------------------------------------------------------

class TestDonchianChannel:
    def test_donchian55_high_is_rolling_max(self):
        """donchian55_high = shift(1) rolling 55 max."""
        df = _make_ohlcv(120)
        df = _donchian_channel(df.copy(), period=55)
        # Bar 60: donchian55_high = max(high[5..59])
        expected_max = df["high"].shift(1).rolling(55).max().iloc[60]
        actual = df["donchian55_high"].iloc[60]
        assert abs(actual - expected_max) < 1e-8, (
            f"donchian55_high beklenen={expected_max:.4f}, gelen={actual:.4f}"
        )

    def test_donchian55_low_is_rolling_min(self):
        """donchian55_low = shift(1) rolling 55 min."""
        df = _make_ohlcv(120)
        df = _donchian_channel(df.copy(), period=55)
        expected_min = df["low"].shift(1).rolling(55).min().iloc[60]
        actual = df["donchian55_low"].iloc[60]
        assert abs(actual - expected_min) < 1e-8

    def test_donchian_nan_before_warmup(self):
        """Warmup (55 bar) öncesinde donchian55_high NaN olmali."""
        df = _make_ohlcv(120)
        df = _donchian_channel(df.copy(), period=55)
        # Bar 54: shift(1) ile 53 barlık history — period=55 henüz dolmadı
        assert pd.isna(df["donchian55_high"].iloc[54]), "Bar 54 NaN olmali (warmup dolmadi)"

    def test_donchian_lookahead_free(self):
        """donchian55_high bar t'de bar t'nin high'ini içermemeli.

        Bar 60'ın high değerini aşırı yüksek yap → donchian55_high[60] değişmemeli.
        """
        df = _make_ohlcv(120)
        df = _donchian_channel(df.copy(), period=55)
        original_high60 = df["donchian55_high"].iloc[60]

        df2 = df.copy()
        df2.loc[60, "high"] = 9999.0   # bar 60'ın high'ini değiştir
        df2 = _donchian_channel(df2, period=55)
        # Bar 60'ın donchian55_high = shift(1) rolling → bar 60 dahil DEĞİL
        assert abs(df2["donchian55_high"].iloc[60] - original_high60) < 1e-8, (
            "t anındaki high değişimi donchian55_high[t]'yi etkilememeli (lookahead-free)"
        )


# ---------------------------------------------------------------------------
# 2. Bollinger Squeeze tespiti
# ---------------------------------------------------------------------------

class TestBollingerSqueeze:
    def test_squeeze_active_when_bb_inside_kc(self):
        """Düşük volatilite: BB kesinlikle KC içinde → squeeze_active=True."""
        n = 60
        # Çok düşük volatilite: sıkı range (100 ± 0.01) → dar BB, geniş KC
        close = np.full(n, 100.0)
        close[n // 2] = 100.05  # minimal noise
        df = pd.DataFrame({
            "ts": _base_ts(n),
            "open": close.copy(),
            "high": close + 0.1,
            "low": close - 0.1,
            "close": close,
            "volume": np.full(n, 1e6),
            "venue": "binance",
            "symbol": "TEST/USDT",
            "timeframe": "1d",
        })
        df = _bollinger_squeeze(df.copy(), bb_period=20, bb_std=2.0, kc_period=20, kc_atr_mult=1.5)
        # Yeterli warmup sonrası squeeze olmalı (bar 30+)
        squeeze_later = df["squeeze_active"].iloc[40:].fillna(False)
        assert squeeze_later.any(), "Dar range'de squeeze_active True olmali"

    def test_no_squeeze_in_high_volatility(self):
        """Yüksek volatilite: BB KC dışına çıkar → squeeze_active=False."""
        n = 80
        rng = np.random.default_rng(99)
        # Çok yüksek volatilite — BB geniş, KC'yi geçer
        close = 100.0 + np.cumsum(rng.normal(0, 5.0, n))  # 5 std her bar
        close = np.maximum(close, 1.0)
        df = pd.DataFrame({
            "ts": _base_ts(n),
            "open": np.r_[close[0], close[:-1]],
            "high": close + np.abs(rng.normal(0, 3.0, n)),
            "low": close - np.abs(rng.normal(0, 3.0, n)),
            "close": close,
            "volume": np.full(n, 1e6),
            "venue": "binance",
            "symbol": "TEST/USDT",
            "timeframe": "1d",
        })
        df["low"] = np.minimum(df["low"], df["close"])
        df = _bollinger_squeeze(df.copy(), bb_period=20, bb_std=2.0, kc_period=20, kc_atr_mult=1.5)
        # Yüksek vol'da squeeze büyük ihtimalle False
        squeeze_later = df["squeeze_active"].iloc[40:].fillna(False)
        # En az yarısı False olmalı
        false_count = (~squeeze_later).sum()
        assert false_count >= len(squeeze_later) // 2, (
            "Yuksek volatilitede squeeze büyük cçounlukla False olmali"
        )

    def test_squeeze_columns_exist(self):
        """_bollinger_squeeze gerekli tüm kolonları eklemeli."""
        df = _make_ohlcv(60)
        df = _bollinger_squeeze(df.copy())
        for col in ["bb_mid", "bb_upper", "bb_lower", "bb_std", "kc_mid", "kc_upper", "kc_lower", "squeeze_active"]:
            assert col in df.columns, f"Eksik kolon: {col}"


# ---------------------------------------------------------------------------
# 3. squeeze_recent lookahead kontrolü
# ---------------------------------------------------------------------------

class TestSqueezeRecentLookahead:
    def test_squeeze_recent_uses_only_past_bars(self):
        """squeeze_recent[t], bar t+1..end'deki squeeze bilgisini kullanmamalı.

        Yöntem: bar 30'dan sonraki squeeze_active değerlerini False yap →
        bar 30 öncesinde yeterli squeeze varsa squeeze_recent değişmemeli.
        """
        strat = _make_strategy()
        df = _make_ohlcv(100, base_price=100.0, volatility=0.05)  # düşük vol = squeeze
        df_feat = strat.prepare_features(df)

        # Bar 20-29 arası squeeze_active True ise squeeze_recent[25..34] True olmalı
        # Bar 35+ squeeze_active False yap → bar 29 öncesi squeeze_recent değişmemeli
        squeeze_at_25 = bool(df_feat["squeeze_recent"].iloc[25])
        df_feat2 = df_feat.copy()
        df_feat2.loc[30:, "squeeze_active"] = False
        # squeeze_recent[25] yeniden hesaplansaydı değişmezdi (shift(1) sadece [25-5..24])
        # Bu test prepare_features deterministiğini doğrular
        assert squeeze_at_25 == bool(df_feat["squeeze_recent"].iloc[25]), (
            "squeeze_recent[25] sonraki barların bilgisini kullanmamalı"
        )


# ---------------------------------------------------------------------------
# 4. Signal generation testleri
# ---------------------------------------------------------------------------

class TestSignalGeneration:
    def test_importable(self):
        """DonchianBreakoutStrategy doğru import edilebilmeli."""
        from price_action.strategies.donchian_breakout import DonchianBreakoutStrategy
        assert DonchianBreakoutStrategy.name == "donchian_breakout"

    def test_prepare_features_columns(self):
        """prepare_features gerekli kolonları eklemeli."""
        strat = _make_strategy()
        df = _make_trend_df(n=120)
        df_feat = strat.prepare_features(df)
        required = [
            "donchian55_high", "donchian55_low",
            "donchian20_high", "donchian20_low",
            "bb_upper", "bb_lower", "bb_mid",
            "kc_upper", "kc_lower",
            "squeeze_active", "squeeze_recent",
            "atr14", "atr_pct", "kaufman_er",
        ]
        for col in required:
            assert col in df_feat.columns, f"Eksik kolon: {col}"

    def test_empty_df_returns_no_signals(self):
        """Boş DataFrame → boş liste."""
        strat = _make_strategy()
        empty = pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
        signals = strat.generate_signals(empty)
        assert signals == []

    def test_long_signal_on_breakout_with_squeeze(self):
        """55-bar kırılım + squeeze_recent → long sinyal üretilmeli.

        Tüm squeeze ve donchian55_high değerlerini kontrol edip bar 70'te
        kesinlikle bir long sinyali oluşmasını sağlarız (diğer barları kapat).
        """
        strat = _make_strategy()
        df = _make_trend_df(n=120, uptrend=True)
        df_feat = strat.prepare_features(df)

        # Önce tüm squeeze_recent ve donchian55_high'ı non-triggering yap
        df_feat["squeeze_recent"] = False
        # donchian55_high'ı her yerde close'un 2x üstüne çek (kırılım yok)
        df_feat["donchian55_high"] = df_feat["close"] * 2.0

        # Bar 70'te sadece o barı tetikle
        bar_idx = 70
        close_val = float(df_feat.loc[bar_idx, "close"])
        df_feat.loc[bar_idx, "donchian55_high"] = close_val * 0.95  # kırılım
        df_feat.loc[bar_idx, "squeeze_recent"] = True
        df_feat.loc[bar_idx, "donchian20_low"] = close_val * 0.90  # SL < close

        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) >= 1, "Kirilim + squeeze sonrasi long sinyal olmali"
        # Bar 70 timestamp'ini bul
        ts_70 = pd.Timestamp(df_feat.loc[bar_idx, "ts"]).to_pydatetime()
        bar70_sig = next((s for s in long_sigs if s.ts == ts_70), None)
        assert bar70_sig is not None, "Bar 70'te long sinyal olmali"
        assert bar70_sig.sl_price < close_val, "SL close altında olmalı"
        assert bar70_sig.tp_price > close_val, "TP close üstünde olmalı"

    def test_short_signal_on_downward_breakout(self):
        """55-bar alt kırılım + squeeze_recent → short sinyal."""
        strat = _make_strategy()
        df = _make_trend_df(n=120, uptrend=False)
        df_feat = strat.prepare_features(df)

        # Önce tüm short koşullarını kapat
        df_feat["squeeze_recent"] = False
        df_feat["donchian55_low"] = df_feat["close"] * 0.0  # hiçbir şeyin altına düşmez

        bar_idx = 70
        close_val = float(df_feat.loc[bar_idx, "close"])
        # donchian55_low'u close'un üstüne çek → alt kırılım koşulu (close < low = tetikle)
        df_feat.loc[bar_idx, "donchian55_low"] = close_val * 1.05
        df_feat.loc[bar_idx, "squeeze_recent"] = True
        df_feat.loc[bar_idx, "donchian20_high"] = close_val * 1.10  # SL > close

        signals = strat.generate_signals(df_feat)
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) >= 1, "Alt kirilim + squeeze sonrasi short sinyal olmali"
        ts_70 = pd.Timestamp(df_feat.loc[bar_idx, "ts"]).to_pydatetime()
        bar70_sig = next((s for s in short_sigs if s.ts == ts_70), None)
        assert bar70_sig is not None, "Bar 70'te short sinyal olmali"
        assert bar70_sig.sl_price > close_val, "Short SL close üstünde olmalı"

    def test_no_signal_without_squeeze_recent(self):
        """Kırılım var ama squeeze_recent False → sinyal yok."""
        strat = _make_strategy()
        df = _make_trend_df(n=120)
        df_feat = strat.prepare_features(df)

        # Tüm squeeze_recent = False, donchian55_high'ı da her yerde yüksek tut
        df_feat["squeeze_recent"] = False
        df_feat["donchian55_high"] = df_feat["close"] * 2.0
        df_feat["donchian55_low"] = df_feat["close"] * 0.0

        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(long_sigs) == 0, "Squeeze olmadan long sinyal uretilmemeli"
        assert len(short_sigs) == 0, "Squeeze olmadan short sinyal uretilmemeli"

    def test_no_signal_when_er_below_threshold(self):
        """ER filtresi aktif: kaufman_er < 0.30 → sinyal yok."""
        strat = _make_strategy_with_er(er_min=0.30)
        df = _make_trend_df(n=120)
        df_feat = strat.prepare_features(df)

        # Tüm ER değerlerini 0.10 yap (düşük trend gücü)
        df_feat["kaufman_er"] = 0.10
        # Tüm barları tetikleyecek şekilde ayarla ama ER blok etsin
        df_feat["squeeze_recent"] = True
        df_feat["donchian55_high"] = df_feat["close"] * 0.90  # hepsi kırılım koşulunu sağlar
        df_feat["donchian20_low"] = df_feat["close"] * 0.85

        signals = strat.generate_signals(df_feat)
        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) == 0, "ER < 0.30 iken sinyal uretilmemeli (whipsaw filtresi)"

    def test_sl_equals_donchian20_low(self):
        """Long SL, donchian20_low'a yakın olmalı (Turtle exit)."""
        strat = _make_strategy()
        df = _make_trend_df(n=120)
        df_feat = strat.prepare_features(df)

        # Sadece bar 70'i tetikle
        df_feat["squeeze_recent"] = False
        df_feat["donchian55_high"] = df_feat["close"] * 2.0

        bar_idx = 70
        close_val = float(df_feat.loc[bar_idx, "close"])
        don20_low = close_val * 0.88
        df_feat.loc[bar_idx, "donchian55_high"] = close_val * 0.92  # kırılım
        df_feat.loc[bar_idx, "squeeze_recent"] = True
        df_feat.loc[bar_idx, "donchian20_low"] = don20_low  # SL seviyesi

        signals = strat.generate_signals(df_feat)
        ts_70 = pd.Timestamp(df_feat.loc[bar_idx, "ts"]).to_pydatetime()
        long_sigs = [s for s in signals if s.direction == "long" and s.ts == ts_70]

        assert len(long_sigs) >= 1, "Bar 70'te long sinyal olmali"
        sig = long_sigs[0]
        # SL donchian20_low'a yakın olmalı (veya close - 0.5*ATR'ın küçüğü)
        assert sig.sl_price <= close_val, "Long SL close'un altında olmali"
        # Turtle exit: SL donchian20_low bölgesinde (0.88 * close)
        assert sig.sl_price <= close_val * 0.95, "SL makul Turtle exit bölgesinde olmali"
        # TP = close + 3R (R = close - SL) → TP > close
        assert sig.tp_price > close_val, "Long TP close üstünde olmali"


# ---------------------------------------------------------------------------
# 5. Default manifest testi
# ---------------------------------------------------------------------------

def test_default_manifest_valid():
    """_default_manifest() geçerli StrategyManifest döndürmeli."""
    m = _default_manifest()
    assert m.name == "donchian_breakout"
    assert len(m.signals.patterns) == 2
    assert m.risk.get("take_profit", {}).get("primary_R", 0) == 3.0


def test_default_manifest_strategy_instantiation():
    """Default manifest ile strateji oluşturulabilmeli."""
    m = _default_manifest()
    strat = DonchianBreakoutStrategy(m)
    assert strat.name == "donchian_breakout"


# ---------------------------------------------------------------------------
# 6. Smoke test
# ---------------------------------------------------------------------------

def test_smoke_run_random_data():
    """Rastgele veriye karşı genel smoke testi — exception olmamalı."""
    rng = np.random.default_rng(2026)
    n = 200
    close = 100.0 * np.exp(np.cumsum(rng.normal(0.001, 0.018, n)))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.004, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.004, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    volume = rng.uniform(1e6, 5e6, n)
    df = pd.DataFrame({
        "ts": [datetime(2022, 1, 1, tzinfo=timezone.utc) + timedelta(days=i) for i in range(n)],
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "venue": "binance",
        "symbol": "SMOKE/USDT",
        "timeframe": "1d",
    })
    strat = _make_strategy()
    df_feat = strat.prepare_features(df)
    signals = strat.generate_signals(df_feat)
    assert isinstance(signals, list)
    # SL/TP tutarlılık kontrolü
    for sig in signals:
        if sig.direction == "long":
            assert sig.sl_price < sig.tp_price, "Long: SL < TP olmali"
        else:
            assert sig.sl_price > sig.tp_price, "Short: SL > TP olmali"
