"""SEC27 ek analiz: r-adj odaklı paired bootstrap.

Ana sprint yıllık-delta CI'sini kullandı (pre-reg disiplini).
Ama tablo gösterdi ki V1/V3 r-adj +0.947/+1.161 daha yüksek (DD iyileşmesi başat).
Bu ek analiz: per-window r-adj delta CI95 ve p-value.

Yan-bulgu kategorisi: pre-reg sınırı dışı, "secondary metric exploration".
"""
from __future__ import annotations
import sys
import json
from pathlib import Path
import random

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

# JSON dump'tan oku (sec27 ana script çıktısı)
data = json.loads((ROOT / "reports" / "researcher" / "sec27_data.json").read_text(encoding="utf-8"))

# Yeniden hesapla — variant ham sonuçları ana script çıktısında değil
# Aslında ana script'i tekrar çalıştırmadan, JSON'dan per-window metric'leri yeniden çıkar:
# Ana script all_results dict'i kaydetmedi, yeniden run gerek.
# Bu script standalone değil — sec27_alt_coin_subportfolio.py'a ek pass yapalım.

print("Bu script all_results dump gerektirir. Ana sprint script'i guncelliyoruz.")
