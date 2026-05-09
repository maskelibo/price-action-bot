---
hypothesis_id: halving-cycle-phase
date: 2026-05-09
author: researcher-agent
status: candidate
priority: low
tags: [macro, btc, halving, cycle, position-sizing, regime]
depends_on: [engulfing_continuation]
---

# Hipotez: BTC Halving Döngüsü Fazı — Makro Boyutlandırma Filtresi

## Özet

BTC'nin 4 yıllık halving döngüsünü makro rejim feature'ı olarak kullanmak:
engulfing sinyallerinin risk tutarı ve kaldıraç faktörlerini döngü fazına göre
ölçeklendirmek. Faz bilgisi *deterministik* (tarihsel halving tarihleri kamu
bilgisi), lookahead yok, hiçbir bar-düzeyinde hesaplama gerektirmiyor.

---

## Motivasyon

Mikro/intraday hipotezler (H1–H17) bar seviyesinde kenar (edge) arar.
Bu hipotez farklı bir katmanda çalışır: *hangi makro iklimde* trade edildiği.
BTC halving'leri yaklaşık 4 yılda bir görülür; tarihsel örüntü:

| Dönem | Tanım | Tarihsel BTC Davranışı |
|-------|-------|------------------------|
| Phase A: 0-12 ay post-halving | Supply şoku anında | %200-700 bull (2013, 2017, 2021 analogları) |
| Phase B: 12-30 ay post-halving | Mid-cycle | Düzeltme/range/bear dönemi |
| Phase C: 30-45 ay post-halving | Erken pre-halving | Accumulation başlangıcı |
| Phase D: 45-48 ay post-halving | Yaklaşan halving | Tekrar toplanma ivmesi |

**Eğer** bu örüntü gerçekten var ve istatistiksel olarak robust ise,
Phase A'da risk büyütmek, Phase B'de küçültmek net pozitif beklenti katar.

---

## Teorik Temel

### Kaufman — Adaptive Risk per Trade
Kaufman (TSM, Adaptive Methods bölümü), risk tutarının sistemin *regime-aware*
metriklere göre modüle edilmesini önerir. Halving fazı, Kaufman'ın rolling Sharpe
/ rolling win-rate metriklerine alternatif / tamamlayıcı bir *harici* regime feature'ı.
Kaufman'ın "Cycle-based Sistemler" notu: "cycles exist but are unstable — use as
filter, not standalone." Bu tam olarak bu hipotezin pozisyonudur: standalone
değil, engulfing'in üstünde ek filtre.

### Grimes — Market Phase Model
Grimes 4-fazlı market phase modelini (Trend / Pullback / Consolidation / Breakout)
intraday/haftalık bar düzeyinde tanımlar; regime, setup'ın önünde filter olarak
durur. Bu hipotez aynı prensibi *makro* zaman dilimine taşır: halving döngüsü = makro
faz. Grimes'ın "regime is everything" uyarısı birebir uygulanır: hangi makro
iklimde olduğunuzu bilmeden bar-düzeyi setup'ı değerlendirmek eksik kalır.

---

## Halving Tarihleri (Sabit — Public Knowledge)

```
2012-11-28  (Block 210,000)
2016-07-09  (Block 420,000)
2020-05-11  (Block 630,000)
2024-04-19  (Block 840,000)  ← en son
2028-04-15  (Block 1,050,000 — tahmini, ±2 ay tolerans)
```

Bu tarihler *geçmiş veri* veya *iyi bilinen gelecek tahmini* olarak mevcut.
Lookahead bias *yoktur*: herhangi bir t anında o tarihe kadar olan tüm
halving'ler zaten kamuya açık bilgidir.

---

## Faz Tanımları

```
Faz A: 0-12 ay post-halving   → Aggressive  (risk *1.0, lev 1-5x)
Faz B: 12-30 ay post-halving  → Defensive   (risk *0.5, lev 1-3x)
Faz C: 30-45 ay post-halving  → Moderate    (risk *0.75, lev 1-3x)
Faz D: 45-48 ay post-halving  → Aggressive  (risk *1.0, lev 1-5x)
```

Geçiş sınırları ay bazlı (30.4375 gün/ay). Halving günü kendisi Phase A başlangıcıdır.

---

## Yapısal Avantajlar

1. **Deterministik**: Parametre yok, optimizasyon yok, overfitting riski minimum.
2. **Lookahead-free**: Geçmiş halving tarihleri zaten biliniyor; gelecek halving
   tahmini ise halving öncesi 6-18 ay boyunca blok zamanlamasından yüksek doğrulukla
   bilinebilir.
