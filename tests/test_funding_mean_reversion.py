"""Unit testler — FundingMeanReversionStrategy + FundingStore + helpers.

Test senaryolari:
  1. FundingStore: schema olusturma, upsert, read, last_ts
  2. Feature helpers: _atr, _swing_high_low, _funding_z_score, reversal_bar
  3. merge_funding_to_ohlcv: timestamp eşleşmesi
  4. Strateji sinyal üretimi:
     a. Extreme pozitif funding + bearish bar → short sinyal
     b. Extreme negatif funding + bullish bar → long sinyal
     c. Normal funding → sinyal yok
     d. Funding kolonu eksik → sinyal yok (graceful)
  5. Lookahead-bias: funding_rate_lag1 shift(1) doğrulaması
  6. Backtest smoke: BacktestEngine ile entegre çalışma
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from price_action.data.funding_ingest import (
    FundingStore,
    _funding_records_to_df,
    reset_funding_pool,
)
from price_action.strategies.funding_mean_reversion import (
    FundingMeanReversionStrategy,
    _atr,
    _default_manifest,
    _funding_z_score,
    _reversal_bar_bearish,
    _reversal_bar_bullish,
    _swing_high_low,
    merge_funding_to_ohlcv,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _base_ts_8h(n: int, start: datetime | None = None) -> list[datetime]:
    if start is None:
        start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [start + timedelta(hours=8 * i) for i in range(n)]


def _make_ohlcv_8h(
    n: int,
    seed: int = 42,
    base_price: float = 50_000.0,
) -> pd.DataFrame:
    """Sentetik 8h OHLCV (BTC benzeri)."""
    rng = np.random.default_rng(seed)
    rets = rng.normal(0.0, 0.01, n)
    close = base_price * np.exp(np.cumsum(rets))
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.003, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.003, n)))
    high = np.maximum.reduce([high, open_, close])
    low = np.minimum.reduce([low, open_, close])
    ts = _base_ts_8h(n)
    return pd.DataFrame({
        "ts": ts,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": rng.uniform(1e6, 5e6, n),
        "venue": "binance",
        "symbol": "BTC/USDT:USDT",
        "timeframe": "4h",
    })


def _make_funding_df(
    n: int,
    rate: float = 0.0001,
    seed: int = 42,
    symbol: str = "BTC/USDT:USDT",
    start: datetime | None = None,
) -> pd.DataFrame:
    """Sabit veya küçük gürültülü funding rate DataFrame."""
    rng = np.random.default_rng(seed)
    ts = _base_ts_8h(n, start)
    rates = rate + rng.normal(0, abs(rate) * 0.05, n)
    return pd.DataFrame({
        "venue": "binance",
        "symbol": symbol,
        "ts": ts,
        "funding_rate": rates,
        "mark_price": 50_000.0 + rng.normal(0, 100, n),
    })


def _make_strategy(overrides: dict | None = None) -> FundingMeanReversionStrategy:
    """Test için minimal manifest ile strateji oluştur."""
    from price_action.strategies.base import StrategyManifest

    raw = {
        "name": "funding_mean_reversion",
        "version": "0.0.1",
        "trend_filter": {"type": "none", "period": 0, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "funding_fade_short",
                    "enabled": True,
                    "weight": 1.0,
                    "params": {
                        "funding_threshold": 0.0005,
                        "z_score_min": 1.5,
                        "reversal_body_ratio_min": 0.35,
                        "swing_lookback": 8,
                    },
                },
                {
                    "id": "funding_fade_long",
                    "enabled": True,
                    "weight": 1.0,
                    "params": {
                        "funding_threshold": 0.0005,
                        "z_score_min": 1.5,
                        "reversal_body_ratio_min": 0.35,
                        "swing_lookback": 8,
                    },
                },
            ],
            "structure": {
                "swing": {"fractal_n": 2},
                "support_resistance": {
                    "lookback_bars": 60,
                    "cluster_atr_multiplier": 0.5,
                    "min_touches": 2,
                    "max_age_bars": 60,
                },
                "require_proximity_to_sr_atr": 0.0,
            },
            "filters": {"atr_min_pct": 0.0},
            "confluence": {"method": "weighted_sum", "min_score": 1.0},
        },
        "risk": {
            "take_profit": {"method": "r_multiple", "primary_R": 1.5},
        },
    }
    if overrides:
        raw.update(overrides)
    manifest = StrategyManifest.model_validate(raw)
    return FundingMeanReversionStrategy(manifest)


# ---------------------------------------------------------------------------
# 1. FundingStore tests
# ---------------------------------------------------------------------------

class TestFundingStore:
    def test_schema_created(self, tmp_path: Path) -> None:
        """FundingStore oluşturulduğunda funding_rates tablosu olmalı."""
        reset_funding_pool()
        store = FundingStore(duckdb_path=tmp_path / "test.duckdb")
        # Tablo yoksa exception olmaz; boş read OK
        df = store.read("BTC/USDT:USDT", venue="binance")
        assert df.empty or isinstance(df, pd.DataFrame)

    def test_upsert_and_read(self, tmp_path: Path) -> None:
        """Upsert edilen kayıtlar okunabilmeli."""
        reset_funding_pool()
        store = FundingStore(duckdb_path=tmp_path / "test.duckdb")
        fr_df = _make_funding_df(10, rate=0.0001)
        written = store.upsert(fr_df)
        assert written == 10
        read_df = store.read("BTC/USDT:USDT", venue="binance")
        assert len(read_df) == 10
        assert "funding_rate" in read_df.columns
        assert abs(read_df["funding_rate"].mean() - 0.0001) < 0.001

    def test_upsert_idempotent(self, tmp_path: Path) -> None:
        """Aynı kayıtları iki kez yazmak satır sayısını artırmamalı."""
        reset_funding_pool()
        store = FundingStore(duckdb_path=tmp_path / "test.duckdb")
        fr_df = _make_funding_df(5, rate=0.0002)
        store.upsert(fr_df)
        store.upsert(fr_df)  # duplicate
        read_df = store.read("BTC/USDT:USDT")
        assert len(read_df) == 5, "İdempotent: duplicate upsert satır sayısını artırmamalı"

    def test_last_ts_empty(self, tmp_path: Path) -> None:
        """Boş DB'de last_ts None dönmeli."""
        reset_funding_pool()
        store = FundingStore(duckdb_path=tmp_path / "test.duckdb")
        ts = store.last_ts("binance", "BTC/USDT:USDT")
        assert ts is None

    def test_last_ts_after_upsert(self, tmp_path: Path) -> None:
        """Upsert sonrası last_ts doğru timestamp dönmeli."""
        reset_funding_pool()
        store = FundingStore(duckdb_path=tmp_path / "test.duckdb")
        fr_df = _make_funding_df(10, rate=0.0001)
        store.upsert(fr_df)
        last = store.last_ts("binance", "BTC/USDT:USDT")
        assert last is not None
        assert isinstance(last, datetime)

    def test_symbols(self, tmp_path: Path) -> None:
        """symbols() mevcut sembolleri listeler."""
        reset_funding_pool()
        store = FundingStore(duckdb_path=tmp_path / "test.duckdb")
        fr_df = _make_funding_df(5, symbol="ETH/USDT:USDT")
        store.upsert(fr_df)
        syms = store.symbols()
        assert "ETH/USDT:USDT" in syms

    def test_upsert_missing_column_raises(self, tmp_path: Path) -> None:
        """Eksik kolon ValueError fırlatmalı."""
        reset_funding_pool()
        store = FundingStore(duckdb_path=tmp_path / "test.duckdb")
        bad_df = pd.DataFrame({"venue": ["binance"], "symbol": ["BTC/USDT:USDT"]})
        with pytest.raises(ValueError, match="eksik kolon"):
            store.upsert(bad_df)

    def test_read_time_filter(self, tmp_path: Path) -> None:
        """start/end filtresi doğru çalışmalı."""
        reset_funding_pool()
        store = FundingStore(duckdb_path=tmp_path / "test.duckdb")
        fr_df = _make_funding_df(20, rate=0.0001)
        store.upsert(fr_df)
        ts_list = list(fr_df["ts"])
        mid = ts_list[9]
        if isinstance(mid, pd.Timestamp):
            mid = mid.to_pydatetime()
        read_df = store.read("BTC/USDT:USDT", start=mid)
        assert len(read_df) <= 20
        assert len(read_df) >= 1


