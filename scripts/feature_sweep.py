"""Feature Sweep Engine — systematic feature × vol-normalized return scan.

OTONOMI-1 (2026-07-07, Principal direktifi): "piyasayı anlasın, on binlerce
korelasyon denesin, uyumu yakalasın." Bu motor bunu İSTATİSTİKSEL DÜRÜSTLÜKLE
yapar — çıplak korelasyon avı değil:

  - Spearman IC (rank korelasyon; outlier-dirençli)
  - Benjamini-Yekutieli FDR düzeltmesi (bağımlı binlerce test)
  - Chronological onay: IS (ilk %70) işaret+büyüklük, OOS (son %30) işaret
    tutarlılığı + |IC_OOS| >= 0.5 × |IC_IS| şartı
  - Lookahead YOK: her feature t anında yalnız <= t verisi kullanır (shift
    disiplini); target = forward return / t-anında bilinen trailing volatility.
  - OI/dominance/sentiment/event verisi yoksa sayı uydurulmaz; coverage
    artefaktı aileyi ve eksik bağımlılığı açıkça işaretler.

Veri: market.duckdb (RO, tüketici) 15m -> seçilen 1h/4h/1d resample;
funding.duckdb + yalnız gerçek örtüşmesi yeterli auxiliary kaynaklar.
Çıktı:
  - reports/research/feature_sweep/YYYY-MM-DD_TF.md (insan-okur rapor)
  - memory/researcher/sweep_candidates_v2.jsonl  (append-only, bütünlük
    kontrollü DESCRIPTIVE_DISCOVERY kuyruğu; promotion_eligible daima false)

Cron: scheduler `feature_sweep` (deterministik CPU, LLM YOK).
Elle: .venv/bin/python scripts/feature_sweep.py [--tf 1h --tf 4h --tf 1d] [--quick]

Hard limits (repo disiplini): forward-fill YOK, clip/winsorize YOK,
sayı uydurma YOK — geçemeyen aday yazılmaz.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import duckdb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import stats  # noqa: E402

from price_action.lab.feature_candidates import (  # noqa: E402
    DEFAULT_CANDIDATE_PATH,
    SUPPORTED_TIMEFRAMES,
    algorithm_code_sha256,
    append_candidate_records,
    make_candidate_record,
    market_snapshot_metadata,
)
from price_action.lab.feature_coverage import build_feature_coverage  # noqa: E402

MARKET_DB = ROOT / "data" / "market.duckdb"
FUNDING_DB = ROOT / "data" / "funding.duckdb"
SENTIMENT_DB = ROOT / "data" / "sentiment.duckdb"
DOMINANCE_DB = ROOT / "data" / "dominance.duckdb"
STABLECOIN_DB = ROOT / "data" / "stablecoin.duckdb"
OUT_DIR = ROOT / "reports" / "research" / "feature_sweep"
CAND_PATH = DEFAULT_CANDIDATE_PATH

SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT",
    "BNB/USDT",
    "ADA/USDT",
    "AVAX/USDT",
    "LINK/USDT",
    "DOT/USDT",
    "DOGE/USDT",
    "XRP/USDT",
    "ZEC/USDT",
    "NEAR/USDT",
    "FIL/USDT",
    "XLM/USDT",
    "TRX/USDT",
    "ATOM/USDT",
    "AAVE/USDT",
    "ALGO/USDT",
]  # trading evreni (18; UNI data-only oldugu icin sweep disi — KARAR P1-6)

# Kabul eşikleri — gevşetilemez (gevşetme = KARAR-GUNLUGU)
FDR_ALPHA = 0.05
MIN_ABS_IC = 0.02
OOS_RATIO = 0.5
IS_FRAC = 0.7
MIN_OBS = 500  # feature-target çifti başına asgari gözlem

_TF_SECONDS = {"1h": 3600, "4h": 4 * 3600, "1d": 24 * 3600}
_SOURCE_15M_BARS = {"1h": 4, "4h": 16, "1d": 96}
_RESAMPLE_RULE = {"1h": "1h", "4h": "4h", "1d": "1D"}
_TARGET_HORIZONS = {
    "1h": ((4, "h"), (24, "h"), (72, "h")),
    "4h": ((12, "h"), (24, "h"), (72, "h")),
    "1d": ((1, "d"), (7, "d"), (30, "d")),
}
TARGET_NORMALIZATION = "TRAILING_REALIZED_VOL_AT_DECISION_BAR"
OOS_SCHEME = "CHRONOLOGICAL_70_30_CONFIRMATION_NOT_PROMOTION_HOLDOUT"


def _feature_family(name: str) -> str:
    """Map feature names to stable coverage/provenance families."""

    mappings = (
        (("ret_", "logret_"), "momentum"),
        (("range_pct", "true_range_pct", "body_", "upper_wick", "lower_wick", "close_location", "open_gap", "direction"), "candlestick"),
        (("realized_vol_", "atr_pct_"), "volatility"),
        (("volume_",), "volume"),
        (("range_pos_", "close_vs_sma_", "efficiency_", "positive_ratio_", "distance_prior_"), "trend_range"),
        (("return_skew_", "return_kurt_", "volume_return_corr_"), "distribution"),
        (("utc_hour_", "weekday_"), "calendar_event_time"),
        (("funding",), "funding"),
        (("btc_", "relative_to_btc_"), "btc_context"),
        (("xs_",), "cross_sectional"),
        (("sentiment_",), "sentiment"),
    )
    for prefixes, family in mappings:
        if name.startswith(prefixes):
            return family
    return "technical_other"


def _event_independence_bars(feature: str, *, timeframe: str) -> int:
    """Do not count repeated event-carry rows as independent observations."""

    seconds = _TF_SECONDS[timeframe]
    if feature.startswith("sentiment_"):
        return max(math.ceil(86400 / seconds), 1)
    if feature.startswith("funding"):
        return max(math.ceil(8 * 3600 / seconds), 1)
    return 1


def _load_ohlcv(
    con: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: str,
) -> pd.DataFrame:
    """15m -> 1h/4h/1d complete bars (UTC, left-closed/left-labelled)."""

    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    df = con.execute(
        """
        SELECT ts, open, high, low, close, volume FROM ohlcv
        WHERE venue='binance' AND symbol=? AND timeframe='15m'
        ORDER BY ts
        """,
        [symbol],
    ).fetchdf()
    if df.empty:
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    df = df.set_index("ts")
    o = df.resample(_RESAMPLE_RULE[timeframe], label="left", closed="left").agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        source_bars=("close", "count"),
    )
    # A partially formed higher-timeframe bar must never enter discovery.  Gaps
    # are also rejected rather than silently treated as complete bars.
    o = o.loc[o["source_bars"] == _SOURCE_15M_BARS[timeframe]].drop(columns="source_bars")
    return o.dropna(subset=["open", "high", "low", "close", "volume"])


def _load_ohlcv_1h(con: duckdb.DuckDBPyConnection, symbol: str) -> pd.DataFrame:
    """Backward-compatible wrapper for focused legacy tests."""

    return _load_ohlcv(con, symbol, "1h")


def _load_funding(symbol: str) -> pd.Series | None:
    if not FUNDING_DB.exists():
        return None
    # funding.duckdb sembolleri ÇIPLAK saklar ('BTC') — üç varyantı da dene
    sym = symbol.replace("/", "")
    base = symbol.split("/")[0]
    try:
        con = duckdb.connect(str(FUNDING_DB), read_only=True)
        df = con.execute(
            "SELECT ts, funding_rate FROM funding_rates WHERE symbol IN (?, ?, ?) ORDER BY ts",
            [symbol, sym, base],
        ).fetchdf()
        con.close()
    except Exception:
        return None
    if df.empty:
        return None
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.set_index("ts")["funding_rate"]


def _load_sentiment() -> pd.Series | None:
    """Load observed daily Fear & Greed events; never synthesize missing days."""

    if not SENTIMENT_DB.exists():
        return None
    try:
        with duckdb.connect(str(SENTIMENT_DB), read_only=True) as con:
            df = con.execute("SELECT ts, value FROM fng_daily ORDER BY ts").fetchdf()
    except Exception:
        return None
    if df.empty:
        return None
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df.drop_duplicates("ts", keep="last").set_index("ts")["value"].astype(float)


def _event_carry(
    series: pd.Series,
    index: pd.DatetimeIndex,
    *,
    tolerance: pd.Timedelta,
) -> pd.Series:
    """As-of carry observed events only while their declared TTL is valid."""

    ordered = series.sort_index()
    ordered = ordered[~ordered.index.duplicated(keep="last")]
    return ordered.reindex(index, method="ffill", tolerance=tolerance)


def build_cross_sectional_features(
    frames: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """Build causal same-close universe ranks/breadth for each loaded symbol."""

    if len(frames) < 2:
        return {symbol: pd.DataFrame(index=frame.index) for symbol, frame in frames.items()}
    closes = pd.concat(
        {symbol: frame["close"].astype(float) for symbol, frame in frames.items()},
        axis=1,
        sort=True,
    ).sort_index()
    ret1 = closes.pct_change(fill_method=None)
    ret4 = closes.pct_change(4, fill_method=None)
    rv24 = ret1.rolling(24, min_periods=24).std()
    rank1 = ret1.rank(axis=1, pct=True)
    rank4 = ret4.rank(axis=1, pct=True)
    rank_rv = rv24.rank(axis=1, pct=True)
    median1 = ret1.median(axis=1, skipna=True)
    median4 = ret4.median(axis=1, skipna=True)
    breadth = (ret1 > 0).where(ret1.notna()).mean(axis=1)
    dispersion = ret1.std(axis=1)
    result: dict[str, pd.DataFrame] = {}
    for symbol, frame in frames.items():
        index = frame.index
        result[symbol] = pd.DataFrame(
            {
                "xs_ret_1bar_rank": rank1[symbol],
                "xs_ret_4bar_rank": rank4[symbol],
                "xs_rv_24bar_rank": rank_rv[symbol],
                "xs_relative_1bar": ret1[symbol] - median1,
                "xs_relative_4bar": ret4[symbol] - median4,
                "xs_breadth_positive_1bar": breadth,
                "xs_median_ret_1bar": median1,
                "xs_dispersion_1bar": dispersion,
            },
            index=closes.index,
        ).reindex(index)
    return result


def build_features(
    o: pd.DataFrame,
    funding: pd.Series | None,
    btc_close: pd.Series | None,
    *,
    timeframe: str = "1h",
    sentiment: pd.Series | None = None,
    cross_sectional: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Build 50+ deterministic, prefix-invariant features known at bar close.

    Window names are expressed in bars because one bar means a different
    duration for 1h, 4h and 1d research.  No global normalization, centered
    rolling window, backward fill, or negative shift is permitted here.
    """

    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    required = {"open", "high", "low", "close", "volume"}
    missing = sorted(required.difference(o.columns))
    if missing:
        raise ValueError(f"OHLCV frame missing columns: {missing}")
    if not o.index.is_monotonic_increasing or o.index.has_duplicates:
        raise ValueError("OHLCV index must be monotonic and unique")

    c = o["close"].astype(float)
    op = o["open"].astype(float)
    hi = o["high"].astype(float)
    lo = o["low"].astype(float)
    volume = o["volume"].astype(float)
    r1 = c.pct_change(fill_method=None)
    log_c = np.log(c.where(c > 0))
    candle_range = (hi - lo).replace(0.0, np.nan)
    previous_close = c.shift(1)
    tr = pd.concat(
        [hi - lo, (hi - previous_close).abs(), (lo - previous_close).abs()],
        axis=1,
    ).max(axis=1)
    values: dict[str, pd.Series] = {}

    # Return and candle anatomy families.
    for bars in (1, 2, 3, 4, 6, 8, 12, 24, 48, 72):
        values[f"ret_{bars}bar"] = c.pct_change(bars, fill_method=None)
    for bars in (1, 4, 12, 24, 72):
        values[f"logret_{bars}bar"] = log_c.diff(bars)
    values["range_pct"] = candle_range / c
    values["true_range_pct"] = tr / c
    values["body_pct"] = (c - op) / op
    values["body_abs_to_range"] = (c - op).abs() / candle_range
    values["upper_wick_to_range"] = (hi - pd.concat([op, c], axis=1).max(axis=1)) / candle_range
    values["lower_wick_to_range"] = (pd.concat([op, c], axis=1).min(axis=1) - lo) / candle_range
    values["close_location"] = (c - lo) / candle_range
    values["open_gap_pct"] = op / previous_close - 1.0
    values["direction"] = np.sign(c - op)

    # Volatility, ATR and volume families.  All moments are trailing only.
    for window in (4, 8, 12, 24, 48, 72, 168, 240):
        values[f"realized_vol_{window}bar"] = r1.rolling(window, min_periods=window).std()
    for window in (4, 8, 14, 24, 48, 72, 168):
        values[f"atr_pct_{window}bar"] = tr.rolling(window, min_periods=window).mean() / c
    for window in (8, 24, 48, 72, 168, 240):
        vol_mean = volume.rolling(window, min_periods=window).mean()
        vol_std = volume.rolling(window, min_periods=window).std()
        values[f"volume_z_{window}bar"] = (volume - vol_mean) / (vol_std + 1e-12)
    for window in (4, 8, 24, 72, 168):
        values[f"volume_ratio_{window}bar"] = volume / (
            volume.rolling(window, min_periods=window).mean() + 1e-12
        )

    # Trend/location and distribution-shape families.
    for window in (8, 24, 48, 72, 168, 240):
        rolling_high = hi.rolling(window, min_periods=window).max()
        rolling_low = lo.rolling(window, min_periods=window).min()
        values[f"range_pos_{window}bar"] = (c - rolling_low) / (
            rolling_high - rolling_low + 1e-12
        )
    for window in (4, 8, 12, 24, 48, 72, 168, 240):
        values[f"close_vs_sma_{window}bar"] = c / (
            c.rolling(window, min_periods=window).mean() + 1e-12
        ) - 1.0
    for window in (8, 24, 72, 168):
        path = c.diff().abs().rolling(window, min_periods=window).sum()
        values[f"efficiency_{window}bar"] = c.diff(window).abs() / (path + 1e-12)
        values[f"positive_ratio_{window}bar"] = (r1 > 0).astype(float).rolling(
            window, min_periods=window
        ).mean()
    for window in (12, 24, 48, 72, 168):
        values[f"return_skew_{window}bar"] = r1.rolling(window, min_periods=window).skew()
        values[f"return_kurt_{window}bar"] = r1.rolling(window, min_periods=window).kurt()
    for window in (24, 72, 168):
        prior_high = hi.rolling(window, min_periods=window).max().shift(1)
        prior_low = lo.rolling(window, min_periods=window).min().shift(1)
        values[f"distance_prior_high_{window}bar"] = c / prior_high - 1.0
        values[f"distance_prior_low_{window}bar"] = c / prior_low - 1.0
        values[f"volume_return_corr_{window}bar"] = r1.rolling(
            window, min_periods=window
        ).corr(volume.pct_change(fill_method=None))

    # Calendar state is known at close and remains prefix-invariant.
    utc_index = pd.DatetimeIndex(o.index)
    if utc_index.tz is None:
        raise ValueError("OHLCV timestamps must be timezone-aware")
    hour_angle = 2.0 * math.pi * utc_index.tz_convert(UTC).hour / 24.0
    weekday_angle = 2.0 * math.pi * utc_index.tz_convert(UTC).dayofweek / 7.0
    values["utc_hour_sin"] = pd.Series(np.sin(hour_angle), index=o.index)
    values["utc_hour_cos"] = pd.Series(np.cos(hour_angle), index=o.index)
    values["weekday_sin"] = pd.Series(np.sin(weekday_angle), index=o.index)
    values["weekday_cos"] = pd.Series(np.cos(weekday_angle), index=o.index)

    # Funding (8h serisi -> asof <= t; z 30g = 90 nokta)
    if funding is not None and len(funding) > 100:
        fu = _event_carry(funding, o.index, tolerance=pd.Timedelta(hours=12))
        values["funding"] = fu
        for window in (30, 90, 270):
            values[f"funding_z_{window}bar"] = (fu - fu.rolling(window).mean()) / (
                fu.rolling(window).std() + 1e-12
            )
        values["funding_chg_6bar"] = fu - fu.shift(6)
    # BTC lider getirisi (alt'lar için cross-feature)
    if btc_close is not None:
        b = _event_carry(
            btc_close,
            o.index,
            tolerance=pd.Timedelta(seconds=_TF_SECONDS[timeframe]),
        )
        for bars in (1, 4, 12, 24):
            values[f"btc_ret_{bars}bar"] = b.pct_change(bars, fill_method=None)
        values["relative_to_btc_4bar"] = values["ret_4bar"] - values["btc_ret_4bar"]

    # Daily sentiment is an observed event series. Derive on the event grid,
    # then carry at most 48h; repeated intraday rows are de-overlapped later.
    if sentiment is not None and len(sentiment) >= MIN_OBS:
        observed = sentiment.sort_index() / 100.0
        event_features = {
            "sentiment_value": observed,
            "sentiment_change_1event": observed.diff(1),
            "sentiment_change_7event": observed.diff(7),
            "sentiment_z_30event": (observed - observed.rolling(30).mean())
            / (observed.rolling(30).std() + 1e-12),
            "sentiment_z_90event": (observed - observed.rolling(90).mean())
            / (observed.rolling(90).std() + 1e-12),
        }
        for name, series in event_features.items():
            values[name] = _event_carry(series, o.index, tolerance=pd.Timedelta(hours=48))

    if cross_sectional is not None and not cross_sectional.empty:
        for name in cross_sectional.columns:
            if name.startswith("xs_"):
                values[name] = cross_sectional[name].reindex(o.index)
    return pd.DataFrame(values, index=o.index).replace([np.inf, -np.inf], np.nan)


