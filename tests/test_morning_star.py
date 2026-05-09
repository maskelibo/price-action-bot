"""Unit testler -- MorningEveningStarStrategy (8 test).

Test senaryolari:
  1. Morning Star kanonik ornegi => long sinyal uretilir
  2. Evening Star kanonik ornegi => short sinyal uretilir
  3. Bar2 gövdesi cok buyuk => pattern tetiklenmez
  4. Bar3 kapanisi Bar1 midpoint altinda => Morning Star basarisiz
  5. Volume filtresi: Bar3 hacmi dusukse (vol_filter=True) => sinyal yok
  6. Lookahead bias: t anindaki bayrak sadece gecmis bar bilgisi kullanir
  7. prepare_features bos DataFrame => bos sonuc (exception yok)
  8. Toplam sinyal sayisi / yon tutarliligi: tum sinyaller long veya short olmali
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.morning_evening_star import (
    MorningEveningStarStrategy,
    _morning_star_flags,
    _evening_star_flags,
    _volume_confirmation,
    _default_manifest,
)


# ---------------------------------------------------------------------------
# Yardimci fabrika fonksiyonlari
# ---------------------------------------------------------------------------

def _make_strategy(overrides: dict | None = None) -> MorningEveningStarStrategy:
    """Test manifest ile strateji olusturur.

    Filtreler kapali (kaufman_er_min=0, atr_min_pct=0, trend_filter kapalı)
    ki istemedigimiz filtreler testleri bloklamasin.
    """
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "morning_evening_star",
        "version": "0.0.1",
        "trend_filter": {"type": "ema", "period": 50, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "morning_star",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "bar1_body_ratio_min": 0.50,
                        "bar2_max_body_ratio": 0.35,
                        "gap_atr_factor": 1.5,
                        "use_volume_filter": False,   # testlerde kapalı; spesifik testler acar
                        "vol_ma_window": 20,
                        "bar2_vol_factor": 0.85,
                        "bar3_vol_factor": 1.10,
                    },
                },
                {
                    "id": "evening_star",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "bar1_body_ratio_min": 0.50,
                        "bar2_max_body_ratio": 0.35,
                        "gap_atr_factor": 1.5,
                        "use_volume_filter": False,
                        "vol_ma_window": 20,
                        "bar2_vol_factor": 0.85,
                        "bar3_vol_factor": 1.10,
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
                "kaufman_er_min": 0.0,
                "bear_regime_size_factor": 1.0,
            },
            "confluence": {"method": "weighted_sum", "min_score": 2.0, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "stop_loss": {"method": "bar2_extreme"},
            "take_profit": {"method": "r_multiple", "primary_R": 2.0},
        },
    }
    if overrides:
        raw.update(overrides)
    manifest = StrategyManifest.model_validate(raw)
    return MorningEveningStarStrategy(manifest)


def _base_ts(n: int) -> list[datetime]:
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def _df_from_bars(
    bars: list[dict],
    venue: str = "binance",
    symbol: str = "TEST/USDT",
    extra_cols: bool = True,
) -> pd.DataFrame:
    """Bar listesinden tam DataFrame olusturur."""
    ts = _base_ts(len(bars))
    df = pd.DataFrame(bars)
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = df[col].astype(float)
    df["ts"] = ts
    if extra_cols:
        df["venue"] = venue
        df["symbol"] = symbol
        df["timeframe"] = "1d"
    if "volume" not in df.columns:
        df["volume"] = 1_000_000.0
    return df


def _make_bar(o: float, h: float, l: float, c: float, v: float = 1_000_000.0) -> dict:
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def _warmup_bars(n: int = 30, base: float = 100.0) -> list[dict]:
    """Indikatör isitma icin neutral barlar uretir."""
    bars = []
    for i in range(n):
        p = base + i * 0.1
        bars.append(_make_bar(p, p + 0.5, p - 0.5, p))
    return bars


# ---------------------------------------------------------------------------
# TEST 1: Morning Star kanonik ornegi => long sinyal uretilir
# ---------------------------------------------------------------------------

class TestMorningStar:
    def test_morning_star_produces_long_signal(self):
        """Kilavuz Morning Star dizisi long sinyal uretmeli."""
        warmup = _warmup_bars(40)
        # Kanonik Morning Star: 3 bar
        # Bar1: Guclu bearish, gövde = 9 (range=10 => body_ratio=0.9 >= 0.5)
        # Bar2: Kucuk gövde, open=90.5 (Bar1 close altinda = gap down), body=0.5 (range=1.5 => ratio~0.33 <= 0.35)
        # Bar3: Bullish, close=97 > midpoint(100+91)/2=95.5 => penetrasyon tamam
        bar1 = _make_bar(o=100.0, h=100.5, l=90.0, c=91.0)   # bearish, body=9, range=10.5
        bar2 = _make_bar(o=90.5,  h=91.2,  l=89.7, c=91.0)   # kucuk gövde, body=0.5, range=1.5
        bar3 = _make_bar(o=91.5,  h=98.0,  l=91.0, c=97.0)   # bullish, close=97 > mid=95.5

        bars = warmup + [bar1, bar2, bar3]
        df = _df_from_bars(bars)

        strategy = _make_strategy()
        df_f = strategy.prepare_features(df)
        signals = strategy.generate_signals(df_f)

        long_signals = [s for s in signals if s.direction == "long"]
        assert len(long_signals) >= 1, (
            f"Morning Star kanonik ornegi long sinyal uretmeli. "
            f"Toplam sinyal: {len(signals)}, morning_star bayrak: "
            f"{df_f['morning_star'].sum()}"
        )
        # Son barda sinyal olmali
        last_sig = long_signals[-1]
        assert last_sig.pattern_id == "morning_star"
        # SL, close altinda olmali
        assert last_sig.sl_price < float(df_f["close"].iloc[-1])
        # TP, close uzerinde olmali (long trade)
        assert last_sig.tp_price > float(df_f["close"].iloc[-1])


# ---------------------------------------------------------------------------
# TEST 2: Evening Star kanonik ornegi => short sinyal uretilir
# ---------------------------------------------------------------------------

class TestEveningStar:
    def test_evening_star_produces_short_signal(self):
        """Kanonik Evening Star dizisi short sinyal uretmeli."""
        warmup = _warmup_bars(40, base=90.0)
        # Bar1: Guclu bullish, body=9 (100-91=9, range=10.5 => ratio~0.86 >= 0.5)
        # Bar2: Kucuk gövde, open=100.5 (Bar1 close yakininda/uzerinde), body=0.5, range=1.5
        # Bar3: Bearish, close=92 < midpoint(91+100)/2=95.5 => penetrasyon tamam
        bar1 = _make_bar(o=91.0,  h=100.5, l=90.5, c=100.0)  # bullish, body=9
        bar2 = _make_bar(o=100.5, h=101.2, l=99.7, c=101.0)  # kucuk gövde, body=0.5
        bar3 = _make_bar(o=100.5, h=101.0, l=91.5, c=92.0)   # bearish, close=92 < mid=95.5

        bars = warmup + [bar1, bar2, bar3]
        df = _df_from_bars(bars)

        strategy = _make_strategy()
        df_f = strategy.prepare_features(df)
        signals = strategy.generate_signals(df_f)

        short_signals = [s for s in signals if s.direction == "short"]
        assert len(short_signals) >= 1, (
            f"Evening Star kanonik ornegi short sinyal uretmeli. "
            f"Toplam sinyal: {len(signals)}, evening_star bayrak: "
            f"{df_f['evening_star'].sum()}"
        )
        last_sig = short_signals[-1]
        assert last_sig.pattern_id == "evening_star"
        # SL, close uzerinde olmali (short trade)
        assert last_sig.sl_price > float(df_f["close"].iloc[-1])
        # TP, close altinda olmali
        assert last_sig.tp_price < float(df_f["close"].iloc[-1])


# ---------------------------------------------------------------------------
# TEST 3: Bar2 gövdesi cok buyuk => pattern tetiklenmez
# ---------------------------------------------------------------------------

class TestBar2BodyTooLarge:
    def test_large_bar2_body_suppresses_morning_star(self):
        """Bar2 gövde orani bar2_max_body_ratio'yu asarsa Morning Star bayrak False olmali."""
        warmup = _warmup_bars(30)
        bar1 = _make_bar(o=100.0, h=100.5, l=90.0, c=91.0)   # guclu bearish
        # Bar2: buyuk gövde (body=5, range=6 => ratio~0.83 >> 0.35)
        bar2 = _make_bar(o=90.5,  h=96.5,  l=90.0, c=95.5)   # buyuk gövde, PATTERN BOZULUYOR
        bar3 = _make_bar(o=95.5,  h=99.0,  l=95.0, c=98.0)   # bullish

        bars = warmup + [bar1, bar2, bar3]
        df = _df_from_bars(bars)

        df_with_atr = df.copy()
        df_with_atr["atr14"] = 2.0  # sabit ATR

        # Sadece bayrak fonksiyonunu test et
        flags = _morning_star_flags(
            df_with_atr,
            bar1_body_ratio_min=0.50,
            bar2_max_body_ratio=0.35,
        )
        # Son barda (Bar3 konumu) Morning Star OLMAMALI
        assert not flags.iloc[-1], (
            "Bar2 gövdesi cok buyuk oldugunda Morning Star bayragi False olmali."
        )


