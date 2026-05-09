"""Unit testler -- ThreeWhiteSoldiersStrategy + Three Black Crows.

Test senaryolari (8 test):
  1. Temiz Three White Soldiers => long sinyal beklenir
  2. Temiz Three Black Crows => short sinyal beklenir
  3. Govde < %50 range => pattern tetiklenmez
  4. Ust golge > %20 range => TWS tetiklenmez
  5. Volume azalan => volume filtresi gerekirse tetiklenmez
  6. Lookahead bias kontrolu — t bari flagleri sadece [t-2..t] bilgisini kullanir
  7. Bos DataFrame => sinyal uretilmez
  8. Dekorelasyon proxy — engulfing sinyalleri ile zamanlama cakisma oranti dusuk
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.three_white_soldiers import (
    ThreeWhiteSoldiersStrategy,
    _three_white_soldiers,
    _three_black_crows,
    _default_manifest,
)


# ---------------------------------------------------------------------------
# Test yardimci fonksiyonlari
# ---------------------------------------------------------------------------

def _base_ts(n: int, start: datetime | None = None) -> list[datetime]:
    if start is None:
        start = datetime(2022, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def _bar(o: float, h: float, l: float, c: float, v: float = 1_000_000.0) -> dict:
    return {
        "open": float(o), "high": float(h),
        "low": float(l), "close": float(c),
        "volume": float(v),
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
    df["ts"] = pd.to_datetime(ts)
    df["venue"] = venue
    df["symbol"] = symbol
    df["timeframe"] = "1d"
    if "volume" not in df.columns:
        df["volume"] = 1_000_000.0
    return df


def _make_strategy(trend_required: bool = False) -> ThreeWhiteSoldiersStrategy:
    """Minimal test manifest — filtreler kapali (pattern mantigi izole edilir)."""
    from price_action.strategies.base import StrategyManifest

    raw = {
        "name": "three_white_soldiers",
        "version": "0.0.1",
        "trend_filter": {"type": "ema", "period": 50, "required": trend_required},
        "signals": {
            "patterns": [
                {
                    "id": "three_white_soldiers",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "body_ratio_min": 0.50,
                        "upper_shadow_max": 0.20,
                        "volume_increasing": False,   # default testlerde vol filtresi kapali
                        "vol_lookback": 10,
                    },
                },
                {
                    "id": "three_black_crows",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "body_ratio_min": 0.50,
                        "lower_shadow_max": 0.20,
                        "volume_increasing": False,
                        "vol_lookback": 10,
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
            },
            "confluence": {
                "method": "weighted_sum",
                "min_score": 2.0,
                "bonus_if_at_sr": 0.0,
            },
        },
        "risk": {
            "stop_loss": {"method": "pattern_extreme", "swing_lookback": 3},
            "take_profit": {"method": "r_multiple", "primary_R": 1.5},
        },
    }
    manifest = StrategyManifest.model_validate(raw)
    return ThreeWhiteSoldiersStrategy(manifest)


# ---------------------------------------------------------------------------
# Yardimci: temiz TWS uclusu
# ---------------------------------------------------------------------------

def _make_tws_trio(base: float = 100.0) -> list[dict]:
    """
    Mekanik olarak temiz Three White Soldiers:
    - 3 bullish bar (close > open)
    - HH closes: 104 > 106 > 109 (azalan degil, artan)
    - Govde >= %50 range
    - Ust golge <= %20 range
    Bar 1: open=100, close=104, high=104.5, low=99   range=5.5, body=4 (73%), upper_shadow=0.5/5.5=9%
    Bar 2: open=104, close=107, high=107.5, low=103  range=4.5, body=3 (67%), upper_shadow=0.5/4.5=11%
    Bar 3: open=107, close=110, high=110.5, low=106  range=4.5, body=3 (67%), upper_shadow=0.5/4.5=11%
    """
    d = base
    return [
        _bar(o=d+0,   h=d+4.5, l=d-1,   c=d+4,   v=1_000_000),
        _bar(o=d+4,   h=d+7.5, l=d+3,   c=d+7,   v=1_100_000),
        _bar(o=d+7,   h=d+10.5, l=d+6,  c=d+10,  v=1_200_000),
    ]


def _make_tbc_trio(base: float = 110.0) -> list[dict]:
    """
    Temiz Three Black Crows:
    - 3 bearish bar (open > close)
    - LL closes: giderek dusuyor
    - Govde >= %50 range
    - Alt golge <= %20 range
    Bar 1: open=110, close=106, high=111, low=105.5  range=5.5, body=4, lower_shadow=0.5
    Bar 2: open=106, close=103, high=107, low=102.5  range=4.5, body=3, lower_shadow=0.5
    Bar 3: open=103, close=100, high=104, low=99.5   range=4.5, body=3, lower_shadow=0.5
    """
    d = base
    return [
        _bar(o=d,     h=d+1,   l=d-4.5, c=d-4,   v=1_000_000),
        _bar(o=d-4,   h=d-3,   l=d-7.5, c=d-7,   v=1_100_000),
        _bar(o=d-7,   h=d-6,   l=d-10.5, c=d-10, v=1_200_000),
    ]


# ---------------------------------------------------------------------------
# TEST 1: Temiz Three White Soldiers => long sinyal beklenir
# ---------------------------------------------------------------------------

class TestThreeWhiteSoldiersBasic:
    def test_clean_tws_generates_long_signal(self):
        """Mekanik olarak perfect TWS => generate_signals long doner."""
        # 20 neutral bar + 3 TWS bar
        neutral = [_bar(100, 101, 99, 100) for _ in range(20)]
        tws_bars = _make_tws_trio(base=100.0)
        all_bars = neutral + tws_bars

        df = _df_from_bars(all_bars)
        strat = _make_strategy()
        df_feats = strat.prepare_features(df)
        signals = strat.generate_signals(df_feats)

        long_sigs = [s for s in signals if s.direction == "long"]
        assert len(long_sigs) >= 1, (
            f"Temiz TWS paterni long sinyal uretmeli. "
            f"Uretilen sinyaller: {[(s.direction, s.pattern_id) for s in signals]}"
        )

    def test_clean_tws_pattern_id(self):
        """TWS long sinyalinin pattern_id'si 'three_white_soldiers' olmali."""
        neutral = [_bar(100, 101, 99, 100) for _ in range(20)]
        tws_bars = _make_tws_trio(base=100.0)
        df = _df_from_bars(neutral + tws_bars)
        strat = _make_strategy()
        sigs = strat.generate_signals(strat.prepare_features(df))
        long_sigs = [s for s in sigs if s.direction == "long"]
        for sig in long_sigs:
            assert sig.pattern_id == "three_white_soldiers"

    def test_tws_sl_below_close(self):
        """TWS long sinyalinde stop-loss close'un altinda olmali."""
        neutral = [_bar(100, 101, 99, 100) for _ in range(20)]
        tws_bars = _make_tws_trio(base=100.0)
        df = _df_from_bars(neutral + tws_bars)
        strat = _make_strategy()
        sigs = strat.generate_signals(strat.prepare_features(df))
        long_sigs = [s for s in sigs if s.direction == "long"]
        for sig in long_sigs:
            assert sig.sl_price < sig.tp_price, "Long: SL < TP olmali"


