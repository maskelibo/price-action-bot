from __future__ import annotations

import json
import math
import os
import platform
import subprocess
import tempfile
from copy import deepcopy
from functools import lru_cache
from importlib import metadata
from itertools import combinations
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from price_action.lab.crypto_15m_pairs_program import load_preregistration
from price_action.lab.crypto_15m_pairs_report import (
    RED_NO_HOLDOUT,
    REQUIRES_TRUE_LOSO,
    PairsReportContractError,
    deterministic_json,
    generate_report,
    load_json_artifact,
    main,
    render_markdown,
    sha256_file,
)
from price_action.lab.crypto_15m_pairs_validation import (
    FROZEN_H_MONTHS,
    FROZEN_V17_CANDIDATE_IDS,
)

pytestmark = pytest.mark.subprocess

ROOT = Path(__file__).resolve().parents[1]
PREREG_PATH = ROOT / "configs/crypto_15m_v17_pairs_prereg.yaml"
V16_PATH = ROOT / "reports/research/crypto_15m_v16_primary_raw_2026-07-11.json.gz"
SCENARIOS = ("B", "C2", "H")
SOURCE_FILES = (
    "configs/crypto_15m_v17_pairs_prereg.yaml",
    "docs/CRYPTO_15M_V17_PAIRS_PREREG_2026-07-11.md",
    "requirements-lock.txt",
    "scripts/research/crypto_15m_v17_pairs_program.py",
    "scripts/research/crypto_15m_v17_pairs_report.py",
    "src/price_action/lab/crypto_15m_pairs_engine.py",
    "src/price_action/lab/crypto_15m_pairs_evidence.py",
    "src/price_action/lab/crypto_15m_pairs_program.py",
    "src/price_action/lab/crypto_15m_pairs_report.py",
    "src/price_action/lab/crypto_15m_pairs_signals.py",
    "src/price_action/lab/crypto_15m_pairs_validation.py",
    "src/price_action/lab/crypto_15m_validation.py",
)


@lru_cache(maxsize=1)
def _fixture_source_commit() -> str:
    """Create an unreachable commit containing the current frozen source bytes."""

    with tempfile.TemporaryDirectory() as temporary:
        env = os.environ.copy()
        env.update(
            {
                "GIT_INDEX_FILE": str(Path(temporary) / "index"),
                "GIT_AUTHOR_NAME": "v17-report-test",
                "GIT_AUTHOR_EMAIL": "v17-report-test@example.invalid",
                "GIT_COMMITTER_NAME": "v17-report-test",
                "GIT_COMMITTER_EMAIL": "v17-report-test@example.invalid",
                "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z",
                "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z",
            }
        )
        subprocess.run(["git", "read-tree", "HEAD"], cwd=ROOT, env=env, check=True)
        subprocess.run(["git", "add", "-f", "--", *SOURCE_FILES], cwd=ROOT, env=env, check=True)
        tree = subprocess.run(
            ["git", "write-tree"], cwd=ROOT, env=env, check=True, capture_output=True, text=True
        ).stdout.strip()
        parent = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.strip()
        return subprocess.run(
            ["git", "commit-tree", tree, "-p", parent],
            cwd=ROOT,
            env=env,
            check=True,
            input="synthetic v17 report fixture\n",
            capture_output=True,
            text=True,
        ).stdout.strip()


def _canonical_hash(value: Any) -> str:
    return (
        __import__("hashlib")
        .sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
        .hexdigest()
    )


def _expected_windows(prereg: dict[str, Any]) -> dict[str, tuple[pd.Timestamp, pd.Timestamp]]:
    folds = [
        (pd.Timestamp(start), pd.Timestamp(end))
        for start, end in prereg["time_protocol"]["expanding_walk_forward"]
    ]
    complete = tuple(
        pd.Timestamp(value) for value in prereg["time_protocol"]["complete_months_utc"]
    )
    development = tuple(pd.Timestamp(value) for value in prereg["time_protocol"]["development"])
    common_is = tuple(
        pd.Timestamp(value) for value in prereg["validation_metrics"]["common_IS_ratio_window"]
    )
    windows = {
        "complete": complete,
        "development": development,
        "common_is": common_is,
        "pseudo_oos": (folds[0][0], folds[-1][1]),
    }
    windows.update({f"walk_forward_{index}": value for index, value in enumerate(folds, 1)})
    return windows


def _global_returns(candidate: str, scenario: str, *, passing: bool) -> pd.Series:
    months = pd.period_range("2021-06", "2026-05", freq="M")
    values = np.empty(len(months), dtype=float)
    phase_all = np.linspace(0.0, 7.0 * np.pi, len(months))
    values[:] = -1.0 + 0.15 * np.sin(phase_all)
    if not passing:
        offset = 0.15 * FROZEN_V17_CANDIDATE_IDS.index(candidate)
        return pd.Series(values - offset, index=months)

    h_locations = months.get_indexer(FROZEN_H_MONTHS)
    phase = np.linspace(0.0, 4.0 * np.pi, len(FROZEN_H_MONTHS))
    if candidate == FROZEN_V17_CANDIDATE_IDS[0]:
        values[:] = 11.5 + 0.6 * np.sin(phase_all)
        if scenario == "H":
            values[h_locations] = 12.0 + np.sin(phase)
        elif scenario == "C2":
            values[h_locations] = 9.0 + 0.5 * np.sin(phase)
        else:
            values[h_locations] = 12.5 + 0.7 * np.sin(phase)
    elif candidate == FROZEN_V17_CANDIDATE_IDS[1]:
        values[:] = 1.5 + 2.5 * np.cos(phase_all)
        values[h_locations] = 2.0 + 3.0 * np.cos(phase)
    else:
        values[:] = -2.0 + 2.5 * np.sin(phase_all + 0.5)
        values[h_locations] = -2.0 + 3.0 * np.sin(phase + 0.5)
    return pd.Series(values, index=months)


