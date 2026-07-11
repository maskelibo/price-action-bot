"""Deterministic, local-only Forex paper broker.

This adapter has a deliberately narrow boundary: it reads a trusted local
market DuckDB and the separate signal journal, then writes simulated state to
its own DuckDB.  Readiness is re-evaluated before the broker database is
created or mutated.  There is no network, credential, exchange, or order path.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from price_action.lab.forex_readiness import (
    READY,
    evaluate_forex_readiness,
    forex_market_age_seconds,
)

MODE = "LOCAL_PERMANENT_PAPER"
BROKER_SCHEMA = "forex-local-paper-broker-v1"
ORDER_PATH_ENABLED = False
NETWORK_PATH_ENABLED = False
EXCHANGE_PATH_ENABLED = False

_TF_DELTA = {
    "1h": timedelta(hours=1),
    "4h": timedelta(hours=4),
    "1d": timedelta(days=1),
}
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SYMBOL_RE = re.compile(r"^[A-Z]{3}/[A-Z]{3}$")


def _hash(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


@dataclass(frozen=True)
class LocalPaperBrokerConfig:
    """Permanent-paper configuration; all database paths must be distinct."""

    market_db: Path
    signal_db: Path
    broker_db: Path
    readiness_config: Path
    venue: str
    symbols: tuple[str, ...]
    timeframe: str
    spread_column: str = "spread_bps"
    paper_notional_usd: float = 1_000.0

    def __post_init__(self) -> None:
        normalized_venue = self.venue.strip().lower()
        if not normalized_venue or normalized_venue != self.venue:
            raise ValueError("venue must be a normalized lowercase identifier")
        if self.timeframe not in _TF_DELTA:
            raise ValueError(f"unsupported timeframe: {self.timeframe}")
        if not self.symbols or any(_SYMBOL_RE.fullmatch(item) is None for item in self.symbols):
            raise ValueError("symbols must be non-empty canonical FX pairs")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("symbols must be unique")
        if _IDENTIFIER_RE.fullmatch(self.spread_column) is None:
            raise ValueError("spread_column must be a safe SQL identifier")
        if (
            isinstance(self.paper_notional_usd, bool)
            or not math.isfinite(self.paper_notional_usd)
            or self.paper_notional_usd <= 0
        ):
            raise ValueError("paper_notional_usd must be finite and positive")
        paths = {self.market_db.resolve(), self.signal_db.resolve(), self.broker_db.resolve()}
        if len(paths) != 3:
            raise ValueError("market, signal, and paper-broker DuckDB files must be separate")


@dataclass(frozen=True)
class _Bar:
    ts: datetime
    open: float
    high: float
    low: float
    close: float
    spread_bps: float


@dataclass(frozen=True)
class _SignalRow:
    signal_id: str
    decision_bar_ts: datetime
    decision_bar_close_ts: datetime
    recorded_at: datetime
    symbol: str
    timeframe: str
    direction: str
    pattern_id: str
    sl_price: float
    tp_price: float


def readiness_scope_blockers(report: dict[str, Any], config: LocalPaperBrokerConfig) -> list[str]:
    blockers: list[str] = []
    if report.get("status") != READY:
        blockers.extend(str(item.get("code", "READINESS_DEFER")) for item in report["reasons"])
        return blockers
    if report.get("authorization") != {"live": False, "testnet": False, "orders": False}:
        blockers.append("UNSAFE_AUTHORIZATION")

    capabilities = report.get("capabilities") or {}
    for capability in ("feed", "local_runner", "paper_broker"):
        if (capabilities.get(capability) or {}).get("ready") is not True:
            blockers.append(f"CAPABILITY_{capability.upper()}_UNAVAILABLE")

    database = report.get("database") or {}
    checks = database.get("checks") or {}
    venue_check = checks.get("source_venues") or {}
    if venue_check.get("ok") is not True or config.venue not in venue_check.get("trusted", []):
        blockers.append("TRUSTED_VENUE_SCOPE_MISMATCH")
    spread_check = checks.get("spread_schema") or {}
    spread_values = checks.get("spread_values") or {}
    if (
        spread_check.get("ok") is not True
        or spread_check.get("column") != config.spread_column
        or spread_values.get("ok") is not True
    ):
        blockers.append("OBSERVED_SPREAD_SCOPE_MISMATCH")
    series = database.get("series") or {}
    for symbol in config.symbols:
        key = f"{config.venue}/{symbol}/{config.timeframe}"
        if (series.get(key) or {}).get("fresh") is not True:
            blockers.append(f"REQUIRED_SERIES_NOT_READY:{key}")
    return blockers


def _load_signals(config: LocalPaperBrokerConfig) -> list[_SignalRow]:
    if config.signal_db.is_symlink() or not config.signal_db.is_file():
        raise ValueError(f"regular signal journal not found: {config.signal_db}")
    with duckdb.connect(str(config.signal_db), read_only=True) as con:
        tables = {
            row[0]
            for row in con.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_schema='main'"
            ).fetchall()
        }
        if "signal_events" not in tables:
            raise ValueError("signal journal is missing signal_events")
        rows = con.execute(
            """
            SELECT signal_id, decision_bar_ts, decision_bar_close_ts, recorded_at,
                   symbol, timeframe, direction, pattern_id, sl_price, tp_price
            FROM signal_events
            WHERE mode='SIGNAL_ONLY_PAPER' AND deployment_evidence=false
            ORDER BY decision_bar_ts, signal_id
            """
        ).fetchall()

    result: list[_SignalRow] = []
    for row in rows:
        signal = _SignalRow(
            signal_id=str(row[0]),
            decision_bar_ts=_utc(row[1], field="decision_bar_ts"),
            decision_bar_close_ts=_utc(row[2], field="decision_bar_close_ts"),
            recorded_at=_utc(row[3], field="recorded_at"),
            symbol=str(row[4]),
            timeframe=str(row[5]),
            direction=str(row[6]),
            pattern_id=str(row[7]),
            sl_price=float(row[8]),
            tp_price=float(row[9]),
        )
        if signal.symbol not in config.symbols or signal.timeframe != config.timeframe:
            continue
        if signal.direction not in {"long", "short"}:
            raise ValueError(f"invalid signal direction: {signal.direction}")
        if signal.recorded_at < signal.decision_bar_close_ts:
            raise ValueError(f"lookahead signal timestamp: {signal.signal_id}")
        if not all(
            math.isfinite(value) and value > 0 for value in (signal.sl_price, signal.tp_price)
        ):
            raise ValueError(f"invalid signal levels: {signal.signal_id}")
        result.append(signal)
    return result


def _load_closed_bars(config: LocalPaperBrokerConfig, *, as_of: datetime) -> dict[str, list[_Bar]]:
    if config.market_db.is_symlink() or not config.market_db.is_file():
        raise ValueError(f"regular market database not found: {config.market_db}")
    spread = f'"{config.spread_column}"'
    result: dict[str, list[_Bar]] = {}
    with duckdb.connect(str(config.market_db), read_only=True) as con:
        for symbol in config.symbols:
            rows = con.execute(
                f"""
                SELECT ts, open, high, low, close, {spread}
                FROM ohlcv
                WHERE lower(venue)=? AND upper(symbol)=? AND lower(timeframe)=?
                ORDER BY ts
                """,
                [config.venue, symbol, config.timeframe],
            ).fetchall()
            bars: list[_Bar] = []
            seen: set[datetime] = set()
            for row in rows:
                ts = _utc(row[0], field="bar timestamp")
                if ts + _TF_DELTA[config.timeframe] > as_of:
                    continue
                if ts in seen:
                    raise ValueError(f"duplicate bar timestamp for {symbol}: {ts.isoformat()}")
                seen.add(ts)
                values = tuple(float(value) for value in row[1:])
                open_, high, low, close, spread_bps = values
                if not all(math.isfinite(value) for value in values):
                    raise ValueError(f"non-finite bar for {symbol}: {ts.isoformat()}")
                if (
                    min(open_, high, low, close) <= 0
                    or high < max(open_, close, low)
                    or low > min(open_, close, high)
                    or spread_bps < 0
                ):
                    raise ValueError(f"invalid closed bar for {symbol}: {ts.isoformat()}")
                bars.append(_Bar(ts, open_, high, low, close, spread_bps))
            result[symbol] = bars
    return result


def _empty_kpis(as_of: datetime) -> dict[str, Any]:
    return {
        "window_start": (as_of - timedelta(days=7)).isoformat(),
        "window_end": as_of.isoformat(),
        "entries": 0,
        "exits": 0,
        "closed_trades": 0,
        "wins": 0,
        "losses": 0,
        "realized_pnl_usd": 0.0,
        "win_rate": None,
        "open_positions": 0,
    }


def read_weekly_broker_kpis(path: Path, *, as_of: datetime) -> dict[str, Any]:
    """Read KPIs without creating or altering a broker database."""

    as_of = _utc(as_of, field="as_of")
    if path.is_symlink() or not path.is_file():
        return _empty_kpis(as_of)
    since = as_of - timedelta(days=7)
    try:
        with duckdb.connect(str(path), read_only=True) as con:
            fill = con.execute(
                """
                SELECT count(*) FILTER (WHERE fill_kind='ENTRY'),
                       count(*) FILTER (WHERE fill_kind!='ENTRY')
                FROM paper_fills WHERE observed_at BETWEEN ? AND ?
                """,
                [since, as_of],
            ).fetchone()
            trade = con.execute(
                """
                SELECT count(*),
                       count(*) FILTER (WHERE realized_pnl_usd > 0),
                       count(*) FILTER (WHERE realized_pnl_usd <= 0),
                       coalesce(sum(realized_pnl_usd), 0)
                FROM paper_trades WHERE exit_observed_at BETWEEN ? AND ?
                """,
                [since, as_of],
            ).fetchone()
            open_count = con.execute(
                "SELECT count(*) FROM paper_positions WHERE status='OPEN'"
            ).fetchone()[0]
    except duckdb.Error:
        return _empty_kpis(as_of)
    closed = int(trade[0])
    return {
        "window_start": since.isoformat(),
        "window_end": as_of.isoformat(),
        "entries": int(fill[0]),
        "exits": int(fill[1]),
        "closed_trades": closed,
        "wins": int(trade[1]),
        "losses": int(trade[2]),
        "realized_pnl_usd": round(float(trade[3]), 8),
        "win_rate": round(float(trade[1]) / closed, 6) if closed else None,
        "open_positions": int(open_count),
    }


class _PaperStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with duckdb.connect(str(path)) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_signal_state (
                    signal_id VARCHAR PRIMARY KEY,
                    state VARCHAR NOT NULL,
                    reason VARCHAR,
                    first_seen_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_positions (
                    signal_id VARCHAR PRIMARY KEY,
                    symbol VARCHAR NOT NULL,
                    timeframe VARCHAR NOT NULL,
                    direction VARCHAR NOT NULL,
                    pattern_id VARCHAR NOT NULL,
                    decision_bar_ts TIMESTAMPTZ NOT NULL,
                    eligible_entry_ts TIMESTAMPTZ NOT NULL,
                    entry_bar_ts TIMESTAMPTZ NOT NULL,
                    entry_observed_at TIMESTAMPTZ NOT NULL,
                    entry_price DOUBLE NOT NULL,
                    quantity DOUBLE NOT NULL,
                    sl_price DOUBLE NOT NULL,
                    tp_price DOUBLE NOT NULL,
                    entry_spread_bps DOUBLE NOT NULL,
                    status VARCHAR NOT NULL,
                    last_evaluated_bar_ts TIMESTAMPTZ NOT NULL,
                    exit_bar_ts TIMESTAMPTZ,
                    exit_observed_at TIMESTAMPTZ,
                    exit_price DOUBLE,
                    exit_reason VARCHAR,
                    realized_pnl_usd DOUBLE
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_fills (
                    fill_id VARCHAR PRIMARY KEY,
                    signal_id VARCHAR NOT NULL,
                    fill_kind VARCHAR NOT NULL,
                    effective_ts TIMESTAMPTZ NOT NULL,
                    bar_ts TIMESTAMPTZ NOT NULL,
                    observed_at TIMESTAMPTZ NOT NULL,
                    side VARCHAR NOT NULL,
                    price DOUBLE NOT NULL,
                    quantity DOUBLE NOT NULL,
                    observed_spread_bps DOUBLE NOT NULL,
                    notional_usd DOUBLE NOT NULL,
                    mode VARCHAR NOT NULL,
                    exchange_order_id VARCHAR
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_trades (
                    trade_id VARCHAR PRIMARY KEY,
                    signal_id VARCHAR UNIQUE NOT NULL,
                    symbol VARCHAR NOT NULL,
                    direction VARCHAR NOT NULL,
                    pattern_id VARCHAR NOT NULL,
                    entry_ts TIMESTAMPTZ NOT NULL,
                    exit_ts TIMESTAMPTZ NOT NULL,
                    entry_observed_at TIMESTAMPTZ NOT NULL,
                    exit_observed_at TIMESTAMPTZ NOT NULL,
                    entry_price DOUBLE NOT NULL,
                    exit_price DOUBLE NOT NULL,
                    quantity DOUBLE NOT NULL,
                    realized_pnl_usd DOUBLE NOT NULL,
                    exit_reason VARCHAR NOT NULL,
                    mode VARCHAR NOT NULL,
                    deployment_evidence BOOLEAN NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS broker_runs (
                    run_id VARCHAR PRIMARY KEY,
                    evaluated_at TIMESTAMPTZ NOT NULL,
                    signals_seen INTEGER NOT NULL,
                    entries INTEGER NOT NULL,
                    exits INTEGER NOT NULL,
                    rejected INTEGER NOT NULL,
                    open_positions INTEGER NOT NULL,
                    detail_json VARCHAR NOT NULL,
                    mode VARCHAR NOT NULL,
                    order_path_enabled BOOLEAN NOT NULL,
                    network_path_enabled BOOLEAN NOT NULL,
                    exchange_path_enabled BOOLEAN NOT NULL
                )
                """
            )


