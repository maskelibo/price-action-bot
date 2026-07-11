"""Run one local, permanent paper-only forex bar-close signal pass."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

# Keep this strict JSON status command free of unrelated logging side effects.
os.environ["PA_LOG_QUIET"] = "1"
os.environ["PA_DISABLE_FILE_LOG"] = "1"

from price_action.forex.paper_signal import (  # noqa: E402
    ForexPaperConfig,
    run_forex_signal_once,
)


def _parse_as_of(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--as-of must include an explicit timezone")
    return parsed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=ROOT / "configs" / "forex_paper_signal.yaml",
    )
    parser.add_argument(
        "--as-of",
        help="Deterministic UTC evaluation timestamp (ISO-8601); no stale bypass.",
    )
    args = parser.parse_args(argv)
    config = ForexPaperConfig.from_yaml(args.config, repo_root=ROOT)
    status = run_forex_signal_once(config, as_of=_parse_as_of(args.as_of))
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0 if status["verdict"] == "READY_LOCAL_PAPER" else 3


if __name__ == "__main__":
    raise SystemExit(main())
