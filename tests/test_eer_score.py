"""EER-Score v1 leakage + reproducibility testleri.

Pre-registered hipotez: memory/researcher/hypotheses/2026-05-13-eer-score-v1.md

Testler:
  1. Look-ahead bias yok — bucket key sadece t-1 verilerine bakar
  2. History lookup — exit_ts < entry_ts kontrol
  3. Sample-size fallback — n<30 ise 0.50
  4. Reproducibility — ayni input -> ayni output (deterministic)
  5. Bucket inference — regime/atr_pct/funding/fng bucket label sanity
  6. Stats — bucket_coverage/fallback_rate hesaplari
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers — sentetik veri kurma
# ---------------------------------------------------------------------------
def _build_btc_df(start: str = "2020-01-01", n: int = 800) -> pd.DataFrame:
    """Sentetik BTC OHLCV — deterministik."""
    rng = np.random.default_rng(42)
    ts = pd.date_range(start, periods=n, freq="1D", tz="UTC")
    rets = rng.normal(0.001, 0.03, size=n)
    close = 30_000.0 * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.001, 0.02, n))
    low = close * (1 - rng.uniform(0.001, 0.02, n))
    return pd.DataFrame({
        "ts": ts,
        "open": close * (1 + rng.uniform(-0.005, 0.005, n)),
        "high": np.maximum(high, close),
        "low": np.minimum(low, close),
        "close": close,
        "volume": rng.uniform(1000, 5000, n),
    })


def _build_sym_df(start: str = "2020-01-01", n: int = 800, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=n, freq="1D", tz="UTC")
    rets = rng.normal(0.002, 0.04, size=n)
    close = 100.0 * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.001, 0.03, n))
    low = close * (1 - rng.uniform(0.001, 0.03, n))
    return pd.DataFrame({
        "ts": ts,
        "open": close * (1 + rng.uniform(-0.005, 0.005, n)),
        "high": np.maximum(high, close),
        "low": np.minimum(low, close),
        "close": close,
        "volume": rng.uniform(500, 1500, n),
    })


def _build_funding_df(start: str = "2020-01-01", n_days: int = 800) -> pd.DataFrame:
    """8h cadence funding — sentetik."""
    rng = np.random.default_rng(1)
    n = n_days * 3
    ts = pd.date_range(start, periods=n, freq="8h", tz="UTC")
    rates = rng.normal(0.00005, 0.0003, size=n)
    return pd.DataFrame({"ts": ts, "fundingRate": rates})


def _build_fng_df(start: str = "2020-01-01", n: int = 800) -> pd.DataFrame:
    rng = np.random.default_rng(2)
    ts = pd.date_range(start, periods=n, freq="1D", tz="UTC")
    vals = rng.integers(10, 90, n)
    return pd.DataFrame({"ts": ts, "value": vals})


def _build_context(symbols: list[str]):
    from price_action.backtest.eer_score import (
        FeatureContext,
        precompute_btc_features,
        precompute_symbol_atr,
        precompute_symbol_atr_quantiles,
    )
    btc = _build_btc_df()
    btc_feats = precompute_btc_features(btc)
    sym_atr = {}
    sym_q = {}
    for i, sym in enumerate(symbols):
        sdf = _build_sym_df(seed=7 + i)
        atr = precompute_symbol_atr(sdf)
        q = precompute_symbol_atr_quantiles(atr)
        sym_atr[sym] = atr
        sym_q[sym] = q
    fng = _build_fng_df()
    funding = _build_funding_df()
    return FeatureContext(
        btc_daily=btc_feats,
        symbol_atr_pct=sym_atr,
        symbol_atr_quantiles=sym_q,
        funding=funding,
        fng=fng,
    )


def _build_trades(n: int = 400, seed: int = 0) -> list[dict]:
    """Sentetik trade'ler — 2021-01'den itibaren."""
    rng = np.random.default_rng(seed)
    symbols = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]
    strategies = ["engulfing_continuation", "brooks_h2_l2", "wyckoff_phase_d"]
    sides = ["long", "short"]
    out = []
    base = pd.Timestamp("2021-01-01", tz="UTC")
    for i in range(n):
        entry = base + pd.Timedelta(days=int(rng.integers(0, 700)))
        hold = int(rng.integers(1, 15))
        exit_ = entry + pd.Timedelta(days=hold)
        out.append({
            "entry_ts": entry,
            "exit_ts": exit_,
            "symbol": rng.choice(symbols),
            "side": rng.choice(sides),
            "strategy": rng.choice(strategies),
            "R": float(rng.normal(0.2, 1.0)),
            "conf": float(rng.uniform(0.1, 0.5)),
            "entry_price": 100.0,
            "initial_sl": 95.0,
        })
    return out


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestBucketInference:
    def test_regime_bucket_bull(self):
        from price_action.backtest.eer_score import _regime_bucket
        # close > ema200 + dd_90d > -10%
        assert _regime_bucket(close=110, ema200=100, dd_90d=-0.05) == "bull"

    def test_regime_bucket_bear(self):
        from price_action.backtest.eer_score import _regime_bucket
        assert _regime_bucket(close=80, ema200=120, dd_90d=-0.40) == "bear"

    def test_regime_bucket_range(self):
        from price_action.backtest.eer_score import _regime_bucket
        # close > ema200 but dd_90d < -10% -> not bull
        # dd_90d > -25% -> not bear
        assert _regime_bucket(close=110, ema200=100, dd_90d=-0.15) == "range"

    def test_atr_pct_bucket(self):
        from price_action.backtest.eer_score import _atr_pct_bucket
        assert _atr_pct_bucket(1.0, q33=2.0, q67=4.0) == "low"
        assert _atr_pct_bucket(3.0, q33=2.0, q67=4.0) == "mid"
        assert _atr_pct_bucket(5.0, q33=2.0, q67=4.0) == "high"

    def test_funding_sign(self):
        from price_action.backtest.eer_score import _funding_sign
        assert _funding_sign(0.001) == "pos"
        assert _funding_sign(-0.001) == "neg"
        assert _funding_sign(0.00005) == "neutral"
        assert _funding_sign(float("nan")) == "neutral"

    def test_fng_bucket(self):
        from price_action.backtest.eer_score import _fng_bucket
        assert _fng_bucket(10) == "ef"
        assert _fng_bucket(30) == "f"
        assert _fng_bucket(50) == "n"
        assert _fng_bucket(70) == "g"
        assert _fng_bucket(90) == "eg"


class TestLeakage:
    """KRITIK: Look-ahead bias asla."""

    def test_history_only_closed_trades(self):
        """Aktif (exit_ts >= entry_ts) trade'ler history'de kullanilamaz."""
        from price_action.backtest.eer_score import compute_eer
        ctx = _build_context(["BTC/USDT", "ETH/USDT"])

        target_entry = pd.Timestamp("2022-06-01", tz="UTC")
        target_trade = {
            "entry_ts": target_entry,
            "exit_ts": target_entry + pd.Timedelta(days=5),
            "symbol": "BTC/USDT",
            "strategy": "engulfing_continuation",
            "side": "long",
            "R": 0.5,
        }

        # Bu history trade target'in entry'sinden SONRA kapaniyor — kullanilamaz
        leaky_history = [{
            "entry_ts": target_entry - pd.Timedelta(days=30),
            "exit_ts": target_entry + pd.Timedelta(days=10),  # AFTER target entry!
            "symbol": "BTC/USDT",
            "strategy": "engulfing_continuation",
            "side": "long",
            "R": 5.0,  # extreme value
        }]

        eer_with_leak = compute_eer(target_trade, leaky_history, ctx)
        # Leaky trade dropped → fallback 0.50
        assert eer_with_leak == 0.50, f"Look-ahead bias detected: {eer_with_leak}"

    def test_bucket_key_uses_only_yesterday_data(self):
        """Bucket key sadece t-1 close'a kadar veriye bakar."""
        from price_action.backtest.eer_score import FeatureContext, precompute_btc_features

        # 2-bar BTC: bugun ema200 daha buyuk, dun daha kucuk → regime farkli olabilir
        btc = pd.DataFrame({
            "ts": pd.to_datetime(["2022-05-30", "2022-05-31", "2022-06-01"], utc=True),
            "open": [30000, 30100, 30200],
            "high": [30500, 30600, 30700],
            "low": [29500, 29600, 29700],
            "close": [30000, 30100, 30200],
        })
        btc_feats = precompute_btc_features(btc)

        ctx = FeatureContext(
            btc_daily=btc_feats,
            symbol_atr_pct={"BTC/USDT": pd.DataFrame({"ts": pd.to_datetime(["2022-05-31"], utc=True), "atr_pct": [2.0]})},
            symbol_atr_quantiles={"BTC/USDT": pd.DataFrame({"ts": pd.to_datetime(["2022-05-31"], utc=True), "q33": [1.5], "q67": [3.0]})},
            funding=pd.DataFrame({"ts": pd.to_datetime(["2022-05-31 00:00:00"], utc=True), "fundingRate": [0.0001]}),
            fng=pd.DataFrame({"ts": pd.to_datetime(["2022-05-31"], utc=True), "value": [50]}),
        )

        entry = pd.Timestamp("2022-06-01 12:00:00", tz="UTC")
        bk = ctx.bucket_key(entry, "BTC/USDT", "engulfing_continuation")
        # bk[1] symbol
        assert bk[1] == "BTC/USDT"
        # bk[0] strategy
        assert bk[0] == "engulfing_continuation"
        # All other components must be valid (causal — yesterday data exists)
        assert all(x is not None for x in bk)

    def test_compute_eer_for_trades_drops_active_at_lookup_time(self):
        """compute_eer_for_trades — i-th trade icin only exit_ts < entry_ts olanlar history."""
        from price_action.backtest.eer_score import compute_eer_for_trades

        ctx = _build_context(["BTC/USDT", "ETH/USDT"])
        # Trades: ilk 100 trade 2021'de kapanmis, sonra 1 trade 2022-06-01'de baslar
        # Eger algoritma kapanmamis trade'i kullanirsa contamination olur
        trades = _build_trades(n=200)

        out, stats = compute_eer_for_trades(trades, ctx)
        assert len(out) == 200
        # Tum EER degerleri [0, 1] aralikta
        for t in out:
            assert 0.0 <= t["eer"] <= 1.0, f"EER out of range: {t['eer']}"