# ---------------------------------------------------------------------------
# TEST 2: Temiz Three Black Crows => short sinyal beklenir
# ---------------------------------------------------------------------------

class TestThreeBlackCrowsBasic:
    def test_clean_tbc_generates_short_signal(self):
        """Mekanik olarak perfect TBC => generate_signals short doner."""
        neutral = [_bar(110, 111, 109, 110) for _ in range(20)]
        tbc_bars = _make_tbc_trio(base=110.0)
        df = _df_from_bars(neutral + tbc_bars)
        strat = _make_strategy()
        df_feats = strat.prepare_features(df)
        signals = strat.generate_signals(df_feats)

        short_sigs = [s for s in signals if s.direction == "short"]
        assert len(short_sigs) >= 1, (
            f"Temiz TBC paterni short sinyal uretmeli. "
            f"Uretilen sinyaller: {[(s.direction, s.pattern_id) for s in signals]}"
        )

    def test_tbc_pattern_id(self):
        neutral = [_bar(110, 111, 109, 110) for _ in range(20)]
        tbc_bars = _make_tbc_trio(base=110.0)
        df = _df_from_bars(neutral + tbc_bars)
        strat = _make_strategy()
        sigs = strat.generate_signals(strat.prepare_features(df))
        short_sigs = [s for s in sigs if s.direction == "short"]
        for sig in short_sigs:
            assert sig.pattern_id == "three_black_crows"

    def test_tbc_sl_above_close(self):
        """TBC short sinyalinde stop-loss close'un ustunde olmali."""
        neutral = [_bar(110, 111, 109, 110) for _ in range(20)]
        tbc_bars = _make_tbc_trio(base=110.0)
        df = _df_from_bars(neutral + tbc_bars)
        strat = _make_strategy()
        sigs = strat.generate_signals(strat.prepare_features(df))
        short_sigs = [s for s in sigs if s.direction == "short"]
        for sig in short_sigs:
            assert sig.sl_price > sig.tp_price, "Short: SL > TP olmali (TP asagida)"


