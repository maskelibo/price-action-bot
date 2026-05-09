"""Unit testler — VSAClimaxTestStrategy.

Test senaryolari (8 test):
  1. Selling Climax tespiti: genis bar + klimaktik hacim + ust kapanis + 5-bar min low
  2. Selling Climax yok: dar bar => SC degil
  3. Selling Climax yok: dusuk hacim => SC degil
  4. Test Bar tespiti: SC sonrasi 3-15 bar, SC low'una yakin + dusuk hacim + dar spread
  5. Test Bar yok: yuksek hacim => TB degil
  6. Long sinyal uretimi: SC + Test Bar + yesil onay bari => long sinyal
  7. Short sinyal uretimi: BC + Up Thrust + kirmizi onay bari => short sinyal
  8. prepare_features bos DataFrame
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.vsa_climax_test import (
    VSAClimaxTestStrategy,
    _detect_selling_climax,
    _detect_buying_climax,
    _detect_test_bar_after_sc,
    _detect_up_thrust_after_bc,
    _default_manifest,
    _vol_sma,
    _spread,
)


# ---------------------------------------------------------------------------
# Yardimci fabrika
# ---------------------------------------------------------------------------

def _base_ts(n: int) -> list[datetime]:
    start = datetime(2023, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(days=i) for i in range(n)]


def _bar(o: float, h: float, l: float, c: float, v: float = 1_000_000.0) -> dict:
    return {
        "open": float(o),
        "high": float(h),
        "low": float(l),
        "close": float(c),
        "volume": float(v),
    }


def _df_from_bars(
    bars: list[dict],
    venue: str = "binance",
    symbol: str = "TEST/USDT",
) -> pd.DataFrame:
    ts_list = _base_ts(len(bars))
    df = pd.DataFrame(bars)
    for col in ["open", "high", "low", "close", "volume"]:
        if col not in df.columns:
            df[col] = 1_000_000.0 if col == "volume" else 100.0
        df[col] = df[col].astype(float)
    df["ts"] = ts_list
    df["venue"] = venue
    df["symbol"] = symbol
    df["timeframe"] = "1d"
    return df


def _make_strategy() -> VSAClimaxTestStrategy:
    manifest = _default_manifest()
    return VSAClimaxTestStrategy(manifest)


def _add_features(bars: list[dict]) -> pd.DataFrame:
    """Barlari DataFrame'e cevir ve features ekle."""
    df = _df_from_bars(bars)
    strat = _make_strategy()
    return strat.prepare_features(df)


# ---------------------------------------------------------------------------
# Selling Climax tespiti icin yardimci bar olusturucular
# ---------------------------------------------------------------------------

def _normal_bar(price: float = 100.0, vol: float = 500_000.0) -> dict:
    """Standart normal bar: spread ~2, hacim ortalama."""
    return _bar(price, price + 1, price - 1, price, vol)


def _make_sc_setup(
    n_warmup: int = 25,
    normal_vol: float = 500_000.0,
    sc_spread_mult: float = 3.0,
    sc_vol_mult: float = 3.0,
    sc_close_pos: float = 0.70,
) -> tuple[list[dict], int]:
    """SC warmup + SC bari olusturur.

    Returns
    -------
    (bars, sc_index)
    """
    bars = []
    base_price = 100.0
    # Warmup: normal barlar (ortalama spread ~2, hacim normal_vol)
    for i in range(n_warmup):
        price = base_price + np.random.uniform(-0.5, 0.5)
        bars.append(_bar(price - 1, price + 1, price - 1, price, normal_vol))

    # SC bar: vol_sma ~normal_vol, ATR ~2
    # spread > 1.5 * ATR: spread = sc_spread_mult * ATR = 3.0 * 2 = 6
    # volume > 2.5 * vol_sma: vol = sc_vol_mult * normal_vol
    # close > 50% range: close = low + sc_close_pos * spread
    atr_approx = 2.0
    sc_spread = sc_spread_mult * atr_approx
    sc_low = base_price - sc_spread / 2
    sc_high = base_price + sc_spread / 2
    sc_close = sc_low + sc_close_pos * sc_spread
    sc_vol = sc_vol_mult * normal_vol

    bars.append(_bar(base_price, sc_high, sc_low, sc_close, sc_vol))
    sc_index = len(bars) - 1
    return bars, sc_index


# ---------------------------------------------------------------------------
# Test 1: Selling Climax tespiti - net durum
# ---------------------------------------------------------------------------

