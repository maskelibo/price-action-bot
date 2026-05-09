---
hypothesis_id: perp-orderbook-imbalance
date: 2026-05-09
author: researcher_agent
status: forward_validation_pending
parent_strategy: engulfing_continuation
version: 1.0.0
tags: [microstructure, orderbook, imbalance, harris, perpetual, paper_trading, forward_validation]
backtest_possible: false
data_availability: live_only
forward_validation_start: 2026-05-09
forward_validation_end: 2026-06-06  # 4 hafta
---

# Hipotez: Perpetual Orderbook Imbalance — Microstructure Edge

## Motivasyon

Engulfing sinyalleri, fiyat aksiyonunu ölçmektedir; ancak fiyat aksiyonu geçmişe aittir.
**Gerçek zamanlı orderbook derinliği** ise o anki kurumsal pozisyonlanmayı gösterir.

Larry Harris'in microstructure çerçevesinde (Trading & Exchanges, 2003):
- Top-of-book ağırlıklı bid/ask dengesizliği, kısa vadeli fiyat baskısını öngörür.
- Bid tarafı ask tarafından belirgin şekilde büyükse, alıcılar daha agresif; fiyat yukarı kayar.
- Bu etki perpetual marjin piyasalarında spot'a kıyasla daha güçlüdür çünkü kaldıraçlı
  katılımcılar pozisyon değişikliklerini daha büyük lot boyutuyla yansıtır.

Mevcut `engulfing_continuation` stratejisi:
- Win rate: ~%50 baseline, Production A konfigürasyonunda +%68 yıllık
- Zayıflık: Engulfing kalıbı RETAIL tarafından görünür ve kolayca "fake" yaratılabilir.
  Büyük bir katılımcı tek bir kapanış mumunu şekillendirebilir.

**Mikro-yapı filtresi** bu sahte sinyalleri eleyebilir: eğer engulfing sinyali atıldığında
orderbook bid/ask imbalance sinyalle AYNI yönde ise — bu kurumsal akışın da aynı yönde
olduğunu gösterir. Retail şekillendirdiği mumun arkasında kurumsal destek yoksa imbalance
nötr veya karşı yönde kalır.

## Hipotez Özeti (Ana İddia)

> Engulfing sinyali + |orderbook_imbalance| > 0.6 (aynı yönde) kombinasyonu,
> tek başına engulfing sinyaline kıyasla win rate'i +%5–%10 artırır.

**Ölçüm birimi:** Win rate (realized_r_multiple > 0 olan trade oranı), 4 haftalık forward veri.

## Teorik Gerekçe

### Harris Microstructure Perspektifi
Harris (2003) orderbook imbalance'ı şöyle tanımlar:
```
imbalance = (bid_volume_top_N - ask_volume_top_N) / (bid_volume_top_N + ask_volume_top_N)
```
- Değer aralığı: [-1, +1]
- +1: tüm likidite bid tarafında → aşırı alım baskısı
- -1: tüm likidite ask tarafında → aşırı satım baskısı
- |imbalance| > 0.6 → anlamlı yönlü baskı (eşik, literatürde 0.5–0.7 arasında)

### Perpetual'a Özgü Güçlendirici Faktörler
1. **Funding rate mekanizması**: Perp long/short oranı dengesizleştiğinde funding rate
   bunu telafi eder. Büyük bid imbalance = long ağırlıklı = ileride funding long öder
   → kurumsal pozisyonlar daha büyük risk alıyor demektir.
2. **Kaldıraç etkisi**: Spot'a kıyasla lot başı daha büyük USD değer. Büyük kurumsal
   emir bir lot ile orderbook'ta çok daha görünür iz bırakır.
3. **Tick bazlı microstructure**: Spot'ta market maker arbitrajı çok hızlı imbalance'ı
   kapatır; perp'te funding arbitraj daha gecikmeli → imbalance sinyal değeri daha uzun süre kalır.

### Akademik Destek
- Gould et al. (2013), "Limit Order Books" — imbalance, 1-dakika ölçeğinde fiyat hareketi
  yönünü öngörüyor (R² ~0.08–0.15, küçük ama istatistiksel olarak anlamlı).
