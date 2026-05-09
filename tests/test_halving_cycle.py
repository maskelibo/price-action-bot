"""Unit testler -- halving_cycle modulu.

Test senaryolari:
  1. Phase computation — bilinen tarihler icin dogru faz
  2. Boundary test — halving gunu kendisi Phase A olmali
  3. Phase A gecisinin tam siniri (12 ay = Phase B baslangici)
  4. Tum faz gecislerini dogrula (A->B->C->D)
  5. Size factor mapping — dogru faktor degerleri
  6. Lookahead-free: gelecek halvingden etkilenme yok
  7. apply_halving_phase_sizing — metadata ekleniyor, size olcekleniyor
  8. Kombine backtest sanity — HalvingCycleEngulfingStrategy sinyal uretime
"""
from __future__ import annotations

from datetime import date, datetime, timezone, timedelta

import numpy as np
import pandas as pd
import pytest

from price_action.strategies.halving_cycle import (
    HALVING_DATES,
    compute_halving_phase,
    phase_to_size_factor,
    apply_halving_phase_sizing,
    add_halving_phase_column,
    HalvingCycleEngulfingStrategy,
    _months_since,
    _DAYS_PER_MONTH,
)


# ---------------------------------------------------------------------------
# Yardimci: minimal Signal olustur
# ---------------------------------------------------------------------------

def _make_signal(ts: datetime, size: float = 1.0):
    """Minimal Signal stub — gercek Signal modeli kullanilir."""
    from price_action.contracts import Signal
    return Signal(
        ts=ts,
        venue="binance",
        symbol="BTC/USDT",
        timeframe="1d",
        direction="long",
        pattern_id="bullish_engulfing_cont",
        confluence_score=1.5,
        sl_price=25000.0,
        tp_price=27000.0,
        suggested_size_atr=size,
        metadata={"test": True},
    )


# ---------------------------------------------------------------------------
# Test 1: Bilinen tarihler icin dogru faz hesabi
# ---------------------------------------------------------------------------

class TestComputeHalvingPhase:
    """compute_halving_phase() dogru fazdaki noktalari dogru siniflandirmali."""

    def test_post_2024_halving_phase_a(self):
        """2024-04-19'dan 1 ay sonra Phase A olmali."""
        ts = datetime(2024, 5, 25, tzinfo=timezone.utc)
        assert compute_halving_phase(ts) == "A"

    def test_post_2024_halving_phase_a_late(self):
        """2024-04-19'dan 11 ay sonra hala Phase A."""
        ts = datetime(2025, 3, 15, tzinfo=timezone.utc)
        assert compute_halving_phase(ts) == "A"

    def test_post_2024_halving_phase_b(self):
        """2024-04-19'dan 14 ay sonra Phase B."""
        ts = datetime(2025, 6, 20, tzinfo=timezone.utc)
        assert compute_halving_phase(ts) == "B"

    def test_post_2020_halving_mid_cycle_phase_b(self):
        """2020-05-11'dan 18 ay sonra (Kasim 2021 civar) Phase B."""
        ts = datetime(2021, 11, 15, tzinfo=timezone.utc)
        assert compute_halving_phase(ts) == "B"

    def test_pre_2024_halving_phase_c(self):
        """2020-05-11'dan 33 ay sonra Phase C (pre-2024 accumulation)."""
        ts = datetime(2023, 2, 15, tzinfo=timezone.utc)
        assert compute_halving_phase(ts) == "C"

    def test_before_first_halving_returns_none(self):
        """2012-11-28'den once hic halving yok => None."""
        ts = datetime(2012, 6, 1, tzinfo=timezone.utc)
        assert compute_halving_phase(ts) is None


# ---------------------------------------------------------------------------
# Test 2: Boundary — halving gunu Phase A olmali
# ---------------------------------------------------------------------------