def _episode(candidate: str, index: int, *, terminal: bool = False) -> dict[str, Any]:
    if terminal:
        entry = pd.Timestamp("2026-05-30T00:00:00Z")
        exit_ts = pd.Timestamp("2026-05-31T23:45:00Z")
        regime = "low_spread"
        month_start = pd.Timestamp("2026-05-01T00:00:00Z")
    else:
        month = FROZEN_H_MONTHS[index % len(FROZEN_H_MONTHS)]
        month_start = month.start_time.tz_localize("UTC")
        selection = month_start + pd.Timedelta(days=(7 - month_start.dayofweek) % 7)
        entry = selection + pd.Timedelta(days=1 + index // len(FROZEN_H_MONTHS))
        exit_ts = entry + pd.Timedelta(hours=1)
        regime = "high_spread" if index % 2 == 0 else "low_spread"
    selection_ts = month_start + pd.Timedelta(days=(7 - month_start.dayofweek) % 7)
    symbols = ("ETH/USDT", "SOL/USDT") if index % 2 == 0 else ("BNB/USDT", "ADA/USDT")
    y_exit_price, x_exit_price = (90.0, 110.0) if regime == "high_spread" else (110.0, 90.0)
    return {
        "candidate_id": candidate,
        "pair_id": "|".join(sorted(symbols)),
        "selection_ts": selection_ts.isoformat(),
        "y_symbol": symbols[0],
        "x_symbol": symbols[1],
        "entry_regime": regime,
        "y_side": "short" if regime == "high_spread" else "long",
        "x_side": "long" if regime == "high_spread" else "short",
        "decision_ts": (entry - pd.Timedelta(minutes=15)).isoformat(),
        "entry_ts": entry.isoformat(),
        "exit_decision_ts": (exit_ts - pd.Timedelta(minutes=15)).isoformat(),
        "exit_ts": exit_ts.isoformat(),
        "exit_reason": "terminal_open_mtm" if terminal else "mean_exit",
        "signal_z": 3.0 if regime == "high_spread" else -3.0,
        "fill_z": 3.0 if regime == "high_spread" else -3.0,
        "entry_z": 3.0 if regime == "high_spread" else -3.0,
        "exit_z": 0.0,
        "alpha": -0.3 if regime == "high_spread" else 0.3,
        "beta": 1.0,
        "validation_mean": 0.0,
        "validation_std": 0.1,
        "gross_weight_y": 0.5,
        "gross_weight_x": 0.5,
        "y_entry_price": 100.0,
        "x_entry_price": 100.0,
        "y_exit_price": y_exit_price,
        "x_exit_price": x_exit_price,
        "y_quantity": 5.0,
        "x_quantity": 5.0,
        "gross_exposure": 1000.0,
        "y_entry_notional": 500.0,
        "x_entry_notional": 500.0,
        "gross_pair_price_pnl": 100.0,
        "payoff_multiplier": 1.0,
        "adjusted_pair_price_pnl": 100.0,
        "y_entry_fee": 2.5,
        "y_entry_spread_slippage": 0.0,
        "y_entry_impact": 0.0,
        "x_entry_fee": 2.5,
        "x_entry_spread_slippage": 0.0,
        "x_entry_impact": 0.0,
        "y_exit_fee": 2.5,
        "y_exit_spread_slippage": 0.0,
        "y_exit_impact": 0.0,
        "x_exit_fee": 2.5,
        "x_exit_spread_slippage": 0.0,
        "x_exit_impact": 0.0,
        "y_funding_cashflow": 0.0,
        "x_funding_cashflow": 0.0,
        "execution_cost": 10.0,
        "net_pnl": 90.0,
        "signal_expected_convergence_return": 0.125,
        "expected_convergence_return": 0.125,
        "adverse_funding": 0.0,
        "signal_stressed_required_return": 0.0171,
        "stressed_required_return": 0.0171,
    }


def _episodes(
    candidate: str, *, passing: bool
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    count = 120 if passing and candidate == FROZEN_V17_CANDIDATE_IDS[0] else 1
    return (
        [_episode(candidate, index) for index in range(count)],
        [_episode(candidate, count, terminal=True)],
    )


def _equity_curve(
    returns: pd.Series, episodes: list[dict[str, Any]], *, initial_equity: float = 10_000.0
) -> list[list[Any]]:
    rows: list[list[Any]] = []
    previous = initial_equity
    for month, return_pct in returns.items():
        start = month.start_time.tz_localize("UTC")
        end = (month + 1).start_time.tz_localize("UTC") - pd.Timedelta(minutes=15)
        ending = previous * (1.0 + float(return_pct) / 100.0)
        timestamps = {
            start,
            start + pd.Timedelta(days=9),
            start + pd.Timedelta(days=19),
            end,
        }
        for episode in episodes:
            for field in ("entry_ts", "exit_ts"):
                timestamp = pd.Timestamp(episode[field])
                if timestamp.tz_localize(None).to_period("M") == month:
                    timestamps.add(timestamp)
        for timestamp in sorted(timestamps):
            if timestamp == end:
                nav = ending
            elif timestamp == start:
                nav = previous * 0.98
            else:
                nav = (previous + ending) / 2.0
            rows.append([timestamp.isoformat(), nav])
        previous = ending
    return rows


def _window(
    curve_rows: list[list[Any]],
    *,
    bounds: tuple[pd.Timestamp, pd.Timestamp],
    closed: list[dict[str, Any]],
    terminal: list[dict[str, Any]],
    initial_equity: float = 10_000.0,
) -> dict[str, Any]:
    start, end = bounds
    curve = pd.Series(
        [float(row[1]) for row in curve_rows],
        index=pd.DatetimeIndex([pd.Timestamp(row[0]) for row in curve_rows]),
        dtype=float,
    )
    months = pd.period_range(
        start.tz_localize(None).to_period("M"),
        (end - pd.Timedelta(nanoseconds=1)).tz_localize(None).to_period("M"),
        freq="M",
    )
    before = curve.loc[curve.index < start]
    baseline = float(before.iloc[-1]) if not before.empty else initial_equity
    pre_window_peak = max(
        initial_equity, float(before.max()) if not before.empty else initial_equity
    )
    values = curve.loc[(curve.index >= start) & (curve.index < end)]
    value_months = values.index.tz_localize(None).to_period("M")
    month_end = values.groupby(value_months).last().reindex(months).ffill().fillna(baseline)
    previous = month_end.shift(1)
    previous.iloc[0] = baseline
    monthly_returns = (month_end / previous - 1.0) * 100.0
    pnl = month_end - previous

    def in_window(record: dict[str, Any], field: str) -> bool:
        timestamp = pd.Timestamp(record[field])
        return start <= timestamp < end

    closed_window = [item for item in closed if in_window(item, "exit_ts")]
    terminal_window = [item for item in terminal if in_window(item, "exit_ts")]
    active_observations = []
    for timestamp in values.index:
        active_observations.append(
            any(
                pd.Timestamp(item["entry_ts"]) <= timestamp < pd.Timestamp(item["exit_ts"])
                for item in closed
            )
            or any(
                pd.Timestamp(item["entry_ts"]) <= timestamp <= pd.Timestamp(item["exit_ts"])
                for item in terminal
            )
        )
    active = (
        pd.Series(active_observations, index=value_months)
        .groupby(level=0)
        .any()
        .reindex(months, fill_value=False)
    )
    running_peak = pre_window_peak
    max_drawdown = 0.0
    for nav in values.to_numpy(dtype=float):
        running_peak = max(running_peak, nav)
        max_drawdown = max(max_drawdown, (running_peak - nav) / running_peak * 100.0)
    recovery_peak = pre_window_peak
    current_recovery = 0
    max_recovery = 0
    for nav in month_end.to_numpy(dtype=float):
        if nav >= recovery_peak - 1e-12:
            recovery_peak = max(recovery_peak, nav)
            current_recovery = 0
        else:
            current_recovery += 1
            max_recovery = max(max_recovery, current_recovery)
    return {
        "start_inclusive": start.isoformat(),
        "end_exclusive": end.isoformat(),
        "baseline_equity": baseline,
        "pre_window_peak_equity": pre_window_peak,
        "ending_equity": float(values.iloc[-1]),
        "total_return_pct": (float(values.iloc[-1]) / baseline - 1.0) * 100.0,
        "equity_observations": len(values),
        "nav_observation_sum": float(values.sum()),
        "arithmetic_mean_15m_nav": float(values.mean()),
        "max_mtm_drawdown_pct": max_drawdown,
        "max_recovery_months": max_recovery,
        "active_months": int(active.sum()),
        "active_month_definition": "at_least_one_equity_curve_observation_with_nonzero_open_pair_exposure",
        "monthly_active_exposure": {str(month): bool(value) for month, value in active.items()},
        "closed_pair_episodes": len(closed_window),
        "terminal_open_pair_pseudo_episodes": len(terminal_window),
        "high_spread_closed_episodes": sum(
            item["entry_regime"] == "high_spread" for item in closed_window
        ),
        "low_spread_closed_episodes": sum(
            item["entry_regime"] == "low_spread" for item in closed_window
        ),
        "monthly_returns_unit": "percentage_points",
        "monthly_returns_pct": {
            str(month): float(value) for month, value in monthly_returns.items()
        },
        "monthly_pnl": {str(month): float(value) for month, value in pnl.items()},
    }


def _scenario(
    candidate: str,
    scenario: str,
    *,
    prereg: dict[str, Any],
    passing: bool,
) -> dict[str, Any]:
    closed, terminal = _episodes(candidate, passing=passing)
    returns = _global_returns(candidate, scenario, passing=passing)
    curve = _equity_curve(returns, [*closed, *terminal])
    windows = {
        name: _window(
            curve,
            bounds=bounds,
            closed=closed,
            terminal=terminal,
        )
        for name, bounds in _expected_windows(prereg).items()
    }
    episodes = [*closed, *terminal]
    total_net_pnl = windows["complete"]["ending_equity"] - windows["complete"]["baseline_equity"]
    target_net_pnl = total_net_pnl / len(episodes)
    base_costs = prereg["risk_and_execution"]["execution_costs_bps_per_leg"]
    cost_multiplier = prereg["risk_and_execution"]["cost_scenarios"][scenario]["cost_multiplier"]
    total_cost_rate = sum(base_costs.values()) * cost_multiplier / 10_000.0
    for episode in episodes:
        payoff_multiplier = (
            0.5
            if scenario == "H" and target_net_pnl + 2_000.0 * total_cost_rate > 0.0
            else 1.25
            if scenario == "H" and target_net_pnl + 2_000.0 * total_cost_rate < 0.0
            else 1.0
        )
        numerator = target_net_pnl + 2_000.0 * total_cost_rate
        gross_price_pnl = (
            numerator / (payoff_multiplier - total_cost_rate)
            if numerator >= 0.0
            else numerator / (payoff_multiplier + total_cost_rate)
        )
        episode["gross_pair_price_pnl"] = gross_price_pnl
        episode["payoff_multiplier"] = payoff_multiplier
        if gross_price_pnl >= 0.0 and episode["entry_regime"] == "high_spread":
            episode["y_exit_price"] = 100.0
            episode["x_exit_price"] = 100.0 + gross_price_pnl / episode["x_quantity"]
        elif gross_price_pnl >= 0.0:
            episode["y_exit_price"] = 100.0 + gross_price_pnl / episode["y_quantity"]
            episode["x_exit_price"] = 100.0
        elif episode["entry_regime"] == "high_spread":
            episode["y_exit_price"] = 100.0 + abs(gross_price_pnl) / episode["y_quantity"]
            episode["x_exit_price"] = 100.0
        else:
            episode["y_exit_price"] = 100.0
            episode["x_exit_price"] = 100.0 + abs(gross_price_pnl) / episode["x_quantity"]
        fill_notionals = {
            "y_entry": episode["y_entry_notional"],
            "x_entry": episode["x_entry_notional"],
            "y_exit": abs(episode["y_quantity"]) * episode["y_exit_price"],
            "x_exit": abs(episode["x_quantity"]) * episode["x_exit_price"],
        }
        for leg_fill, notional in fill_notionals.items():
            episode[f"{leg_fill}_fee"] = notional * base_costs["fee"] * cost_multiplier / 10_000.0
            episode[f"{leg_fill}_spread_slippage"] = (
                notional * base_costs["spread_and_slippage"] * cost_multiplier / 10_000.0
            )
            episode[f"{leg_fill}_impact"] = (
                notional * base_costs["impact"] * cost_multiplier / 10_000.0
            )
        episode["execution_cost"] = sum(
            episode[field]
            for leg_fill in fill_notionals
            for field in (
                f"{leg_fill}_fee",
                f"{leg_fill}_spread_slippage",
                f"{leg_fill}_impact",
            )
        )
        episode["adjusted_pair_price_pnl"] = gross_price_pnl * payoff_multiplier
        episode["net_pnl"] = episode["adjusted_pair_price_pnl"] - episode["execution_cost"]
    economic = [
        {**item, "episode_kind": "closed", "is_closed_sample": True, "funding_cashflow": 0.0}
        for item in closed
    ] + [
        {
            **item,
            "episode_kind": "terminal_open_mtm",
            "is_closed_sample": False,
            "funding_cashflow": 0.0,
        }
        for item in terminal
    ]
    rejections: list[dict[str, Any]] = []
    accrued_exit_cost = sum(
        episode[field]
        for episode in terminal
        for field in (
            "y_exit_fee",
            "y_exit_spread_slippage",
            "y_exit_impact",
            "x_exit_fee",
            "x_exit_spread_slippage",
            "x_exit_impact",
        )
    )
    ledger_execution_cost = sum(episode["execution_cost"] for episode in episodes)
    payload = {
        "initial_equity": windows["complete"]["baseline_equity"],
        "final_equity": windows["complete"]["ending_equity"],
        "max_mtm_drawdown_pct": windows["complete"]["max_mtm_drawdown_pct"],
        "total_execution_cost": ledger_execution_cost - accrued_exit_cost,
        "accrued_exit_cost": accrued_exit_cost,
        "total_funding_cashflow": 0.0,
        "open_pair_count": len(terminal),
        "open_leg_count": 2 * len(terminal),
        "quarantined_pairs": [],
        "engine_monthly_returns": [
            {"month": month, "return_pct": value}
            for month, value in windows["complete"]["monthly_returns_pct"].items()
        ],
        "equity_curve_observations": len(curve),
        "equity_curve_ledger": curve,
        "equity_curve_sha256": _canonical_hash(curve),
        "closed_episode_ledger": closed,
        "terminal_episode_ledger": terminal,
        "economic_episode_ledger": economic,
        "economic_terminal_rows_are_closed_samples": False,
        "rejections": rejections,
        "rejection_counts": {},
        "windows": windows,
    }
    for field in (
        "closed_episode_ledger",
        "terminal_episode_ledger",
        "economic_episode_ledger",
        "rejections",
    ):
        payload[f"{field}_sha256"] = _canonical_hash(payload[field])
    return payload


def _stream(candidate: str, *, passing: bool, prereg: dict[str, Any]) -> dict[str, Any]:
    closed, terminal = _episodes(candidate, passing=passing)
    cell = next(item for item in prereg["candidate_cells"] if item["id"] == candidate)
    all_episodes = [*closed, *terminal]
    complete_start, complete_end = _expected_windows(prereg)["complete"]
    schedule = []
    for month in pd.period_range(
        complete_start.tz_localize(None).to_period("M"),
        complete_end.tz_localize(None).to_period("M"),
        freq="M",
    ):
        first = month.start_time.tz_localize("UTC")
        selection_ts = first + pd.Timedelta(days=(7 - first.dayofweek) % 7)
        if not complete_start <= selection_ts < complete_end:
            continue
        episodes = [
            item for item in all_episodes if pd.Timestamp(item["selection_ts"]) == selection_ts
        ]
        by_pair: dict[str, dict[str, Any]] = {}
        for episode in episodes:
            by_pair.setdefault(episode["pair_id"], episode)
        models = [
            {
                "candidate_id": candidate,
                "pair_id": pair_id,
                "selection_ts": selection_ts.isoformat(),
                "y_symbol": episode["y_symbol"],
                "x_symbol": episode["x_symbol"],
                "alpha": episode["alpha"],
                "beta": episode["beta"],
                "validation_mean": episode["validation_mean"],
                "validation_std": episode["validation_std"],
                "gross_weight_y": episode["gross_weight_y"],
                "gross_weight_x": episode["gross_weight_x"],
            }
            for pair_id, episode in sorted(by_pair.items())
        ]
        model_by_pair = {model["pair_id"]: model for model in models}
        primary = sorted(prereg["universe"]["primary_symbols"])
        decisions = []
        for first_symbol, second_symbol in combinations(primary, 2):
            pair_id = f"{first_symbol}|{second_symbol}"
            model = model_by_pair.get(pair_id)
            decisions.append(
                {
                    "candidate_id": candidate,
                    "pair_id": pair_id,
                    "selection_ts": selection_ts.isoformat(),
                    "status": "selected" if model is not None else "rejected",
                    "reason": "SELECTED" if model is not None else "DATA_WINDOW_INELIGIBLE",
                    "y_symbol": model["y_symbol"] if model is not None else None,
                    "x_symbol": model["x_symbol"] if model is not None else None,
                }
            )
        schedule.append(
            {
                "selection_ts": selection_ts.isoformat(),
                "selected_pair_ids": sorted(by_pair),
                "selected_models": models,
                "pair_decisions": decisions,
                "rejected_pair_reasons": [
                    item for item in decisions if item["status"] == "rejected"
                ],
            }
        )
    flattened_models = [model for selection in schedule for model in selection["selected_models"]]
    intents = [
        {
            "candidate_id": candidate,
            "pair_id": episode["pair_id"],
            "selection_ts": episode["selection_ts"],
            "decision_ts": episode["decision_ts"],
            "entry_ts": episode["entry_ts"],
            "y_symbol": episode["y_symbol"],
            "x_symbol": episode["x_symbol"],
            "y_side": episode["y_side"],
            "x_side": episode["x_side"],
            "z_score": episode["signal_z"],
            "alpha": episode["alpha"],
            "beta": episode["beta"],
            "validation_mean": episode["validation_mean"],
            "validation_std": episode["validation_std"],
            "gross_weight_y": episode["gross_weight_y"],
            "gross_weight_x": episode["gross_weight_x"],
            "entry_abs_z": cell["entry_abs_z"],
            "exit_abs_z": cell["exit_abs_z"],
            "disaster_abs_z": cell["disaster_abs_z"],
            "max_hold_hours": cell["max_hold_hours"],
            "cooldown_hours": cell["cooldown_hours"],
            "expected_convergence_return": 0.125,
            "adverse_funding": 0.0,
            "stressed_required_return": 0.0171,
            "economic_buffer_multiplier": 1.5,
            "base_round_trip_cost_per_gross": 0.0057,
            "c2_round_trip_cost_per_gross": 0.0114,
        }
        for episode in all_episodes
    ]
    stream = {
        "pair_selection_ledger": schedule,
        "pair_models": flattened_models,
        "entry_intents": intents,
    }
    for field in ("pair_selection_ledger", "pair_models", "entry_intents"):
        stream[f"{field}_sha256"] = _canonical_hash(stream[field])
    return stream


def _v17_payload(*, passing: bool) -> dict[str, Any]:
    prereg = load_preregistration(PREREG_PATH)
    source_hashes = {relative: sha256_file(ROOT / relative) for relative in SOURCE_FILES}
    source_commit = _fixture_source_commit()
    prereg_sha256 = sha256_file(PREREG_PATH)
    snapshots = {
        name: {
            "name": name,
            "configured_path": prereg["snapshots"][name]["path"],
            "resolved_path": str(ROOT / prereg["snapshots"][name]["path"]),
            "bytes": prereg["snapshots"][name]["bytes"],
            "sha256": prereg["snapshots"][name]["sha256"],
            "status": "VERIFIED",
        }
        for name in ("market", "funding")
    }
    streams: dict[str, Any] = {}
    results: dict[str, Any] = {}
    for candidate in FROZEN_V17_CANDIDATE_IDS:
        streams[candidate] = _stream(candidate, passing=passing, prereg=prereg)
        results[candidate] = {
            scenario: _scenario(
                candidate,
                scenario,
                prereg=prereg,
                passing=passing,
            )
            for scenario in SCENARIOS
        }
    return {
        "schema_version": "crypto-15m-v17-pairs-run-v1",
        "mode": "FULL_FROZEN_REPLAY",
        "partition": "primary",
        "evidence_eligible": True,
        "evidence_ineligible_reasons": [],
        "candidate_ids": list(FROZEN_V17_CANDIDATE_IDS),
        "candidate_count": 3,
        "scenario_order": list(SCENARIOS),
        "preregistration": {
            "path": str(PREREG_PATH),
            "sha256": prereg_sha256,
            "schema_version": "crypto-15m-v17-pairs-prereg-v1",
            "status": "PREREGISTERED_NO_RESULTS_SEEN",
            "live_deployment_authorized": False,
        },
        "source_provenance": {
            "git_commit": source_commit,
            "research_source_clean": True,
            "research_source_status": [],
            "missing_source_files": [],
            "file_sha256": source_hashes,
        },
        "runtime_versions": {
            "python": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "duckdb": metadata.version("duckdb"),
            "numpy": metadata.version("numpy"),
            "pandas": metadata.version("pandas"),
            "pyyaml": metadata.version("PyYAML"),
            "scipy": metadata.version("scipy"),
            "statsmodels": metadata.version("statsmodels"),
        },
        "snapshots": snapshots,
        "execution_governance": {
            "canonical_prereg_path": str(PREREG_PATH.resolve()),
            "canonical_prereg_semantic_match": True,
            "canonical_prereg_preflight_sha256": prereg_sha256,
            "canonical_prereg_postflight_sha256": prereg_sha256,
            "clean_source_preflight": True,
            "source_unchanged_postflight": True,
            "snapshots_reverified_postflight": True,
            "snapshots_unchanged_postflight": True,
            "preflight_git_commit": source_commit,
            "postflight_git_commit": source_commit,
            "preflight_source_file_sha256": source_hashes,
            "postflight_source_file_sha256": source_hashes,
            "postflight_snapshots": deepcopy(snapshots),
        },
        "streams": streams,
        "results": results,
    }


def _write_payload(tmp_path: Path, payload: dict[str, Any], name: str = "v17.json") -> Path:
    path = tmp_path / name
    path.write_text(
        json.dumps(payload, sort_keys=False, separators=(",", ":"), allow_nan=False),
        encoding="utf-8",
    )
    return path


def test_red_report_is_exact_fail_closed_and_turnover_is_preregistered(tmp_path: Path) -> None:
    raw_path = _write_payload(tmp_path, _v17_payload(passing=False))

    report = generate_report(raw_path, repo_root=ROOT)

    assert report["decision"]["verdict"] == RED_NO_HOLDOUT
    assert report["decision"]["locked_primary_winner"] is None
    assert report["decision"]["holdout"] == "NOT_RUN_PRIMARY_GATES_FAILED"
    assert report["multiple_testing"]["local_v17_exact_36x3"]["months"] == 36
    assert (
        report["multiple_testing"]["program_wide_v16_plus_v17_exact_36x9"]["candidate_count"] == 9
    )
    for candidate in FROZEN_V17_CANDIDATE_IDS:
        cell = report["cells"][candidate]
        assert list(cell["scenario_windows"]["H"]["pseudo_oos"]["monthly_returns_pct"]) == [
            str(month) for month in FROZEN_H_MONTHS
        ]
        assert cell["primary_pre_LOSO_gates"]["passed"] is False
        assert cell["full_hard_gates"]["passed"] is False
        assert (
            "concentration.all_true_leave_one_symbol_out_replays_positive"
            in cell["full_hard_gates"]["failed_gates"]
        )
        assert any(item.startswith("holdout.") for item in cell["full_hard_gates"]["failed_gates"])
        turnover = cell["metrics"]["turnover"]
        assert turnover["filled_gross_notional_numerator"] == pytest.approx(
            turnover["entry_fill_gross_notional"]
            + turnover["closed_exit_fill_gross_notional"]
            + turnover["terminal_accrued_liquidation_gross_notional"]
        )
        assert turnover["filled_gross_turnover"] > 0.0


def test_primary_pass_locks_one_winner_but_stops_before_loso_and_holdout(tmp_path: Path) -> None:
    raw_path = _write_payload(tmp_path, _v17_payload(passing=True))

    report = generate_report(raw_path, repo_root=ROOT)

    winner = FROZEN_V17_CANDIDATE_IDS[0]
    assert report["decision"]["verdict"] == REQUIRES_TRUE_LOSO
    assert report["decision"]["locked_primary_winner"] == winner
    assert report["decision"]["true_LOSO"] == "REQUIRED_NOT_RUN"
    assert report["decision"]["holdout"] == "NOT_RUN_REQUIRES_TRUE_LOSO"
    assert report["cells"][winner]["primary_pre_LOSO_gates"]["passed"] is True
    assert report["cells"][winner]["full_hard_gates"]["passed"] is False
    assert report["ranking"]["rows"][0]["candidate_id"] == winner
    assert report["ranking"]["rows"][0]["H_rank_value_pct"] == pytest.approx(12.0)
    assert report["decision"]["live_deployment_authorized"] is False


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda payload: payload.update(evidence_eligible=False), "evidence_eligible"),
        (
            lambda payload: payload["candidate_ids"].__setitem__(0, "POSTHOC_CELL"),
            "candidate IDs/order",
        ),
        (
            lambda payload: payload["snapshots"]["market"].update(sha256="0" * 64),
            "immutable identity",
        ),
        (
            lambda payload: payload["execution_governance"].update(
                canonical_prereg_preflight_sha256="0" * 64
            ),
            "preflight preregistration hash",
        ),
        (
            lambda payload: payload["source_provenance"].update(
                missing_source_files=["missing.py"]
            ),
            "missing frozen source files",
        ),
    ],
)
def test_header_contract_tampering_fails_before_metrics(
    tmp_path: Path, mutator: Any, message: str
) -> None:
    payload = _v17_payload(passing=False)
    mutator(payload)
    raw_path = _write_payload(tmp_path, payload)

    with pytest.raises(PairsReportContractError, match=message):
        generate_report(raw_path, repo_root=ROOT)


