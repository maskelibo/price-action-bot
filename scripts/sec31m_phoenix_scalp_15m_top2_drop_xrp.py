"""SEC31m: Round 13 — TOP-2 + drop XRP (compact pool).
R11 (TOP-2 + all 10 sym): %230 / -%30 / 7.69
Hedef: XRP drop ile DD'yi -%25-27'ye indir, ROI ±0.
Output: reports/lab/sec31m_phoenix_scalp_15m_top2_drop_xrp_results.md
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
sec31.REPORT_OUT = ROOT / "reports" / "lab" / "sec31m_phoenix_scalp_15m_top2_drop_xrp_results.md"
sec31.PHOENIX_STRATEGIES = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
]
sec31.SYMBOLS_10 = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT",
                    "ADA/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT", "DOGE/USDT"]
if __name__ == "__main__": sec31.main()
