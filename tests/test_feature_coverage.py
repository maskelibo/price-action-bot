"""Auxiliary feature coverage must report missing data without fabrication."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import duckdb

from price_action.lab.feature_coverage import build_feature_coverage


def _event_db(path: Path, ddl: str, rows: list[tuple]) -> None:
    with duckdb.connect(str(path)) as con:
        con.execute(ddl)
        if rows:
            placeholders = ",".join("?" for _ in rows[0])
            table = ddl.split("TABLE ", 1)[1].split("(", 1)[0].strip()
            con.executemany(f"INSERT INTO {table} VALUES ({placeholders})", rows)


def test_missing_oi_dominance_stablecoin_and_event_are_explicit(tmp_path: Path) -> None:
    funding = tmp_path / "funding.duckdb"
    with duckdb.connect(str(funding)) as con:
        con.execute(
            "CREATE TABLE funding_rates(venue VARCHAR, symbol VARCHAR, ts TIMESTAMPTZ, funding_rate DOUBLE)"
        )
        con.execute(
            "CREATE TABLE oi_snapshot(venue VARCHAR, symbol VARCHAR, ts TIMESTAMPTZ, open_interest DOUBLE)"
        )
        for i in range(600):
            con.execute(
                "INSERT INTO funding_rates VALUES ('binance','BTC',?,0.0001)",
                [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=8 * i)],
            )
        for i in range(40):
            con.execute(
                "INSERT INTO oi_snapshot VALUES ('binance','BTC',?,100.0)",
                [datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i)],
            )

    sentiment = tmp_path / "sentiment.duckdb"
    _event_db(
        sentiment,
        "CREATE TABLE fng_daily(ts TIMESTAMPTZ, value INTEGER)",
        [
            (datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=i), i % 100)
            for i in range(600)
        ],
    )
    dominance = tmp_path / "dominance.duckdb"
    _event_db(
        dominance,
        "CREATE TABLE btc_dominance_daily(ts TIMESTAMPTZ, btc_dominance DOUBLE)",
        [
            (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(days=i), 60.0)
            for i in range(90)
        ],
    )
    stablecoin = tmp_path / "stablecoin.duckdb"
    _event_db(
        stablecoin,
        "CREATE TABLE stablecoin_supply_daily(ts TIMESTAMPTZ, symbol VARCHAR, market_cap_usd DOUBLE)",
        [],
    )

    coverage = build_feature_coverage(
        produced_columns={
            "funding",
            "funding_z_30bar",
            "sentiment_value",
            "xs_ret_1bar_rank",
            "utc_hour_sin",
            "weekday_cos",
        },
        min_observations=500,
        funding_db=funding,
        sentiment_db=sentiment,
        dominance_db=dominance,
        stablecoin_db=stablecoin,
    )
    families = {row["family"]: row for row in coverage["families"]}

    assert families["funding"]["status"] == "AVAILABLE"
    assert families["sentiment"]["status"] == "AVAILABLE"
    assert families["open_interest"]["status"] == "UNAVAILABLE_INSUFFICIENT_HISTORY"
    assert families["btc_dominance"]["status"] == "UNAVAILABLE_INSUFFICIENT_HISTORY"
    assert families["stablecoin_supply"]["status"] == "UNAVAILABLE_INSUFFICIENT_HISTORY"
    assert families["scheduled_macro_event"]["status"] == "UNAVAILABLE_NO_SOURCE_CONFIGURED"
    assert coverage["synthetic_auxiliary_values_created"] is False
    assert all(row["synthetic_values_created"] is False for row in coverage["families"])


def test_missing_database_is_reported_not_raised(tmp_path: Path) -> None:
    missing = tmp_path / "missing.duckdb"
    coverage = build_feature_coverage(
        produced_columns={"utc_hour_sin"},
        min_observations=500,
        funding_db=missing,
        sentiment_db=missing,
        dominance_db=missing,
        stablecoin_db=missing,
    )
    families = {row["family"]: row for row in coverage["families"]}
    assert families["sentiment"]["status"] == "UNAVAILABLE_SOURCE"
    assert families["open_interest"]["status"] == "UNAVAILABLE_SOURCE"
    assert coverage["all_unavailable_are_explicit"] is True
