"""Canonical strategy worker executed only under macOS Seatbelt.

The parent sends one canonical JSON request on stdin.  The worker imports the
pinned strategy closure, performs feature/signal evaluation, and emits exactly
one canonical JSON response.  It has no journal, market database, credential,
network, or order interface.
"""

from __future__ import annotations

import contextlib
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

REQUEST_SCHEMA = "tf-signal-shadow-worker-request-v1"
RESPONSE_SCHEMA = "tf-signal-shadow-worker-response-v1"
_MAX_STDIN_BYTES = 32 * 1024 * 1024


def _canonical(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()


def _fail(message: str) -> int:
    sys.stderr.write(message[:1000] + "\n")
    return 2


def main() -> int:
    os.environ["PA_ENGULF_NUMBA"] = "0"
    os.environ["NUMBA_DISABLE_JIT"] = "1"
    sys.dont_write_bytecode = True
    raw = sys.stdin.buffer.read(_MAX_STDIN_BYTES + 1)
    if not raw or len(raw) > _MAX_STDIN_BYTES:
        return _fail("worker request is empty or exceeds the byte cap")
    try:
        request = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return _fail(f"worker request is invalid JSON: {exc}")
    if not isinstance(request, dict) or raw != _canonical(request):
        return _fail("worker request is not canonical JSON")
    if request.get("schema_version") != REQUEST_SCHEMA:
        return _fail("worker request schema mismatch")
    strategy = request.get("strategy")
    timeframe = request.get("timeframe")
    class_name = request.get("class_name")
    bars = request.get("bars")
    if not all(isinstance(value, str) and value for value in (strategy, timeframe, class_name)):
        return _fail("worker request identity is invalid")
    if not isinstance(bars, list) or not bars or len(bars) > 5000:
        return _fail("worker bars must be a non-empty capped list")

    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "src"))
    try:
        with contextlib.redirect_stdout(sys.stderr):
            import pandas as pd

            from price_action.contracts import Signal

            module = importlib.import_module(f"price_action.strategies.{strategy}")
            for flag in (
                "_VSA_NUMBA_AVAILABLE",
                "_BROOKS_NUMBA_AVAILABLE",
                "_AVWAP_NUMBA_AVAILABLE",
                "_ENGULF_NUMBA_AVAILABLE",
            ):
                if hasattr(module, flag):
                    setattr(module, flag, False)
            strategy_class = getattr(module, class_name)
            manifest_factory = getattr(module, "_default_manifest", None)
            if callable(manifest_factory):
                manifest = manifest_factory()
            else:
                from price_action.strategies.base import StrategyManifest

                manifest = StrategyManifest(name=strategy, version="signal-shadow")
            instance = strategy_class(manifest)
            frame = pd.DataFrame(bars)
            frame["ts"] = pd.to_datetime(frame["ts"], utc=True, errors="raise")
            for column in ("open", "high", "low", "close", "volume"):
                frame[column] = pd.to_numeric(frame[column], errors="raise")
            featured = instance.prepare_features(frame)
            generated = list(instance.generate_signals(featured))
            if any(type(signal) is not Signal for signal in generated):
                return _fail("strategy returned a non-canonical Signal object")
            response_signals = [
                {
                    "confluence_score": float(signal.confluence_score),
                    "direction": str(signal.direction),
                    "fingerprint": signal.fingerprint(),
                    "pattern_id": str(signal.pattern_id),
                    "sl_price": float(signal.sl_price),
                    "tp_price": float(signal.tp_price),
                    "ts": pd.Timestamp(signal.ts).isoformat(),
                }
                for signal in generated
            ]
    except Exception as exc:
        return _fail(f"worker strategy evaluation failed: {type(exc).__name__}: {exc}")
    sys.stdout.buffer.write(
        _canonical(
            {
                "schema_version": RESPONSE_SCHEMA,
                "signals": response_signals,
                "status": "OK",
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
