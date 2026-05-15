"""🏛️ ATLAS Paper Daemon — v2.0.3 baseline (wyckoff dahil) paper trading.

Configurable env wrapper of paper_trade_daemon.py.
Bot adı: ATLAS
Strategies: TOP_11 (wyckoff_phase_d dahil — 11 strategy + FVG)
Journal: data/paper_journal_atlas.duckdb
Risk config: configs/risk_atlas_v203.yaml

Usage:
    python scripts/paper_daemon_atlas.py            # daemon
    python scripts/paper_daemon_atlas.py --once     # single-pass
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
os.environ["PA_BOT_NAME"] = "atlas"
os.environ["PA_RISK_CONFIG"] = str(Path(__file__).resolve().parents[1] / "configs" / "risk_atlas_v203.yaml")

# Original daemon'u import et ve çalıştır
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

print("=" * 80)
print("🏛️  ATLAS PAPER DAEMON — v2.0.3 baseline (wyckoff dahil)")
print("=" * 80)
print(f"Bot: ATLAS")
print(f"Strategies: TOP_11 (engulfing, obv, vwap, wyckoff, brooks, pin_bar, eq_highs, cvd, vsa, brooks_fb, fvg)")
print(f"Journal: data/paper_journal_atlas.duckdb")
print(f"Risk config: configs/risk_atlas_v203.yaml")
print(f"Expected: yıllık +%134-239 (backtest), DD -%32-42")
print("=" * 80)
print()

# paper_trade_daemon main'i çağır
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