def _quotes(bar: _Bar) -> dict[str, float]:
    half = bar.spread_bps / 20_000.0
    return {
        "bid_open": bar.open * (1.0 - half),
        "bid_high": bar.high * (1.0 - half),
        "bid_low": bar.low * (1.0 - half),
        "ask_open": bar.open * (1.0 + half),
        "ask_high": bar.high * (1.0 + half),
        "ask_low": bar.low * (1.0 + half),
    }


def _exit_fill(
    *, direction: str, sl_price: float, tp_price: float, bar: _Bar
) -> tuple[str, float] | None:
    quote = _quotes(bar)
    if direction == "long":
        stop_hit = quote["bid_low"] <= sl_price
        target_hit = quote["bid_high"] >= tp_price
        if stop_hit:  # Stop wins every ambiguous same-bar outcome.
            return "SL", min(sl_price, quote["bid_open"])
        if target_hit:
            return "TP", tp_price
        return None
    stop_hit = quote["ask_high"] >= sl_price
    target_hit = quote["ask_low"] <= tp_price
    if stop_hit:
        return "SL", max(sl_price, quote["ask_open"])
    if target_hit:
        return "TP", tp_price
    return None


def _position_values(row: tuple[Any, ...]) -> dict[str, Any]:
    names = (
        "signal_id",
        "symbol",
        "timeframe",
        "direction",
        "pattern_id",
        "decision_bar_ts",
        "eligible_entry_ts",
        "entry_bar_ts",
        "entry_observed_at",
        "entry_price",
        "quantity",
        "sl_price",
        "tp_price",
        "entry_spread_bps",
        "status",
        "last_evaluated_bar_ts",
    )
    return dict(zip(names, row, strict=True))


