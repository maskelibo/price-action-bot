"""SEC31b: Phoenix-Scalp 15m + PYRAMID ON Retest.

GATE P4a default config FAIL geldi (yıllık +%7.4 / r-adj 0.304). 6mo preview'da
pyramid ON r-adj 6.4 (Phoenix 1d parity) vermişti. Bu varyant:
  - YAML: configs/risk_phoenix_scalp_15m_pyramid_on.yaml (pyramid_enabled: true)
  - Aynı 13-pencere walk-forward
  - Aynı 10 strateji × 10 sym

User direktifi 2026-05-17: scalper ek bağımsız bot olarak değerlendir;
Phoenix 1d production'da kalıyor. Scalper'ın kendi başına anlam üretmesi
gate'in.

Output: reports/lab/sec31b_phoenix_scalp_15m_pyramid_on_results.md
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

# Override SCALP_RISK_YAML before importing sec31 module
import scripts.sec31_phoenix_scalp_15m_rolling as sec31
sec31.SCALP_RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_on.yaml"
sec31.REPORT_OUT = ROOT / "reports" / "lab" / "sec31b_phoenix_scalp_15m_pyramid_on_results.md"

if __name__ == "__main__":
    sec31.main()