- Silantyev (2019), Binance perp datası üzerinde imbalance sinyalinin HFT dışı ölçeklerde
  de çalıştığını gösteriyor — 1m-5m window hala anlamlı.

## Veri Erişilebilirlik Analizi

| Kaynak | Maliyet | Mevcut mu? | Not |
|---|---|---|---|
| Binance REST `GET /api/v3/depth` | Ücretsiz | EVET | Real-time, top 20 level |
| CCXT `fetch_order_book(symbol, limit=20)` | Ücretsiz | EVET | REST wrapper |
| Binance WebSocket `@depth` | Ücretsiz | EVET | Delta güncellemeler |
| Binance historical orderbook | HAYIR | — | Yok (silinmiş) |
| Tardis.dev | ~$200+/ay | HAYIR | Paid, granular historical |
| Binance Data Portal (data.binance.vision) | Ücretsiz | KISMI | Günlük snapshot, tick yok |

**SONUÇ:** Gerçek zamanlı orderbook snapshot → MÜMKÜN VE ÜCRETSİZ.
Tarihsel orderbook backtesti → MÜMKÜN DEĞİL (ücretsiz erişimde yok).

**Pratikte yapılabilir olan:** Paper trading sırasında her sinyal anında orderbook
snapshot çekip log'a yaz. 4 hafta veri biriktikten sonra imbalance ile realized R-multiple
arasındaki korelasyonu ölç → forward validation.

## Uygulama Planı

### Bileşenler
1. **`src/price_action/data/orderbook_logger.py`** — Ana modül:
   - `fetch_orderbook_snapshot(symbol, venue, limit)` → ccxt REST çağrısı
   - `compute_imbalance(snapshot, top_n)` → [-1, +1] float
   - `log_signal_orderbook(signal_info, imbalance)` → DuckDB append
   - Tüm ağ hataları `except Exception` ile yutulur, crash olmaz

2. **`scripts/paper_trading_loop.py`** — Defansif hook:
   - Sinyal bulunduğunda `try: import orderbook_logger; ... except: pass`
   - Loop mantığını değiştirmez

3. **`tests/test_orderbook_logger.py`** — 6 birim testi

### DuckDB Tablo Şeması
```sql
CREATE TABLE orderbook_snapshots (
    snapshot_id    TEXT PRIMARY KEY,
    ts             TIMESTAMP WITH TIME ZONE NOT NULL,
    signal_ts      TIMESTAMP WITH TIME ZONE,
    venue          TEXT NOT NULL,
    symbol         TEXT NOT NULL,
    direction      TEXT,           -- sinyal yönü: 'long' | 'short'
    top_n          INT,
    bid_volume     DOUBLE,
    ask_volume     DOUBLE,
    imbalance      DOUBLE,         -- (bid - ask) / (bid + ask)
    raw_bids       TEXT,           -- JSON: [[price, size], ...]
    raw_asks       TEXT,           -- JSON: [[price, size], ...]
    signal_id      TEXT,           -- paper trade fingerprint
    pattern_id     TEXT,
    confidence     DOUBLE,
    fetch_latency_ms DOUBLE
)
```

## Test Planı (Forward Validation — 4 Hafta)

### Veri Toplama Takvimi
- **Başlangıç:** 2026-05-09 (bugün, ilk paper loop çalıştıktan sonra)
- **Bitiş:** 2026-06-06 (4 hafta)
- **Frekans:** Her engulfing sinyali tetiklendiğinde (günlük 1d bar kapanışı, ~00:05 UTC)
- **Hedef:** min 30 snapshot (10 sembol × ~3 sinyal/hafta beklenti)

### Analiz Soruları (4 Hafta Sonrası)
1. |imbalance| > 0.6 olduğunda win rate vs olmadığında win rate
2. Imbalance yönü sinyal yönüyle eşleştiğinde vs eşleşmediğinde R-multiple dağılımı
3. Imbalance magnitude ile |R-multiple| arasında korelasyon var mı?
4. Hangi sembollerde imbalance daha "gürültüsüz" (SOL? BTC?)

