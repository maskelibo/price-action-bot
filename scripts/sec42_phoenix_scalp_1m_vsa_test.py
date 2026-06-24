"""SEC42: 1m TF — vsa_climax_test solo test.

5m TOP-2 (vsa + brooks_fb) yıllık +%511 / r-adj 13.08 verdi. vsa_climax_test
15m'de mean R +0.586, 5m'de +0.27. Acaba 1m'de de pozitif mi?

NOT: 1m fizik bariyer (fill %22.6, fee 5× yetersiz) zaten dokümante.
Bu test sadece "edge timeframe-stability" verisi için — eğer pozitif R çıkarsa
bot ARCHITECTURALLY 1m'de de "çalışabilir" (user hedefinin literal anlamı:
çalışabilen scalper bot — fizik bariyer profitable deployment'i engellese de).

Mevcut 1m data: BTC × 6mo (sample). Diğer sym yok (1m KILL kararı sonrası
full ingest yapılmadı). Bu yüzden BTC solo + 6mo single-window.

Output: reports/lab/sec42_phoenix_scalp_1m_vsa_test_results.md
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

import scripts.sec33_phoenix_scalp_1m_rolling as sec33
sec33.REPORT_OUT = ROOT / "reports" / "lab" / "sec42_phoenix_scalp_1m_vsa_test_results.md"
sec33.PHOENIX_STRATEGIES = [
    ("vsa_climax_test", "VSAClimaxTestStrategy"),  # 15m yıldız (+0.586), 5m pozitif (+0.27)
]
sec33.SYMBOLS_10 = ["BTC/USDT"]  # sadece BTC × 1m mevcut

if __name__ == "__main__": sec33.main()