def test_month_calendar_hash_and_turnover_denominator_fail_closed(tmp_path: Path) -> None:
    payload = _v17_payload(passing=False)
    candidate = FROZEN_V17_CANDIDATE_IDS[0]
    h = payload["results"][candidate]["H"]
    h["windows"]["pseudo_oos"]["monthly_returns_pct"].pop("2023-06")
    raw_path = _write_payload(tmp_path, payload, "month.json")
    with pytest.raises(PairsReportContractError, match="exact chronological months"):
        generate_report(raw_path, repo_root=ROOT)

    payload = _v17_payload(passing=False)
    payload["results"][candidate]["H"]["closed_episode_ledger"][0]["net_pnl"] = 999.0
    raw_path = _write_payload(tmp_path, payload, "hash.json")
    with pytest.raises(PairsReportContractError, match="hash mismatch"):
        generate_report(raw_path, repo_root=ROOT)

    payload = _v17_payload(passing=False)
    payload["results"][candidate]["H"]["windows"]["pseudo_oos"].pop("arithmetic_mean_15m_nav")
    raw_path = _write_payload(tmp_path, payload, "turnover.json")
    with pytest.raises(PairsReportContractError, match=r"nav_mean|turnover denominator"):
        generate_report(raw_path, repo_root=ROOT)