def build_targets(o: pd.DataFrame, *, timeframe: str = "1h") -> pd.DataFrame:
    """Forward returns divided by trailing volatility known at decision t."""

    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"unsupported timeframe: {timeframe}")
    c = o["close"].astype(float)
    r1 = c.pct_change(fill_method=None)
    t = pd.DataFrame(index=o.index)
    for duration, unit in _TARGET_HORIZONS[timeframe]:
        target = f"fwd_volnorm_{duration}{unit}"
        bars = _target_horizon_bars(target, timeframe=timeframe)
        trailing_window = max(20, bars * 4)
        scale = r1.rolling(trailing_window, min_periods=trailing_window).std() * math.sqrt(bars)
        forward_return = c.shift(-bars) / c - 1.0
        t[target] = forward_return / scale.replace(0.0, np.nan)
    return t


def _target_horizon_bars(target_col: str, *, timeframe: str = "1h") -> int:
    """Convert an explicit duration target to bars for de-overlap effective-N."""

    if timeframe not in _TF_SECONDS:
        return 1
    match = re.fullmatch(r"fwd_(?:volnorm_)?(\d+)(m|h|d)", str(target_col))
    if match is None:
        return 1
    magnitude = max(int(match.group(1)), 1)
    unit_seconds = {"m": 60, "h": 3600, "d": 86400}[match.group(2)]
    return max(math.ceil(magnitude * unit_seconds / _TF_SECONDS[timeframe]), 1)