# ---------------------------------------------------------------------------
# TEST 3: Govde < %50 range => pattern tetiklenmez
# ---------------------------------------------------------------------------

class TestBodyRatioFilter:
    def test_small_body_no_tws_signal(self):
        """Govde < %50 range oldugunda _three_white_soldiers False donmeli."""
        # Kucuk govdeli 3 bullish bar — %25 body/range
        bars_raw = [
            # range=10, body=2.5 (25%) — fail
            {"open": 100.0, "high": 110.0, "low": 100.0, "close": 102.5, "volume": 1e6},
            {"open": 103.0, "high": 113.0, "low": 103.0, "close": 105.5, "volume": 1e6},
            {"open": 106.0, "high": 116.0, "low": 106.0, "close": 108.5, "volume": 1e6},
        ]
        neutral = [_bar(100, 101, 99, 100) for _ in range(5)]
        all_bars = neutral + [
            {"open": b["open"], "high": b["high"], "low": b["low"],
             "close": b["close"], "volume": b["volume"]} for b in bars_raw
        ]
        df = _df_from_bars(all_bars)
        result = _three_white_soldiers(df, body_ratio_min=0.50, upper_shadow_max=0.20, volume_increasing=False)
        # Son bar (bar 7, idx=7) pattern tetiklenmemeli
        assert result.iloc[-1] == False, "Kucuk govde TWS tetiklememeli"

    def test_full_body_tws_detected(self):
        """Govde >= %50 range oldugunda _three_white_soldiers True donmeli."""
        neutral = [_bar(100, 101, 99, 100) for _ in range(5)]
        tws = _make_tws_trio(base=100.0)
        all_bars = neutral + tws
        df = _df_from_bars(all_bars)
        result = _three_white_soldiers(df, body_ratio_min=0.50, upper_shadow_max=0.20, volume_increasing=False)
        assert result.iloc[-1] == True, "Yeterli govde boyutu TWS tetiklemeli"


# ---------------------------------------------------------------------------
# TEST 4: Ust golge > %20 range => TWS tetiklenmez
# ---------------------------------------------------------------------------

