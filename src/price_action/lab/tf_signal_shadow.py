"""Local, signal-only runner for authorized timeframe shadow specifications.

This module is deliberately unable to submit or cancel exchange orders.  It
reads closed OHLCV bars from the local market snapshot, executes a pinned
``Strategy`` implementation, and appends scans/signals to the candidate's
separate DuckDB journal.  The only accepted configs are the fail-closed specs
created by :mod:`price_action.lab.tf_shadow_promotion`.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import json
import math
import os
import re
import resource
import stat
import subprocess
import sys
import tempfile
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd
import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from price_action.lab.hypothesis_runner import discover_strategy_shelf
from price_action.lab.tf_shadow_promotion import (
    AUTHORIZATION_SCOPE,
    CAPABILITY_CONTRACT,
    SHADOW_CONFIG_SCHEMA,
    EvidenceRejectedError,
    strategy_dependency_closure,
    validate_evidence,
    validate_strategy_capabilities,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

SUPPORTED_TFS: dict[str, int] = {
    "5m": 5,
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "4h": 240,
    "1d": 1440,
}

DEFAULT_SYMBOLS = (
    "AAVE/USDT",
    "ADA/USDT",
    "ALGO/USDT",
    "ATOM/USDT",
    "AVAX/USDT",
    "BNB/USDT",
    "BTC/USDT",
    "DOGE/USDT",
    "DOT/USDT",
    "ETH/USDT",
    "FIL/USDT",
    "LINK/USDT",
    "NEAR/USDT",
    "SOL/USDT",
    "TRX/USDT",
    "XLM/USDT",
    "XRP/USDT",
    "ZEC/USDT",
)

_MAX_CONFIG_BYTES = 512 * 1024
_MAX_WORKER_BYTES = 32 * 1024 * 1024
_WORKER_TIMEOUT_SECONDS = 30
_SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
_WORKER_RELATIVE_PATH = "src/price_action/lab/tf_signal_shadow_worker.py"
_AUTH_SCHEMA = "tf-shadow-principal-authorization-v1"
_AUTH_NONCE_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_JOURNAL_COLUMNS = {
    "shadow_metadata": {"key", "value"},
    "shadow_scans": {"scan_id", "ts", "bar_ts", "symbol", "status", "notes"},
    "shadow_signals": {
        "signal_id",
        "ts",
        "bar_ts",
        "symbol",
        "strategy",
        "timeframe",
        "side",
        "entry_reference",
        "sl_reference",
        "tp_reference",
        "status",
        "notes",
    },
}


class ShadowRunError(RuntimeError):
    """A shadow config, input, or journal failed a safety invariant."""


class StrategyCapabilityError(ShadowRunError):
    """Strategy attempted a capability forbidden in signal-only shadow mode."""


@dataclass(frozen=True)
class ValidatedShadowConfig:
    path: Path
    candidate_id: str
    strategy: str
    timeframe: str
    module_path: Path
    journal_path: Path
    evidence_path: Path
    payload: dict[str, Any]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _python_ast_sha256(raw: bytes, *, label: str) -> str:
    try:
        tree = ast.parse(raw.decode("utf-8"), filename=label)
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise StrategyCapabilityError(f"snapshot source is not valid Python: {label}") from exc
    return _sha256_bytes(ast.dump(tree, annotate_fields=True, include_attributes=False).encode())


def _safe_repo_file(
    repo_root: Path,
    value: Any,
    *,
    field: str,
    required_parent: Path | None = None,
) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ShadowRunError(f"{field} must be a non-empty repo-relative path")
    root = repo_root.resolve()
    path = (root / value).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ShadowRunError(f"{field} escapes repository root") from exc
    if required_parent is not None:
        parent = (root / required_parent).resolve()
        try:
            path.relative_to(parent)
        except ValueError as exc:
            raise ShadowRunError(f"{field} is outside {required_parent}") from exc
    if path.is_symlink() or not path.is_file():
        raise ShadowRunError(f"{field} is missing or unsafe: {value}")
    return path


def validate_shadow_config(
    config_path: Path,
    *,
    repo_root: Path = REPO_ROOT,
) -> ValidatedShadowConfig:
    """Validate the complete no-exchange boundary before opening any journal."""

    repo_root = Path(repo_root).resolve()
    config_path = Path(config_path)
    if config_path.is_symlink() or not config_path.is_file():
        raise ShadowRunError("shadow config is missing or is a symlink")
    raw = config_path.read_bytes()
    if len(raw) > _MAX_CONFIG_BYTES:
        raise ShadowRunError("shadow config is unexpectedly large")
    try:
        payload = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ShadowRunError(f"invalid shadow YAML: {exc}") from exc
    if not isinstance(payload, dict):
        raise ShadowRunError("shadow config root must be an object")

    candidate_id = payload.get("candidate_id")
    strategy = payload.get("strategy")
    timeframe = payload.get("timeframe")
    if payload.get("schema_version") != SHADOW_CONFIG_SCHEMA:
        raise ShadowRunError("unsupported shadow config schema")
    if not isinstance(candidate_id, str) or not candidate_id.startswith("tf-"):
        raise ShadowRunError("invalid candidate_id")
    if not isinstance(strategy, str) or strategy not in discover_strategy_shelf():
        raise ShadowRunError("strategy is not a concrete local Strategy module")
    if timeframe not in SUPPORTED_TFS:
        raise ShadowRunError("unsupported shadow timeframe")

    mode = payload.get("mode") or {}
    exchange = payload.get("exchange") or {}
    runtime = payload.get("runtime") or {}
    exact_false = (
        exchange.get("enabled") is False,
        exchange.get("credentials_allowed") is False,
        exchange.get("market_data_private_api_allowed") is False,
        exchange.get("order_submit_allowed") is False,
        exchange.get("cancel_order_allowed") is False,
        runtime.get("auto_start") is False,
        runtime.get("launchd_bootstrap_allowed") is False,
        runtime.get("daemon_restart_allowed") is False,
    )
    exact_true = (
        mode.get("sim_only") is True,
        mode.get("signal_only") is True,
        runtime.get("scheduler_tick_requires_queue_authorization") is True,
    )
    if mode.get("run_mode") != "shadow" or not all(exact_false + exact_true):
        raise ShadowRunError("config violates the signal-only/no-exchange boundary")
    if payload.get("capabilities") != CAPABILITY_CONTRACT:
        raise ShadowRunError("config capability contract is missing or changed")

    module = payload.get("strategy_module") or {}
    expected_module = f"src/price_action/strategies/{strategy}.py"
    if module.get("path") != expected_module:
        raise ShadowRunError("strategy module path does not match strategy")
    module_path = _safe_repo_file(
        repo_root,
        module.get("path"),
        field="strategy_module.path",
        required_parent=Path("src/price_action/strategies"),
    )
    if module.get("sha256") != _sha256_file(module_path):
        raise ShadowRunError("strategy module hash drifted after authorization")
    try:
        validate_strategy_capabilities(module_path, strategy)
    except EvidenceRejectedError as exc:
        raise ShadowRunError(f"strategy capability contract rejected module: {exc}") from exc
    try:
        expected_closure = strategy_dependency_closure(
            repo_root,
            strategy=strategy,
            timeframe=str(timeframe),
        )
    except EvidenceRejectedError as exc:
        raise ShadowRunError(f"strategy dependency closure rejected: {exc}") from exc
    if payload.get("strategy_dependency_closure") != expected_closure:
        raise ShadowRunError("strategy transitive dependency closure hash/scan drifted")

    principal = payload.get("principal_authorization")
    if not isinstance(principal, dict) or set(principal) != {
        "algorithm",
        "artifact",
        "max_validity_seconds",
        "public_key_path",
        "public_key_sha256",
        "state",
    }:
        raise ShadowRunError("principal authorization policy is missing or malformed")
    if principal.get("algorithm") != "Ed25519" or principal.get("state") != (
        "SPEC_READY_NOT_RUNNING"
    ):
        raise ShadowRunError("principal authorization policy/state is invalid")
    if not isinstance(principal.get("artifact"), str) or not principal["artifact"]:
        raise ShadowRunError("principal authorization artifact path is invalid")
    if (
        not isinstance(principal.get("public_key_sha256"), str)
        or re.fullmatch(r"[0-9a-f]{64}", principal["public_key_sha256"]) is None
    ):
        raise ShadowRunError("principal public key sha256 is invalid")

    evidence = payload.get("evidence") or {}
    evidence_path = _safe_repo_file(
        repo_root,
        evidence.get("artifact"),
        field="evidence.artifact",
        required_parent=Path("reports/tf_robustness"),
    )
    if evidence.get("artifact_sha256") != _sha256_file(evidence_path):
        raise ShadowRunError("evidence artifact hash mismatch")
    if (
        evidence.get("independent_oos") is not True
        or evidence.get("deployment_authorized") is not True
        or evidence.get("authorization_scope") != "SIGNAL_ONLY_SHADOW"
    ):
        raise ShadowRunError("evidence scope is not SIGNAL_ONLY_SHADOW")
    try:
        validated_evidence = validate_evidence(
            evidence_path,
            evidence_dir=evidence_path.parent,
            repo_root=repo_root,
        )
    except EvidenceRejectedError as exc:
        raise ShadowRunError(f"independent evidence rejected: {exc}") from exc
    if validated_evidence.strategy != strategy or validated_evidence.candidate_tf != timeframe:
        raise ShadowRunError("config identity differs from evidence identity")
    evidence_principal = validated_evidence.payload.get("authorization", {}).get(
        "principal_authorization"
    )
    config_principal_policy = {
        key: principal.get(key)
        for key in (
            "algorithm",
            "max_validity_seconds",
            "public_key_path",
            "public_key_sha256",
        )
    }
    if config_principal_policy != evidence_principal:
        raise ShadowRunError("Principal key policy differs from canonical OOS evidence pin")

    journal = payload.get("journal") or {}
    journal_path = _safe_repo_file(
        repo_root,
        journal.get("path"),
        field="journal.path",
        required_parent=Path("data/shadow"),
    )
    if journal.get("namespace") != candidate_id:
        raise ShadowRunError("journal namespace differs from candidate_id")
    _verify_journal(journal_path, candidate_id, evidence["artifact_sha256"])

    return ValidatedShadowConfig(
        path=config_path.resolve(),
        candidate_id=candidate_id,
        strategy=strategy,
        timeframe=timeframe,
        module_path=module_path,
        journal_path=journal_path,
        evidence_path=evidence_path,
        payload=payload,
    )


def _verify_journal(path: Path, candidate_id: str, evidence_sha: str) -> None:
    try:
        con = duckdb.connect(str(path), read_only=True)
        try:
            for table, expected in _REQUIRED_JOURNAL_COLUMNS.items():
                columns = {
                    row[1] for row in con.execute(f"PRAGMA table_info('{table}')").fetchall()
                }
                if columns != expected:
                    raise ShadowRunError(f"shadow journal schema mismatch: {table}")
            metadata = dict(con.execute("SELECT key, value FROM shadow_metadata").fetchall())
        finally:
            con.close()
    except duckdb.Error as exc:
        raise ShadowRunError(f"shadow journal is unreadable: {exc}") from exc
    expected_meta = {
        "candidate_id": candidate_id,
        "evidence_sha256": evidence_sha,
        "exchange_enabled": "false",
        "signal_only": "true",
    }
    if any(metadata.get(key) != value for key, value in expected_meta.items()):
        raise ShadowRunError("shadow journal metadata identity mismatch")


def _bar_delta(timeframe: str) -> timedelta:
    return timedelta(minutes=SUPPORTED_TFS[timeframe])


def _load_direct_bars(
    con: duckdb.DuckDBPyConnection,
    symbol: str,
    timeframe: str,
) -> pd.DataFrame:
    return con.execute(
        """
        SELECT ts, open, high, low, close, volume
        FROM ohlcv
        WHERE venue='binance' AND symbol=? AND timeframe=?
        ORDER BY ts
        """,
        [symbol, timeframe],
    ).fetchdf()


def _resample_15m(source: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    target_minutes = SUPPORTED_TFS[timeframe]
    if target_minutes < 15 or target_minutes % 15:
        return pd.DataFrame()
    expected = target_minutes // 15
    source = source.set_index("ts")
    grouped = source.resample(f"{target_minutes}min", label="left", closed="left")
    bars = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
    )
    counts = grouped["close"].count()
    return bars[counts == expected].dropna().reset_index()


def load_closed_bars(
    market_db: Path,
    *,
    symbol: str,
    timeframe: str,
    now: datetime,
    max_bars: int = 2000,
) -> pd.DataFrame:
    """Read complete local bars only; never contacts a market-data API."""

    if now.tzinfo is None:
        raise ShadowRunError("now must be timezone-aware")
    market_db = Path(market_db)
    if market_db.is_symlink() or not market_db.is_file():
        raise ShadowRunError("local market snapshot is missing or unsafe")
    try:
        con = duckdb.connect(str(market_db), read_only=True)
        try:
            bars = _load_direct_bars(con, symbol, timeframe)
            if bars.empty and timeframe in {"30m", "1h", "4h", "1d"}:
                bars = _load_direct_bars(con, symbol, "15m")
                if not bars.empty:
                    bars["ts"] = pd.to_datetime(bars["ts"], utc=True)
                    bars = _resample_15m(bars, timeframe)
        finally:
            con.close()
    except duckdb.Error as exc:
        raise ShadowRunError(f"market snapshot read failed: {exc}") from exc
    if bars.empty:
        return bars

    bars["ts"] = pd.to_datetime(bars["ts"], utc=True)
    bars = bars.sort_values("ts").drop_duplicates("ts", keep=False)
    close_cutoff = pd.Timestamp(now.astimezone(UTC)) - pd.Timedelta(_bar_delta(timeframe))
    bars = bars[bars["ts"] <= close_cutoff]
    numeric = ["open", "high", "low", "close", "volume"]
    for column in numeric:
        bars[column] = pd.to_numeric(bars[column], errors="coerce")
    valid = (
        bars[numeric].notna().all(axis=1)
        & (bars[["open", "high", "low", "close"]] > 0).all(axis=1)
        & (bars["high"] >= bars[["open", "close", "low"]].max(axis=1))
        & (bars["low"] <= bars[["open", "close", "high"]].min(axis=1))
        & (bars["volume"] >= 0)
    )
    if not bool(valid.all()):
        raise ShadowRunError(f"{symbol}/{timeframe}: invalid OHLCV rows")
    return bars.tail(max_bars).reset_index(drop=True)


def _canonical_json_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def _sbpl_literal(path: Path) -> str:
    return str(Path(path).absolute()).replace("\\", "\\\\").replace('"', '\\"')


def _checked_snapshot_relative(value: Any) -> Path:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise StrategyCapabilityError("strategy closure path must be repo-relative")
    relative = Path(value)
    if ".." in relative.parts or not relative.parts:
        raise StrategyCapabilityError("strategy closure path escapes its snapshot")
    return relative


def _read_pinned_source(repo_root: Path, relative: Path) -> bytes:
    """Read one regular source without following a symlink at any path component."""

    root = Path(repo_root).resolve()
    source = root / relative
    cursor = source
    while cursor != root:
        if cursor.is_symlink():
            raise StrategyCapabilityError(f"strategy closure contains a symlink: {relative}")
        cursor = cursor.parent
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
    except OSError as exc:
        raise StrategyCapabilityError(f"strategy closure source is missing/unsafe: {relative}") from exc
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise StrategyCapabilityError(f"strategy closure source is not regular: {relative}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def _write_snapshot_file(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o400)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _materialize_strategy_snapshot(
    validated: ValidatedShadowConfig,
    *,
    repo_root: Path,
    snapshot_root: Path,
) -> Path:
    """Copy only the config-pinned source closure into an isolated temp tree."""

    closure = validated.payload.get("strategy_dependency_closure")
    if not isinstance(closure, list) or not closure:
        raise StrategyCapabilityError("strategy dependency closure is missing")
    copied: set[str] = set()
    seen: set[str] = set()
    root = Path(repo_root).resolve()
    snapshot = Path(snapshot_root).resolve()
    for row in closure:
        if not isinstance(row, dict):
            raise StrategyCapabilityError("strategy dependency closure row is invalid")
        relative = _checked_snapshot_relative(row.get("path"))
        relative_text = str(relative)
        if relative_text in seen:
            raise StrategyCapabilityError("strategy dependency closure contains duplicate paths")
        seen.add(relative_text)
        source = root / relative
        if row.get("absent") is True:
            if set(row) != {"path", "absent", "kind"} or row.get("kind") != "manifest":
                raise StrategyCapabilityError("absent strategy manifest receipt is malformed")
            if source.exists() or source.is_symlink():
                raise StrategyCapabilityError("pinned absent strategy manifest now exists")
            continue

        raw = _read_pinned_source(root, relative)
        if row.get("sha256") != _sha256_bytes(raw):
            raise StrategyCapabilityError(f"strategy closure source hash drifted: {relative_text}")
        if row.get("kind") == "manifest":
            if set(row) != {"path", "sha256", "kind"}:
                raise StrategyCapabilityError("strategy manifest closure receipt is malformed")
        else:
            if set(row) != {"path", "sha256", "ast_sha256"}:
                raise StrategyCapabilityError("Python strategy closure receipt is malformed")
            if row.get("ast_sha256") != _python_ast_sha256(raw, label=relative_text):
                raise StrategyCapabilityError(f"strategy closure AST drifted: {relative_text}")

        target = snapshot / relative
        try:
            target.resolve().relative_to(snapshot)
        except ValueError as exc:  # pragma: no cover - guarded by relative parser
            raise StrategyCapabilityError("strategy snapshot target escaped") from exc
        _write_snapshot_file(target, raw)
        if target.read_bytes() != raw or _sha256_file(target) != row["sha256"]:
            raise StrategyCapabilityError(f"strategy snapshot copy verification failed: {relative_text}")
        if "ast_sha256" in row and row["ast_sha256"] != _python_ast_sha256(
            target.read_bytes(), label=relative_text
        ):
            raise StrategyCapabilityError(f"strategy snapshot AST verification failed: {relative_text}")
        copied.add(relative_text)

    required = {
        f"src/price_action/strategies/{validated.strategy}.py",
        _WORKER_RELATIVE_PATH,
    }
    if not required.issubset(copied):
        raise StrategyCapabilityError("strategy snapshot lacks required pinned sources")
    worker = snapshot / _WORKER_RELATIVE_PATH
    if worker.is_symlink() or not worker.is_file():  # pragma: no cover - defensive
        raise StrategyCapabilityError("pinned signal-shadow worker snapshot is unsafe")
    return worker


def _strategy_worker_sandbox_profile(
    python_path: Path,
    snapshot_root: Path | None = None,
) -> str:
    """Deny all reads except the exact snapshot and interpreter runtime."""

    executable_paths = {Path(python_path).absolute(), Path(python_path).resolve()}
    # Keep both lexical and resolved prefixes.  ``uv``/venv installations use
    # a two-stage symlink (venv -> unversioned runtime -> versioned runtime),
    # and Seatbelt must be able to traverse each pinned spelling without
    # granting access to the surrounding home/repository tree.
    runtime_prefixes = {
        Path(sys.base_prefix).absolute(),
        Path(sys.base_exec_prefix).absolute(),
        Path(sys.exec_prefix).absolute(),
        Path(sys.prefix).absolute(),
    }
    runtime_roots = runtime_prefixes | {path.resolve() for path in runtime_prefixes}
    system_runtime_roots = {
        Path("/System/Library/CoreServices"),
        Path("/System/Library/Frameworks"),
        Path("/System/Library/PrivateFrameworks"),
        Path("/usr/lib"),
        Path("/Library/Apple/System/Library"),
        Path("/private/var/db/dyld"),
    }
    lines = [
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        "(deny file-write*)",
        "(deny process-exec)",
        "(deny file-read*)",
        # Python needs to traverse the filesystem root before it reaches the
        # exact runtime/snapshot allowlists.  This literal permits only the
        # root directory itself, not any child subtree.
        '(allow file-read* (literal "/"))',
    ]
    lines.extend(
        f'(allow process-exec (literal "{_sbpl_literal(path)}"))'
        for path in sorted(executable_paths, key=str)
    )
    lines.extend(
        f'(allow file-read* (subpath "{_sbpl_literal(path)}"))'
        for path in sorted(runtime_roots, key=str)
    )
    lines.extend(
        f'(allow file-read* (subpath "{_sbpl_literal(path)}"))'
        for path in sorted(system_runtime_roots, key=str)
        if path.exists()
    )
    if snapshot_root is not None:
        lines.append(
            f'(allow file-read* (literal "{_sbpl_literal(Path(snapshot_root).resolve())}"))'
        )
        lines.append(
            f'(allow file-read* (subpath "{_sbpl_literal(Path(snapshot_root).resolve())}"))'
        )
    runtime_literals = (
        Path("/dev/null"),
        Path("/dev/random"),
        Path("/dev/urandom"),
        Path("/usr/share/zoneinfo/UTC"),
        Path("/var/db/timezone/zoneinfo/UTC"),
    )
    for device in runtime_literals:
        if device.exists():
            lines.append(f'(allow file-read* (literal "{_sbpl_literal(device)}"))')
    return "\n".join(lines)


def _worker_resource_limits() -> None:
    resource.setrlimit(resource.RLIMIT_CPU, (_WORKER_TIMEOUT_SECONDS, _WORKER_TIMEOUT_SECONDS))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024 * 1024, 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (64, 64))
    with suppress(ValueError):
        resource.setrlimit(resource.RLIMIT_AS, (4 * 1024**3, 4 * 1024**3))


def _run_strategy_worker(
    validated: ValidatedShadowConfig,
    frame: pd.DataFrame,
    *,
    repo_root: Path,
) -> list[dict[str, Any]]:
    """Execute strategy code only in a fail-closed macOS Seatbelt worker."""

    if not _SANDBOX_EXEC.is_file() or _SANDBOX_EXEC.is_symlink():
        raise StrategyCapabilityError("macOS sandbox-exec is required for strategy evaluation")
    class_name = discover_strategy_shelf()[validated.strategy][0]
    bars = [
        {
            "close": float(row.close),
            "high": float(row.high),
            "low": float(row.low),
            "open": float(row.open),
            "symbol": str(row.symbol),
            "timeframe": str(row.timeframe),
            "ts": pd.Timestamp(row.ts).isoformat(),
            "venue": str(row.venue),
            "volume": float(row.volume),
        }
        for row in frame.itertuples(index=False)
    ]
    request = _canonical_json_bytes(
        {
            "bars": bars,
            "class_name": class_name,
            "schema_version": "tf-signal-shadow-worker-request-v1",
            "strategy": validated.strategy,
            "timeframe": validated.timeframe,
        }
    )
    if len(request) > _MAX_WORKER_BYTES:
        raise StrategyCapabilityError("strategy worker request exceeds the byte cap")
    python_path = Path(sys.executable).absolute()
    with tempfile.TemporaryDirectory(prefix="tf-signal-shadow-worker-") as temp_name:
        snapshot_root = Path(temp_name) / "snapshot"
        snapshot_root.mkdir(mode=0o700)
        worker_path = _materialize_strategy_snapshot(
            validated,
            repo_root=Path(repo_root),
            snapshot_root=snapshot_root,
        )
        command = [
            str(_SANDBOX_EXEC),
            "-p",
            _strategy_worker_sandbox_profile(python_path, snapshot_root),
            str(python_path),
            "-I",
            str(worker_path),
        ]
        env = {
            "HOME": str(snapshot_root),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PATH": "/usr/bin:/bin",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONHASHSEED": "0",
            "NUMBA_DISABLE_JIT": "1",
            "PA_ENGULF_NUMBA": "0",
            "PA_LOG_QUIET": "1",
            "PA_DISABLE_FILE_LOG": "1",
            "PA_RUNTIME_ROOT": str(snapshot_root),
            "PA_TESTING": "1",
            "TZ": "UTC",
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
        }
        try:
            completed = subprocess.run(
                command,
                cwd=snapshot_root,
                env=env,
                input=request,
                capture_output=True,
                timeout=_WORKER_TIMEOUT_SECONDS + 5,
                check=False,
                preexec_fn=_worker_resource_limits,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise StrategyCapabilityError(f"sandboxed strategy worker failed: {exc}") from exc
        if completed.returncode != 0:
            stderr = completed.stderr.decode("utf-8", errors="replace")[:1000]
            raise StrategyCapabilityError(
                f"sandboxed strategy worker exited {completed.returncode}: {stderr}"
            )
        if not completed.stdout or len(completed.stdout) > _MAX_WORKER_BYTES:
            raise StrategyCapabilityError("sandboxed strategy worker output violates the byte cap")
        try:
            response = json.loads(completed.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StrategyCapabilityError("sandboxed strategy worker output is invalid JSON") from exc
        if not isinstance(response, dict) or completed.stdout != _canonical_json_bytes(response):
            raise StrategyCapabilityError("sandboxed strategy worker output is not canonical")
        if (
            response.get("schema_version") != "tf-signal-shadow-worker-response-v1"
            or response.get("status") != "OK"
            or not isinstance(response.get("signals"), list)
        ):
            raise StrategyCapabilityError("sandboxed strategy worker response contract failed")
        signals = response["signals"]
    return signals


def _stable_id(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def _json_notes(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def verify_principal_authorization(
    validated: ValidatedShadowConfig,
    *,
    repo_root: Path,
    authorization_path: Path,
    now: datetime,
) -> dict[str, Any]:
    """Verify an external Ed25519 Principal authorization artifact."""

    if now.tzinfo is None:
        raise ShadowRunError("authorization verification time must be timezone-aware")
    now = now.astimezone(UTC)
    policy = validated.payload["principal_authorization"]
    configured_artifact = _safe_repo_file(
        repo_root,
        policy["artifact"],
        field="principal_authorization.artifact",
        required_parent=Path("memory/researcher/shadow_authorizations"),
    )
    if Path(authorization_path).resolve() != configured_artifact:
        raise ShadowRunError("authorization artifact path differs from config pin")
    public_key_path = _safe_repo_file(
        repo_root,
        policy["public_key_path"],
        field="principal_authorization.public_key_path",
        required_parent=Path("configs/keys"),
    )
    public_key_raw = public_key_path.read_bytes()
    if _sha256_file(public_key_path) != policy["public_key_sha256"]:
        raise ShadowRunError("Principal public key hash differs from config pin")
    if len(public_key_raw) != 32:
        raise ShadowRunError("Principal Ed25519 public key must contain exactly 32 raw bytes")
    raw = configured_artifact.read_bytes()
    if len(raw) > 128 * 1024:
        raise ShadowRunError("Principal authorization artifact exceeds the byte cap")
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShadowRunError("Principal authorization artifact is invalid JSON") from exc
    if not isinstance(payload, dict) or raw != _canonical_json_bytes(payload):
        raise ShadowRunError("Principal authorization artifact is not canonical JSON")
    expected_fields = {
        "candidate_id",
        "config_sha256",
        "decision",
        "evidence_sha256",
        "expires_at",
        "issued_at",
        "nonce",
        "schema_version",
        "scope",
        "signature",
    }
    if set(payload) != expected_fields:
        raise ShadowRunError("Principal authorization artifact fields are not exact")
    if (
        payload.get("schema_version") != _AUTH_SCHEMA
        or payload.get("decision") != "AUTHORIZE_SIGNAL_SHADOW_TICK"
        or payload.get("scope") != AUTHORIZATION_SCOPE
        or payload.get("candidate_id") != validated.candidate_id
        or payload.get("evidence_sha256")
        != validated.payload["evidence"]["artifact_sha256"]
        or payload.get("config_sha256") != _sha256_file(validated.path)
        or not isinstance(payload.get("nonce"), str)
        or _AUTH_NONCE_RE.fullmatch(payload["nonce"]) is None
    ):
        raise ShadowRunError("Principal authorization identity/scope binding failed")
    try:
        issued = datetime.fromisoformat(str(payload["issued_at"]).replace("Z", "+00:00"))
        expires = datetime.fromisoformat(str(payload["expires_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ShadowRunError("Principal authorization timestamps are invalid") from exc
    if issued.tzinfo is None or expires.tzinfo is None:
        raise ShadowRunError("Principal authorization timestamps must be timezone-aware")
    issued, expires = issued.astimezone(UTC), expires.astimezone(UTC)
    max_validity = policy["max_validity_seconds"]
    if not issued <= now < expires or (expires - issued).total_seconds() > max_validity:
        raise ShadowRunError("Principal authorization is not active or exceeds max validity")
    unsigned = dict(payload)
    signature_text = unsigned.pop("signature")
    try:
        signature = base64.b64decode(signature_text, validate=True)
        Ed25519PublicKey.from_public_bytes(public_key_raw).verify(
            signature,
            _canonical_json_bytes(unsigned),
        )
    except (ValueError, TypeError, InvalidSignature) as exc:
        raise ShadowRunError("Principal Ed25519 authorization signature is invalid") from exc

    # A nonce may authorize repeated ticks for this exact candidate until
    # expiry, but it cannot appear in a second authorization artifact.
    for other in configured_artifact.parent.glob("*.json"):
        if other.resolve() == configured_artifact:
            continue
        try:
            other_payload = json.loads(other.read_bytes())
        except Exception:
            continue
        if isinstance(other_payload, dict) and other_payload.get("nonce") == payload["nonce"]:
            raise ShadowRunError("Principal authorization nonce replayed in another artifact")
    return payload


def run_shadow_config(
    config_path: Path,
    *,
    repo_root: Path = REPO_ROOT,
    market_db: Path | None = None,
    now: datetime | None = None,
    symbols: tuple[str, ...] = DEFAULT_SYMBOLS,
    authorization_path: Path | None = None,
) -> dict[str, Any]:
    """Run one idempotent local scan for every symbol's newest closed bar."""

    validated = validate_shadow_config(config_path, repo_root=repo_root)
    now = (now or datetime.now(UTC)).astimezone(UTC)
    configured_authorization = (
        Path(repo_root) / validated.payload["principal_authorization"]["artifact"]
    )
    verify_principal_authorization(
        validated,
        repo_root=Path(repo_root),
        authorization_path=Path(authorization_path or configured_authorization),
        now=now,
    )
    if not _SANDBOX_EXEC.is_file() or _SANDBOX_EXEC.is_symlink():
        raise StrategyCapabilityError("macOS sandbox-exec is required; shadow remains HOLD")
    db_path = Path(market_db or Path(repo_root) / "data" / "market.duckdb")
    counts = {"symbols": 0, "scanned": 0, "already_scanned": 0, "signals": 0, "errors": 0}
    details: list[dict[str, Any]] = []

    con = duckdb.connect(str(validated.journal_path))
    try:
        for symbol in symbols:
            counts["symbols"] += 1
            try:
                bars = load_closed_bars(
                    db_path,
                    symbol=symbol,
                    timeframe=validated.timeframe,
                    now=now,
                )
                if bars.empty:
                    details.append({"symbol": symbol, "status": "NO_LOCAL_DATA"})
                    continue
                bar_ts = pd.Timestamp(bars["ts"].iloc[-1]).to_pydatetime()
                scan_id = _stable_id(validated.candidate_id, symbol, bar_ts.isoformat())
                exists = con.execute(
                    "SELECT 1 FROM shadow_scans WHERE scan_id=?",
                    [scan_id],
                ).fetchone()
                if exists:
                    counts["already_scanned"] += 1
                    details.append(
                        {
                            "symbol": symbol,
                            "bar_ts": bar_ts.isoformat(),
                            "status": "ALREADY_SCANNED",
                        }
                    )
                    continue

                frame = bars.copy()
                frame["venue"] = "binance"
                frame["symbol"] = symbol
                frame["timeframe"] = validated.timeframe
                generated = _run_strategy_worker(validated, frame, repo_root=Path(repo_root))
                expected_signal_fields = {
                    "confluence_score",
                    "direction",
                    "fingerprint",
                    "pattern_id",
                    "sl_price",
                    "tp_price",
                    "ts",
                }
                if any(
                    not isinstance(signal, dict) or set(signal) != expected_signal_fields
                    for signal in generated
                ):
                    raise ShadowRunError("strategy worker emitted a malformed signal")
                signals = [
                    signal
                    for signal in generated
                    if pd.Timestamp(signal["ts"]).tz_convert("UTC") == pd.Timestamp(bar_ts)
                ]
                status = "SIGNAL" if signals else "NO_SIGNAL"
                con.execute(
                    "INSERT INTO shadow_scans VALUES (?, ?, ?, ?, ?, ?)",
                    [
                        scan_id,
                        now,
                        bar_ts,
                        symbol,
                        status,
                        _json_notes(
                            {
                                "source": "local_market_snapshot",
                                "exchange_io": False,
                                "n_bars": len(frame),
                            }
                        ),
                    ],
                )
                entry_reference = float(frame["close"].iloc[-1])
                for signal in signals:
                    values = (
                        entry_reference,
                        float(signal["sl_price"]),
                        float(signal["tp_price"]),
                        float(signal["confluence_score"]),
                    )
                    if not all(math.isfinite(value) for value in values):
                        raise ShadowRunError("strategy emitted non-finite signal values")
                    fingerprint = signal.get("fingerprint")
                    if not isinstance(fingerprint, str) or not fingerprint:
                        raise ShadowRunError("strategy worker emitted invalid signal fingerprint")
                    signal_id = _stable_id(scan_id, fingerprint)
                    con.execute(
                        "INSERT INTO shadow_signals VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        [
                            signal_id,
                            now,
                            bar_ts,
                            symbol,
                            validated.strategy,
                            validated.timeframe,
                            signal["direction"],
                            entry_reference,
                            signal["sl_price"],
                            signal["tp_price"],
                            "OBSERVED_SIGNAL_ONLY",
                            _json_notes(
                                {
                                    "pattern_id": signal["pattern_id"],
                                    "confluence_score": signal["confluence_score"],
                                    "exchange_io": False,
                                }
                            ),
                        ],
                    )
                con.commit()
                counts["scanned"] += 1
                counts["signals"] += len(signals)
                details.append(
                    {
                        "symbol": symbol,
                        "bar_ts": bar_ts.isoformat(),
                        "status": status,
                        "n_signals": len(signals),
                    }
                )
            except Exception as exc:
                with suppress(duckdb.TransactionException):
                    con.rollback()
                counts["errors"] += 1
                details.append(
                    {
                        "symbol": symbol,
                        "status": "ERROR",
                        "error": f"{type(exc).__name__}: {exc}"[:300],
                    }
                )
    finally:
        con.close()

    return {
        "schema_version": "tf-signal-shadow-run-v1",
        "generated_at": now.isoformat(),
        "candidate_id": validated.candidate_id,
        "strategy": validated.strategy,
        "timeframe": validated.timeframe,
        "counts": counts,
        "details": details,
        "runtime_process_started": False,
        "exchange_io_performed": False,
        "order_path_enabled": False,
    }