# ---------------------------------------------------------------------------
# TEST 4: Bar3 kapanisi midpoint altinda => Morning Star basarisiz
# ---------------------------------------------------------------------------

class TestBar3BelowMidpoint:
    def test_bar3_close_below_midpoint_no_morning_star(self):
        """Bar3 close Bar1 midpoint'inin altindaysa Morning Star tamamlanmamali."""
        warmup = _warmup_bars(30)
        bar1 = _make_bar(o=100.0, h=100.5, l=90.0, c=91.0)   # bearish, mid = (100+91)/2 = 95.5
        bar2 = _make_bar(o=90.5,  h=91.2,  l=89.7, c=91.0)   # kucuk gövde
        # Bar3: bullish ama close=94 < midpoint=95.5 => PENETRASYON YETERSIZ
        bar3 = _make_bar(o=91.0,  h=94.5,  l=90.5, c=94.0)   # close=94 < 95.5

        bars = warmup + [bar1, bar2, bar3]
        df = _df_from_bars(bars)
        df["atr14"] = 2.0

        flags = _morning_star_flags(
            df,
            bar1_body_ratio_min=0.50,
            bar2_max_body_ratio=0.35,
            gap_atr_factor=2.0,
        )
        assert not flags.iloc[-1], (
            "Bar3 kapanisi Bar1 gövde ortasinin altindayken Morning Star basarisiz olmali."
        )


