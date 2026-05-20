"""SEC41: 5m TOP-2 strateji (vsa+brooks_fb) — son test.

Phoenix DNA 10-strat aggregat -0.37 R. Researcher 2 hipotez (VWAP+CVD) RED.
AMA vsa_climax_test (15m'de mean R +0.586, pool yıldızı) 5m'de SOLO test edilmedi.
Eğer vsa edge'i timeframe-stable ise 5m'de de pozitif olabilir.

Output: reports/lab/sec41_phoenix_scalp_5m_top2_final_results.md
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

import scripts.sec32_phoenix_scalp_5m_rolling as sec32
sec32.REPORT_OUT = ROOT / "reports" / "lab" / "sec41_phoenix_scalp_5m_top2_final_results.md"
# 5m için manifest aktif (SEC-SCALP-S7) + TOP-2 (15m kazananları)
sec32.PHOENIX_STRATEGIES = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),        # 15m'de yıldız +0.586 R, 5m'de test edilmedi
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),  # 15m volume çıpası
]

if __name__ == "__main__": sec32.main()