def run_default_scan(
    *,
    repo_root: Path = REPO_ROOT,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Tick only queue-authorized active shadows; specs are safe no-ops.

    A generated config keeps ``auto_start=false`` permanently.  Scheduler
    execution is an explicit, separate queue capability requiring the exact
    ``SHADOW_ACTIVE_AUTHORIZED`` state plus a dated operator authorization.
    Merely placing a YAML file in ``configs/shadow`` can never tick it.
    """

    repo_root = Path(repo_root).resolve()
    scan_now = now or datetime.now(UTC)
    if scan_now.tzinfo is None:
        raise ShadowRunError("scheduler scan time must be timezone-aware")
    scan_now = scan_now.astimezone(UTC)
    results: list[dict[str, Any]] = []
    queue_path = repo_root / "memory" / "researcher" / "deploy_queue.json"
    rows: list[dict[str, Any]] = []
    if queue_path.is_file() and not queue_path.is_symlink():
        try:
            queue = json.loads(queue_path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            results.append(
                {
                    "status": "REJECTED",
                    "reason_code": "QUEUE",
                    "error": f"deploy queue is invalid JSON: {exc}"[:500],
                    "exchange_io_performed": False,
                    "order_path_enabled": False,
                }
            )
            queue = {}
        shadow = queue.get("tf_signal_shadow") if isinstance(queue, dict) else None
        if isinstance(shadow, dict) and isinstance(shadow.get("candidates"), list):
            rows = [row for row in shadow["candidates"] if isinstance(row, dict)]

    executed = 0
    for row in sorted(rows, key=lambda item: str(item.get("id", ""))):
        candidate_id = row.get("id")
        config_value = row.get("config")
        if row.get("status") != "SHADOW_ACTIVE_AUTHORIZED":
            results.append(
                {
                    "candidate_id": candidate_id,
                    "config": config_value,
                    "status": "SKIPPED_NOT_AUTHORIZED",
                    "queue_status": row.get("status"),
                    "exchange_io_performed": False,
                    "order_path_enabled": False,
                }
            )
            continue
        safety = row.get("safety")
        safety_valid = (
            isinstance(safety, dict)
            and safety.get("sim_only") is True
            and safety.get("signal_only") is True
            and safety.get("exchange_enabled") is False
            and safety.get("order_submit_allowed") is False
            and safety.get("auto_start") is False
            and safety.get("scheduler_tick_requires_queue_authorization") is True
        )
        if not safety_valid:
            results.append(
                {
                    "candidate_id": candidate_id,
                    "config": config_value,
                    "status": "REJECTED",
                    "reason_code": "AUTHORIZATION",
                    "error": "active queue row violates the signal-only safety policy",
                    "exchange_io_performed": False,
                    "order_path_enabled": False,
                }
            )
            continue
        try:
            path = _safe_repo_file(
                repo_root,
                config_value,
                field="deploy_queue.config",
                required_parent=Path("configs/shadow"),
            )
            validated = validate_shadow_config(path, repo_root=repo_root)
            expected_principal_policy = dict(validated.payload["principal_authorization"])
            expected_principal_policy.pop("state", None)
            if (
                validated.candidate_id != candidate_id
                or validated.strategy != row.get("strategy")
                or validated.timeframe != row.get("timeframe")
                or validated.payload.get("evidence", {}).get("artifact_sha256")
                != row.get("evidence_artifact_sha256")
                or _sha256_file(path) != row.get("config_sha256")
                or validated.payload.get("strategy_dependency_closure")
                != row.get("strategy_dependency_closure")
                or row.get("principal_authorization") != expected_principal_policy
            ):
                raise ShadowRunError("active queue identity differs from shadow config")
            authorization_path = _safe_repo_file(
                repo_root,
                expected_principal_policy["artifact"],
                field="deploy_queue.principal_authorization.artifact",
                required_parent=Path("memory/researcher/shadow_authorizations"),
            )
            verify_principal_authorization(
                validated,
                repo_root=repo_root,
                authorization_path=authorization_path,
                now=scan_now,
            )
            executed += 1
            try:
                results.append(
                    run_shadow_config(
                        path,
                        repo_root=repo_root,
                        now=scan_now,
                        authorization_path=authorization_path,
                    )
                )
            except Exception as exc:
                results.append(
                    {
                        "config": str(path.relative_to(repo_root)),
                        "status": "REJECTED",
                        "reason_code": "EXECUTION",
                        "error": f"{type(exc).__name__}: {exc}"[:500],
                        "exchange_io_performed": False,
                        "order_path_enabled": False,
                    }
                )
        except Exception as exc:
            results.append(
                {
                    "candidate_id": candidate_id,
                    "config": config_value,
                    "status": "REJECTED",
                    "reason_code": "AUTHORIZATION",
                    "error": f"{type(exc).__name__}: {exc}"[:500],
                    "exchange_io_performed": False,
                    "order_path_enabled": False,
                }
            )
    return {
        "schema_version": "tf-signal-shadow-scan-v1",
        "generated_at": scan_now.isoformat(),
        "configs_considered": len(rows),
        "configs_scanned": executed,
        "results": results,
        "runtime_process_started": False,
        "exchange_io_performed": False,
        "order_path_enabled": False,
    }