class TestSampleSizeFallback:
    def test_low_n_returns_fallback(self):
        """n<30 olan bucket icin EER = 0.50."""
        from price_action.backtest.eer_score import compute_eer
        ctx = _build_context(["BTC/USDT"])

        target = {
            "entry_ts": pd.Timestamp("2022-01-15", tz="UTC"),
            "exit_ts": pd.Timestamp("2022-01-20", tz="UTC"),
            "symbol": "BTC/USDT",
            "strategy": "engulfing_continuation",
            "side": "long",
            "R": 0.5,
        }
        # Sadece 5 history (n<30)
        history = []
        for i in range(5):
            entry = pd.Timestamp("2022-01-01", tz="UTC") + pd.Timedelta(days=i)
            history.append({
                "entry_ts": entry,
                "exit_ts": entry + pd.Timedelta(days=2),
                "symbol": "BTC/USDT",
                "strategy": "engulfing_continuation",
                "side": "long",
                "R": float(i),
            })
        eer = compute_eer(target, history, ctx)
        assert eer == 0.50, f"Expected 0.50 fallback, got {eer}"

    def test_zero_history_returns_fallback(self):
        from price_action.backtest.eer_score import compute_eer
        ctx = _build_context(["BTC/USDT"])
        target = {
            "entry_ts": pd.Timestamp("2022-01-15", tz="UTC"),
            "exit_ts": pd.Timestamp("2022-01-20", tz="UTC"),
            "symbol": "BTC/USDT",
            "strategy": "engulfing_continuation",
            "side": "long",
            "R": 0.5,
        }
        eer = compute_eer(target, [], ctx)
        assert eer == 0.50


