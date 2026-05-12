"""BTC Dominance ingest CLI — CEO brief 2026-05-12 (sec 4.4) gerekliligi.

EER-Score ve Researcher B HYP-2026-05-12-regime-btc-dominance-trend-veto icin
gerekli BTC.D verisini CoinGecko free API'sinden ceker.

Mevcut modul: src/price_action/data/dominance_ingest.py (DominanceStore +
fetch_btc_dominance_history). Bu CLI sadece sarmal — calistirilirsa
data/dominance.duckdb dosyasi olusturur.

Calistirma:
    # Online (5-15 dakika, rate-limit'e gore):
    python scripts/ingest_btc_dominance.py

    # Mock (offline, test amacli — ONAYSIZ prod'a baglanmasin):
    python scripts/ingest_btc_dominance.py --mock

    # 5 yil backfill:
    python scripts/ingest_btc_dominance.py --days 1825

Yasaklar (data_engineer kontrati):
- Clip yapilmaz (modul icindeki 20-80% clip yalniz outlier guard, sentinel).
- Forward-fill yok.
- Onaysiz prod'a baglanmasin — once CEO approve gerekli.

Onay statusu: ONAYSIZ. Bu script yazildi, **calistirma karari CEO'ya kalir**.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))


def main():
    parser = argparse.ArgumentParser(description="BTC Dominance ingest (CoinGecko)")
    parser.add_argument("--days", type=int, default=1825,
                        help="Backfill gun sayisi (default 1825 = 5y)")
    parser.add_argument("--mock", action="store_true",
                        help="API'siz mock veri kullan (test amacli)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Detayli log")
    parser.add_argument("--dry-run", action="store_true",
                        help="Sadece kontrol — yazma yapma")
    args = parser.parse_args()

    print("=" * 60)
    print("BTC DOMINANCE INGEST")
    print(f"Mode: {'MOCK' if args.mock else 'LIVE'}, days={args.days}")
    print(f"Target: data/dominance.duckdb")
    print("=" * 60)

    if not args.mock and not args.dry_run:
        print()
        print("UYARI: Live API kullaniliyor. CoinGecko free tier rate limit'i:")
        print("  - 30 req/min")
        print(f"  - {args.days} gun icin ~{(args.days // 89) + 1} pencere = "
              f"~{((args.days // 89) + 1) * 12} saniye min sleep")
        print("  - Toplam tahmini sure: 3-15 dakika")
        print()

    if args.dry_run:
        print("DRY-RUN: islem yapilmiyor, plan dogrulandi.")
        print(f"  Hedef: data/dominance.duckdb")
        print(f"  Modul: src/price_action/data/dominance_ingest.py")
        print(f"  Yontem: fetch_and_store(days={args.days}, force_mock={args.mock})")
        return 0

    try:
        from price_action.data.dominance_ingest import (
            fetch_and_store, DominanceStore,
        )
    except ImportError as exc:
        print(f"ERROR: dominance_ingest modulu yuklenemedi: {exc}")
        print("Cozum: PYTHONPATH=src ile calistirin veya")
        print("       pip install -e . (proje root'unda)")
        return 1

    written = fetch_and_store(
        days=args.days,
        force_mock=args.mock,
        verbose=args.verbose,
    )

    store = DominanceStore()
    total = store.count()
    last_ts = store.last_ts()

    print()
    print(f"Yazildi    : {written} satir (bu run)")
    print(f"Toplam     : {total} satir (tum DB)")
    print(f"En son ts  : {last_ts}")

    if written == 0:
        print()
        print("UYARI: 0 satir yazildi.")
        print("  - API connectivity sorunu olabilir")
        print("  - --mock ile test edebilirsiniz")
        return 1

    # Manifest tetigi (data_engineer kontrati: her veri ingest'i sonrasi
    # quality manifest refresh edilmeli)
    print()
    print("OK Ingest tamam. Manifest yenilemek icin:")
    print("    python scripts/data_feature_coverage.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