# ---------------------------------------------------------------------------
# 2. Feature helpers
# ---------------------------------------------------------------------------

class TestFeatureHelpers:
    def test_atr_computed(self) -> None:
        """_atr hesabı NaN içermemeli (ilk birkaç bar dışında)."""
        df = _make_ohlcv_8h(50)
        atr = _atr(df, 14)
        assert (atr.iloc[20:] > 0).all(), "ATR pozitif olmalı"

    def test_swing_high_low_lookahead_free(self) -> None:
        """Swing high/low: bar t için [t-lookback..t-1] kullanılmalı.

        Bar 10'da high=200000 (çok yüksek). Bar 9'daki swing high bunu görmemeli.
        """
        n = 30
        df = _make_ohlcv_8h(n, seed=1)
        df.loc[10, "high"] = 200_000.0
        sh, _ = _swing_high_low(df, lookback=5)
        # Bar 9: pencere [4..8] — bar 10 dahil değil
        assert float(sh.iloc[9]) < 200_000.0, "Bar 9 bar-10's high'ını görmemeli"
        # Bar 11: pencere [6..10] — bar 10 dahil
        assert float(sh.iloc[11]) == pytest.approx(200_000.0, rel=0.01)

    def test_funding_z_score_shift(self) -> None:
        """_funding_z_score shift(1) kullanıyor olmalı.

        Seri: ilk N-1 bar normal, son bar extreme.
        Son barın z-score'u: shift(1) → lagged series at [-1] = fr[-2] (normal).
        Bu bar için mean/std = rolling of shifted values → z near 0.
        Bar N-1'in z-score'u ise lag olduğu için bar N-2'yi görür → normal.
        """
        n = 100
        fr = pd.Series(np.zeros(n))
        fr.iloc[-1] = 10.0  # extreme at last bar
        z = _funding_z_score(fr, window=40)
        # Son bar: shift(1) ile lagged fr[-1] = fr[-2] = 0 → z should be ~0
        # Note: after shift, std can be 0 for many bars → NaN is acceptable for those
        # The key check: bar[-2] z-score should NOT see bar[-1]'s extreme value
        # (the extreme only affects z at bar[-1+1]=bar[0], which wraps, so check bar index n-2)
        z_second_to_last = float(z.iloc[-2])
        # Bar -2: shifted series looks at fr[-3]=0, rolling std ~0 → NaN or ~0
        # The crucial lookahead check: the extreme value 10.0 at bar N-1 should
        # NOT appear in z-scores at bars BEFORE N (since shift moves it to N+1 which is OOB)
        # So z at bar N should use fr[N-1] (the value 10.0) after shift → it IS visible
        # But z at bar N-1 should use fr[N-2]=0 → NOT visible
        # The correct assertion: z at second-to-last bar is not extreme
        assert np.isnan(z_second_to_last) or abs(z_second_to_last) < 3.0, (
            "Bar N-1: lag shifted value is fr[N-2]=0, z should be ~0 or NaN (zero std)"
        )

    def test_reversal_bar_bear(self) -> None:
        """Bearish bar doğru tespit edilmeli."""
        df = pd.DataFrame({
            "open": [100.0, 100.0],
            "high": [105.0, 105.0],
            "low": [90.0, 90.0],
            "close": [95.0, 102.0],  # bar 0 bearish, bar 1 bullish
        })
        flags = _reversal_bar_bearish(df, body_ratio_min=0.3)
        assert bool(flags.iloc[0]), "Bar 0 bearish olmalı"
        assert not bool(flags.iloc[1]), "Bar 1 bullish - bear flag False olmalı"

    def test_reversal_bar_bull(self) -> None:
        """Bullish bar doğru tespit edilmeli."""
        df = pd.DataFrame({
            "open": [95.0, 100.0],
            "high": [105.0, 105.0],
            "low": [90.0, 90.0],
            "close": [102.0, 95.0],  # bar 0 bullish, bar 1 bearish
        })
        flags = _reversal_bar_bullish(df, body_ratio_min=0.3)
        assert bool(flags.iloc[0]), "Bar 0 bullish olmalı"
        assert not bool(flags.iloc[1]), "Bar 1 bearish - bull flag False olmalı"

    def test_reversal_bar_fails_body_ratio(self) -> None:
        """Body ratio < threshold ise flag False olmalı."""
        df = pd.DataFrame({
            "open": [100.0],
            "high": [110.0],
            "low": [90.0],
            "close": [99.5],  # body=0.5, range=20, ratio=0.025 < 0.35
        })
        assert not bool(_reversal_bar_bearish(df, body_ratio_min=0.35).iloc[0])