3. **Ekonomik mantık**: Arz şoku teorisi (PlanB, stock-to-flow) spekülatif olsa da
   *arz-azalma* mekanizması gerçektir. Bu hipotez S2F'yi onaylamak zorunda değil;
   sadece "tarihsel olarak post-halving dönemler bullish olma eğilimindeydi" gözlemini
   sizing'e bağlar.

---

## Kritik Zayıflıklar

### İstatistiksel Örneklem Problemi (ANA SORUN)

**4 halving × 4 faz = 16 sample.** Bu sayı, herhangi bir istatistiksel test için
çok küçüktür:

- p-değeri hesaplamak anlamlı değil (N < 20).
- Bir fazın "iyi" görünmesi tamamen şans eseri olabilir (tek bir 2017 veya
  2021 bull market o fazı hayatta tutar).
- Backtesting 2023-05 → 2026-05 penceresinde *yalnızca 2 fazı* (Phase B sonu +
  Phase A başlangıcı) kapsar. Bu tek bir halving döngüsü.

**Bu hipotez istatistiksel kanıt üretemez. Sonuçlar narrative-fit riski taşır.**

### Diğer Zayıflıklar

- **"Döngü bozulabilir"**: Kurumsal Bitcoin benimsenme, ETF'ler, macro-politika
  değişimleri 4 yıllık örüntüyü bozabilir. 2024-2025 çevriminde ETF girişleri
  halving öncesi Phase A benzeri davranış yarattı — döngü "öne çekildi."
- **Engulfing ile bağımsızlık?**: Eğer Phase A zaten bullish ise, engulfing
  sinyalleri Phase A'da zaten daha sık ve başarılı olabilir — sizin eklediğiniz
  *sadece* sizing. Ama Phase A'da size *büyütmek* zaten yüksek volatilite anlamına
  gelir; drawdown riski de artar.
- **Phase B'de zaten az sinyal**: Bear/range döneminde engulfing continuation zaten
  az sinyal üretir. Sizing'i de yarıya indirmek etkiyi iki kez küçültür.

---

## Backtest Kapsamı

### 3y Pencere: 2023-05 → 2026-05

| Dönem | Tarih | Faz |
|-------|-------|-----|
| 2023-05 → 2024-04-19 | ~11 ay | Phase C (erken pre-halving) |
| 2024-04-19 → 2025-04-19 | 12 ay | Phase A (post-halving bull) |
| 2025-04-19 → 2026-05 | ~13 ay | Phase A → Phase B geçişi |

Bu pencere Phase A boyunca 2024-2025 boğa piyasasını kapsıyor. Phase A'nın
agresif sizing ile yakalanması muhtemelen güçlü görünecek — ama bu büyük ölçüde
o spesifik bull cycle'dan kaynaklanır, genel geçer bir pattern'dan değil.

---

## Verdict Beklentisi (Pre-Backtest)

**DEFER bekleniyor** — olası sebepler:
- Phase A sizing artışı 2024-2025 bull'da görünür iyileşme sağlar.
- Ama istatistiksel anlamlılık kurulmaz (N=1 döngü, 16 global sample).
- "Narrative-fit" riski yüksek: 4 yıllık bir döngüde 1 gözlem kanıt değil.
- Sonraki halving (2028) civarında *out-of-sample* test edilebilir hale gelecek.

Eğer PROMOTE edilirse: yalnızca "Phase A agresif, Phase B defansif" kuralı
uygulanmalı; C/D fazları yeterli data olmadığından nötr tutulabilir.

---

## Uygulama Notları

- `compute_halving_phase(ts)` → deterministic, no lookahead
- `phase_to_size_factor(phase)` → A=1.0, B=0.5, C=0.75, D=1.0
- `apply_halving_phase_sizing(signals)` → Signal listesindeki metadata'ya
  `halving_phase` ve `halving_size_factor` ekler; `suggested_size_atr` ölçeklenir
- Engulfing stratejisi değiştirilmez (DO NOT MODIFY kuralı)

---

## Sonraki Adımlar

1. Backtest çalıştır → per-phase breakdown raporla
2. Engulfing solo vs engulfing+halving karşılaştır
3. Eğer Sharpe farkı > 0.2 VE DD düşüyorsa: DEFER (çok az sample, ama pozitif işaret)
4. 2028 halvinginden sonra out-of-sample doğrulama planı hazırla
