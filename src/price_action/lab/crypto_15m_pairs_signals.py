"""Causal selection and entry signals for the preregistered v17 pair cells.

All timestamps on frames and intents are UTC 15-minute *bar-open* labels.  A
decision on a ``:45`` bar is known when that bar completes 15 minutes later;
``PairEntryIntent.entry_ts`` is that shared next-open timestamp.  The module is
pure and performs no file, network, random-number, or wall-clock IO.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import combinations
from typing import Literal

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import coint

Side = Literal["long", "short"]
_BAR = pd.Timedelta(minutes=15)
_HOUR = pd.Timedelta(hours=1)
_OHLCV = ("open", "high", "low", "close", "volume")


def _finite(name: str, value: float, *, positive: bool = False) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or (positive and parsed <= 0.0):
        raise ValueError(f"{name} must be finite{' and > 0' if positive else ''}")
    return parsed


def _canonical_usdt_symbol(value: object, *, label: str) -> str:
    text = str(value).strip().upper().split(":", 1)[0].replace("-", "/").replace("_", "/")
    if not text:
        raise ValueError(f"{label}: symbol must be non-empty")
    if "/" in text:
        pieces = text.split("/")
        if len(pieces) != 2:
            raise ValueError(f"{label}: unsupported symbol {value!r}")
        base, quote = pieces
    elif text.endswith("USDT"):
        base, quote = text[:-4], "USDT"
    else:
        base, quote = text, "USDT"
    if not base or quote != "USDT" or not base.isalnum():
        raise ValueError(f"{label}: unsupported symbol {value!r}")
    return f"{base}/USDT"


def _positive_int(name: str, value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be an integer >= 1")
    return value


def _utc_datetime(name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware UTC")
    if value.utcoffset() != timedelta(0):
        raise ValueError(f"{name} must be UTC")
    return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class PairCell:
    candidate_id: str
    train_hours: int
    validation_hours: int
    entry_abs_z: float
    exit_abs_z: float
    disaster_abs_z: float
    half_life_min_hours: float
    half_life_max_hours: float
    max_hold_hours: int
    cooldown_hours: int

    def __post_init__(self) -> None:
        if not str(self.candidate_id).strip():
            raise ValueError("candidate_id must be non-empty")
        for name in ("train_hours", "validation_hours", "max_hold_hours", "cooldown_hours"):
            object.__setattr__(self, name, _positive_int(name, getattr(self, name)))
        for name in (
            "entry_abs_z",
            "exit_abs_z",
            "disaster_abs_z",
            "half_life_min_hours",
            "half_life_max_hours",
        ):
            object.__setattr__(self, name, _finite(name, getattr(self, name), positive=True))
        if not self.exit_abs_z < self.entry_abs_z < self.disaster_abs_z:
            raise ValueError("z thresholds must satisfy exit < entry < disaster")
        if self.half_life_min_hours >= self.half_life_max_hours:
            raise ValueError("half-life bounds must be increasing")


@dataclass(frozen=True, slots=True)
class PairModel:
    candidate_id: str
    pair_id: str
    selection_ts: datetime
    y_symbol: str
    x_symbol: str
    alpha: float
    beta: float
    validation_mean: float
    validation_std: float
    engle_granger_p: float
    holm_adjusted_p: float
    normalized_price_ssd: float
    training_correlation: float
    half_life_hours: float
    pair_btc_beta: float
    gross_weight_y: float
    gross_weight_x: float
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.pair_id:
            raise ValueError("candidate_id and pair_id must be non-empty")
        if not self.y_symbol or not self.x_symbol or self.y_symbol == self.x_symbol:
            raise ValueError("pair symbols must be distinct and non-empty")
        for name in (
            "selection_ts",
            "train_start",
            "train_end",
            "validation_start",
            "validation_end",
        ):
            object.__setattr__(self, name, _utc_datetime(name, getattr(self, name)))
        if not self.train_start < self.train_end <= self.validation_start < self.validation_end:
            raise ValueError("model windows must be ordered")
        if self.validation_end != self.selection_ts:
            raise ValueError("validation must end at selection_ts")
        for name in (
            "alpha",
            "beta",
            "validation_mean",
            "validation_std",
            "engle_granger_p",
            "holm_adjusted_p",
            "normalized_price_ssd",
            "training_correlation",
            "half_life_hours",
            "pair_btc_beta",
            "gross_weight_y",
            "gross_weight_x",
        ):
            object.__setattr__(self, name, _finite(name, getattr(self, name)))
        if self.validation_std <= 0.0 or self.beta <= 0.0 or self.half_life_hours <= 0.0:
            raise ValueError("model scale, beta and half-life must be > 0")
        if not 0.0 <= self.engle_granger_p <= 1.0:
            raise ValueError("engle_granger_p must be in [0, 1]")
        if not 0.0 <= self.holm_adjusted_p <= 1.0:
            raise ValueError("holm_adjusted_p must be in [0, 1]")
        if min(self.gross_weight_y, self.gross_weight_x) <= 0.0:
            raise ValueError("gross weights must be > 0")
        if not math.isclose(self.gross_weight_y + self.gross_weight_x, 1.0, abs_tol=1e-12):
            raise ValueError("gross weights must sum to one")


@dataclass(frozen=True, slots=True)
class PairEntryIntent:
    candidate_id: str
    pair_id: str
    selection_ts: datetime
    decision_ts: datetime
    entry_ts: datetime
    y_symbol: str
    x_symbol: str
    y_side: Side
    x_side: Side
    z_score: float
    alpha: float
    beta: float
    validation_mean: float
    validation_std: float
    gross_weight_y: float
    gross_weight_x: float
    entry_abs_z: float
    exit_abs_z: float
    disaster_abs_z: float
    max_hold_hours: int
    cooldown_hours: int
    expected_convergence_return: float
    adverse_funding: float
    stressed_required_return: float
    economic_buffer_multiplier: float = 1.50
    base_round_trip_cost_per_gross: float = 0.0057
    c2_round_trip_cost_per_gross: float = 0.0114

    def __post_init__(self) -> None:
        if not self.candidate_id or not self.pair_id:
            raise ValueError("candidate_id and pair_id must be non-empty")
        if not self.y_symbol or not self.x_symbol or self.y_symbol == self.x_symbol:
            raise ValueError("intent pair symbols must be distinct and non-empty")
        for name in ("selection_ts", "decision_ts", "entry_ts"):
            object.__setattr__(self, name, _utc_datetime(name, getattr(self, name)))
        if self.selection_ts > self.entry_ts:
            raise ValueError("selection_ts cannot be after entry_ts")
        if self.entry_ts - self.decision_ts != timedelta(minutes=15):
            raise ValueError("entry_ts must be the next 15-minute open")
        if self.decision_ts.minute != 45:
            raise ValueError("entry decisions must use a completed :45 source bar")
        if {self.y_side, self.x_side} != {"long", "short"}:
            raise ValueError("pair intent must contain one long and one short leg")
        for name in (
            "z_score",
            "alpha",
            "beta",
            "validation_mean",
            "validation_std",
            "gross_weight_y",
            "gross_weight_x",
            "entry_abs_z",
            "exit_abs_z",
            "disaster_abs_z",
            "expected_convergence_return",
            "adverse_funding",
            "stressed_required_return",
            "economic_buffer_multiplier",
            "base_round_trip_cost_per_gross",
            "c2_round_trip_cost_per_gross",
        ):
            object.__setattr__(self, name, _finite(name, getattr(self, name)))
        object.__setattr__(
            self, "max_hold_hours", _positive_int("max_hold_hours", self.max_hold_hours)
        )
        object.__setattr__(
            self, "cooldown_hours", _positive_int("cooldown_hours", self.cooldown_hours)
        )
        if abs(self.z_score) >= self.disaster_abs_z:
            raise ValueError("entry z must be strictly inside the disaster threshold")
        if abs(self.z_score) < self.entry_abs_z:
            raise ValueError("provisional entry z must meet the entry threshold")
        if not self.exit_abs_z < self.entry_abs_z < self.disaster_abs_z:
            raise ValueError("intent z thresholds must satisfy exit < entry < disaster")
        if min(self.validation_std, self.beta, self.gross_weight_y, self.gross_weight_x) <= 0.0:
            raise ValueError("scale, beta and gross weights must be > 0")
        if not math.isclose(self.gross_weight_y + self.gross_weight_x, 1.0, abs_tol=1e-12):
            raise ValueError("gross weights must sum to one")
        if self.adverse_funding < 0.0 or self.stressed_required_return < 0.0:
            raise ValueError("funding and required return must be >= 0")
        if self.expected_convergence_return < self.stressed_required_return:
            raise ValueError("provisional intent must pass the economic entry gate")


PREREGISTERED_PAIR_CELLS = (
    PairCell("DP1_EG_90D_Z2P5", 2160, 672, 2.5, 0.5, 4.5, 12.0, 120.0, 168, 48),
    PairCell("DP2_EG_180D_Z2P5", 4320, 672, 2.5, 0.5, 4.5, 24.0, 168.0, 336, 72),
    PairCell("DP3_EG_180D_Z3_STRICT", 4320, 672, 3.0, 0.5, 5.0, 24.0, 168.0, 336, 72),
)


@dataclass(frozen=True, slots=True)
class _PairCandidate:
    pair_id: str
    y_symbol: str
    x_symbol: str
    alpha: float
    beta: float
    validation_mean: float
    validation_std: float
    engle_granger_p: float
    normalized_price_ssd: float
    training_correlation: float
    half_life_hours: float
    pair_btc_beta: float
    gross_weight_y: float
    gross_weight_x: float
    beta_relative_change: float
    validation_mean_shift: float
    validation_std_ratio: float
    validation_crossings: int
    train_start: datetime
    train_end: datetime
    validation_start: datetime
    validation_end: datetime


def _normalize_frame(frame: pd.DataFrame, *, symbol: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ValueError(f"{symbol}: frame must be a non-empty DataFrame")
    missing = sorted(set(_OHLCV).difference(frame.columns))
    if missing:
        raise ValueError(f"{symbol}: missing OHLCV columns: {missing}")
    raw_ts = frame["ts"] if "ts" in frame.columns else frame.index
    try:
        index = pd.DatetimeIndex(raw_ts)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{symbol}: invalid timestamps") from exc
    if index.tz is None or any(ts.utcoffset() != timedelta(0) for ts in index):
        raise ValueError(f"{symbol}: timestamps must be timezone-aware UTC")
    index = index.tz_convert(UTC)
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError(f"{symbol}: timestamps must be unique and increasing")
    if np.any(index.as_unit("ns").asi8 % _BAR.value != 0):
        raise ValueError(f"{symbol}: timestamps must be on the UTC quarter-hour grid")
    clean = frame.loc[:, _OHLCV].copy()
    clean.index = index
    for column in _OHLCV:
        clean[column] = pd.to_numeric(clean[column], errors="coerce")
    if not np.isfinite(clean.to_numpy(dtype=float)).all():
        raise ValueError(f"{symbol}: OHLCV values must be finite")
    if (clean[["open", "high", "low", "close"]] <= 0.0).any().any():
        raise ValueError(f"{symbol}: prices must be > 0")
    if (clean["volume"] < 0.0).any():
        raise ValueError(f"{symbol}: volume must be >= 0")
    if (clean["high"] < clean[["open", "low", "close"]].max(axis=1)).any():
        raise ValueError(f"{symbol}: invalid OHLC high")
    if (clean["low"] > clean[["open", "high", "close"]].min(axis=1)).any():
        raise ValueError(f"{symbol}: invalid OHLC low")
    return clean


def normalize_pair_frames(frames: Mapping[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """Validate frames independently; deliberately perform no global alignment."""

    if not isinstance(frames, Mapping) or not frames:
        raise ValueError("frames must be a non-empty symbol mapping")
    result: dict[str, pd.DataFrame] = {}
    for raw_symbol in sorted(frames):
        symbol = str(raw_symbol).strip()
        if not symbol:
            raise ValueError("symbols must be non-empty")
        result[symbol] = _normalize_frame(frames[raw_symbol], symbol=symbol)
    return result


def _pair_id(first: str, second: str) -> str:
    return "|".join(sorted((first, second)))


def _complete_hour_index(index: pd.DatetimeIndex) -> pd.DatetimeIndex:
    return index[(index.minute == 45) & (index.second == 0) & (index.microsecond == 0)]


def _pair_hourly_window(
    frames: Mapping[str, pd.DataFrame],
    first_symbol: str,
    second_symbol: str,
    btc_symbol: str,
    *,
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> pd.DataFrame:
    """Return pair-local completed-hour closes without filling any missing price."""

    common = frames[first_symbol].index.intersection(frames[second_symbol].index, sort=False)
    common = common.intersection(frames[btc_symbol].index, sort=False).sort_values()
    endpoints = _complete_hour_index(common)
    endpoints = endpoints[(endpoints >= start) & (endpoints < end)]
    complete_mask = np.ones(len(endpoints), dtype=bool)
    for offset in range(4):
        complete_mask &= (endpoints - offset * _BAR).isin(common)
    complete_endpoints = endpoints[complete_mask]
    if complete_endpoints.empty:
        return pd.DataFrame(index=pd.DatetimeIndex([], tz=UTC))

    def hourly_volume(symbol: str) -> np.ndarray:
        total = np.zeros(len(complete_endpoints), dtype=float)
        for offset in range(4):
            total += (
                frames[symbol]
                .loc[complete_endpoints - offset * _BAR, "volume"]
                .to_numpy(dtype=float)
            )
        return total

    return pd.DataFrame(
        {
            f"{first_symbol}:close": frames[first_symbol]
            .loc[complete_endpoints, "close"]
            .to_numpy(),
            f"{first_symbol}:volume": hourly_volume(first_symbol),
            f"{second_symbol}:close": frames[second_symbol]
            .loc[complete_endpoints, "close"]
            .to_numpy(),
            f"{second_symbol}:volume": hourly_volume(second_symbol),
            f"{btc_symbol}:close": frames[btc_symbol].loc[complete_endpoints, "close"].to_numpy(),
        },
        index=complete_endpoints,
    )


def _longest_exact_hour_block(frame: pd.DataFrame) -> pd.DataFrame:
    """Choose the longest exact-1h block; ties deliberately choose the latest."""

    if frame.empty:
        return frame.copy()
    breaks = frame.index.to_series(index=frame.index).diff().ne(_HOUR)
    blocks = [group for _, group in frame.groupby(breaks.cumsum(), sort=True)]
    return max(blocks, key=lambda block: (len(block), block.index[-1])).copy()


def _exact_hour_suffix(frame: pd.DataFrame, *, expected_last: pd.Timestamp) -> pd.DataFrame:
    """Return the exact-1h suffix only when it reaches the fixed-window cutoff."""

    if frame.empty or frame.index[-1] != expected_last:
        return frame.iloc[0:0].copy()
    start = len(frame) - 1
    while start > 0 and frame.index[start] - frame.index[start - 1] == _HOUR:
        start -= 1
    return frame.iloc[start:].copy()


def _ols_alpha_beta(y: np.ndarray, x: np.ndarray) -> tuple[float, float]:
    design = np.column_stack((np.ones(len(x), dtype=float), x))
    alpha, beta = np.linalg.lstsq(design, y, rcond=None)[0]
    return float(alpha), float(beta)


def _exact_hour_returns(log_prices: np.ndarray, index: pd.DatetimeIndex) -> np.ndarray:
    exact = np.asarray(index[1:] - index[:-1] == _HOUR, dtype=bool)
    return np.diff(log_prices)[exact]


def _ar1_half_life(residual: np.ndarray, index: pd.DatetimeIndex) -> tuple[float, float]:
    if len(residual) < 3:
        return float("nan"), float("nan")
    exact = np.asarray(index[1:] - index[:-1] == _HOUR, dtype=bool)
    if exact.sum() < 2:
        return float("nan"), float("nan")
    _, phi = _ols_alpha_beta(residual[1:][exact], residual[:-1][exact])
    if not 0.0 < phi < 1.0:
        return phi, float("nan")
    return phi, float(-math.log(2.0) / math.log(phi))


def _mean_crossings(values: np.ndarray, mean: float, index: pd.DatetimeIndex) -> int:
    centered = values - mean
    # Frozen contract: only a strict sign change across two exact-adjacent
    # hourly observations is a crossing.  A value exactly on the mean does not
    # bridge its neighbours and therefore contributes no crossing.
    return sum(
        1
        for offset in range(1, len(centered))
        if index[offset] - index[offset - 1] == _HOUR
        and centered[offset - 1] * centered[offset] < 0.0
    )


def _engle_granger_p(y: np.ndarray, x: np.ndarray) -> float:
    try:
        _statistic, pvalue, _critical = coint(y, x, trend="c", maxlag=24, autolag="aic")
    except (ArithmeticError, ValueError, np.linalg.LinAlgError):
        return 1.0
    return float(pvalue) if math.isfinite(float(pvalue)) else 1.0


def _candidate_from_pair(
    frames: Mapping[str, pd.DataFrame],
    first_symbol: str,
    second_symbol: str,
    cell: PairCell,
    selection_ts: pd.Timestamp,
    *,
    btc_symbol: str,
    minimum_completeness: float,
) -> _PairCandidate | None:
    validation_end = selection_ts
    validation_start = validation_end - cell.validation_hours * _HOUR
    train_end = validation_start
    train_start = train_end - cell.train_hours * _HOUR
    hourly = _pair_hourly_window(
        frames,
        first_symbol,
        second_symbol,
        btc_symbol,
        start=train_start,
        end=validation_end,
    )
    train_window = hourly.loc[(hourly.index >= train_start) & (hourly.index < train_end)]
    validation_window = hourly.loc[
        (hourly.index >= validation_start) & (hourly.index < validation_end)
    ]
    train = _longest_exact_hour_block(train_window)
    validation = _exact_hour_suffix(validation_window, expected_last=selection_ts - _BAR)
    if len(train) < math.ceil(cell.train_hours * minimum_completeness):
        return None
    if len(validation) < math.ceil(cell.validation_hours * minimum_completeness):
        return None

    first_liquidity = float(
        (validation[f"{first_symbol}:close"] * validation[f"{first_symbol}:volume"]).median()
    )
    second_liquidity = float(
        (validation[f"{second_symbol}:close"] * validation[f"{second_symbol}:volume"]).median()
    )
    if first_liquidity > second_liquidity:
        x_symbol, y_symbol = first_symbol, second_symbol
    elif second_liquidity > first_liquidity:
        x_symbol, y_symbol = second_symbol, first_symbol
    else:
        x_symbol, y_symbol = sorted((first_symbol, second_symbol))

    train_x_price = train[f"{x_symbol}:close"].to_numpy(dtype=float)
    train_y_price = train[f"{y_symbol}:close"].to_numpy(dtype=float)
    validation_x_price = validation[f"{x_symbol}:close"].to_numpy(dtype=float)
    validation_y_price = validation[f"{y_symbol}:close"].to_numpy(dtype=float)
    log_x = np.log(train_x_price)
    log_y = np.log(train_y_price)
    alpha, beta = _ols_alpha_beta(log_y, log_x)
    residual = log_y - alpha - beta * log_x
    train_mean = float(np.mean(residual))
    train_std = float(np.std(residual, ddof=0))
    validation_residual = np.log(validation_y_price) - alpha - beta * np.log(validation_x_price)
    validation_mean = float(np.mean(validation_residual))
    validation_std = float(np.std(validation_residual, ddof=0))
    normalized_y = train_y_price / train_y_price[0]
    normalized_x = train_x_price / train_x_price[0]
    ssd = float(np.square(normalized_y - normalized_x).mean())
    train_index = pd.DatetimeIndex(train.index)
    y_returns = _exact_hour_returns(log_y, train_index)
    x_returns = _exact_hour_returns(log_x, train_index)
    btc_returns = _exact_hour_returns(
        np.log(train[f"{btc_symbol}:close"].to_numpy(dtype=float)), train_index
    )
    correlation = float(np.corrcoef(y_returns, x_returns)[0, 1])
    midpoint = len(train) // 2
    _alpha_first, beta_first = _ols_alpha_beta(log_y[:midpoint], log_x[:midpoint])
    _alpha_second, beta_second = _ols_alpha_beta(log_y[midpoint:], log_x[midpoint:])
    beta_change = abs(beta_first - beta_second) / max(abs(beta), np.finfo(float).eps)
    _phi, half_life = _ar1_half_life(residual, train_index)
    weight_y = 1.0 / (1.0 + beta) if beta > 0.0 else float("nan")
    weight_x = beta / (1.0 + beta) if beta > 0.0 else float("nan")
    pair_returns = weight_y * y_returns - weight_x * x_returns
    btc_variance = float(np.var(btc_returns, ddof=1))
    pair_btc_beta = (
        abs(float(np.cov(pair_returns, btc_returns, ddof=1)[0, 1]) / btc_variance)
        if btc_variance > 0.0 and math.isfinite(weight_y)
        else float("inf")
    )
    mean_shift = abs(validation_mean - train_mean) / train_std if train_std > 0.0 else float("inf")
    std_ratio = validation_std / train_std if train_std > 0.0 else float("inf")
    crossings = _mean_crossings(
        validation_residual, validation_mean, pd.DatetimeIndex(validation.index)
    )
    pvalue = _engle_granger_p(log_y, log_x)
    return _PairCandidate(
        pair_id=_pair_id(first_symbol, second_symbol),
        y_symbol=y_symbol,
        x_symbol=x_symbol,
        alpha=alpha,
        beta=beta,
        validation_mean=validation_mean,
        validation_std=validation_std,
        engle_granger_p=pvalue,
        normalized_price_ssd=ssd,
        training_correlation=correlation,
        half_life_hours=half_life,
        pair_btc_beta=pair_btc_beta,
        gross_weight_y=weight_y,
        gross_weight_x=weight_x,
        beta_relative_change=float(beta_change),
        validation_mean_shift=float(mean_shift),
        validation_std_ratio=float(std_ratio),
        validation_crossings=crossings,
        train_start=train_start.to_pydatetime(),
        train_end=train_end.to_pydatetime(),
        validation_start=validation_start.to_pydatetime(),
        validation_end=validation_end.to_pydatetime(),
    )


def _is_first_monday_utc(value: pd.Timestamp) -> bool:
    return (
        value.tzinfo is not None
        and value.utcoffset() == timedelta(0)
        and value.day <= 7
        and value.dayofweek == 0
        and value.hour == 0
        and value.minute == 0
        and value.second == 0
    )


def _select_at_normalized(
    frames: Mapping[str, pd.DataFrame],
    universe: Sequence[str],
    cell: PairCell,
    selection_ts: pd.Timestamp,
    *,
    snapshot_sha256: str,
    btc_symbol: str,
    minimum_completeness: float,
) -> tuple[PairModel, ...]:
    data_candidates: list[_PairCandidate] = []
    for first_symbol, second_symbol in combinations(sorted(universe), 2):
        candidate = _candidate_from_pair(
            frames,
            first_symbol,
            second_symbol,
            cell,
            selection_ts,
            btc_symbol=btc_symbol,
            minimum_completeness=minimum_completeness,
        )
        if candidate is not None:
            data_candidates.append(candidate)
    if not data_candidates:
        return ()

    # Audit P0: Holm's family is every unordered data-eligible pair, before SSD filtering.
    adjusted = holm_adjusted_pvalues(
        {candidate.pair_id: candidate.engle_granger_p for candidate in data_candidates}
    )
    gatev_top = {
        candidate.pair_id
        for candidate in sorted(
            data_candidates,
            key=lambda item: (item.normalized_price_ssd, item.pair_id),
        )[:20]
    }
    eligible = [
        candidate
        for candidate in data_candidates
        if candidate.pair_id in gatev_top
        and adjusted[candidate.pair_id] <= 0.05
        and math.isfinite(candidate.training_correlation)
        and math.isfinite(candidate.half_life_hours)
        and math.isfinite(candidate.pair_btc_beta)
        and candidate.validation_std > 0.0
        and candidate.training_correlation >= 0.75
        and 0.25 <= candidate.beta <= 4.0
        and cell.half_life_min_hours <= candidate.half_life_hours <= cell.half_life_max_hours
        and candidate.beta_relative_change <= 0.20
        and candidate.validation_mean_shift <= 0.50
        and 0.50 <= candidate.validation_std_ratio <= 1.50
        and candidate.validation_crossings >= 4
        and candidate.pair_btc_beta <= 0.15
    ]
    selection_dt = selection_ts.to_pydatetime()
    eligible.sort(
        key=lambda item: (
            adjusted[item.pair_id],
            item.normalized_price_ssd,
            deterministic_pair_tiebreak(
                snapshot_sha256, item.pair_id, cell.candidate_id, selection_dt
            ),
        )
    )
    selected: list[_PairCandidate] = []
    used_symbols: set[str] = set()
    for candidate in eligible:
        if candidate.y_symbol in used_symbols or candidate.x_symbol in used_symbols:
            continue
        selected.append(candidate)
        used_symbols.update((candidate.y_symbol, candidate.x_symbol))
        if len(selected) == 3:
            break
    return tuple(
        PairModel(
            candidate_id=cell.candidate_id,
            pair_id=candidate.pair_id,
            selection_ts=selection_dt,
            y_symbol=candidate.y_symbol,
            x_symbol=candidate.x_symbol,
            alpha=candidate.alpha,
            beta=candidate.beta,
            validation_mean=candidate.validation_mean,
            validation_std=candidate.validation_std,
            engle_granger_p=candidate.engle_granger_p,
            holm_adjusted_p=adjusted[candidate.pair_id],
            normalized_price_ssd=candidate.normalized_price_ssd,
            training_correlation=candidate.training_correlation,
            half_life_hours=candidate.half_life_hours,
            pair_btc_beta=candidate.pair_btc_beta,
            gross_weight_y=candidate.gross_weight_y,
            gross_weight_x=candidate.gross_weight_x,
            train_start=candidate.train_start,
            train_end=candidate.train_end,
            validation_start=candidate.validation_start,
            validation_end=candidate.validation_end,
        )
        for candidate in selected
    )


def select_pairs_at_timestamp(
    frames: Mapping[str, pd.DataFrame],
    universe: Sequence[str],
    cell: PairCell,
    selection_ts: datetime | pd.Timestamp,
    *,
    snapshot_sha256: str,
    btc_symbol: str = "BTC/USDT",
    minimum_completeness: float = 0.95,
) -> tuple[PairModel, ...]:
    """Select at most three causal, deterministic, non-overlapping pairs."""

    clean = normalize_pair_frames(frames)
    parsed_ts = pd.Timestamp(selection_ts)
    if parsed_ts.tzinfo is None:
        raise ValueError("selection_ts must be timezone-aware UTC")
    parsed_ts = parsed_ts.tz_convert(UTC)
    if not _is_first_monday_utc(parsed_ts):
        raise ValueError("selection_ts must be the first Monday 00:00 UTC")
    symbols = tuple(sorted(set(universe)))
    if len(symbols) < 2 or btc_symbol in symbols:
        raise ValueError("universe needs two non-BTC symbols and must exclude BTC")
    missing = sorted(set(symbols).union({btc_symbol}).difference(clean))
    if missing:
        raise ValueError(f"frames missing required symbols: {missing}")
    if not 0.0 < minimum_completeness <= 1.0:
        raise ValueError("minimum_completeness must be in (0, 1]")
    return _select_at_normalized(
        clean,
        symbols,
        cell,
        parsed_ts,
        snapshot_sha256=snapshot_sha256,
        btc_symbol=btc_symbol,
        minimum_completeness=minimum_completeness,
    )


def first_monday_selections(
    start: datetime | pd.Timestamp, end: datetime | pd.Timestamp
) -> tuple[datetime, ...]:
    """Return every calendar first-Monday 00:00 UTC in ``[start, end)``."""

    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if start_ts.tzinfo is None or end_ts.tzinfo is None:
        raise ValueError("selection range must be timezone-aware UTC")
    start_ts = start_ts.tz_convert(UTC)
    end_ts = end_ts.tz_convert(UTC)
    if start_ts >= end_ts:
        raise ValueError("selection range must be increasing")
    result: list[datetime] = []
    for month in pd.period_range(
        start_ts.tz_localize(None).to_period("M"), end_ts.tz_localize(None).to_period("M"), freq="M"
    ):
        first = month.start_time.tz_localize(UTC)
        selection = first + pd.Timedelta(days=(7 - first.dayofweek) % 7)
        if start_ts <= selection < end_ts:
            result.append(selection.to_pydatetime())
    return tuple(result)


def select_pairs_monthly(
    frames: Mapping[str, pd.DataFrame],
    universe: Sequence[str],
    cell: PairCell,
    *,
    start: datetime | pd.Timestamp,
    end: datetime | pd.Timestamp,
    snapshot_sha256: str,
    btc_symbol: str = "BTC/USDT",
    minimum_completeness: float = 0.95,
) -> dict[datetime, tuple[PairModel, ...]]:
    """Select each calendar month and preserve explicit empty early months."""

    clean = normalize_pair_frames(frames)
    symbols = tuple(sorted(set(universe)))
    if len(symbols) < 2 or btc_symbol in symbols:
        raise ValueError("universe needs two non-BTC symbols and must exclude BTC")
    missing = sorted(set(symbols).union({btc_symbol}).difference(clean))
    if missing:
        raise ValueError(f"frames missing required symbols: {missing}")
    if not 0.0 < minimum_completeness <= 1.0:
        raise ValueError("minimum_completeness must be in (0, 1]")
    result: dict[datetime, tuple[PairModel, ...]] = {}
    for selection_dt in first_monday_selections(start, end):
        result[selection_dt] = _select_at_normalized(
            clean,
            symbols,
            cell,
            pd.Timestamp(selection_dt),
            snapshot_sha256=snapshot_sha256,
            btc_symbol=btc_symbol,
            minimum_completeness=minimum_completeness,
        )
    return result


def _funding_series(value: pd.Series | pd.DataFrame, *, symbol: str) -> pd.Series:
    if isinstance(value, pd.Series):
        series = value.copy()
        index = pd.DatetimeIndex(series.index)
    elif isinstance(value, pd.DataFrame):
        rate_column = "funding_rate" if "funding_rate" in value.columns else "rate"
        if rate_column not in value.columns:
            raise ValueError(f"{symbol}: funding needs funding_rate or rate")
        raw_index = value["ts"] if "ts" in value.columns else value.index
        index = pd.DatetimeIndex(raw_index)
        series = pd.Series(value[rate_column].to_numpy(), index=index)
    else:
        raise ValueError(f"{symbol}: funding must be a Series or DataFrame")
    if index.tz is None or any(ts.utcoffset() != timedelta(0) for ts in index):
        raise ValueError(f"{symbol}: funding timestamps must be timezone-aware UTC")
    index = index.tz_convert(UTC).floor("s")
    if index.has_duplicates or not index.is_monotonic_increasing:
        raise ValueError(f"{symbol}: effective funding timestamps must be unique and increasing")
    series.index = index
    series = pd.to_numeric(series, errors="coerce")
    if not np.isfinite(series.to_numpy(dtype=float)).all():
        raise ValueError(f"{symbol}: funding rates must be finite")
    return series.astype(float)


def _normalize_funding_mapping(
    funding: Mapping[str, pd.Series | pd.DataFrame],
) -> dict[str, pd.Series]:
    normalized: dict[str, pd.Series] = {}
    for raw_symbol, value in funding.items():
        symbol = _canonical_usdt_symbol(raw_symbol, label="funding")
        if symbol in normalized:
            raise ValueError(f"funding symbols collide after canonicalization: {symbol}")
        normalized[symbol] = _funding_series(value, symbol=symbol)
    return normalized


def _worst_known_payment_rate(
    rates: pd.Series, *, entry_ts: pd.Timestamp, side: Side
) -> float | None:
    # Strict cutoff: an event settling at the shared entry open was not safely
    # knowable before that fill, and the newly opened pair does not receive it.
    known = rates.loc[rates.index < entry_ts].tail(3)
    if len(known) < 3:
        return None
    direction = 1.0 if side == "long" else -1.0
    return max(float((known * direction).max()), 0.0)


def _known_funding_cadence_hours(rates: pd.Series, *, entry_ts: pd.Timestamp) -> float:
    known_index = rates.index[rates.index < entry_ts][-30:]
    if len(known_index) < 2:
        return 8.0
    intervals = np.asarray(
        [
            (known_index[offset] - known_index[offset - 1]).total_seconds() / 3_600.0
            for offset in range(1, len(known_index))
        ],
        dtype=float,
    )
    positive = intervals[intervals > 0.0]
    return float(positive.min()) if positive.size else 8.0


def adverse_funding_for_entry(
    funding: Mapping[str, pd.Series | pd.DataFrame],
    model: PairModel,
    *,
    entry_ts: datetime | pd.Timestamp,
    y_side: Side,
    x_side: Side,
    max_hold_hours: int,
) -> float | None:
    """Return conservative max-hold funding burden, or ``None`` without history."""

    normalized = _normalize_funding_mapping(funding)
    return _adverse_funding_from_normalized(
        normalized,
        model,
        entry_ts=entry_ts,
        y_side=y_side,
        x_side=x_side,
        max_hold_hours=max_hold_hours,
    )


def _adverse_funding_from_normalized(
    funding: Mapping[str, pd.Series],
    model: PairModel,
    *,
    entry_ts: datetime | pd.Timestamp,
    y_side: Side,
    x_side: Side,
    max_hold_hours: int,
) -> float | None:
    if model.y_symbol not in funding or model.x_symbol not in funding:
        return None
    parsed_entry = pd.Timestamp(entry_ts)
    if parsed_entry.tzinfo is None:
        raise ValueError("entry_ts must be timezone-aware UTC")
    parsed_entry = parsed_entry.tz_convert(UTC)
    y_rates = funding[model.y_symbol]
    x_rates = funding[model.x_symbol]
    worst_y = _worst_known_payment_rate(y_rates, entry_ts=parsed_entry, side=y_side)
    worst_x = _worst_known_payment_rate(x_rates, entry_ts=parsed_entry, side=x_side)
    if worst_y is None or worst_x is None:
        return None
    hold_hours = _positive_int("max_hold_hours", max_hold_hours)
    y_horizon_events = math.ceil(
        hold_hours / _known_funding_cadence_hours(y_rates, entry_ts=parsed_entry)
    )
    x_horizon_events = math.ceil(
        hold_hours / _known_funding_cadence_hours(x_rates, entry_ts=parsed_entry)
    )
    return float(
        model.gross_weight_y * worst_y * y_horizon_events
        + model.gross_weight_x * worst_x * x_horizon_events
    )


def economic_entry_requirement(adverse_funding: float) -> float:
    """Return the frozen 1.5x C2/H break-even threshold."""

    funding = _finite("adverse_funding", adverse_funding)
    if funding < 0.0:
        raise ValueError("adverse_funding must be >= 0")
    # Audit P0: C2 stresses funding 2x; H halves positive payoff but does not
    # scale costs or funding.
    return float(1.5 * max(0.0114 + 2.0 * funding, 2.0 * (0.0057 + funding)))


def _model_z(model: PairModel, y_close: np.ndarray, x_close: np.ndarray) -> np.ndarray:
    spread = np.log(y_close) - model.alpha - model.beta * np.log(x_close)
    return (spread - model.validation_mean) / model.validation_std


def generate_pair_entry_intents(
    frames: Mapping[str, pd.DataFrame],
    funding: Mapping[str, pd.Series | pd.DataFrame],
    cell: PairCell,
    selections: Mapping[datetime, Sequence[PairModel]],
    *,
    btc_symbol: str = "BTC/USDT",
) -> tuple[PairEntryIntent, ...]:
    """Generate economic-gated hourly intents from frozen monthly models.

    The function does not know portfolio episode state.  Atomic occupancy and
    post-exit cooldown are therefore engine responsibilities; thresholds and the
    cooldown duration travel on every immutable intent.
    """

    clean = normalize_pair_frames(frames)
    normalized_funding = _normalize_funding_mapping(funding)
    ordered_selections: list[tuple[pd.Timestamp, tuple[PairModel, ...]]] = []
    for raw_ts, raw_models in selections.items():
        selection_ts = pd.Timestamp(raw_ts)
        if selection_ts.tzinfo is None:
            raise ValueError("selection timestamps must be timezone-aware UTC")
        selection_ts = selection_ts.tz_convert(UTC)
        if not _is_first_monday_utc(selection_ts):
            raise ValueError("selection timestamps must be first-Monday 00:00 UTC")
        models = tuple(raw_models)
        if any(model.selection_ts != selection_ts.to_pydatetime() for model in models):
            raise ValueError("model selection_ts does not match selection ledger key")
        if any(model.candidate_id != cell.candidate_id for model in models):
            raise ValueError("selection ledger contains a model for another cell")
        ordered_selections.append((selection_ts, models))
    ordered_selections.sort(key=lambda item: item[0])
    if not ordered_selections:
        return ()

    intents: list[PairEntryIntent] = []
    latest_label = max(frame.index[-1] for frame in clean.values())
    for selection_index, (selection_ts, models) in enumerate(ordered_selections):
        active_end = (
            ordered_selections[selection_index + 1][0]
            if selection_index + 1 < len(ordered_selections)
            else latest_label + _BAR
        )
        for model in models:
            if btc_symbol in {model.y_symbol, model.x_symbol}:
                raise ValueError("BTC reference cannot be traded")
            missing = {model.y_symbol, model.x_symbol, btc_symbol}.difference(clean)
            if missing:
                raise ValueError(f"frames missing model symbols: {sorted(missing)}")
            common = clean[model.y_symbol].index.intersection(
                clean[model.x_symbol].index, sort=False
            )
            common = common.intersection(clean[btc_symbol].index, sort=False).sort_values()
            common_set = set(common)
            decisions = common[
                (common.minute == 45)
                & (common + _BAR >= selection_ts)
                & (common + _BAR < active_end)
            ]
            for decision_ts in decisions:
                history = pd.date_range(decision_ts - 3 * _BAR, decision_ts, freq=_BAR, tz=UTC)
                entry_ts = decision_ts + _BAR
                if any(timestamp not in common_set for timestamp in history):
                    continue
                # Atomic next-open requirement applies to both tradable legs.
                if (
                    entry_ts not in clean[model.y_symbol].index
                    or entry_ts not in clean[model.x_symbol].index
                ):
                    continue
                y_close = clean[model.y_symbol].loc[history, "close"].to_numpy(dtype=float)
                x_close = clean[model.x_symbol].loc[history, "close"].to_numpy(dtype=float)
                z_values = _model_z(model, y_close, x_close)
                high = bool(np.all(z_values >= cell.entry_abs_z))
                low = bool(np.all(z_values <= -cell.entry_abs_z))
                if not high and not low:
                    continue
                entry_z = float(z_values[-1])
                if abs(entry_z) >= cell.disaster_abs_z:
                    continue
                y_side: Side = "short" if high else "long"
                x_side: Side = "long" if high else "short"
                funding_cost = _adverse_funding_from_normalized(
                    normalized_funding,
                    model,
                    entry_ts=entry_ts,
                    y_side=y_side,
                    x_side=x_side,
                    max_hold_hours=cell.max_hold_hours,
                )
                if funding_cost is None:
                    continue
                expected = float(
                    (abs(entry_z) - cell.exit_abs_z) * model.validation_std / (1.0 + model.beta)
                )
                required = economic_entry_requirement(funding_cost)
                if expected < required:
                    continue
                intents.append(
                    PairEntryIntent(
                        candidate_id=cell.candidate_id,
                        pair_id=model.pair_id,
                        selection_ts=model.selection_ts,
                        decision_ts=decision_ts.to_pydatetime(),
                        entry_ts=entry_ts.to_pydatetime(),
                        y_symbol=model.y_symbol,
                        x_symbol=model.x_symbol,
                        y_side=y_side,
                        x_side=x_side,
                        z_score=entry_z,
                        alpha=model.alpha,
                        beta=model.beta,
                        validation_mean=model.validation_mean,
                        validation_std=model.validation_std,
                        gross_weight_y=model.gross_weight_y,
                        gross_weight_x=model.gross_weight_x,
                        entry_abs_z=cell.entry_abs_z,
                        exit_abs_z=cell.exit_abs_z,
                        disaster_abs_z=cell.disaster_abs_z,
                        max_hold_hours=cell.max_hold_hours,
                        cooldown_hours=cell.cooldown_hours,
                        expected_convergence_return=expected,
                        adverse_funding=funding_cost,
                        stressed_required_return=required,
                    )
                )
    return tuple(sorted(intents, key=lambda item: (item.entry_ts, item.pair_id, item.candidate_id)))


def holm_adjusted_pvalues(pvalues: Mapping[str, float]) -> dict[str, float]:
    """Return Holm step-down adjusted p-values with deterministic key ties."""

    checked: list[tuple[str, float]] = []
    for key, raw in pvalues.items():
        value = _finite(f"pvalue[{key}]", raw)
        if not 0.0 <= value <= 1.0:
            raise ValueError("p-values must be in [0, 1]")
        checked.append((str(key), value))
    ordered = sorted(checked, key=lambda item: (item[1], item[0]))
    count = len(ordered)
    result: dict[str, float] = {}
    running = 0.0
    for rank, (key, value) in enumerate(ordered):
        running = max(running, (count - rank) * value)
        result[key] = min(running, 1.0)
    return result


def deterministic_pair_tiebreak(
    snapshot_sha256: str, pair_id: str, candidate_id: str, selection_ts: datetime
) -> str:
    selection_ts = _utc_datetime("selection_ts", selection_ts)
    payload = f"{snapshot_sha256}|{pair_id}|{candidate_id}|{selection_ts.isoformat()}"
    return hashlib.sha256(payload.encode()).hexdigest()


__all__ = [
    "PREREGISTERED_PAIR_CELLS",
    "PairCell",
    "PairEntryIntent",
    "PairModel",
    "adverse_funding_for_entry",
    "deterministic_pair_tiebreak",
    "economic_entry_requirement",
    "first_monday_selections",
    "generate_pair_entry_intents",
    "holm_adjusted_pvalues",
    "normalize_pair_frames",
    "select_pairs_at_timestamp",
    "select_pairs_monthly",
]
