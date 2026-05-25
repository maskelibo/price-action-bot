"""SEC31g: Phoenix-Scalp 15m + r%3 + pyramid + TOP-4 strateji ablation.

Round 4 (Ablation BOMBA): analyst bulgu — 6 strateji negatif edge.
TOP-4 keep: vsa_climax_test (+0.586/n40k), brooks_failed_breakout (+0.195/n220k),
            engulfing_continuation (+0.091/n9k), anchored_vwap_reversal (+0.069/n104k)
6 DROP: fvg_fill_reversal (-0.285), equal_highs_sweep, obv_engulfing_confluence,
        brooks_h2_l2, cvd_spike_fade, pin_bar_round_numbers
Pool mean R: 0.076 → 0.200 (2.63×)
Lineer projeksiyon: yıllık %320, gerçekçi bant %200-280 (kompozisyon riski).

Output: reports/lab/sec31g_phoenix_scalp_15m_r3_top4_results.md
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
sec31.SCALP_RISK_YAML = ROOT / "configs" / "risk_phoenix_scalp_15m_pyramid_r3.yaml"
sec31.REPORT_OUT = ROOT / "reports" / "lab" / "sec31g_phoenix_scalp_15m_r3_top4_results.md"

# ABLATION: TOP-4 strateji only
sec31.PHOENIX_STRATEGIES = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),                  # +0.586 R, n=40k
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),     # +0.195 R, n=220k
    ("anchored_vwap_reversal", "AnchoredVWAPReversalStrategy"),     # +0.069 R, n=104k
    ("engulfing_continuation", "EngulfingContinuationStrategy"),    # +0.091 R, n=9k
]

if __name__ == "__main__": sec31.main()