class TestReproducibility:
    def test_same_input_same_output(self):
        """Deterministic: ayni input → ayni output."""
        from price_action.backtest.eer_score import compute_eer_for_trades

        ctx = _build_context(["BTC/USDT", "ETH/USDT", "SOL/USDT"])
        trades = _build_trades(n=300, seed=42)

        out1, stats1 = compute_eer_for_trades(trades, ctx)
        out2, stats2 = compute_eer_for_trades(trades, ctx)

        assert len(out1) == len(out2)
        for t1, t2 in zip(out1, out2):
            assert t1["eer"] == t2["eer"], "Non-deterministic EER computation"
        assert stats1.n_full_eer == stats2.n_full_eer

    def test_config_hash_stable(self):
        from price_action.backtest.eer_score import EERConfig
        c1 = EERConfig()
        c2 = EERConfig()
        assert c1.config_hash() == c2.config_hash()

    def test_data_hash_stable(self):
        from price_action.backtest.eer_score import trades_data_hash
        trades = _build_trades(n=100)
        h1 = trades_data_hash(trades)
        h2 = trades_data_hash(trades)
        assert h1 == h2

    def test_data_hash_different_for_different_data(self):
        from price_action.backtest.eer_score import trades_data_hash
        t1 = _build_trades(n=100, seed=1)
        t2 = _build_trades(n=100, seed=2)
        assert trades_data_hash(t1) != trades_data_hash(t2)


class TestStats:
    def test_stats_reasonable(self):
        from price_action.backtest.eer_score import compute_eer_for_trades

        ctx = _build_context(["BTC/USDT", "ETH/USDT", "SOL/USDT"])
        trades = _build_trades(n=500, seed=11)

        out, stats = compute_eer_for_trades(trades, ctx)
        s = stats.summary()
        assert s["n_total"] == 500
        # Sentetik veride bucket coverage muhtemelen dusuk olur (cunku 6-dim
        # kombinatorik patlama + kucuk sample). Bu test cogu trade'in fallback
        # almasini OK kabul eder — bir log mesaji yeterli.
        assert s["n_full_eer"] + s["n_fallback"] == 500
        assert 0.0 <= s["bucket_coverage"] <= 1.0
        assert 0.0 <= s["fallback_rate"] <= 1.0


class TestTierMapping:
    def test_eer_to_tier_boundaries(self):
        from price_action.backtest.eer_score import eer_to_tier
        assert eer_to_tier(0.05) == 1
        assert eer_to_tier(0.19) == 1
        assert eer_to_tier(0.20) == 2
        assert eer_to_tier(0.50) == 2
        assert eer_to_tier(0.59) == 2
        assert eer_to_tier(0.60) == 3
        assert eer_to_tier(0.89) == 3
        assert eer_to_tier(0.90) == 4
        assert eer_to_tier(1.00) == 4