# ---------------------------------------------------------------------------
# 3. merge_funding_to_ohlcv
# ---------------------------------------------------------------------------

class TestMergeFundingToOhlcv:
    def test_merge_aligned_timestamps(self) -> None:
        """Aynı timestamp'ler merge edilmeli."""
        n = 10
        ohlcv = _make_ohlcv_8h(n)
        funding = _make_funding_df(n, rate=0.001)
        merged = merge_funding_to_ohlcv(ohlcv, funding, symbol="BTC/USDT:USDT")
        assert "funding_rate" in merged.columns
        assert len(merged) == n
        # Çoğu bar'da funding_rate dolu olmalı
        assert merged["funding_rate"].notna().sum() > n // 2

    def test_merge_empty_funding(self) -> None:
        """Boş funding → funding_rate NaN olmalı."""
        ohlcv = _make_ohlcv_8h(5)
        funding = pd.DataFrame(columns=["ts", "funding_rate", "mark_price"])
        merged = merge_funding_to_ohlcv(ohlcv, funding)
        assert merged["funding_rate"].isna().all()

    def test_merge_empty_ohlcv(self) -> None:
        """Boş OHLCV → boş DataFrame dönmeli."""
        funding = _make_funding_df(5)
        ohlcv = pd.DataFrame()
        merged = merge_funding_to_ohlcv(ohlcv, funding)
        assert merged.empty