### Başarı Kriteri
- n ≥ 30 trade (istatistiksel minimum)
- imbalance-aligned trades win rate ≥ baseline + %5 (örn: %55 vs %50)
- Cohen's h ≥ 0.2 (küçük ama anlamlı effect size)
- p-value < 0.10 (tek kuyruklu Fisher exact, n=30 için gevşek eşik)

## Risk ve Eleştirel Değerlendirme

### Temel Soru: Gerçek Kurumsal Akış mı, Retail Noise mu?

**Lehine argümanlar (kurumsal akış):**
- Binance perp top-5 seviyesinde minimum lot değeri genellikle $50k–$500k
- Bu büyüklükte emirler bireysel retail trader'dan gelmez
- Market maker hedge emirleri bu seviyelerde yoğunlaşır
- HFT arbitraj orderbookun "yanlış" imbalance'ını milisaniyeler içinde kapatır; 1m snapshot
  hala orada duruyorsa "gerçek" pozisyonlanma anlamına gelir

**Aleyhine argümanlar (noise):**
- Spoofing: büyük limit emirler görünür olup anında iptal edilir. REST snapshot'la yakalanabilir.
- Layering: aynı market maker birden fazla seviyede emir dizer, sahte derinlik yaratır.
- 1d bar kapanışında orderbook microstructure, 1d fiyat hareketini öngörme açısından
  çok "kısa vadeli" bilgi içeriyor olabilir.
- 1m snapshot yetersiz; ideal olan 1h ortalaması (500ms polling → aggregated 1h imbalance).

**Tarafsız değerlendirme:**
Gould et al. ve Silantyev verisi küçük ama anlamlı bir edge gösterse de bu çalışmalar
1m-5m PRICE öngörüsü için yapılmıştır, 1d trade win rate için değil. Transfer edilebilirliği
**bilinmiyor** — forward validation'ın amacı tam olarak bu.

**Muhtemel en iyi senaryo:** Imbalance, engulfing'in "gerçekten güçlü mü sahte mi" sorusunu
cevaplamanın PROXY'si. %50 değil %70 doğrulukla bile bir eleme kriteri olarak değerlidir.

### Diğer Riskler
1. **Lookahead yok:** Orderbook log tamamen prospektif (sinyal anında gerçek zamanlı).
2. **Network hataları:** Rate limit / exchange downtime → skip, no crash (savunmacı logging).
3. **Sample size:** 4 haftada 30 trade çok iyimser olabilir; 10–15 trade gerçekçi.
   n<20 ise istatistiksel sonuç çıkarmak güç → süre 8 haftaya uzatılabilir.
4. **Stale snapshot:** Sinyal hesaplandıktan sonra orderbook 1-2 dakika içinde değişir.
   Snapshot timestamp'i loglanıyor, gecikme takip edilebilir.

## VERDICT Kriteri (6 Hafta Sonra)

| Sonuç | Karar |
|---|---|
| n≥30, imbalance-aligned WR > baseline+%5, p<0.10 | ACTIVATE: confidence score'a imbalance terimi ekle |
| n≥30, anlamsız fark, p>0.10 | REJECT: imbalance'ı confidence formula'dan dışla |
| n<20 | EXTEND: 8. haftaya uzat |
| Spoof indicator yüksek (5+ snapshot'ta spoofing şüphesi) | PAUSE: metodoloji revize |

## Gelecek Adım: Backtest Hazırlığı (Paid Data Alındığında)

Tardis.dev Level-2 snapshot paketi satın alındığında (~$200/ay, Binance USDT-perp):
- `orderbook_logger.py`'daki `OrderbookSnapshot` Pydantic modeli aynı şema
- `backtest_imbalance.py` — historik snapshot CSV → compute_imbalance() → sinyal overlay
- Walk-forward ile 3 yıl backtest mümkün hale gelir

**Modül tasarımı bu gelecek backtesti destekleyecek şekilde yapılandırıldı.**