class TestSellingClimaxDetection:
    def test_sc_detected_clear_case(self):
        """SC: genis bar + klimaktik hacim + ust kapanis + 5-bar min low."""
        np.random.seed(42)
        bars, sc_idx = _make_sc_setup(n_warmup=25, sc_spread_mult=3.0, sc_vol_mult=3.5)
        df = _add_features(bars)

        # SC barinda sc_flag True olmali
        sc_at_idx = df["sc_flag"].iloc[sc_idx]
        assert bool(sc_at_idx), (
            f"SC tespit edilmedi (bar {sc_idx}). "
            f"spread={df['high'].iloc[sc_idx]-df['low'].iloc[sc_idx]:.2f}, "
            f"atr20={df['atr20'].iloc[sc_idx]:.2f}, "
            f"vol={bars[sc_idx]['volume']:.0f}, vol_sma={df['vol_sma20'].iloc[sc_idx]:.0f}"
        )

    # ------------------------------------------------------------------
    # Test 2: Dar bar => SC degil
    # ------------------------------------------------------------------

    def test_sc_not_detected_narrow_spread(self):
        """Dar spread => SC degil."""
        np.random.seed(7)
        normal_vol = 500_000.0
        base_price = 100.0
        bars = []
        # 25 warmup
        for _ in range(25):
            bars.append(_bar(base_price - 1, base_price + 1, base_price - 1, base_price, normal_vol))

        # Dar bar: spread = 0.5 (< 1.5 * ATR ~2.0)
        sc_vol = 3.5 * normal_vol
        bars.append(_bar(base_price, base_price + 0.25, base_price - 0.25, base_price + 0.2, sc_vol))

        df = _add_features(bars)
        sc_at_idx = df["sc_flag"].iloc[-1]
        assert not bool(sc_at_idx), "Dar spread ile SC olmamali"

    # ------------------------------------------------------------------
    # Test 3: Dusuk hacim => SC degil
    # ------------------------------------------------------------------

    def test_sc_not_detected_low_volume(self):
        """Dusuk hacim => SC degil."""
        np.random.seed(11)
        normal_vol = 500_000.0
        base_price = 100.0
        bars = []
        for _ in range(25):
            bars.append(_bar(base_price - 1, base_price + 1, base_price - 1, base_price, normal_vol))

        # Genis bar ama dusuk hacim (< 2.5 × SMA)
        low_vol = 0.5 * normal_vol
        sc_spread = 6.0  # genis
        sc_low = base_price - 3.0
        sc_close = sc_low + 0.7 * sc_spread
        bars.append(_bar(base_price, base_price + 3.0, sc_low, sc_close, low_vol))

        df = _add_features(bars)
        sc_at_idx = df["sc_flag"].iloc[-1]
        assert not bool(sc_at_idx), "Dusuk hacim ile SC olmamali"


# ---------------------------------------------------------------------------
# Test 4: Test Bar tespiti
# ---------------------------------------------------------------------------