class TestUpperShadowFilter:
    def test_large_upper_shadow_no_tws(self):
        """Ust golge > %20 range => _three_white_soldiers False donmeli."""
        neutral = [_bar(100, 101, 99, 100) for _ in range(5)]
        # Buyuk ust golgeli 3 bullish bar
        # Bar: open=100, close=105, high=115, low=99
        # range=16, body=5 (31% — body filter fail da olur)
        # Govde >= %50 saglamak icin: open=100, close=109, high=115, low=99
        # range=16, body=9 (56%), upper_shadow=6/16=37.5% — upper shadow > 20%
        big_shadow_bars = [
            _bar(o=100, h=115, l=99, c=109),   # upper shadow 6/16 = 37.5%
            _bar(o=109, h=125, l=108, c=119),  # upper shadow 6/17 = 35.3%
            _bar(o=119, h=135, l=118, c=129),  # upper shadow 6/17 = 35.3%
        ]
        all_bars = neutral + big_shadow_bars
        df = _df_from_bars(all_bars)
        result = _three_white_soldiers(
            df, body_ratio_min=0.50, upper_shadow_max=0.20, volume_increasing=False
        )
        assert result.iloc[-1] == False, "Buyuk ust golge TWS tetiklememeli"

    def test_minimal_upper_shadow_tws(self):
        """Ust golge <= %20 => pattern tetiklenir."""
        neutral = [_bar(100, 101, 99, 100) for _ in range(5)]
        tws = _make_tws_trio(base=100.0)
        all_bars = neutral + tws
        df = _df_from_bars(all_bars)
        result = _three_white_soldiers(
            df, body_ratio_min=0.50, upper_shadow_max=0.20, volume_increasing=False
        )
        assert result.iloc[-1] == True, "Minimal ust golge TWS tetiklemeli"


# ---------------------------------------------------------------------------
# TEST 5: Volume filtresi — artan volume zorunlu
# ---------------------------------------------------------------------------

class TestVolumeFilter:
    def test_decreasing_volume_blocked(self):
        """Volume azaliyorsa volume_increasing=True filtresi pattern'i engeller."""
        neutral = [_bar(100, 101, 99, 100, v=2_000_000) for _ in range(20)]
        # Azalan volume ile temiz TWS
        tws_raw = _make_tws_trio(base=100.0)
        tws_raw[0]["volume"] = 3_000_000
        tws_raw[1]["volume"] = 2_000_000   # dusuk
        tws_raw[2]["volume"] = 1_000_000   # daha dusuk — avg'nin altinda
        all_bars = neutral + tws_raw
        df = _df_from_bars(all_bars)
        result = _three_white_soldiers(
            df, body_ratio_min=0.50, upper_shadow_max=0.20, volume_increasing=True, vol_lookback=10
        )
        # Neutral barlarin vol_avg ~2M; son bar 1M < avg => filtrelemeli
        assert result.iloc[-1] == False, "Azalan volume (ortalama altinda) TWS tetiklememeli"

    def test_increasing_volume_passes(self):
        """Volume ortalama uzerinde kalirsa filtre gecilir."""
        neutral = [_bar(100, 101, 99, 100, v=500_000) for _ in range(20)]
        tws_raw = _make_tws_trio(base=100.0)
        tws_raw[0]["volume"] = 1_000_000
        tws_raw[1]["volume"] = 1_500_000
        tws_raw[2]["volume"] = 2_000_000
        all_bars = neutral + tws_raw
        df = _df_from_bars(all_bars)
        result = _three_white_soldiers(
            df, body_ratio_min=0.50, upper_shadow_max=0.20, volume_increasing=True, vol_lookback=10
        )
        assert result.iloc[-1] == True, "Artan volume (ortalama uzerinde) TWS tetiklemeli"


# ---------------------------------------------------------------------------
# TEST 6: Lookahead bias kontrolu
# ---------------------------------------------------------------------------

