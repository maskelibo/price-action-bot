"""SEC31h: Round 8 — R4 best (TOP-4 + r%3 + pyramid) + conf 0.35.

R4 baseline: yıllık +%234 / DD -%29.8 / r-adj 7.83 (PRIMARY GATE PASS).
Conf 0.35 lever: kalite üstü trade, mean R artar, DD düşer.
Hedef: DD'yi -%20-25'e indir, ROI ya kor ya artır.

Output: reports/lab/sec31h_phoenix_scalp_15m_r3_top4_conf035_results.md
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
sec31.SCALP_RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_r3_top4_conf035.yaml"
sec31.REPORT_OUT = ROOT / "reports" / "lab" / "sec31h_phoenix_scalp_15m_r3_top4_conf035_results.md"
sec31.PHOENIX_STRATEGIES = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
    ("anchored_vwap_reversal", "AnchoredVWAPReversalStrategy"),
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
]
if __name__ == "__main__": sec31.main()