def _deoverlapped_p(ic: float, n_raw: int, h_bars: int) -> float:
    """Örtüşen forward-return için ETKİN-N Spearman iki-yanlı p-değeri.

    FIX 2026-07-10 (P2 feature-sweep p-şişmesi): fwd_4h/24h/72h target'ları ÖRTÜŞEN
    — komşu satırlar h-1/h bar paylaşır; feature'lar da rolling/ffill autokorele.
    scipy'nin i.i.d. p'si ham n≈31k ile deflate → |IC|>0.011 mikroskopik p → %74
    FDR-pass (crypto getiri tahmininde istatistiksel imkânsız). Etkin örneklem
    n_eff = n_raw // h_bars (bağımsız blok sayısı); Spearman t = ic*sqrt((n_eff-2)/
    (1-ic²)), p = 2*t.sf(|t|, n_eff-2). n_eff<=2 veya |ic|>=1 → p=1.0 (güvenli).
    Nokta-tahmin ic'ye DOKUNULMAZ; yalnız p düzelir → daha az ama dürüst aday.
    """
    n_eff = int(n_raw) // max(int(h_bars), 1)
    if n_eff <= 2 or abs(ic) >= 1.0:
        return 1.0
    t = ic * np.sqrt((n_eff - 2) / (1.0 - ic * ic))
    return float(2.0 * stats.t.sf(abs(t), n_eff - 2))