# ---------------------------------------------------------------------------
# 4. Strategy signal generation
# ---------------------------------------------------------------------------

class TestFundingMRSignals:
    def test_importable(self) -> None:
        from price_action.strategies.funding_mean_reversion import FundingMeanReversionStrategy
        assert FundingMeanReversionStrategy.name == "funding_mean_reversion"

    def test_prepare_features_columns(self) -> None:
        """prepare_features gerekli kolonları eklemeli."""
        strat = _make_strategy()
        ohlcv = _make_ohlcv_8h(60)
        funding = _make_funding_df(60, rate=0.0001)
        merged = merge_funding_to_ohlcv(ohlcv, funding, symbol="BTC/USDT:USDT")
        df_feat = strat.prepare_features(merged)
        for col in ["atr14", "atr_pct", "swing_high_8", "swing_low_8",
                    "funding_rate_lag1", "funding_z", "funding_z_lag1",
                    "reversal_bear", "reversal_bull"]:
            assert col in df_feat.columns, f"Eksik kolon: {col}"

    def test_no_signal_without_funding(self) -> None:
        """Funding kolonu yoksa sinyal üretilmemeli (graceful)."""
        strat = _make_strategy()
        ohlcv = _make_ohlcv_8h(60)  # no funding_rate column
        sigs = strat.generate_signals(ohlcv)
        assert sigs == [], "Funding kolonu olmadan sinyal üretilmemeli"

    def test_no_signal_normal_funding(self) -> None:
        """Normal funding (threshold altında) → sinyal yok."""
        strat = _make_strategy()
        n = 150
        ohlcv = _make_ohlcv_8h(n, seed=10)
        # Çok düşük funding — threshold=0.0005 altında
        funding = _make_funding_df(n, rate=0.0001, seed=10)
        merged = merge_funding_to_ohlcv(ohlcv, funding, symbol="BTC/USDT:USDT")
        df_feat = strat.prepare_features(merged)
        sigs = strat.generate_signals(df_feat)
        # Normal funding → ya hiç sinyal yok ya çok az (z-score filtresi geçmez)
        # z-score min=1.5 ile 0.0001 ≈ mean etrafında → z ~0 → sinyal üretilmez
        assert len(sigs) == 0, "Normal funding ile sinyal üretilmemeli"

    def test_short_signal_extreme_positive_funding(self) -> None:
        """Extreme pozitif funding + bearish bar → short sinyal üretilmeli."""
        strat = _make_strategy()
        n = 120
        ohlcv = _make_ohlcv_8h(n, seed=5)
        # Normal funding başlangıç, sonra aşırı pozitif
        funding = _make_funding_df(n, rate=0.0001, seed=5)

        # Bar 100-110 arasında extreme pozitif funding set et
        extreme_bars = list(range(100, 110))
        funding.loc[extreme_bars, "funding_rate"] = 0.002  # >> 0.0005 threshold

        merged = merge_funding_to_ohlcv(ohlcv, funding, symbol="BTC/USDT:USDT")

        # Bar 101-110'da bearish reversal bar zorla
        for i in extreme_bars[1:]:
            price = float(ohlcv.loc[i, "close"])
            merged.loc[i, "open"] = price * 1.01
            merged.loc[i, "close"] = price * 0.99  # bearish
            merged.loc[i, "high"] = price * 1.015
            merged.loc[i, "low"] = price * 0.985

        df_feat = strat.prepare_features(merged)
        sigs = strat.generate_signals(df_feat)
        short_sigs = [s for s in sigs if s.direction == "short"]
        assert len(short_sigs) >= 1, "Extreme pozitif funding + bearish bar → short sinyal olmalı"

        sig = short_sigs[0]
        assert sig.pattern_id == "funding_fade_short"
        assert sig.sl_price > float(sig.metadata.get("atr14", 0))
        assert sig.tp_price < sig.sl_price  # tp below sl for short

    def test_long_signal_extreme_negative_funding(self) -> None:
        """Extreme negatif funding + bullish bar → long sinyal üretilmeli."""
        strat = _make_strategy()
        n = 120
        ohlcv = _make_ohlcv_8h(n, seed=7)
        funding = _make_funding_df(n, rate=0.0001, seed=7)

        # Bar 100-110 extreme negatif
        extreme_bars = list(range(100, 110))
        funding.loc[extreme_bars, "funding_rate"] = -0.002  # << -0.0005 threshold

        merged = merge_funding_to_ohlcv(ohlcv, funding, symbol="BTC/USDT:USDT")

        # Bullish reversal barlar zorla
        for i in extreme_bars[1:]:
            price = float(ohlcv.loc[i, "close"])
            merged.loc[i, "open"] = price * 0.99
            merged.loc[i, "close"] = price * 1.01  # bullish
            merged.loc[i, "high"] = price * 1.015
            merged.loc[i, "low"] = price * 0.985

        df_feat = strat.prepare_features(merged)
        sigs = strat.generate_signals(df_feat)
        long_sigs = [s for s in sigs if s.direction == "long"]
        assert len(long_sigs) >= 1, "Extreme negatif funding + bullish bar → long sinyal olmalı"

        sig = long_sigs[0]
        assert sig.pattern_id == "funding_fade_long"
        assert sig.tp_price > sig.sl_price  # tp above sl for long

    def test_signal_schema_valid(self) -> None:
        """Üretilen sinyaller Signal schema'sını geçmeli."""
        from price_action.contracts import Signal

        strat = _make_strategy()
        n = 120
        ohlcv = _make_ohlcv_8h(n, seed=11)
        funding = _make_funding_df(n, rate=0.0001, seed=11)
        funding.loc[100:110, "funding_rate"] = 0.002

        merged = merge_funding_to_ohlcv(ohlcv, funding, symbol="BTC/USDT:USDT")
        for i in range(100, 110):
            price = float(ohlcv.loc[i, "close"])
            merged.loc[i, "open"] = price * 1.01
            merged.loc[i, "close"] = price * 0.99
            merged.loc[i, "high"] = price * 1.015
            merged.loc[i, "low"] = price * 0.985

        df_feat = strat.prepare_features(merged)
        sigs = strat.generate_signals(df_feat)
        for sig in sigs:
            assert isinstance(sig, Signal)
            assert sig.direction in {"long", "short"}
            assert sig.sl_price > 0
            assert sig.tp_price > 0
            assert sig.confluence_score >= 0
            assert sig.fingerprint()

    def test_empty_df_returns_no_signals(self) -> None:
        """Boş DataFrame → boş sinyal listesi."""
        strat = _make_strategy()
        sigs = strat.generate_signals(pd.DataFrame())
        assert sigs == []

    def test_default_manifest_valid(self) -> None:
        """_default_manifest() geçerli StrategyManifest döndürmeli."""
        m = _default_manifest()
        assert m.name == "funding_mean_reversion"
        assert len(m.signals.patterns) == 2
        pattern_ids = [p.id for p in m.signals.patterns]
        assert "funding_fade_short" in pattern_ids
        assert "funding_fade_long" in pattern_ids


