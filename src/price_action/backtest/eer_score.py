"""EER-Score v1 — Expected Edge Rank Percentile.

CEO Brief 2026-05-12 ref bolum 4.1. Mevcut confluence_score (4787 trade'in
%96.9'u tek bucket'ta yigili, top tier %77 yigili) BOZUK; DYNAMIC v0.9.8 buna
bagimli oldugu icin patladi (+%2.5 yillik).

EER pre-registered hipotez: `memory/researcher/hypotheses/2026-05-13-eer-score-v1.md`

Tasarim:
  Her trade icin, **entry_ts'inden onceki 180 gunde**, ayni 6-dim bucket key
  kombinasyonundaki kapanmis trade'lerin avg_R'sini hesapla. Bu degerin, ayni
  pencere icindeki TUM bucket'larin avg_R distribution'undaki percentile rank'i
  EER'dir. n<30 olan bucket'lar 0.50 medyan fallback alir.

Look-ahead bias YASAK:
  - Bucket key: trade entry_ts - 1 gun close'una kadar bilinen veriler.
  - History lookup: exit_ts < trade.entry_ts (kapanmis trade).
  - Funding/F&G: T-1 00:00 cut (causal).

Reproducibility:
  - data_hash + config_hash kayit
  - tests/test_eer_score.py 4 leakage testi gecmeden production'a girmez.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

import numpy as np
import pandas as pd

# Default config — pre-registered hipoteze gore sabit. SWEEP YASAK (HARK koruma).
DEFAULT_LOOKBACK_DAYS: int = 180
DEFAULT_SAMPLE_MIN: int = 30
DEFAULT_FEATURE_KEYS: tuple[str, ...] = (
    "strategy_id",
    "symbol",
    "regime_bucket",
    "atr_pct_bucket",
    "funding_sign",
    "fng_bucket",
)
DEFAULT_FALLBACK_EER: float = 0.50
DEFAULT_MIN_BUCKETS_FOR_RANK: int = 5

# Regime threshold'lari (hipoteze gore sabit)
REGIME_DD_BULL: float = -0.10
REGIME_DD_BEAR: float = -0.25
ATR_PCT_QUANTILES: tuple[float, float] = (0.33, 0.67)
FUNDING_THRESHOLDS: tuple[float, float] = (-1e-4, 1e-4)
FNG_THRESHOLDS: tuple[int, int, int, int] = (20, 40, 60, 80)


# ---------------------------------------------------------------------------
# Bucket inference (CAUSAL — sadece t-1 close'a kadar bilinen veri)
# ---------------------------------------------------------------------------
def _regime_bucket(close: float, ema200: float, dd_90d: float) -> str:
    """BTC EMA200 + 90d DD'ye gore regime.

    bull: close > ema200 AND dd_90d > -10%
    bear: dd_90d <= -25%
    range: aksi durumda
    """
    if pd.isna(close) or pd.isna(ema200) or pd.isna(dd_90d):
        return "range"  # conservative fallback
    if close > ema200 and dd_90d > REGIME_DD_BULL:
        return "bull"
    if dd_90d <= REGIME_DD_BEAR:
        return "bear"
    return "range"


def _atr_pct_bucket(atr_pct: float, q33: float, q67: float) -> str:
    """ATR% 252-bar trailing quintile-ish (3-bucket).

    low:  atr_pct < q33
    mid:  q33 <= atr_pct < q67
    high: atr_pct >= q67
    """
    if pd.isna(atr_pct) or pd.isna(q33) or pd.isna(q67):
        return "mid"
    if atr_pct < q33:
        return "low"
    if atr_pct < q67:
        return "mid"
    return "high"


def _funding_sign(funding_rate: float) -> str:
    """T-1 00:00 BTC funding rate sign bucket.

    pos: > +1e-4
    neg: < -1e-4
    neutral: aralik
    """
    if pd.isna(funding_rate):
        return "neutral"
    if funding_rate > FUNDING_THRESHOLDS[1]:
        return "pos"
    if funding_rate < FUNDING_THRESHOLDS[0]:
        return "neg"
    return "neutral"


def _fng_bucket(fng_value: float) -> str:
    """Fear & Greed Index bucket (5 kova).

    ef (extreme_fear): < 20
    f  (fear):        [20, 40)
    n  (neutral):     [40, 60)
    g  (greed):       [60, 80)
    eg (extreme_greed): >= 80
    """
    if pd.isna(fng_value):
        return "n"  # neutral fallback (causal-safe)
    v = int(fng_value)
    if v < FNG_THRESHOLDS[0]:
        return "ef"
    if v < FNG_THRESHOLDS[1]:
        return "f"
    if v < FNG_THRESHOLDS[2]:
        return "n"
    if v < FNG_THRESHOLDS[3]:
        return "g"
    return "eg"


@dataclass
class FeatureContext:
    """Causal feature pipeline — bucket inference icin gerekli zaman serisi.

    Tum seriler tz-aware UTC olmali. Tum lookup'lar `as-of yesterday close`
    (entry_ts.normalize() - 1 day) noktasinda yapilir.
    """
    btc_daily: pd.DataFrame                      # ts, close, ema200, dd_90d
    symbol_atr_pct: dict[str, pd.DataFrame]      # symbol -> ts, atr_pct
    symbol_atr_quantiles: dict[str, pd.DataFrame]  # symbol -> ts, q33, q67 (252-bar rolling)
    funding: pd.DataFrame                         # ts, fundingRate (8h cadence, kullanim: as-of)
    fng: pd.DataFrame                             # ts, value

    def _asof(self, df: pd.DataFrame, target_ts: pd.Timestamp, col: str) -> float:
        """as-of lookup — target_ts'den onceki en yakin satirin col degeri."""
        if df is None or df.empty:
            return float("nan")
        # df.ts <= target_ts → pratikte target_ts gunu disinda kalan en son satir
        mask = df["ts"] <= target_ts
        if not mask.any():
            return float("nan")
        return float(df.loc[mask, col].iloc[-1])

    def bucket_key(
        self,
        entry_ts: pd.Timestamp,
        symbol: str,
        strategy_id: str,
    ) -> tuple[str, str, str, str, str, str]:
        """6-dim bucket key — TUM komponentler causal (entry_ts - 1 day).

        Returns: (strategy_id, symbol, regime_bucket, atr_pct_bucket, funding_sign, fng_bucket)
        """
        if entry_ts.tzinfo is None:
            entry_ts = entry_ts.tz_localize("UTC")
        # Yesterday's close (causal cutoff)
        yesterday = entry_ts.normalize() - pd.Timedelta(days=1)

        # BTC regime
        close = self._asof(self.btc_daily, yesterday, "close")
        ema200 = self._asof(self.btc_daily, yesterday, "ema200")
        dd_90d = self._asof(self.btc_daily, yesterday, "dd_90d")
        regime = _regime_bucket(close, ema200, dd_90d)

        # ATR% bucket
        sym_atr = self.symbol_atr_pct.get(symbol)
        sym_q = self.symbol_atr_quantiles.get(symbol)
        atr_pct = self._asof(sym_atr, yesterday, "atr_pct") if sym_atr is not None else float("nan")
        q33 = self._asof(sym_q, yesterday, "q33") if sym_q is not None else float("nan")
        q67 = self._asof(sym_q, yesterday, "q67") if sym_q is not None else float("nan")
        atr_b = _atr_pct_bucket(atr_pct, q33, q67)

        # Funding sign (00:00 UTC cut on yesterday)
        funding_cutoff = yesterday + pd.Timedelta(hours=0)
        f_rate = self._asof(self.funding, funding_cutoff, "fundingRate")
        f_sign = _funding_sign(f_rate)

        # F&G bucket
        fng_val = self._asof(self.fng, yesterday, "value")
        fng_b = _fng_bucket(fng_val)

        return (strategy_id, symbol, regime, atr_b, f_sign, fng_b)


