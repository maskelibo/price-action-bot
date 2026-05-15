"""🔥 PHOENIX Futures Daemon — Binance Futures TESTNET.

Bot: PHOENIX (v2.0.4, wyckoff disabled — WYK-001 mitigation)
Empirik baseline: 13-pencere rolling ort +%200.3 / DD -%32.0 / r-adj 6.26

Konfigürasyon: configs/risk_phoenix_v204.yaml (10 strateji, wyckoff hariç)
Journal: data/futures_journal_phoenix.duckdb

GERÇEK testnet emirleri gönderir (gerçek para DEĞİL, testnet USDT).

Usage:
    python scripts/futures_daemon_phoenix.py            # daemon mode
    python scripts/futures_daemon_phoenix.py --once     # single pass test
"""
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

os.environ["PA_BOT_NAME"] = "phoenix"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

print("=" * 80)
print("🔥  PHOENIX FUTURES TESTNET DAEMON — v2.0.4 (wyckoff disabled)")
print("=" * 80)
print(f"Bot: PHOENIX")
print(f"Mode: Binance Futures TESTNET (gerçek emir, testnet USDT)")
print(f"Strategies: 10 (TOP_11 - wyckoff_phase_d)")
print(f"Risk config: configs/risk_phoenix_v204.yaml")
print(f"Journal: data/futures_journal_phoenix.duckdb")
print(f"Expected: yıllık +%200.3 / DD -%32.0 / r-adj 6.26 (13-pencere)")
print("=" * 80)
print()

# futures_daemon.py'i ENV ile çalıştır (subprocess yerine inline exec — env miras OK)
daemon_path = ROOT / "scripts" / "futures_daemon.py"
sys.argv = [str(daemon_path)] + sys.argv[1:]  # --once vs daemon argümanı geç
exec(compile(daemon_path.read_text(encoding="utf-8"), str(daemon_path), "exec"), {"__name__": "__main__", "__file__": str(daemon_path)})
