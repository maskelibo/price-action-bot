"""SEC31e: Phoenix-Scalp 15m + r%3 + signal_confidence_min 0.25→0.35.

Round 6 lever: kalite üstü trade (conf 0.35) → daha az ama daha iyi sinyal.
Beklenen: yıllık ~%150-180 / DD ~%22-28 (DD düşer + ROI biraz düşer ama r-adj artar).

Output: reports/lab/sec31e_phoenix_scalp_15m_r3_conf035_results.md
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
import scripts.sec31_phoenix_scalp_15m_rolling as sec31
sec31.SCALP_RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_r3_conf035.yaml"
sec31.REPORT_OUT = ROOT / "reports" / "lab" / "sec31e_phoenix_scalp_15m_r3_conf035_results.md"
if __name__ == "__main__": sec31.main()
