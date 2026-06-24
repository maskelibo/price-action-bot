"""SEC31j: Round 10 — TOP-4 + r%2 + pyramid (low risk DD reduction).

R4 (r%3) yıllık %234 / DD -%30. R10 hedefi: r%2 ile DD'yi -%20-25'e indir,
ROI %180-200 koru. Pareto frontier'in low-DD ucu.

Output: reports/lab/sec31j_phoenix_scalp_15m_top4_r2_results.md
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
sec31.SCALP_RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_top4_r2.yaml"
sec31.REPORT_OUT = ROOT / "reports" / "lab" / "sec31j_phoenix_scalp_15m_top4_r2_results.md"
sec31.PHOENIX_STRATEGIES = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
    ("anchored_vwap_reversal", "AnchoredVWAPReversalStrategy"),
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
]
if __name__ == "__main__": sec31.main()