def _close_position(
    con: duckdb.DuckDBPyConnection,
    *,
    position: dict[str, Any],
    bar: _Bar,
    observed_at: datetime,
    reason: str,
    exit_price: float,
) -> None:
    direction = position["direction"]
    multiplier = 1.0 if direction == "long" else -1.0
    pnl = (exit_price - float(position["entry_price"])) * float(position["quantity"]) * multiplier
    side = "sell" if direction == "long" else "buy"
    fill_id = _hash({"signal_id": position["signal_id"], "kind": reason, "bar": bar.ts})
    trade_id = _hash({"signal_id": position["signal_id"], "kind": "closed_trade"})
    con.execute(
        """
        INSERT INTO paper_fills VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (fill_id) DO NOTHING
        """,
        [
            fill_id,
            position["signal_id"],
            f"EXIT_{reason}",
            bar.ts,
            bar.ts,
            observed_at,
            side,
            exit_price,
            position["quantity"],
            bar.spread_bps,
            exit_price * float(position["quantity"]),
            MODE,
            None,
        ],
    )
    con.execute(
        """
        UPDATE paper_positions
        SET status='CLOSED', last_evaluated_bar_ts=?, exit_bar_ts=?, exit_observed_at=?,
            exit_price=?, exit_reason=?, realized_pnl_usd=?
        WHERE signal_id=? AND status='OPEN'
        """,
        [bar.ts, bar.ts, observed_at, exit_price, reason, pnl, position["signal_id"]],
    )
    con.execute(
        """
        INSERT INTO paper_trades VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (trade_id) DO NOTHING
        """,
        [
            trade_id,
            position["signal_id"],
            position["symbol"],
            direction,
            position["pattern_id"],
            position["entry_bar_ts"],
            bar.ts,
            position["entry_observed_at"],
            observed_at,
            position["entry_price"],
            exit_price,
            position["quantity"],
            pnl,
            reason,
            MODE,
            False,
        ],
    )
    con.execute(
        "UPDATE paper_signal_state SET state='CLOSED', updated_at=? WHERE signal_id=?",
        [observed_at, position["signal_id"]],
    )


