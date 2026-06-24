"""SEC31n: Round 14 — TOP-2 + TOP-5 sym (max edge concentration).

Strategies: vsa_climax_test + brooks_failed_breakout (en güçlü 2)
Symbols: AVAX, LINK, DOT, SOL, ADA (en yüksek pool R)

Beklenti: yıllık %240+, DD ~-%25 (concentration on best edges).

Output: reports/lab/sec31n_phoenix_scalp_15m_top2_5sym_results.md
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
sec31.REPORT_OUT = ROOT / "reports" / "lab" / "sec31n_phoenix_scalp_15m_top2_5sym_results.md"
sec31.PHOENIX_STRATEGIES = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),
    ("brooks_failed_breakout", "BrooksFailedBreakoutStrategy"),
]
sec31.SYMBOLS_10 = ["AVAX/USDT", "LINK/USDT", "DOT/USDT", "SOL/USDT", "ADA/USDT"]
if __name__ == "__main__": sec31.main()
