from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import yaml

from price_action.lab.forex_readiness import (
    DEFER,
    READY,
    evaluate_forex_readiness,
    forex_market_age_seconds,
)


def _write_db(
    path: Path,
    *,
    venue: str = "histdata",
    timestamp: str = "2026-07-08T08:00:00Z",
    bad_ohlc: bool = False,
    include_spread: bool = True,
) -> None:
    con = duckdb.connect(str(path))
    spread_sql = ", spread_bps DOUBLE" if include_spread else ""
    con.execute(
        f"""
        CREATE TABLE ohlcv (
            venue VARCHAR NOT NULL,
            symbol VARCHAR NOT NULL,
            timeframe VARCHAR NOT NULL,
            ts TIMESTAMP WITH TIME ZONE NOT NULL,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE
            {spread_sql}
        )
        """
    )
    columns = "venue, symbol, timeframe, ts, open, high, low, close"
    placeholders = "?, ?, ?, ?, ?, ?, ?, ?"
    values: list[object] = [
        venue,
        "EUR/USD",
        "4h",
        timestamp,
        1.10,
        1.09 if bad_ohlc else 1.12,
        1.08,
        1.11,
    ]
    if include_spread:
        columns += ", spread_bps"
        placeholders += ", ?"
        values.append(1.5)
    con.execute(f"INSERT INTO ohlcv ({columns}) VALUES ({placeholders})", values)
    con.close()