def _run_ready(
    config: LocalPaperBrokerConfig,
    *,
    as_of: datetime,
    signals: list[_SignalRow],
    bars_by_symbol: dict[str, list[_Bar]],
) -> dict[str, Any]:
    store = _PaperStore(config.broker_db)
    entries = 0
    exits = 0
    rejected = 0
    deferred = 0

    with duckdb.connect(str(store.path)) as con:
        con.begin()
        try:
            for signal in signals:
                state = con.execute(
                    "SELECT state FROM paper_signal_state WHERE signal_id=?", [signal.signal_id]
                ).fetchone()
                if state is not None and state[0] in {"CLOSED", "REJECTED"}:
                    continue

                position_row = con.execute(
                    """
                    SELECT signal_id, symbol, timeframe, direction, pattern_id,
                           decision_bar_ts, eligible_entry_ts, entry_bar_ts,
                           entry_observed_at, entry_price, quantity, sl_price, tp_price,
                           entry_spread_bps, status, last_evaluated_bar_ts
                    FROM paper_positions WHERE signal_id=?
                    """,
                    [signal.signal_id],
                ).fetchone()
                bars = bars_by_symbol.get(signal.symbol, [])

                if position_row is None:
                    eligible = signal.decision_bar_close_ts
                    candidates = [bar for bar in bars if bar.ts >= eligible]
                    if not candidates:
                        deferred += 1
                        continue
                    entry_bar = candidates[0]
                    quote = _quotes(entry_bar)
                    entry_price = (
                        quote["ask_open"] if signal.direction == "long" else quote["bid_open"]
                    )
                    levels_valid = (
                        signal.sl_price < entry_price < signal.tp_price
                        if signal.direction == "long"
                        else signal.tp_price < entry_price < signal.sl_price
                    )
                    if not levels_valid:
                        con.execute(
                            """
                            INSERT INTO paper_signal_state VALUES (?, 'REJECTED', ?, ?, ?)
                            ON CONFLICT (signal_id) DO NOTHING
                            """,
                            [signal.signal_id, "INVALID_LEVELS_AT_ENTRY", as_of, as_of],
                        )
                        rejected += 1
                        continue

                    quantity = config.paper_notional_usd / entry_price
                    con.execute(
                        """
                        INSERT INTO paper_signal_state VALUES (?, 'OPEN', NULL, ?, ?)
                        ON CONFLICT (signal_id) DO NOTHING
                        """,
                        [signal.signal_id, as_of, as_of],
                    )
                    con.execute(
                        """
                        INSERT INTO paper_positions VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'OPEN', ?,
                            NULL, NULL, NULL, NULL, NULL
                        ) ON CONFLICT (signal_id) DO NOTHING
                        """,
                        [
                            signal.signal_id,
                            signal.symbol,
                            signal.timeframe,
                            signal.direction,
                            signal.pattern_id,
                            signal.decision_bar_ts,
                            eligible,
                            entry_bar.ts,
                            as_of,
                            entry_price,
                            quantity,
                            signal.sl_price,
                            signal.tp_price,
                            entry_bar.spread_bps,
                            entry_bar.ts,
                        ],
                    )
                    fill_id = _hash(
                        {"signal_id": signal.signal_id, "kind": "ENTRY", "bar": entry_bar.ts}
                    )
                    con.execute(
                        """
                        INSERT INTO paper_fills VALUES (?, ?, 'ENTRY', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT (fill_id) DO NOTHING
                        """,
                        [
                            fill_id,
                            signal.signal_id,
                            entry_bar.ts,
                            entry_bar.ts,
                            as_of,
                            "buy" if signal.direction == "long" else "sell",
                            entry_price,
                            quantity,
                            entry_bar.spread_bps,
                            entry_price * quantity,
                            MODE,
                            None,
                        ],
                    )
                    entries += 1
                    position_row = con.execute(
                        """
                        SELECT signal_id, symbol, timeframe, direction, pattern_id,
                               decision_bar_ts, eligible_entry_ts, entry_bar_ts,
                               entry_observed_at, entry_price, quantity, sl_price, tp_price,
                               entry_spread_bps, status, last_evaluated_bar_ts
                        FROM paper_positions WHERE signal_id=?
                        """,
                        [signal.signal_id],
                    ).fetchone()
                    # Catch up deterministically when a local loop was missed: entry
                    # is fixed to the first eligible bar, then every later *closed*
                    # bar is evaluated in timestamp order within the same transaction.
                    candidate_bars = candidates
                else:
                    position = _position_values(position_row)
                    if position["status"] != "OPEN":
                        continue
                    last_evaluated = _utc(
                        position["last_evaluated_bar_ts"], field="last_evaluated_bar_ts"
                    )
                    candidate_bars = [bar for bar in bars if bar.ts > last_evaluated]

                position = _position_values(position_row)
                for bar in candidate_bars:
                    outcome = _exit_fill(
                        direction=position["direction"],
                        sl_price=float(position["sl_price"]),
                        tp_price=float(position["tp_price"]),
                        bar=bar,
                    )
                    if outcome is not None:
                        _close_position(
                            con,
                            position=position,
                            bar=bar,
                            observed_at=as_of,
                            reason=outcome[0],
                            exit_price=outcome[1],
                        )
                        exits += 1
                        break
                    con.execute(
                        """
                        UPDATE paper_positions SET last_evaluated_bar_ts=?
                        WHERE signal_id=? AND status='OPEN'
                        """,
                        [bar.ts, signal.signal_id],
                    )

            open_positions = int(
                con.execute("SELECT count(*) FROM paper_positions WHERE status='OPEN'").fetchone()[
                    0
                ]
            )
            run_id = _hash(
                {
                    "schema": BROKER_SCHEMA,
                    "as_of": as_of,
                    "signals": [signal.signal_id for signal in signals],
                }
            )
            detail = {"deferred_signals": deferred, "entry_policy": "next_closed_bar_open"}
            con.execute(
                """
                INSERT INTO broker_runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (run_id) DO NOTHING
                """,
                [
                    run_id,
                    as_of,
                    len(signals),
                    entries,
                    exits,
                    rejected,
                    open_positions,
                    json.dumps(detail, sort_keys=True),
                    MODE,
                    ORDER_PATH_ENABLED,
                    NETWORK_PATH_ENABLED,
                    EXCHANGE_PATH_ENABLED,
                ],
            )
            con.commit()
        except Exception:
            con.rollback()
            raise

    return {
        "schema_version": BROKER_SCHEMA,
        "verdict": "READY_LOCAL_PAPER",
        "evaluated_at": as_of.isoformat(),
        "signals_seen": len(signals),
        "entries": entries,
        "exits": exits,
        "rejected": rejected,
        "deferred_signals": deferred,
        "weekly_kpis": read_weekly_broker_kpis(config.broker_db, as_of=as_of),
        "entry_policy": "signal decision bar closes, then first subsequent closed bar open",
        "ambiguous_same_bar_policy": "SL_FIRST",
        "spread_policy": "observed full spread, half on each executable quote",
        "permanent_paper_only": True,
        "order_path_enabled": ORDER_PATH_ENABLED,
        "network_path_enabled": NETWORK_PATH_ENABLED,
        "exchange_path_enabled": EXCHANGE_PATH_ENABLED,
        "deployment_evidence": False,
        "broker_db_mutated": True,
    }


