"""Pre-registered cross-sectional funding-carry feasibility backtest.

This module deliberately implements only the PRIMARY configuration registered in
``memory/researcher/hypotheses/2026-07-07-xs-carry-funding-dispersion-weekly-dedicated-book.md``:

* Monday 00:00 UTC rebalance;
* trailing seven-day funding-rate rank;
* top/bottom ``k=3``;
* one-for-one spot/perpetual hedge per selected symbol;
* conservative full-turnover fees/slippage and short-spot borrow;
* rank-permutation and leave-one-symbol-out checks.

The local dataset contains a fixed 19-symbol survivor universe rather than a
delisting-inclusive historical universe.  Consequently every result produced by
this module is labelled ``FEASIBILITY_NOT_PROMOTION`` even if numerical gates pass.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import pandas as pd

CALENDAR_DAYS_PER_YEAR = 365.2425
STATUS = "FEASIBILITY_NOT_PROMOTION"


def _utc_timestamp(value: str | pd.Timestamp) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _json_scalar(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        value = float(value)
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def _json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return _json_scalar(value)


@dataclass(frozen=True)
class XSCarryConfig:
    """Frozen PRIMARY feasibility configuration.

    Each selected symbol receives ``1 / (2*k)`` equity notional on both its
    perpetual and spot legs.  The resulting book has 1x aggregate perpetual
    notional, 1x aggregate spot notional, and 2x gross exposure while remaining
    delta-neutral per symbol.  The short-spot half therefore borrows 0.5x equity.
    """

    start: str | pd.Timestamp = "2022-01-01"
    end: str | pd.Timestamp = "2026-06-30"
    oos_start: str | pd.Timestamp = "2024-01-01"
    k: int = 3
    funding_score_lookback_days: int = 7
    rebalance_days: int = 7
    min_liquidity_usd: float = 50_000_000.0
    liquidity_window_days: int = 30
    min_liquidity_observations: int = 25
    min_funding_observations: int = 18
    perp_taker_fee_bps: float = 5.0
    spot_taker_fee_bps: float = 5.0
    slippage_bps_per_leg: float = 3.0
    borrow_apr: float = 0.15
    borrow_stress_apr: float = 0.25
    permutations: int = 500
    random_seed: int = 42

    def __post_init__(self) -> None:
        start = _utc_timestamp(self.start)
        end = _utc_timestamp(self.end)
        oos_start = _utc_timestamp(self.oos_start)
        if end <= start:
            raise ValueError("end must be after start")
        if not start <= oos_start <= end:
            raise ValueError("oos_start must fall inside the requested sample")
        if self.k < 1:
            raise ValueError("k must be positive")
        if self.funding_score_lookback_days != 7 or self.rebalance_days != 7:
            raise ValueError("PRIMARY feasibility is frozen to 7d score and 7d rebalance")
        if self.permutations < 1:
            raise ValueError("permutations must be positive")
        nonnegative = (
            self.min_liquidity_usd,
            self.perp_taker_fee_bps,
            self.spot_taker_fee_bps,
            self.slippage_bps_per_leg,
            self.borrow_apr,
            self.borrow_stress_apr,
        )
        if any(value < 0 for value in nonnegative):
            raise ValueError("liquidity, cost, and borrow inputs must be non-negative")

    @property
    def start_utc(self) -> pd.Timestamp:
        return _utc_timestamp(self.start)

    @property
    def end_utc(self) -> pd.Timestamp:
        return _utc_timestamp(self.end)

    @property
    def oos_start_utc(self) -> pd.Timestamp:
        return _utc_timestamp(self.oos_start)

    def canonical_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["start"] = self.start_utc.isoformat()
        payload["end"] = self.end_utc.isoformat()
        payload["oos_start"] = self.oos_start_utc.isoformat()
        payload["cost_turnover_assumption_pct"] = 100.0
        payload["pair_leg_notional_of_equity"] = 1.0 / (2.0 * self.k)
        return payload


def _normalise_market_frame(frame: pd.DataFrame, name: str) -> pd.DataFrame:
    required = {"symbol", "ts", "open", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"{name} missing columns: {sorted(missing)}")
    out = frame.loc[:, ["symbol", "ts", "open", "close", "volume"]].copy()
    out["symbol"] = (
        out["symbol"]
        .astype(str)
        .str.replace("/USDT:USDT", "", regex=False)
        .str.replace("/USDT", "", regex=False)
    )
    out["ts"] = pd.to_datetime(out["ts"], utc=True)
    for column in ("open", "close", "volume"):
        out[column] = pd.to_numeric(out[column], errors="coerce")
    out = out.dropna(subset=["symbol", "ts", "open", "close", "volume"])
    out = out[(out["open"] > 0) & (out["close"] > 0) & (out["volume"] >= 0)]
    return out.drop_duplicates(["symbol", "ts"], keep="last").sort_values(
        ["symbol", "ts"], ignore_index=True
    )


def _normalise_funding_frame(frame: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "ts", "funding_rate"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"funding missing columns: {sorted(missing)}")
    out = frame.loc[:, ["symbol", "ts", "funding_rate"]].copy()
    out["symbol"] = (
        out["symbol"]
        .astype(str)
        .str.replace("/USDT:USDT", "", regex=False)
        .str.replace("/USDT", "", regex=False)
    )
    out["ts"] = pd.to_datetime(out["ts"], utc=True)
    out["funding_rate"] = pd.to_numeric(out["funding_rate"], errors="coerce")
    out = out.dropna(subset=["symbol", "ts", "funding_rate"])
    return out.drop_duplicates(["symbol", "ts"], keep="last").sort_values(
        ["symbol", "ts"], ignore_index=True
    )


@dataclass(frozen=True)
class XSCarryData:
    """Normalised funding plus matching spot/perpetual daily OHLCV."""

    funding: pd.DataFrame
    spot: pd.DataFrame
    perp: pd.DataFrame
    source_metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "funding", _normalise_funding_frame(self.funding))
        object.__setattr__(self, "spot", _normalise_market_frame(self.spot, "spot"))
        object.__setattr__(self, "perp", _normalise_market_frame(self.perp, "perp"))
        if not self.symbols:
            raise ValueError("funding, spot, and perp have no common symbols")

    @property
    def symbols(self) -> tuple[str, ...]:
        common = set(self.funding["symbol"]) & set(self.spot["symbol"]) & set(self.perp["symbol"])
        return tuple(sorted(common))


@dataclass(frozen=True)
class XSCarryFeasibilityResult:
    status: str
    promotion_eligible: bool
    limitations: tuple[str, ...]
    config: Mapping[str, Any]
    coverage: Mapping[str, Any]
    metrics: Mapping[str, Any]
    gates: Mapping[str, Any]
    robustness: Mapping[str, Any]
    reproducibility: Mapping[str, Any]
    weekly_returns: pd.DataFrame = field(repr=False)

    def to_dict(self, *, include_weekly_returns: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "status": self.status,
            "promotion_eligible": self.promotion_eligible,
            "limitations": self.limitations,
            "config": self.config,
            "coverage": self.coverage,
            "metrics": self.metrics,
            "gates": self.gates,
            "robustness": self.robustness,
            "reproducibility": self.reproducibility,
        }
        if include_weekly_returns:
            payload["weekly_returns"] = self.weekly_returns.to_dict(orient="records")
        return _json_safe(payload)


def _first_monday_on_or_after(ts: pd.Timestamp) -> pd.Timestamp:
    day = ts.normalize()
    return day + pd.Timedelta(days=(7 - day.weekday()) % 7)


def _rebalance_intervals(config: XSCarryConfig) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    first = _first_monday_on_or_after(config.start_utc)
    last_start = config.end_utc - pd.Timedelta(days=config.rebalance_days)
    if first > last_start:
        return []
    starts = pd.date_range(first, last_start, freq="W-MON", tz="UTC")
    return [(start, start + pd.Timedelta(days=config.rebalance_days)) for start in starts]


def _lookup(matrix: pd.DataFrame, ts: pd.Timestamp, symbol: str) -> float:
    try:
        value = matrix.at[ts, symbol]
    except (KeyError, TypeError):
        return float("nan")
    return float(value) if pd.notna(value) else float("nan")


def _prepare_weekly_panel(data: XSCarryData, config: XSCarryConfig) -> pd.DataFrame:
    symbols = list(data.symbols)
    spot = data.spot[data.spot["symbol"].isin(symbols)].copy()
    perp = data.perp[data.perp["symbol"].isin(symbols)].copy()
    funding = data.funding[data.funding["symbol"].isin(symbols)].copy()

    spot["quote_volume"] = spot["close"] * spot["volume"]
    spot["liquidity_usd_30d_median"] = spot.groupby("symbol", sort=False)["quote_volume"].transform(
        lambda values: (
            values.rolling(
                config.liquidity_window_days,
                min_periods=config.min_liquidity_observations,
            )
            .median()
            .shift(1)
        )
    )

    spot_open = spot.pivot(index="ts", columns="symbol", values="open")
    perp_open = perp.pivot(index="ts", columns="symbol", values="open")
    liquidity = spot.pivot(index="ts", columns="symbol", values="liquidity_usd_30d_median")

    rows: list[dict[str, Any]] = []
    for start, end in _rebalance_intervals(config):
        history_start = start - pd.Timedelta(days=config.funding_score_lookback_days)
        trailing = funding[(funding["ts"] >= history_start) & (funding["ts"] < start)]
        # Enter immediately after the rebalance timestamp settlement and hold
        # through the next Monday settlement: (start, end] gives 21 normal 8h events.
        holding = funding[(funding["ts"] > start) & (funding["ts"] <= end)]
        score = trailing.groupby("symbol")["funding_rate"].agg(["mean", "count"])
        realised = holding.groupby("symbol")["funding_rate"].agg(["sum", "count"])

        btc_start = _lookup(spot_open, start, "BTC")
        btc_end = _lookup(spot_open, end, "BTC")
        btc_return = (
            btc_end / btc_start - 1.0
            if math.isfinite(btc_start) and math.isfinite(btc_end) and btc_start > 0
            else float("nan")
        )
        for symbol in symbols:
            spot_start = _lookup(spot_open, start, symbol)
            spot_end = _lookup(spot_open, end, symbol)
            perp_start = _lookup(perp_open, start, symbol)
            perp_end = _lookup(perp_open, end, symbol)
            rows.append(
                {
                    "start": start,
                    "end": end,
                    "symbol": symbol,
                    "score": float(score.at[symbol, "mean"]) if symbol in score.index else np.nan,
                    "score_count": int(score.at[symbol, "count"]) if symbol in score.index else 0,
                    "funding_sum": float(realised.at[symbol, "sum"])
                    if symbol in realised.index
                    else np.nan,
                    "funding_count": int(realised.at[symbol, "count"])
                    if symbol in realised.index
                    else 0,
                    "spot_return": spot_end / spot_start - 1.0
                    if math.isfinite(spot_start) and math.isfinite(spot_end) and spot_start > 0
                    else np.nan,
                    "perp_return": perp_end / perp_start - 1.0
                    if math.isfinite(perp_start) and math.isfinite(perp_end) and perp_start > 0
                    else np.nan,
                    "liquidity_usd_30d_median": _lookup(liquidity, start, symbol),
                    "btc_return": btc_return,
                }
            )
    return pd.DataFrame(rows)


def _complete_rows(group: pd.DataFrame, config: XSCarryConfig) -> pd.DataFrame:
    required = (
        group["score"].notna()
        & group["funding_sum"].notna()
        & group["spot_return"].notna()
        & group["perp_return"].notna()
        & (group["score_count"] >= config.min_funding_observations)
        & (group["funding_count"] >= config.min_funding_observations)
    )
    return group.loc[required].copy()


def _eligible_rows(group: pd.DataFrame, config: XSCarryConfig) -> pd.DataFrame:
    complete = _complete_rows(group, config)
    if config.min_liquidity_usd > 0:
        complete = complete[
            complete["liquidity_usd_30d_median"].notna()
            & (complete["liquidity_usd_30d_median"] >= config.min_liquidity_usd)
        ]
    return complete


def _ranked_sides(
    eligible: pd.DataFrame,
    config: XSCarryConfig,
    rng: np.random.Generator | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if rng is None:
        ranked = eligible.sort_values(["score", "symbol"], ascending=[False, True])
        top = ranked.head(config.k)
        # Select the opposite tail of one complete ranking so ties cannot put the
        # same symbol on both sides.  Re-sort the selected tail for readable low→high output.
        bottom = ranked.tail(config.k).sort_values(["score", "symbol"], ascending=[True, True])
        return tuple(top["symbol"]), tuple(bottom["symbol"])
    symbols = np.asarray(sorted(eligible["symbol"].astype(str)), dtype=object)
    ranking = rng.permutation(symbols)
    return tuple(str(value) for value in ranking[: config.k]), tuple(
        str(value) for value in ranking[-config.k :]
    )


def _book_turnover(
    previous: Mapping[str, float] | None,
    current: Mapping[str, float],
) -> float:
    if previous is None:
        return 1.0
    symbols = set(previous) | set(current)
    return 0.5 * sum(
        abs(current.get(symbol, 0.0) - previous.get(symbol, 0.0)) for symbol in symbols
    )


def _construct_weekly_returns(
    panel: pd.DataFrame,
    config: XSCarryConfig,
    *,
    excluded_symbols: Iterable[str] = (),
    rng: np.random.Generator | None = None,
) -> pd.DataFrame:
    excluded = set(excluded_symbols)
    period_rows: list[dict[str, Any]] = []
    previous_weights: dict[str, float] | None = None
    leg_weight = 1.0 / (2.0 * config.k)

    if panel.empty:
        return pd.DataFrame()
    for (_, _), raw_group in panel.groupby(["start", "end"], sort=True):
        group = raw_group[~raw_group["symbol"].isin(excluded)]
        complete = _complete_rows(group, config)
        # Too few complete observations means the source cannot price the book
        # (for example after local perpetual history ends), so the week is outside
        # the effective sample rather than a fabricated zero-return observation.
        if len(complete) < 2 * config.k:
            continue
        eligible = _eligible_rows(group, config)
        if len(eligible) < 2 * config.k:
            # Complete inputs exist but the frozen liquidity gate leaves too few
            # names.  Hold cash rather than silently shrinking k.  This preserves
            # the calendar-week return sequence and makes the constraint visible.
            current_weights: dict[str, float] = {}
            turnover = _book_turnover(previous_weights, current_weights)
            previous_weights = current_weights
            period_rows.append(
                {
                    "start": raw_group["start"].iloc[0],
                    "end": raw_group["end"].iloc[0],
                    "top_symbols": (),
                    "bottom_symbols": (),
                    "eligible_symbols": len(eligible),
                    "funding_settlements_min": int(complete["funding_count"].min()),
                    "funding_score_spread": np.nan,
                    "realised_funding_spread": np.nan,
                    "funding_return": 0.0,
                    "hedged_price_return": 0.0,
                    "gross_return": 0.0,
                    "trading_cost": 0.0,
                    "borrow_cost": 0.0,
                    "stress_borrow_cost": 0.0,
                    "net_return": 0.0,
                    "stress_net_return": 0.0,
                    "realized_turnover": turnover,
                    "cost_turnover_assumption": 0.0,
                    "btc_return": float(raw_group["btc_return"].iloc[0]),
                    "book_active": False,
                }
            )
            continue
        top_symbols, bottom_symbols = _ranked_sides(eligible, config, rng)
        # The deterministic rank cannot overlap when N >= 2k.  Keep this guard
        # explicit because accidental overlap would double-count a hedge pair.
        if set(top_symbols) & set(bottom_symbols):
            raise RuntimeError("top and bottom funding books overlap")

        selected = eligible.set_index("symbol").loc[list(top_symbols + bottom_symbols)]
        perp_direction = {symbol: -1.0 for symbol in top_symbols}
        perp_direction.update({symbol: 1.0 for symbol in bottom_symbols})
        current_weights = {
            symbol: direction * leg_weight for symbol, direction in perp_direction.items()
        }

        hedged_price_return = 0.0
        funding_return = 0.0
        for symbol, direction in perp_direction.items():
            row = selected.loc[symbol]
            hedged_price_return += (
                leg_weight * direction * (float(row["perp_return"]) - float(row["spot_return"]))
            )
            # A long perp pays positive funding; a short perp receives it.
            funding_return += leg_weight * -direction * float(row["funding_sum"])

        gross_return = hedged_price_return + funding_return
        period_days = float((raw_group["end"].iloc[0] - raw_group["start"].iloc[0]).days)
        perp_notional = len(perp_direction) * leg_weight
        spot_notional = perp_notional
        trading_cost = (
            perp_notional * 2.0 * config.perp_taker_fee_bps / 10_000.0
            + spot_notional * 2.0 * config.spot_taker_fee_bps / 10_000.0
            + (perp_notional + spot_notional) * config.slippage_bps_per_leg / 10_000.0
        )
        short_spot_notional = len(bottom_symbols) * leg_weight
        borrow_cost = config.borrow_apr * short_spot_notional * period_days / CALENDAR_DAYS_PER_YEAR
        stress_borrow_cost = (
            config.borrow_stress_apr * short_spot_notional * period_days / CALENDAR_DAYS_PER_YEAR
        )
        raw_funding_spread = float(
            selected.loc[list(top_symbols), "funding_sum"].mean()
            - selected.loc[list(bottom_symbols), "funding_sum"].mean()
        )
        turnover = _book_turnover(previous_weights, current_weights)
        previous_weights = current_weights
        period_rows.append(
            {
                "start": raw_group["start"].iloc[0],
                "end": raw_group["end"].iloc[0],
                "top_symbols": top_symbols,
                "bottom_symbols": bottom_symbols,
                "eligible_symbols": len(eligible),
                "funding_settlements_min": int(selected["funding_count"].min()),
                "funding_score_spread": float(
                    selected.loc[list(top_symbols), "score"].mean()
                    - selected.loc[list(bottom_symbols), "score"].mean()
                ),
                "realised_funding_spread": raw_funding_spread,
                "funding_return": funding_return,
                "hedged_price_return": hedged_price_return,
                "gross_return": gross_return,
                "trading_cost": trading_cost,
                "borrow_cost": borrow_cost,
                "stress_borrow_cost": stress_borrow_cost,
                "net_return": gross_return - trading_cost - borrow_cost,
                "stress_net_return": gross_return - trading_cost - stress_borrow_cost,
                "realized_turnover": turnover,
                "cost_turnover_assumption": 1.0,
                "btc_return": float(raw_group["btc_return"].iloc[0]),
                "book_active": True,
            }
        )
    return pd.DataFrame(period_rows)


def build_weekly_returns(
    data: XSCarryData,
    config: XSCarryConfig,
    *,
    excluded_symbols: Iterable[str] = (),
) -> pd.DataFrame:
    """Build observed PRIMARY weekly returns without robustness resampling."""

    panel = _prepare_weekly_panel(data, config)
    return _construct_weekly_returns(panel, config, excluded_symbols=excluded_symbols)


def newey_west_tstat(returns: pd.Series, max_lag: int | None = None) -> tuple[float, int]:
    """Newey-West/HAC t-statistic for the mean of a weekly return series."""

    values = pd.to_numeric(returns, errors="coerce").dropna().to_numpy(dtype=float)
    n_obs = len(values)
    if n_obs < 2:
        return float("nan"), 0
    if max_lag is None:
        max_lag = max(1, math.floor(4.0 * (n_obs / 100.0) ** (2.0 / 9.0)))
    max_lag = min(max(int(max_lag), 0), n_obs - 1)
    residuals = values - values.mean()
    long_run_variance = float(np.dot(residuals, residuals) / n_obs)
    for lag in range(1, max_lag + 1):
        weight = 1.0 - lag / (max_lag + 1.0)
        autocovariance = float(np.dot(residuals[lag:], residuals[:-lag]) / n_obs)
        long_run_variance += 2.0 * weight * autocovariance
    if long_run_variance <= 0:
        if values.mean() == 0:
            return 0.0, max_lag
        return math.copysign(float("inf"), values.mean()), max_lag
    standard_error = math.sqrt(long_run_variance / n_obs)
    return float(values.mean() / standard_error), max_lag


def summarize_returns(periods: pd.DataFrame, *, return_col: str) -> dict[str, float | int]:
    """Compute compounded, equity-base, and calendar-annualized weekly metrics."""

    required = {"start", "end", return_col}
    if periods.empty or not required.issubset(periods.columns):
        return {
            "annualized_return_pct": float("nan"),
            "calendar_sharpe": float("nan"),
            "nw_tstat_weekly": float("nan"),
            "nw_max_lag": 0,
            "maxdd_equity_base_pct": float("nan"),
            "rho_weekly_to_btc": float("nan"),
            "n_periods": 0,
        }
    frame = periods.dropna(subset=[return_col]).sort_values("start").copy()
    returns = pd.to_numeric(frame[return_col], errors="coerce").dropna()
    if returns.empty:
        return summarize_returns(pd.DataFrame(), return_col=return_col)
    if (returns <= -1.0).any():
        annualized_return = -1.0
    else:
        terminal_equity = float((1.0 + returns).prod())
        elapsed_days = max(float((frame["end"].iloc[-1] - frame["start"].iloc[0]).days), 1.0)
        annualized_return = terminal_equity ** (CALENDAR_DAYS_PER_YEAR / elapsed_days) - 1.0
    period_days = pd.to_datetime(frame["end"], utc=True) - pd.to_datetime(frame["start"], utc=True)
    median_days = max(float(period_days.dt.total_seconds().median() / 86_400.0), 1.0)
    standard_deviation = float(returns.std(ddof=1))
    calendar_sharpe = (
        float(returns.mean() / standard_deviation * math.sqrt(CALENDAR_DAYS_PER_YEAR / median_days))
        if len(returns) >= 2 and standard_deviation > 0
        else float("nan")
    )
    equity = np.concatenate(([1.0], np.cumprod(1.0 + returns.to_numpy(dtype=float))))
    drawdowns = equity / np.maximum.accumulate(equity) - 1.0
    max_drawdown = abs(float(np.min(drawdowns)))
    nw_tstat, nw_lag = newey_west_tstat(returns)
    rho = float("nan")
    if "btc_return" in frame.columns:
        paired = frame[[return_col, "btc_return"]].dropna()
        if (
            len(paired) >= 2
            and paired[return_col].std(ddof=1) > 0
            and paired["btc_return"].std(ddof=1) > 0
        ):
            rho = float(paired[return_col].corr(paired["btc_return"]))
    return {
        "annualized_return_pct": annualized_return * 100.0,
        "calendar_sharpe": calendar_sharpe,
        "nw_tstat_weekly": nw_tstat,
        "nw_max_lag": nw_lag,
        "maxdd_equity_base_pct": max_drawdown * 100.0,
        "rho_weekly_to_btc": rho,
        "n_periods": len(returns),
    }


def _permutation_from_panel(
    panel: pd.DataFrame,
    config: XSCarryConfig,
    observed_periods: pd.DataFrame,
) -> dict[str, Any]:
    observed_statistic = float(observed_periods["net_return"].mean())
    rng = np.random.default_rng(config.random_seed)
    null_statistics = np.empty(config.permutations, dtype=float)
    for index in range(config.permutations):
        permuted = _construct_weekly_returns(panel, config, rng=rng)
        null_statistics[index] = float(permuted["net_return"].mean())
    exceedances = int(np.sum(null_statistics >= observed_statistic))
    pvalue = (exceedances + 1.0) / (config.permutations + 1.0)
    return {
        "pvalue": float(pvalue),
        "observed_mean_weekly_return": observed_statistic,
        "null_mean_weekly_return": float(np.mean(null_statistics)),
        "null_std_weekly_return": float(np.std(null_statistics, ddof=1))
        if len(null_statistics) > 1
        else 0.0,
        "null_95pct_weekly_return": float(np.quantile(null_statistics, 0.95)),
        "exceedances": exceedances,
        "n_permutations": config.permutations,
        "random_seed": config.random_seed,
        "statistic": "mean net weekly return",
    }


def funding_rank_permutation_pvalue(
    data: XSCarryData,
    config: XSCarryConfig,
    observed_periods: pd.DataFrame | None = None,
) -> dict[str, Any]:
    """One-sided rank-permutation p-value with the Phipson-Smyth +1 correction."""

    panel = _prepare_weekly_panel(data, config)
    if observed_periods is None:
        observed_periods = _construct_weekly_returns(panel, config)
    if observed_periods.empty:
        raise ValueError("no observed weekly periods available for permutation")
    return _permutation_from_panel(panel, config, observed_periods)


def _canonical_frame_bytes(frame: pd.DataFrame) -> bytes:
    canonical = frame.copy()
    canonical = canonical.reindex(sorted(canonical.columns), axis=1)
    sort_columns = [column for column in ("symbol", "ts") if column in canonical.columns]
    if sort_columns:
        canonical = canonical.sort_values(sort_columns, ignore_index=True)
    if "ts" in canonical.columns:
        canonical["ts"] = pd.to_datetime(canonical["ts"], utc=True).dt.strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )
    return canonical.to_csv(
        index=False,
        lineterminator="\n",
        float_format="%.17g",
    ).encode("utf-8")


def reproducibility_hashes(data: XSCarryData, config: XSCarryConfig) -> dict[str, Any]:
    frame_hashes: dict[str, str] = {}
    combined = hashlib.sha256()
    for name, frame in (("funding", data.funding), ("spot", data.spot), ("perp", data.perp)):
        digest = hashlib.sha256(_canonical_frame_bytes(frame)).hexdigest()
        frame_hashes[name] = digest
        combined.update(name.encode("utf-8"))
        combined.update(digest.encode("ascii"))
    config_json = json.dumps(
        config.canonical_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    try:
        git_hash = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        git_hash = "UNAVAILABLE"
    return {
        "git_hash": git_hash,
        "data_hash_sha256": combined.hexdigest(),
        "data_component_hashes_sha256": frame_hashes,
        "config_hash_sha256": hashlib.sha256(config_json).hexdigest(),
        "hash_method": "SHA256(canonical sorted UTF-8 CSV inputs); combined hash over component digests",
        "source_metadata": dict(data.source_metadata),
    }


def _frame_range(frame: pd.DataFrame) -> dict[str, Any]:
    return {
        "rows": len(frame),
        "symbols": int(frame["symbol"].nunique()),
        "min_ts": frame["ts"].min(),
        "max_ts": frame["ts"].max(),
    }


def _coverage(
    data: XSCarryData, config: XSCarryConfig, periods: pd.DataFrame, panel: pd.DataFrame
) -> dict[str, Any]:
    ranges = {
        "funding": _frame_range(data.funding),
        "spot": _frame_range(data.spot),
        "perp": _frame_range(data.perp),
    }
    latest = {name: values["max_ts"] for name, values in ranges.items()}
    latest_values = [value for value in latest.values() if pd.notna(value)]
    mismatch_days = (
        float((max(latest_values) - min(latest_values)).total_seconds() / 86_400.0)
        if latest_values
        else float("nan")
    )
    attempted = int(panel["start"].nunique()) if not panel.empty else 0
    used = len(periods)
    active = int(periods["book_active"].sum()) if used else 0
    return {
        "requested_start": config.start_utc,
        "requested_end": config.end_utc,
        "effective_start": periods["start"].min() if used else None,
        "effective_end": periods["end"].max() if used else None,
        "oos_start": config.oos_start_utc,
        "universe": data.symbols,
        "universe_size": len(data.symbols),
        "delisting_inclusive": False,
        "input_ranges": ranges,
        "freshness_mismatch_days": mismatch_days,
        "attempted_rebalances": attempted,
        "data_available_rebalances": used,
        "active_book_rebalances": active,
        "cash_due_liquidity_rebalances": used - active,
        "unavailable_input_rebalances": attempted - used,
        "median_eligible_symbols_weekly": float(periods["eligible_symbols"].median())
        if used
        else float("nan"),
        "minimum_eligible_symbols_weekly": int(periods["eligible_symbols"].min()) if used else 0,
    }


def _gate(value: float, operator: str, threshold: float) -> dict[str, Any]:
    passed = False
    if math.isfinite(value):
        if operator == ">":
            passed = value > threshold
        elif operator == "<":
            passed = value < threshold
        elif operator == "abs<":
            passed = abs(value) < threshold
        else:
            raise ValueError(f"unsupported gate operator: {operator}")
    return {"value": value, "operator": operator, "threshold": threshold, "pass": passed}


def run_xs_carry_feasibility(
    data: XSCarryData,
    config: XSCarryConfig | None = None,
) -> XSCarryFeasibilityResult:
    """Run PRIMARY feasibility, robustness checks, gates, and reproducibility hashes."""

    config = config or XSCarryConfig()
    panel = _prepare_weekly_panel(data, config)
    periods = _construct_weekly_returns(panel, config)
    if periods.empty:
        raise ValueError("no complete weekly periods satisfy PRIMARY eligibility requirements")

    net = summarize_returns(periods, return_col="net_return")
    gross = summarize_returns(periods, return_col="gross_return")
    stress = summarize_returns(periods, return_col="stress_net_return")
    is_periods = periods[periods["start"] < config.oos_start_utc]
    is_net = summarize_returns(is_periods, return_col="net_return")
    is_gross = summarize_returns(is_periods, return_col="gross_return")
    oos_periods = periods[periods["start"] >= config.oos_start_utc]
    oos = summarize_returns(oos_periods, return_col="net_return")
    permutation = _permutation_from_panel(panel, config, periods)

    leave_one_out: dict[str, float] = {}
    for symbol in data.symbols:
        held_out = _construct_weekly_returns(panel, config, excluded_symbols=(symbol,))
        held_out_oos = held_out[held_out["start"] >= config.oos_start_utc]
        held_out_metrics = summarize_returns(held_out_oos, return_col="net_return")
        leave_one_out[symbol] = float(held_out_metrics["calendar_sharpe"])
    finite_loso = [value for value in leave_one_out.values() if math.isfinite(value)]
    loso_min = min(finite_loso) if len(finite_loso) == len(data.symbols) else float("nan")

    active_periods = periods[periods["book_active"]]
    realised_spread_annualized = float(
        active_periods["realised_funding_spread"].mean()
        * CALENDAR_DAYS_PER_YEAR
        / config.rebalance_days
        * 100.0
    )
    metrics = {
        "net_annualized_return_pct": net["annualized_return_pct"],
        "net_sharpe_calendar_day": net["calendar_sharpe"],
        "nw_tstat_weekly": net["nw_tstat_weekly"],
        "nw_max_lag": net["nw_max_lag"],
        "maxdd_equity_base_pct": net["maxdd_equity_base_pct"],
        "rho_weekly_to_BTC": net["rho_weekly_to_btc"],
        "oos_sharpe_2024_2026": oos["calendar_sharpe"],
        "oos_annualized_return_pct": oos["annualized_return_pct"],
        "shuffle_baseline_pvalue": permutation["pvalue"],
        "symbol_leave_one_out_min_oos_sharpe": loso_min,
        "borrow_stress_25apr_net_return_pct": stress["annualized_return_pct"],
        "gross_annualized_return_pct": gross["annualized_return_pct"],
        "gross_calendar_sharpe": gross["calendar_sharpe"],
        "is_gross_annualized_return_pct": is_gross["annualized_return_pct"],
        "is_gross_calendar_sharpe": is_gross["calendar_sharpe"],
        "is_net_maxdd_equity_base_pct": is_net["maxdd_equity_base_pct"],
        "avg_realized_gross_dispersion_annualized_pct": realised_spread_annualized,
        "avg_turnover_per_rebalance_pct": float(periods["realized_turnover"].mean() * 100.0),
        "cost_turnover_assumption_pct": 100.0,
        "avg_trading_cost_per_active_rebalance_bps": float(
            active_periods["trading_cost"].mean() * 10_000.0
        ),
        "avg_borrow_cost_per_active_rebalance_bps": float(
            active_periods["borrow_cost"].mean() * 10_000.0
        ),
        "avg_hedged_price_return_annualized_pct": float(
            periods["hedged_price_return"].mean()
            * CALENDAR_DAYS_PER_YEAR
            / config.rebalance_days
            * 100.0
        ),
        "n_weekly_returns": len(periods),
        "n_active_book_weeks": len(active_periods),
        "n_cash_due_liquidity_weeks": len(periods) - len(active_periods),
        "n_is_weekly_returns": len(is_periods),
        "n_oos_weekly_returns": len(oos_periods),
    }

    gates = {
        "net_annualized_return_pct": _gate(float(metrics["net_annualized_return_pct"]), ">", 12.0),
        "net_sharpe_calendar_day": _gate(float(metrics["net_sharpe_calendar_day"]), ">", 1.0),
        "nw_tstat_weekly": _gate(float(metrics["nw_tstat_weekly"]), ">", 2.0),
        "maxdd_equity_base_pct": _gate(float(metrics["maxdd_equity_base_pct"]), "<", 15.0),
        "abs_rho_weekly_to_BTC": _gate(float(metrics["rho_weekly_to_BTC"]), "abs<", 0.15),
        "oos_sharpe_2024_2026": _gate(float(metrics["oos_sharpe_2024_2026"]), ">", 0.7),
        "shuffle_baseline_pvalue": _gate(float(metrics["shuffle_baseline_pvalue"]), "<", 0.05),
        "symbol_leave_one_out_min_oos_sharpe": _gate(
            float(metrics["symbol_leave_one_out_min_oos_sharpe"]), ">", 0.4
        ),
        "borrow_stress_25apr_net_return_pct": _gate(
            float(metrics["borrow_stress_25apr_net_return_pct"]), ">", 6.0
        ),
    }
    gates["all_numeric_gates_pass"] = all(item["pass"] for item in gates.values())
    gates["promotion_gate_pass"] = False
    gates["promotion_gate_reason"] = (
        "Numerical gates cannot promote a fixed survivor universe; a delisting-inclusive rerun is required."
    )

    negative_loso = sum(value < 0 for value in finite_loso)
    stop_criteria = {
        "is_gross_return_below_5pct": float(is_gross["annualized_return_pct"]) < 5.0,
        "is_gross_sharpe_below_0_3": float(is_gross["calendar_sharpe"]) < 0.3,
        "absolute_btc_rho_above_0_30": abs(float(net["rho_weekly_to_btc"])) > 0.30,
        "is_equity_base_maxdd_above_30pct": float(is_net["maxdd_equity_base_pct"]) > 30.0,
        "three_or_more_negative_loso_oos_sharpes": negative_loso >= 3,
    }
    robustness = {
        "funding_rank_permutation": permutation,
        "leave_one_symbol_out_oos_sharpe": leave_one_out,
        "leave_one_symbol_out_min_oos_sharpe": loso_min,
        "leave_one_symbol_out_negative_count": negative_loso,
        "pre_registered_stop_criteria_triggered": stop_criteria,
        "hard_terminate_triggered": any(stop_criteria.values()),
    }

    limitations = (
        "The local 19-symbol universe is not delisting-inclusive; dead contracts such as LUNA and FTT are absent.",
        "Funding, spot, and perpetual OHLCV data freshness may differ; the test stops at the common usable weekly endpoint.",
        "The 30-day liquidity gate uses close multiplied by base volume as a historical quote-volume proxy.",
        "Calendar weeks with complete prices but fewer than 2k liquidity-eligible symbols are modeled as cash; unavailable post-history weeks are excluded.",
        "This is a PRIMARY feasibility run only; the pre-registered 81-cell sensitivity grid is intentionally not run here.",
    )
    return XSCarryFeasibilityResult(
        status=STATUS,
        promotion_eligible=False,
        limitations=limitations,
        config=config.canonical_dict(),
        coverage=_coverage(data, config, periods, panel),
        metrics=metrics,
        gates=gates,
        robustness=robustness,
        reproducibility=reproducibility_hashes(data, config),
        weekly_returns=periods,
    )


def load_local_xs_carry_data(
    funding_db: str | Path,
    market_db: str | Path,
    config: XSCarryConfig | None = None,
    *,
    venue: str = "binance",
) -> XSCarryData:
    """Load the fixed local funding universe and matching spot/perp daily OHLCV."""

    config = config or XSCarryConfig()
    funding_path = Path(funding_db).expanduser().resolve()
    market_path = Path(market_db).expanduser().resolve()
    if not funding_path.is_file():
        raise FileNotFoundError(funding_path)
    if not market_path.is_file():
        raise FileNotFoundError(market_path)

    buffer_days = max(
        config.funding_score_lookback_days + 1,
        config.liquidity_window_days + config.min_liquidity_observations + 1,
    )
    load_start = config.start_utc - pd.Timedelta(days=buffer_days)
    load_end = config.end_utc
    with duckdb.connect(str(funding_path), read_only=True) as connection:
        symbols = [
            str(row[0])
            for row in connection.execute(
                "SELECT DISTINCT symbol FROM funding_rates WHERE venue = ? ORDER BY symbol",
                [venue],
            ).fetchall()
        ]
        funding = connection.execute(
            """
            SELECT symbol, ts, funding_rate
            FROM funding_rates
            WHERE venue = ? AND ts >= ? AND ts <= ? AND symbol IN (SELECT UNNEST(?))
            ORDER BY symbol, ts
            """,
            [venue, load_start.to_pydatetime(), load_end.to_pydatetime(), symbols],
        ).df()
    if not symbols:
        raise ValueError(f"no funding symbols found for venue={venue!r}")

    spot_symbols = [f"{symbol}/USDT" for symbol in symbols]
    perp_symbols = [f"{symbol}/USDT:USDT" for symbol in symbols]
    query = """
        SELECT symbol, ts, open, close, volume
        FROM ohlcv
        WHERE venue = ? AND timeframe = '1d' AND ts >= ? AND ts <= ?
          AND symbol IN (SELECT UNNEST(?))
        ORDER BY symbol, ts
    """
    with duckdb.connect(str(market_path), read_only=True) as connection:
        spot = connection.execute(
            query,
            [venue, load_start.to_pydatetime(), load_end.to_pydatetime(), spot_symbols],
        ).df()
        perp = connection.execute(
            query,
            [venue, load_start.to_pydatetime(), load_end.to_pydatetime(), perp_symbols],
        ).df()

    metadata = {
        "funding_db": str(funding_path),
        "funding_db_size_bytes": funding_path.stat().st_size,
        "market_db": str(market_path),
        "market_db_size_bytes": market_path.stat().st_size,
        "venue": venue,
        "loaded_funding_universe_size": len(symbols),
    }
    return XSCarryData(funding=funding, spot=spot, perp=perp, source_metadata=metadata)


__all__ = [
    "STATUS",
    "XSCarryConfig",
    "XSCarryData",
    "XSCarryFeasibilityResult",
    "build_weekly_returns",
    "funding_rank_permutation_pvalue",
    "load_local_xs_carry_data",
    "newey_west_tstat",
    "reproducibility_hashes",
    "run_xs_carry_feasibility",
    "summarize_returns",
]
