"""Shared synthetic canonical TF OOS trust-chain fixture for focused tests."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from price_action.lab.tf_independent_oos import (
    build_pool_from_replay,
    create_preregistration,
    evaluate_preregistration,
    record_pool_provenance,
)

CREATED_AT = datetime(2024, 1, 10, tzinfo=UTC)
OOS_START = datetime(2024, 1, 11, tzinfo=UTC)
AS_OF = datetime(2025, 1, 20, tzinfo=UTC)


@dataclass(frozen=True)
class CanonicalTFRepo:
    root: Path
    evidence: Path
    evidence_dir: Path
    preregistration: Path
    candidate_pool: Path
    baseline_pool: Path
    variant_pools: tuple[Path, ...]
    raw_ohlcv: Path
    principal_private_key: Any


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(payload: dict) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def write_principal_authorization(
    fixture: CanonicalTFRepo,
    *,
    config_path: Path,
    issued_at: datetime,
    expires_at: datetime,
    nonce: str = "ab" * 32,
    candidate_id: str | None = None,
    config_sha256: str | None = None,
    evidence_sha256: str | None = None,
) -> Path:
    config = yaml.safe_load(Path(config_path).read_text(encoding="utf-8"))
    unsigned = {
        "candidate_id": candidate_id or config["candidate_id"],
        "config_sha256": config_sha256 or _sha(Path(config_path)),
        "decision": "AUTHORIZE_SIGNAL_SHADOW_TICK",
        "evidence_sha256": evidence_sha256 or config["evidence"]["artifact_sha256"],
        "expires_at": expires_at.isoformat(),
        "issued_at": issued_at.isoformat(),
        "nonce": nonce,
        "schema_version": "tf-shadow-principal-authorization-v1",
        "scope": "SIGNAL_ONLY_SHADOW",
    }
    signature = fixture.principal_private_key.sign(_canonical(unsigned))
    payload = {**unsigned, "signature": __import__("base64").b64encode(signature).decode("ascii")}
    path = fixture.root / config["principal_authorization"]["artifact"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical(payload))
    return path


def _row(
    strategy: str,
    timestamp: datetime,
    *,
    symbol: str,
    r_value: float,
    regime: str,
) -> dict:
    return {
        "entry_ts": timestamp,
        "exit_ts": timestamp + timedelta(hours=1),
        "R": r_value,
        "symbol": symbol,
        "strategy": strategy,
        "side": "long",
        "regime": regime,
    }


def _selection_rows(strategy: str, r_value: float) -> list[dict]:
    return [
        _row(
            strategy,
            datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index),
            symbol=f"SYM{index}",
            r_value=r_value,
            regime="trend" if index % 2 else "range",
        )
        for index in range(5)
    ]


def _future_rows(strategy: str, r_value: float) -> list[dict]:
    rows: list[dict] = []
    for day in range(365):
        timestamp = OOS_START + timedelta(days=day, hours=1)
        for symbol_index in range(5):
            rows.append(
                _row(
                    strategy,
                    timestamp + timedelta(minutes=symbol_index),
                    symbol=f"SYM{symbol_index}",
                    r_value=r_value,
                    regime="trend" if day % 2 else "range",
                )
            )
    return rows


_BUILDER_SOURCE = r'''#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import pickle
from datetime import datetime, timedelta
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--tf-oos-replay-v1", action="store_true", required=True)
parser.add_argument("--raw-snapshot", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
parser.add_argument("--strategy", required=True)
parser.add_argument("--timeframe", required=True)
parser.add_argument("--parameters-json", required=True)
args = parser.parse_args()
parameters = json.loads(args.parameters_json)
threshold = float(parameters["threshold"])
rows = []
for line in args.raw_snapshot.read_text(encoding="utf-8").splitlines():
    item = json.loads(line)
    if args.timeframe == "15m":
        r_value = float(item["baseline_r"])
    elif threshold < 1.0:
        r_value = float(item["variant_low_r"])
    elif threshold > 1.0:
        r_value = float(item["variant_high_r"])
    else:
        r_value = float(item["candidate_r"])
    entry = datetime.fromisoformat(item["entry_ts"].replace("Z", "+00:00"))
    rows.append({
        "entry_ts": entry,
        "exit_ts": entry + timedelta(hours=1),
        "R": r_value,
        "symbol": item["symbol"],
        "strategy": args.strategy,
        "side": "long",
        "regime": item["regime"],
    })
rows.sort(key=lambda row: (row["entry_ts"], row["symbol"], row["strategy"]))
raw = pickle.dumps(rows, protocol=4)
args.output.write_bytes(raw)
receipt = {
    "contract": "TF_POOL_BUILDER_REPLAY_V1",
    "output_sha256": hashlib.sha256(raw).hexdigest(),
    "status": "OK",
}
print(json.dumps(receipt, indent=2, sort_keys=True, ensure_ascii=False))
'''


def _raw_row(timestamp: datetime, symbol: str, regime: str, *, phase: str) -> dict:
    return {
        "candidate_r": 0.25 if phase == "selection" else 0.30,
        "baseline_r": 0.05,
        "entry_ts": timestamp.isoformat(),
        "regime": regime,
        "symbol": symbol,
        "variant_high_r": 0.18,
        "variant_low_r": 0.22,
    }


def _append_raw(path: Path, rows: list[dict]) -> None:
    with path.open("ab") as handle:
        for row in rows:
            handle.write(
                (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode()
            )


def _build_pool(root: Path, strategy: str, path: Path) -> None:
    _logical_id, role, parameters, _variant_of, _delta = _identity(path)
    build_pool_from_replay(
        output_path=path,
        raw_ohlcv_path=root / "data/raw_ohlcv.jsonl",
        builder_path=root / "scripts/synthetic_pool_builder.py",
        repo_root=root,
        strategy=strategy,
        timeframe="15m" if role == "baseline" else "30m",
        parameters=parameters,
    )


def _identity(path: Path) -> tuple[str, str, dict, str | None, dict]:
    if "candidate" in path.name:
        return "edge-30m-primary", "candidate", {"risk": 1.0, "threshold": 1.0}, None, {}
    if "baseline" in path.name:
        return "edge-15m-baseline", "baseline", {"risk": 1.0, "threshold": 1.0}, None, {}
    value = 0.9 if "variant-1" in path.name else 1.1
    return (
        f"edge-30m-threshold-{str(value).replace('.', '-')}",
        "variant",
        {"risk": 1.0, "threshold": value},
        "edge-30m-primary",
        {"threshold": {"from": 1.0, "to": value}},
    )


def _attest(root: Path, strategy: str, path: Path, generated_at: datetime) -> None:
    logical_id, role, parameters, variant_of, delta = _identity(path)
    record_pool_provenance(
        pool_path=path,
        raw_ohlcv_path=root / "data/raw_ohlcv.jsonl",
        builder_path=root / "scripts/synthetic_pool_builder.py",
        repo_root=root,
        strategy=strategy,
        timeframe="15m" if role == "baseline" else "30m",
        logical_id=logical_id,
        parameter_family="edge-parameters",
        parameter_role=role,
        parameters=parameters,
        variant_of=variant_of,
        declared_delta=delta,
        generated_at=generated_at,
    )


def make_canonical_tf_repo(
    tmp_path: Path,
    *,
    strategy: str = "engulfing_continuation",
    strategy_source: str,
    as_of: datetime = AS_OF,
) -> CanonicalTFRepo:
    root = tmp_path / "repo"
    module = root / f"src/price_action/strategies/{strategy}.py"
    module.parent.mkdir(parents=True)
    module.write_text(strategy_source, encoding="utf-8")
    source_root = Path(__file__).resolve().parents[1]
    for relative in (
        "src/price_action/__init__.py",
        "src/price_action/contracts.py",
        "src/price_action/logging_config.py",
        "src/price_action/runtime_paths.py",
        "src/price_action/settings.py",
        "src/price_action/strategies/__init__.py",
        "src/price_action/strategies/base.py",
        "src/price_action/strategies/classic_pa.py",
        "src/price_action/strategies/manifest_loader.py",
        "src/price_action/lab/tf_signal_shadow_worker.py",
    ):
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((source_root / relative).read_bytes())
    evaluator_module = root / "src/price_action/lab/tf_independent_oos.py"
    evaluator_module.parent.mkdir(parents=True, exist_ok=True)
    evaluator_module.write_text("# pinned canonical evaluator module fixture\n", encoding="utf-8")
    wrapper = root / "scripts/tf_independent_oos_runner.py"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("# pinned canonical evaluator wrapper fixture\n", encoding="utf-8")
    builder = root / "scripts/synthetic_pool_builder.py"
    builder.write_text(_BUILDER_SOURCE, encoding="utf-8")
    protocol = root / "configs/tf_oos_protocol.yaml"
    protocol.parent.mkdir(parents=True)
    protocol_payload = yaml.safe_load(
        (source_root / "configs/tf_oos_protocol.yaml").read_text(encoding="utf-8")
    )
    principal_private_key = Ed25519PrivateKey.generate()
    public_key_raw = principal_private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    public_key = root / "configs/keys/tf_shadow_principal_ed25519.pub"
    public_key.parent.mkdir(parents=True)
    public_key.write_bytes(public_key_raw)
    protocol_payload["authorization"]["principal_authorization"]["public_key_sha256"] = (
        hashlib.sha256(public_key_raw).hexdigest()
    )
    protocol.write_text(yaml.safe_dump(protocol_payload, sort_keys=False), encoding="utf-8")
    raw = root / "data/raw_ohlcv.jsonl"
    raw.parent.mkdir(parents=True)
    raw.write_bytes(b"")
    _append_raw(
        raw,
        [
            _raw_row(
                datetime(2024, 1, 1, tzinfo=UTC) + timedelta(days=index),
                f"SYM{index}",
                "trend" if index % 2 else "range",
                phase="selection",
            )
            for index in range(5)
        ],
    )

    candidate = root / "data/edge_30m_candidate_pool.pkl"
    baseline = root / "data/edge_15m_baseline_pool.pkl"
    variants = (
        root / "data/edge_30m_variant-1_pool.pkl",
        root / "data/edge_30m_variant-2_pool.pkl",
    )
    pool_paths = (candidate, baseline, *variants)
    for path in pool_paths:
        _build_pool(root, strategy, path)
        _attest(root, strategy, path, datetime(2024, 1, 6, 1, tzinfo=UTC))

    discovery = {
        "schema_version": "tf-robustness-v2",
        "generated_at": "2024-01-06T00:00:00+00:00",
        "verdict": "DESCRIPTIVE_SCREEN_PASS",
        "evidence_class": "DESCRIPTIVE_REUSED_HISTORY",
        "independent_oos": False,
        "deployment_authorized": False,
        "strategy": strategy,
        "inputs": {
            "candidate_tf": "30m",
            "baseline_tf": "15m",
            "candidate_pool": {"path": str(candidate), "sha256": _sha(candidate)},
            "baseline_pool": {"path": str(baseline), "sha256": _sha(baseline)},
        },
        "data_quality": {"valid": True, "errors": []},
        "gates": [{"name": "descriptive", "passed": True}],
        "failed_gates": [],
    }
    discovery_path = root / "reports/tf_discovery/discovery.json"
    discovery_path.parent.mkdir(parents=True)
    discovery_path.write_text(json.dumps(discovery, sort_keys=True) + "\n", encoding="utf-8")
    _, preregistration = create_preregistration(
        discovery_path=discovery_path,
        repo_root=root,
        output_dir=root / "reports/tf_oos/prereg",
        candidate_pool=candidate,
        baseline_pool=baseline,
        variant_pools=variants,
        created_at=CREATED_AT,
        oos_start=OOS_START,
    )

    future_raw = []
    for day in range(365):
        timestamp = OOS_START + timedelta(days=day, hours=1)
        for symbol_index in range(5):
            future_raw.append(
                _raw_row(
                    timestamp + timedelta(minutes=symbol_index),
                    f"SYM{symbol_index}",
                    "trend" if day % 2 else "range",
                    phase="future",
                )
            )
    _append_raw(raw, future_raw)
    for path in pool_paths:
        _build_pool(root, strategy, path)
        _attest(root, strategy, path, as_of - timedelta(days=1))

    evidence_dir = root / "reports/tf_robustness"
    _, evidence = evaluate_preregistration(
        preregistration_path=preregistration,
        repo_root=root,
        evidence_dir=evidence_dir,
        status_dir=root / "reports/tf_oos/status",
        as_of=as_of,
    )
    queue = root / "memory/researcher/deploy_queue.json"
    queue.parent.mkdir(parents=True)
    queue.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "status": "SUPERSEDED",
                "candidates": [{"id": "legacy", "status": "SUPERSEDED"}],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return CanonicalTFRepo(
        root=root,
        evidence=evidence,
        evidence_dir=evidence_dir,
        preregistration=preregistration,
        candidate_pool=candidate,
        baseline_pool=baseline,
        variant_pools=variants,
        raw_ohlcv=raw,
        principal_private_key=principal_private_key,
    )
