"""Read-only, fail-closed evidence gate for the E13 exit experiment."""

from __future__ import annotations

import hashlib
import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import yaml

from price_action.execution.e13_storage import (
    canonical_e13_data_root,
    e13_global_lock_path,
    e13_policy_migration_root,
    e13_policy_migration_transaction_path,
    e13_transaction_path,
    resolve_e13_artifact_path,
    secure_read_text,
    validate_e13_artifact_path,
)

ROOT = Path(__file__).resolve().parents[3]
E13_DEFAULT_CONFIG_PATH = ROOT / "configs" / "risk_phoenix_scalp_15m_v15p2.yaml"

_SYNTHETIC_CLOSE_REASONS = {
    "dms",
    "force",
    "liquidation",
    "manual",
    "manual_close",
    "partial_close",
    "reconcile_orphan",
    "unknown",
}
_SHADOW_SOURCE = "e13_atr_shadow_recorder_v1"
_SHADOW_SCHEMA_VERSION = 1
E13_POLICY_PROVENANCE_VERSION = 2


def _aware_utc(value: datetime, *, field: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def _parse_aware_utc(value: Any, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be valid ISO-8601") from exc
    return _aware_utc(parsed, field=field)


def _positive_float(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field} must be finite and > 0")
    return number


def _nonnegative_float(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be finite and >= 0")
    return number


def _positive_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer >= 1")
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer >= 1") from exc
    if number < 1 or number != float(value):
        raise ValueError(f"{field} must be an integer >= 1")
    return number


@dataclass(frozen=True)
class E13Policy:
    """Validated E13 policy loaded entirely from the live risk YAML."""

    config_path: Path
    clean_cutoff: datetime
    required_clean_closes: int
    eligible_close_reasons: tuple[str, ...]
    live_trail_pct: float
    live_activate_after_r: float
    atr_period: int
    atr_method: str
    atr_multiplier: float
    atr_activate_after_r: float
    shadow_schema_version: int
    required_paired_closes: int
    shadow_market_venue: str
    shadow_timeframe: str
    entry_timestamp_semantics: str
    shadow_state_path: Path
    shadow_evidence_path: Path
    policy_provenance_version: int
    policy_hash_sha256: str

    @property
    def live_exit_mode(self) -> str:
        return f"PCT_TRAIL_{self.live_trail_pct * 100:g}_PERCENT_FROZEN"

    @property
    def candidate_exit_mode(self) -> str:
        return f"ATR_CHANDELIER_{self.atr_multiplier:g}X_SHADOW_ONLY"


def _e13_policy_hash(
    *,
    config_path: Path,
    clean_cutoff: datetime,
    required_clean: int,
    reasons: tuple[str, ...],
    live_trail_pct: float,
    live_activate: float,
    atr_period: int,
    atr_method: str,
    atr_multiplier: float,
    atr_activate: float,
    schema_version: int,
    required_paired: int,
    market_venue: str,
    timeframe: str,
    entry_semantics: str,
    state_path: Path,
    evidence_path: Path,
) -> str:
    """Hash the full policy, including every durable artifact identity."""
    payload = {
        "policy_provenance": {
            "version": E13_POLICY_PROVENANCE_VERSION,
            "config_path": str(config_path),
            "canonical_data_root": str(canonical_e13_data_root()),
        },
        "clean_cutoff_utc": clean_cutoff.isoformat(),
        "required_clean_closes": required_clean,
        "eligible_close_reasons": list(reasons),
        "live_exit": {
            "method": "pct_trail",
            "trail_pct": live_trail_pct,
            "activate_after_R": live_activate,
        },
        "candidate_exit": {
            "method": "atr_chandelier",
            "atr_period": atr_period,
            "atr_method": atr_method,
            "multiplier": atr_multiplier,
            "activate_after_R": atr_activate,
        },
        "paired_shadow": {
            "schema_version": schema_version,
            "min_paired_closed_trades": required_paired,
            "market_venue": market_venue,
            "timeframe": timeframe,
            "entry_timestamp_semantics": entry_semantics,
            "state_path": str(state_path),
            "evidence_path": str(evidence_path),
            "writer_lock_path": str(e13_global_lock_path()),
            "transaction_path": str(e13_transaction_path()),
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def e13_legacy_semantic_policy_hash(policy: E13Policy) -> str:
    """Reproduce the exact pre-provenance E13 semantic policy hash."""
    payload = {
        "clean_cutoff_utc": policy.clean_cutoff.isoformat(),
        "required_clean_closes": policy.required_clean_closes,
        "eligible_close_reasons": list(policy.eligible_close_reasons),
        "live_exit": {
            "method": "pct_trail",
            "trail_pct": policy.live_trail_pct,
            "activate_after_R": policy.live_activate_after_r,
        },
        "candidate_exit": {
            "method": "atr_chandelier",
            "atr_period": policy.atr_period,
            "atr_method": policy.atr_method,
            "multiplier": policy.atr_multiplier,
            "activate_after_R": policy.atr_activate_after_r,
        },
        "paired_shadow": {
            "schema_version": policy.shadow_schema_version,
            "min_paired_closed_trades": policy.required_paired_closes,
            "market_venue": policy.shadow_market_venue,
            "timeframe": policy.shadow_timeframe,
            "entry_timestamp_semantics": policy.entry_timestamp_semantics,
        },
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def load_e13_policy(config_path: str | Path = E13_DEFAULT_CONFIG_PATH) -> E13Policy:
    """Load and validate E13 policy; any ambiguity fails closed."""
    path = Path(config_path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("risk config must be a mapping")
    try:
        block = raw["exit_evidence"]["e13_atr_chandelier"]
    except (KeyError, TypeError) as exc:
        raise ValueError("config is missing exit_evidence.e13_atr_chandelier") from exc
    if not isinstance(block, dict):
        raise ValueError("exit_evidence.e13_atr_chandelier must be a mapping")
    if block.get("status") != "shadow_only":
        raise ValueError("E13 status must remain shadow_only")
    if block.get("auto_promote") is not False:
        raise ValueError("E13 auto_promote must be false")

    clean_cutoff = _parse_aware_utc(
        block.get("clean_cutoff_utc"), field="E13 clean_cutoff_utc"
    )
    required_clean = _positive_int(
        block.get("min_clean_closed_trades"), field="E13 min_clean_closed_trades"
    )

    reasons_raw = block.get("eligible_close_reasons")
    if not isinstance(reasons_raw, list) or not reasons_raw:
        raise ValueError("E13 eligible_close_reasons must be a non-empty list")
    reasons = tuple(str(reason).strip().lower() for reason in reasons_raw)
    if any(not reason for reason in reasons) or len(reasons) != len(set(reasons)):
        raise ValueError("E13 eligible_close_reasons must be unique, non-empty strings")
    forbidden = sorted(set(reasons) & _SYNTHETIC_CLOSE_REASONS)
    if forbidden:
        raise ValueError(f"synthetic close reasons cannot be E13-eligible: {forbidden}")

    live = block.get("live_exit")
    candidate = block.get("candidate_exit")
    paired = block.get("paired_shadow")
    if not isinstance(live, dict) or live.get("method") != "pct_trail":
        raise ValueError("E13 live_exit.method must be pct_trail")
    if not isinstance(candidate, dict) or candidate.get("method") != "atr_chandelier":
        raise ValueError("E13 candidate_exit.method must be atr_chandelier")
    if not isinstance(paired, dict):
        raise ValueError("E13 paired_shadow must be a mapping")

    live_trail_pct = _positive_float(live.get("trail_pct"), field="E13 live trail_pct")
    live_activate = _nonnegative_float(
        live.get("activate_after_R"), field="E13 live activate_after_R"
    )
    atr_period = _positive_int(candidate.get("atr_period"), field="E13 candidate atr_period")
    atr_method = str(candidate.get("atr_method") or "").strip().lower()
    if atr_method != "true_range_sma":
        raise ValueError("E13 candidate atr_method must be true_range_sma")
    atr_multiplier = _positive_float(
        candidate.get("multiplier"), field="E13 candidate multiplier"
    )
    atr_activate = _nonnegative_float(
        candidate.get("activate_after_R"), field="E13 candidate activate_after_R"
    )

    # The existing research/backtest block and the E13 candidate must not drift.
    try:
        trailing = raw["stop_loss"]["trailing"]
    except (KeyError, TypeError) as exc:
        raise ValueError("config is missing stop_loss.trailing") from exc
    trailing_candidate = (
        isinstance(trailing, dict)
        and trailing.get("enabled") is True
        and trailing.get("method") == "atr_chandelier"
        and _positive_int(trailing.get("atr_period"), field="stop_loss.trailing atr_period")
        == atr_period
        and _positive_float(trailing.get("multiplier"), field="stop_loss.trailing multiplier")
        == atr_multiplier
        and _nonnegative_float(
            trailing.get("activate_after_R"), field="stop_loss.trailing activate_after_R"
        )
        == atr_activate
    )
    if not trailing_candidate:
        raise ValueError("stop_loss.trailing and E13 candidate_exit settings drifted")

    schema_version = _positive_int(
        paired.get("schema_version"), field="E13 paired_shadow schema_version"
    )
    if schema_version != _SHADOW_SCHEMA_VERSION:
        raise ValueError(f"E13 paired shadow schema must be {_SHADOW_SCHEMA_VERSION}")
    required_paired = _positive_int(
        paired.get("min_paired_closed_trades"),
        field="E13 paired_shadow min_paired_closed_trades",
    )
    if required_paired < required_clean:
        raise ValueError("paired shadow minimum cannot be below clean-close minimum")
    market_venue = str(paired.get("market_venue") or "").strip().lower()
    timeframe = str(paired.get("timeframe") or "").strip().lower()
    entry_semantics = str(paired.get("entry_timestamp_semantics") or "").strip().lower()
    if market_venue != "binance":
        raise ValueError("E13 paired_shadow market_venue must be binance")
    if timeframe != "15m":
        raise ValueError("E13 paired_shadow timeframe must be 15m")
    if entry_semantics != "signal_bar_open":
        raise ValueError(
            "E13 paired_shadow entry_timestamp_semantics must be signal_bar_open"
        )

    state_path = resolve_e13_artifact_path(
        paired.get("state_path"), field="E13 paired_shadow state_path"
    )
    evidence_path = resolve_e13_artifact_path(
        paired.get("evidence_path"), field="E13 paired_shadow evidence_path"
    )
    reserved_paths = {
        e13_global_lock_path(),
        e13_transaction_path(),
        e13_policy_migration_transaction_path(),
    }
    if state_path == evidence_path:
        raise ValueError("E13 state_path and evidence_path must be different")
    if state_path in reserved_paths or evidence_path in reserved_paths:
        raise ValueError("E13 state/evidence path collides with reserved runtime metadata")
    migration_root = e13_policy_migration_root()
    if state_path.is_relative_to(migration_root) or evidence_path.is_relative_to(
        migration_root
    ):
        raise ValueError("E13 state/evidence path collides with migration namespace")
    policy_hash = _e13_policy_hash(
        config_path=path,
        clean_cutoff=clean_cutoff,
        required_clean=required_clean,
        reasons=reasons,
        live_trail_pct=live_trail_pct,
        live_activate=live_activate,
        atr_period=atr_period,
        atr_method=atr_method,
        atr_multiplier=atr_multiplier,
        atr_activate=atr_activate,
        schema_version=schema_version,
        required_paired=required_paired,
        market_venue=market_venue,
        timeframe=timeframe,
        entry_semantics=entry_semantics,
        state_path=state_path,
        evidence_path=evidence_path,
    )

    return E13Policy(
        config_path=path,
        clean_cutoff=clean_cutoff,
        required_clean_closes=required_clean,
        eligible_close_reasons=reasons,
        live_trail_pct=live_trail_pct,
        live_activate_after_r=live_activate,
        atr_period=atr_period,
        atr_method=atr_method,
        atr_multiplier=atr_multiplier,
        atr_activate_after_r=atr_activate,
        shadow_schema_version=schema_version,
        required_paired_closes=required_paired,
        shadow_market_venue=market_venue,
        shadow_timeframe=timeframe,
        entry_timestamp_semantics=entry_semantics,
        shadow_state_path=state_path,
        shadow_evidence_path=evidence_path,
        policy_provenance_version=E13_POLICY_PROVENANCE_VERSION,
        policy_hash_sha256=policy_hash,
    )


def _finite(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _close_enough(left: Any, right: Any) -> bool:
    if not _finite(left) or not _finite(right):
        return False
    return math.isclose(float(left), float(right), rel_tol=1e-8, abs_tol=1e-8)


def _naive_utc_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC).isoformat()


def _paired_r_is_consistent(record: dict[str, Any], journal: dict[str, Any]) -> bool:
    numeric_fields = (
        "entry_price",
        "initial_sl_price",
        "baseline_exit_price",
        "candidate_exit_price",
    )
    if any(isinstance(record.get(field), bool) for field in numeric_fields):
        return False
    try:
        entry = float(record["entry_price"])
        initial_sl = float(record["initial_sl_price"])
        baseline_exit = float(record["baseline_exit_price"])
        candidate_exit = float(record["candidate_exit_price"])
    except (KeyError, TypeError, ValueError):
        return False
    values = (entry, initial_sl, baseline_exit, candidate_exit)
    if not all(math.isfinite(value) and value > 0 for value in values):
        return False
    risk = abs(entry - initial_sl)
    if risk <= 0:
        return False
    side = journal["side"]
    if (side == "long" and initial_sl >= entry) or (side == "short" and initial_sl <= entry):
        return False
    baseline_r = (
        (baseline_exit - entry) / risk
        if side == "long"
        else (entry - baseline_exit) / risk
    )
    candidate_r = (
        (candidate_exit - entry) / risk
        if side == "long"
        else (entry - candidate_exit) / risk
    )
    return _close_enough(record.get("baseline_realized_r"), baseline_r) and _close_enough(
        record.get("candidate_realized_r"), candidate_r
    )


def _journal_clean_rows(
    connection: duckdb.DuckDBPyConnection,
    policy: E13Policy,
) -> tuple[dict[str, dict[str, Any]], int, Counter[str], int, int]:
    rows = connection.execute(
        """
        SELECT trade_id, ts_open, ts_close, side, entry_price, exit_price,
               realized_pnl_usdt, realized_r, close_reason
        FROM futures_trades_closed
        WHERE ts_close >= ?
        ORDER BY ts_close, trade_id
        """,
        [policy.clean_cutoff.replace(tzinfo=None)],
    ).fetchall()
    clean: dict[str, dict[str, Any]] = {}
    excluded: Counter[str] = Counter()
    invalid = 0
    opened_before_cutoff = 0
    for row in rows:
        trade_id, ts_open, ts_close, side, entry, exit_price, pnl, realized_r, reason = row
        normalized_reason = str(reason or "<missing>").strip().lower()
        if normalized_reason not in policy.eligible_close_reasons:
            excluded[normalized_reason] += 1
            continue
        if isinstance(ts_open, datetime) and ts_open < policy.clean_cutoff.replace(tzinfo=None):
            opened_before_cutoff += 1
            continue
        valid = (
            bool(trade_id)
            and isinstance(ts_open, datetime)
            and isinstance(ts_close, datetime)
            and str(side).lower() in {"long", "short"}
            and _finite(entry)
            and float(entry) > 0
            and _finite(exit_price)
            and float(exit_price) > 0
            and _finite(pnl)
            and _finite(realized_r)
        )
        if not valid or str(trade_id) in clean:
            invalid += 1
            continue
        clean[str(trade_id)] = {
            "trade_id": str(trade_id),
            "ts_open": ts_open,
            "ts_close": ts_close,
            "side": str(side).lower(),
            "entry_price": float(entry),
            "exit_price": float(exit_price),
            "realized_r": float(realized_r),
            "close_reason": normalized_reason,
        }
    return clean, len(rows), excluded, invalid, opened_before_cutoff


def _read_paired_shadow(
    policy: E13Policy,
    clean: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], Counter[str]]:
    transaction_path = validate_e13_artifact_path(
        e13_transaction_path(),
        field="E13 recovery transaction",
    )
    if transaction_path.exists():
        return [], Counter({"pending_recovery_transaction": 1})
    migration_transaction_path = validate_e13_artifact_path(
        e13_policy_migration_transaction_path(),
        field="E13 policy migration transaction",
    )
    if migration_transaction_path.exists():
        return [], Counter({"pending_policy_migration": 1})
    path = validate_e13_artifact_path(
        policy.shadow_evidence_path,
        field="E13 shadow evidence",
    )
    if not path.exists():
        return [], Counter()
    valid: list[dict[str, Any]] = []
    invalid: Counter[str] = Counter()
    seen: set[str] = set()
    for line in secure_read_text(path, field="E13 shadow evidence").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            invalid["invalid_json"] += 1
            continue
        if not isinstance(record, dict):
            invalid["not_an_object"] += 1
            continue
        trade_id = str(record.get("trade_id") or "")
        journal = clean.get(trade_id)
        reason = ""
        if not journal:
            reason = "not_a_clean_journal_trade"
        elif trade_id in seen:
            reason = "duplicate_trade_id"
        elif record.get("schema_version") != policy.shadow_schema_version:
            reason = "schema_mismatch"
        elif (
            record.get("policy_provenance_version")
            != policy.policy_provenance_version
        ):
            reason = "policy_provenance_mismatch"
        elif record.get("source") != _SHADOW_SOURCE or record.get("causal") is not True:
            reason = "untrusted_source"
        elif record.get("policy_hash_sha256") != policy.policy_hash_sha256:
            reason = "policy_hash_mismatch"
        elif str(record.get("side") or "").lower() != journal["side"]:
            reason = "side_mismatch"
        elif str(record.get("baseline_close_reason") or "").lower() != journal["close_reason"]:
            reason = "close_reason_mismatch"
        elif not _close_enough(record.get("entry_price"), journal["entry_price"]):
            reason = "entry_price_mismatch"
        elif not _close_enough(record.get("baseline_exit_price"), journal["exit_price"]):
            reason = "baseline_exit_price_mismatch"
        elif not _close_enough(record.get("baseline_realized_r"), journal["realized_r"]):
            reason = "baseline_r_mismatch"
        elif not _finite(record.get("candidate_exit_price")) or float(
            record["candidate_exit_price"]
        ) <= 0:
            reason = "invalid_candidate_exit"
        elif not _finite(record.get("candidate_realized_r")):
            reason = "invalid_candidate_r"
        elif record.get("candidate_close_reason") not in {
            "atr_chandelier_gap",
            "atr_chandelier_stop",
            "shared_initial_stop",
            "shared_initial_stop_gap",
        }:
            reason = "invalid_candidate_close_reason"
        elif record.get("candidate_policy") != {
            "method": "atr_chandelier",
            "atr_period": policy.atr_period,
            "atr_method": policy.atr_method,
            "multiplier": policy.atr_multiplier,
            "activate_after_R": policy.atr_activate_after_r,
            "stop_effective": "next_completed_bar",
            "market_venue": policy.shadow_market_venue,
            "timeframe": policy.shadow_timeframe,
            "entry_timestamp_semantics": policy.entry_timestamp_semantics,
        }:
            reason = "candidate_policy_mismatch"
        elif not _paired_r_is_consistent(record, journal):
            reason = "inconsistent_paired_r"
        elif (
            isinstance(record.get("bars_observed"), bool)
            or not isinstance(record.get("bars_observed"), int)
            or record["bars_observed"] < 1
        ):
            reason = "no_causal_bars"
        else:
            try:
                opened = _parse_aware_utc(record.get("ts_open_utc"), field="ts_open_utc")
                baseline_closed = _parse_aware_utc(
                    record.get("baseline_closed_at_utc"), field="baseline_closed_at_utc"
                )
                candidate_closed = _parse_aware_utc(
                    record.get("candidate_closed_at_utc"), field="candidate_closed_at_utc"
                )
            except ValueError:
                reason = "invalid_timestamp"
            else:
                journal_opened = journal["ts_open"].replace(tzinfo=UTC)
                journal_closed = journal["ts_close"].replace(tzinfo=UTC)
                if opened != journal_opened or baseline_closed != journal_closed:
                    reason = "timestamp_mismatch"
                elif candidate_closed <= opened:
                    reason = "noncausal_candidate_timestamp"
        if reason:
            invalid[reason] += 1
            continue
        seen.add(trade_id)
        valid.append(record)
    # A writer always installs the recovery record before publishing evidence
    # and removes it only after state is durable. This second check prevents a
    # read racing that narrow transaction window from approving partial state.
    validate_e13_artifact_path(
        transaction_path,
        field="E13 recovery transaction",
    )
    if transaction_path.exists():
        return [], Counter({"pending_recovery_transaction": 1})
    validate_e13_artifact_path(
        migration_transaction_path,
        field="E13 policy migration transaction",
    )
    if migration_transaction_path.exists():
        return [], Counter({"pending_policy_migration": 1})
    return valid, invalid


def _paired_metrics(records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    deltas = [
        float(record["candidate_realized_r"]) - float(record["baseline_realized_r"])
        for record in records
    ]
    return {
        "mean_candidate_delta_r": statistics.fmean(deltas),
        "median_candidate_delta_r": statistics.median(deltas),
        "candidate_better_fraction": sum(delta > 0 for delta in deltas) / len(deltas),
        "worst_candidate_delta_r": min(deltas),
        "best_candidate_delta_r": max(deltas),
    }


def e13_exit_evidence(
    journal_path: str | Path,
    *,
    config_path: str | Path = E13_DEFAULT_CONFIG_PATH,
    clean_cutoff: datetime | None = None,
    required_clean_closes: int | None = None,
) -> dict[str, Any]:
    """Evaluate E13 without changing the journal, artifacts, or live exit mode.

    ``clean_cutoff`` and ``required_clean_closes`` are compatibility assertions,
    not overrides.  If supplied they must exactly match the YAML policy.
    """
    policy = load_e13_policy(config_path)
    if clean_cutoff is not None:
        asserted_cutoff = _aware_utc(clean_cutoff, field="clean_cutoff")
        if asserted_cutoff != policy.clean_cutoff:
            raise ValueError("clean_cutoff override is forbidden; update the YAML policy")
    if (
        required_clean_closes is not None
        and required_clean_closes != policy.required_clean_closes
    ):
        raise ValueError("required_clean_closes override is forbidden; update the YAML policy")

    journal = Path(journal_path).expanduser().resolve()
    if not journal.is_file():
        raise FileNotFoundError(journal)
    with duckdb.connect(str(journal), read_only=True) as connection:
        tables = {str(row[0]) for row in connection.execute("SHOW TABLES").fetchall()}
        if "futures_trades_closed" not in tables:
            raise ValueError("journal is missing futures_trades_closed")
        clean, post_cutoff, excluded, invalid_rows, pre_cutoff_opens = _journal_clean_rows(
            connection, policy
        )

    paired, invalid_paired = _read_paired_shadow(policy, clean)
    clean_count = len(clean)
    paired_count = len(paired)
    sample_ready = clean_count >= policy.required_clean_closes
    paired_ready = paired_count >= policy.required_paired_closes
    paired_integrity = not invalid_paired
    review_ready = sample_ready and paired_ready and paired_integrity
    if not paired_integrity:
        decision = "HOLD_PAIRED_SHADOW_EVIDENCE_INTEGRITY"
    elif review_ready:
        decision = "READY_FOR_FORMAL_REVIEW"
    elif not sample_ready:
        decision = "HOLD_CLEAN_SAMPLE_REQUIRED"
    else:
        decision = "HOLD_PAIRED_SHADOW_EVIDENCE_REQUIRED"

    clean_rows = list(clean.values())
    return {
        "experiment": "E13_ATR_CHANDELIER",
        "config": str(policy.config_path),
        "policy_hash_sha256": policy.policy_hash_sha256,
        "policy_provenance_version": policy.policy_provenance_version,
        "journal": str(journal),
        "clean_cutoff_utc": policy.clean_cutoff.isoformat(),
        "eligible_close_reasons": list(policy.eligible_close_reasons),
        "post_cutoff_closed_trades": post_cutoff,
        "clean_closed_trades": clean_count,
        "required_clean_closed_trades": policy.required_clean_closes,
        "remaining_clean_closed_trades": max(policy.required_clean_closes - clean_count, 0),
        "excluded_close_reasons": dict(sorted(excluded.items())),
        "excluded_pre_cutoff_open_trades": pre_cutoff_opens,
        "invalid_post_cutoff_rows": invalid_rows,
        "first_clean_close_utc": _naive_utc_iso(
            min((row["ts_close"] for row in clean_rows), default=None)
        ),
        "last_clean_close_utc": _naive_utc_iso(
            max((row["ts_close"] for row in clean_rows), default=None)
        ),
        "sample_gate_pass": sample_ready,
        "shadow_evidence_artifact": str(policy.shadow_evidence_path),
        "paired_shadow_closed_trades": paired_count,
        "required_paired_shadow_closed_trades": policy.required_paired_closes,
        "remaining_paired_shadow_closed_trades": max(
            policy.required_paired_closes - paired_count, 0
        ),
        "invalid_paired_shadow_records": dict(sorted(invalid_paired.items())),
        "paired_shadow_integrity_pass": paired_integrity,
        "paired_shadow_gate_pass": paired_ready,
        "paired_metrics": _paired_metrics(paired),
        "formal_review_ready": review_ready,
        "promotion_authorized": False,
        "live_exit_mode": policy.live_exit_mode,
        "candidate_exit_mode": policy.candidate_exit_mode,
        "decision": decision,
        "note": (
            "E13 never auto-promotes. Clean direct closes and policy-hashed causal paired "
            "shadow outcomes are both required before explicit formal review."
        ),
    }


__all__ = [
    "E13_DEFAULT_CONFIG_PATH",
    "E13_POLICY_PROVENANCE_VERSION",
    "E13Policy",
    "e13_exit_evidence",
    "e13_legacy_semantic_policy_hash",
    "load_e13_policy",
]