def _write_config(
    path: Path,
    db_path: Path,
    *,
    broker: bool | None = True,
    trusted_venue: str = "histdata",
) -> None:
    def implementation_contract(name: str) -> dict[str, str]:
        implementation = path.parent / f"{name}_implementation.py"
        implementation.write_text(f'CAPABILITY = "{name}"\n', encoding="utf-8")
        contract = path.parent / f"{name}_capability.json"
        contract.write_text(
            json.dumps(
                {
                    "schema_version": "forex-capability-v1",
                    "capability": name,
                    "ready": True,
                    "paper_only": True,
                    "live_authorized": False,
                    "testnet_authorized": False,
                    "order_authorized": False,
                    "implementation_artifacts": [
                        {
                            "path": str(implementation),
                            "sha256": hashlib.sha256(implementation.read_bytes()).hexdigest(),
                        }
                    ],
                },
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        return {"contract_file": str(contract)}

    capabilities: dict[str, object] = {
        "feed": True,
        "local_runner": implementation_contract("local_runner"),
    }
    if broker is True:
        capabilities["paper_broker"] = implementation_contract("paper_broker")
    elif broker is False:
        capabilities["paper_broker"] = False
    payload = {
        "schema_version": "forex-autonomy-v1",
        "database": {"path": str(db_path)},
        "data": {
            "trusted_venues": [trusted_venue],
            "required_series": [{"venue": trusted_venue, "symbol": "EUR/USD", "timeframe": "4h"}],
            "min_rows_per_series": 1,
            "spread": {"column": "spread_bps", "min_value": 0.0, "max_value": 20.0},
            "freshness": {
                "max_market_age_bars": 2.0,
                "grace_hours": 2.0,
                "future_tolerance_hours": 1.0,
                "market_hours": {
                    "friday_close_hour_utc": 22,
                    "sunday_open_hour_utc": 22,
                },
            },
        },
        "capabilities": capabilities,
        "policy": {
            "permanent_mode": "PAPER_ONLY",
            "live_authorized": False,
            "testnet_authorized": False,
            "order_authorized": False,
        },
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def _codes(report: dict[str, object]) -> set[str]:
    return {item["code"] for item in report["reasons"]}  # type: ignore[index, union-attr]


def test_fresh_trusted_data_and_local_contracts_are_ready(tmp_path: Path) -> None:
    db = tmp_path / "forex.duckdb"
    cfg = tmp_path / "config.yaml"
    _write_db(db)
    _write_config(cfg, db)

    before = db.read_bytes()
    report = evaluate_forex_readiness(cfg, now="2026-07-08T12:00:00Z")

    assert report["status"] == READY
    assert report["reasons"] == []
    assert report["database"]["access_mode"] == "read_only"
    assert report["policy"]["mode"] == "PAPER_ONLY"
    assert report["authorization"] == {"live": False, "testnet": False, "orders": False}
    assert db.read_bytes() == before


def test_stale_max_timestamp_defers(tmp_path: Path) -> None:
    db = tmp_path / "forex.duckdb"
    cfg = tmp_path / "config.yaml"
    _write_db(db, timestamp="2026-07-06T08:00:00Z")
    _write_config(cfg, db)

    report = evaluate_forex_readiness(cfg, now="2026-07-08T12:00:00Z")

    assert report["status"] == DEFER
    assert "DATA_STALE" in _codes(report)


def test_weekend_closure_does_not_make_friday_data_stale(tmp_path: Path) -> None:
    db = tmp_path / "forex.duckdb"
    cfg = tmp_path / "config.yaml"
    _write_db(db, timestamp="2026-07-10T20:00:00Z")  # Friday
    _write_config(cfg, db)

    report = evaluate_forex_readiness(cfg, now="2026-07-12T20:00:00Z")  # Sunday pre-open

    assert report["status"] == READY
    series = next(iter(report["database"]["series"].values()))
    assert series["market_age_hours"] == 2.0
    assert (
        forex_market_age_seconds(
            datetime(2026, 7, 10, 20, tzinfo=UTC),
            datetime(2026, 7, 12, 20, tzinfo=UTC),
        )
        == 2 * 3600
    )


def test_bad_ohlc_defers(tmp_path: Path) -> None:
    db = tmp_path / "forex.duckdb"
    cfg = tmp_path / "config.yaml"
    _write_db(db, bad_ohlc=True)
    _write_config(cfg, db)

    report = evaluate_forex_readiness(cfg, now="2026-07-08T12:00:00Z")

    assert report["status"] == DEFER
    assert "OHLC_VALUES_INVALID" in _codes(report)


def test_untrusted_and_proven_broken_venue_defers(tmp_path: Path) -> None:
    db = tmp_path / "forex.duckdb"
    cfg = tmp_path / "config.yaml"
    _write_db(db, venue="yfinance")
    _write_config(cfg, db, trusted_venue="histdata")

    report = evaluate_forex_readiness(cfg, now="2026-07-08T12:00:00Z")

    assert report["status"] == DEFER
    assert "PROVEN_BROKEN_VENUE_OBSERVED" in _codes(report)
    assert "UNTRUSTED_VENUE_OBSERVED" in _codes(report)


def test_proven_broken_venue_cannot_be_whitelisted(tmp_path: Path) -> None:
    db = tmp_path / "forex.duckdb"
    cfg = tmp_path / "config.yaml"
    _write_db(db, venue="yfinance")
    _write_config(cfg, db, trusted_venue="yfinance")

    report = evaluate_forex_readiness(cfg, now="2026-07-08T12:00:00Z")

    assert report["status"] == DEFER
    assert "PROVEN_BROKEN_VENUE_CONFIGURED" in _codes(report)


def test_missing_paper_broker_contract_defers(tmp_path: Path) -> None:
    db = tmp_path / "forex.duckdb"
    cfg = tmp_path / "config.yaml"
    _write_db(db)
    _write_config(cfg, db, broker=None)

    report = evaluate_forex_readiness(cfg, now="2026-07-08T12:00:00Z")

    assert report["status"] == DEFER
    assert "CAPABILITY_PAPER_BROKER_UNAVAILABLE" in _codes(report)


def test_valid_capability_files_can_replace_explicit_booleans(tmp_path: Path) -> None:
    db = tmp_path / "forex.duckdb"
    cfg = tmp_path / "config.yaml"
    _write_db(db)
    _write_config(cfg, db)
    report = evaluate_forex_readiness(cfg, now="2026-07-08T12:00:00Z")

    assert report["status"] == READY
    assert report["capabilities"]["feed"]["source"] == "explicit_boolean"
    for name in ("paper_broker", "local_runner"):
        capability = report["capabilities"][name]
        assert capability["source"] == "contract_file"
        assert capability["content_pinned"] is True


def test_implementation_capability_boolean_true_is_not_proof(tmp_path: Path) -> None:
    db = tmp_path / "forex.duckdb"
    cfg = tmp_path / "config.yaml"
    _write_db(db)
    _write_config(cfg, db)
    payload = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    payload["capabilities"]["paper_broker"] = True
    cfg.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    report = evaluate_forex_readiness(cfg, now="2026-07-08T12:00:00Z")

    assert report["status"] == DEFER
    assert "CAPABILITY_PAPER_BROKER_UNAVAILABLE" in _codes(report)


def test_changed_implementation_invalidates_content_pin(tmp_path: Path) -> None:
    db = tmp_path / "forex.duckdb"
    cfg = tmp_path / "config.yaml"
    _write_db(db)
    _write_config(cfg, db)
    payload = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    contract_path = Path(payload["capabilities"]["local_runner"]["contract_file"])
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    implementation = Path(contract["implementation_artifacts"][0]["path"])
    implementation.write_text("CAPABILITY = 'tampered'\n", encoding="utf-8")

    report = evaluate_forex_readiness(cfg, now="2026-07-08T12:00:00Z")

    assert report["status"] == DEFER
    assert "CAPABILITY_LOCAL_RUNNER_UNAVAILABLE" in _codes(report)
    assert report["capabilities"]["local_runner"]["content_pinned"] is False


def test_numeric_true_cannot_impersonate_boolean_capability_lock(tmp_path: Path) -> None:
    db = tmp_path / "forex.duckdb"
    cfg = tmp_path / "config.yaml"
    _write_db(db)
    _write_config(cfg, db)
    payload = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    contract_path = Path(payload["capabilities"]["paper_broker"]["contract_file"])
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    contract["ready"] = 1
    contract_path.write_text(json.dumps(contract), encoding="utf-8")

    report = evaluate_forex_readiness(cfg, now="2026-07-08T12:00:00Z")

    assert report["status"] == DEFER
    assert "CAPABILITY_PAPER_BROKER_UNAVAILABLE" in _codes(report)


def test_repository_local_capability_contracts_match_implementation_content() -> None:
    root = Path(__file__).resolve().parents[1]
    autonomy = yaml.safe_load((root / "configs" / "forex_autonomy.yaml").read_text())

    assert autonomy["capabilities"]["feed"] is False
    for name in ("paper_broker", "local_runner"):
        contract_path = root / autonomy["capabilities"][name]["contract_file"]
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        assert contract["capability"] == name
        assert contract["paper_only"] is True
        assert contract["live_authorized"] is False
        assert contract["testnet_authorized"] is False
        assert contract["order_authorized"] is False
        for artifact in contract["implementation_artifacts"]:
            implementation = root / artifact["path"]
            assert hashlib.sha256(implementation.read_bytes()).hexdigest() == artifact["sha256"]


def test_missing_observed_spread_defers(tmp_path: Path) -> None:
    db = tmp_path / "forex.duckdb"
    cfg = tmp_path / "config.yaml"
    _write_db(db, include_spread=False)
    _write_config(cfg, db)

    report = evaluate_forex_readiness(cfg, now="2026-07-08T12:00:00Z")

    assert report["status"] == DEFER
    assert "SPREAD_DATA_MISSING" in _codes(report)


def test_unsafe_policy_request_never_changes_authorization(tmp_path: Path) -> None:
    db = tmp_path / "forex.duckdb"
    cfg = tmp_path / "config.yaml"
    _write_db(db)
    _write_config(cfg, db)
    payload = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    payload["policy"]["live_authorized"] = True
    cfg.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    report = evaluate_forex_readiness(cfg, now="2026-07-08T12:00:00Z")

    assert report["status"] == DEFER
    assert report["authorization"]["live"] is False
    assert report["authorization"]["testnet"] is False
    assert report["authorization"]["orders"] is False
    assert "POLICY_CONTRACT_UNSAFE" in _codes(report)


def test_numeric_false_cannot_impersonate_boolean_policy_lock(tmp_path: Path) -> None:
    db = tmp_path / "forex.duckdb"
    cfg = tmp_path / "config.yaml"
    _write_db(db)
    _write_config(cfg, db)
    payload = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    payload["policy"]["live_authorized"] = 0
    cfg.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")

    report = evaluate_forex_readiness(cfg, now="2026-07-08T12:00:00Z")

    assert report["status"] == DEFER
    assert report["authorization"] == {"live": False, "testnet": False, "orders": False}
    assert "POLICY_CONTRACT_UNSAFE" in _codes(report)