class TestTestBarDetection:
    def _make_sc_plus_test_bar(
        self,
        wait_bars: int = 5,
        tb_vol_mult: float = 0.40,  # < 0.60 -> dusuk hacim
        tb_spread_mult: float = 0.50,  # < 0.80 -> dar
        tb_close_pos: float = 0.70,  # > 0.50 -> ust yari
    ) -> tuple[pd.DataFrame, int]:
        """SC + Test Bar yapisini olusturur."""
        np.random.seed(42)
        normal_vol = 500_000.0
        base_price = 100.0
        bars = []

        # 25 warmup
        for _ in range(25):
            bars.append(_bar(base_price - 1, base_price + 1, base_price - 1, base_price, normal_vol))

        # SC bar (index 25)
        atr_approx = 2.0
        sc_spread = 3.0 * atr_approx
        sc_low = base_price - sc_spread / 2
        sc_high = base_price + sc_spread / 2
        sc_close = sc_low + 0.70 * sc_spread
        sc_vol = 3.5 * normal_vol
        bars.append(_bar(base_price, sc_high, sc_low, sc_close, sc_vol))

        # wait_bars arasi barlar (konsolidasyon)
        recovery = sc_close + 1.0
        for _ in range(wait_bars):
            bars.append(_bar(recovery - 0.5, recovery + 1, recovery - 1, recovery, normal_vol * 0.8))

        # Test Bar: SC low'una yakin, dusuk hacim, dar spread, ust kapanis
        tb_low = sc_low + 0.005 * sc_low  # SC low'unun %0.5 ustunde -> tolerance icinde
        tb_spread = tb_spread_mult * atr_approx
        tb_high = tb_low + tb_spread
        tb_close = tb_low + tb_close_pos * tb_spread
        tb_vol = tb_vol_mult * normal_vol
        bars.append(_bar(tb_low + 0.5 * tb_spread, tb_high, tb_low, tb_close, tb_vol))
        tb_index = len(bars) - 1

        df = _add_features(bars)
        return df, tb_index

    def test_test_bar_detected(self):
        """SC sonrasi (5 bar sonra) Test Bar tespiti."""
        df, tb_idx = self._make_sc_plus_test_bar(wait_bars=5)
        tb_at_idx = df["test_bar_flag"].iloc[tb_idx]
        assert bool(tb_at_idx), (
            f"Test Bar tespit edilmedi (bar {tb_idx}). "
            f"sc_flag any={df['sc_flag'].any()}, "
            f"test_bar_flag any={df['test_bar_flag'].any()}"
        )

    # ------------------------------------------------------------------
    # Test 5: Yuksek hacim => TB degil
    # ------------------------------------------------------------------

    def test_test_bar_not_detected_high_volume(self):
        """Test Bar yuksek hacimle gelirse TB degil."""
        np.random.seed(42)
        normal_vol = 500_000.0
        base_price = 100.0
        bars = []
        for _ in range(25):
            bars.append(_bar(base_price - 1, base_price + 1, base_price - 1, base_price, normal_vol))

        # SC
        atr_approx = 2.0
        sc_spread = 3.0 * atr_approx
        sc_low = base_price - sc_spread / 2
        sc_high = base_price + sc_spread / 2
        sc_close = sc_low + 0.70 * sc_spread
        sc_vol = 3.5 * normal_vol
        bars.append(_bar(base_price, sc_high, sc_low, sc_close, sc_vol))

        # 5 konsolidasyon
        recovery = sc_close + 1.0
        for _ in range(5):
            bars.append(_bar(recovery - 0.5, recovery + 1, recovery - 1, recovery, normal_vol * 0.8))

        # Yuksek hacimli "test bar" — vol > 0.6 * SMA
        tb_low = sc_low + 0.005 * sc_low
        tb_spread = 0.5 * atr_approx
        tb_high = tb_low + tb_spread
        tb_close = tb_low + 0.70 * tb_spread
        high_vol = 2.0 * normal_vol  # > 0.6 * SMA => TB degil
        bars.append(_bar(tb_low + 0.5 * tb_spread, tb_high, tb_low, tb_close, high_vol))

        df = _add_features(bars)
        assert not bool(df["test_bar_flag"].iloc[-1]), "Yuksek hacimle Test Bar olmamali"


# ---------------------------------------------------------------------------
# Test 6: Long sinyal uretimi — SC + Test Bar + yesil onay bari
# ---------------------------------------------------------------------------

class TestLongSignalE2E:
    def test_long_signal_generated(self):
        """SC + Test Bar + yesil onay bari => long sinyal beklenir."""
        np.random.seed(99)
        normal_vol = 500_000.0
        base_price = 100.0
        bars = []

        # 25 warmup
        for _ in range(25):
            bars.append(_bar(base_price - 1, base_price + 1, base_price - 1, base_price, normal_vol))

        # SC (index 25)
        atr_approx = 2.0
        sc_spread = 3.5 * atr_approx
        sc_low = base_price - sc_spread / 2
        sc_high = base_price + sc_spread / 2
        sc_close = sc_low + 0.65 * sc_spread
        sc_vol = 4.0 * normal_vol
        bars.append(_bar(base_price, sc_high, sc_low, sc_close, sc_vol))

        # 5 konsolidasyon bari
        recovery = sc_close + 1.5
        for _ in range(5):
            bars.append(_bar(recovery - 0.5, recovery + 1, recovery - 1, recovery, normal_vol * 0.7))

        # Test Bar (index 31)
        tb_low = sc_low + 0.005 * sc_low
        tb_spread = 0.4 * atr_approx
        tb_high = tb_low + tb_spread
        tb_close = tb_low + 0.70 * tb_spread
        tb_vol = 0.35 * normal_vol
        bars.append(_bar(tb_low + 0.5 * tb_spread, tb_high, tb_low, tb_close, tb_vol))

        # Yesil onay bari (index 32): close > open
        bars.append(_bar(recovery, recovery + 3, recovery - 0.5, recovery + 2.5, normal_vol))

        df = _df_from_bars(bars)
        strat = _make_strategy()
        sigs = strat.generate_signals(df)

        long_sigs = [s for s in sigs if s.direction == "long"]
        assert len(long_sigs) >= 1, (
            f"Long sinyal uretilmedi. Toplam sinyal: {len(sigs)}. "
            f"sc_flag: {strat.prepare_features(df)['sc_flag'].sum()}, "
            f"test_bar: {strat.prepare_features(df)['test_bar_flag'].sum()}, "
            f"long_confirm: {strat.prepare_features(df)['long_confirm'].sum()}"
        )

        # Sinyal gecerliligi
        for sig in long_sigs:
            assert sig.sl_price < sig.tp_price, "Long SL < TP olmali"
            assert sig.confluence_score > 0.0
            assert sig.pattern_id == "vsa_sc_test_long"