# ---------------------------------------------------------------------------
# Daily feature precomputation (BTC EMA200 + 90d DD; symbol ATR% + 252-quantile)
# ---------------------------------------------------------------------------
def precompute_btc_features(btc_df: pd.DataFrame) -> pd.DataFrame:
    """BTC daily OHLCV'den ema200, dd_90d derived feature'lari hesapla.

    Input: ts (tz-aware UTC), open, high, low, close
    Output: ts, close, ema200, dd_90d (tz-aware)
    """
    df = btc_df.sort_values("ts").reset_index(drop=True).copy()
    df["ema200"] = df["close"].ewm(span=200, adjust=False).mean()
    rolling_max = df["close"].rolling(90, min_periods=1).max()
    df["dd_90d"] = (df["close"] / rolling_max) - 1.0  # negative dd
    return df[["ts", "close", "ema200", "dd_90d"]]


def precompute_symbol_atr(symbol_df: pd.DataFrame) -> pd.DataFrame:
    """Symbol daily OHLCV'den ATR%(14) hesapla.

    Output: ts, atr_pct (close-normalized, percentage)
    """
    df = symbol_df.sort_values("ts").reset_index(drop=True).copy()
    h_l = df["high"] - df["low"]
    h_c = (df["high"] - df["close"].shift()).abs()
    l_c = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([h_l, h_c, l_c], axis=1).max(axis=1)
    atr14 = tr.ewm(alpha=1 / 14, adjust=False).mean()
    df["atr_pct"] = (atr14 / df["close"]) * 100.0  # percent
    return df[["ts", "atr_pct"]]


