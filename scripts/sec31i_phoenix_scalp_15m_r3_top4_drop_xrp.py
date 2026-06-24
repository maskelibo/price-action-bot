"""SEC31i: Round 9 — R4 best + symbol drop XRP (analyst: tek negatif sym).

XRP mean R -0.017 (tek negatif). Drop ile pool mR +0.0867 (marjinal +%13).
Hedef: ROI ±0, DD biraz düşer (XRP noise temizlenir).

Output: reports/lab/sec31i_phoenix_scalp_15m_r3_top4_drop_xrp_results.md
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
sec31.REPORT_OUT = ROOT / "reports" / "lab" / "sec31i_phoenix_scalp_15m_r3_top4_drop_xrp_results.md"
sec31.PHOENIX_STRATEGIES = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
    ("anchored_vwap_reversal", "AnchoredVWAPReversalStrategy"),
    ("engulfing_continuation", "EngulfingContinuationStrategy"),
]
sec31.SYMBOLS_10 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
                    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT",
                    "DOGE/USDT"]  # 10 → 9 (XRP drop)
if __name__ == "__main__": sec31.main()
