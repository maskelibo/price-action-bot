"""Explicit auxiliary feature coverage for the autonomous feature factory.

Missing alternative data is evidence of unavailability, not permission to
manufacture a proxy.  This module inspects local DuckDB sources read-only and
emits a machine-readable coverage ledger.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb

COVERAGE_SCHEMA = "feature-family-coverage-v1"


def _table_summary(
    path: Path,
    *,
    table: str,
    per_symbol: bool = False,
) -> dict[str, Any]:
    if not path.exists():
        return {
            "source": str(path),
            "table": table,
            "status": "SOURCE_MISSING",
            "rows": 0,
            "min_ts": None,
            "max_ts": None,
            "max_rows_per_symbol": 0,
        }
    try:
        with duckdb.connect(str(path), read_only=True) as con:
            rows, min_ts, max_ts = con.execute(
                f'SELECT count(*), min(ts), max(ts) FROM "{table}"'
            ).fetchone()
            max_per_symbol = 0
            if per_symbol and rows:
                max_per_symbol = con.execute(
                    f'SELECT max(n) FROM (SELECT count(*) AS n FROM "{table}" GROUP BY symbol)'
                ).fetchone()[0]
    except Exception as exc:
        return {
            "source": str(path),
            "table": table,
            "status": "SOURCE_INVALID",
            "rows": 0,
            "min_ts": None,
            "max_ts": None,
            "max_rows_per_symbol": 0,
            "error": f"{type(exc).__name__}:{exc}",
        }
    return {
        "source": str(path),
        "table": table,
        "status": "OBSERVED",
        "rows": int(rows),
        "min_ts": min_ts.isoformat() if min_ts else None,
        "max_ts": max_ts.isoformat() if max_ts else None,
        "max_rows_per_symbol": int(max_per_symbol or 0),
    }


def _feature_names(columns: set[str], prefixes: tuple[str, ...]) -> list[str]:
    return sorted(name for name in columns if name.startswith(prefixes))


def build_feature_coverage(
    *,
    produced_columns: set[str],
    min_observations: int,
    funding_db: Path,
    sentiment_db: Path,
    dominance_db: Path,
    stablecoin_db: Path,
    generated_at: datetime | None = None,
) -> dict[str, Any]:
    """Return coverage without creating a value for any unavailable family."""

    now = (generated_at or datetime.now(UTC)).astimezone(UTC)
    funding = _table_summary(funding_db, table="funding_rates", per_symbol=True)
    oi = _table_summary(funding_db, table="oi_snapshot", per_symbol=True)
    sentiment = _table_summary(sentiment_db, table="fng_daily")
    dominance = _table_summary(dominance_db, table="btc_dominance_daily")
    stablecoin = _table_summary(stablecoin_db, table="stablecoin_supply_daily", per_symbol=True)

    def observed_family(
        family: str,
        source: dict[str, Any],
        features: list[str],
        *,
        effective_rows: int,
    ) -> dict[str, Any]:
        if source["status"] != "OBSERVED":
            status = "UNAVAILABLE_SOURCE"
            reason = source["status"]
        elif effective_rows < min_observations:
            status = "UNAVAILABLE_INSUFFICIENT_HISTORY"
            reason = f"effective_rows={effective_rows}<min_observations={min_observations}"
        elif not features:
            status = "UNAVAILABLE_NOT_IMPLEMENTED"
            reason = "source exists but no causal feature is produced"
        else:
            status = "AVAILABLE"
            reason = "observed local source and causal feature implementation"
        return {
            "family": family,
            "status": status,
            "reason": reason,
            "features": features,
            "feature_count": len(features),
            "source": source,
            "synthetic_values_created": False,
        }

    families = [
        observed_family(
            "funding",
            funding,
            _feature_names(produced_columns, ("funding",)),
            effective_rows=funding["max_rows_per_symbol"],
        ),
        observed_family(
            "sentiment",
            sentiment,
            _feature_names(produced_columns, ("sentiment_",)),
            effective_rows=sentiment["rows"],
        ),
        observed_family(
            "open_interest",
            oi,
            _feature_names(produced_columns, ("oi_", "open_interest_")),
            effective_rows=oi["max_rows_per_symbol"],
        ),
        observed_family(
            "btc_dominance",
            dominance,
            _feature_names(produced_columns, ("dominance_",)),
            effective_rows=dominance["rows"],
        ),
        observed_family(
            "stablecoin_supply",
            stablecoin,
            _feature_names(produced_columns, ("stablecoin_",)),
            effective_rows=stablecoin["max_rows_per_symbol"],
        ),
        {
            "family": "cross_sectional",
            "status": "AVAILABLE"
            if _feature_names(produced_columns, ("xs_",))
            else "UNAVAILABLE_NOT_IMPLEMENTED",
            "reason": "same-close ranks across the loaded local universe"
            if _feature_names(produced_columns, ("xs_",))
            else "fewer than two aligned symbols",
            "features": _feature_names(produced_columns, ("xs_",)),
            "feature_count": len(_feature_names(produced_columns, ("xs_",))),
            "source": {"source": "local aligned market OHLCV", "status": "OBSERVED"},
            "synthetic_values_created": False,
        },
        {
            "family": "calendar_event_time",
            "status": "AVAILABLE",
            "reason": "deterministic UTC timestamp transform",
            "features": _feature_names(produced_columns, ("utc_hour_", "weekday_")),
            "feature_count": len(
                _feature_names(produced_columns, ("utc_hour_", "weekday_"))
            ),
            "source": {"source": "OHLCV timestamp", "status": "OBSERVED"},
            "synthetic_values_created": False,
        },
        {
            "family": "scheduled_macro_event",
            "status": "UNAVAILABLE_NO_SOURCE_CONFIGURED",
            "reason": "no local point-in-time macro-event calendar with release timestamps",
            "features": [],
            "feature_count": 0,
            "source": {"source": None, "status": "SOURCE_MISSING"},
            "synthetic_values_created": False,
        },
    ]
    return {
        "schema_version": COVERAGE_SCHEMA,
        "generated_at": now.isoformat(),
        "min_observations": min_observations,
        "produced_feature_count": len(produced_columns),
        "families": families,
        "unavailable_families": [
            family["family"] for family in families if family["status"] != "AVAILABLE"
        ],
        "all_unavailable_are_explicit": True,
        "synthetic_auxiliary_values_created": False,
    }


__all__ = ["COVERAGE_SCHEMA", "build_feature_coverage"]
