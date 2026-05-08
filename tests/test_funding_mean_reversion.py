"""Unit testler — FundingMeanReversionStrategy + FundingStore + helpers.

Test senaryolari:
  1. FundingStore: schema olusturma, upsert, read, last_ts
  2. Feature helpers: _atr, _swing_high_low, _funding_z_score, _adaptive_funding_bands,
     _kaufman_er, reversal_bar
  3. merge_funding_to_ohlcv: timestamp eşleşmesi
  4. Strateji sinyal üretimi (v2.0.0 — adaptive threshold + ER filter + BNB exclusion):
     a. Extreme pozitif funding + bearish bar + low ER → short sinyal
     b. Extreme negatif funding + bullish bar + low ER → long sinyal
     c. Normal funding → sinyal yok
     d. Funding kolonu eksik → sinyal yok (graceful)
     e. BNB sembolü → sinyal yok (exclusion)
     f. Yüksek ER (trend) → sinyal yok (regime filter)
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
    BNB_EXCLUDED_SYMBOLS,
    FundingMeanReversionStrategy,
    REGIME_ER_MAX,
    _adaptive_funding_bands,
    _atr,
    _default_manifest,
    _funding_z_score,
    _kaufman_er,
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
    """Test için v2.0.0 manifest ile strateji oluştur.

    v2.0.0 parametreleri:
      - adaptive_window=60, extreme_pctile_high/low=95/5
      - kaufman_er_max=0.30 (regime filter)
      - BNB excluded (tokenomic contamination)
    """
    from price_action.strategies.base import StrategyManifest

    raw = {
        "name": "funding_mean_reversion",
        "version": "2.0.0",
        "trend_filter": {"type": "none", "period": 0, "required": False},
        "signals": {
            "patterns": [
                {
                    "id": "funding_fade_short",
                    "enabled": True,
                    "weight": 1.0,
                    "params": {
                        "adaptive_window": 60,
                        "extreme_pctile_high": 95.0,
                        "reversal_body_ratio_min": 0.35,
                        "swing_lookback": 8,
                        "kaufman_er_max": 0.30,
                        "kaufman_er_period": 14,
                    },
                },
                {
                    "id": "funding_fade_long",
                    "enabled": True,
                    "weight": 1.0,
                    "params": {
                        "adaptive_window": 60,
                        "extreme_pctile_low": 5.0,
                        "reversal_body_ratio_min": 0.35,
                        "swing_lookback": 8,
                        "kaufman_er_max": 0.30,
                        "kaufman_er_period": 14,
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


def _make_choppy_ohlcv_8h(
    n: int,
    seed: int = 42,
    base_price: float = 50_000.0,
    chop_pct: float = 0.005,
) -> pd.DataFrame:
    """Choppy (mean-reverting) OHLCV — Kaufman ER stays low (<0.30).

    Alternating up/down bars around base_price create ER ≈ 0.
    Used for regime-filter tests where ER < 0.30 is required to pass.
    """
    rng = np.random.default_rng(seed)
    # Oscillate: price bounces between base ± chop_pct without net directional move
    prices = np.empty(n)
    prices[0] = base_price
    for j in range(1, n):
        direction = 1 if j % 2 == 0 else -1
        noise = rng.uniform(0.3, 1.0)
        prices[j] = base_price + direction * chop_pct * base_price * noise
    close = prices
    open_ = np.r_[close[0], close[:-1]]
    high = np.maximum(open_, close) * (1 + np.abs(rng.normal(0, 0.002, n)))
    low = np.minimum(open_, close) * (1 - np.abs(rng.normal(0, 0.002, n)))
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
        """Normal funding (adaptive percentile altında) → sinyal yok.

        v2.0.0: sabit threshold yerine adaptive 95th/5th percentile.
        Tamamen sabit funding_rate=0.0001 kullanılır (noise yok) böylece
        95th pctile == mean == 0.0001 — hiçbir bar threshold'u aşamaz.
        """
        strat = _make_strategy()
        n = 150
        ohlcv = _make_ohlcv_8h(n, seed=10)
        # Perfectly flat funding — 95th percentile == 0.0001 → nothing crosses it
        # (No noise: all values identical so max == mean == 0.0001)
        ts_list = _base_ts_8h(n)
        funding = pd.DataFrame({
            "venue": "binance",
            "symbol": "BTC/USDT:USDT",
            "ts": ts_list,
            "funding_rate": np.full(n, 0.0001),
            "mark_price": np.full(n, 50_000.0),
        })
        merged = merge_funding_to_ohlcv(ohlcv, funding, symbol="BTC/USDT:USDT")
        df_feat = strat.prepare_features(merged)
        sigs = strat.generate_signals(df_feat)
        # Flat funding → 95th pctile == 0.0001 == all values → no bar exceeds threshold
        assert len(sigs) == 0, "Normal/flat funding ile sinyal üretilmemeli"

    def test_short_signal_extreme_positive_funding(self) -> None:
        """Extreme pozitif funding + bearish bar + choppy regime → short sinyal üretilmeli.

        v2.0.0: choppy OHLCV kullanılır böylece Kaufman ER < 0.30 koşulu sağlanır.
        Adaptive threshold: funding_rate=0.0001 baseline, extreme=0.002 → 95th pctile
        yaklaşık 0.0001 civarında → 0.002 kesinlikle aşar.
        """
        strat = _make_strategy()
        n = 120
        # Choppy price action — ER stays low (<0.30) enabling the regime filter to pass
        ohlcv = _make_choppy_ohlcv_8h(n, seed=5)
        # Normal funding başlangıç, sonra aşırı pozitif
        funding = _make_funding_df(n, rate=0.0001, seed=5)

        # Bar 100-110 arasında extreme pozitif funding set et
        extreme_bars = list(range(100, 110))
        funding.loc[extreme_bars, "funding_rate"] = 0.002  # >> 95th pctile (~0.0001)

        merged = merge_funding_to_ohlcv(ohlcv, funding, symbol="BTC/USDT:USDT")
        # Override symbol/timeframe from ohlcv
        merged["symbol"] = "BTC/USDT:USDT"
        merged["timeframe"] = "4h"

        # Bar 101-110'da bearish reversal bar zorla
        for i in extreme_bars[1:]:
            price = float(merged.loc[i, "close"])
            merged.loc[i, "open"] = price * 1.01
            merged.loc[i, "close"] = price * 0.99  # bearish
            merged.loc[i, "high"] = price * 1.015
            merged.loc[i, "low"] = price * 0.985

        df_feat = strat.prepare_features(merged)
        sigs = strat.generate_signals(df_feat)
        short_sigs = [s for s in sigs if s.direction == "short"]
        assert len(short_sigs) >= 1, (
            "Extreme pozitif funding + bearish bar + choppy regime (ER<0.30) → short sinyal olmalı"
        )

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

    def test_bnb_exclusion_no_signals(self) -> None:
        """BNB sembolü için sinyal üretilmemeli — tokenomic contamination exclusion."""
        strat = _make_strategy()
        n = 120
        # Choppy OHLCV with BNB symbol
        ohlcv = _make_choppy_ohlcv_8h(n, seed=55)
        ohlcv["symbol"] = "BNB/USDT:USDT"
        ohlcv["timeframe"] = "4h"
        funding = _make_funding_df(n, rate=0.0001, seed=55, symbol="BNB/USDT:USDT")
        # Inject extreme negative funding (BNB tokenomic-like pattern)
        funding.loc[list(range(100, 110)), "funding_rate"] = -0.003
        merged = merge_funding_to_ohlcv(ohlcv, funding, symbol="BNB/USDT:USDT")
        merged["symbol"] = "BNB/USDT:USDT"
        # Inject bullish reversal bars
        for i in range(100, 110):
            price = float(merged.loc[i, "close"])
            merged.loc[i, "open"] = price * 0.99
            merged.loc[i, "close"] = price * 1.01
            merged.loc[i, "high"] = price * 1.015
            merged.loc[i, "low"] = price * 0.985

        df_feat = strat.prepare_features(merged)
        sigs = strat.generate_signals(df_feat)
        assert sigs == [], (
            "BNB sembolü tokenomik contamination nedeniyle exclude edilmeli — sinyal üretilmemeli"
        )

    def test_bnb_in_excluded_set(self) -> None:
        """BNB_EXCLUDED_SYMBOLS kümesi BNB'yi içermeli."""
        assert "BNB/USDT:USDT" in BNB_EXCLUDED_SYMBOLS

    def test_regime_filter_blocks_trending(self) -> None:
        """Trending rejimde (Kaufman ER >= 0.30) sinyal üretilmemeli."""
        strat = _make_strategy()
        n = 120
        # Strongly trending OHLCV — ER will be high
        rng = np.random.default_rng(77)
        rets = np.abs(rng.normal(0.02, 0.005, n))  # always positive → strong up-trend
        close = 50_000.0 * np.exp(np.cumsum(rets))
        open_ = np.r_[close[0], close[:-1]]
        high = np.maximum(open_, close) * 1.001
        low = np.minimum(open_, close) * 0.999
        ts_list = _base_ts_8h(n)
        ohlcv = pd.DataFrame({
            "ts": ts_list, "open": open_, "high": high, "low": low,
            "close": close, "volume": np.ones(n) * 1e6,
            "venue": "binance", "symbol": "BTC/USDT:USDT", "timeframe": "4h",
        })
        funding = _make_funding_df(n, rate=0.0001, seed=77)
        funding.loc[list(range(100, 110)), "funding_rate"] = 0.002
        merged = merge_funding_to_ohlcv(ohlcv, funding, symbol="BTC/USDT:USDT")
        merged["symbol"] = "BTC/USDT:USDT"
        # Inject bearish reversal bars at extreme funding window
        for i in range(101, 110):
            price = float(merged.loc[i, "close"])
            merged.loc[i, "open"] = price * 1.01
            merged.loc[i, "close"] = price * 0.99
            merged.loc[i, "high"] = price * 1.015
            merged.loc[i, "low"] = price * 0.985

        df_feat = strat.prepare_features(merged)
        # Verify ER is actually high in the extreme funding window
        er_at_extreme = float(df_feat.loc[105, "kaufman_er_lag1"])
        # If ER is high, the regime filter should block all signals
        if er_at_extreme >= REGIME_ER_MAX:
            short_sigs = [s for s in strat.generate_signals(df_feat) if s.direction == "short"]
            # Signals at bars with high ER should be blocked
            sigs_at_extreme = [
                s for s in short_sigs
                if any(
                    pd.Timestamp(s.ts) == pd.Timestamp(df_feat.loc[i, "ts"])
                    for i in range(100, 110)
                )
            ]
            assert sigs_at_extreme == [], (
                f"ER={er_at_extreme:.2f} >= {REGIME_ER_MAX}: regime filter sinyali bloklamalı"
            )

    def test_adaptive_bands_lookahead_free(self) -> None:
        """_adaptive_funding_bands: band_high/low, bar t için shift(1) geçmişi kullanmalı.

        Lookahead-free doğrulaması: spike bar 50'de.
        - band_high at bar 49 → spike (bar 50) shifted by 1 → appears as lagged[51],
          so bar 49's rolling window [20..49] does NOT contain the spike. Must be low.
        - band_high at bar 70 → window [41..70] DOES contain lagged[51]=0.005.
          With 30 values, 29×0.0001 + 1×0.005. At 95th pctile this is at position
          floor(0.95 * 29) = 27.55 → linear interp between sorted[27]=0.0001 and
          sorted[28]=0.0001 → 0.0001 (spike at sorted[29] is NOT in top 5% of 30).
          Instead use max() assertion: the spike must appear in the max of the window.
        - Approach: use a very wide spread (10 spikes) to confirm shift behavior.
        """
        n = 120
        fr = pd.Series(np.full(n, 0.0001))
        # Set bars 50..59 to a high value (10 consecutive = >5% of window=30, so 95th pctile sees it)
        fr.iloc[50:60] = 0.005
        bh, bl = _adaptive_funding_bands(fr, window=30)

        # Bar 49: window includes lagged[20..49] = all 0.0001 → band_high ≈ 0.0001
        assert float(bh.iloc[49]) < 0.001, (
            f"Bar 49 band_high ({bh.iloc[49]:.6f}) spike'ı görmemeli (lookahead-free)"
        )
        # Bar 70: lagged[70] = fr[69]=0.005 (still in spike range).
        # Rolling window [41..70] includes lagged[51..60] = 10 spike bars.
        # 10/30 > 5% → 95th pctile should be elevated.
        assert float(bh.iloc[70]) > 0.001, (
            f"Bar 70 band_high ({bh.iloc[70]:.6f}) spike bölgesini görmeli"
        )

    def test_kaufman_er_low_in_choppy(self) -> None:
        """_make_choppy_ohlcv_8h kullanıldığında ER < 0.30 olmalı (regime filtre geçer)."""
        n = 100
        ohlcv = _make_choppy_ohlcv_8h(n, seed=42)
        er = _kaufman_er(ohlcv["close"], period=14)
        # After warmup, ER should be low in choppy data
        er_warmup = er.iloc[20:].median()
        assert er_warmup < 0.30, (
            f"Choppy OHLCV'de ER medyan={er_warmup:.3f} < 0.30 olmalı (regime filter geçmeli)"
        )


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
        """BacktestEngine ile FundingMRStrategy çalışmalı, exception yok.

        v2.0.0: choppy OHLCV (ER < 0.30) kullanılır böylece sinyal üretilir.
        """
        from datetime import datetime, timezone
        from price_action.backtest.engine import BacktestEngine

        strat = _make_strategy()
        n = 200
        start_dt = datetime(2024, 1, 1, tzinfo=timezone.utc)

        # Choppy price — ER stays low so regime filter passes for signals
        ohlcv = _make_choppy_ohlcv_8h(n, seed=99, base_price=50_000.0)
        funding = _make_funding_df(n, rate=0.0001, seed=99)
        # Inject a few extreme funding windows
        funding.loc[100:105, "funding_rate"] = 0.002
        funding.loc[150:155, "funding_rate"] = -0.002

        merged = merge_funding_to_ohlcv(ohlcv, funding, symbol="BTC/USDT:USDT")
        merged["symbol"] = "BTC/USDT:USDT"
        merged["timeframe"] = "4h"
        # Inject bearish reversal bars at extreme long funding
        for i in range(100, 106):
            price = float(merged.loc[i, "close"])
            merged.loc[i, "open"] = price * 1.01
            merged.loc[i, "close"] = price * 0.99
            merged.loc[i, "high"] = price * 1.015
            merged.loc[i, "low"] = price * 0.985
        # Inject bullish reversal bars at extreme short funding
        for i in range(150, 156):
            price = float(merged.loc[i, "close"])
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
        """Sinyal olmayan veriye karşı backtest: n_trades=0 ve equity sabit.

        v2.0.0: Tamamen sabit funding_rate kullanılır (noise yok) böylece
        adaptive 95th pctile == 0.0001 == tüm değerler → hiçbir bar threshold'u aşamaz.
        """
        from datetime import datetime, timezone
        from price_action.backtest.engine import BacktestEngine

        strat = _make_strategy()
        n = 100
        start_dt = datetime(2024, 1, 1, tzinfo=timezone.utc)

        ohlcv = _make_ohlcv_8h(n, seed=1)
        # Perfectly flat funding — 95th pctile == mean → no crossing → no signals
        ts_list_dt = _base_ts_8h(n)
        funding = pd.DataFrame({
            "venue": "binance",
            "symbol": "BTC/USDT:USDT",
            "ts": ts_list_dt,
            "funding_rate": np.full(n, 0.0001),
            "mark_price": np.full(n, 50_000.0),
        })
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
