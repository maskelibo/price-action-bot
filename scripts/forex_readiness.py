#!/usr/bin/env python3
"""Read-only CLI for the permanent-paper Forex readiness gate."""

import os

# The lab package's legacy __init__ imports logging configuration.  Suppress its
# stdout/file sinks before that import so this inspector emits one strict JSON
# document and does not mutate operational logs.
os.environ["PA_LOG_QUIET"] = "1"
os.environ["PA_DISABLE_FILE_LOG"] = "1"

from price_action.lab.forex_readiness import cli_main

if __name__ == "__main__":
    raise SystemExit(cli_main())