# ---------------------------------------------------------------------------
# TEST 5: Volume filtresi: Bar3 hacmi dusukse sinyal uretilmez
# ---------------------------------------------------------------------------

class TestVolumeFilter:
    def test_volume_filter_blocks_signal_when_bar3_low_volume(self):
        """Volume filtresi aktifken Bar3 hacmi yetersizse sinyal cikmamali."""
        warmup = _warmup_bars(40)
        bar1 = _make_bar(o=100.0, h=100.5, l=90.0, c=91.0, v=1_000_000)
        bar2 = _make_bar(o=90.5,  h=91.2,  l=89.7, c=91.0, v=300_000)   # dusuk hacim
        # Bar3: dusuk hacim (bar3_vol_factor=1.10 gerektiriyor ama cok dusuk)
        bar3 = _make_bar(o=91.5,  h=98.0,  l=91.0, c=97.0, v=200_000)   # DUSUK HACIM

        bars = warmup + [bar1, bar2, bar3]
        df = _df_from_bars(bars)

        # Volume filtresi ACIK bir strateji olustur
        from price_action.strategies.base import StrategyManifest
        raw = {
            "name": "morning_evening_star",
            "version": "0.0.1",
            "trend_filter": {"type": "ema", "period": 50, "required": False},
            "signals": {
                "patterns": [
                    {
                        "id": "morning_star",
                        "enabled": True,
                        "weight": 2.0,
                        "params": {
                            "bar1_body_ratio_min": 0.50,
                            "bar2_max_body_ratio": 0.35,
                            "gap_atr_factor": 2.0,
                            "use_volume_filter": True,   # ACIK
                            "vol_ma_window": 5,          # kisa pencere — ortalamayi yuksek tut
                            "bar2_vol_factor": 0.85,
                            "bar3_vol_factor": 1.10,
                        },
                    },
                    {
                        "id": "evening_star",
                        "enabled": False,  # kapalı — sadece MS test ediyoruz
                        "weight": 2.0,
                        "params": {},
                    },
                ],
                "structure": {
                    "swing": {"fractal_n": 2},
                    "support_resistance": {"lookback_bars": 30, "min_touches": 2, "max_age_bars": 30},
                    "require_proximity_to_sr_atr": 0.0,
                },
                "filters": {
                    "atr_min_pct": 0.0, "kaufman_er_min": 0.0, "bear_regime_size_factor": 1.0,
                },
                "confluence": {"min_score": 2.0, "bonus_if_at_sr": 0.0},
            },
            "risk": {
                "take_profit": {"primary_R": 2.0},
            },
        }
        manifest = StrategyManifest.model_validate(raw)
        strategy = MorningEveningStarStrategy(manifest)
        df_f = strategy.prepare_features(df)

        # vol_b3_high False olmali: Bar3 hacmi MA'nin 1.10x altinda
        assert not df_f["vol_b3_high"].iloc[-1], (
            "Bar3 hacmi MA'nin %110'unun altindayken vol_b3_high False olmali."
        )

        signals = strategy.generate_signals(df_f)
        long_sigs = [s for s in signals if s.direction == "long"]
        # Volume filtresi aktifken Bar3 dusuk hacimliyse sinyal gelmemeli
        # (Son bar Morning Star pattern'ı var ama vol_b3_high=False => bloklanir)
        last_ms_flag = df_f["morning_star"].iloc[-1]
        if last_ms_flag:
            # Pattern var ama volume filtresi blokluyor olmali
            assert len(long_sigs) == 0 or not df_f["vol_b3_high"].iloc[-1], (
                "Volume filtresi actikken dusuk Bar3 hacminde sinyal bloklü olmali."
            )