def precompute_symbol_atr_quantiles(symbol_atr_df: pd.DataFrame, window: int = 252) -> pd.DataFrame:
    """252-bar rolling 33rd/67th percentile of ATR%.

    Causal: rolling window includes only past data (excluding current bar may
    be set via .shift(1); we keep current bar inclusive — bucket lookup is
    as-of yesterday so this is t-1 anyway).
    """
    df = symbol_atr_df.sort_values("ts").reset_index(drop=True).copy()
    df["q33"] = df["atr_pct"].rolling(window, min_periods=30).quantile(ATR_PCT_QUANTILES[0])
    df["q67"] = df["atr_pct"].rolling(window, min_periods=30).quantile(ATR_PCT_QUANTILES[1])
    return df[["ts", "q33", "q67"]]


# ---------------------------------------------------------------------------
# EER core
# ---------------------------------------------------------------------------
@dataclass
class EERConfig:
    """Pre-registered EER konfigurasyonu — sweep YASAK (HARK koruma)."""
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    sample_min: int = DEFAULT_SAMPLE_MIN
    feature_keys: tuple[str, ...] = DEFAULT_FEATURE_KEYS
    fallback_eer: float = DEFAULT_FALLBACK_EER
    min_buckets_for_rank: int = DEFAULT_MIN_BUCKETS_FOR_RANK
    regime_dd_bull: float = REGIME_DD_BULL
    regime_dd_bear: float = REGIME_DD_BEAR
    atr_quantiles: tuple[float, float] = ATR_PCT_QUANTILES
    funding_thresholds: tuple[float, float] = FUNDING_THRESHOLDS
    fng_thresholds: tuple[int, int, int, int] = FNG_THRESHOLDS

    def config_hash(self) -> str:
        d = {
            "lookback_days": self.lookback_days,
            "sample_min": self.sample_min,
            "feature_keys": list(self.feature_keys),
            "fallback_eer": self.fallback_eer,
            "regime_dd_bull": self.regime_dd_bull,
            "regime_dd_bear": self.regime_dd_bear,
            "atr_quantiles": list(self.atr_quantiles),
            "funding_thresholds": list(self.funding_thresholds),
            "fng_thresholds": list(self.fng_thresholds),
        }
        s = json.dumps(d, sort_keys=True)
        return hashlib.sha256(s.encode()).hexdigest()[:16]


@dataclass
class EERStats:
    """EER hesaplama sirasinda derlenen tani istatistikleri."""
    n_total: int = 0
    n_with_bucket: int = 0       # bucket key uretilen trade'ler
    n_fallback: int = 0          # n<30 oldugu icin 0.50 verilenler
    n_full_eer: int = 0          # gercek percentile alanlar
    bucket_coverage: float = 0.0  # n_full_eer / n_total
    fallback_rate: float = 0.0    # n_fallback / n_total
    bucket_counts: dict[tuple, int] = field(default_factory=dict)
    eer_distribution: list[float] = field(default_factory=list)

    def summary(self) -> dict:
        return {
            "n_total": self.n_total,
            "n_full_eer": self.n_full_eer,
            "n_fallback": self.n_fallback,
            "bucket_coverage": round(self.bucket_coverage, 4),
            "fallback_rate": round(self.fallback_rate, 4),
            "n_unique_buckets": len(self.bucket_counts),
            "top_bucket_share": (
                max(self.bucket_counts.values()) / max(1, self.n_total)
                if self.bucket_counts else 0.0
            ),
        }