def sweep_symbol(
    sym: str,
    feats: pd.DataFrame,
    tgts: pd.DataFrame,
    *,
    timeframe: str = "1h",
) -> list[dict]:
    """Tüm (feature, target) çiftleri için IS/OOS Spearman IC."""
    out = []
    n = len(feats)
    if n < MIN_OBS:
        return out
    for fc in feats.columns:
        for tc in tgts.columns:
            pair = pd.concat([feats[fc], tgts[tc]], axis=1).dropna()
            if len(pair) < MIN_OBS:
                continue
            k = int(len(pair) * IS_FRAC)
            is_df, oos_df = pair.iloc[:k], pair.iloc[k:]
            if len(oos_df) < 100:
                continue
            if (
                is_df.iloc[:, 0].nunique() < 2
                or is_df.iloc[:, 1].nunique() < 2
                or oos_df.iloc[:, 0].nunique() < 2
                or oos_df.iloc[:, 1].nunique() < 2
            ):
                continue
            ic_is, _p_iid = stats.spearmanr(is_df.iloc[:, 0], is_df.iloc[:, 1])
            ic_oos, _ = stats.spearmanr(oos_df.iloc[:, 0], oos_df.iloc[:, 1])
            if np.isnan(ic_is) or np.isnan(ic_oos):
                continue
            # scipy'nin i.i.d. p'si yerine örtüşen-target etkin-N p'si (P2 fix):
            # _p_iid deflate; _deoverlapped_p gerçek anlamlılığı verir.
            p_is = _deoverlapped_p(
                float(ic_is),
                len(is_df),
                max(
                    _target_horizon_bars(tc, timeframe=timeframe),
                    _event_independence_bars(fc, timeframe=timeframe),
                ),
            )
            out.append(
                {
                    "symbol": sym,
                    "timeframe": timeframe,
                    "feature": fc,
                    "feature_family": _feature_family(fc),
                    "target": tc,
                    "target_normalization": TARGET_NORMALIZATION,
                    "oos_scheme": OOS_SCHEME,
                    "n_is": len(is_df),
                    "n_oos": len(oos_df),
                    "is_start_ts": pd.Timestamp(is_df.index[0]).isoformat(),
                    "is_end_ts": pd.Timestamp(is_df.index[-1]).isoformat(),
                    "oos_start_ts": pd.Timestamp(oos_df.index[0]).isoformat(),
                    "oos_end_ts": pd.Timestamp(oos_df.index[-1]).isoformat(),
                    "effective_independence_bars": max(
                        _target_horizon_bars(tc, timeframe=timeframe),
                        _event_independence_bars(fc, timeframe=timeframe),
                    ),
                    "ic_is": round(float(ic_is), 4),
                    "p_is": float(p_is),
                    "ic_oos": round(float(ic_oos), 4),
                }
            )
    return out