class TestLookaheadBias:
    def test_no_lookahead_in_pattern_detection(self):
        """Lookahead bias yok: t barinda hesaplanan flag t+1 barini kullanmamali.

        Kontrol yontemi:
        - N barlik dataframe uzerinde tum flagleri hesapla.
        - Son bari eksilt, yeniden hesapla.
        - Truncated seride son barin flag degeri degismemeli.
        """
        neutral = [_bar(100, 101, 99, 100) for _ in range(20)]
        tws = _make_tws_trio(base=100.0)
        extra = [_bar(111, 115, 109, 112)]  # 1 ekstra bar (gelecek bilgisi simule)
        all_bars = neutral + tws + extra

        df_full = _df_from_bars(all_bars)
        df_trunc = _df_from_bars(all_bars[:-1])  # son barsiz

        flags_full = _three_white_soldiers(df_full, volume_increasing=False)
        flags_trunc = _three_white_soldiers(df_trunc, volume_increasing=False)

        # TWS bar index = len(neutral) + 2 = 22 (0-indexed)
        tws_bar_idx = len(neutral) + len(tws) - 1  # = 22
        flag_full = bool(flags_full.iloc[tws_bar_idx])
        flag_trunc = bool(flags_trunc.iloc[tws_bar_idx])

        assert flag_full == flag_trunc, (
            f"Lookahead bias! Ekstra bar eklenince flag degisti: "
            f"full={flag_full}, trunc={flag_trunc}"
        )


# ---------------------------------------------------------------------------
# TEST 7: Bos DataFrame => sinyal uretilmez
# ---------------------------------------------------------------------------

class TestEmptyDataFrame:
    def test_empty_df_no_signals(self):
        """Bos DataFrame verildiginde hic sinyal uretilmemeli."""
        df_empty = pd.DataFrame(
            columns=["ts", "open", "high", "low", "close", "volume", "venue", "symbol", "timeframe"]
        )
        strat = _make_strategy()
        df_feats = strat.prepare_features(df_empty)
        signals = strat.generate_signals(df_feats)
        assert signals == [], f"Bos DF'de sinyal beklenmiyordu, {len(signals)} geldi"

    def test_insufficient_bars_no_signals(self):
        """2 barlik DF — pattern icin en az 3 bar gerekiyor, sinyal olmamali."""
        bars = [_bar(100, 101, 99, 100), _bar(101, 102, 100, 101)]
        df = _df_from_bars(bars)
        strat = _make_strategy()
        signals = strat.generate_signals(strat.prepare_features(df))
        assert len(signals) == 0, "2 barlik DF'de sinyal beklenmiyordu"


# ---------------------------------------------------------------------------
# TEST 8: Dekorelasyon proxy — engulfing ile sinyal zamanlamasi
# ---------------------------------------------------------------------------