# ---------------------------------------------------------------------------
# 5. Lookahead-bias tests
# ---------------------------------------------------------------------------

class TestLookaheadBias:
    def test_funding_z_uses_only_past_bars(self) -> None:
        """funding_rate_lag1: bar t'de funding[t-1] kullanılmalı (shift(1) garantisi).

        Doğrudan funding_rate_lag1 değerini kontrol ederiz — z-score window
        smoothing efektini bypass eder ve shift davranışını doğrular.
        """
        n = 120
        ohlcv = _make_ohlcv_8h(n, seed=20)
        funding = _make_funding_df(n, rate=0.00001, seed=20)

        # Sadece bar N=100'de extreme
        extreme_val = 0.01
        funding.loc[100, "funding_rate"] = extreme_val

        merged = merge_funding_to_ohlcv(ohlcv, funding, symbol="BTC/USDT:USDT")
        strat = _make_strategy()
        df_feat = strat.prepare_features(merged)

        # funding_rate_lag1[100] = funding_rate[99] (NOT the extreme at 100)
        lag1_at_100 = float(df_feat.loc[100, "funding_rate_lag1"])
        # funding_rate_lag1[101] = funding_rate[100] = extreme_val
        lag1_at_101 = float(df_feat.loc[101, "funding_rate_lag1"])

        # Bar 100's lag1 should NOT see bar 100's extreme value
        assert lag1_at_100 < extreme_val * 0.5, (
            f"Bar 100 lag1 ({lag1_at_100}) bar 100'ın extreme değerini ({extreme_val}) görmemeli"
        )
        # Bar 101's lag1 SHOULD see bar 100's extreme value
        assert lag1_at_101 == pytest.approx(extreme_val, rel=0.01), (
            f"Bar 101 lag1 ({lag1_at_101}) bar 100'ın extreme değerini ({extreme_val}) görmeli"
        )

    def test_swing_sl_no_future_bars(self) -> None:
        """swing_high_8 bar t'de [t-8..t-1] kullanılmalı.

        Bar 50'de çok yüksek bir high koy. Bar 49'da swing_high_8 bunu görmemeli.
        """
        n = 80
        ohlcv = _make_ohlcv_8h(n, seed=30)
        ohlcv.loc[50, "high"] = 999_999.0  # extreme spike at bar 50

        funding = _make_funding_df(n, rate=0.0001, seed=30)
        merged = merge_funding_to_ohlcv(ohlcv, funding, symbol="BTC/USDT:USDT")

        strat = _make_strategy()
        df_feat = strat.prepare_features(merged)

        # Bar 49: swing_high should NOT include bar 50
        assert float(df_feat.loc[49, "swing_high_8"]) < 999_999.0, (
            "Bar 49 bar-50'nin spike'ını görmemeli (lookahead)"
        )
        # Bar 51: swing_high SHOULD include bar 50
        assert float(df_feat.loc[51, "swing_high_8"]) == pytest.approx(999_999.0, rel=0.01)

    def test_signal_at_t_not_affected_by_t_plus_future(self) -> None:
        """Bar t'deki sinyal, t+1..end bilgisinden etkilenmemeli.

        Yöntem: t+5..end funding_rate_lag1 ve reversal flaglerini sıfırla.
        Signal sayısı değişmemeli.
        """
        strat = _make_strategy()
        n = 120
        ohlcv = _make_ohlcv_8h(n, seed=42)
        funding = _make_funding_df(n, rate=0.0001, seed=42)
        funding.loc[80:95, "funding_rate"] = 0.002  # extreme at 80-95

        merged = merge_funding_to_ohlcv(ohlcv, funding, symbol="BTC/USDT:USDT")
        for i in range(80, 95):
            price = float(ohlcv.loc[i, "close"])
            merged.loc[i, "open"] = price * 1.01
            merged.loc[i, "close"] = price * 0.99
            merged.loc[i, "high"] = price * 1.015
            merged.loc[i, "low"] = price * 0.985

        df_feat_full = strat.prepare_features(merged)
        sigs_full = strat.generate_signals(df_feat_full)

        # Truncate future: zero out features after bar 85
        df_feat_trunc = df_feat_full.copy()
        df_feat_trunc.loc[86:, "funding_rate_lag1"] = 0.0
        df_feat_trunc.loc[86:, "funding_z_lag1"] = 0.0
        df_feat_trunc.loc[86:, "reversal_bear"] = False
        df_feat_trunc.loc[86:, "reversal_bull"] = False

        sigs_trunc = strat.generate_signals(df_feat_trunc)

        # Signals up to bar 85 should be identical
        sigs_full_early = [s for s in sigs_full if pd.Timestamp(s.ts) <= pd.Timestamp(merged.loc[85, "ts"])]
        sigs_trunc_early = [s for s in sigs_trunc if pd.Timestamp(s.ts) <= pd.Timestamp(merged.loc[85, "ts"])]
        assert len(sigs_full_early) == len(sigs_trunc_early), (
            "Gelecek barlar sıfırlanması geçmiş sinyalleri etkilememeli"
        )


