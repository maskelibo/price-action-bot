# Data Engineer Learning — 2026-05-13 Feature Coverage

> CEO brief 2026-05-12 (sec 4.4): EER-Score icin feature pipeline readiness.

## Yapilanlar
- `scripts/data_feature_coverage.py` — read-only feature coverage analyzer.
  Tum feature'lari taradi, hic clip/fill yapmadi, ham veri dokunulmamis.
- `data/quality/2026-05-13-feature-coverage.json` — manifest yazildi. Her
  feature icin `data_hash` (sha256[:16]) eklendi — reproducibility icin.
- `scripts/ingest_btc_dominance.py` — BTC.D fetch CLI. Mevcut modul
  `src/price_action/data/dominance_ingest.py` zaten DominanceStore + CoinGecko
  fetcher saglıyor; CLI sarmal yazildi. **Onaysiz calistirilmadi** (CEO onayi
  gerekli — data_engineer kontrati: yeni veri kaynagini onaysiz prod'a baglama).

## Bulgular (numerical)

| Feature | Status | Notlar |
|---|---|---|
| 1d OHLCV (11 sym, 5y) | warn | 10/11 OK (1834 satir, 0 gap). MATIC delisted 2024-09-10 (1229 satir). Survivorship icin korundu. |
| 1w OHLCV | ok | 2796 satir |
| 4h OHLCV | ok | 65700 satir, 2023-05-10'dan beri |
| 1m OHLCV | missing | Microstructure icin; paper trade'e gerekli **degil** (1d proxy yeterli) |
| BTC funding (00:00_only) | ok | 5475 satir total, 1825 saat=00 satir, **0 gap**, last=2026-05-12 |
| F&G daily | warn | 2000 satir, **1 gap** (2025-05-12), last=2026-05-12. Gap rate 0.05% — toleransli. |
| BTC dominance | **missing** | DB yok. Fetch modulu hazir, **ingest calismamis**. |
| ATR%, EMA200_streak, 90d_DD | compute_on_demand | regime.py icinde her cagirimda yeniden hesaplaniyor. Cache yok. EER 13x11 pencerede tekrarli compute olur — W2'de pickle cache eklenmeli. |

## En Kritik Eksik
**BTC dominance** — Researcher B HYP-2026-05-12-regime-btc-dominance-trend-veto
ve EER-Score `btc_dom_trend` bucket key bu veri olmadan calismaz.

- Fetch ETA: 3 saat (CoinGecko free 30 req/min, 5y backfill ~12 pencere x 12s = ~3 dakika ama 401 fallback'lerle 10-30 dk; 3 saat conservative).
- Mevcut `dominance_ingest.py` yontemi: `btc_mcap[t] / latest_btc_mcap * current_dom` — **yaklasiklik**. Free API'de total market cap tarihi yok. EER icin yeterli (trend sign onemli, absolute degil) ama "ground truth" degil.
- Onaylanırsa: `python scripts/ingest_btc_dominance.py --days 1825 -v`

## Reproducibility
- Manifest'te her dataset icin `data_hash` (SHA256[:16]).
- EER backtest'leri bu hash'i kayda alacak — `eer_v1_walkforward.py` icinde
  manifest'i okuyup `dataset_hashes` field'ina ekleyebilir.
- BTC OHLCV current hash: `06bf57797eede268` (1834 satir, 2021-05-01..2026-05-08).

## Yasaklara Uyum
- [x] Clip/winsorize YOK
- [x] Forward-fill YOK
- [x] MATIC delisted satirlari silinmedi (survivorship guard)
- [x] BTC.D fetch script onaysiz CALISTIRILMADI

## Notlar (Lab / Risk Officer'a)
- F&G 1 gun gap 2025-05-12 civari (alternative.me): EER bucket'inda
  o gun trade varsa "no_data" tier fallback gerekiyor.
- 1m OHLCV ihtiyaci paper trade icin **YOK** karari teyit edildi.
- 4h OHLCV mevcut (2023-05-10+); v0.8.2 lock'da kullanilmiyor ama envanterde.

## Sonraki Adim
1. CEO onayi -> `python scripts/ingest_btc_dominance.py --days 1825 -v` (W1 ici).
2. Sonra `data_feature_coverage.py` rerun -> EER-ready=True hedefi.
3. Derived feature cache (W2) — EER walk-forward maliyeti icin.
