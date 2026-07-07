# DÜNYA KLASMANI YOL HARİTASI — "En İyi Trade-Bot Şirketi" Boşluk Analizi

**Tarih:** 2026-07-07 · **Referans çerçeve:** çok-stratejili sistematik fonlar (Renaissance/Two Sigma/Jane Street sınıfının *yapısal* dersleri — ölçek değil, disiplin kopyalanır)

## 1. Dürüst konum tespiti

| Katman | Dünya klasmanı ne yapar | Bizde durum | Boşluk |
|---|---|---|---|
| Risk/execution disiplini | Bypass edilemez limitler, DMS, mutabakat | ✅ VAR — production seviyesi (PROJE_RAPORU 8/10) | Küçük (FULL_AUDIT D2-D4) |
| **Alfa fabrikası** | Sürekli, ÇOK-modaliteli sinyal araştırması; yüzlerce bağımsız küçük edge | ❌ 4 detektör × tek modalite (fiyat); 41 günde 0 terfi | **EN BÜYÜK boşluk** |
| Veri tedariki | Onlarca kaynak: tick, OI, funding, likidasyon, on-chain, alternatif | Kod hazır, veri YENİ bağlanıyor (dominance/sentiment bugün doldu) | Büyük ama ucuz |
| Portföy inşası | Edge'ler portföy-optimizasyonla birleşir (corr/Kelly/vol-target) | Tek bot, 2 kol, eşit ağırlık | Büyük (ama önce edge lazım) |
| Execution araştırması | Slippage/mikroyapı Ar-Ge'si, maker/taker optimizasyonu | Statik 25bps limit; paper'da 0bps (ölçümsüz) | Orta (canlıda kritikleşir) |
| Kapasite/ölçek | Sermaye-kapasite modeli per-strateji | Yok | Erken (canlı sonrası) |
| Altyapı | Çok-düğüm, failover, misfire telafisi | Tek Mac, kaçan-cron kanıtlı | Büyük (bilinen) |
| **Değerlendirme kültürü** | Her model/insan çıktısı ölçülür | LLM çıktısı ölçümsüz (~$200/ay kör harcama) | Büyük |

**Bir cümlede:** Savunmamız fon seviyesinde, hücumumuz hobi seviyesinde; dünya klasmanına giden yol **hücum hattını (veri × sinyal × portföy) endüstrileştirmekten** geçiyor.

## 2. Kurulacak departmanlar / ajanlar (öncelik sırasıyla)

### D1 — Feature Factory *(BUGÜN kuruldu — OTONOMI-1)*
`feature_sweep` motoru = bu departmanın v1'i. **Genişleme yolu:** feature kütüphanesini 13→50+ (OI, dominance, sentiment, cross-sectional rank, event-time), TF'leri 1h→{4h,1d}, hedefleri vol-normalize R'ye çevir. Sahip: deterministik kod + researcher tüketici. *Yeni LLM ajanı GEREKMEZ.*

### D2 — Signal Bridge Engineer *(1-2 gün, en yüksek kaldıraç)*
PROGRAM_V2 AİLE-1: `hypothesis_runner`'a `new_strategy` → `engine.run(StrategyClass, tf)` köprüsü. %82 NOT_EXECUTABLE'ı eritir; ~75 hazır strateji sınıfını otonom test edilebilir yapar. *Tek seferlik mühendislik; ajan değil.*

### D3 — Portfolio Construction Agent *(edge sayısı ≥3 olunca)*
Bugünkü portfolio_manager deterministik sıralayıcı; dünya klasmanı versiyonu: corr-matrisi + vol-target + kısıtlı optimizasyon ile strateji-ağırlık önerisi, haftalık. Girdi: per-strateji canlı R serileri (journal'da var). Model: Sonnet yeterli. Kapı: Principal onaysız ağırlık değişmez (mevcut kural).

### D4 — Execution Research *(mikro-canlı öncesi şart)*
Paper'da slippage 0bps = ölçümsüz. Mikro-canlıda ilk 100 emirde gerçek slippage/latency/maker-oranı raporu; 25bps limitin ve %57bps varsayımının kalibrasyonu. Mevcut execution_chief persona'sına GÖREV eklenir; yeni ajan gerekmez.

### D5 — Data Vendor Scout *(aylık, market_scout'a ek görev)*
OI tarihsel (Coinalyze/laevitas), likidasyon feed, tick verisi maliyet/fayda taraması. Çıktı: "hangi veri kaynağı kaç $/ay, hangi aileyi açar".

### D6 — Model Validation (LLM Eval) *(fabrika ölçümü)*
20-30 örneklik golden set + haftalık judge koşusu: hipotez kalitesi, rapor doğruluğu, persona-uyum skoru. PROJE_RAPORU önerisiyle aynı; artifact metadata'sı (P1-2) altyapıyı hazırladı.

### KURULMAYACAKLAR (bilinçli)
- **HFT/mikrosaniye execution** — bizim ölçek/altyapıda negatif beklenti.
- **Duygu-analizi Twitter botu** — sinyal/gürültü kanıtı olmadan modalite eklemiyoruz; F&G ile başla (bugün bağlandı), ölç, sonra genişle.
- **Ayrı "ML departmanı"** — meta_labeling.py mevcut; ML, Feature Factory'nin tüketicisi olarak büyür, ayrı imparatorluk olarak değil.

## 3. "Bizim sistem neyi eksik yapıyor" — 5 kök alışkanlık

1. **Üretmeden önce ölçmüyorduk** → hipotezler temadan geliyordu, piyasadan değil. *(Bugün değişti: sweep→pulse hattı.)*
2. **Raf ile motor kopuk** → 75 strateji sınıfı yazılmış, 4'ü koşabiliyor. *(D2 köprüsü.)*
3. **Keşif sonuçları tüketicisiz** → tf_exploration/market_scout raporları kimsenin okumadığı markdown'a ölüyordu. *(Sweep adayları artık pulse'ın girdisi; aynı desen TF/scout'a uygulanacak.)*
4. **Tek modalite tüneli** → fiyat-only doygunluğu 3 kez bağımsız kanıtlandı ama funding 5 yıldır diskte bağlantısız duruyordu.
5. **Fabrika verimi ölçümsüz** → token harcandı, kalite ölçülmedi. *(Hard-cap + metadata girdi; eval harness sırada.)*

## 4. Sıralı kuruluş takvimi

| Ay | Kurulum | Başarı ölçütü |
|---|---|---|
| **Ay 1** (Tem) | D1 genişletme + D2 köprüsü + PROGRAM_V2 H1-H4 | ≥1 yeni strateji ailesi gerçek backtest'te GO/RED aldı; sweep 4h/1d'ye genişledi |
| **Ay 2** | D6 eval harness + D5 ilk tarama + VPS failover (PROJE_RAPORU yapısal-1) | LLM kalite skoru baseline'da; kaçan-cron sınıfı kapandı |
| **Ay 3** | D3 portföy (edge≥3 ise) + D4 hazırlık; GO/NO-GO penceresi doluyor | Çok-kollu portföy önerisi ilk kez optimizasyonla üretildi |
| Sürekli | Aylık: bu dokümanın skor tablosu güncellenir | Boşluk sütunu daralıyor mu? |