def bh_fdr(results: list[dict], alpha: float = FDR_ALPHA) -> list[dict]:
    """Benjamini-Yekutieli: bağımlı/korele p'ler için FDR; geçenlere fdr_pass=True.

    FIX 2026-07-10 (P2): testler ağır korele (3 iç-içe örtüşen target/feature +
    tüm semboller BTC ile ko-hareket) → düz BH'nin bağımsızlık/PRDS varsayımı
    bozuk. BY, eşiği harmonik sayı H_m ile bölerek bağımlılık altında FDR
    garantisini geri verir. Monoton sıkılaştırma → BH'nin reddettiğini asla kabul
    etmez (güvenli). FDR_ALPHA ve OOS kapısı DEĞİŞMEZ (eşik gevşetme YASAK).
    """
    if not results:
        return results
    ps = sorted((r["p_is"], i) for i, r in enumerate(results))
    m = len(ps)
    h_m = sum(1.0 / k for k in range(1, m + 1))  # BY harmonic düzeltmesi
    thresh_idx = -1
    for rank, (p, _) in enumerate(ps, start=1):
        if p <= alpha * rank / (m * h_m):
            thresh_idx = rank
    passing = (
        {i for _, (p, i) in zip(range(thresh_idx), ps, strict=False)} if thresh_idx > 0 else set()
    )
    for i, r in enumerate(results):
        r["fdr_pass"] = i in passing
        r["fdr_method"] = "BENJAMINI_YEKUTIELI"
        r["fdr_alpha"] = alpha
        r["fdr_family_size"] = m
        r["fdr_scope"] = "ALL_SELECTED_TF_SYMBOL_FEATURE_TARGET_PAIRS_IN_RUN"
    return results


