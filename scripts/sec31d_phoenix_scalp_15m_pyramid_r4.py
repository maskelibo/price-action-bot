"""SEC31d: Phoenix-Scalp 15m + PYRAMID + risk %4 (Round 3, champion seviyesi).

User hedefi: yıllık %200. Risk %2→%122, %3→?, %4→? (lineer extrapolasyon ~%240).
1d champion %4 risk_per_trade ile +%200 üretiyordu — aynı risk seviyesinde 15m'in
relatif edge'i (mean R 0.04 vs 1d 0.32) fee/slip'le boğuluyor, pyramid amplifier.

Output: reports/lab/sec31d_phoenix_scalp_15m_pyramid_r4_results.md
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
sec31.SCALP_RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r4.yaml"
sec31.REPORT_OUT = ROOT / "reports" / "lab" / "sec31d_phoenix_scalp_15m_pyramid_r4_results.md"

if __name__ == "__main__":
    sec31.main()
