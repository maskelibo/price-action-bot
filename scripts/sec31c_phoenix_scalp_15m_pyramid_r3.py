"""SEC31c: Phoenix-Scalp 15m + PYRAMID ON + risk %3 (Round 2 iteration).

Round 1 sonucu (sec31b): pyramid_on + manifest + risk %2 →
  yıllık +%122.2 / DD -%31.3 / r-adj 3.909 / 34/34 pozitif pencere

User hedefi: yıllık %200'e yaklaşmak. Round 2 lever: risk_per_trade %2 → %3
(1d champion %4 ortasına git, fee/slip dengesi koru). Tahmin: yıllık ~%170-220,
DD ~%40-50 (DD agresifleşir, alt-gate -%25'i geçer ama ana hedef +%200'e daha yakın).

Output: reports/lab/sec31c_phoenix_scalp_15m_pyramid_r3_results.md
"""
from __future__ import annotations

import io
import os
import sys
from pathlib import Path

if __name__ == "__main__":
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

os.environ["PA_LOG_QUIET"] = "1"

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

import scripts.sec31_phoenix_scalp_15m_rolling as sec31
sec31.SCALP_RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"
sec31.REPORT_OUT = ROOT / "reports" / "lab" / "sec31c_phoenix_scalp_15m_pyramid_r3_results.md"

if __name__ == "__main__":
    sec31.main()
