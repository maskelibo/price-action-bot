from __future__ import annotations

import copy
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pytest
import yaml

from price_action.lab import crypto_15m_program as program
from price_action.lab.crypto_15m_event_engine import PortfolioResult

ROOT = Path(__file__).resolve().parents[1]
BASE_PREREG = ROOT / "configs" / "crypto_15m_v16_research_prereg.yaml"


def _base_config() -> dict:
    with BASE_PREREG.open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def _write_prereg(path: Path, config: dict) -> Path:
    path.write_text(yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return path


def _synthetic_frozen_inputs(tmp_path: Path) -> Path:
    config = copy.deepcopy(_base_config())
    symbols = config["universe"]["symbols"]
    start = pd.Timestamp("2024-01-05T00:00:00Z")
    timestamps = pd.date_range(start, periods=340, freq="15min", tz="UTC")
    end = timestamps[-1] + pd.Timedelta(minutes=15)

    market_rows: list[pd.DataFrame] = []
    step = np.arange(len(timestamps), dtype=float)
    btc_returns = 0.0005 * np.sin(step / 7.0) + 0.0002 * np.cos(step / 19.0)
    for position, symbol in enumerate(symbols):
        residual = (position - 8.5) * 0.000002 + 0.00015 * np.sin(
            step / (5.0 + position % 4) + position
        )
        returns = btc_returns if position == 0 else (0.7 + position / 40.0) * btc_returns + residual
        close = (100.0 + position * 10.0) * np.cumprod(1.0 + returns)
        open_ = np.concatenate(([close[0]], close[:-1]))
        frame = pd.DataFrame(
            {
                "venue": "binance",
                "symbol": symbol.replace("/", ""),
                "timeframe": "15m",
                "ts": timestamps,
                "open": open_,
                "high": np.maximum(open_, close) * 1.002,
                "low": np.minimum(open_, close) * 0.998,
                "close": close,
                "volume": 1_000.0 + position * 10.0 + step,
            }
        )
        if symbol == symbols[-1]:
            frame = frame.drop(index=100)
        market_rows.append(frame)
    market_data = pd.concat(market_rows, ignore_index=True)
    market_path = tmp_path / "market.duckdb"
    connection = duckdb.connect(str(market_path))
    try:
        connection.execute(
            """
            CREATE TABLE ohlcv (
                venue VARCHAR, symbol VARCHAR, timeframe VARCHAR, ts TIMESTAMPTZ,
                open DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume DOUBLE
            )
            """
        )
        connection.register("market_input", market_data)
        connection.execute("INSERT INTO ohlcv SELECT * FROM market_input")
    finally:
        connection.close()

    funding_timestamps = pd.date_range(
        start - pd.Timedelta(hours=8), end, freq="8h", inclusive="left", tz="UTC"
    )
    funding_rows: list[dict] = []
    for position, symbol in enumerate(symbols):
        for event_number, timestamp in enumerate(funding_timestamps):
            sign = 1.0 if (position + event_number) % 2 == 0 else -1.0
            funding_rows.append(
                {
                    "venue": "binance",
                    "symbol": f"{symbol}:USDT",
                    "ts": timestamp,
                    "funding_rate": sign * (0.0001 + position * 0.000001),
                    "mark_price": 100.0 + position * 10.0,
                }
            )
    funding_data = pd.DataFrame(funding_rows)
    funding_path = tmp_path / "funding.duckdb"
    connection = duckdb.connect(str(funding_path))
    try:
        connection.execute(
            """
            CREATE TABLE funding_rates (
                venue VARCHAR, symbol VARCHAR, ts TIMESTAMPTZ,
                funding_rate DOUBLE, mark_price DOUBLE
            )
            """
        )
        connection.register("funding_input", funding_data)
        connection.execute("INSERT INTO funding_rates SELECT * FROM funding_input")
    finally:
        connection.close()

    config["snapshots"]["market"].update(
        {
            "path": market_path.name,
            "bytes": market_path.stat().st_size,
            "sha256": program.sha256_file(market_path),
        }
    )
    config["snapshots"]["funding"].update(
        {
            "path": funding_path.name,
            "bytes": funding_path.stat().st_size,
            "sha256": program.sha256_file(funding_path),
        }
    )
    config["time_protocol"]["complete_months_utc"] = [start.isoformat(), end.isoformat()]
    config["time_protocol"]["development"] = [
        start.isoformat(),
        (start + pd.Timedelta(days=2)).isoformat(),
    ]
    development_end = start + pd.Timedelta(days=2)
    fold_step = (end - development_end) / 6
    fold_edges = [development_end + fold_step * position for position in range(7)]
    config["time_protocol"]["expanding_walk_forward"] = [
        [fold_edges[position].isoformat(), fold_edges[position + 1].isoformat()]
        for position in range(6)
    ]
    config["time_protocol"]["gap_policy"]["warmup_bars_after_gap"] = 1
    for cell in config["candidate_cells"]:
        cell["beta_lookback_bars"] = 8
        cell["hold_bars"] = 4
        cell["stop_atr_period"] = 4
        if cell["family"] == "residual_cross_sectional_trend":
            cell["formation_bars"] = 8
        else:
            cell["residual_formation_bars"] = 8
            cell["residual_z_lookback_bars"] = 16
            cell["residual_abs_z_min"] = 0.1
    return _write_prereg(tmp_path / "prereg.yaml", config)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("BTCUSDT", "BTC/USDT"),
        ("eth/usdt", "ETH/USDT"),
        ("SOL-USDT", "SOL/USDT"),
        ("XRP/USDT:USDT", "XRP/USDT"),
        ("AAVE", "AAVE/USDT"),
    ],
)
def test_normalize_usdt_symbol(raw: str, expected: str) -> None:
    assert program.normalize_usdt_symbol(raw) == expected