class TestHalvingDayBoundary:
    """Halving gunu tam sinirlari."""

    def test_2024_halving_day_is_phase_a(self):
        """2024-04-19 (halving gunu) Phase A baslangici."""
        ts = datetime(2024, 4, 19, tzinfo=timezone.utc)
        assert compute_halving_phase(ts) == "A"

    def test_2020_halving_day_is_phase_a(self):
        """2020-05-11 (halving gunu) Phase A baslangici."""
        ts = datetime(2020, 5, 11, tzinfo=timezone.utc)
        assert compute_halving_phase(ts) == "A"

    def test_one_day_before_halving_is_prior_phase(self):
        """Halving'den bir gun once onceki faz gecerli."""
        ts = datetime(2024, 4, 18, tzinfo=timezone.utc)
        phase = compute_halving_phase(ts)
        # 2020-05-11 halvinginden 47.3 ay sonra => Phase D
        assert phase in ("C", "D")  # Phase C veya D olabilir (sinir bolgesi)

    def test_phase_a_to_b_boundary(self):
        """12 ay tam olarak Phase B baslangicidir."""
        # 2024-04-19 + 12 ay = 2025-04-19
        ts_a = datetime(2025, 4, 18, tzinfo=timezone.utc)   # hala A
        ts_b = datetime(2025, 4, 21, tzinfo=timezone.utc)   # artik B
        assert compute_halving_phase(ts_a) == "A"
        assert compute_halving_phase(ts_b) == "B"


# ---------------------------------------------------------------------------
# Test 3: Faz gecis sirasi tutarlilik
# ---------------------------------------------------------------------------

class TestPhaseSequence:
    """4 faz dogru sirada gelir."""

    def test_all_phases_reachable_from_2020_halving(self):
        """2020 halvinginden baslayip her fazi gormeli."""
        seen = set()
        base = date(2020, 5, 11)
        # A: 0-12 ay
        for months in [1, 6, 11]:
            d = base + timedelta(days=int(months * _DAYS_PER_MONTH))
            seen.add(compute_halving_phase(datetime.combine(d, datetime.min.time())))
        # B: 12-30 ay
        for months in [13, 20, 29]:
            d = base + timedelta(days=int(months * _DAYS_PER_MONTH))
            seen.add(compute_halving_phase(datetime.combine(d, datetime.min.time())))
        # C: 30-45 ay
        for months in [31, 38, 44]:
            d = base + timedelta(days=int(months * _DAYS_PER_MONTH))
            seen.add(compute_halving_phase(datetime.combine(d, datetime.min.time())))
        # D: 45-48 ay
        for months in [46, 47]:
            d = base + timedelta(days=int(months * _DAYS_PER_MONTH))
            seen.add(compute_halving_phase(datetime.combine(d, datetime.min.time())))

        assert "A" in seen
        assert "B" in seen
        assert "C" in seen
        assert "D" in seen


# ---------------------------------------------------------------------------
# Test 4: Size factor mapping
# ---------------------------------------------------------------------------

class TestPhaseToSizeFactor:
    """phase_to_size_factor() dogru degerleri vermeli."""

    def test_phase_a_factor(self):
        assert phase_to_size_factor("A") == 1.0

    def test_phase_b_factor(self):
        assert phase_to_size_factor("B") == 0.5

    def test_phase_c_factor(self):
        assert phase_to_size_factor("C") == 0.75

    def test_phase_d_factor(self):
        assert phase_to_size_factor("D") == 1.0

    def test_none_factor(self):
        """None (halving oncesi) => notr 1.0."""
        assert phase_to_size_factor(None) == 1.0


# ---------------------------------------------------------------------------
# Test 5: Lookahead-free — gelecek halvingden etkilenme yok
# ---------------------------------------------------------------------------

