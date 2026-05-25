"""SEC31k: Round 11 — TOP-2 strategy only (vsa + brooks_fb).

Analyst: en güçlü 2 strateji = vsa_climax_test (+0.586 R, n=40k) + brooks_failed_breakout
(+0.195 R, n=220k). Toplam n=260k. Pool mean R ~+0.30 lineer projeksiyon.

Hedef: daha az noise = daha düşük DD. ROI belki de daha yüksek (concentration on edge).

Output: reports/lab/sec31k_phoenix_scalp_15m_top2_results.md
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
sec31.REPORT_OUT = ROOT / "reports" / "lab" / "sec31k_phoenix_scalp_15m_top2_results.md"
sec31.PHOENIX_STRATEGIES = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
]
if __name__ == "__main__": sec31.main()