def test_foreign_candidate_id_fails_even_when_ledger_hash_is_recomputed(tmp_path: Path) -> None:
    payload = _v17_payload(passing=False)
    candidate = FROZEN_V17_CANDIDATE_IDS[0]
    scenario = payload["results"][candidate]["H"]
    scenario["closed_episode_ledger"][0]["candidate_id"] = FROZEN_V17_CANDIDATE_IDS[1]
    scenario["closed_episode_ledger_sha256"] = _canonical_hash(scenario["closed_episode_ledger"])
    raw_path = _write_payload(tmp_path, payload, "foreign-candidate.json")

    with pytest.raises(PairsReportContractError, match="foreign candidate_id"):
        generate_report(raw_path, repo_root=ROOT)


def test_selection_schedule_and_all_78_pair_decisions_are_required(tmp_path: Path) -> None:
    payload = _v17_payload(passing=False)
    candidate = FROZEN_V17_CANDIDATE_IDS[0]
    stream = payload["streams"][candidate]
    stream["pair_selection_ledger"] = []
    stream["pair_selection_ledger_sha256"] = _canonical_hash([])
    raw_path = _write_payload(tmp_path, payload, "empty-schedule.json")
    with pytest.raises(PairsReportContractError, match="every exact first-Monday"):
        generate_report(raw_path, repo_root=ROOT)

    payload = _v17_payload(passing=False)
    stream = payload["streams"][candidate]
    selection = stream["pair_selection_ledger"][0]
    selection["pair_decisions"].pop()
    selection["rejected_pair_reasons"] = [
        item for item in selection["pair_decisions"] if item["status"] == "rejected"
    ]
    stream["pair_selection_ledger_sha256"] = _canonical_hash(stream["pair_selection_ledger"])
    raw_path = _write_payload(tmp_path, payload, "missing-decision.json")
    with pytest.raises(PairsReportContractError, match="all 78 primary pairs"):
        generate_report(raw_path, repo_root=ROOT)