def run_local_paper_broker_once(
    config: LocalPaperBrokerConfig,
    *,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Run one fail-closed local paper pass after an independent readiness check."""

    evaluated_at = _utc(as_of or datetime.now(UTC), field="as_of")
    report = evaluate_forex_readiness(
        config.readiness_config,
        now=evaluated_at,
        db_path_override=config.market_db,
    )
    blockers = readiness_scope_blockers(report, config)
    if blockers:
        return {
            "schema_version": BROKER_SCHEMA,
            "verdict": "DEFER_READINESS",
            "evaluated_at": evaluated_at.isoformat(),
            "blockers": blockers,
            "readiness_status": report.get("status"),
            "readiness_reasons": report.get("reasons", []),
            "weekly_kpis": read_weekly_broker_kpis(config.broker_db, as_of=evaluated_at),
            "permanent_paper_only": True,
            "order_path_enabled": ORDER_PATH_ENABLED,
            "network_path_enabled": NETWORK_PATH_ENABLED,
            "exchange_path_enabled": EXCHANGE_PATH_ENABLED,
            "deployment_evidence": False,
            "broker_db_mutated": False,
        }

    try:
        signals = _load_signals(config)
        bars = _load_closed_bars(config, as_of=evaluated_at)
        readiness_series = report["database"]["series"]
        for symbol, symbol_bars in bars.items():
            if not symbol_bars:
                raise ValueError(f"no complete trusted bars for {symbol}")
            key = f"{config.venue}/{symbol}/{config.timeframe}"
            allowed_hours = float(readiness_series[key]["allowed_market_age_hours"])
            last_close = symbol_bars[-1].ts + _TF_DELTA[config.timeframe]
            closed_bar_age = forex_market_age_seconds(last_close, evaluated_at) / 3600.0
            if closed_bar_age > allowed_hours:
                raise ValueError(
                    f"latest complete bar for {key} is stale: "
                    f"{closed_bar_age:.3f}h>{allowed_hours:.3f}h"
                )
    except (duckdb.Error, OSError, ValueError) as exc:
        return {
            "schema_version": BROKER_SCHEMA,
            "verdict": "DEFER_INPUT_BLOCKED",
            "evaluated_at": evaluated_at.isoformat(),
            "blockers": [f"{type(exc).__name__}:{exc}"],
            "weekly_kpis": read_weekly_broker_kpis(config.broker_db, as_of=evaluated_at),
            "permanent_paper_only": True,
            "order_path_enabled": ORDER_PATH_ENABLED,
            "network_path_enabled": NETWORK_PATH_ENABLED,
            "exchange_path_enabled": EXCHANGE_PATH_ENABLED,
            "deployment_evidence": False,
            "broker_db_mutated": False,
        }
    return _run_ready(
        config,
        as_of=evaluated_at,
        signals=signals,
        bars_by_symbol=bars,
    )
