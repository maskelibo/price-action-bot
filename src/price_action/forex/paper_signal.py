"""Fail-closed local Forex signal recorder and permanent-paper coordinator.

The coordinator reads only closed bars from one trusted venue.  It requires a
successful Forex readiness report before creating or mutating either journal,
then invokes the separate deterministic local paper broker.  No historical
result is represented as deployment evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import yaml

from price_action.contracts import Signal
from price_action.forex.paper_broker import (
    LocalPaperBrokerConfig,
    read_weekly_broker_kpis,
    readiness_scope_blockers,
    run_local_paper_broker_once,
)
from price_action.lab.forex_readiness import evaluate_forex_readiness

REPO_ROOT = Path(__file__).resolve().parents[3]
MODE = "SIGNAL_ONLY_PAPER"
STATUS_SCHEMA = "forex-paper-signal-status-v2"
JOURNAL_SCHEMA = "forex-paper-signal-journal-v1"
CONFIG_SCHEMA = "forex-paper-signal-config-v1"
ORDER_PATH_ENABLED = False
NETWORK_PATH_ENABLED = False
DEPLOYMENT_EVIDENCE = False

_TF_DELTA = {
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SYMBOL_RE = re.compile(r"^[A-Z]{3}/[A-Z]{3}$")

SignalDetector = Callable[[pd.DataFrame, "ForexPaperConfig"], list[Signal]]


def _safe_repo_path(value: str | Path, *, root: Path, label: str) -> Path:
    root = root.resolve()
    raw = Path(value).expanduser()
    candidate = raw if raw.is_absolute() else root / raw
    if candidate.is_symlink():
        raise ValueError(f"{label} cannot be a symlink")
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} escapes repository root: {value!s}") from exc
    return resolved


def _json_hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str | None:
    if path.is_symlink() or not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _utc(value: datetime | pd.Timestamp | str, *, field: str) -> datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return ts.tz_convert("UTC").to_pydatetime()


@dataclass(frozen=True)
class ForexPaperConfig:
    """Strict configuration for the local, permanent-paper loop."""

    market_db: Path
    journal_db: Path
    broker_db: Path
    status_path: Path
    readiness_config: Path
    symbols: tuple[str, ...] = ("EUR/USD",)
    venue: str = "histdata"
    timeframe: str = "4h"
    spread_column: str = "spread_bps"
    strategy: str = "equal_highs_sweep"
    max_feed_age_hours: float = 72.0
    min_history_bars: int = 250
    atr_min_pct: float = 0.0008
    paper_notional_usd: float = 1_000.0
    risk_reference: Path | None = None
    config_path: Path | None = None
    mode: str = MODE
    permanent_paper_only: bool = True
    allow_order_submission: bool = False
    allow_network: bool = False

    def __post_init__(self) -> None:
        if self.mode != MODE:
            raise ValueError(f"mode must be exactly {MODE}")
        if self.permanent_paper_only is not True:
            raise ValueError("permanent_paper_only must be boolean true")
        if self.allow_order_submission is not False or self.allow_network is not False:
            raise ValueError("order submission and network access must be boolean false")
        if self.venue != self.venue.strip().lower() or not self.venue:
            raise ValueError("venue must be normalized lowercase")
        if self.timeframe not in _TF_DELTA:
            raise ValueError(f"unsupported timeframe: {self.timeframe}")
        if not self.symbols or any(_SYMBOL_RE.fullmatch(item) is None for item in self.symbols):
            raise ValueError("symbols must be canonical FX pairs")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("symbols must be unique")
        if _IDENTIFIER_RE.fullmatch(self.spread_column) is None:
            raise ValueError("spread_column must be a safe SQL identifier")
        if not math.isfinite(self.max_feed_age_hours) or self.max_feed_age_hours <= 0:
            raise ValueError("max_feed_age_hours must be finite and positive")
        if self.min_history_bars < 50:
            raise ValueError("min_history_bars must be at least 50")
        if not math.isfinite(self.paper_notional_usd) or self.paper_notional_usd <= 0:
            raise ValueError("paper_notional_usd must be finite and positive")
        db_paths = {self.market_db.resolve(), self.journal_db.resolve(), self.broker_db.resolve()}
        if len(db_paths) != 3:
            raise ValueError("market, signal, and paper-broker databases must be separate")
        for label, path in (
            ("market_db", self.market_db),
            ("journal_db", self.journal_db),
            ("broker_db", self.broker_db),
            ("status_path", self.status_path),
            ("readiness_config", self.readiness_config),
        ):
            if path.is_symlink():
                raise ValueError(f"{label} cannot be a symlink")

    @classmethod
    def from_yaml(cls, path: str | Path, *, repo_root: Path = REPO_ROOT) -> ForexPaperConfig:
        root = repo_root.resolve()
        config_path = _safe_repo_path(path, root=root, label="config path")
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("forex paper config must be a mapping")
        if raw.get("schema_version") != CONFIG_SCHEMA:
            raise ValueError(f"schema_version must be {CONFIG_SCHEMA}")
        locks = raw.get("safety_locks") or {}
        data = raw.get("data") or {}
        output = raw.get("output") or {}
        strategy = raw.get("strategy") or {}
        broker = raw.get("paper_broker") or {}
        readiness = raw.get("readiness") or {}
        if not all(
            isinstance(section, dict)
            for section in (locks, data, output, strategy, broker, readiness)
        ):
            raise ValueError("forex paper config sections must be mappings")

        def resolve(value: str | Path, *, label: str) -> Path:
            return _safe_repo_path(value, root=root, label=label)

        return cls(
            market_db=resolve(data.get("market_db", "data/forex_market.duckdb"), label="market_db"),
            journal_db=resolve(
                output.get("journal_db", "data/forex_paper_signals.duckdb"),
                label="journal_db",
            ),
            broker_db=resolve(
                output.get("broker_db", "data/forex_paper_broker.duckdb"),
                label="broker_db",
            ),
            status_path=resolve(
                output.get("status_path", "data/state/forex_paper_status.json"),
                label="status_path",
            ),
            readiness_config=resolve(
                readiness.get("config", "configs/forex_autonomy.yaml"),
                label="readiness config",
            ),
            symbols=tuple(str(item).strip().upper() for item in data.get("symbols", ["EUR/USD"])),
            venue=str(data.get("venue", "histdata")).strip().lower(),
            timeframe=str(data.get("timeframe", "4h")).strip().lower(),
            spread_column=str(data.get("spread_column", "spread_bps")),
            strategy=str(strategy.get("name", "equal_highs_sweep")),
            max_feed_age_hours=float(data.get("max_feed_age_hours", 72.0)),
            min_history_bars=int(data.get("min_history_bars", 250)),
            atr_min_pct=float(strategy.get("atr_min_pct", 0.0008)),
            paper_notional_usd=float(broker.get("notional_usd", 1_000.0)),
            risk_reference=resolve(
                raw.get("risk_reference", "configs/risk_forex.yaml"),
                label="risk_reference",
            ),
            config_path=config_path,
            mode=str(raw.get("mode", "")),
            permanent_paper_only=locks.get("permanent_paper_only", False),
            allow_order_submission=locks.get("allow_order_submission", True),
            allow_network=locks.get("allow_network", True),
        )

    @property
    def config_hash(self) -> str:
        return _json_hash(
            {
                "schema": STATUS_SCHEMA,
                "mode": self.mode,
                "market_db": str(self.market_db.resolve()),
                "journal_db": str(self.journal_db.resolve()),
                "broker_db": str(self.broker_db.resolve()),
                "readiness_config": str(self.readiness_config.resolve()),
                "readiness_config_sha256": _file_hash(self.readiness_config),
                "symbols": self.symbols,
                "venue": self.venue,
                "timeframe": self.timeframe,
                "spread_column": self.spread_column,
                "strategy": self.strategy,
                "max_feed_age_hours": self.max_feed_age_hours,
                "min_history_bars": self.min_history_bars,
                "atr_min_pct": self.atr_min_pct,
                "paper_notional_usd": self.paper_notional_usd,
                "permanent_paper_only": self.permanent_paper_only,
                "allow_order_submission": self.allow_order_submission,
                "allow_network": self.allow_network,
            }
        )

    def broker_config(self) -> LocalPaperBrokerConfig:
        return LocalPaperBrokerConfig(
            market_db=self.market_db,
            signal_db=self.journal_db,
            broker_db=self.broker_db,
            readiness_config=self.readiness_config,
            venue=self.venue,
            symbols=self.symbols,
            timeframe=self.timeframe,
            spread_column=self.spread_column,
            paper_notional_usd=self.paper_notional_usd,
        )


def _empty_signal_kpis(as_of: datetime) -> dict[str, Any]:
    return {
        "window_start": (as_of - timedelta(days=7)).isoformat(),
        "window_end": as_of.isoformat(),
        "runs": 0,
        "fresh_runs": 0,
        "blocked_runs": 0,
        "new_signals": 0,
        "duplicate_signals": 0,
        "signals": 0,
        "long_signals": 0,
        "short_signals": 0,
    }


class ForexSignalJournal:
    """Separate idempotent journal for paper signals and successful loop runs."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(self.path)) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS signal_events (
                    signal_id VARCHAR PRIMARY KEY,
                    decision_bar_ts TIMESTAMPTZ NOT NULL,
                    decision_bar_close_ts TIMESTAMPTZ NOT NULL,
                    recorded_at TIMESTAMPTZ NOT NULL,
                    symbol VARCHAR NOT NULL,
                    timeframe VARCHAR NOT NULL,
                    direction VARCHAR NOT NULL,
                    pattern_id VARCHAR NOT NULL,
                    confluence_score DOUBLE NOT NULL,
                    sl_price DOUBLE NOT NULL,
                    tp_price DOUBLE NOT NULL,
                    manifest_hash VARCHAR,
                    metadata_json VARCHAR NOT NULL,
                    mode VARCHAR NOT NULL,
                    deployment_evidence BOOLEAN NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS loop_runs (
                    run_id VARCHAR PRIMARY KEY,
                    evaluated_at TIMESTAMPTZ NOT NULL,
                    feed_status VARCHAR NOT NULL,
                    verdict VARCHAR NOT NULL,
                    feed_age_hours DOUBLE,
                    source_last_close_ts TIMESTAMPTZ,
                    configured_symbols INTEGER NOT NULL,
                    new_signals INTEGER NOT NULL,
                    duplicate_signals INTEGER NOT NULL,
                    config_hash VARCHAR NOT NULL,
                    mode VARCHAR NOT NULL,
                    order_path_enabled BOOLEAN NOT NULL,
                    network_path_enabled BOOLEAN NOT NULL,
                    deployment_evidence BOOLEAN NOT NULL,
                    detail_json VARCHAR NOT NULL
                )
                """
            )

    def record_signal(
        self,
        signal: Signal,
        *,
        recorded_at: datetime,
        timeframe_delta: timedelta,
        config_hash: str,
    ) -> bool:
        decision_ts = _utc(signal.ts, field="signal timestamp")
        signal_id = _json_hash(
            {
                "config_hash": config_hash,
                "strategy_manifest": signal.manifest_hash,
                "fingerprint": signal.fingerprint(),
            }
        )
        with duckdb.connect(str(self.path)) as con:
            inserted = con.execute(
                """
                INSERT INTO signal_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (signal_id) DO NOTHING RETURNING signal_id
                """,
                [
                    signal_id,
                    decision_ts,
                    decision_ts + timeframe_delta,
                    recorded_at,
                    signal.symbol,
                    signal.timeframe,
                    signal.direction,
                    signal.pattern_id,
                    signal.confluence_score,
                    signal.sl_price,
                    signal.tp_price,
                    signal.manifest_hash,
                    json.dumps(signal.metadata, sort_keys=True, default=str),
                    MODE,
                    DEPLOYMENT_EVIDENCE,
                ],
            ).fetchone()
        return inserted is not None

    def record_run(self, row: dict[str, Any]) -> None:
        with duckdb.connect(str(self.path)) as con:
            con.execute(
                """
                INSERT INTO loop_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (run_id) DO UPDATE SET
                    feed_status=excluded.feed_status, verdict=excluded.verdict,
                    new_signals=excluded.new_signals,
                    duplicate_signals=excluded.duplicate_signals,
                    detail_json=excluded.detail_json
                """,
                [
                    row["run_id"],
                    row["evaluated_at"],
                    row["feed_status"],
                    row["verdict"],
                    row.get("feed_age_hours"),
                    row.get("source_last_close_ts"),
                    row["configured_symbols"],
                    row["new_signals"],
                    row["duplicate_signals"],
                    row["config_hash"],
                    MODE,
                    ORDER_PATH_ENABLED,
                    NETWORK_PATH_ENABLED,
                    DEPLOYMENT_EVIDENCE,
                    json.dumps(row.get("detail", {}), sort_keys=True, default=str),
                ],
            )

    def weekly_kpis(self, *, as_of: datetime) -> dict[str, Any]:
        return read_weekly_signal_kpis(self.path, as_of=as_of)


def read_weekly_signal_kpis(path: Path, *, as_of: datetime) -> dict[str, Any]:
    """Read signal KPIs without creating or mutating the signal journal."""

    as_of = _utc(as_of, field="as_of")
    if path.is_symlink() or not path.is_file():
        return _empty_signal_kpis(as_of)
    since = as_of - timedelta(days=7)
    try:
        with duckdb.connect(str(path), read_only=True) as con:
            run = con.execute(
                """
                SELECT count(*), count(*) FILTER (WHERE feed_status='FRESH'),
                       count(*) FILTER (WHERE feed_status!='FRESH'),
                       coalesce(sum(new_signals), 0), coalesce(sum(duplicate_signals), 0)
                FROM loop_runs WHERE evaluated_at BETWEEN ? AND ?
                """,
                [since, as_of],
            ).fetchone()
            sig = con.execute(
                """
                SELECT count(*), count(*) FILTER (WHERE direction='long'),
                       count(*) FILTER (WHERE direction='short')
                FROM signal_events WHERE recorded_at BETWEEN ? AND ?
                """,
                [since, as_of],
            ).fetchone()
    except duckdb.Error:
        return _empty_signal_kpis(as_of)
    return {
        "window_start": since.isoformat(),
        "window_end": as_of.isoformat(),
        "runs": int(run[0]),
        "fresh_runs": int(run[1]),
        "blocked_runs": int(run[2]),
        "new_signals": int(run[3]),
        "duplicate_signals": int(run[4]),
        "signals": int(sig[0]),
        "long_signals": int(sig[1]),
        "short_signals": int(sig[2]),
    }


def _load_complete_bars(
    config: ForexPaperConfig,
    *,
    symbol: str,
    as_of: datetime,
) -> pd.DataFrame:
    if config.market_db.is_symlink() or not config.market_db.is_file():
        return pd.DataFrame()
    spread = f'"{config.spread_column}"'
    with duckdb.connect(str(config.market_db), read_only=True) as con:
        columns = {
            row[0]
            for row in con.execute(
                """
                SELECT column_name FROM information_schema.columns
                WHERE table_schema='main' AND table_name='ohlcv'
                """
            ).fetchall()
        }
        volume = "volume" if "volume" in columns else "0.0 AS volume"
        frame = con.execute(
            f"""
            SELECT ts, open, high, low, close, {volume}, {spread} AS observed_spread_bps
            FROM ohlcv
            WHERE lower(venue)=? AND upper(symbol)=? AND lower(timeframe)=?
            ORDER BY ts
            """,
            [config.venue, symbol, config.timeframe],
        ).fetchdf()
    if frame.empty:
        return frame
    if not isinstance(frame["ts"].dtype, pd.DatetimeTZDtype):
        raise ValueError(f"timezone-aware source timestamps required for {symbol}")
    frame["ts"] = pd.to_datetime(frame["ts"], utc=True)
    delta = _TF_DELTA[config.timeframe]
    frame["bar_close_ts"] = frame["ts"] + delta
    frame = frame.loc[frame["bar_close_ts"] <= pd.Timestamp(as_of)].copy()
    duplicated = frame["ts"].duplicated(keep=False)
    if bool(duplicated.any()):
        raise ValueError(f"duplicate timestamps for {symbol}: {int(duplicated.sum())}")
    frame = frame.sort_values("ts").reset_index(drop=True)
    if frame.empty:
        return frame
    numeric = ["open", "high", "low", "close", "observed_spread_bps"]
    finite = frame[numeric].apply(lambda column: column.map(math.isfinite)).all(axis=1)
    valid = frame[numeric].notna().all(axis=1) & finite
    valid &= (frame[["open", "high", "low", "close"]] > 0).all(axis=1)
    valid &= frame["observed_spread_bps"] >= 0
    valid &= frame["high"] >= frame[["open", "close", "low"]].max(axis=1)
    valid &= frame["low"] <= frame[["open", "close", "high"]].min(axis=1)
    if not bool(valid.all()):
        raise ValueError(f"invalid OHLC/spread rows for {symbol}: {int((~valid).sum())}")
    frame["venue"] = config.venue
    frame["symbol"] = symbol
    frame["timeframe"] = config.timeframe
    return frame


def _default_detector(frame: pd.DataFrame, config: ForexPaperConfig) -> list[Signal]:
    if config.strategy != "equal_highs_sweep":
        raise ValueError(f"unsupported local forex strategy: {config.strategy}")
    from price_action.strategies.equal_highs_sweep import (
        EqualHighsSweepStrategy,
        _default_manifest,
    )

    manifest = _default_manifest()
    manifest.signals.filters.atr_min_pct = config.atr_min_pct
    return EqualHighsSweepStrategy(manifest).generate_signals(frame)


def _write_status(path: Path, status: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(status, indent=2, sort_keys=True, default=str) + "\n").encode()
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _defer_status(
    config: ForexPaperConfig,
    *,
    evaluated_at: datetime,
    blockers: list[str],
    readiness: dict[str, Any],
    verdict: str = "DEFER_READINESS",
) -> dict[str, Any]:
    signal_kpis = read_weekly_signal_kpis(config.journal_db, as_of=evaluated_at)
    broker_kpis = read_weekly_broker_kpis(config.broker_db, as_of=evaluated_at)
    status = {
        "schema_version": STATUS_SCHEMA,
        "journal_schema": JOURNAL_SCHEMA,
        "evaluated_at": evaluated_at.isoformat(),
        "mode": MODE,
        "verdict": verdict,
        "feed_status": "BLOCKED",
        "blockers": blockers,
        "readiness_status": readiness.get("status"),
        "readiness_reasons": readiness.get("reasons", []),
        "new_signals": 0,
        "duplicate_signals": 0,
        "weekly_kpis": {"signals": signal_kpis, "paper_trades": broker_kpis},
        "config_hash": config.config_hash,
        "market_db": str(config.market_db),
        "journal_db": str(config.journal_db),
        "broker_db": str(config.broker_db),
        "journal_mutated": False,
        "broker_db_mutated": False,
        "permanent_paper_only": True,
        "order_path_enabled": ORDER_PATH_ENABLED,
        "network_path_enabled": NETWORK_PATH_ENABLED,
        "deployment_evidence": DEPLOYMENT_EVIDENCE,
        "historical_eurusd_4h_result_counts_as_deployment_evidence": False,
    }
    _write_status(config.status_path, status)
    return status


def run_forex_signal_once(
    config: ForexPaperConfig,
    *,
    as_of: datetime | None = None,
    detector: SignalDetector | None = None,
) -> dict[str, Any]:
    """Run one readiness-gated signal and deterministic local-paper pass."""

    evaluated_at = _utc(as_of or datetime.now(UTC), field="as_of")
    broker_config = config.broker_config()
    readiness = evaluate_forex_readiness(
        config.readiness_config,
        now=evaluated_at,
        db_path_override=config.market_db,
    )
    readiness_blockers = readiness_scope_blockers(readiness, broker_config)
    if readiness_blockers:
        return _defer_status(
            config,
            evaluated_at=evaluated_at,
            blockers=readiness_blockers,
            readiness=readiness,
        )

    frames: dict[str, pd.DataFrame] = {}
    sources: list[dict[str, Any]] = []
    blockers: list[str] = []
    for symbol in config.symbols:
        try:
            frame = _load_complete_bars(config, symbol=symbol, as_of=evaluated_at)
        except (duckdb.Error, OSError, ValueError) as exc:
            blockers.append(f"{symbol}:DATA_QUALITY:{type(exc).__name__}:{exc}")
            continue
        if frame.empty:
            blockers.append(f"{symbol}:NO_COMPLETE_BARS")
            continue
        last_open = _utc(frame["ts"].iloc[-1], field="last bar timestamp")
        last_close = _utc(frame["bar_close_ts"].iloc[-1], field="last bar close")
        age_hours = max((evaluated_at - last_close).total_seconds() / 3600.0, 0.0)
        sources.append(
            {
                "venue": config.venue,
                "symbol": symbol,
                "bars": len(frame),
                "last_bar_ts": last_open.isoformat(),
                "last_bar_close_ts": last_close.isoformat(),
                "feed_age_hours": round(age_hours, 3),
                "observed_spread": True,
            }
        )
        if len(frame) < config.min_history_bars:
            blockers.append(f"{symbol}:INSUFFICIENT_HISTORY:{len(frame)}<{config.min_history_bars}")
        elif age_hours > config.max_feed_age_hours:
            blockers.append(
                f"{symbol}:STALE_FEED:{age_hours:.3f}h>{config.max_feed_age_hours:.3f}h"
            )
        else:
            frames[symbol] = frame
    if blockers:
        return _defer_status(
            config,
            evaluated_at=evaluated_at,
            blockers=blockers,
            readiness=readiness,
            verdict="DEFER_INPUT_BLOCKED",
        )

    detector_fn = detector or _default_detector
    eligible_signals: list[Signal] = []
    ignored_signals = 0
    for symbol, frame in frames.items():
        latest_ts = _utc(frame["ts"].iloc[-1], field="latest bar timestamp")
        for signal in detector_fn(frame, config):
            signal_ts = _utc(signal.ts, field="signal timestamp")
            if (
                signal.venue.strip().lower() != config.venue
                or signal.symbol != symbol
                or signal.timeframe != config.timeframe
                or signal_ts != latest_ts
            ):
                ignored_signals += 1
                continue
            eligible_signals.append(signal)

    journal = ForexSignalJournal(config.journal_db)
    new_signals = 0
    duplicate_signals = 0
    for signal in eligible_signals:
        if journal.record_signal(
            signal,
            recorded_at=evaluated_at,
            timeframe_delta=_TF_DELTA[config.timeframe],
            config_hash=config.config_hash,
        ):
            new_signals += 1
        else:
            duplicate_signals += 1
    feed_age = max(float(item["feed_age_hours"]) for item in sources)
    source_last_close = min(
        _utc(item["last_bar_close_ts"], field="source last close") for item in sources
    )
    run_id = _json_hash(
        {
            "config_hash": config.config_hash,
            "evaluated_at": evaluated_at.isoformat(),
            "source_last_close_ts": source_last_close,
        }
    )
    journal.record_run(
        {
            "run_id": run_id,
            "evaluated_at": evaluated_at,
            "feed_status": "FRESH",
            "verdict": "READY_LOCAL_PAPER",
            "feed_age_hours": feed_age,
            "source_last_close_ts": source_last_close,
            "configured_symbols": len(config.symbols),
            "new_signals": new_signals,
            "duplicate_signals": duplicate_signals,
            "config_hash": config.config_hash,
            "detail": {"sources": sources, "ignored_signals": ignored_signals},
        }
    )

    broker_status = run_local_paper_broker_once(broker_config, as_of=evaluated_at)
    signal_kpis = journal.weekly_kpis(as_of=evaluated_at)
    status = {
        "schema_version": STATUS_SCHEMA,
        "journal_schema": JOURNAL_SCHEMA,
        "evaluated_at": evaluated_at.isoformat(),
        "mode": MODE,
        "verdict": (
            "READY_LOCAL_PAPER"
            if broker_status.get("verdict") == "READY_LOCAL_PAPER"
            else "DEFER_BROKER"
        ),
        "feed_status": "FRESH",
        "feed_age_hours": feed_age,
        "max_feed_age_hours": config.max_feed_age_hours,
        "blockers": broker_status.get("blockers", []),
        "sources": sources,
        "strategy": config.strategy,
        "venue": config.venue,
        "timeframe": config.timeframe,
        "symbols": list(config.symbols),
        "new_signals": new_signals,
        "duplicate_signals": duplicate_signals,
        "ignored_signals": ignored_signals,
        "weekly_kpis": {
            "signals": signal_kpis,
            "paper_trades": broker_status["weekly_kpis"],
        },
        "paper_broker": broker_status,
        "config_hash": config.config_hash,
        "market_db": str(config.market_db),
        "journal_db": str(config.journal_db),
        "broker_db": str(config.broker_db),
        "risk_reference": str(config.risk_reference) if config.risk_reference else None,
        "risk_reference_active": False,
        "risk_reference_reason": "fixed paper notional; no live risk or order path",
        "journal_mutated": True,
        "broker_db_mutated": broker_status.get("broker_db_mutated", False),
        "permanent_paper_only": True,
        "order_path_enabled": ORDER_PATH_ENABLED,
        "network_path_enabled": NETWORK_PATH_ENABLED,
        "deployment_evidence": DEPLOYMENT_EVIDENCE,
        "historical_eurusd_4h_result_counts_as_deployment_evidence": False,
    }
    _write_status(config.status_path, status)
    return status
