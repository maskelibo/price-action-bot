"""Global settings and paths."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
DATA_DIR = REPO_ROOT / "data" / "forex"
PARQUET_DIR = DATA_DIR / "parquet"
DUCKDB_PATH = DATA_DIR / "forex.duckdb"
REPORTS_DIR = REPO_ROOT / "reports" / "forex"
LOGS_DIR = REPO_ROOT / "logs" / "forex"
CONFIGS_DIR = ROOT / "configs"

PAIRS = [
    "EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD",
    "NZDUSD", "USDCHF", "EURJPY", "GBPJPY", "EURGBP",
]

TIMEFRAMES = ["15m", "1m", "tick"]
PRIMARY_TF = "15m"
INTRABAR_TF = "1m"

for d in (DATA_DIR, PARQUET_DIR, REPORTS_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)
