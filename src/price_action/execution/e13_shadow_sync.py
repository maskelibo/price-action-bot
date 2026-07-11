"""Advance E13 shadow state from local journal and completed 15m bars only."""

from __future__ import annotations

import math
import tempfile
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb

from price_action.execution.e13_shadow import (
    AtrChandelierShadowRecorder,
    E13ShadowBusyError,
    E13ShadowLease,
    e13_shadow_lock_path,
)
from price_action.execution.e13_storage import (
    atomic_write_text,
    e13_policy_migration_transaction_path,
    e13_transaction_path,
    ensure_canonical_e13_data_root,
    secure_read_text,
    validate_e13_artifact_path,
)
from price_action.execution.exit_evidence import (
    E13_DEFAULT_CONFIG_PATH,
    E13Policy,
    load_e13_policy,
)

_SIGNAL_COLUMNS = {
    "signal_id",
    "ts",
    "symbol",
    "side",
    "fill_price",
    "sl_price",
    "status",
}
_CLOSE_COLUMNS = {
    "trade_id",
    "ts_close",
    "exit_price",
    "realized_r",
    "close_reason",
}
_OHLCV_COLUMNS = {
    "venue",
    "symbol",
    "timeframe",
    "ts",
    "open",
    "high",
    "low",
    "close",
}


class E13ShadowMutationError(RuntimeError):
    """A sync failed after one or more durable local artifact mutations."""

    def __init__(self, cause: Exception, mutation_paths: set[Path]) -> None:
        self.mutated_real_artifacts = True
        self.mutation_paths = tuple(sorted(str(path) for path in mutation_paths))
        super().__init__(
            f"E13 sync failed after durable mutation ({type(cause).__name__}): {cause}"
        )


