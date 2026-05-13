"""ML hatti archive — Sec3.1 (HYP-2026-05-15 + HYP-2026-05-16 + HYP-2026-05-17 RED ise).

Tasinacak:
  scripts/ml_meta_labeling_baseline.py        -> archive/ml_attempts/
  scripts/ml_meta_labeling_walkforward.py     -> archive/ml_attempts/
  scripts/ml_meta_labeling_robustness.py      -> archive/ml_attempts/
  scripts/regime_conditional_ml_walkforward.py -> archive/ml_attempts/
  scripts/w3_regime_forensics.py              -> archive/ml_attempts/
  scripts/ml_meta_v2_walkforward.py           -> archive/ml_attempts/
  scripts/v095_ml_trade_scoring.py            -> archive/ml_attempts/
  scripts/build_mtf_cache.py                  -> archive/ml_attempts/

src/price_action/ml/* KORUNUR (mevcut prod kullanmiyor ama ileride lazim olabilir).
data/mtf_*.pkl + data/v095_*.pkl KORUNUR.
reports/research/ml_meta_*.txt + .json KORUNUR.
memory/researcher/hypotheses/2026-05-1[5-7]-* KORUNUR (geçmiş hipotez kayidi).

Cikti: archive/ml_attempts/README.md (ne neden archive edildi)

NOT: Sadece ML hattini sonlandirmaya karar verince calistirilir.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_DIR = ROOT / "archive" / "ml_attempts"

SCRIPTS_TO_ARCHIVE = [
    "scripts/ml_meta_labeling_baseline.py",
    "scripts/ml_meta_labeling_walkforward.py",
    "scripts/ml_meta_labeling_robustness.py",
    "scripts/regime_conditional_ml_walkforward.py",
    "scripts/w3_regime_forensics.py",
    "scripts/ml_meta_v2_walkforward.py",
    "scripts/v095_ml_trade_scoring.py",
    "scripts/build_mtf_cache.py",
]

README_TEXT = """# ML Hatti Archive (2026-05-17)

Bu klasor 3 sprint zincirini takip eden ML meta-labeling denemelerinin scriptlerini icerir.

## Kapanis Kararı

3 sprint zincir kanit:
1. **HYP-2026-05-15-001 (ML v1)**: RF + 13 feature + thr=0.55 → RED (CV AUC 0.527, overfit gap +0.23)
2. **HYP-2026-05-16-001 (Regime-conditional)**: BTC period_return median mask → RED-borderline (3/4 PASS, random null p=0.0500 marjinal)
3. **HYP-2026-05-17-001 (Feature space v2)**: + 5 feature (4h/1h/funding/fng) → [VERDICT BURAYA]

Yapısal sonuc: 4787 trade pool + mevcut feature seti + RF/regime-mask/MTF-altdata
kombinasyonlarinin hicbiri yıllık %36 BALANCED+F&G uzerine anlamli alpha
katmiyor. Trade-level filter edge yok bu setup'ta.

## Korunan Bilesenler

- `src/price_action/ml/*` (meta_labeling.py, features.py, features_v2.py, inference.py, train_filter.py)
  → ileride yeni feature/regime denemeleri icin kullanilabilir
- `data/v095_*.pkl, data/mtf_*.pkl` → trade pool + MTF cache
- `data/alt_data/funding_*.csv, fng_daily.csv` → alt-data
- `reports/research/ml_meta_*.txt` + `.json` → tum sonuclar (analytics icin)
- `memory/researcher/hypotheses/2026-05-1[5-7]-*` → pre-reg hipotezler ve postmortemler

## Yeni Sprint Yolu

ML hatti yerine:
1. **Lab W3 tournament** — Champion (BALANCED+F&G) confirm
2. **Yeni strateji sınıfı arama** — futures basis, mean-reversion, vol overlay
3. **Mevcut stratejilerin fine-tuning** — parametre optimizasyonu

## Retrieval

Eger ileride ML denemesi tekrar gerekirse:
```
git mv archive/ml_attempts/ml_meta_v2_walkforward.py scripts/
```
veya benzer.
"""


def main() -> None:
    if not ARCHIVE_DIR.exists():
        print(f"Creating {ARCHIVE_DIR}")
        ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

    moved = []
    skipped = []
    for rel_path in SCRIPTS_TO_ARCHIVE:
        src = ROOT / rel_path
        if not src.exists():
            skipped.append(rel_path)
            continue
        dst = ARCHIVE_DIR / Path(rel_path).name
        print(f"  mv {rel_path} -> {dst.relative_to(ROOT)}")
        shutil.move(str(src), str(dst))
        moved.append(rel_path)

    readme_path = ARCHIVE_DIR / "README.md"
    readme_path.write_text(README_TEXT, encoding="utf-8")
    print(f"  README: {readme_path.relative_to(ROOT)}")

    print(f"\nMoved: {len(moved)}")
    print(f"Skipped (not found): {len(skipped)}")
    for s in skipped:
        print(f"  - {s}")


if __name__ == "__main__":
    main()