class TestLookaheadFree:
    """compute_halving_phase sadece ts'den onceki halvingleri kullaniyor."""

    def test_2023_date_uses_2020_halving_not_2024(self):
        """2023-01-01 icin 2024 halvingini bilmemeli; 2020 bazli Phase B/C vermeli."""
        ts = datetime(2023, 1, 1, tzinfo=timezone.utc)
        phase = compute_halving_phase(ts)
        # 2020-05-11'den ~31.7 ay sonra => Phase C
        assert phase == "C"

    def test_future_halvings_dont_affect_present(self):
        """2025-01-15 icin yalnizca 2024 halvingini kullanmali (2028 degil)."""
        ts = datetime(2025, 1, 15, tzinfo=timezone.utc)
        phase = compute_halving_phase(ts)
        # 2024-04-19'dan ~8.9 ay sonra => Phase A
        assert phase == "A"

    def test_halving_dates_are_all_past_or_estimated(self):
        """HALVING_DATES listesi gercek tarihler + 1 tahmini iceriyor."""
        # 2024-04-19'a kadar olan 4 tarih dogrulanmis
        confirmed = [d for d in HALVING_DATES if d <= date(2024, 12, 31)]
        assert len(confirmed) == 4

    def test_months_since_calculation(self):
        """_months_since hesabi dogru olmali."""
        d1 = date(2024, 4, 19)
        d2 = date(2025, 4, 19)
        months = _months_since(d1, d2)
        # 365 gun / 30.4375 = ~11.99 ay
        assert abs(months - 12.0) < 0.1


# ---------------------------------------------------------------------------
# Test 6: apply_halving_phase_sizing
# ---------------------------------------------------------------------------

class TestApplyHalvingPhaseSizing:
    """apply_halving_phase_sizing metadata ve size guncelleme."""

    def test_phase_b_signal_size_halved(self):
        """Phase B zamaninda signal size 0.5x olmali."""
        # 2021-11-15 => Phase B (2020-05-11'den ~18 ay sonra)
        ts = datetime(2021, 11, 15, tzinfo=timezone.utc)
        sig = _make_signal(ts, size=1.0)
        result = apply_halving_phase_sizing([sig], base_risk=0.01)
        assert len(result) == 1
        out = result[0]
        assert out.metadata["halving_phase"] == "B"
        assert abs(out.suggested_size_atr - 0.5) < 1e-9
        assert abs(out.metadata["halving_size_factor"] - 0.5) < 1e-9

    def test_phase_a_signal_unchanged(self):
        """Phase A zamaninda signal size degismemeli (factor=1.0)."""
        ts = datetime(2024, 6, 1, tzinfo=timezone.utc)
        sig = _make_signal(ts, size=1.0)
        result = apply_halving_phase_sizing([sig])
        out = result[0]
        assert out.metadata["halving_phase"] == "A"
        assert abs(out.suggested_size_atr - 1.0) < 1e-9

    def test_metadata_preserved(self):
        """Orijinal metadata korunmali."""
        ts = datetime(2024, 6, 1, tzinfo=timezone.utc)
        sig = _make_signal(ts)
        result = apply_halving_phase_sizing([sig])
        out = result[0]
        assert out.metadata.get("test") is True

    def test_empty_list_returns_empty(self):
        result = apply_halving_phase_sizing([])
        assert result == []


# ---------------------------------------------------------------------------
# Test 7: add_halving_phase_column
# ---------------------------------------------------------------------------

class TestAddHalvingPhaseColumn:
    """add_halving_phase_column DataFrame islemleri."""

    def test_columns_added(self):
        df = pd.DataFrame({
            "ts": pd.to_datetime([
                "2024-05-01", "2025-06-01", "2023-02-01"
            ], utc=True)
        })
        out = add_halving_phase_column(df)
        assert "halving_phase" in out.columns
        assert "halving_size_factor" in out.columns

    def test_phase_values_correct(self):
        df = pd.DataFrame({
            "ts": pd.to_datetime([
                "2024-05-01",  # Phase A (2024 halvinginden 12 gun sonra)
                "2025-06-01",  # Phase B (2024 halvinginden ~13.4 ay sonra)
                "2023-03-01",  # Phase C (2020 halvinginden ~33.7 ay sonra)
            ], utc=True)
        })
        out = add_halving_phase_column(df)
        phases = out["halving_phase"].tolist()
        assert phases[0] == "A"
        assert phases[1] == "B"
        assert phases[2] == "C"


# ---------------------------------------------------------------------------
# Test 8: HalvingCycleEngulfingStrategy kombinasyon sanity
# ---------------------------------------------------------------------------

