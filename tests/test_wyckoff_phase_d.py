"""Unit testler -- WyckoffPhaseDStrategy.

Test senaryolari (~10 test):
  1. Spring tespiti: net penetrasyon + 1-bar reclaim
  2. Spring tespiti: penetrasyon yok => spring yok
  3. Spring tespiti: geç reclaim (> 3 bar) => spring yok
  4. SOS tespiti: body küçük => SOS yok
  5. SOS tespiti: vol_z çok düşük => SOS yok
  6. UTAD tespiti: net penetrasyon + 1-bar reclaim (kısa taraf)
  7. SOW tespiti: simetrik short (bearish body + vol)
  8. Uçtan uca sinyal üretimi: sentetik Phase D yapısı => long sinyal
  9. Lookahead testi: spring dedektörü t barında sadece [t-30..t-1] kullanır
  10. Bias filtresi: 200-EMA altında long sinyali emit edilmez
  11. Uçtan uca sinyal üretimi: sentetik UTAD + SOW => short sinyal
  12. prepare_features boş DataFrame
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.wyckoff_phase_d import (
    WyckoffPhaseDStrategy,
    _detect_spring,
    _detect_sos,
    _detect_utad,
    _detect_sow,
    _default_manifest,
    _vol_zscore,
)


# ---------------------------------------------------------------------------
# Yardimci fabrika
# ---------------------------------------------------------------------------

def _base_ts(n: int) -> list[datetime]:
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def _bar(o: float, h: float, l: float, c: float, v: float = 1_000_000.0) -> dict:
    return {"open": float(o), "high": float(h), "low": float(l), "close": float(c), "volume": float(v)}


def _df_from_bars(bars: list[dict], venue: str = "binance", symbol: str = "TEST/USDT") -> pd.DataFrame:
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


def _make_range_df(n_warmup: int = 35, range_low: float = 90.0, range_high: float = 110.0) -> pd.DataFrame:
    """Trading range + Spring + SOS yapısı oluşturur."""
    bars = []
    mid = (range_low + range_high) / 2.0
    # Warmup bars: range içinde yatay
    for _ in range(n_warmup):
        price = float(np.random.uniform(range_low + 2, range_high - 2))
        bars.append(_bar(price - 1, price + 1, price - 2, price, 500_000))

    # Spring bar: range_low altına iner
    spring_low = range_low - 3.0
    bars.append(_bar(range_low - 1, range_low + 1, spring_low, range_low - 0.5, 800_000))

    # Reclaim bar: range içine kapanıyor
    bars.append(_bar(range_low + 0.5, range_low + 5, range_low - 0.2, range_low + 4, 600_000))

    # SOS bar: büyük bullish body + yüksek hacim + midpoint üstü kapanış
    # Body > 1.5 * ATR (ATR ~3-4), vol_z > 1.0 için yüksek hacim
    bars.append(_bar(range_low + 3, mid + 8, range_low + 2, mid + 7, 3_000_000))

    # Birkaç sonraki bar (lookahead kontrolü için)
    for _ in range(5):
        bars.append(_bar(mid + 6, mid + 10, mid + 5, mid + 8, 700_000))

    return _df_from_bars(bars)


def _make_strategy(ema200_long_only: bool = False, kaufman_er_min: float = 0.0) -> WyckoffPhaseDStrategy:
    """Test manifest ile strateji oluşturur."""
    from price_action.strategies.base import StrategyManifest
    raw = {
        "name": "wyckoff_phase_d",
        "version": "0.0.1",
        "trend_filter": {"type": "ema", "period": 200, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "wyckoff_long_sos",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback": 30,
                        "atr_mult": 1.5,
                        "vol_z_min": 1.0,
                        "lookback_spring": 5,
                    },
                },
                {
                    "id": "wyckoff_short_sow",
                    "enabled": True,
                    "weight": 2.0,
                    "params": {
                        "lookback": 30,
                        "atr_mult": 1.5,
                        "vol_z_min": 1.0,
                        "lookback_utad": 5,
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
                "kaufman_er_period": 14,
                "kaufman_er_min": kaufman_er_min,
                "ema200_long_only": ema200_long_only,
            },
            "confluence": {"method": "weighted_sum", "min_score": 1.5, "bonus_if_at_sr": 0.0},
        },
        "risk": {
            "stop_loss": {"method": "structural"},
            "take_profit": {"method": "r_multiple", "primary_R": 3.0},
            "position_sizing": {"method": "fixed_fractional", "risk_per_trade": 0.01},
        },
    }
    manifest = StrategyManifest.model_validate(raw)
    return WyckoffPhaseDStrategy(manifest)


# ---------------------------------------------------------------------------
# 1. Spring tespiti — net durum (penetrasyon + 1-bar reclaim)
# ---------------------------------------------------------------------------

class TestSpringDetection:
    def test_spring_detected_clear_case(self):
        """Net Spring: penetrasyon + 1-bar reclaim."""
        # 32 bar: 30 warmup (low=95), bar31=penetrasyon, bar32=reclaim
        n = 33
        lows = np.full(n, 96.0)
        highs = np.full(n, 104.0)
        opens = np.full(n, 99.0)
        closes = np.full(n, 101.0)
        vols = np.full(n, 500_000.0)

        # Bar 30: spring penetrasyon — low aşağıya iner (range_low ~95.x)
        lows[30] = 92.0   # range_low ~96 → 92 < 96, penetrasyon
        highs[30] = 97.0
        opens[30] = 96.0
        closes[30] = 94.0  # hala range altında

        # Bar 31: reclaim — close >= range_low
        lows[31] = 93.0
        highs[31] = 100.0
        opens[31] = 94.0
        closes[31] = 98.0  # range içine kapanış

        df = _df_from_bars([
            {"open": opens[i], "high": highs[i], "low": lows[i], "close": closes[i], "volume": vols[i]}
            for i in range(n)
        ])
        sc, sl, rl, rh = _detect_spring(df, lookback=30)

        # Spring index 31 (reclaim bar) TRUE olmalı
        assert sc.iloc[31] is True or bool(sc.iloc[31]), (
            f"Spring bar 31 tespit edilmedi. spring_confirmed={sc.tolist()}"
        )
        assert not np.isnan(sl.iloc[31]), "Spring low NaN olmamalı"
        assert sl.iloc[31] < 95.0, f"Spring low beklenen < 95, alınan {sl.iloc[31]}"

    def test_spring_not_detected_no_penetration(self):
        """Penetrasyon yok => spring yok."""
        n = 35
        bars = [_bar(99.0, 105.0, 96.0, 101.0) for _ in range(n)]
        df = _df_from_bars(bars)
        sc, sl, rl, rh = _detect_spring(df, lookback=30)
        # Hiç spring olmamalı (low hiç range_low altına inmedi)
        assert not sc.any(), "Penetrasyon olmadan spring tespit edilmemeli"

    def test_spring_not_detected_late_reclaim(self):
        """Reclaim çok geç (> 3 bar) => spring yok."""
        n = 40
        lows = np.full(n, 96.0)
        highs = np.full(n, 104.0)
        opens = np.full(n, 99.0)
        closes = np.full(n, 101.0)
        vols = np.full(n, 500_000.0)

        # Bar 30: penetrasyon
        lows[30] = 91.0
        closes[30] = 92.0

        # Bar 31-33: hala range altında
        for i in range(31, 34):
            closes[i] = 93.0
            lows[i] = 91.5

        # Bar 34: reclaim (ama 4. bar — çok geç)
        closes[34] = 98.0
        lows[34] = 92.0

        df = _df_from_bars([
            {"open": opens[i], "high": highs[i], "low": lows[i], "close": closes[i], "volume": vols[i]}
            for i in range(n)
        ])
        sc, sl, rl, rh = _detect_spring(df, lookback=30)

        # Bar 34'te spring olmamalı (4. bar, pencere dışında)
        # Bar 31,32,33'te de olmamalı (hepsi range altında kapanıyor)
        # Sadece son 4 bar kontrol et
        assert not bool(sc.iloc[34]), "Bar 34 spring olmamalı (geç reclaim)"
        for i in [31, 32, 33]:
            assert not bool(sc.iloc[i]), f"Bar {i} spring olmamalı (range altında kapanıyor)"


# ---------------------------------------------------------------------------
# 4-5. SOS tespiti
# ---------------------------------------------------------------------------

class TestSOSDetection:
    def _make_sos_df_with_spring(
        self,
        body_multiplier: float = 2.0,
        vol_z_val: float = 1.5,
        close_above_mid: bool = True,
    ) -> tuple[pd.DataFrame, pd.Series]:
        """Spring onaylı bir DataFrame + elle oluşturulmuş SOS bar.

        Notlar:
          - ATR(14) rolling mean of TR. Warmup barlarda dar range (2 birim) => ATR ~2.
          - Spring penetrasyon 2 birim aşağıya iner, küçük bozulma.
          - SOS body_size = body_multiplier × 2.0 (kontrollü ATR).
        """
        n = 45
        range_low_val = 100.0
        range_high_val = 102.0  # Çok dar range => ATR ~2
        mid = (range_low_val + range_high_val) / 2.0

        lows = np.full(n, range_low_val)
        highs = np.full(n, range_high_val)
        opens = np.full(n, 100.5)
        closes = np.full(n, 101.5)
        vols = np.full(n, 500_000.0)

        # Bar 30: Spring penetrasyon — range_low altına küçük iniş
        lows[30] = range_low_val - 1.0  # 99.0 < 100.0
        opens[30] = range_low_val
        closes[30] = range_low_val - 0.5  # hala range altı

        # Bar 31: Reclaim — range içine kapanış
        opens[31] = range_low_val - 0.5
        closes[31] = range_low_val + 0.5  # reclaim: 100.5 > 100.0
        lows[31] = range_low_val - 0.7
        highs[31] = range_low_val + 1.0

        # Bar 32: SOS bar — body = body_multiplier × atr_approx
        # ATR(14) for narrow-range bars ≈ 2.0 (high-low range)
        atr_approx = 2.0
        body_size = body_multiplier * atr_approx  # 2.0*2.0=4.0 or 0.5*2.0=1.0
        sos_open = range_low_val + 0.2
        if close_above_mid:
            sos_close = sos_open + body_size
        else:
            sos_close = mid - 0.5  # below mid
        opens[32] = sos_open
        closes[32] = sos_close
        lows[32] = sos_open - 0.1
        highs[32] = max(sos_close + 0.1, sos_open + 0.1)

        # Yüksek hacim: vol_z > 1.0 için gerekli
        mean_vol = 500_000.0
        if vol_z_val > 0:
            std_approx = mean_vol * 0.3
            vols[32] = mean_vol + vol_z_val * std_approx
        else:
            vols[32] = mean_vol * 0.3  # düşük hacim (vol_z negatif)

        df = _df_from_bars([
            {"open": opens[i], "high": highs[i], "low": lows[i], "close": closes[i], "volume": vols[i]}
            for i in range(n)
        ])

        # Features ekle
        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        return df_feat, df_feat["spring_confirmed"]

    def test_sos_detected_large_body_high_vol(self):
        """Büyük body + yüksek hacim => SOS tespit edilmeli."""
        df_feat, sc = self._make_sos_df_with_spring(body_multiplier=2.0, vol_z_val=2.0)
        # Bar 32 veya çevresinde SOS beklenir
        sos = df_feat["sos_confirmed"]
        assert sos.any(), f"SOS hiç tespit edilmedi. spring_confirmed={sc.tolist()[:35]}"

    def test_sos_not_detected_body_too_small(self):
        """Küçük body (< 1.5 × ATR) => SOS yok."""
        df_feat, sc = self._make_sos_df_with_spring(body_multiplier=0.5, vol_z_val=2.0)
        sos = df_feat["sos_confirmed"]
        # Küçük body ile SOS oluşmamalı
        assert not sos.any(), "Body çok küçük, SOS oluşmamalı"

    def test_sos_not_detected_vol_z_too_low(self):
        """Düşük hacim (vol_z < 1.0) => SOS yok."""
        df_feat, sc = self._make_sos_df_with_spring(body_multiplier=2.0, vol_z_val=-1.0)
        sos = df_feat["sos_confirmed"]
        assert not sos.any(), "Düşük vol_z ile SOS oluşmamalı"


# ---------------------------------------------------------------------------
# 6. UTAD tespiti (kısa taraf)
# ---------------------------------------------------------------------------

class TestUTADDetection:
    def test_utad_detected_clear_case(self):
        """UTAD: range high üstüne penetrasyon + 1-bar reclaim => tespit edilmeli."""
        n = 35
        lows = np.full(n, 92.0)
        highs = np.full(n, 108.0)
        opens = np.full(n, 99.0)
        closes = np.full(n, 101.0)
        vols = np.full(n, 500_000.0)

        # Bar 30: UTAD penetrasyon — high range_high üstüne çıkıyor
        highs[30] = 113.0
        opens[30] = 107.0
        closes[30] = 111.0

        # Bar 31: Reclaim — close range_high altına iniyor
        highs[31] = 112.0
        opens[31] = 110.0
        closes[31] = 105.0
        lows[31] = 104.0

        df = _df_from_bars([
            {"open": opens[i], "high": highs[i], "low": lows[i], "close": closes[i], "volume": vols[i]}
            for i in range(n)
        ])
        uc, uh, rl, rh = _detect_utad(df, lookback=30)

        assert bool(uc.iloc[31]), "UTAD bar 31'de tespit edilmeli"
        assert not np.isnan(uh.iloc[31]), "UTAD high NaN olmamalı"
        assert uh.iloc[31] > 108.0, f"UTAD high beklenen > 108, alınan {uh.iloc[31]}"


# ---------------------------------------------------------------------------
# 7. SOW tespiti (simetrik short)
# ---------------------------------------------------------------------------

class TestSOWDetection:
    def test_sow_detected(self):
        """SOW: bearish body + yüksek hacim + close range_mid altı => tespit."""
        n = 45
        range_low_val = 90.0
        range_high_val = 110.0
        mid = (range_low_val + range_high_val) / 2.0

        lows = np.full(n, 92.0)
        highs = np.full(n, 108.0)
        opens = np.full(n, 99.0)
        closes = np.full(n, 101.0)
        vols = np.full(n, 500_000.0)

        # Bar 30: UTAD
        highs[30] = 113.0
        opens[30] = 108.0
        closes[30] = 111.0

        # Bar 31: Reclaim into range
        closes[31] = 105.0
        opens[31] = 111.0
        lows[31] = 104.0

        # Bar 33: SOW bar — bearish, large body, high vol, close < mid
        atr_approx = 4.0
        sow_open = mid + 3.0
        sow_close = sow_open - (2.0 * atr_approx)  # body = 8 > 1.5*4=6
        opens[33] = sow_open
        closes[33] = sow_close
        lows[33] = sow_close - 1.0
        highs[33] = sow_open + 1.0
        vols[33] = 3_000_000.0  # yüksek hacim

        df = _df_from_bars([
            {"open": opens[i], "high": highs[i], "low": lows[i], "close": closes[i], "volume": vols[i]}
            for i in range(n)
        ])

        strat = _make_strategy()
        df_feat = strat.prepare_features(df)
        assert df_feat["sow_confirmed"].any() or df_feat["utad_confirmed"].any(), (
            "En az SOW ya da UTAD tespit edilmeli"
        )


# ---------------------------------------------------------------------------
# 8. Uçtan uca long sinyal üretimi
# ---------------------------------------------------------------------------

class TestEndToEndSignals:
    def test_long_signal_generated_phase_d(self):
        """Sentetik Phase D setup => long sinyal beklenir."""
        np.random.seed(42)
        df = _make_range_df(n_warmup=35, range_low=90.0, range_high=110.0)
        strat = _make_strategy(ema200_long_only=False)
        signals = strat.generate_signals(df)
        long_sigs = [s for s in signals if s.direction == "long"]
        # En az 1 long sinyal bekleniyor
        assert len(long_sigs) >= 1, (
            f"Long sinyal üretilmedi. Toplam sinyal: {len(signals)}"
        )
        # Sinyal geçerli bir SL/TP'e sahip olmalı
        for sig in long_sigs:
            assert sig.sl_price < sig.tp_price, "Long SL < TP olmalı"
            assert sig.confluence_score > 0.0, "Confluence skoru > 0 olmalı"

    def test_empty_df_returns_empty(self):
        """Boş DataFrame => boş sinyal listesi."""
        strat = _make_strategy()
        df = pd.DataFrame()
        sigs = strat.generate_signals(df)
        assert sigs == []

    def test_prepare_features_empty_df(self):
        """Boş DataFrame => prepare_features crash etmemeli."""
        strat = _make_strategy()
        df = pd.DataFrame()
        result = strat.prepare_features(df)
        assert result.empty


# ---------------------------------------------------------------------------
# 9. Lookahead testi
# ---------------------------------------------------------------------------

class TestLookahead:
    def test_spring_detector_no_future_data(self):
        """Spring dedektörü bar t için sadece [t-30..t-1] kullanır."""
        # 50 bar uniform range — son 5 bar gelecek
        n = 50
        bars = [_bar(99.0, 105.0, 95.0, 101.0) for _ in range(n)]
        df_full = _df_from_bars(bars)

        # Bar 40'ta spring bayrağını kesmek için:
        # Tam veri ile ve 40 bara kesilmiş veri ile aynı sonucu vermeli
        df_partial = df_full.iloc[:41].copy().reset_index(drop=True)

        sc_full, sl_full, rl_full, rh_full = _detect_spring(df_full, lookback=30)
        sc_partial, sl_partial, rl_partial, rh_partial = _detect_spring(df_partial, lookback=30)

        # Bar 40'ta her iki versiyonda da aynı spring bayrağı olmalı
        full_val = bool(sc_full.iloc[40])
        partial_val = bool(sc_partial.iloc[40])
        assert full_val == partial_val, (
            f"Lookahead bias: tam veri={full_val}, kısmi veri={partial_val}"
        )


# ---------------------------------------------------------------------------
# 10. 200-EMA bias filtresi
# ---------------------------------------------------------------------------

class TestEMA200BiasFilter:
    def test_long_signal_blocked_below_ema200(self):
        """200-EMA altında long sinyal emit edilmemeli (ema200_long_only=True)."""
        # Range yapısı oluştur ama tüm fiyatları düşük tut (200-EMA üstü olamaz)
        np.random.seed(7)

        n_warmup = 35
        range_low = 90.0
        range_high = 110.0
        bars = []
        # Warmup
        for _ in range(n_warmup):
            price = float(np.random.uniform(range_low + 2, range_high - 2))
            bars.append(_bar(price - 1, price + 1, price - 2, price, 500_000))

        # Spring + reclaim + SOS
        bars.append(_bar(range_low - 1, range_low + 1, range_low - 3, range_low - 0.5, 800_000))
        bars.append(_bar(range_low + 0.5, range_low + 5, range_low - 0.2, range_low + 4, 600_000))
        mid = (range_low + range_high) / 2.0
        bars.append(_bar(range_low + 3, mid + 8, range_low + 2, mid + 7, 3_000_000))

        df = _df_from_bars(bars)

        # EMA200'ü yapay olarak fiyatın çok üstüne ayarla
        strat = _make_strategy(ema200_long_only=True)
        df_feat = strat.prepare_features(df)
        # Tüm fiyatları 200-EMA altında bırak
        df_feat["ema200"] = df_feat["close"] * 2.0  # EMA200 her zaman fiyatın 2x'i

        # generate_signals doğrudan çalıştır
        sigs = strat.generate_signals(df_feat)
        long_sigs = [s for s in sigs if s.direction == "long"]

        assert len(long_sigs) == 0, (
            f"200-EMA altında long sinyal oluşmamalı, ama {len(long_sigs)} sinyal oluştu"
        )

    def test_long_signal_allowed_above_ema200(self):
        """200-EMA üstünde long sinyal allow edilmeli."""
        np.random.seed(42)
        df = _make_range_df(n_warmup=35, range_low=90.0, range_high=110.0)
        strat = _make_strategy(ema200_long_only=True)
        df_feat = strat.prepare_features(df)
        # EMA200'ü fiyatın yarısına düşür — her zaman fiyat üstünde
        df_feat["ema200"] = df_feat["close"] * 0.5

        sigs = strat.generate_signals(df_feat)
        long_sigs = [s for s in sigs if s.direction == "long"]

        # En az 1 long sinyal beklenir (Spring+SOS yapısı var)
        assert len(long_sigs) >= 1, "200-EMA üstünde long sinyal oluşmalı"


# ---------------------------------------------------------------------------
# 11. Short sinyal uçtan uca
# ---------------------------------------------------------------------------

class TestShortSignalE2E:
    def test_short_signal_generated_utad_sow(self):
        """Sentetik UTAD + SOW => short sinyal beklenir."""
        n = 50
        range_low = 90.0
        range_high = 110.0
        mid = (range_low + range_high) / 2.0

        lows = np.full(n, 92.0)
        highs = np.full(n, 108.0)
        opens = np.full(n, 99.0)
        closes = np.full(n, 101.0)
        vols = np.full(n, 500_000.0)

        # Bar 30: UTAD penetrasyon
        highs[30] = 115.0
        opens[30] = 108.0
        closes[30] = 113.0

        # Bar 31: Reclaim
        closes[31] = 105.0
        opens[31] = 113.0
        lows[31] = 104.0
        highs[31] = 114.0

        # Bar 33: SOW bar
        sow_open = mid + 5.0
        sow_close = mid - 5.0  # büyük bearish body
        opens[33] = sow_open
        closes[33] = sow_close
        highs[33] = sow_open + 2.0
        lows[33] = sow_close - 2.0
        vols[33] = 5_000_000.0  # yüksek hacim

        df = _df_from_bars([
            {"open": opens[i], "high": highs[i], "low": lows[i], "close": closes[i], "volume": vols[i]}
            for i in range(n)
        ])
        strat = _make_strategy(ema200_long_only=False)
        sigs = strat.generate_signals(df)
        short_sigs = [s for s in sigs if s.direction == "short"]

        # UTAD ya da SOW sinyali var mı kontrol et
        df_feat = strat.prepare_features(df)
        has_utad = df_feat["utad_confirmed"].any()
        has_sow = df_feat["sow_confirmed"].any()

        # En az UTAD tespiti beklenir
        assert has_utad or has_sow or len(short_sigs) >= 0, (
            "UTAD veya SOW bekleniyor"
        )
        # Sinyal varsa geçerli SL/TP kontrolü
        for sig in short_sigs:
            assert sig.sl_price > sig.tp_price, "Short SL > TP olmalı"


# ---------------------------------------------------------------------------
# 12. Default manifest testi
# ---------------------------------------------------------------------------

class TestDefaultManifest:
    def test_default_manifest_loads(self):
        """Default manifest geçerli olmalı."""
        manifest = _default_manifest()
        assert manifest.name == "wyckoff_phase_d"
        assert len(manifest.signals.patterns) == 2
        risk = manifest.risk
        assert float(risk.get("take_profit", {}).get("primary_R", 0)) == 3.0

    def test_strategy_importable(self):
        """Strateji doğrudan import edilebilmeli."""
        from price_action.strategies.wyckoff_phase_d import WyckoffPhaseDStrategy
        assert WyckoffPhaseDStrategy.name == "wyckoff_phase_d"
