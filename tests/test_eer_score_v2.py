"""EER-Score v2 testleri: hierarchical fallback + Bayesian shrinkage + edge-gate.

Pre-registered: memory/researcher/hypotheses/2026-05-14-eer-score-v2.md

Testler:
  1. Look-ahead bias yok (history: exit_ts < entry_ts)
  2. Hierarchical fallback dogru level cikariyor (L1 -> L2 -> L3 -> L4)
  3. Bayesian shrinkage formul dogru (n=0 → global, n=large → bucket)
  4. Edge ratio computation dogru
  5. Config + reproducibility hash
  6. 4-dim bucket key — funding/fng kullanilmiyor
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# Helpers — sentetik veri kurma (v1 testleri ile ayni pattern)
# ---------------------------------------------------------------------------
def _build_btc_df(start: str = "2020-01-01", n: int = 1500) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    ts = pd.date_range(start, periods=n, freq="1D", tz="UTC")
    rets = rng.normal(0.001, 0.03, size=n)
    close = 30_000.0 * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.001, 0.02, n))
    low = close * (1 - rng.uniform(0.001, 0.02, n))
    return pd.DataFrame({
        "ts": ts, "open": close,
        "high": np.maximum(high, close),
        "low": np.minimum(low, close),
        "close": close,
        "volume": rng.uniform(1000, 5000, n),
    })


def _build_sym_df(start: str = "2020-01-01", n: int = 1500, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    ts = pd.date_range(start, periods=n, freq="1D", tz="UTC")
    rets = rng.normal(0.002, 0.04, size=n)
    close = 100.0 * np.exp(np.cumsum(rets))
    high = close * (1 + rng.uniform(0.001, 0.03, n))
    low = close * (1 - rng.uniform(0.001, 0.03, n))
    return pd.DataFrame({
        "ts": ts, "open": close,
        "high": np.maximum(high, close),
        "low": np.minimum(low, close),
        "close": close,
        "volume": rng.uniform(500, 1500, n),
    })


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
    # v2 funding/fng kullanmiyor; dummy data
    funding = pd.DataFrame({"ts": pd.to_datetime(["2020-01-01"], utc=True), "fundingRate": [0.0001]})
    fng = pd.DataFrame({"ts": pd.to_datetime(["2020-01-01"], utc=True), "value": [50]})
    return FeatureContext(
        btc_daily=btc_feats,
        symbol_atr_pct=sym_atr,
        symbol_atr_quantiles=sym_q,
        funding=funding,
        fng=fng,
    )


def _build_trades_dense(n: int = 2000, seed: int = 0) -> list[dict]:
    """Yogun trade — bucket coverage testi icin.

    Daha az sembol/strateji → buckets dolar; 4-dim coverage saglanir.
    """
    rng = np.random.default_rng(seed)
    symbols = ["BTC/USDT", "ETH/USDT"]
    strategies = ["engulfing_continuation", "brooks_h2_l2"]
    out = []
    base = pd.Timestamp("2021-01-01", tz="UTC")
    for i in range(n):
        entry = base + pd.Timedelta(days=int(rng.integers(0, 1200)))
        hold = int(rng.integers(1, 8))
        exit_ = entry + pd.Timedelta(days=hold)
        out.append({
            "entry_ts": entry,
            "exit_ts": exit_,
            "symbol": rng.choice(symbols),
            "side": rng.choice(["long", "short"]),
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
class TestShrinkage:
    def test_shrinkage_zero_n_returns_global(self):
        from price_action.backtest.eer_score import _shrunken_avg
        assert _shrunken_avg([], global_avg=0.3, k=20) == 0.3

    def test_shrinkage_small_n_pulls_toward_global(self):
        from price_action.backtest.eer_score import _shrunken_avg
        bucket = [2.0, 2.0, 2.0, 2.0, 2.0]  # n=5, bucket_avg = 2.0
        # k=20, global=0.0 -> shrunken = (5*2.0 + 20*0.0)/25 = 0.4
        result = _shrunken_avg(bucket, global_avg=0.0, k=20)
        assert abs(result - 0.4) < 1e-6, f"Expected 0.4, got {result}"

    def test_shrinkage_large_n_stays_near_bucket(self):
        from price_action.backtest.eer_score import _shrunken_avg
        bucket = [2.0] * 1000  # n=1000
        # k=20, global=0 -> shrunken = (1000*2.0 + 20*0) / 1020 ~= 1.96
        result = _shrunken_avg(bucket, global_avg=0.0, k=20)
        assert abs(result - 1.96) < 0.01

    def test_shrinkage_k_zero_returns_bucket(self):
        from price_action.backtest.eer_score import _shrunken_avg
        bucket = [1.5, 2.5]  # avg 2.0
        result = _shrunken_avg(bucket, global_avg=0.0, k=0)
        assert abs(result - 2.0) < 1e-6


class TestBucketKey4Dim:
    def test_v2_bucket_key_has_4_components(self):
        """v2 bucket key 4 elemandan olusur (funding/fng cikartilmis)."""
        from price_action.backtest.eer_score import _bucket_key_v2_4dim
        ctx = _build_context(["BTC/USDT"])
        entry = pd.Timestamp("2022-06-01", tz="UTC")
        bk = _bucket_key_v2_4dim(entry, "BTC/USDT", "engulfing_continuation", ctx)
        assert len(bk) == 4, f"Expected 4-dim, got {len(bk)}"
        assert bk[0] == "engulfing_continuation"
        assert bk[1] == "BTC/USDT"
        assert bk[2] in ("bull", "bear", "range")
        assert bk[3] in ("low", "mid", "high")


class TestHierarchicalFallback:
    def test_hierarchical_resolves_at_lower_levels(self):
        """v2 fix: hierarchical fallback level 2-3 ile coverage saglanir.

        4-dim L1 sample_min=30 sentetik veride ulasilamaz; L2/L3 dolar.
        Gercek 5y trade pool'da L1 cogu yuksek-frekansli bucket icin >=%10
        beklenir (gercek backtest gosterecek).
        """
        from price_action.backtest.eer_score import (
            compute_eer_v2_for_trades, EERConfigV2,
        )
        ctx = _build_context(["BTC/USDT", "ETH/USDT"])
        trades = _build_trades_dense(n=1500, seed=0)
        out, stats = compute_eer_v2_for_trades(trades, ctx, EERConfigV2())
        s = stats.summary()
        # En az L2 veya L3 cogu trade'i resolved etmis olmali
        resolved = s["n_l1"] + s["n_l2"] + s["n_l3"]
        assert resolved > 0.5 * s["n_total"], (
            f"Hierarchical fallback should resolve >50% trades: {s}"
        )
        # Bucket coverage L1-L3 sentetik veride bile %30 ustu olmali (v1 %0 idi)
        assert s["bucket_coverage_l1_l3"] >= 0.30, (
            f"Coverage gate >=30% missed: {s['bucket_coverage_l1_l3']}"
        )

    def test_fallback_distribution_includes_all_levels_or_l4(self):
        from price_action.backtest.eer_score import (
            compute_eer_v2_for_trades, EERConfigV2,
        )
        ctx = _build_context(["BTC/USDT", "ETH/USDT"])
        trades = _build_trades_dense(n=1500, seed=11)
        out, stats = compute_eer_v2_for_trades(trades, ctx, EERConfigV2())
        # Levels toplami + fallback = total
        s = stats.summary()
        total_resolved = s["n_l1"] + s["n_l2"] + s["n_l3"] + s["n_l4"] + s["n_fallback"]
        assert total_resolved == s["n_total"]

    def test_eer_values_in_unit_interval(self):
        from price_action.backtest.eer_score import (
            compute_eer_v2_for_trades, EERConfigV2,
        )
        ctx = _build_context(["BTC/USDT", "ETH/USDT"])
        trades = _build_trades_dense(n=500, seed=3)
        out, _ = compute_eer_v2_for_trades(trades, ctx, EERConfigV2())
        for t in out:
            assert 0.0 <= t["eer_v2"] <= 1.0, f"EER v2 out of range: {t['eer_v2']}"


class TestLeakageV2:
    def test_history_only_closed_trades_v2(self):
        """v2: exit_ts >= entry_ts olan trade'ler kullanilamaz."""
        from price_action.backtest.eer_score import (
            compute_eer_v2_for_trades, EERConfigV2,
        )
        ctx = _build_context(["BTC/USDT"])

        # Hedef trade — bunun EER'i hesaplaniyor
        target_entry = pd.Timestamp("2022-06-01", tz="UTC")
        target = {
            "entry_ts": target_entry,
            "exit_ts": target_entry + pd.Timedelta(days=5),
            "symbol": "BTC/USDT",
            "strategy": "engulfing_continuation",
            "side": "long",
            "R": 0.5,
        }
        # Leaky: exit_ts > target_entry
        leaky = {
            "entry_ts": target_entry - pd.Timedelta(days=30),
            "exit_ts": target_entry + pd.Timedelta(days=10),
            "symbol": "BTC/USDT",
            "strategy": "engulfing_continuation",
            "side": "long",
            "R": 99.0,
        }
        pool = [leaky, target]
        out, _ = compute_eer_v2_for_trades(pool, ctx, EERConfigV2())
        # Target trade fallback alir (history yetersiz cunku leaky drop edildi)
        target_out = [t for t in out if t["entry_ts"] == target_entry][0]
        # 0.50 fallback OR bucket_n=0 — leaky kullanilmamali
        # Eer leaky kullanilsaydi extreme R=99 → top rank olurdu (1.0)
        assert target_out["eer_v2"] != 1.0, "Look-ahead leakage detected (extreme R 99 leaked)"