def compute_eer_for_trades(
    trades: list[dict],
    context: FeatureContext,
    config: EERConfig | None = None,
) -> tuple[list[dict], EERStats]:
    """Tum trade'lere EER ekle. Causal — sadece exit_ts < entry_ts trade'leri kullan.

    Trades formati:
      [{entry_ts, exit_ts, symbol, side, strategy, R, conf, ...}, ...]

    Cikti: ayni listenin kopyasi + her trade'e "eer", "bucket_key", "bucket_n"
    "bucket_avg_R" alanlari eklenir.

    Algoritma:
      1. Tum trade'lere bucket_key ata (causal).
      2. Trade'leri entry_ts'e gore sirala.
      3. Her trade icin:
         a. Lookback window = [entry_ts - lookback_days, entry_ts)
         b. Window icindeki KAPANMIS (exit_ts < entry_ts) trade'leri al.
         c. Bucket gruplama: ayni bucket'taki trade'lerin avg_R'sini hesapla.
         d. Trade'in bucket'inda n>=sample_min ise:
              - Tum window-bucket avg_R'lari arasinda bu bucket'in percentile rank'i = EER
            Aksi durumda: EER = fallback_eer (0.50)
    """
    cfg = config or EERConfig()
    stats = EERStats()
    stats.n_total = len(trades)
    if not trades:
        return [], stats

    # Defensive copy + bucket key annotation
    enriched = []
    for t in trades:
        t2 = dict(t)
        entry_ts = pd.Timestamp(t2["entry_ts"])
        if entry_ts.tzinfo is None:
            entry_ts = entry_ts.tz_localize("UTC")
        exit_ts = pd.Timestamp(t2["exit_ts"])
        if exit_ts.tzinfo is None:
            exit_ts = exit_ts.tz_localize("UTC")
        t2["entry_ts"] = entry_ts
        t2["exit_ts"] = exit_ts
        try:
            bk = context.bucket_key(entry_ts, t2["symbol"], t2["strategy"])
            t2["bucket_key"] = bk
            stats.n_with_bucket += 1
            stats.bucket_counts[bk] = stats.bucket_counts.get(bk, 0) + 1
        except Exception:
            t2["bucket_key"] = None
        enriched.append(t2)

    enriched.sort(key=lambda x: x["entry_ts"])

    # Forward pass: each trade looks at CLOSED prior trades within lookback
    for i, trade in enumerate(enriched):
        bk = trade.get("bucket_key")
        if bk is None:
            trade["eer"] = cfg.fallback_eer
            trade["bucket_n"] = 0
            trade["bucket_avg_R"] = float("nan")
            stats.n_fallback += 1
            stats.eer_distribution.append(cfg.fallback_eer)
            continue

        cutoff_start = trade["entry_ts"] - pd.Timedelta(days=cfg.lookback_days)
        # Collect prior closed trades in window — group by bucket
        bucket_rs: dict[tuple, list[float]] = defaultdict(list)
        # Walk backwards from current position; stop early if entry too old.
        # NOTE: we use exit_ts < trade.entry_ts as causal constraint.
        for j in range(i - 1, -1, -1):
            cand = enriched[j]
            if cand["entry_ts"] < cutoff_start:
                break
            cand_bk = cand.get("bucket_key")
            if cand_bk is None:
                continue
            # MUST be closed before current trade's entry
            if cand["exit_ts"] >= trade["entry_ts"]:
                continue
            try:
                bucket_rs[cand_bk].append(float(cand["R"]))
            except (KeyError, TypeError, ValueError):
                continue

        # Bucket avg_R'lari + current trade'in bucket'ina ait stats
        bucket_avgs = []
        my_bucket_rs = bucket_rs.get(bk, [])
        my_n = len(my_bucket_rs)
        my_avg_R = float(np.mean(my_bucket_rs)) if my_n > 0 else float("nan")

        for k, rs in bucket_rs.items():
            if len(rs) >= cfg.sample_min:
                bucket_avgs.append(float(np.mean(rs)))

        if my_n < cfg.sample_min or len(bucket_avgs) < cfg.min_buckets_for_rank:
            trade["eer"] = cfg.fallback_eer
            trade["bucket_n"] = my_n
            trade["bucket_avg_R"] = my_avg_R
            stats.n_fallback += 1
            stats.eer_distribution.append(cfg.fallback_eer)
            continue

        # Percentile rank: fraction of bucket_avgs <= my_avg_R
        my_avg = float(np.mean(my_bucket_rs))
        rank = sum(1 for x in bucket_avgs if x <= my_avg) / len(bucket_avgs)
        trade["eer"] = float(rank)
        trade["bucket_n"] = my_n
        trade["bucket_avg_R"] = my_avg
        stats.n_full_eer += 1
        stats.eer_distribution.append(float(rank))

    stats.bucket_coverage = stats.n_full_eer / max(1, stats.n_total)
    stats.fallback_rate = stats.n_fallback / max(1, stats.n_total)
    return enriched, stats