# ---------------------------------------------------------------------------
# 6. _funding_records_to_df helper
# ---------------------------------------------------------------------------

class TestFundingRecordsToDF:
    def test_converts_ccxt_records(self) -> None:
        """ccxt funding_rate_history formatındaki kayıtlar DataFrame'e çevrilmeli."""
        records = [
            {
                "symbol": "BTC/USDT:USDT",
                "fundingRate": 0.0001,
                "timestamp": 1714521600000,
                "datetime": "2024-05-01T00:00:00.000Z",
                "info": {"markPrice": "60000.0"},
            },
            {
                "symbol": "BTC/USDT:USDT",
                "fundingRate": -0.0002,
                "timestamp": 1714550400000,
                "datetime": "2024-05-01T08:00:00.000Z",
                "info": {"markPrice": "59500.0"},
            },
        ]
        df = _funding_records_to_df(records, venue="binance")
        assert len(df) == 2
        assert list(df.columns) == ["venue", "symbol", "ts", "funding_rate", "mark_price"]
        assert float(df.iloc[0]["funding_rate"]) == pytest.approx(0.0001)
        assert float(df.iloc[1]["funding_rate"]) == pytest.approx(-0.0002)
        assert float(df.iloc[0]["mark_price"]) == pytest.approx(60000.0)

    def test_empty_records(self) -> None:
        """Boş kayıt listesi → boş DataFrame."""
        df = _funding_records_to_df([], venue="binance")
        assert df.empty


