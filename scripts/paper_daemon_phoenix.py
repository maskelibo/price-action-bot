"""🔥 PHOENIX Paper Daemon — v2.0.4 (wyckoff disabled) paper trading.

Configurable env wrapper of paper_trade_daemon.py.
Bot adı: PHOENIX
Strategies: TOP_11 - wyckoff_phase_d (10 strategy + FVG = 11 - 1 = 10)
Journal: data/paper_journal_phoenix.duckdb
Risk config: configs/risk_phoenix_v204.yaml

Usage:
    python scripts/paper_daemon_phoenix.py            # daemon
    python scripts/paper_daemon_phoenix.py --once     # single-pass
"""
import os
import sys
from pathlib import Path

# Windows console encoding fix (Türkçe + emoji)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# Bot-spesifik environment ayarla
os.environ["PA_BOT_NAME"] = "phoenix"
os.environ["PA_RISK_CONFIG"] = str(Path(__file__).resolve().parents[1] / "configs" / "risk_phoenix_v204.yaml")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

print("=" * 80)
print("🔥  PHOENIX PAPER DAEMON — v2.0.4 (wyckoff DISABLED, WYK-001 mitigation)")
print("=" * 80)
print(f"Bot: PHOENIX")
print(f"Strategies: TOP_10 (wyckoff_phase_d disabled) + FVG = 10 strategy")
print(f"Journal: data/paper_journal_phoenix.duckdb")
print(f"Risk config: configs/risk_phoenix_v204.yaml")
print(f"Expected: yıllık +%200-300 (backtest), DD -%30-35, WR %69+")
print(f"Empirik baseline: 13-pencere rolling ort +%200.3 / DD -%32.0 / r-adj 6.26")
print("=" * 80)
print()

from scripts.paper_trade_daemon import run_signal_scan, run_position_monitor, equity_snapshot, main_loop  # noqa: E402
import argparse  # noqa: E402

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Bir kez çalış (test)")
    args = parser.parse_args()
    if args.once:
        run_signal_scan()
        run_position_monitor()
        equity_snapshot()
    else:
        main_loop()