@pytest.mark.subprocess
def test_dry_and_smoke_never_access_snapshot_paths(tmp_path: Path) -> None:
    config = _base_config()
    config["snapshots"]["market"]["path"] = "definitely-missing-market.duckdb"
    config["snapshots"]["funding"]["path"] = "definitely-missing-funding.duckdb"
    prereg = _write_prereg(tmp_path / "prereg.yaml", config)

    dry = program.dry_run(prereg)
    smoke = program.smoke_run(prereg)

    assert dry["mode"] == "DRY_RUN_NO_SNAPSHOT_ACCESS"
    assert smoke["mode"] == "SMOKE_IN_MEMORY_NO_SNAPSHOT_ACCESS"
    assert dry["snapshots"]["market"]["status"] == "NOT_ACCESSED"
    assert smoke["smoke"]["closed_trades"] == 1
    assert smoke["smoke"]["reference_symbol_traded"] is False


def test_snapshot_verifier_rejects_hash_mismatch(tmp_path: Path) -> None:
    snapshot = tmp_path / "tiny.duckdb"
    snapshot.write_bytes(b"frozen")
    spec = {"path": snapshot.name, "bytes": 6, "sha256": "0" * 64}

    with pytest.raises(ValueError, match="SHA256 mismatch"):
        program.verify_frozen_snapshot("market", spec, repo_root=tmp_path)


def test_portfolio_result_adapter_uses_curve_pct_points_and_positive_dd() -> None:
    result = PortfolioResult(
        trades=(),
        equity_curve=(
            (datetime(2024, 1, 31, 23, 45, tzinfo=UTC), 110.0),
            (datetime(2024, 2, 29, 23, 45, tzinfo=UTC), 121.0),
        ),
        monthly_returns=(("2024-01", 999.0),),  # Must not be trusted by the adapter.
        rejections=(),
        initial_equity=100.0,
        final_equity=121.0,
        max_drawdown=-0.123,
        total_execution_cost=7.0,
        total_funding_cashflow=-2.0,
        open_position_count=1,
        accrued_exit_cost=3.0,
    )

    adapted = program._scenario_result(
        result,
        windows={
            "complete": (
                pd.Timestamp("2024-01-01T00:00:00Z"),
                pd.Timestamp("2024-03-01T00:00:00Z"),
            )
        },
    )
    complete = adapted["windows"]["complete"]

    assert complete["monthly_returns_pct"] == pytest.approx({"2024-01": 10.0, "2024-02": 10.0})
    assert complete["monthly_returns_unit"] == "percentage_points"
    assert complete["max_mtm_drawdown_pct"] == pytest.approx(0.0)
    assert adapted["accrued_exit_cost"] == pytest.approx(3.0)


@pytest.mark.subprocess
def test_synthetic_duckdb_full_program_is_aligned_dual_funding_and_deterministic(
    tmp_path: Path,
) -> None:
    prereg = _synthetic_frozen_inputs(tmp_path)

    payload = program.run_program(prereg, repo_root=tmp_path)

    assert payload["mode"] == "FULL_FROZEN_REPLAY"
    assert isinstance(payload["evidence_eligible"], bool)
    assert payload["snapshots"]["market"]["status"] == "VERIFIED"
    assert payload["market_alignment"]["frame_count"] == 18
    assert payload["market_alignment"]["common_rows"] == 339
    assert payload["market_alignment"]["dropped_rows_by_symbol"]["ALGO/USDT"] == 0
    assert payload["market_alignment"]["dropped_rows_by_symbol"]["BTC/USDT"] == 1
    assert payload["funding"]["signal_column"] == "funding_rate"
    assert payload["funding"]["engine_column"] == "rate"
    assert payload["funding"]["engine_event_count"] > 0
    assert payload["intent_generation"]["frame_universe_count"] == 18
    assert payload["intent_generation"]["ranking_universe_count"] == 17
    assert payload["intent_generation"]["reference_symbol_intents"] == 0
    assert set(payload["results"]) == set(payload["candidate_ids"])
    assert all(
        tuple(scenarios) == program.SCENARIO_ORDER for scenarios in payload["results"].values()
    )
    for scenarios in payload["results"].values():
        for result in scenarios.values():
            assert result["windows"]["complete"]["monthly_returns_unit"] == "percentage_points"
            assert result["windows"]["complete"]["max_mtm_drawdown_pct"] >= 0.0
            assert len(result["windows"]["pseudo_oos"]["monthly_returns_pct"]) == 1
            assert "accrued_exit_cost" in result

    rendered = program.deterministic_json(payload)
    assert rendered == program.deterministic_json(payload)
    assert '"NaN"' not in rendered
    assert "Infinity" not in rendered
