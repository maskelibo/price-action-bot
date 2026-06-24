"""SEC31f: Phoenix-Scalp 15m + r%3 + tighter partial close (20/20/60 vs 40/30/30).

Round 7 lever: daha çok runner → tail-heavy distribution, pyramid amplifier.
Beklenen: yıllık ~%200-260 / DD ~%35-45 (DD biraz büyür ama tail kazanır).

Output: reports/lab/sec31f_phoenix_scalp_15m_r3_partial_results.md
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
sec31.SCALP_RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_r3_partial.yaml"
sec31.REPORT_OUT = ROOT / "reports" / "lab" / "sec31f_phoenix_scalp_15m_r3_partial_results.md"
if __name__ == "__main__": sec31.main()