def test_primary_universe_and_economic_tagged_union_are_fail_closed(tmp_path: Path) -> None:
    payload = _v17_payload(passing=False)
    candidate = FROZEN_V17_CANDIDATE_IDS[0]
    scenario = payload["results"][candidate]["H"]
    closed = scenario["closed_episode_ledger"][0]
    closed.update(pair_id="AAVE/USDT|XLM/USDT", y_symbol="AAVE/USDT", x_symbol="XLM/USDT")
    scenario["closed_episode_ledger_sha256"] = _canonical_hash(scenario["closed_episode_ledger"])
    raw_path = _write_payload(tmp_path, payload, "holdout-leak.json")
    with pytest.raises(PairsReportContractError, match="outside the primary universe"):
        generate_report(raw_path, repo_root=ROOT)

    payload = _v17_payload(passing=False)
    scenario = payload["results"][candidate]["H"]
    scenario["economic_episode_ledger"][0]["is_closed_sample"] = False
    scenario["economic_episode_ledger_sha256"] = _canonical_hash(
        scenario["economic_episode_ledger"]
    )
    raw_path = _write_payload(tmp_path, payload, "economic-union.json")
    with pytest.raises(PairsReportContractError, match=r"exact closed\+terminal union"):
        generate_report(raw_path, repo_root=ROOT)