def confirm_oos(r: dict) -> bool:
    return (
        r["fdr_pass"]
        and abs(r["ic_is"]) >= MIN_ABS_IC
        and np.sign(r["ic_oos"]) == np.sign(r["ic_is"])
        and abs(r["ic_oos"]) >= OOS_RATIO * abs(r["ic_is"])
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="ilk 4 sembol (smoke test)")
    ap.add_argument(
        "--tf",
        choices=sorted(SUPPORTED_TIMEFRAMES),
        action="append",
        help="repeatable; omitted means the full 1h/4h/1d factory",
    )
    ap.add_argument(
        "--candidate-path",
        type=Path,
        default=CAND_PATH,
        help="v2 append-only discovery queue (tests/staging may inject another path)",
    )
    ap.add_argument(
        "--no-candidates",
        action="store_true",
        help="validate/report only; do not append the discovery queue",
    )
    args = ap.parse_args()

    syms = SYMBOLS[:4] if args.quick else SYMBOLS
    timeframes = tuple(dict.fromkeys(args.tf or sorted(SUPPORTED_TIMEFRAMES)))
    all_results: list[dict] = []
    sources: dict[tuple[str, str], dict] = {}
    produced_by_tf: dict[str, set[str]] = {timeframe: set() for timeframe in timeframes}
    sentiment = _load_sentiment()
    with duckdb.connect(str(MARKET_DB), read_only=True) as con:
        for timeframe in timeframes:
            frames = {
                sym: frame
                for sym in syms
                if not (frame := _load_ohlcv(con, sym, timeframe)).empty
                and len(frame) >= MIN_OBS
            }
            cross_sectional = build_cross_sectional_features(frames)
            btc_close = frames.get("BTC/USDT", pd.DataFrame()).get("close")
            for sym in syms:
                o = frames.get(sym)
                if o is None:
                    print(f"[sweep] {timeframe} {sym}: veri yetersiz — atlandı")
                    continue
                sources[(timeframe, sym)] = market_snapshot_metadata(
                    o, symbol=sym, timeframe=timeframe
                )
                feats = build_features(
                    o,
                    _load_funding(sym),
                    None if sym == "BTC/USDT" else btc_close,
                    timeframe=timeframe,
                    sentiment=sentiment,
                    cross_sectional=cross_sectional.get(sym),
                )
                produced_by_tf[timeframe].update(feats.columns)
                tgts = build_targets(o, timeframe=timeframe)
                rs = sweep_symbol(sym, feats, tgts, timeframe=timeframe)
                all_results.extend(rs)
                print(
                    f"[sweep] {timeframe} {sym}: {len(rs)} test "
                    f"({len(o)} bar, {len(feats.columns)} feature)"
                )

    # One BY family across every selected TF/symbol/feature/target pair.
    all_results = bh_fdr(all_results)
    candidates = [r for r in all_results if confirm_oos(r)]
    candidates.sort(key=lambda r: -abs(r["ic_oos"]))

    ts = datetime.now(UTC)
    stamp = ts.strftime("%Y-%m-%d")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Discovery queue.  These records can seed a hypothesis only; the schema
    # explicitly withholds every live/shadow promotion authority.
    code_sha = algorithm_code_sha256()
    candidate_records = [
        make_candidate_record(
            result,
            timeframe=result["timeframe"],
            source=sources[(result["timeframe"], result["symbol"])],
            generated_at=ts,
            code_sha256=code_sha,
        )
        for result in candidates
    ]
    if args.no_candidates:
        appended = 0
        duplicates = 0
    else:
        append_summary = append_candidate_records(
            args.candidate_path,
            candidate_records,
            expected_algorithm_sha256=code_sha,
        )
        appended = append_summary.appended
        duplicates = append_summary.duplicates

    reports: list[Path] = []
    for timeframe in timeframes:
        tf_results = [r for r in all_results if r["timeframe"] == timeframe]
        tf_candidates = [r for r in candidates if r["timeframe"] == timeframe]
        coverage = build_feature_coverage(
            produced_columns=produced_by_tf[timeframe],
            min_observations=MIN_OBS,
            funding_db=FUNDING_DB,
            sentiment_db=SENTIMENT_DB,
            dominance_db=DOMINANCE_DB,
            stablecoin_db=STABLECOIN_DB,
            generated_at=ts,
        )
        coverage["timeframe"] = timeframe
        coverage_path = OUT_DIR / f"{stamp}_{timeframe}_coverage.json"
        coverage_path.write_text(
            json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        lines = [
            f"# Feature Sweep — {stamp} — {timeframe}",
            "",
            f"Toplam test: **{len(tf_results)}** · Feature: **{len(produced_by_tf[timeframe])}** · "
            f"Global FDR(BY, α={FDR_ALPHA}, m={len(all_results)}) geçen: "
            f"**{sum(1 for r in tf_results if r['fdr_pass'])}** · "
            f"OOS-tutarlı keşif: **{len(tf_candidates)}**",
            "",
            "Target: forward return / decision-bar trailing realized volatility.",
            "OOS: chronological 70/30 confirmation; independent promotion holdout DEĞİL.",
            "Kanıt sınıfı: DESCRIPTIVE_DISCOVERY · promotion_eligible=false",
            "",
            "## Auxiliary coverage",
            "",
            "| family | status | features | reason |",
            "|---|---|---:|---|",
        ]
        for family in coverage["families"]:
            lines.append(
                f"| {family['family']} | {family['status']} | {family['feature_count']} | "
                f"{family['reason']} |"
            )
        lines.extend(
            [
                "",
                "| symbol | family | feature | target | IC_is | IC_oos | n |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for result in tf_candidates[:40]:
            lines.append(
                f"| {result['symbol']} | {result['feature_family']} | {result['feature']} | "
                f"{result['target']} | {result['ic_is']:+.3f} | {result['ic_oos']:+.3f} | "
                f"{result['n_is'] + result['n_oos']} |"
            )
        if not tf_candidates:
            lines.append("| — | — | (bu turda aday yok — dürüst sonuç) | | | | |")
        report = OUT_DIR / f"{stamp}_{timeframe}.md"
        report.write_text("\n".join(lines) + "\n", encoding="utf-8")
        reports.append(report)

    print(
        f"[sweep] TAMAM: TF={','.join(timeframes)}, {len(all_results)} test, "
        f"{len(candidates)} keşif ({appended} yeni, {duplicates} duplicate) → "
        f"{', '.join(str(path) for path in reports)}"
    )


if __name__ == "__main__":
    main()