def _aware_utc(value: datetime, *, field: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be a timestamp")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _journal_utc(value: datetime, *, field: str) -> datetime:
    """Journal TIMESTAMP columns are UTC-semantic and intentionally naive."""
    if not isinstance(value, datetime):
        raise ValueError(f"{field} must be a timestamp")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _finite_positive(value: Any) -> bool:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(parsed) and parsed > 0


def _finite_number(value: Any) -> bool:
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _columns(connection: duckdb.DuckDBPyConnection, table: str) -> dict[str, str]:
    tables = {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
    if table not in tables:
        raise ValueError(f"database is missing table: {table}")
    return {
        str(row[0]).lower(): str(row[1]).upper()
        for row in connection.execute(f'DESCRIBE "{table}"').fetchall()
    }


def _require_columns(
    connection: duckdb.DuckDBPyConnection,
    table: str,
    required: set[str],
) -> dict[str, str]:
    columns = _columns(connection, table)
    missing = sorted(required - set(columns))
    if missing:
        raise ValueError(f"{table} is missing required columns: {missing}")
    return columns


def _load_baselines(journal_path: Path, policy: E13Policy) -> list[dict[str, Any]]:
    with duckdb.connect(str(journal_path), read_only=True) as connection:
        _require_columns(connection, "futures_signals", _SIGNAL_COLUMNS)
        _require_columns(connection, "futures_trades_closed", _CLOSE_COLUMNS)
        rows = connection.execute(
            """
            SELECT s.signal_id, s.ts, s.symbol, s.side, s.fill_price, s.sl_price,
                   s.status, c.ts_close, c.exit_price, c.realized_r, c.close_reason
            FROM futures_signals s
            LEFT JOIN futures_trades_closed c ON c.trade_id = s.signal_id
            WHERE s.ts >= ?
              AND (lower(s.status) = 'filled' OR c.ts_close >= ?)
            ORDER BY s.ts, s.signal_id
            """,
            [
                policy.clean_cutoff.replace(tzinfo=None),
                policy.clean_cutoff.replace(tzinfo=None),
            ],
        ).fetchall()
    keys = (
        "trade_id",
        "ts_open",
        "symbol",
        "side",
        "entry_price",
        "initial_sl_price",
        "status",
        "ts_close",
        "exit_price",
        "realized_r",
        "close_reason",
    )
    return [dict(zip(keys, row, strict=True)) for row in rows]


def _validate_market_schema(market_path: Path) -> None:
    with duckdb.connect(str(market_path), read_only=True) as connection:
        columns = _require_columns(connection, "ohlcv", _OHLCV_COLUMNS)
    if "WITH TIME ZONE" not in columns["ts"]:
        raise ValueError("ohlcv.ts must be TIMESTAMP WITH TIME ZONE")


def _floor_15m(value: datetime) -> datetime:
    value = value.astimezone(UTC)
    return value.replace(minute=(value.minute // 15) * 15, second=0, microsecond=0)


def _last_expected_bar_start(through: datetime) -> datetime:
    # At 12:07 the last fully completed bar started at 11:45 and ended at 12:00.
    return _floor_15m(through) - timedelta(minutes=15)


def _bars_with_atr(
    market_path: Path,
    *,
    policy: E13Policy,
    symbol: str,
    signal_bar_open: datetime,
    through: datetime,
) -> dict[str, Any]:
    """Return causal bars; ATR(t) is used only to set the stop for bar t+1."""
    first_exposure_start = signal_bar_open + timedelta(minutes=15)
    warmup = first_exposure_start - timedelta(
        minutes=15 * (policy.atr_period + 2)
    )
    with duckdb.connect(str(market_path), read_only=True) as connection:
        rows = connection.execute(
            """
            SELECT ts, open, high, low, close
            FROM ohlcv
            WHERE venue = ? AND symbol = ? AND timeframe = ?
              AND ts >= ? AND ts < ?
            ORDER BY ts
            """,
            [
                policy.shadow_market_venue,
                symbol,
                policy.shadow_timeframe,
                warmup,
                through,
            ],
        ).fetchall()

    parsed: list[tuple[datetime, float, float, float, float]] = []
    for row_number, (raw_ts, raw_open, raw_high, raw_low, raw_close) in enumerate(
        rows, start=1
    ):
        values = (raw_open, raw_high, raw_low, raw_close)
        if not all(_finite_positive(value) for value in values):
            return {
                "status": "invalid_ohlc",
                "detail": f"{symbol} row {row_number} has non-positive/non-finite OHLC",
                "bars": [],
                "last_complete_bar_start": None,
            }
        opened = _journal_utc(raw_ts, field="ohlcv.ts")
        o, high, low, close = map(float, values)
        if high < max(o, low, close) or low > min(o, high, close):
            return {
                "status": "invalid_ohlc",
                "detail": f"{symbol} row {row_number} has invalid OHLC ordering",
                "bars": [],
                "last_complete_bar_start": None,
            }
        if opened.second or opened.microsecond or opened.minute % 15:
            return {
                "status": "misaligned_bar_timestamp",
                "detail": f"{symbol} has a non-15m timestamp: {opened.isoformat()}",
                "bars": [],
                "last_complete_bar_start": None,
            }
        if parsed and opened - parsed[-1][0] != timedelta(minutes=15):
            return {
                "status": "non_contiguous_15m_bars",
                "detail": (
                    f"{symbol} gap: {parsed[-1][0].isoformat()} -> {opened.isoformat()}"
                ),
                "bars": [],
                "last_complete_bar_start": parsed[-1][0],
            }
        if opened + timedelta(minutes=15) <= through:
            parsed.append((opened, o, high, low, close))

    if len(parsed) < policy.atr_period + 1:
        return {
            "status": "insufficient_atr_history",
            "detail": (
                f"{symbol} has {len(parsed)} completed rows; "
                f"need at least {policy.atr_period + 1}"
            ),
            "bars": [],
            "last_complete_bar_start": parsed[-1][0] if parsed else None,
        }

    true_ranges: list[float] = []
    bars: list[dict[str, Any]] = []
    previous_close = parsed[0][4]
    for bar_start, o, high, low, close in parsed[1:]:
        tr = max(high - low, abs(high - previous_close), abs(low - previous_close))
        previous_close = close
        true_ranges.append(tr)
        if len(true_ranges) < policy.atr_period or bar_start < first_exposure_start:
            continue
        atr = sum(true_ranges[-policy.atr_period :]) / policy.atr_period
        bars.append(
            {
                "ts": bar_start + timedelta(minutes=15),
                "open_price": o,
                "high": high,
                "low": low,
                "close": close,
                "atr": atr,
            }
        )
    return {
        "status": "ok",
        "detail": "ok",
        "bars": bars,
        "last_complete_bar_start": parsed[-1][0],
    }


def _coverage_reaches(
    last_complete_bar_start: datetime | None,
    *,
    through: datetime,
    first_exposure_start: datetime,
) -> bool:
    expected = _last_expected_bar_start(through)
    if expected < first_exposure_start:
        return True
    return last_complete_bar_start is not None and last_complete_bar_start >= expected


def _issue(
    result: dict[str, Any],
    *,
    trade_id: str,
    code: str,
    detail: str,
) -> None:
    result["issues"].append({"trade_id": trade_id, "code": code, "detail": detail})


def _sync_with_policy(
    journal: Path,
    market: Path,
    *,
    policy: E13Policy,
    horizon: datetime,
    lease: E13ShadowLease,
    on_artifact_mutation: Any = None,
    transaction_path: Path | None = None,
) -> dict[str, Any]:
    baselines = _load_baselines(journal, policy)
    _validate_market_schema(market)
    recorder = AtrChandelierShadowRecorder(
        policy,
        lease=lease,
        on_artifact_mutation=on_artifact_mutation,
        transaction_path=transaction_path,
    )
    evidence_ids = recorder.evidence_trade_ids()
    baseline_ids = {str(row.get("trade_id") or "").strip() for row in baselines}
    result: dict[str, Any] = {
        "policy_hash_sha256": policy.policy_hash_sha256,
        "policy_provenance_version": policy.policy_provenance_version,
        "through_utc": horizon.isoformat(),
        "baselines_seen": len(baselines),
        "trades_started": 0,
        "bars_applied": 0,
        "evidence_emitted": 0,
        "already_evidenced": 0,
        "historical_closed_without_state": 0,
        "ineligible_discarded": 0,
        "invalid_baselines": 0,
        "issues": [],
    }

    for baseline in baselines:
        trade_id = str(baseline.get("trade_id") or "").strip()
        side = str(baseline.get("side") or "").strip().lower()
        status = str(baseline.get("status") or "").strip().lower()
        if (
            not trade_id
            or side not in {"long", "short"}
            or not _finite_positive(baseline.get("entry_price"))
            or not _finite_positive(baseline.get("initial_sl_price"))
            or not isinstance(baseline.get("ts_open"), datetime)
            or not str(baseline.get("symbol") or "").strip()
        ):
            result["invalid_baselines"] += 1
            _issue(
                result,
                trade_id=trade_id or "<missing>",
                code="invalid_baseline",
                detail="missing/invalid id, side, timestamps, symbol, entry, or initial SL",
            )
            continue
        opened = _journal_utc(baseline["ts_open"], field="signal ts")
        if opened < policy.clean_cutoff:
            # Defensive parity with the SQL predicate.
            continue
        closed_raw = baseline.get("ts_close")
        parsed_close = (
            _journal_utc(closed_raw, field="close ts")
            if isinstance(closed_raw, datetime)
            else None
        )
        closed = parsed_close if parsed_close is not None and parsed_close <= horizon else None
        close_reason = str(baseline.get("close_reason") or "").strip().lower()
        state = recorder.trade_state(trade_id)
        if state is not None:
            try:
                state = recorder.validate_trade_identity(
                    trade_id=trade_id,
                    side=side,
                    ts_open=opened,
                    entry_price=float(baseline["entry_price"]),
                    initial_sl_price=float(baseline["initial_sl_price"]),
                )
            except ValueError as exc:
                result["invalid_baselines"] += 1
                _issue(
                    result,
                    trade_id=trade_id,
                    code="state_baseline_identity_mismatch",
                    detail=str(exc),
                )
                continue

        if closed is not None and close_reason not in policy.eligible_close_reasons:
            if recorder.discard_trade(trade_id):
                result["ineligible_discarded"] += 1
            continue
        if trade_id in evidence_ids:
            result["already_evidenced"] += 1
            continue
        if closed is not None and (
            not _finite_positive(baseline.get("exit_price"))
            or not _finite_number(baseline.get("realized_r"))
        ):
            result["invalid_baselines"] += 1
            _issue(
                result,
                trade_id=trade_id,
                code="invalid_close",
                detail="eligible close lacks finite positive exit_price/realized_r",
            )
            continue

        if state is None:
            if closed is not None:
                # Do not manufacture prospective evidence from an already-known close.
                result["historical_closed_without_state"] += 1
                _issue(
                    result,
                    trade_id=trade_id,
                    code="closed_without_prospective_state",
                    detail="not backfilled; E13 state did not exist while trade was open",
                )
                continue
            if status != "filled":
                result["invalid_baselines"] += 1
                _issue(
                    result,
                    trade_id=trade_id,
                    code="nonfilled_without_close",
                    detail=f"signal status is {status!r} without an eligible close",
                )
                continue
            recorder.start_trade(
                trade_id=trade_id,
                side=side,
                ts_open=opened,
                entry_price=float(baseline["entry_price"]),
                initial_sl_price=float(baseline["initial_sl_price"]),
            )
            result["trades_started"] += 1
            state = recorder.trade_state(trade_id)

        # If the candidate was already terminal, an arriving baseline close can
        # be paired without requiring any later market data.
        if (
            closed is not None
            and state is not None
            and state.get("candidate_exit_price") is not None
            and state.get("baseline_exit_price") is None
        ):
            recorder.record_baseline_close(
                trade_id=trade_id,
                ts_close=closed,
                exit_price=float(baseline["exit_price"]),
                close_reason=close_reason,
                baseline_realized_r=float(baseline["realized_r"]),
            )
            evidence_ids.add(trade_id)
            result["evidence_emitted"] += 1
            continue

        market_result = _bars_with_atr(
            market,
            policy=policy,
            symbol=str(baseline["symbol"]),
            signal_bar_open=opened,
            through=horizon,
        )
        if market_result["status"] != "ok":
            _issue(
                result,
                trade_id=trade_id,
                code=str(market_result["status"]),
                detail=str(market_result["detail"]),
            )
            continue
        bars = market_result["bars"]
        last_complete = market_result["last_complete_bar_start"]
        first_exposure_start = opened + timedelta(minutes=15)
        last_state = recorder.trade_state(trade_id) or {}
        last_bar_raw = last_state.get("last_bar_utc")
        last_bar = datetime.fromisoformat(last_bar_raw) if last_bar_raw else None

        preclose_bars = [bar for bar in bars if closed is None or bar["ts"] <= closed]
        for bar in preclose_bars:
            if last_bar is not None and bar["ts"] <= last_bar:
                continue
            recorder.observe_closed_bar(trade_id=trade_id, **bar)
            result["bars_applied"] += 1
            current = recorder.trade_state(trade_id)
            if current is None or current.get("candidate_exit_price") is not None:
                break

        state = recorder.trade_state(trade_id)
        if closed is not None and state is not None and state.get("baseline_exit_price") is None:
            covered_to_close = _coverage_reaches(
                last_complete,
                through=closed,
                first_exposure_start=first_exposure_start,
            )
            if state.get("candidate_exit_price") is None and not covered_to_close:
                _issue(
                    result,
                    trade_id=trade_id,
                    code="market_not_complete_through_baseline_close",
                    detail=f"local 15m data does not reach {closed.isoformat()}",
                )
                continue
            if int(state.get("bars_observed", 0)) < 1:
                _issue(
                    result,
                    trade_id=trade_id,
                    code="no_causal_bar_before_close",
                    detail="trade closed before one complete post-entry 15m bar was observed",
                )
                continue
            recorder.record_baseline_close(
                trade_id=trade_id,
                ts_close=closed,
                exit_price=float(baseline["exit_price"]),
                close_reason=close_reason,
                baseline_realized_r=float(baseline["realized_r"]),
            )
            if recorder.trade_state(trade_id) is None:
                evidence_ids.add(trade_id)
                result["evidence_emitted"] += 1
                continue

        # If live baseline closed first, continue the independent virtual
        # candidate on later completed bars until its own terminal stop.
        state = recorder.trade_state(trade_id)
        if state is not None and state.get("candidate_exit_price") is None:
            last_bar_raw = state.get("last_bar_utc")
            last_bar = datetime.fromisoformat(last_bar_raw) if last_bar_raw else None
            for bar in bars:
                if closed is not None and bar["ts"] <= closed:
                    continue
                if last_bar is not None and bar["ts"] <= last_bar:
                    continue
                recorder.observe_closed_bar(trade_id=trade_id, **bar)
                result["bars_applied"] += 1
                if recorder.trade_state(trade_id) is None:
                    evidence_ids.add(trade_id)
                    result["evidence_emitted"] += 1
                    break
                current = recorder.trade_state(trade_id) or {}
                if current.get("candidate_exit_price") is not None:
                    break

        if not _coverage_reaches(
            last_complete,
            through=horizon,
            first_exposure_start=first_exposure_start,
        ):
            _issue(
                result,
                trade_id=trade_id,
                code="market_not_complete_through_tick",
                detail=f"local 15m snapshot does not reach {horizon.isoformat()}",
            )

    orphan_state = sorted(set(recorder.trade_ids()) - baseline_ids)
    for trade_id in orphan_state:
        _issue(
            result,
            trade_id=trade_id,
            code="orphan_shadow_state",
            detail="state checkpoint has no matching eligible/open journal row",
        )
    result["open_shadow_trades"] = len(recorder.trade_ids())
    result["evidence_checkpoint_trades"] = len(evidence_ids)
    result["fail_closed"] = bool(result["issues"])
    result["status"] = "HOLD_LOCAL_EVIDENCE_GAPS" if result["issues"] else "OK"
    return result


def sync_e13_shadow(
    journal_path: str | Path,
    market_path: str | Path,
    *,
    config_path: str | Path = E13_DEFAULT_CONFIG_PATH,
    through: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Advance prospective E13 state without network, broker, or exchange I/O."""
    policy = load_e13_policy(config_path)
    journal = Path(journal_path).expanduser().resolve()
    market = Path(market_path).expanduser().resolve()
    if not journal.is_file():
        raise FileNotFoundError(journal)
    if not market.is_file():
        raise FileNotFoundError(market)
    horizon = datetime.now(UTC) if through is None else _aware_utc(through, field="through")
    real_mutations: set[Path] = set()

    def _note_real_mutation(path: Path) -> None:
        real_mutations.add(path)

    try:
        # One canonical, config-independent lease covers journal/market reads,
        # every state read-modify-write, and evidence emission. Alternate YAML
        # paths and the manual recorder therefore cannot race this tick.
        with E13ShadowLease(policy.shadow_state_path) as lease:
            migration_transaction = validate_e13_artifact_path(
                e13_policy_migration_transaction_path(),
                field="E13 policy migration transaction",
                create_parent=True,
            )
            if migration_transaction.exists():
                result = {
                    "policy_hash_sha256": policy.policy_hash_sha256,
                    "policy_provenance_version": policy.policy_provenance_version,
                    "through_utc": horizon.isoformat(),
                    "status": "HOLD_POLICY_MIGRATION_PENDING",
                    "fail_closed": True,
                    "retryable": False,
                    "baselines_seen": 0,
                    "trades_started": 0,
                    "bars_applied": 0,
                    "evidence_emitted": 0,
                    "already_evidenced": 0,
                    "historical_closed_without_state": 0,
                    "ineligible_discarded": 0,
                    "invalid_baselines": 0,
                    "open_shadow_trades": 0,
                    "evidence_checkpoint_trades": 0,
                    "issues": [
                        {
                            "trade_id": "<policy-migration>",
                            "code": "policy_migration_pending",
                            "detail": str(migration_transaction),
                        }
                    ],
                }
            elif not dry_run:
                result = _sync_with_policy(
                    journal,
                    market,
                    policy=policy,
                    horizon=horizon,
                    lease=lease,
                    on_artifact_mutation=_note_real_mutation,
                )
            else:
                transaction = validate_e13_artifact_path(
                    e13_transaction_path(),
                    field="E13 recovery transaction",
                    create_parent=True,
                )
                if transaction.exists():
                    raise ValueError(
                        "E13 dry-run refused while a durable recovery transaction is pending"
                    )
                data_root = ensure_canonical_e13_data_root()
                with tempfile.TemporaryDirectory(
                    prefix=".e13-shadow-dryrun-",
                    dir=data_root,
                ) as raw_temp:
                    temp = Path(raw_temp)
                    dry_policy = replace(
                        policy,
                        shadow_state_path=temp / "state.json",
                        shadow_evidence_path=temp / "evidence.jsonl",
                    )
                    real_state = validate_e13_artifact_path(
                        policy.shadow_state_path,
                        field="E13 shadow state",
                    )
                    real_evidence = validate_e13_artifact_path(
                        policy.shadow_evidence_path,
                        field="E13 shadow evidence",
                    )
                    if real_state.exists():
                        atomic_write_text(
                            dry_policy.shadow_state_path,
                            secure_read_text(
                                real_state,
                                field="E13 shadow state",
                            ),
                            field="E13 dry-run shadow state",
                        )
                    if real_evidence.exists():
                        atomic_write_text(
                            dry_policy.shadow_evidence_path,
                            secure_read_text(
                                real_evidence,
                                field="E13 shadow evidence",
                            ),
                            field="E13 dry-run shadow evidence",
                        )
                    result = _sync_with_policy(
                        journal,
                        market,
                        policy=dry_policy,
                        horizon=horizon,
                        lease=lease,
                        transaction_path=temp / "transaction.json",
                    )
    except E13ShadowBusyError as exc:
        result = {
            "policy_hash_sha256": policy.policy_hash_sha256,
            "policy_provenance_version": policy.policy_provenance_version,
            "through_utc": horizon.isoformat(),
            "status": "HOLD_WRITER_BUSY",
            "fail_closed": True,
            "retryable": True,
            "lease_busy": True,
            "writer_lock_path": str(exc.lock_path),
            "baselines_seen": 0,
            "trades_started": 0,
            "bars_applied": 0,
            "evidence_emitted": 0,
            "already_evidenced": 0,
            "historical_closed_without_state": 0,
            "ineligible_discarded": 0,
            "invalid_baselines": 0,
            "open_shadow_trades": 0,
            "evidence_checkpoint_trades": 0,
            "issues": [
                {
                    "trade_id": "<writer-lease>",
                    "code": "writer_busy",
                    "detail": str(exc),
                }
            ],
        }
    except Exception as exc:
        if real_mutations and not dry_run:
            raise E13ShadowMutationError(exc, real_mutations) from exc
        raise

    result["dry_run"] = bool(dry_run)
    result.setdefault("lease_busy", False)
    result.setdefault("policy_provenance_version", policy.policy_provenance_version)
    result.setdefault("retryable", False)
    result.setdefault("writer_lock_path", str(e13_shadow_lock_path(policy.shadow_state_path)))
    result["mutated_real_artifacts"] = bool(real_mutations) and not dry_run
    result["mutated_artifact_paths"] = (
        sorted(str(path) for path in real_mutations) if not dry_run else []
    )
    result["journal"] = str(journal)
    result["market"] = str(market)
    result["config"] = str(policy.config_path)
    result["state_artifact"] = str(policy.shadow_state_path)
    result["evidence_artifact"] = str(policy.shadow_evidence_path)
    result["network_calls"] = 0
    result["exchange_calls"] = 0
    return result


__all__ = ["E13ShadowMutationError", "sync_e13_shadow"]