def test_turnover_denominator_must_reconcile_to_all_six_folds(tmp_path: Path) -> None:
    payload = _v17_payload(passing=True)
    candidate = FROZEN_V17_CANDIDATE_IDS[0]
    pseudo = payload["results"][candidate]["H"]["windows"]["pseudo_oos"]
    pseudo["arithmetic_mean_15m_nav"] = 1e12
    pseudo["nav_observation_sum"] = pseudo["equity_observations"] * 1e12
    raw_path = _write_payload(tmp_path, payload, "turnover-exploit.json")

    with pytest.raises(PairsReportContractError, match="pseudo fold nav_observation_sum"):
        generate_report(raw_path, repo_root=ROOT)


def test_each_intent_has_exactly_one_scenario_outcome(tmp_path: Path) -> None:
    payload = _v17_payload(passing=False)
    candidate = FROZEN_V17_CANDIDATE_IDS[0]
    stream = payload["streams"][candidate]
    extra = dict(stream["entry_intents"][0])
    extra["decision_ts"] = "2023-06-08T23:45:00+00:00"
    extra["entry_ts"] = "2023-06-09T00:00:00+00:00"
    stream["entry_intents"].append(extra)
    stream["entry_intents_sha256"] = _canonical_hash(stream["entry_intents"])
    raw_path = _write_payload(tmp_path, payload, "missing-outcome.json")

    with pytest.raises(PairsReportContractError, match="outcomes do not partition"):
        generate_report(raw_path, repo_root=ROOT)


