"""🏛️ ATLAS Futures Daemon — Binance Futures TESTNET.

Bot: ATLAS (v2.0.3 baseline — wyckoff dahil control variant)
Empirik baseline: 13-pencere rolling ort +%134.3 / DD -%42.5 / r-adj 3.16

⚠️ NOT: Tek testnet hesabında PHOENIX ile paralel çalıştırma DOĞRU DEĞİL
(pozisyon attribution karışır). 2. testnet hesabı açtıktan sonra deploy et.

Usage:
    python scripts/futures_daemon_atlas.py            # daemon mode
    python scripts/futures_daemon_atlas.py --once     # single pass test
"""
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

os.environ["PA_BOT_NAME"] = "atlas"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

print("=" * 80)
print("🏛️  ATLAS FUTURES TESTNET DAEMON — v2.0.3 (wyckoff dahil, baseline)")
print("=" * 80)
print(f"Bot: ATLAS")
print(f"Mode: Binance Futures TESTNET")
print(f"Strategies: 11 (TOP_11 full)")
print(f"Risk config: configs/risk_atlas_v203.yaml")
print(f"Journal: data/futures_journal_atlas.duckdb")
print(f"Expected: yıllık +%134.3 / DD -%42.5 (memory baseline +%239.5)")
print("=" * 80)
print()

daemon_path = ROOT / "scripts" / "futures_daemon.py"
sys.argv = [str(daemon_path)] + sys.argv[1:]
exec(compile(daemon_path.read_text(encoding="utf-8"), str(daemon_path), "exec"), {"__name__": "__main__", "__file__": str(daemon_path)})