# ---------------------------------------------------------------------------
# Test 7: Short sinyal uretimi — BC + Up Thrust + kirmizi onay bari
# ---------------------------------------------------------------------------

class TestShortSignalE2E:
    def test_short_signal_generated(self):
        """BC + Up Thrust + kirmizi onay bari => short sinyal beklenir."""
        np.random.seed(77)
        normal_vol = 500_000.0
        base_price = 100.0
        bars = []

        # 25 warmup
        for _ in range(25):
            bars.append(_bar(base_price - 1, base_price + 1, base_price - 1, base_price, normal_vol))

        # BC bar (index 25): wide spread + climax vol + close < %50 (ust fitil)
        # 5-bar max high icin: onceki 4 barda high < bc_high
        atr_approx = 2.0
        bc_spread = 3.5 * atr_approx
        bc_low = base_price - bc_spread / 2
        bc_high = base_price + bc_spread / 2
        bc_close = bc_low + 0.30 * bc_spread  # alt yari = ust fitil
        bc_vol = 4.0 * normal_vol
        bars.append(_bar(base_price, bc_high, bc_low, bc_close, bc_vol))

        # 5 konsolidasyon bari (dusus / pullback)
        pullback = bc_close - 1.5
        for _ in range(5):
            bars.append(_bar(pullback + 0.5, pullback + 1, pullback - 1, pullback, normal_vol * 0.7))

        # Up Thrust (index 31): BC high'ına yaklasim + dusuk hacim + ust fitil (close < %50)
        ut_high = bc_high - 0.005 * bc_high  # tolerance icinde
        ut_spread = 0.4 * atr_approx
        ut_low = ut_high - ut_spread
        ut_close = ut_low + 0.30 * ut_spread  # ust fitil (close < %50)
        ut_vol = 0.35 * normal_vol
        bars.append(_bar(ut_low + 0.5 * ut_spread, ut_high, ut_low, ut_close, ut_vol))

        # Kirmizi onay bari (index 32): close < open
        bars.append(_bar(pullback + 1, pullback + 1.5, pullback - 2.5, pullback - 2.0, normal_vol))

        df = _df_from_bars(bars)
        strat = _make_strategy()
        sigs = strat.generate_signals(df)

        short_sigs = [s for s in sigs if s.direction == "short"]
        assert len(short_sigs) >= 1, (
            f"Short sinyal uretilmedi. Toplam sinyal: {len(sigs)}. "
            f"bc_flag: {strat.prepare_features(df)['bc_flag'].sum()}, "
            f"up_thrust: {strat.prepare_features(df)['up_thrust_flag'].sum()}, "
            f"short_confirm: {strat.prepare_features(df)['short_confirm'].sum()}"
        )

        for sig in short_sigs:
            assert sig.sl_price > sig.tp_price, "Short SL > TP olmali"
            assert sig.confluence_score > 0.0
            assert sig.pattern_id == "vsa_bc_thrust_short"


# ---------------------------------------------------------------------------
# Test 8: prepare_features bos DataFrame
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_prepare_features_empty_df(self):
        """Bos DataFrame => prepare_features crash etmemeli."""
        strat = _make_strategy()
        df = pd.DataFrame()
        result = strat.prepare_features(df)
        assert result.empty

    def test_generate_signals_empty_df(self):
        """Bos DataFrame => bos sinyal listesi."""
        strat = _make_strategy()
        df = pd.DataFrame()
        sigs = strat.generate_signals(df)
        assert sigs == []

    def test_default_manifest_valid(self):
        """Default manifest gecerli olmali."""
        manifest = _default_manifest()
        assert manifest.name == "vsa_climax_test"
        assert len(manifest.signals.patterns) == 2
        pattern_ids = {p.id for p in manifest.signals.patterns}
        assert "vsa_sc_test_long" in pattern_ids
        assert "vsa_bc_thrust_short" in pattern_ids
        primary_R = float(manifest.risk.get("take_profit", {}).get("primary_R", 0))
        assert primary_R == 3.0

    def test_strategy_importable(self):
        """Strateji dogrudan import edilebilmeli."""
        from price_action.strategies.vsa_climax_test import VSAClimaxTestStrategy
        assert VSAClimaxTestStrategy.name == "vsa_climax_test"