def test_active_months_are_derived_from_episode_intervals(tmp_path: Path) -> None:
    payload = _v17_payload(passing=False)
    candidate = FROZEN_V17_CANDIDATE_IDS[0]
    windows = payload["results"][candidate]["H"]["windows"]
    for window in windows.values():
        window["monthly_active_exposure"] = {
            month: True for month in window["monthly_active_exposure"]
        }
        window["active_months"] = len(window["monthly_active_exposure"])
    raw_path = _write_payload(tmp_path, payload, "active-month-exploit.json")

    with pytest.raises(PairsReportContractError, match="active exposure disagrees"):
        generate_report(raw_path, repo_root=ROOT)


def test_pre_window_peak_is_bound_across_same_start_windows(tmp_path: Path) -> None:
    payload = _v17_payload(passing=False)
    candidate = FROZEN_V17_CANDIDATE_IDS[0]
    h_windows = payload["results"][candidate]["H"]["windows"]
    h_windows["pseudo_oos"]["pre_window_peak_equity"] = h_windows["pseudo_oos"]["baseline_equity"]
    raw_path = _write_payload(tmp_path, payload, "recovery-peak-exploit.json")

    with pytest.raises(PairsReportContractError, match=r"pre-window peak|pseudo/fold1"):
        generate_report(raw_path, repo_root=ROOT)