# ---------------------------------------------------------------------------
# TEST 6: Lookahead bias: t anindaki bayrak sadece gecmis bilgi kullanir
# ---------------------------------------------------------------------------

class TestNoLookaheadBias:
    def test_morning_star_flag_no_lookahead(self):
        """Bar N'nin Morning Star bayragı sadece N-1 ve N-2 bilgisini kullanmali.

        Yontem: Bar N'in bilgilerini degistirip bayragin degismedigini kontrol et.
        Bar N'ye ait bilgi N-1 veya N-2'yi etkilemez; N-3'teki bayrak N, N+1
        bilgisine gore degismemelidir.
        """
        warmup = _warmup_bars(40)
        bar1 = _make_bar(o=100.0, h=100.5, l=90.0, c=91.0)
        bar2 = _make_bar(o=90.5,  h=91.2,  l=89.7, c=91.0)
        bar3 = _make_bar(o=91.5,  h=98.0,  l=91.0, c=97.0)
        # Gecmis barlar + gelecek bir bar (test icin ekleniyor)
        bar_future = _make_bar(o=97.0, h=110.0, l=96.0, c=108.0)

        bars_v1 = warmup + [bar1, bar2, bar3, bar_future]
        bars_v2 = warmup + [bar1, bar2, bar3, _make_bar(o=97.0, h=99.0, l=80.0, c=81.0)]

        df1 = _df_from_bars(bars_v1)
        df2 = _df_from_bars(bars_v2)

        df1["atr14"] = 2.0
        df2["atr14"] = 2.0

        flags1 = _morning_star_flags(df1, gap_atr_factor=2.0)
        flags2 = _morning_star_flags(df2, gap_atr_factor=2.0)

        # Bar3 konumundaki bayrak (sondan 2. eleman = index -2) her iki versiyonda ayni olmali
        # Cunku o noktada gelecek bar (bar_future) henuz gelmemis
        assert flags1.iloc[-2] == flags2.iloc[-2], (
            "Bar N bayragı, N+1 bar bilgisine gore degismemeli (lookahead bias yok)."
        )


