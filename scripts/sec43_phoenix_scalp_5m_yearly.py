"""SEC43: 5m TOP-2 YIL-YIL backtest (non-overlapping).

User sordu: mean +%441 yıllık → her yıl mı %441 mi yoksa bir yıl %80 bir yıl
%1000 mi? Cevap için non-overlapping 1-yıllık pencereler:
  2021-05/2022-05, 2022-05/2023-05, 2023-05/2024-05, 2024-05/2025-05, 2025-05/2026-05

Mean değil, **per-year P&L stability** ölçeceğiz.

Output: reports/lab/sec43_phoenix_scalp_5m_yearly_results.md
"""
from __future__ import annotations
import io, os, sys
from pathlib import Path
if __name__ == "__main__":
    try: sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception: pass
os.environ["PA_LOG_QUIET"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "src"))

import scripts.sec31_phoenix_scalp_15m_rolling as sec31  # ana harness, TRAIN_DAYS burada
import scripts.sec32_phoenix_scalp_5m_rolling as sec32
# Hem sec31 hem sec32'de override (sec32 build_windows sec31'i çağırıyor)
sec31.TRAIN_DAYS = 365
sec31.OOS_DAYS = 0
sec31.STEP_DAYS = 365
sec32.TRAIN_DAYS = 365
sec32.OOS_DAYS = 0
sec32.STEP_DAYS = 365
sec32.TARGET_WINDOWS = 5
sec32.REPORT_OUT = ROOT / "reports" / "lab" / "sec43_phoenix_scalp_5m_yearly_results.md"
sec32.PHOENIX_STRATEGIES = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
]

if __name__ == "__main__": sec32.main()
