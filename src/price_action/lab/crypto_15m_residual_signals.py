"""Causal signal generators for the preregistered crypto 15-minute cells.

The functions are pure: callers provide already-loaded frames and funding
events, and no file, network, random-number, or wall-clock state is consulted.
OHLCV timestamps are 15-minute bar-open labels.  An intent at ``t`` therefore
uses the completed bar labelled ``t`` and the event engine may enter only at
the next contiguous bar open.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC

import numpy as np
import pandas as pd

from price_action.lab.crypto_15m_event_engine import SignalIntent

_OHLCV = ("open", "high", "low", "close", "volume")
_BAR = pd.Timedelta(minutes=15)
_MAX_GAP = pd.Timedelta(minutes=30)


@dataclass(frozen=True, slots=True)
class ResidualTrendCell:
    candidate_id: str
    formation_bars: int
    beta_lookback_bars: int = 2688
    hold_bars: int = 672
    long_k: int = 3
    short_k: int = 3
    atr_period: int = 96
    stop_atr_multiple: float = 4.0


@dataclass(frozen=True, slots=True)
class FundingReversionCell:
    candidate_id: str
    residual_abs_z_min: float
    hold_bars: int
    beta_lookback_bars: int = 2688
    formation_bars: int = 96
    z_lookback_bars: int = 2880
    long_k: int = 2
    short_k: int = 2
    atr_period: int = 96
    stop_atr_multiple: float = 3.0


PREREGISTERED_TREND_CELLS = (
    ResidualTrendCell("T1_RESIDUAL_TREND_1W", 672),
    ResidualTrendCell("T2_RESIDUAL_TREND_2W", 1344),
    ResidualTrendCell("T4_RESIDUAL_TREND_4W", 2688),
)
PREREGISTERED_REVERSION_CELLS = (
    FundingReversionCell("M1_FUNDING_RESIDUAL_REVERSION_4H_Z2", 2.0, 16),
    FundingReversionCell("M2_FUNDING_RESIDUAL_REVERSION_8H_Z2", 2.0, 32),
    FundingReversionCell("M3_FUNDING_RESIDUAL_REVERSION_4H_Z2P5", 2.5, 16),
)


def _positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or int(value) < 1:
        raise ValueError(f"{name} must be an integer >= 1")
    return int(value)


def _utc_index(frame: pd.DataFrame, *, symbol: str) -> tuple[pd.DataFrame, pd.DatetimeIndex]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError(f"{symbol}: OHLCV frame must be a non-empty DataFrame")
    missing = sorted(set(_OHLCV).difference(frame.columns))
    if missing:
        raise ValueError(f"{symbol}: missing OHLCV columns: {missing}")
    raw = frame["ts"] if "ts" in frame.columns else frame.index
    try:
        index = pd.DatetimeIndex(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{symbol}: timestamps are invalid") from exc
    if index.tz is None or str(index.tz).upper() not in {"UTC", "UTC+00:00"}:
        raise ValueError(f"{symbol}: timestamps must be timezone-aware UTC")
    index = index.tz_convert(UTC)
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError(f"{symbol}: timestamps must be unique and increasing")
    if len(index) > 1:
        deltas = index[1:] - index[:-1]
        grid_steps = deltas / _BAR
        if np.any(deltas <= pd.Timedelta(0)) or np.any(grid_steps != np.floor(grid_steps)):
            raise ValueError(f"{symbol}: timestamps must lie on one 15-minute grid")
    if np.any(index.as_unit("ns").asi8 % _BAR.value != 0):
        raise ValueError(f"{symbol}: timestamps must be anchored to the UTC quarter-hour grid")
    normalized = frame.loc[:, _OHLCV].copy()
    normalized.index = index
    values = normalized.to_numpy(dtype=float)
    if not np.isfinite(values).all():
        raise ValueError(f"{symbol}: OHLCV values must be finite")
    if (normalized[["open", "high", "low", "close"]] <= 0).any().any():
        raise ValueError(f"{symbol}: prices must be > 0")
    if (normalized["volume"] < 0).any():
        raise ValueError(f"{symbol}: volume must be >= 0")
    if (normalized["high"] < normalized[["open", "low", "close"]].max(axis=1)).any():
        raise ValueError(f"{symbol}: high violates OHLC geometry")
    if (normalized["low"] > normalized[["open", "high", "close"]].min(axis=1)).any():
        raise ValueError(f"{symbol}: low violates OHLC geometry")
    return normalized, index


def validate_aligned_utc_15m_frames(
    frames: Mapping[str, pd.DataFrame],
    *,
    btc_symbol: str = "BTC/USDT",
) -> dict[str, pd.DataFrame]:
    """Return defensive copies after strict aligned-frame validation."""

    if not isinstance(frames, Mapping) or btc_symbol not in frames or len(frames) < 2:
        raise ValueError("frames must contain BTC and at least one tradable symbol")
    normalized: dict[str, pd.DataFrame] = {}
    reference: pd.DatetimeIndex | None = None
    for symbol in sorted(frames):
        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError("frame symbols must be non-empty strings")
        frame, index = _utc_index(frames[symbol], symbol=symbol)
        if reference is None:
            reference = index
        elif not reference.equals(index):
            raise ValueError("all OHLCV frames must have exactly aligned timestamps")
        normalized[symbol] = frame
    return normalized


def _gap_breaks(index: pd.DatetimeIndex) -> pd.Series:
    return index.to_series(index=index).diff().gt(_MAX_GAP)


def _contiguous_age(index: pd.DatetimeIndex) -> pd.Series:
    breaks = _gap_breaks(index)
    return pd.Series(1, index=index).groupby(breaks.cumsum()).cumsum().astype(int)


def _atr(frame: pd.DataFrame, period: int) -> pd.Series:
    previous = frame["close"].shift(1)
    true_range = pd.concat(
        [
            frame["high"] - frame["low"],
            (frame["high"] - previous).abs(),
            (frame["low"] - previous).abs(),
        ],
        axis=1,
    ).max(axis=1)
    true_range = true_range.mask(_gap_breaks(frame.index))
    return true_range.rolling(period, min_periods=period).mean()


def compute_causal_residual_features(
    frames: Mapping[str, pd.DataFrame],
    *,
    beta_lookback_bars: int = 2688,
    atr_period: int = 96,
    btc_symbol: str = "BTC/USDT",
) -> dict[str, pd.DataFrame]:
    """Compute one-bar returns, shifted rolling BTC beta, residuals and ATR.

    Beta at bar ``t`` is estimated strictly from returns ending at ``t-1``.
    The residual at ``t`` may use the current completed bar's return.
    """

    beta_lookback_bars = _positive_int("beta_lookback_bars", beta_lookback_bars)
    atr_period = _positive_int("atr_period", atr_period)
    clean = validate_aligned_utc_15m_frames(frames, btc_symbol=btc_symbol)
    btc_return = clean[btc_symbol]["close"].pct_change(fill_method=None)
    gap_breaks = _gap_breaks(clean[btc_symbol].index)
    btc_return = btc_return.mask(gap_breaks)
    btc_variance = (
        btc_return.rolling(beta_lookback_bars, min_periods=beta_lookback_bars).var().shift(1)
    )
    age = _contiguous_age(clean[btc_symbol].index)
    output: dict[str, pd.DataFrame] = {}
    for symbol, frame in clean.items():
        asset_return = frame["close"].pct_change(fill_method=None).mask(gap_breaks)
        covariance = (
            asset_return.rolling(beta_lookback_bars, min_periods=beta_lookback_bars)
            .cov(btc_return)
            .shift(1)
        )
        beta = (covariance / btc_variance.replace(0.0, np.nan)).mask(gap_breaks)
        output[symbol] = pd.DataFrame(
            {
                "close": frame["close"],
                "asset_return": asset_return,
                "btc_return": btc_return,
                "beta": beta,
                "residual_return": asset_return - beta * btc_return,
                "atr": _atr(frame, atr_period),
                "contiguous_bars": age,
            },
            index=frame.index,
        )
    return output


def _rank(scores: Mapping[str, float], *, reverse: bool) -> list[str]:
    return [
        symbol
        for symbol, _ in sorted(
            scores.items(), key=lambda item: ((-item[1] if reverse else item[1]), item[0])
        )
    ]


def _intent(
    cell_id: str,
    ts: pd.Timestamp,
    symbol: str,
    side: str,
    score: float,
    atr: float,
    stop_atr_multiple: float,
    hold_bars: int,
) -> SignalIntent:
    return SignalIntent(
        candidate_id=cell_id,
        decision_ts=ts.to_pydatetime(),
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        score=abs(float(score)),
        atr=float(atr),
        stop_atr_multiple=float(stop_atr_multiple),
        hold_bars=int(hold_bars),
    )


def generate_residual_cross_sectional_trend_intents(
    frames: Mapping[str, pd.DataFrame],
    cell: ResidualTrendCell,
    *,
    trade_holdouts: frozenset[str] | None = None,
    btc_symbol: str = "BTC/USDT",
    warmup_bars_after_gap: int = 500,
) -> list[SignalIntent]:
    """Long top residual trends and short bottom trends each Monday 00:00 UTC."""

    if trade_holdouts is None:
        raise ValueError("trade_holdouts must be explicitly provided")
    warmup = _positive_int("warmup_bars_after_gap", warmup_bars_after_gap)
    long_k = _positive_int("long_k", cell.long_k)
    short_k = _positive_int("short_k", cell.short_k)
    features = compute_causal_residual_features(
        frames,
        beta_lookback_bars=cell.beta_lookback_bars,
        atr_period=cell.atr_period,
        btc_symbol=btc_symbol,
    )
    tradable = sorted(set(features).difference(trade_holdouts).difference({btc_symbol}))
    if len(tradable) < long_k + short_k:
        raise ValueError("not enough non-holdout symbols for disjoint long/short ranks")
    scores: dict[str, pd.Series] = {}
    for symbol, feature in features.items():
        residual = feature["residual_return"]
        rolling = residual.rolling(cell.formation_bars, min_periods=cell.formation_bars)
        cumulative = rolling.sum()
        scale = rolling.std(ddof=0) * np.sqrt(float(cell.formation_bars))
        scores[symbol] = cumulative / scale.replace(0.0, np.nan)
    intents: list[SignalIntent] = []
    for ts in features[btc_symbol].index:
        if ts.dayofweek != 0 or ts.hour != 0 or ts.minute != 0:
            continue
        values: dict[str, float] = {}
        for symbol in tradable:
            row = features[symbol].loc[ts]
            score = scores[symbol].loc[ts]
            if (
                row["contiguous_bars"] >= warmup
                and np.isfinite(score)
                and np.isfinite(row["atr"])
                and row["atr"] > 0
            ):
                values[symbol] = float(score)
        if len(values) < long_k + short_k:
            continue
        longs = _rank(values, reverse=True)[:long_k]
        shorts = _rank(values, reverse=False)[:short_k]
        for symbol in longs:
            row = features[symbol].loc[ts]
            intents.append(
                _intent(
                    cell.candidate_id,
                    ts,
                    symbol,
                    "long",
                    values[symbol],
                    row["atr"],
                    cell.stop_atr_multiple,
                    cell.hold_bars,
                )
            )
        for symbol in shorts:
            row = features[symbol].loc[ts]
            intents.append(
                _intent(
                    cell.candidate_id,
                    ts,
                    symbol,
                    "short",
                    values[symbol],
                    row["atr"],
                    cell.stop_atr_multiple,
                    cell.hold_bars,
                )
            )
    return sorted(intents, key=lambda item: (item.decision_ts, -item.score, item.symbol))


def _funding_series(value: pd.Series | pd.DataFrame, *, symbol: str) -> pd.Series:
    if isinstance(value, pd.DataFrame):
        if "funding_rate" not in value.columns:
            raise ValueError(f"{symbol}: funding frame needs funding_rate")
        raw_index = value["ts"] if "ts" in value.columns else value.index
        series = pd.Series(value["funding_rate"].to_numpy(), index=pd.DatetimeIndex(raw_index))
    elif isinstance(value, pd.Series):
        series = value.copy()
        series.index = pd.DatetimeIndex(series.index)
    else:
        raise ValueError(f"{symbol}: funding must be a Series or DataFrame")
    if series.index.tz is None or str(series.index.tz).upper() not in {"UTC", "UTC+00:00"}:
        raise ValueError(f"{symbol}: funding timestamps must be UTC")
    series.index = series.index.tz_convert(UTC)
    if series.index.has_duplicates or not series.index.is_monotonic_increasing:
        raise ValueError(f"{symbol}: funding timestamps must be unique and increasing")
    series = pd.to_numeric(series, errors="coerce")
    if not np.isfinite(series.dropna().to_numpy(dtype=float)).all():
        raise ValueError(f"{symbol}: funding must be finite")
    return series.astype(float)


def generate_funding_confirmed_residual_reversion_intents(
    frames: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.Series | pd.DataFrame],
    cell: FundingReversionCell,
    *,
    trade_holdouts: frozenset[str] | None = None,
    btc_symbol: str = "BTC/USDT",
    warmup_bars_after_gap: int = 500,
) -> list[SignalIntent]:
    """Fade residual extremes only when funding crowds in the move's direction."""

    if trade_holdouts is None:
        raise ValueError("trade_holdouts must be explicitly provided")
    warmup = _positive_int("warmup_bars_after_gap", warmup_bars_after_gap)
    features = compute_causal_residual_features(
        frames,
        beta_lookback_bars=cell.beta_lookback_bars,
        atr_period=cell.atr_period,
        btc_symbol=btc_symbol,
    )
    tradable = sorted(set(features).difference(trade_holdouts).difference({btc_symbol}))
    formation: dict[str, pd.Series] = {}
    zscore: dict[str, pd.Series] = {}
    funding_aligned: dict[str, pd.Series] = {}
    for symbol in tradable:
        if symbol not in funding:
            continue
        formed = (
            features[symbol]["residual_return"]
            .rolling(cell.formation_bars, min_periods=cell.formation_bars)
            .sum()
        )
        prior = formed.shift(1)
        mean = prior.rolling(cell.z_lookback_bars, min_periods=cell.z_lookback_bars).mean()
        std = prior.rolling(cell.z_lookback_bars, min_periods=cell.z_lookback_bars).std(ddof=0)
        formation[symbol] = formed
        zscore[symbol] = (formed - mean) / std.replace(0.0, np.nan)
        observed = _funding_series(funding[symbol], symbol=symbol)
        funding_aligned[symbol] = observed.reindex(
            features[symbol].index, method="ffill", tolerance=pd.Timedelta(hours=8)
        )
    intents: list[SignalIntent] = []
    for ts in features[btc_symbol].index:
        if ts.minute != 0 or ts.hour not in {0, 8, 16}:
            continue
        positive: dict[str, float] = {}
        negative: dict[str, float] = {}
        for symbol in sorted(zscore):
            row = features[symbol].loc[ts]
            z = zscore[symbol].loc[ts]
            rate = funding_aligned[symbol].loc[ts]
            if (
                row["contiguous_bars"] < warmup
                or not np.isfinite(z)
                or not np.isfinite(rate)
                or not np.isfinite(row["atr"])
                or row["atr"] <= 0
            ):
                continue
            if z >= cell.residual_abs_z_min and rate > 0:
                positive[symbol] = float(z)
            elif z <= -cell.residual_abs_z_min and rate < 0:
                negative[symbol] = float(z)
        for symbol in _rank(negative, reverse=False)[: cell.long_k]:
            row = features[symbol].loc[ts]
            intents.append(
                _intent(
                    cell.candidate_id,
                    ts,
                    symbol,
                    "long",
                    negative[symbol],
                    row["atr"],
                    cell.stop_atr_multiple,
                    cell.hold_bars,
                )
            )
        for symbol in _rank(positive, reverse=True)[: cell.short_k]:
            row = features[symbol].loc[ts]
            intents.append(
                _intent(
                    cell.candidate_id,
                    ts,
                    symbol,
                    "short",
                    positive[symbol],
                    row["atr"],
                    cell.stop_atr_multiple,
                    cell.hold_bars,
                )
            )
    return sorted(intents, key=lambda item: (item.decision_ts, -item.score, item.symbol))