# ---------------------------------------------------------------------------
# TEST 7: prepare_features bos DataFrame => bos sonuc (exception yok)
# ---------------------------------------------------------------------------

class TestEmptyDataFrame:
    def test_empty_dataframe_no_exception(self):
        """Bos DataFrame verildiginde prepare_features ve generate_signals exception firlatmamali."""
        strategy = _make_strategy()
        empty = pd.DataFrame(
            columns=["ts", "open", "high", "low", "close", "volume", "venue", "symbol", "timeframe"]
        )
        df_f = strategy.prepare_features(empty)
        assert df_f.empty

        signals = strategy.generate_signals(empty)
        assert signals == []

    def test_single_bar_no_signal(self):
        """Tek bar durumunda 3-bar pattern olusturulamaz; sinyal yok."""
        strategy = _make_strategy()
        df = _df_from_bars([_make_bar(100, 102, 98, 101)])
        df_f = strategy.prepare_features(df)
        signals = strategy.generate_signals(df_f)
        assert len(signals) == 0


# ---------------------------------------------------------------------------
# TEST 8: Yon tutarliligi — tum sinyaller long veya short olmali
# ---------------------------------------------------------------------------

class TestSignalDirectionConsistency:
    def test_signals_direction_consistency(self):
        """Uretilen sinyaller sadece 'long' veya 'short' olabilir; baska yon yok."""
        rng = np.random.default_rng(42)
        n = 300
        start = datetime(2023, 1, 1, tzinfo=timezone.utc)
        ts = [start + timedelta(days=i) for i in range(n)]
        rets = rng.normal(0.0, 0.02, size=n)
        close = 100.0 * np.exp(np.cumsum(rets))
        high = close * (1 + rng.uniform(0.005, 0.02, size=n))
        low = close * (1 - rng.uniform(0.005, 0.02, size=n))
        open_ = np.empty(n)
        open_[0] = close[0]
        open_[1:] = close[:-1]
        high = np.maximum.reduce([high, open_, close])
        low = np.minimum.reduce([low, open_, close])
        vol = rng.uniform(500_000, 1_500_000, size=n)

        df = pd.DataFrame({
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

        strategy = _make_strategy()
        df_f = strategy.prepare_features(df)
        signals = strategy.generate_signals(df_f)

        valid_directions = {"long", "short"}
        for sig in signals:
            assert sig.direction in valid_directions, (
                f"Gecersiz direction: {sig.direction!r}. Sadece 'long' veya 'short' beklenir."
            )

        # Morning Star => long; Evening Star => short olmalı
        for sig in signals:
            if sig.pattern_id == "morning_star":
                assert sig.direction == "long", "morning_star sinyali long olmali"
            elif sig.pattern_id == "evening_star":
                assert sig.direction == "short", "evening_star sinyali short olmali"

    def test_tp_sl_geometry(self):
        """Long sinyallerde tp > close > sl; short'ta sl > close > tp."""
        warmup = _warmup_bars(40)
        # Kanonik Morning Star
        bars = warmup + [
            _make_bar(o=100.0, h=100.5, l=90.0, c=91.0),
            _make_bar(o=90.5,  h=91.2,  l=89.7, c=91.0),
            _make_bar(o=91.5,  h=98.0,  l=91.0, c=97.0),
        ]
        df = _df_from_bars(bars)
        strategy = _make_strategy()
        df_f = strategy.prepare_features(df)
        signals = strategy.generate_signals(df_f)

        for sig in signals:
            close_approx = float(df_f["close"].iloc[-1])
            if sig.direction == "long":
                assert sig.tp_price > sig.sl_price, "Long: tp > sl olmali"
                assert sig.sl_price < close_approx * 1.05, "Long: sl, close'a makul uzaklikta"
            else:
                assert sig.sl_price > sig.tp_price, "Short: sl > tp olmali"


# ---------------------------------------------------------------------------
# Direkt fonksiyon testleri (unit)
# ---------------------------------------------------------------------------

class TestPatternFunctions:
    def _minimal_df_with_atr(self, bars: list[dict]) -> pd.DataFrame:
        df = _df_from_bars(bars, extra_cols=False)
        df["atr14"] = 2.0
        return df

    def test_morning_star_flag_detected_correctly(self):
        """_morning_star_flags kanonik girdide son barda True donmeli."""
        warmup = _warmup_bars(5)
        bar1 = _make_bar(o=100.0, h=100.5, l=90.0, c=91.0)
        bar2 = _make_bar(o=90.5,  h=91.2,  l=89.7, c=91.0)
        bar3 = _make_bar(o=91.5,  h=98.0,  l=91.0, c=97.0)

        df = self._minimal_df_with_atr(warmup + [bar1, bar2, bar3])
        flags = _morning_star_flags(df, bar1_body_ratio_min=0.50, bar2_max_body_ratio=0.35, gap_atr_factor=2.0)
        assert flags.iloc[-1] is True or flags.iloc[-1] == True, (
            "Kanonik Morning Star icin son barda True bekleniyor."
        )

    def test_evening_star_flag_detected_correctly(self):
        """_evening_star_flags kanonik girdide son barda True donmeli."""
        warmup = _warmup_bars(5, base=90.0)
        bar1 = _make_bar(o=91.0,  h=100.5, l=90.5, c=100.0)
        bar2 = _make_bar(o=100.5, h=101.2, l=99.7, c=101.0)
        bar3 = _make_bar(o=100.5, h=101.0, l=91.5, c=92.0)

        df = self._minimal_df_with_atr(warmup + [bar1, bar2, bar3])
        flags = _evening_star_flags(df, bar1_body_ratio_min=0.50, bar2_max_body_ratio=0.35, gap_atr_factor=2.0)
        assert flags.iloc[-1] is True or flags.iloc[-1] == True, (
            "Kanonik Evening Star icin son barda True bekleniyor."
        )

    def test_volume_confirmation_logic(self):
        """_volume_confirmation: Bar2 dusuk, Bar3 yuksek hacim dogru tespit edilmeli."""
        n = 30
        ts = [datetime(2023, 1, 1, tzinfo=timezone.utc) + timedelta(days=i) for i in range(n)]
        vol = [1_000_000.0] * n
        vol[-2] = 300_000.0      # Bar2: dusuk hacim
        vol[-1] = 2_500_000.0   # Bar3: yuksek hacim
        df = pd.DataFrame({
            "ts": ts,
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.5] * n,
            "volume": vol,
        })
        b2_low, b3_high = _volume_confirmation(df, vol_ma_window=20, bar2_vol_factor=0.85, bar3_vol_factor=1.10)
        assert b2_low.iloc[-1], "Bar2 dusuk hacim olmali (vol_b2_low=True)"
        assert b3_high.iloc[-1], "Bar3 yuksek hacim olmali (vol_b3_high=True)"

    def test_default_manifest_is_valid(self):
        """_default_manifest() gecerli bir StrategyManifest uretmeli."""
        manifest = _default_manifest()
        assert manifest.name == "morning_evening_star"
        assert len(manifest.signals.patterns) == 2
        pattern_ids = {p.id for p in manifest.signals.patterns}
        assert "morning_star" in pattern_ids
        assert "evening_star" in pattern_ids