# ---------------------------------------------------------------------------
# Hash helpers (reproducibility)
# ---------------------------------------------------------------------------
def trades_data_hash(trades: list[dict]) -> str:
    """Trade listesinin deterministic hash'i — entry_ts/symbol/side/R only.

    Bu hash data lineage icin; tam trade tuple'i degil cunku conf vs eer
    test'lerinde aynı trade pool farkli skor alir.
    """
    items = []
    for t in trades:
        items.append((
            str(t.get("entry_ts")),
            t.get("symbol"),
            t.get("side"),
            t.get("strategy"),
            round(float(t.get("R", 0.0)), 6),
        ))
    s = json.dumps(items, sort_keys=True, default=str)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


def context_data_hash(context: FeatureContext) -> str:
    """FeatureContext'in deterministic hash'i — shape + ts range only."""
    parts = []
    for name, df in [
        ("btc_daily", context.btc_daily),
        ("funding", context.funding),
        ("fng", context.fng),
    ]:
        if df is None or df.empty:
            parts.append((name, 0, "", ""))
        else:
            parts.append((name, len(df), str(df["ts"].iloc[0]), str(df["ts"].iloc[-1])))
    for sym, df in sorted(context.symbol_atr_pct.items()):
        parts.append((f"atr_{sym}", len(df), str(df["ts"].iloc[0]), str(df["ts"].iloc[-1])))
    s = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(s.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Convenience: single-trade compute_eer (test API)
# ---------------------------------------------------------------------------
def compute_eer(
    trade: dict,
    history_trades: list[dict],
    context: FeatureContext,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    feature_keys: tuple[str, ...] = DEFAULT_FEATURE_KEYS,
    sample_min: int = DEFAULT_SAMPLE_MIN,
) -> float:
    """Tek bir trade icin EER — test API'si.

    history_trades: trade.entry_ts'inden ONCE kapanmis trade'ler (look-ahead yasak).
    Assertion: tum history_trades'ler trade.exit_ts <= trade.entry_ts olmali.
    """
    entry_ts = pd.Timestamp(trade["entry_ts"])
    if entry_ts.tzinfo is None:
        entry_ts = entry_ts.tz_localize("UTC")

    # Defensive: history yalniz kapanmis
    cutoff_start = entry_ts - pd.Timedelta(days=lookback_days)
    closed = []
    for h in history_trades:
        h_exit = pd.Timestamp(h["exit_ts"])
        if h_exit.tzinfo is None:
            h_exit = h_exit.tz_localize("UTC")
        if h_exit >= entry_ts:
            # Look-ahead — DROP (this is the audit guarantee)
            continue
        h_entry = pd.Timestamp(h["entry_ts"])
        if h_entry.tzinfo is None:
            h_entry = h_entry.tz_localize("UTC")
        if h_entry < cutoff_start:
            continue
        closed.append(h)

    cfg = EERConfig(
        lookback_days=lookback_days,
        sample_min=sample_min,
        feature_keys=feature_keys,
    )
    pool = closed + [trade]
    out, _ = compute_eer_for_trades(pool, context, cfg)
    last = out[-1]
    # Match by entry_ts + symbol + strategy
    for t in out:
        if (
            pd.Timestamp(t["entry_ts"]) == entry_ts
            and t["symbol"] == trade["symbol"]
            and t["strategy"] == trade["strategy"]
        ):
            last = t
            break
    return float(last["eer"])


# ---------------------------------------------------------------------------
# Tier mapping (Lab'in W3 isi ama burada referans default tutuyoruz)
# ---------------------------------------------------------------------------
def eer_to_tier(
    eer: float,
    cuts: tuple[float, float, float] = (0.20, 0.60, 0.90),
) -> int:
    """EER'i 4-tier'a map et: T1 (lowest) ... T4 (highest)."""
    if eer < cuts[0]:
        return 1
    if eer < cuts[1]:
        return 2
    if eer < cuts[2]:
        return 3
    return 4


# ===========================================================================
# EER v2 — Hierarchical Fallback + Bayesian Shrinkage + Edge-Gated Sizing
# ===========================================================================
# v1 (RED): 6-dim bucket -> %0 coverage. v2 fix:
#   - 4-dim bucket (strategy, symbol, regime, atr) — funding+fng dropped
#   - 365-day lookback (v1: 180)
#   - Hierarchical fallback (L1 4-dim -> L2 3-dim drop symbol -> L3 2-dim drop atr -> L4 strategy avg)
#   - Bayesian shrinkage (k=20) to global avg
#   - Edge-gate: tier sizing applied only if in-sample top/bot edge_ratio >= 3.5
# Pre-registered: memory/researcher/hypotheses/2026-05-14-eer-score-v2.md
# ===========================================================================

DEFAULT_LOOKBACK_DAYS_V2: int = 365
DEFAULT_SAMPLE_MIN_V2: int = 30
DEFAULT_SHRINKAGE_K: int = 20
DEFAULT_EDGE_GATE: float = 3.5
DEFAULT_FEATURE_KEYS_V2_L1: tuple[str, ...] = (
    "strategy_id", "symbol", "regime_bucket", "atr_pct_bucket",
)


@dataclass
class EERConfigV2:
    """Pre-registered EER v2 konfigurasyonu — sweep YASAK."""
    lookback_days: int = DEFAULT_LOOKBACK_DAYS_V2
    sample_min: int = DEFAULT_SAMPLE_MIN_V2
    sample_min_l4: int = 10  # strategy avg (lvl 4) gevsek esik
    shrinkage_k: int = DEFAULT_SHRINKAGE_K
    edge_gate: float = DEFAULT_EDGE_GATE
    # Regime threshold'lari (v1 ile ayni)
    regime_dd_bull: float = REGIME_DD_BULL
    regime_dd_bear: float = REGIME_DD_BEAR
    atr_quantiles: tuple[float, float] = ATR_PCT_QUANTILES
    min_buckets_for_rank: int = 5

    def config_hash(self) -> str:
        d = {
            "v": 2,
            "lookback_days": self.lookback_days,
            "sample_min": self.sample_min,
            "sample_min_l4": self.sample_min_l4,
            "shrinkage_k": self.shrinkage_k,
            "edge_gate": self.edge_gate,
            "regime_dd_bull": self.regime_dd_bull,
            "regime_dd_bear": self.regime_dd_bear,
            "atr_quantiles": list(self.atr_quantiles),
        }
        s = json.dumps(d, sort_keys=True)
        return hashlib.sha256(s.encode()).hexdigest()[:16]


@dataclass
class EERStatsV2:
    """v2 EER hesaplama istatistikleri — hierarchical level dagilimini takip eder."""
    n_total: int = 0
    n_l1: int = 0           # full 4-dim bucket
    n_l2: int = 0           # symbol dropped
    n_l3: int = 0           # atr dropped (strategy + regime)
    n_l4: int = 0           # strategy avg only
    n_fallback: int = 0     # ne L4 bile yetmedi → 0.50
    bucket_counts_l1: dict[tuple, int] = field(default_factory=dict)
    eer_distribution: list[float] = field(default_factory=list)

    @property
    def bucket_coverage(self) -> float:
        return (self.n_l1 + self.n_l2 + self.n_l3) / max(1, self.n_total)

    @property
    def fallback_rate(self) -> float:
        return self.n_fallback / max(1, self.n_total)

    def summary(self) -> dict:
        return {
            "n_total": self.n_total,
            "n_l1": self.n_l1,
            "n_l2": self.n_l2,
            "n_l3": self.n_l3,
            "n_l4": self.n_l4,
            "n_fallback": self.n_fallback,
            "bucket_coverage_l1_l3": round(self.bucket_coverage, 4),
            "fallback_rate": round(self.fallback_rate, 4),
            "n_unique_buckets_l1": len(self.bucket_counts_l1),
            "l1_share": round(self.n_l1 / max(1, self.n_total), 4),
            "l4_share": round(self.n_l4 / max(1, self.n_total), 4),
        }


def _bucket_key_v2_4dim(entry_ts, symbol, strategy_id, context: FeatureContext) -> tuple[str, str, str, str]:
    """4-dim bucket key — funding+fng cikartildi (v2 fix)."""
    if entry_ts.tzinfo is None:
        entry_ts = entry_ts.tz_localize("UTC")
    yesterday = entry_ts.normalize() - pd.Timedelta(days=1)

    close = context._asof(context.btc_daily, yesterday, "close")
    ema200 = context._asof(context.btc_daily, yesterday, "ema200")
    dd_90d = context._asof(context.btc_daily, yesterday, "dd_90d")
    regime = _regime_bucket(close, ema200, dd_90d)

    sym_atr = context.symbol_atr_pct.get(symbol)
    sym_q = context.symbol_atr_quantiles.get(symbol)
    atr_pct = context._asof(sym_atr, yesterday, "atr_pct") if sym_atr is not None else float("nan")
    q33 = context._asof(sym_q, yesterday, "q33") if sym_q is not None else float("nan")
    q67 = context._asof(sym_q, yesterday, "q67") if sym_q is not None else float("nan")
    atr_b = _atr_pct_bucket(atr_pct, q33, q67)

    return (strategy_id, symbol, regime, atr_b)


def _shrunken_avg(bucket_R: list[float], global_avg: float, k: int = 20) -> float:
    """Bayesian shrinkage — bucket avg_R global'a cek (sample-size weighted)."""
    n = len(bucket_R)
    if n == 0:
        return global_avg
    bucket_avg = float(np.mean(bucket_R))
    return (n * bucket_avg + k * global_avg) / (n + k)


def compute_eer_v2_for_trades(
    trades: list[dict],
    context: FeatureContext,
    config: EERConfigV2 | None = None,
) -> tuple[list[dict], EERStatsV2]:
    """v2: hierarchical fallback + Bayesian shrinkage. Causal — exit_ts < entry_ts."""
    cfg = config or EERConfigV2()
    stats = EERStatsV2()
    stats.n_total = len(trades)
    if not trades:
        return [], stats

    # Defensive copy + 4-dim bucket key
    enriched = []
    for t in trades:
        t2 = dict(t)
        entry_ts = pd.Timestamp(t2["entry_ts"])
        if entry_ts.tzinfo is None:
            entry_ts = entry_ts.tz_localize("UTC")
        exit_ts = pd.Timestamp(t2["exit_ts"])
        if exit_ts.tzinfo is None:
            exit_ts = exit_ts.tz_localize("UTC")
        t2["entry_ts"] = entry_ts
        t2["exit_ts"] = exit_ts
        try:
            bk = _bucket_key_v2_4dim(entry_ts, t2["symbol"], t2["strategy"], context)
            t2["bucket_key_v2"] = bk
            stats.bucket_counts_l1[bk] = stats.bucket_counts_l1.get(bk, 0) + 1
        except Exception:
            t2["bucket_key_v2"] = None
        enriched.append(t2)

    enriched.sort(key=lambda x: x["entry_ts"])

    # Forward pass
    for i, trade in enumerate(enriched):
        bk1 = trade.get("bucket_key_v2")
        if bk1 is None:
            trade["eer_v2"] = 0.50
            trade["eer_v2_level"] = 0
            trade["eer_v2_bucket_n"] = 0
            stats.n_fallback += 1
            stats.eer_distribution.append(0.50)
            continue

        cutoff_start = trade["entry_ts"] - pd.Timedelta(days=cfg.lookback_days)

        # Collect prior closed trades in window
        l1_pool = defaultdict(list)  # 4-dim
        l2_pool = defaultdict(list)  # 3-dim
        l3_pool = defaultdict(list)  # 2-dim (strategy, regime)
        l4_pool = defaultdict(list)  # 1-dim (strategy)
        all_pool = []                # global

        for j in range(i - 1, -1, -1):
            cand = enriched[j]
            if cand["entry_ts"] < cutoff_start:
                break
            cand_bk = cand.get("bucket_key_v2")
            if cand_bk is None:
                continue
            if cand["exit_ts"] >= trade["entry_ts"]:
                continue
            try:
                R = float(cand["R"])
            except (KeyError, TypeError, ValueError):
                continue
            s_id, s_sym, regime, atr_b = cand_bk
            l1_pool[(s_id, s_sym, regime, atr_b)].append(R)
            l2_pool[(s_id, regime, atr_b)].append(R)
            l3_pool[(s_id, regime)].append(R)
            l4_pool[s_id].append(R)
            all_pool.append(R)

        if len(all_pool) < 30:
            # global avg unreliable — fallback
            trade["eer_v2"] = 0.50
            trade["eer_v2_level"] = 0
            trade["eer_v2_bucket_n"] = 0
            stats.n_fallback += 1
            stats.eer_distribution.append(0.50)
            continue

        global_avg = float(np.mean(all_pool))

        # Hierarchical level resolution
        my_l1 = (bk1[0], bk1[1], bk1[2], bk1[3])
        my_l2 = (bk1[0], bk1[2], bk1[3])
        my_l3 = (bk1[0], bk1[2])
        my_l4 = bk1[0]

        chosen_level = 0
        chosen_pool = None
        my_bucket_rs = None

        l1_rs = l1_pool.get(my_l1, [])
        if len(l1_rs) >= cfg.sample_min:
            chosen_level = 1
            chosen_pool = l1_pool
            my_bucket_rs = l1_rs
        else:
            l2_rs = l2_pool.get(my_l2, [])
            if len(l2_rs) >= cfg.sample_min:
                chosen_level = 2
                chosen_pool = l2_pool
                my_bucket_rs = l2_rs
            else:
                l3_rs = l3_pool.get(my_l3, [])
                if len(l3_rs) >= cfg.sample_min:
                    chosen_level = 3
                    chosen_pool = l3_pool
                    my_bucket_rs = l3_rs
                else:
                    l4_rs = l4_pool.get(my_l4, [])
                    if len(l4_rs) >= cfg.sample_min_l4:
                        chosen_level = 4
                        chosen_pool = l4_pool
                        my_bucket_rs = l4_rs

        if chosen_level == 0 or my_bucket_rs is None:
            trade["eer_v2"] = 0.50
            trade["eer_v2_level"] = 0
            trade["eer_v2_bucket_n"] = 0
            stats.n_fallback += 1
            stats.eer_distribution.append(0.50)
            continue

        # Shrinkage
        my_shrunken = _shrunken_avg(my_bucket_rs, global_avg, k=cfg.shrinkage_k)

        # Percentile rank within the same level's buckets
        # All other buckets at this level, shrunken
        same_level_buckets_shrunken = []
        threshold_n = cfg.sample_min if chosen_level <= 3 else cfg.sample_min_l4
        for k, rs in chosen_pool.items():
            if len(rs) >= threshold_n:
                same_level_buckets_shrunken.append(_shrunken_avg(rs, global_avg, k=cfg.shrinkage_k))

        if len(same_level_buckets_shrunken) < cfg.min_buckets_for_rank:
            trade["eer_v2"] = 0.50
            trade["eer_v2_level"] = chosen_level
            trade["eer_v2_bucket_n"] = len(my_bucket_rs)
            stats.n_fallback += 1
            stats.eer_distribution.append(0.50)
            continue

        rank = sum(1 for x in same_level_buckets_shrunken if x <= my_shrunken) / len(same_level_buckets_shrunken)
        trade["eer_v2"] = float(rank)
        trade["eer_v2_level"] = chosen_level
        trade["eer_v2_bucket_n"] = len(my_bucket_rs)
        trade["eer_v2_bucket_avg_R_shrunken"] = my_shrunken
        trade["eer_v2_bucket_avg_R_raw"] = float(np.mean(my_bucket_rs))

        if chosen_level == 1:
            stats.n_l1 += 1
        elif chosen_level == 2:
            stats.n_l2 += 1
        elif chosen_level == 3:
            stats.n_l3 += 1
        elif chosen_level == 4:
            stats.n_l4 += 1
        stats.eer_distribution.append(float(rank))

    return enriched, stats


def compute_in_sample_edge_ratio(
    trades: list[dict],
    score_field: str = "eer_v2",
    top_cut: float = 0.80,
    bot_cut: float = 0.20,
    min_n: int = 30,
) -> float:
    """In-sample edge ratio: top-tier avg_R / bot-tier avg_R.

    Bu sayi >=3.5 ise EER tier sizing kullanmaya deger; aksi takdirde flat T2.
    Analyst input (`reports/analytics/2026-05-13-dynamic-failure.md`): top/bot
    spread 1.39x (gercek). Tier sizing icin 3.5x+ gerek.
    """
    top_Rs = [t["R"] for t in trades if t.get(score_field, 0.5) >= top_cut]
    bot_Rs = [t["R"] for t in trades if t.get(score_field, 0.5) <= bot_cut]
    if len(top_Rs) < min_n or len(bot_Rs) < min_n:
        return 1.0
    top_avg = float(np.mean(top_Rs))
    bot_avg = float(np.mean(bot_Rs))
    if bot_avg <= 0:
        return 1.0 if top_avg <= 0 else 999.0
    return top_avg / bot_avg


__all__ = [
    "EERConfig",
    "EERConfigV2",
    "EERStats",
    "EERStatsV2",
    "FeatureContext",
    "compute_eer",
    "compute_eer_for_trades",
    "compute_eer_v2_for_trades",
    "compute_in_sample_edge_ratio",
    "context_data_hash",
    "eer_to_tier",
    "precompute_btc_features",
    "precompute_symbol_atr",
    "precompute_symbol_atr_quantiles",
    "trades_data_hash",
    "DEFAULT_LOOKBACK_DAYS",
    "DEFAULT_LOOKBACK_DAYS_V2",
    "DEFAULT_SAMPLE_MIN",
    "DEFAULT_SAMPLE_MIN_V2",
    "DEFAULT_FEATURE_KEYS",
    "DEFAULT_SHRINKAGE_K",
    "DEFAULT_EDGE_GATE",
]