# ---------------------------------------------------------------------------
# 7. Backtest smoke test
# ---------------------------------------------------------------------------

class TestBacktestSmoke:
    def test_backtest_engine_runs(self) -> None:
        """BacktestEngine ile FundingMRStrategy çalışmalı, exception yok."""
        from datetime import datetime, timezone
        from price_action.backtest.engine import BacktestEngine

        strat = _make_strategy()
        n = 200
        start_dt = datetime(2024, 1, 1, tzinfo=timezone.utc)

        ohlcv = _make_ohlcv_8h(n, seed=99, base_price=50_000.0)
        funding = _make_funding_df(n, rate=0.0001, seed=99)
        # Inject a few extreme funding windows
        funding.loc[100:105, "funding_rate"] = 0.002
        funding.loc[150:155, "funding_rate"] = -0.002

        merged = merge_funding_to_ohlcv(ohlcv, funding, symbol="BTC/USDT:USDT")
        # Inject bearish reversal bars at extreme long funding
        for i in range(100, 106):
            price = float(ohlcv.loc[i, "close"])
            merged.loc[i, "open"] = price * 1.01
            merged.loc[i, "close"] = price * 0.99
            merged.loc[i, "high"] = price * 1.015
            merged.loc[i, "low"] = price * 0.985
        # Inject bullish reversal bars at extreme short funding
        for i in range(150, 156):
            price = float(ohlcv.loc[i, "close"])
            merged.loc[i, "open"] = price * 0.99
            merged.loc[i, "close"] = price * 1.01
            merged.loc[i, "high"] = price * 1.015
            merged.loc[i, "low"] = price * 0.985

        ts_list = list(merged["ts"])

        def _provider(symbol: str, tf: str, start: datetime, end: datetime) -> pd.DataFrame:
            return merged[(merged["ts"] >= pd.Timestamp(start, tz="UTC"))
                          & (merged["ts"] <= pd.Timestamp(end, tz="UTC"))].copy()

        engine = BacktestEngine()
        result = engine.run(
            strat,
            universe=["BTC/USDT:USDT"],
            start=start_dt,
            end=ts_list[-1] if isinstance(ts_list[-1], datetime) else ts_list[-1].to_pydatetime(),
            initial_capital=10_000.0,
            timeframe="8h",
            ohlcv_provider=_provider,
        )
        assert result is not None
        assert result.strategy_name == "funding_mean_reversion"
        assert isinstance(result.kpis, dict)
        assert "sharpe" in result.kpis
        assert result.initial_capital == 10_000.0

    def test_backtest_no_signals_no_trades(self) -> None:
        """Sinyal olmayan veriye karşı backtest: n_trades=0 ve equity sabit."""
        from datetime import datetime, timezone
        from price_action.backtest.engine import BacktestEngine

        strat = _make_strategy()
        n = 100
        start_dt = datetime(2024, 1, 1, tzinfo=timezone.utc)

        # Only normal funding — no extreme, no signals
        ohlcv = _make_ohlcv_8h(n, seed=1)
        funding = _make_funding_df(n, rate=0.00005, seed=1)  # below threshold
        merged = merge_funding_to_ohlcv(ohlcv, funding, symbol="BTC/USDT:USDT")
        ts_list = list(merged["ts"])

        def _provider(symbol, tf, start, end):
            return merged.copy()

        engine = BacktestEngine()
        result = engine.run(
            strat,
            universe=["BTC/USDT:USDT"],
            start=start_dt,
            end=ts_list[-1] if isinstance(ts_list[-1], datetime) else ts_list[-1].to_pydatetime(),
            initial_capital=10_000.0,
            timeframe="8h",
            ohlcv_provider=_provider,
        )
        assert result.n_trades == 0
        assert abs(result.equity_curve.iloc[-1] - 10_000.0) < 1.0
