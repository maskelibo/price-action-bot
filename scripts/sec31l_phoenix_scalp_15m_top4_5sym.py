"""SEC31l: Round 12 — TOP-4 strateji + TOP-5 sym (highest mean R).

Analyst Top-5 sym: AVAX (+0.150), LINK (+0.143), DOT (+0.117), SOL (+0.112), ADA (+0.076).
Drop: BTC (+0.021), ETH (+0.039), BNB, DOGE, XRP.

Concentration on edge — daha az çeşitlilik ama daha yüksek pool R.
Hedef: yıllık %250+ / DD -%25.

Output: reports/lab/sec31l_phoenix_scalp_15m_top4_5sym_results.md
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
sec31.REPORT_OUT = ROOT / "reports" / "lab" / "sec31l_phoenix_scalp_15m_top4_5sym_results.md"
sec31.PHOENIX_STRATEGIES = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
    ("anchored_vwap_reversal", "AnchoredVWAPReversalStrategy"),
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
]
sec31.SYMBOLS_10 = ["AVAX/USDT", "LINK/USDT", "DOT/USDT", "SOL/USDT", "ADA/USDT"]
if __name__ == "__main__": sec31.main()