def generate_preregistered_signal_intents(
    frames: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.Series | pd.DataFrame],
    *,
    trade_holdouts: frozenset[str],
    btc_symbol: str = "BTC/USDT",
) -> dict[str, tuple[SignalIntent, ...]]:
    """Generate all six frozen cells without combining or selecting them."""

    result: dict[str, tuple[SignalIntent, ...]] = {}
    for cell in PREREGISTERED_TREND_CELLS:
        result[cell.candidate_id] = tuple(
            generate_residual_cross_sectional_trend_intents(
                frames, cell, trade_holdouts=trade_holdouts, btc_symbol=btc_symbol
            )
        )
    for cell in PREREGISTERED_REVERSION_CELLS:
        result[cell.candidate_id] = tuple(
            generate_funding_confirmed_residual_reversion_intents(
                frames,
                funding,
                cell,
                trade_holdouts=trade_holdouts,
                btc_symbol=btc_symbol,
            )
        )
    return result


__all__ = [
    "PREREGISTERED_REVERSION_CELLS",
    "PREREGISTERED_TREND_CELLS",
    "FundingReversionCell",
    "ResidualTrendCell",
    "compute_causal_residual_features",
    "generate_funding_confirmed_residual_reversion_intents",
    "generate_preregistered_signal_intents",
    "generate_residual_cross_sectional_trend_intents",
    "validate_aligned_utc_15m_frames",
]