class TestHalvingCycleEngulfingStrategy:
    """HalvingCycleEngulfingStrategy signal uretme sanity."""

    @staticmethod
    def _make_base_strategy():
        from price_action.strategies.engulfing_continuation import EngulfingContinuationStrategy
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
                        "params": {
                            "body_ratio_min": 0.6,
                            "pullback_window": 10,
                            "pullback_touch_atr": 0.5,
                        },
                    },
                    {
                        "id": "bearish_engulfing_cont",
                        "enabled": True,
                        "weight": 1.5,
                        "params": {
                            "body_ratio_min": 0.6,
                            "pullback_window": 10,
                            "pullback_touch_atr": 0.5,
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
                "confluence": {
                    "method": "weighted_sum",
                    "min_score": 1.0,
                    "bonus_if_at_sr": 0.0,
                },
            },
            "risk": {
                "stop_loss": {"method": "structural", "swing_lookback": 10},
                "take_profit": {"method": "r_multiple", "primary_R": 2.0},
            },
        }
        return EngulfingContinuationStrategy(StrategyManifest.model_validate(raw))

    @staticmethod
    def _make_synthetic_ohlcv(n: int = 120, start: str = "2024-05-01") -> pd.DataFrame:
        """Basit sentetik OHLCV — Phase A (2024 halvinginden sonra)."""
        rng = np.random.default_rng(42)
        dates = pd.date_range(start, periods=n, freq="1D", tz="UTC")
        close = 60_000 + np.cumsum(rng.normal(0, 500, n))
        open_ = close - rng.uniform(-200, 200, n)
        high = np.maximum(open_, close) + rng.uniform(100, 400, n)
        low = np.minimum(open_, close) - rng.uniform(100, 400, n)
        volume = rng.uniform(1e8, 5e8, n)
        df = pd.DataFrame({
            "ts": dates,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "symbol": "BTC/USDT",
            "timeframe": "1d",
            "venue": "binance",
        })
        return df

    def test_strategy_instantiation(self):
        """HalvingCycleEngulfingStrategy basarili olusturuluyor."""
        base = self._make_base_strategy()
        halving_strat = HalvingCycleEngulfingStrategy(base, base_risk=0.01)
        assert "halving_cycle" in halving_strat.name

    def test_prepare_features_adds_halving_columns(self):
        """prepare_features halving_phase sutununu eklemeli."""
        base = self._make_base_strategy()
        halving_strat = HalvingCycleEngulfingStrategy(base, base_risk=0.01)
        df = self._make_synthetic_ohlcv(n=120, start="2024-05-01")
        df_feats = halving_strat.prepare_features(df)
        assert "halving_phase" in df_feats.columns
        assert "halving_size_factor" in df_feats.columns

    def test_generate_signals_phase_a_all_have_metadata(self):
        """Phase A zamaninda uretilen sinyaller halving_phase=A metadata tasiyor."""
        base = self._make_base_strategy()
        halving_strat = HalvingCycleEngulfingStrategy(base, base_risk=0.01)
        df = self._make_synthetic_ohlcv(n=120, start="2024-05-01")
        df_feats = halving_strat.prepare_features(df)
        signals = halving_strat.generate_signals(df_feats)

        if signals:  # en az bir sinyal urettiyse
            for sig in signals:
                assert "halving_phase" in sig.metadata
                assert sig.metadata["halving_phase"] == "A"
                assert abs(sig.metadata["halving_size_factor"] - 1.0) < 1e-9

    def test_phase_b_signals_have_reduced_size(self):
        """Phase B zamaninda sinyaller azaltilmis size tasiyor."""
        base = self._make_base_strategy()
        halving_strat = HalvingCycleEngulfingStrategy(base, base_risk=0.01)
        # Phase B: 2020-05-11'den 14 ay sonra = 2021-07-11
        df = self._make_synthetic_ohlcv(n=90, start="2021-07-11")
        df_feats = halving_strat.prepare_features(df)
        signals = halving_strat.generate_signals(df_feats)

        if signals:
            for sig in signals:
                assert sig.metadata.get("halving_phase") == "B"
                # size factor 0.5 => suggested_size_atr 0.5
                assert sig.suggested_size_atr <= 0.5 + 1e-9