class TestEdgeRatio:
    def test_edge_ratio_positive_high(self):
        from price_action.backtest.eer_score import compute_in_sample_edge_ratio
        # top tier: avg_R=1.0, bot tier: avg_R=0.2 -> ratio 5.0
        trades = []
        for _ in range(50):
            trades.append({"R": 1.0, "eer_v2": 0.9})
        for _ in range(50):
            trades.append({"R": 0.2, "eer_v2": 0.1})
        r = compute_in_sample_edge_ratio(trades, score_field="eer_v2")
        assert abs(r - 5.0) < 0.01

    def test_edge_ratio_insufficient_sample(self):
        from price_action.backtest.eer_score import compute_in_sample_edge_ratio
        # < 30 trade per tier -> ratio = 1.0
        trades = [{"R": 1.0, "eer_v2": 0.9} for _ in range(10)]
        r = compute_in_sample_edge_ratio(trades, score_field="eer_v2")
        assert r == 1.0

    def test_edge_ratio_bot_zero_or_negative(self):
        from price_action.backtest.eer_score import compute_in_sample_edge_ratio
        # bot avg = 0 -> return 1.0 (cant compute ratio)
        trades = []
        for _ in range(40):
            trades.append({"R": 1.0, "eer_v2": 0.9})
        for _ in range(40):
            trades.append({"R": 0.0, "eer_v2": 0.1})
        r = compute_in_sample_edge_ratio(trades, score_field="eer_v2")
        # bot_avg = 0, top_avg = 1.0 -> 999.0 (extreme edge)
        assert r == 999.0


class TestReproducibilityV2:
    def test_v2_deterministic(self):
        from price_action.backtest.eer_score import compute_eer_v2_for_trades, EERConfigV2
        ctx = _build_context(["BTC/USDT", "ETH/USDT"])
        trades = _build_trades_dense(n=300, seed=42)
        out1, st1 = compute_eer_v2_for_trades(trades, ctx, EERConfigV2())
        out2, st2 = compute_eer_v2_for_trades(trades, ctx, EERConfigV2())
        for t1, t2 in zip(out1, out2):
            assert t1["eer_v2"] == t2["eer_v2"], "Non-deterministic v2 EER"
        assert st1.n_l1 == st2.n_l1

    def test_v2_config_hash_stable(self):
        from price_action.backtest.eer_score import EERConfigV2
        c1 = EERConfigV2()
        c2 = EERConfigV2()
        assert c1.config_hash() == c2.config_hash()

    def test_v2_config_hash_changes_with_k(self):
        from price_action.backtest.eer_score import EERConfigV2
        c1 = EERConfigV2(shrinkage_k=20)
        c2 = EERConfigV2(shrinkage_k=40)
        assert c1.config_hash() != c2.config_hash()