def test_drawdown_cannot_be_below_monthly_close_lower_bound(tmp_path: Path) -> None:
    payload = _v17_payload(passing=False)
    candidate = FROZEN_V17_CANDIDATE_IDS[0]
    for scenario in SCENARIOS:
        scenario_payload = payload["results"][candidate][scenario]
        scenario_payload["max_mtm_drawdown_pct"] = 0.0
        for window in scenario_payload["windows"].values():
            window["max_mtm_drawdown_pct"] = 0.0
    raw_path = _write_payload(tmp_path, payload, "drawdown-exploit.json")

    with pytest.raises(PairsReportContractError, match="monthly-close lower bound"):
        generate_report(raw_path, repo_root=ROOT)


def test_equity_curve_and_episode_financial_identities_are_fail_closed(tmp_path: Path) -> None:
    payload = _v17_payload(passing=False)
    candidate = FROZEN_V17_CANDIDATE_IDS[0]
    scenario = payload["results"][candidate]["C2"]
    scenario["closed_episode_ledger"][0]["net_pnl"] = 1e9
    scenario["economic_episode_ledger"][0]["net_pnl"] = 1e9
    scenario["closed_episode_ledger_sha256"] = _canonical_hash(scenario["closed_episode_ledger"])
    scenario["economic_episode_ledger_sha256"] = _canonical_hash(
        scenario["economic_episode_ledger"]
    )
    raw_path = _write_payload(tmp_path, payload, "financial-forge.json")
    with pytest.raises(PairsReportContractError, match="episode net PnL identity"):
        generate_report(raw_path, repo_root=ROOT)

    payload = _v17_payload(passing=False)
    scenario = payload["results"][candidate]["H"]
    scenario["equity_curve_ledger"][0][1] *= 1.01
    scenario["equity_curve_sha256"] = _canonical_hash(scenario["equity_curve_ledger"])
    raw_path = _write_payload(tmp_path, payload, "curve-forge.json")
    with pytest.raises(PairsReportContractError, match=r"curve (NAV sum|max drawdown|monthly)"):
        generate_report(raw_path, repo_root=ROOT)


def test_fake_git_commit_and_runtime_versions_are_rejected(tmp_path: Path) -> None:
    payload = _v17_payload(passing=False)
    payload["source_provenance"]["git_commit"] = "0" * 40
    payload["execution_governance"]["preflight_git_commit"] = "0" * 40
    payload["execution_governance"]["postflight_git_commit"] = "0" * 40
    raw_path = _write_payload(tmp_path, payload, "fake-commit.json")
    with pytest.raises(PairsReportContractError, match="not a valid repository commit"):
        generate_report(raw_path, repo_root=ROOT)

    payload = _v17_payload(passing=False)
    payload["runtime_versions"]["numpy"] = "0.0.0"
    raw_path = _write_payload(tmp_path, payload, "fake-runtime.json")
    with pytest.raises(PairsReportContractError, match="runtime versions differ"):
        generate_report(raw_path, repo_root=ROOT)


def test_strict_loader_and_deterministic_json_markdown(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"a":1,"a":2}', encoding="utf-8")
    with pytest.raises(PairsReportContractError, match="duplicate JSON key"):
        load_json_artifact(duplicate)

    raw_path = _write_payload(tmp_path, _v17_payload(passing=False))
    report = generate_report(raw_path, repo_root=ROOT)
    first_json = deterministic_json(report)
    second_json = deterministic_json(report)
    first_markdown = render_markdown(report)
    second_markdown = render_markdown(report)

    assert first_json == second_json
    assert first_markdown == second_markdown
    assert first_json.endswith("\n") and first_markdown.endswith("\n")
    assert "NaN" not in first_json and "Infinity" not in first_json
    assert "RED_NO_HOLDOUT" in first_markdown
    assert "holdout çalıştırılmadı" in first_markdown
    assert math.isfinite(float(report["ranking"]["rows"][0]["turnover"]))


def test_cli_defaults_work_outside_repo_and_protect_outputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    raw_path = _write_payload(tmp_path, _v17_payload(passing=False))
    json_output = tmp_path / "report.json"
    markdown_output = tmp_path / "report.md"
    monkeypatch.chdir(tmp_path)

    assert (
        main(
            [
                "--v17-raw",
                str(raw_path),
                "--json-output",
                str(json_output),
                "--markdown-output",
                str(markdown_output),
            ]
        )
        == 0
    )
    assert (
        json.loads(json_output.read_text(encoding="utf-8"))["decision"]["verdict"] == RED_NO_HOLDOUT
    )
    assert markdown_output.read_text(encoding="utf-8").startswith("# Crypto 15m v17 pairs")
    assert "RED_NO_HOLDOUT" in capsys.readouterr().out

    with pytest.raises(PairsReportContractError, match="must be distinct"):
        main(
            [
                "--v17-raw",
                str(raw_path),
                "--json-output",
                str(json_output),
                "--markdown-output",
                str(json_output),
            ]
        )

    with pytest.raises(PairsReportContractError, match="cannot overwrite"):
        main(
            [
                "--v17-raw",
                str(raw_path),
                "--json-output",
                str(ROOT / "src/price_action/lab/crypto_15m_pairs_report.py"),
            ]
        )