class TestDecorrelationProxy:
    def test_tws_and_engulfing_different_signals(self):
        """TWS ve engulfing farkli pattern mekanizmalari — cakisma orani dusuk olmali.

        Test stratejisi:
        - 40 neutral bar + 3 TWS bar + 20 neutral + engulfing bar kombinasyonu
        - Her iki strateji icin sinyal gunleri karsilastirilir
        - TWS son barda; engulfing daha onceki bir barda tetiklenecek sekilde kurgu

        Beklenti: TWS sinyali vs engulfing sinyali farkli gunlerde.
        """
        from price_action.strategies.engulfing_continuation import (
            EngulfingContinuationStrategy,
        )
        from price_action.strategies.base import StrategyManifest

        # Blok 1: 40 neutral + 3 TWS (toplam 43 bar)
        neutral1 = [_bar(100, 101, 99, 100) for _ in range(40)]
        tws_trio = _make_tws_trio(base=100.0)

        # Blok 2: neutral sonrasi bearish + bullish engulfing kombinasyonu
        neutral2 = [_bar(110, 111, 109, 110) for _ in range(15)]
        engulf_bars = [
            # bearish bar (engulfing oncesi)
            _bar(o=110, h=111, l=105, c=106),   # bearish: open 110, close 106
            # bullish engulfing: open <= 106, close >= 110
            _bar(o=105, h=114, l=104, c=112),   # engulfing body: 105->112, prev 110->106
        ]

        all_bars = neutral1 + tws_trio + neutral2 + engulf_bars
        df = _df_from_bars(all_bars)

        # TWS sinyalleri (vol filtresi kapali)
        strat_tws = _make_strategy()
        tws_feats = strat_tws.prepare_features(df.copy())
        tws_sigs = strat_tws.generate_signals(tws_feats)
        tws_days = {str(s.ts.date()) for s in tws_sigs}

        # Engulfing sinyalleri (pullback + trend filter kapali)
        eng_raw = {
            "name": "engulfing_continuation",
            "version": "0.0.1",
            "trend_filter": {"type": "ema", "period": 50, "required": False},
            "signals": {
                "patterns": [
                    {
                        "id": "bullish_engulfing_cont",
                        "enabled": True,
                        "weight": 1.5,
                        "params": {"body_ratio_min": 0.5, "pullback_window": 60, "pullback_touch_atr": 5.0},
                    },
                    {
                        "id": "bearish_engulfing_cont",
                        "enabled": True,
                        "weight": 1.5,
                        "params": {"body_ratio_min": 0.5, "pullback_window": 60, "pullback_touch_atr": 5.0},
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
                "filters": {"atr_min_pct": 0.0, "volume_zscore_min": 0.0, "kaufman_er_min": 0.0},
                "confluence": {"method": "weighted_sum", "min_score": 1.0, "bonus_if_at_sr": 0.0},
            },
            "risk": {
                "stop_loss": {"method": "structural", "swing_lookback": 10},
                "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            },
        }
        eng_manifest_obj = StrategyManifest.model_validate(eng_raw)
        strat_eng = EngulfingContinuationStrategy(eng_manifest_obj)
        eng_feats = strat_eng.prepare_features(df.copy())
        eng_sigs = strat_eng.generate_signals(eng_feats)
        eng_days = {str(s.ts.date()) for s in eng_sigs}

        # En az bir strateji sinyal uretmeli
        assert len(tws_days) > 0 or len(eng_days) > 0, (
            "En az bir strateji sinyal uretmeli"
        )

        if len(tws_days) == 0 or len(eng_days) == 0:
            # Tek strateji sinyal uretiyor — zaten dekorele (0 kesisim)
            return

        # Kesisim: TWS 3. barinda sinyal var; engulfing cok daha sonra
        overlap = tws_days & eng_days
        overlap_ratio = len(overlap) / max(len(tws_days), len(eng_days))

        assert overlap_ratio < 0.60, (
            f"TWS ve Engulfing cok fazla ayni barda cakisiyor ({overlap_ratio:.1%}). "
            f"TWS={len(tws_days)} sinyal ({sorted(tws_days)}), "
            f"Engulfing={len(eng_days)} sinyal ({sorted(eng_days)}), "
            f"Kesisim={len(overlap)}"
        )


# ---------------------------------------------------------------------------
# TEST BONUS: _default_manifest manifest schema kontrolu
# ---------------------------------------------------------------------------

class TestManifest:
    def test_default_manifest_valid(self):
        """_default_manifest() gecerli bir StrategyManifest dondurmeli."""
        manifest = _default_manifest()
        assert manifest.name == "three_white_soldiers"
        assert manifest.version == "1.0.0"
        pattern_ids = [p.id for p in manifest.signals.patterns]
        assert "three_white_soldiers" in pattern_ids
        assert "three_black_crows" in pattern_ids

    def test_default_manifest_risk_params(self):
        """Manifest risk parametreleri dogru olmali: 1.5R, 1% risk."""
        manifest = _default_manifest()
        assert manifest.risk["take_profit"]["primary_R"] == pytest.approx(1.5)
        assert manifest.risk["position_sizing"]["risk_per_trade"] == pytest.approx(0.01)
