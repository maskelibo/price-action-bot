#!/usr/bin/env python3
"""CLI entry point for the frozen crypto 15-minute v17 pair program."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

os.environ.setdefault("PA_LOG_QUIET", "1")
os.environ.setdefault("PA_DISABLE_FILE_LOG", "1")

from price_action.lab.crypto_15m_pairs_program import main  # noqa: E402, I001


if __name__ == "__main__":
    raise SystemExit(main())
